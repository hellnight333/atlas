//! A written record of how Atlas started.
//!
//! RC1 shipped a build that could reach "Waiting for the kernel to come up" and
//! then show nothing at all. Nobody could say which step had stalled, because
//! nothing was written down: the boot sequence reported progress to a window
//! that had already stopped listening, and the evidence died with the process.
//!
//! So every boot writes `logs/startup.log` inside the data directory, from both
//! sides of the app — the Rust shell and the webview. A user who sees a stuck
//! window can send this file, and it names the step that did not finish.
//!
//! Two design points worth keeping:
//!
//! * Lines are buffered until the data directory is known. The first few events
//!   happen before Atlas has chosen where to write, and those are exactly the
//!   ones that matter if resolving the data directory is what failed.
//! * Every line also goes to stderr, so `Atlas.app/Contents/MacOS/atlas-desktop`
//!   run from a terminal narrates itself without needing the file at all.

use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

/// Keeps the log from growing without bound across many launches. Small enough
/// to paste into an issue, large enough to hold several boots.
const MAX_BYTES: u64 = 512 * 1024;

pub struct StartupLog {
    path: Mutex<Option<PathBuf>>,
    /// Lines recorded before the destination was known.
    pending: Mutex<Vec<String>>,
    started: Instant,
}

impl Default for StartupLog {
    fn default() -> Self {
        Self {
            path: Mutex::new(None),
            pending: Mutex::new(Vec::new()),
            started: Instant::now(),
        }
    }
}

impl StartupLog {
    /// Record one event. `source` is `shell` or `ui`, so a reader can tell which
    /// side of the application stopped making progress.
    pub fn record(&self, source: &str, message: &str) {
        let line = format!(
            "{}  {:>7}  [{}] {}",
            iso8601_utc(),
            format!("+{}ms", self.started.elapsed().as_millis()),
            source,
            message
        );

        eprintln!("[atlas-startup] {line}");

        let destination = self.path.lock().ok().and_then(|slot| slot.clone());
        match destination {
            Some(path) => append(&path, &line),
            None => {
                if let Ok(mut pending) = self.pending.lock() {
                    pending.push(line);
                }
            }
        }
    }

    /// Point the log at the data directory and flush everything buffered so far.
    ///
    /// Failing to open the log must never stop Atlas from starting — a missing
    /// diagnostic is a smaller problem than an app that will not run — so this
    /// reports the problem to stderr and carries on.
    pub fn attach(&self, data_dir: &Path) {
        let dir = data_dir.join("logs");
        if let Err(error) = fs::create_dir_all(&dir) {
            eprintln!(
                "[atlas-startup] could not create {}: {error}",
                dir.display()
            );
            return;
        }
        let path = dir.join("startup.log");
        rotate_if_large(&path);

        // Which binary this actually is. Not a nicety: a stale build left in a
        // `target/` directory looks identical to the installed one, launches
        // just as happily, and faithfully reproduces bugs that were fixed hours
        // ago. A whole debugging round was spent on exactly that. One line here
        // answers "which Atlas am I running" before anyone asks.
        let exe = std::env::current_exe()
            .map(|path| path.display().to_string())
            .unwrap_or_else(|_| "unknown".into());

        append(
            &path,
            &format!(
                "\n=== Atlas {} ({}) ===\n  binary: {exe}",
                env!("CARGO_PKG_VERSION"),
                option_env!("ATLAS_BUILD_COMMIT").unwrap_or("local build")
            ),
        );
        if let Ok(mut pending) = self.pending.lock() {
            for line in pending.drain(..) {
                append(&path, &line);
            }
        }
        if let Ok(mut slot) = self.path.lock() {
            *slot = Some(path);
        }
    }

    pub fn path(&self) -> Option<PathBuf> {
        self.path.lock().ok().and_then(|slot| slot.clone())
    }

    /// The tail of the log, for the diagnostics screen.
    pub fn tail(&self, lines: usize) -> Option<String> {
        let path = self.path()?;
        let text = fs::read_to_string(path).ok()?;
        let collected: Vec<&str> = text.lines().collect();
        let start = collected.len().saturating_sub(lines);
        Some(collected[start..].join("\n"))
    }
}

fn append(path: &Path, line: &str) {
    if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(path) {
        let _ = writeln!(file, "{line}");
    }
}

/// Start a fresh file once the old one gets large, keeping one generation.
fn rotate_if_large(path: &Path) {
    if fs::metadata(path).map(|m| m.len()).unwrap_or(0) > MAX_BYTES {
        let _ = fs::rename(path, path.with_extension("log.1"));
    }
}

/// `2026-08-03T13:05:12.345Z`, without pulling in a date library for one line.
///
/// Uses Howard Hinnant's days-from-civil algorithm in reverse. Correct for any
/// date this application will ever see, and it cannot panic.
fn iso8601_utc() -> String {
    let now = match SystemTime::now().duration_since(UNIX_EPOCH) {
        Ok(value) => value,
        // A clock before 1970 is not worth a branch anywhere else.
        Err(_) => return "0000-00-00T00:00:00.000Z".to_string(),
    };
    let total_secs = now.as_secs();
    let millis = now.subsec_millis();

    let days = (total_secs / 86_400) as i64;
    let secs_of_day = total_secs % 86_400;
    let (hour, minute, second) = (
        secs_of_day / 3600,
        (secs_of_day % 3600) / 60,
        secs_of_day % 60,
    );

    // civil_from_days, shifted to an era beginning 0000-03-01.
    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = (z - era * 146_097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = if month <= 2 { y + 1 } else { y };

    format!("{year:04}-{month:02}-{day:02}T{hour:02}:{minute:02}:{second:02}.{millis:03}Z")
}
