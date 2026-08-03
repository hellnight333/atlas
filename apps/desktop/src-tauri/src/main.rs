// Release builds on Windows must not open a console window behind the app.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod bootstrap;
mod startup_log;

use std::sync::Mutex;

use bootstrap::{BootstrapState, KernelProcess, Progress};
use serde::Serialize;
use startup_log::StartupLog;
use tauri::{Manager, RunEvent, WindowEvent};

#[derive(Serialize)]
struct Backend {
    /// None until the kernel is reachable. The frontend must not issue API
    /// calls before this is populated.
    api_port: Option<u16>,
    api_base_url: Option<String>,
    version: &'static str,
}

/// Guards against two bootstrap sequences running at once, which the Retry
/// button on the diagnostics screen makes possible.
#[derive(Default)]
struct BootstrapRunning(Mutex<bool>);

/// Where the frontend should send API calls.
///
/// The port is chosen at runtime, so it cannot be baked into the bundle.
#[tauri::command]
fn backend(state: tauri::State<'_, BootstrapState>) -> Backend {
    let port = *state.api_port.lock().unwrap();
    Backend {
        api_port: port,
        api_base_url: port.map(|p| format!("http://127.0.0.1:{p}")),
        version: env!("CARGO_PKG_VERSION"),
    }
}

/// The current boot stage, for a frontend that mounted after an event fired.
#[tauri::command]
fn bootstrap_progress(state: tauri::State<'_, BootstrapState>) -> Option<Progress> {
    state.progress.lock().unwrap().clone()
}

/// Tail of the PostgreSQL log, for the troubleshooting panel.
#[tauri::command]
fn database_log(state: tauri::State<'_, BootstrapState>, lines: Option<usize>) -> Option<String> {
    let dir = state.pg_data_dir.lock().unwrap().clone()?;
    bootstrap::postgres_log(&dir, lines.unwrap_or(200))
}

/// Let the webview write into the same startup log as the shell.
///
/// Without this the log stops at "kernel: ready" and says nothing about whether
/// the UI ever rendered — which is the half that was actually failing.
#[tauri::command]
fn log_startup(log: tauri::State<'_, StartupLog>, message: String) {
    log.record("ui", &message);
}

/// Tail of `logs/startup.log`.
#[tauri::command]
fn startup_log(log: tauri::State<'_, StartupLog>, lines: Option<usize>) -> Option<String> {
    log.tail(lines.unwrap_or(300))
}

/// Everything a user could reasonably be asked to send when Atlas will not
/// start, assembled into one block of text they can paste.
#[tauri::command]
fn diagnostic_report(app: tauri::AppHandle) -> String {
    let mut out = String::new();
    out.push_str(&format!("Atlas {}\n", env!("CARGO_PKG_VERSION")));
    out.push_str(&format!(
        "platform: {} {}\n",
        std::env::consts::OS,
        std::env::consts::ARCH
    ));

    if let Some(state) = app.try_state::<BootstrapState>() {
        let stage = state.progress.lock().ok().and_then(|slot| slot.clone());
        match stage {
            Some(progress) => {
                let detail = progress
                    .detail
                    .as_deref()
                    .map(|d| format!(" ({d})"))
                    .unwrap_or_default();
                out.push_str(&format!(
                    "stage: {:?} — {}{}\n",
                    progress.stage, progress.message, detail
                ));
            }
            None => out.push_str("stage: not started\n"),
        }
        let dir = state.data_dir.lock().ok().and_then(|slot| slot.clone());
        out.push_str(&format!(
            "data directory: {}\n",
            dir.map(|d| d.display().to_string())
                .unwrap_or_else(|| "not resolved".into())
        ));
        let api = state.api_port.lock().ok().and_then(|slot| *slot);
        out.push_str(&format!(
            "api port: {}\n",
            api.map(|p| p.to_string())
                .unwrap_or_else(|| "not assigned".into())
        ));
    }

    let section = |out: &mut String, title: &str, body: Option<String>| {
        out.push_str(&format!("\n--- {title} ---\n"));
        out.push_str(&body.unwrap_or_else(|| "(not available)".into()));
        out.push('\n');
    };

    if let Some(log) = app.try_state::<StartupLog>() {
        section(&mut out, "startup.log", log.tail(200));
    }
    if let Some(state) = app.try_state::<BootstrapState>() {
        let dir = state.data_dir.lock().ok().and_then(|slot| slot.clone());
        section(
            &mut out,
            "kernel.log",
            dir.and_then(|d| bootstrap::tail_file(&d.join("logs").join("kernel.log"), 120)),
        );
        let pg = state.pg_data_dir.lock().ok().and_then(|slot| slot.clone());
        section(
            &mut out,
            "postgres server.log",
            pg.and_then(|d| bootstrap::postgres_log(&d, 80)),
        );
    }

    out
}

/// Reveal the log directory in the user's file manager.
#[tauri::command]
fn open_log_folder(app: tauri::AppHandle) -> Result<(), String> {
    use tauri_plugin_opener::OpenerExt;

    let dir = app
        .try_state::<BootstrapState>()
        .and_then(|state| state.data_dir.lock().ok().and_then(|slot| slot.clone()))
        .ok_or_else(|| "Atlas has not chosen a data directory yet.".to_string())?;
    let logs = dir.join("logs");
    app.opener()
        .open_path(logs.display().to_string(), None::<&str>)
        .map_err(|e| e.to_string())
}

/// Move a damaged database aside and start over.
///
/// Offered on the diagnostics screen only when the database is the thing that
/// is broken. Destructive in effect, so it is never automatic: a person has to
/// ask for it, having been told what it does.
#[tauri::command]
fn reset_database(app: tauri::AppHandle) -> Result<String, String> {
    let dir = app
        .try_state::<BootstrapState>()
        .and_then(|state| state.data_dir.lock().ok().and_then(|slot| slot.clone()))
        .ok_or_else(|| "Atlas has not chosen a data directory yet.".to_string())?;

    shutdown(&app);
    let archived = bootstrap::reset_database(&dir).map_err(|e| e.to_string())?;
    bootstrap::log(
        &app,
        &format!("database reset; old one kept at {}", archived.display()),
    );

    retry_bootstrap(app)?;
    Ok(archived.display().to_string())
}

/// Run the boot sequence again after a failure.
#[tauri::command]
fn retry_bootstrap(app: tauri::AppHandle) -> Result<(), String> {
    {
        let running = app.state::<BootstrapRunning>();
        let mut flag = running.0.lock().map_err(|_| "retry is unavailable")?;
        if *flag {
            return Err("Atlas is already starting.".into());
        }
        *flag = true;
    }
    // Anything still alive from the failed attempt has to go first, or the new
    // attempt inherits its port and its lock file.
    shutdown(&app);
    if let Some(state) = app.try_state::<KernelProcess>() {
        if let Ok(mut slot) = state.exited.lock() {
            *slot = None;
        }
    }
    bootstrap::log(&app, "retry requested from the diagnostics screen");
    spawn_bootstrap(app);
    Ok(())
}

/// Run the boot sequence on a background thread and report a failure to the UI.
fn spawn_bootstrap(handle: tauri::AppHandle) {
    std::thread::spawn(move || {
        let result = bootstrap::run(&handle);
        if let Some(running) = handle.try_state::<BootstrapRunning>() {
            if let Ok(mut flag) = running.0.lock() {
                *flag = false;
            }
        }
        if let Err(error) = result {
            bootstrap::log(&handle, &format!("FAILED: {error}"));
            // Stores as well as emits, so a webview that mounts after the
            // failure still finds it instead of waiting out the boot deadline.
            bootstrap::report_failure(&handle, error.to_string());
        }
    });
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_opener::init())
        .manage(BootstrapState::default())
        .manage(KernelProcess::default())
        .manage(StartupLog::default())
        .manage(BootstrapRunning::default())
        .invoke_handler(tauri::generate_handler![
            backend,
            bootstrap_progress,
            database_log,
            log_startup,
            startup_log,
            diagnostic_report,
            open_log_folder,
            retry_bootstrap,
            reset_database
        ])
        .setup(|app| {
            let handle = app.handle().clone();
            if let Some(log) = handle.try_state::<StartupLog>() {
                log.record("shell", "process started");
            }
            if let Some(running) = handle.try_state::<BootstrapRunning>() {
                if let Ok(mut flag) = running.0.lock() {
                    *flag = true;
                }
            }
            // Bootstrap off the UI thread: initdb on a first run takes seconds
            // and must not freeze the window it is reporting progress to.
            spawn_bootstrap(handle);
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { .. } = event {
                shutdown(window.app_handle());
            }
        })
        .build(tauri::generate_context!())
        .expect("failed to start Atlas")
        .run(|app, event| {
            // Both are handled deliberately. On macOS, quitting from the Dock
            // or the menu does not always produce ExitRequested, and the app
            // would exit leaving PostgreSQL and the kernel running — a user
            // who quits Atlas should not still be paying for it in RAM.
            // Exit is the last event before the process goes away.
            match event {
                RunEvent::ExitRequested { .. } | RunEvent::Exit => shutdown(app),
                _ => {}
            }
        });
}

/// Stop the kernel, then the database. Order matters: killing PostgreSQL from
/// under a live kernel produces connection errors in the log that look like a
/// fault when they are only a shutdown.
///
/// Idempotent, because it can be reached from a window close, an exit request
/// and the final exit event in the same quit.
fn shutdown(app: &tauri::AppHandle) {
    if let Some(kernel) = app.try_state::<KernelProcess>() {
        kernel.kill();
    }
    if let Some(state) = app.try_state::<BootstrapState>() {
        let bin = state.pg_bin_dir.lock().unwrap().clone();
        let data = state.pg_data_dir.lock().unwrap().clone();
        if let (Some(bin), Some(data)) = (bin, data) {
            bootstrap::stop_postgres(&bin, &data);
        }
        if let Some(dir) = state.data_dir.lock().unwrap().clone() {
            bootstrap::clear_kernel_pid(&dir);
            // Last, and only if it is ours. A lock left behind is not fatal --
            // the next launch checks liveness -- but leaving one is untidy and
            // makes the next start log a recovery it did not need.
            bootstrap::release_instance_lock(&dir);
        }
    }
}
