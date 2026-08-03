//! Bringing Atlas up on a machine that has nothing installed.
//!
//! An installed Atlas has no shell, no DBA and no Python. This module owns the
//! sequence that a developer would otherwise run by hand:
//!
//! 1. Pick a data directory (per-user, or beside the binary when portable).
//! 2. `initdb` the bundled PostgreSQL, once, on first run.
//! 3. Start PostgreSQL on a free loopback port.
//! 4. Start the packaged kernel, which creates its own database and serves.
//! 5. Poll `/health` until the API answers.
//!
//! Every step reports progress, because a first run does real work — `initdb`
//! alone takes a few seconds — and a silent window looks like a hang.
//!
//! Shutdown runs in reverse and is best-effort: PostgreSQL is stopped with
//! `pg_ctl stop -m fast` so the next start does not have to run crash
//! recovery.

use std::fs;
use std::io::{BufRead, BufReader};
use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager};

use crate::startup_log::StartupLog;

/// How long the kernel gets to answer `/health` before we call it failed.
///
/// Generous because a first run on a cold machine has to import a PyInstaller
/// bundle from disk. The window does not sit silent for this long -- the UI
/// gives up on its own after 30s and offers diagnostics.
const KERNEL_READY_TIMEOUT: Duration = Duration::from_secs(90);

/// Event name the frontend listens on for boot progress.
pub const BOOTSTRAP_EVENT: &str = "atlas://bootstrap";

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Stage {
    Starting,
    PreparingStorage,
    InitialisingDatabase,
    StartingDatabase,
    StartingKernel,
    WaitingForKernel,
    Ready,
    Failed,
}

#[derive(Debug, Clone, Serialize)]
pub struct Progress {
    pub stage: Stage,
    pub message: String,
    /// True only on the run that creates the data directory. The UI uses this
    /// to explain why the first launch is slower than every later one.
    pub first_run: bool,
    pub detail: Option<String>,
}

/// Everything the app needs to know about the running backend.
#[derive(Debug, Default)]
pub struct BootstrapState {
    pub api_port: Mutex<Option<u16>>,
    pub pg_port: Mutex<Option<u16>>,
    pub pg_data_dir: Mutex<Option<PathBuf>>,
    pub pg_bin_dir: Mutex<Option<PathBuf>>,
    pub data_dir: Mutex<Option<PathBuf>>,
    pub progress: Mutex<Option<Progress>>,
}

#[derive(Debug)]
pub struct BootstrapError(pub String);

impl std::fmt::Display for BootstrapError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl std::error::Error for BootstrapError {}

fn fail(message: impl Into<String>) -> BootstrapError {
    BootstrapError(message.into())
}

/// Record a boot failure so a window that has not mounted yet can still find it.
///
/// Emitting the event is not enough. Bootstrap can fail in well under a second
/// -- an unwritable data directory fails almost immediately -- while the webview
/// takes longer than that to load. The event fires into an empty room, and the
/// frontend, which asks for the current stage when it mounts, would be told the
/// last stage that was *stored* and sit waiting for a sequence that already
/// died. Storing it is what makes the diagnostics screen appear at once.
pub fn report_failure(app: &AppHandle, detail: String) {
    report(
        app,
        Stage::Failed,
        "Atlas could not start",
        false,
        Some(detail),
    );
}

/// Write one line to `logs/startup.log`.
pub fn log(app: &AppHandle, message: &str) {
    if let Some(state) = app.try_state::<StartupLog>() {
        state.record("shell", message);
    }
}

fn report(app: &AppHandle, stage: Stage, message: &str, first_run: bool, detail: Option<String>) {
    log(
        app,
        &match &detail {
            Some(detail) => format!("stage={stage:?} {message} ({detail})"),
            None => format!("stage={stage:?} {message}"),
        },
    );

    let progress = Progress {
        stage,
        message: message.to_string(),
        first_run,
        detail,
    };
    if let Some(state) = app.try_state::<BootstrapState>() {
        if let Ok(mut slot) = state.progress.lock() {
            *slot = Some(progress.clone());
        }
    }
    // A failed emit means no window is listening yet, which is not fatal --
    // the frontend asks for the current stage when it mounts.
    let _ = app.emit(BOOTSTRAP_EVENT, progress);
}

/// Ask the OS for a free loopback port by binding one and letting it go.
///
/// There is an unavoidable race between releasing the port and the child
/// binding it. Fixed ports are worse: two Atlas installs, or anything else
/// already on 5432, would collide every time instead of rarely.
fn free_port() -> Result<u16, BootstrapError> {
    let listener = TcpListener::bind("127.0.0.1:0")
        .map_err(|e| fail(format!("could not reserve a local port: {e}")))?;
    let port = listener
        .local_addr()
        .map_err(|e| fail(format!("could not read the reserved port: {e}")))?
        .port();
    drop(listener);
    Ok(port)
}

/// Where Atlas keeps its data.
///
/// `ATLAS_DATA_DIR` wins, so a portable install can keep everything beside the
/// executable. Otherwise the platform's per-user application data directory.
fn resolve_data_dir(app: &AppHandle) -> Result<PathBuf, BootstrapError> {
    if let Ok(dir) = std::env::var("ATLAS_DATA_DIR") {
        if !dir.trim().is_empty() {
            return Ok(PathBuf::from(dir));
        }
    }
    app.path()
        .app_data_dir()
        .map_err(|e| fail(format!("no writable application data directory: {e}")))
}

/// Locate the bundled PostgreSQL binaries.
///
/// `resource_dir()` alone is not enough. It is correct for an installed app --
/// `Atlas.app/Contents/Resources` on macOS, the mounted AppDir in an AppImage,
/// the executable's directory on Windows -- but on Linux it resolves to
/// `/usr/lib/atlas-desktop` for a plain binary, which is not where a portable
/// archive unpacked into a user's home directory keeps anything.
///
/// So the executable's own directory is searched too, and every location tried
/// is written to the startup log. A missing database is then a named path
/// rather than a mystery.
fn resolve_postgres_bin(app: &AppHandle) -> Result<PathBuf, BootstrapError> {
    let mut candidates: Vec<PathBuf> = Vec::new();

    if let Ok(dir) = app.path().resource_dir() {
        candidates.push(dir.join("postgres"));
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            // Portable layout: the tree sits beside the executable, which is
            // also where Tauri writes it next to an unbundled build.
            candidates.push(dir.join("postgres"));
            candidates.push(dir.join("resources").join("postgres"));
        }
    }

    for candidate in &candidates {
        let bin = candidate.join("bin");
        if bin.join(postgres_exe("pg_ctl")).exists() {
            return Ok(bin);
        }
        log(app, &format!("postgres not at {}", bin.display()));
    }

    Err(fail(format!(
        "the bundled PostgreSQL is missing. Looked in: {}. A packaged Atlas should \
         ship it; for a development build run infra/packaging/fetch_postgres.py.",
        candidates
            .iter()
            .map(|c| c.join("bin").display().to_string())
            .collect::<Vec<_>>()
            .join(", ")
    )))
}

fn postgres_exe(name: &str) -> String {
    if cfg!(windows) {
        format!("{name}.exe")
    } else {
        name.to_string()
    }
}

/// True when this data directory has never been initialised.
fn needs_initdb(pg_data: &Path) -> bool {
    !pg_data.join("PG_VERSION").exists()
}

fn run_initdb(bin_dir: &Path, pg_data: &Path) -> Result<(), BootstrapError> {
    // A fresh cluster is created with trust auth on loopback only. There is no
    // password because there is no network exposure: PostgreSQL is started
    // bound to 127.0.0.1 and is never advertised beyond this machine.
    let output = Command::new(bin_dir.join(postgres_exe("initdb")))
        .arg("-D")
        .arg(pg_data)
        .args(["-U", "atlas", "--auth=trust", "-E", "UTF8"])
        .output()
        .map_err(|e| fail(format!("could not run initdb: {e}")))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(fail(format!(
            "initdb failed: {}",
            stderr.lines().last().unwrap_or("no output")
        )));
    }
    Ok(())
}

/// Where the running kernel's pid is recorded, so a later run can clean up
/// after a crash.
fn kernel_pid_file(data_dir: &Path) -> PathBuf {
    data_dir.join("kernel.pid")
}

/// Kill a kernel left behind by a previous run.
///
/// Nothing in this process can survive `SIGKILL` or a power cut, so a crashed
/// Atlas leaves its kernel orphaned (reparented to init) holding a port and
/// a few hundred megabytes. No in-process handler can prevent that -- it can
/// only be cleaned up by whoever starts next.
///
/// The pid is matched against the recorded file rather than by process name,
/// so this can never kill an unrelated program that happens to be called
/// something similar, or a second Atlas the user started deliberately.
fn reclaim_kernel(data_dir: &Path) {
    let pid_file = kernel_pid_file(data_dir);
    let Ok(contents) = fs::read_to_string(&pid_file) else {
        return;
    };
    if let Ok(pid) = contents.trim().parse::<u32>() {
        kill_tree(pid);
    }
    let _ = fs::remove_file(&pid_file);
}

/// Stop anything still holding this data directory from a previous run.
///
/// Without this, Atlas starts exactly once. If the app is force-quit, crashes,
/// or is killed by the OS, our shutdown handler never runs and PostgreSQL is
/// left alive holding `postmaster.pid`. The next launch then dies with
/// "lock file postmaster.pid already exists" and Atlas never starts again
/// until the user finds and kills the process by hand.
///
/// `pg_ctl stop` handles both cases: a live orphan is shut down cleanly, and a
/// stale pid file whose process is gone reports "no server running", which is
/// not an error here.
///
/// This treats the data directory as exclusively ours. Two copies of Atlas
/// sharing one data directory is already unsupported -- PostgreSQL itself
/// refuses it -- so reclaiming it is the behaviour that makes recovery work.
fn reclaim_data_dir(bin_dir: &Path, pg_data: &Path) {
    if !pg_data.join("postmaster.pid").exists() {
        return;
    }
    let _ = Command::new(bin_dir.join(postgres_exe("pg_ctl")))
        .arg("-D")
        .arg(pg_data)
        .args(["-m", "fast", "-w", "stop"])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
}

fn start_postgres(bin_dir: &Path, pg_data: &Path, port: u16) -> Result<(), BootstrapError> {
    reclaim_data_dir(bin_dir, pg_data);
    let log = pg_data.join("server.log");
    let output = Command::new(bin_dir.join(postgres_exe("pg_ctl")))
        .arg("-D")
        .arg(pg_data)
        .arg("-l")
        .arg(&log)
        .arg("-o")
        .arg(format!("-p {port} -h 127.0.0.1"))
        .args(["-w", "start"])
        .output()
        .map_err(|e| fail(format!("could not run pg_ctl: {e}")))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(fail(format!(
            "PostgreSQL did not start: {}. See {}",
            stderr.lines().last().unwrap_or("no output"),
            log.display()
        )));
    }
    Ok(())
}

/// Forget the recorded kernel pid after a clean shutdown, so the next start
/// does not try to kill a pid the OS may have reused for something else.
pub fn clear_kernel_pid(data_dir: &Path) {
    let _ = fs::remove_file(kernel_pid_file(data_dir));
}

pub fn stop_postgres(bin_dir: &Path, pg_data: &Path) {
    // Best effort. "-m fast" rolls back open transactions and checkpoints, so
    // the next start skips crash recovery.
    let _ = Command::new(bin_dir.join(postgres_exe("pg_ctl")))
        .arg("-D")
        .arg(pg_data)
        .args(["-m", "fast", "-w", "stop"])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
}

/// Poll the kernel's health endpoint until it answers or we run out of patience.
///
/// This used to accept a bare TCP connect as proof of life, on the reasoning
/// that uvicorn binds the port only after importing the ASGI app. That is not
/// true in a way that matters: the listening socket accepts connections while
/// the worker is still starting, so the connect succeeds, the shell announces
/// "ready", and the first real request from the UI then sits in the accept
/// queue. If the kernel dies during import, that request never completes and
/// never fails -- which is precisely how a window ends up blank forever.
///
/// So readiness now means the kernel answered an actual HTTP request.
fn wait_for_kernel(app: &AppHandle, port: u16, deadline: Duration) -> Result<(), BootstrapError> {
    let started = Instant::now();
    let mut attempts = 0_u32;
    let mut last_note = Instant::now();
    let mut last_error = String::from("no attempt completed");

    while started.elapsed() < deadline {
        // If the kernel has already died there is nothing left to wait for.
        if let Some(state) = app.try_state::<KernelProcess>() {
            let exited = state.exited.lock().ok().and_then(|slot| slot.clone());
            if let Some(reason) = exited {
                return Err(fail(format!(
                    "the Atlas kernel stopped before it finished starting: {reason}. \
                     See logs/kernel.log in the Atlas data directory."
                )));
            }
        }

        attempts += 1;
        match probe_health(port) {
            Ok(status) if (200..500).contains(&status) => {
                log(
                    app,
                    &format!(
                        "health: HTTP {status} after {attempts} attempt(s), {}ms",
                        started.elapsed().as_millis()
                    ),
                );
                return Ok(());
            }
            Ok(status) => last_error = format!("HTTP {status}"),
            Err(error) => last_error = error,
        }

        // One line every couple of seconds, not one per poll -- enough to show
        // the wait is progressing without burying the log.
        if last_note.elapsed() >= Duration::from_secs(2) {
            log(
                app,
                &format!(
                    "health: still waiting after {}s ({attempts} attempts, last: {last_error})",
                    started.elapsed().as_secs()
                ),
            );
            last_note = Instant::now();
        }

        std::thread::sleep(Duration::from_millis(200));
    }

    Err(fail(format!(
        "the Atlas kernel did not answer /health on port {port} within {}s. Last attempt: {last_error}",
        deadline.as_secs()
    )))
}

/// One HTTP/1.1 GET /health, returning the status code.
///
/// Hand-rolled rather than pulling in an HTTP client: this is the only request
/// the shell ever makes, it is to loopback, and the shell should not carry a
/// TLS stack it will never use. Every socket operation is bounded, so a kernel
/// that accepts a connection and then says nothing cannot wedge the boot.
fn probe_health(port: u16) -> Result<u16, String> {
    use std::io::{Read, Write};
    use std::net::{SocketAddr, TcpStream};

    let address = SocketAddr::from(([127, 0, 0, 1], port));
    let mut stream = TcpStream::connect_timeout(&address, Duration::from_secs(2))
        .map_err(|e| format!("connect: {e}"))?;
    stream
        .set_read_timeout(Some(Duration::from_secs(3)))
        .and_then(|_| stream.set_write_timeout(Some(Duration::from_secs(3))))
        .map_err(|e| format!("socket options: {e}"))?;

    stream
        .write_all(
            b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\nAccept: */*\r\n\r\n",
        )
        .map_err(|e| format!("write: {e}"))?;

    // The status line is all that is needed, but the response is small and
    // reading to the end keeps the socket from being closed mid-write.
    let mut buffer = Vec::with_capacity(512);
    let mut chunk = [0_u8; 512];
    loop {
        match stream.read(&mut chunk) {
            Ok(0) => break,
            Ok(n) => {
                buffer.extend_from_slice(&chunk[..n]);
                if buffer.len() > 8192 || buffer.windows(4).any(|w| w == b"\r\n\r\n") {
                    break;
                }
            }
            Err(e) => return Err(format!("read: {e}")),
        }
    }

    let head = String::from_utf8_lossy(&buffer);
    let status = head
        .split_whitespace()
        .nth(1)
        .and_then(|code| code.parse::<u16>().ok())
        .ok_or_else(|| {
            format!(
                "unparseable response: {:?}",
                head.chars().take(60).collect::<String>()
            )
        })?;
    Ok(status)
}

/// Run the whole sequence. Returns the API port the frontend should talk to.
pub fn run(app: &AppHandle) -> Result<u16, BootstrapError> {
    report(app, Stage::Starting, "Starting Atlas", false, None);

    let data_dir = resolve_data_dir(app)?;

    // Point the log at disk as early as possible. Everything above this line is
    // buffered in memory and flushed here, so a failure to resolve the data
    // directory is still recorded once a later run succeeds.
    if let Some(state) = app.try_state::<StartupLog>() {
        state.attach(&data_dir);
    }
    log(app, &format!("data directory: {}", data_dir.display()));

    let pg_data = data_dir.join("postgres");
    let first_run = needs_initdb(&pg_data);
    log(app, &format!("first run: {first_run}"));

    report(
        app,
        Stage::PreparingStorage,
        "Preparing local storage",
        first_run,
        Some(data_dir.display().to_string()),
    );
    fs::create_dir_all(&data_dir)
        .map_err(|e| fail(format!("could not create {}: {e}", data_dir.display())))?;

    // Clear anything a previous crash left running before claiming the port
    // and data directory for ourselves.
    reclaim_kernel(&data_dir);

    let bin_dir = resolve_postgres_bin(app)?;
    log(app, &format!("postgres binaries: {}", bin_dir.display()));

    if first_run {
        report(
            app,
            Stage::InitialisingDatabase,
            "Setting up the database for the first time",
            true,
            Some("This happens once and takes a few seconds.".into()),
        );
        run_initdb(&bin_dir, &pg_data)?;
        log(app, "postgres: initdb complete");
    }

    let pg_port = free_port()?;
    report(
        app,
        Stage::StartingDatabase,
        "Starting the database",
        first_run,
        None,
    );
    log(app, &format!("postgres: launching on port {pg_port}"));
    start_postgres(&bin_dir, &pg_data, pg_port)?;
    // pg_ctl was invoked with -w, so it has already waited for the server to
    // accept connections. Reaching this line is the readiness signal.
    log(app, &format!("postgres: ready on port {pg_port}"));

    // Record enough to shut down cleanly even if a later step fails.
    if let Some(state) = app.try_state::<BootstrapState>() {
        *state.pg_port.lock().unwrap() = Some(pg_port);
        *state.pg_data_dir.lock().unwrap() = Some(pg_data.clone());
        *state.pg_bin_dir.lock().unwrap() = Some(bin_dir.clone());
        *state.data_dir.lock().unwrap() = Some(data_dir.clone());
    }

    let api_port = free_port()?;
    let database_url = format!("postgresql+psycopg://atlas@127.0.0.1:{pg_port}/atlas");

    report(
        app,
        Stage::StartingKernel,
        "Starting the Atlas kernel",
        first_run,
        None,
    );
    log(app, &format!("kernel: launching on port {api_port}"));
    spawn_kernel(app, api_port, &database_url, &data_dir)?;

    report(
        app,
        Stage::WaitingForKernel,
        "Waiting for the kernel to come up",
        first_run,
        None,
    );
    wait_for_kernel(app, api_port, KERNEL_READY_TIMEOUT)?;

    if let Some(state) = app.try_state::<BootstrapState>() {
        *state.api_port.lock().unwrap() = Some(api_port);
    }
    report(app, Stage::Ready, "Atlas is ready", first_run, None);
    log(
        app,
        &format!("kernel: ready, api base http://127.0.0.1:{api_port}"),
    );
    Ok(api_port)
}

/// Start the packaged kernel binary as a sidecar process.
fn spawn_kernel(
    app: &AppHandle,
    api_port: u16,
    database_url: &str,
    data_dir: &Path,
) -> Result<(), BootstrapError> {
    use tauri_plugin_shell::process::CommandEvent;
    use tauri_plugin_shell::ShellExt;

    let command = app
        .shell()
        .sidecar("atlas-kernel")
        .map_err(|e| fail(format!("the bundled Atlas kernel is missing: {e}")))?
        .env("ATLAS_DATABASE_URL", database_url)
        .env("ATLAS_DATA_DIR", data_dir.display().to_string())
        .env("ATLAS_PROFILE", "production")
        .args(["--host", "127.0.0.1", "--port", &api_port.to_string()]);

    let (mut rx, child) = command
        .spawn()
        .map_err(|e| fail(format!("could not start the Atlas kernel: {e}")))?;

    // Recorded before anything else can fail, so a crash one line later still
    // leaves a trail the next run can clean up.
    let _ = fs::write(kernel_pid_file(data_dir), child.pid().to_string());

    if let Some(state) = app.try_state::<KernelProcess>() {
        state.store(child);
    }

    // Drain the kernel's output so its pipe never fills and blocks it. Lines
    // are forwarded to the app log, which is what a diagnostics export reads.
    let handle = app.clone();
    std::thread::spawn(move || {
        while let Some(event) = tauri::async_runtime::block_on(rx.recv()) {
            match event {
                CommandEvent::Stdout(line) | CommandEvent::Stderr(line) => {
                    let text = String::from_utf8_lossy(&line).trim_end().to_string();
                    if !text.is_empty() {
                        log_kernel_line(&handle, &text);
                    }
                }
                CommandEvent::Terminated(payload) => {
                    let note = format!("kernel exited with status {:?}", payload.code);
                    log_kernel_line(&handle, &note);
                    // Recorded so the boot wait can stop immediately instead of
                    // spending the full timeout waiting for a process that is
                    // already gone.
                    if let Some(state) = handle.try_state::<KernelProcess>() {
                        if let Ok(mut slot) = state.exited.lock() {
                            *slot = Some(note.clone());
                        }
                    }
                    log(&handle, &note);
                    break;
                }
                _ => {}
            }
        }
    });

    Ok(())
}

/// Forward one line of kernel output to the UI and to `logs/kernel.log`.
///
/// The file matters more than the event: events reach only a window that is
/// already listening, and a kernel that fails during startup does so before
/// anyone is.
fn log_kernel_line(app: &AppHandle, line: &str) {
    let _ = app.emit("atlas://kernel-log", line.to_string());

    let path = app
        .try_state::<BootstrapState>()
        .and_then(|state| state.data_dir.lock().ok().and_then(|dir| dir.clone()));
    if let Some(dir) = path {
        let logs = dir.join("logs");
        if fs::create_dir_all(&logs).is_ok() {
            if let Ok(mut file) = fs::OpenOptions::new()
                .create(true)
                .append(true)
                .open(logs.join("kernel.log"))
            {
                use std::io::Write;
                let _ = writeln!(file, "{line}");
            }
        }
    }
}

/// Handle to the running kernel so it can be stopped with the window.
#[derive(Default)]
pub struct KernelProcess {
    pub child: Mutex<Option<tauri_plugin_shell::process::CommandChild>>,
    /// Kept separately because taking the child to kill it also takes its pid,
    /// and the child's own children still need to be found afterwards.
    pub pid: Mutex<Option<u32>>,
    /// Set when the kernel process ends, so a boot that is waiting on it can
    /// fail with the real reason instead of timing out.
    pub exited: Mutex<Option<String>>,
}

impl KernelProcess {
    pub fn store(&self, child: tauri_plugin_shell::process::CommandChild) {
        if let Ok(mut slot) = self.pid.lock() {
            *slot = Some(child.pid());
        }
        if let Ok(mut slot) = self.child.lock() {
            *slot = Some(child);
        }
    }

    /// Stop the kernel and everything it started.
    ///
    /// The kernel is a PyInstaller binary: the process we spawn is a
    /// bootloader that unpacks itself and runs the real interpreter as a
    /// *child*. Killing only our direct child leaves that grandchild holding
    /// the API port, so the tree has to go.
    pub fn kill(&self) {
        let pid = self.pid.lock().ok().and_then(|mut slot| slot.take());

        if let Some(pid) = pid {
            kill_tree(pid);
        }

        if let Ok(mut slot) = self.child.lock() {
            if let Some(child) = slot.take() {
                let _ = child.kill();
            }
        }
    }
}

/// Kill a process and its descendants, using only what the platform ships.
fn kill_tree(pid: u32) {
    #[cfg(windows)]
    {
        // /T includes the whole tree, /F forces it.
        let _ = Command::new("taskkill")
            .args(["/F", "/T", "/PID", &pid.to_string()])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }

    #[cfg(not(windows))]
    {
        // Children first: killing the parent first would reparent them to
        // init and lose the link we need to find them by.
        let _ = Command::new("pkill")
            .args(["-TERM", "-P", &pid.to_string()])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
        let _ = Command::new("kill")
            .args(["-TERM", &pid.to_string()])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }
}

/// Read a log file tail for the diagnostics screen, if it exists.
pub fn postgres_log(pg_data: &Path, lines: usize) -> Option<String> {
    tail_file(&pg_data.join("server.log"), lines)
}

/// Last `lines` lines of a file, or None if it cannot be read.
pub fn tail_file(path: &Path, lines: usize) -> Option<String> {
    let file = fs::File::open(path).ok()?;
    let collected: Vec<String> = BufReader::new(file).lines().map_while(Result::ok).collect();
    let start = collected.len().saturating_sub(lines);
    Some(collected[start..].join("\n"))
}
