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

/// Whether a process is alive *and* is one of ours.
///
/// Liveness alone is not enough: pids are reused, and killing or deferring to
/// an unrelated program because it inherited a number would be worse than the
/// problem being solved. The command name is checked too.
fn is_live_atlas_process(pid: u32, needle: &str) -> bool {
    #[cfg(windows)]
    {
        let Ok(output) = Command::new("tasklist")
            .args(["/FI", &format!("PID eq {pid}"), "/FO", "CSV", "/NH"])
            .output()
        else {
            return false;
        };
        let text = String::from_utf8_lossy(&output.stdout).to_lowercase();
        return text.contains(&needle.to_lowercase());
    }

    #[cfg(not(windows))]
    {
        let Ok(output) = Command::new("ps")
            .args(["-p", &pid.to_string(), "-o", "command="])
            .output()
        else {
            return false;
        };
        if !output.status.success() {
            return false;
        }
        let text = String::from_utf8_lossy(&output.stdout).to_lowercase();
        !text.trim().is_empty() && text.contains(&needle.to_lowercase())
    }
}

/// Where this instance records that it owns the data directory.
fn instance_lock_file(data_dir: &Path) -> PathBuf {
    data_dir.join("atlas.lock")
}

/// Claim exclusive use of the data directory, or refuse to start.
///
/// This is the guard that turns a nuisance into a non-event. Without it a
/// second Atlas launched against the same data directory will reclaim it from
/// the first -- killing its kernel and stopping its database out from under a
/// window that has already rendered and will therefore never show an error.
/// Worse, two PostgreSQL servers reaching the same cluster can leave WAL from
/// one against the control file of the other, which is not a recoverable
/// state: the cluster is destroyed and everything in it is gone.
///
/// A stale lock is not a problem. The recorded pid is checked for liveness and
/// for being an Atlas process, so a crash leaves a lock that the next launch
/// correctly ignores.
fn acquire_instance_lock(app: &AppHandle, data_dir: &Path) -> Result<(), BootstrapError> {
    let lock = instance_lock_file(data_dir);

    if let Ok(contents) = fs::read_to_string(&lock) {
        if let Ok(pid) = contents.trim().parse::<u32>() {
            if pid != std::process::id() && is_live_atlas_process(pid, "atlas") {
                return Err(fail(format!(
                    "Atlas is already running (process {pid}) and is using this \
                     data directory.\n\nTwo copies cannot share one database. The \
                     second would stop the first, and both writing at once can \
                     destroy the data outright.\n\nSwitch to the Atlas window that \
                     is already open, or quit it before starting this one."
                )));
            }
            log(app, &format!("ignoring stale instance lock from pid {pid}"));
        }
    }

    fs::write(&lock, std::process::id().to_string())
        .map_err(|e| fail(format!("could not claim {}: {e}", lock.display())))?;
    log(
        app,
        &format!("instance lock acquired ({})", std::process::id()),
    );
    Ok(())
}

/// Give up the data directory. Best effort, and only if the lock is ours.
pub fn release_instance_lock(data_dir: &Path) {
    let lock = instance_lock_file(data_dir);
    if let Ok(contents) = fs::read_to_string(&lock) {
        if contents.trim().parse::<u32>() == Ok(std::process::id()) {
            let _ = fs::remove_file(&lock);
        }
    }
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
fn reclaim_data_dir(app: &AppHandle, bin_dir: &Path, pg_data: &Path) {
    let pid_file = pg_data.join("postmaster.pid");
    if !pid_file.exists() {
        return;
    }
    log(app, "postgres: a lock file from a previous run is present");

    // The polite route first. Works when the file is intact, whether the
    // server it names is alive or already gone.
    let stopped = Command::new(bin_dir.join(postgres_exe("pg_ctl")))
        .arg("-D")
        .arg(pg_data)
        .args(["-m", "fast", "-w", "stop"])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|status| status.success())
        .unwrap_or(false);

    if stopped {
        log(app, "postgres: previous server stopped cleanly");
        return;
    }

    // pg_ctl refused, which nearly always means the lock file is unreadable or
    // truncated -- the shape a hard power loss leaves behind. Before this was
    // handled, that state was terminal: pg_ctl would not stop it because it
    // could not parse it, and would not start because the file was there.
    // Atlas could never start again.
    log(
        app,
        "postgres: pg_ctl could not stop it; inspecting the lock file directly",
    );

    // Line one of postmaster.pid is the postmaster's pid.
    let owner = fs::read_to_string(&pid_file)
        .ok()
        .and_then(|body| body.lines().next().map(str::to_owned))
        .and_then(|first| first.trim().parse::<u32>().ok());

    match owner {
        Some(pid) if is_live_atlas_process(pid, "postgres") => {
            // A real server is still on this directory. Stop it, or the next
            // start will run a second one against the same files -- which is
            // how a cluster gets destroyed rather than merely inconvenienced.
            log(
                app,
                &format!("postgres: orphaned server {pid} is alive; stopping it"),
            );
            kill_tree(pid);
            for _ in 0..50 {
                if !is_live_atlas_process(pid, "postgres") {
                    break;
                }
                std::thread::sleep(Duration::from_millis(100));
            }
        }
        Some(pid) => log(app, &format!("postgres: recorded server {pid} is gone")),
        None => log(app, "postgres: the lock file is unreadable"),
    }

    // Safe now: nothing is running against this directory. PostgreSQL's own
    // documentation says a lock file whose postmaster is gone may be removed.
    if fs::remove_file(&pid_file).is_ok() {
        log(app, "postgres: removed the stale lock file");
    }
}

fn start_postgres(
    app: &AppHandle,
    bin_dir: &Path,
    pg_data: &Path,
    port: u16,
) -> Result<(), BootstrapError> {
    reclaim_data_dir(app, bin_dir, pg_data);
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
        // pg_ctl says "Examine the log output." and exits. Doing as it asks on
        // the user's behalf is the difference between a diagnosis and homework:
        // the real reason is always in server.log, and a person looking at a
        // diagnostics screen cannot be expected to go and find it.
        let detail = postgres_failure_detail(&log);
        return Err(fail(format!("PostgreSQL did not start. {detail}")));
    }
    Ok(())
}

/// Read out of server.log why PostgreSQL refused, in words worth showing.
fn postgres_failure_detail(log_path: &Path) -> String {
    let Some(tail) = tail_file(log_path, 40) else {
        return format!("Nothing was written to {}.", log_path.display());
    };

    // A cluster whose WAL and control file disagree, or whose checkpoint cannot
    // be found, is not going to recover on the next attempt. Saying so, and
    // saying what can be done, beats an error the user will retry forever.
    // The set PostgreSQL uses when the files themselves are the problem. Found
    // by corrupting a cluster and reading what it actually said: a control file
    // scribbled over reports "incompatible with server", not a checkpoint
    // error, and matching only the checkpoint wording left the user with a dead
    // end and no reset offered.
    const UNRECOVERABLE: [&str; 6] = [
        "could not locate a valid checkpoint record",
        "is from different database system",
        "database files are incompatible with server",
        "incorrect checksum in control file",
        "control file contains invalid data",
        "PANIC",
    ];
    let unrecoverable = UNRECOVERABLE.iter().any(|needle| tail.contains(needle));

    let reason = tail
        .lines()
        .rev()
        .find(|line| {
            line.contains("FATAL")
                || line.contains("PANIC")
                || line.contains("ERROR")
                || line.contains("could not")
        })
        .map(str::trim)
        .unwrap_or("The database log does not say why.");

    if unrecoverable {
        format!(
            "{reason}\n\nThe database files are damaged beyond repair, which usually \
             follows a power loss or two copies of Atlas running at once. Atlas will not \
             delete them on your behalf. To start over, move this folder aside and \
             reopen Atlas -- a new database will be created:\n{}",
            log_path
                .parent()
                .map(|p| p.display().to_string())
                .unwrap_or_default()
        )
    } else {
        format!("{reason}\n\nFull log: {}", log_path.display())
    }
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

    // Before anything is reclaimed. Reclaiming is safe only once we know no
    // other Atlas is using this directory -- otherwise "recovery" is theft.
    acquire_instance_lock(app, &data_dir)?;

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
    start_postgres(app, &bin_dir, &pg_data, pg_port)?;
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

                    // If Atlas had already started, the window is open and
                    // rendered, and nothing on screen would ever mention that
                    // the backend behind it has died. Every request would fail
                    // silently and the application would simply stop working --
                    // indistinguishable, to the person using it, from a hang.
                    let was_running = handle
                        .try_state::<BootstrapState>()
                        .and_then(|state| state.progress.lock().ok().and_then(|p| p.clone()))
                        .map(|progress| progress.stage == Stage::Ready)
                        .unwrap_or(false);
                    if was_running {
                        report_failure(
                            &handle,
                            format!(
                                "The Atlas kernel stopped unexpectedly ({}). Atlas cannot \
                                 do anything until it is restarted. See logs/kernel.log in \
                                 the Atlas data directory for what it said on the way out.",
                                payload
                                    .code
                                    .map(|code| format!("exit code {code}"))
                                    .unwrap_or_else(|| "no exit code".into())
                            ),
                        );
                    }
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

/// Move a damaged database aside so a fresh one can be created.
///
/// Never deletes. A cluster PostgreSQL cannot open may still contain something
/// recoverable by someone who knows what they are doing, and Atlas is not
/// entitled to decide otherwise on a user's behalf. It is renamed with a
/// timestamp and left where they can find it.
///
/// This exists because the alternative was a dead end: an unrecoverable cluster
/// left Atlas permanently unable to start, and the only way out was Finder or a
/// terminal. That is not something a daily-driver application may ask of anyone.
pub fn reset_database(data_dir: &Path) -> Result<PathBuf, BootstrapError> {
    let pg_data = data_dir.join("postgres");
    if !pg_data.exists() {
        return Err(fail("there is no database to reset"));
    }

    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let archived = data_dir.join(format!("postgres.damaged.{stamp}"));

    fs::rename(&pg_data, &archived)
        .map_err(|e| fail(format!("could not move the old database aside: {e}")))?;
    Ok(archived)
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
