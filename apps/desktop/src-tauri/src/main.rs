// Release builds on Windows must not open a console window behind the app.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod bootstrap;

use bootstrap::{BootstrapState, KernelProcess, Progress, Stage};
use serde::Serialize;
use tauri::{Emitter, Manager, RunEvent, WindowEvent};

#[derive(Serialize)]
struct Backend {
    /// None until the kernel is reachable. The frontend must not issue API
    /// calls before this is populated.
    api_port: Option<u16>,
    api_base_url: Option<String>,
    version: &'static str,
}

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

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_opener::init())
        .manage(BootstrapState::default())
        .manage(KernelProcess::default())
        .invoke_handler(tauri::generate_handler![
            backend,
            bootstrap_progress,
            database_log
        ])
        .setup(|app| {
            let handle = app.handle().clone();
            // Bootstrap off the UI thread: initdb on a first run takes seconds
            // and must not freeze the window it is reporting progress to.
            std::thread::spawn(move || {
                if let Err(error) = bootstrap::run(&handle) {
                    let _ = handle.emit(
                        bootstrap::BOOTSTRAP_EVENT,
                        Progress {
                            stage: Stage::Failed,
                            message: "Atlas could not start".to_string(),
                            first_run: false,
                            detail: Some(error.to_string()),
                        },
                    );
                }
            });
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
        }
    }
}
