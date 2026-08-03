# Changelog

All notable changes to Atlas. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

Versions before `0.12.0-alpha.1` were internal engineering milestones. They
were tagged and are listed here for continuity, but they were never released
to anyone.

## [Unreleased]

### Fixed — desktop stability

Found by running the *released* build against a real data directory, rather
than a development build against a temporary one. Every one of these needs a
packaged app and real state to reproduce.

- **Two copies of Atlas could destroy the database.** A second launch reclaimed
  the data directory from the first: it killed the running kernel and stopped
  the database beneath a window that had already rendered and would therefore
  never show an error. With an orphaned server still attached, two PostgreSQL
  processes reached the same cluster and left WAL from one against the control
  file of the other — which is not recoverable. Atlas now takes a lock on the
  data directory and a second copy refuses to start, naming the process that
  holds it. A lock left by a crash is ignored: the recorded pid is checked for
  liveness and for being an Atlas process.
- **A damaged lock file made Atlas permanently unstartable.** `pg_ctl` will not
  stop a server whose `postmaster.pid` it cannot parse, and will not start one
  while the file exists — the shape a power loss leaves behind. Atlas now reads
  the file itself, stops the recorded server if it is genuinely alive, and
  removes the file when it is not.
- **"Examine the log output."** was the entire diagnosis a user got when
  PostgreSQL refused to start. Atlas now reads the log on their behalf and shows
  the actual reason.
- **A database beyond repair was a dead end.** Atlas now recognises the states
  PostgreSQL reports when the files themselves are broken, says so plainly, and
  offers to move the damaged database aside and start over. Nothing is deleted —
  it is renamed and left where it was.
- **A kernel that died after startup was invisible.** The window stayed up,
  rendered and useless, with every request failing silently. That is
  indistinguishable from a hang. It now shows the diagnostics screen.
- **The startup deadline was too tight and fired falsely.** 30 seconds per stage
  is not enough for a first run under Rosetta, where `initdb` and a cold kernel
  import are each easily that long. It is now 120 seconds per stage — long
  enough that the shell always reports the real failure first — and the splash
  admits when it is taking a while instead of looking frozen.
- **The download page listed filenames that do not exist** and gave no warning
  about architecture. The Intel build runs on Apple Silicon through Rosetta at
  roughly a fifth of the speed, with nothing on screen to say why.

## [0.12.0-alpha.2] — RC1 Hotfix

`0.12.0-alpha.1` built on every platform and installed correctly, and was still
unusable. Three faults, each of which presented as silence rather than an error.
Nothing here is a new feature.

### Fixed

- **Atlas opened to a black window and stayed there.** `App` called
  `useGlobalShortcuts`, which calls `useNavigate`, but `App` is the component
  that *provides* the router — so the hook ran outside its own context and threw
  `useNavigate() may be used only in the context of a <Router> component` on
  every render. React unmounts the tree when a render throws, so the result was
  an empty document: no error, no log, nothing to distinguish it from a hang.
  Router-dependent hooks now live in `DesktopShellLayout`, inside the router.
- **An installed Atlas could not talk to its own kernel.** Tauri serves the
  frontend from its own scheme, so the packaged webview's origin is
  `tauri://localhost` (`http://tauri.localhost` on Windows). The kernel's CORS
  policy allowed only the Vite dev server, so every request from a real
  installation was blocked. The browser reports that as a bare "Load failed",
  and the onboarding store reads any failure as "setup already done" — so Atlas
  skipped the first-run wizard and opened an empty workspace, on every launch,
  while working perfectly in `npm run dev`.
- **Both portable archives shipped without a database.** The Linux `tar.gz` and
  the Windows `.zip` contained no PostgreSQL at all, while the release notes
  promised one. `tauri.conf.json` maps `resources/postgres` to `postgres`, so
  Tauri writes `$exe_dir/postgres`; the workflow copied `$exe_dir/resources`,
  which never existed, and a trailing `|| true` hid the failure every time. The
  build now fails if the database is missing from an archive.
- **Resource lookup ignored the portable layout.** `resource_dir()` resolves to
  `/usr/lib/atlas-desktop` for a plain Linux binary, which is not where an
  archive unpacked into a home directory keeps anything. The executable's own
  directory is now searched too, and every path tried is logged.
- **A boot failure could take 30 seconds to appear.** Bootstrap can fail in
  under a second, before the webview has loaded, and the failure was emitted but
  never stored — so a window that mounted afterwards saw only the last
  successful stage and waited. Failures are now recorded like any other stage.
- **Kernel readiness was declared too early.** The shell accepted a bare TCP
  connect as proof the kernel was up, but a listening socket accepts connections
  while the worker is still importing. Readiness now means an answered
  `GET /health`.

### Added

- **`logs/startup.log`,** written by both the shell and the webview, covering
  the whole sequence: storage, `initdb`, PostgreSQL launch and readiness, kernel
  launch, health polling, the webview loading, setup state, and the first screen
  rendered. Each line carries a UTC timestamp and milliseconds since launch.
  Also mirrored to stderr, and it survives a data directory that cannot be
  written by falling back to stderr alone.
- **`logs/kernel.log`** — the kernel's own output, previously emitted only as an
  event that nothing was listening for when it mattered.
- **A diagnostics screen** shown whenever Atlas cannot start, or has not started
  within 30 seconds. It always names a reason and offers Retry, Open
  diagnostics, View logs, and Copy diagnostic report.
- **A root error boundary,** so a render crash anywhere shows that screen rather
  than a blank window. This class of bug can no longer present as a black
  screen.
- **Bounded requests on the boot path,** so a kernel that accepts a connection
  and then never answers fails instead of leaving the UI pending forever.

## [0.12.0-alpha.1] — Public Alpha

The first release intended for people other than the author.

### Added

- **Licensing.** Atlas is now under the Business Source License 1.1. Personal
  use, internal company use, research and education are permitted, including
  commercially. Offering Atlas to third parties as a hosted service is not. On
  2030-08-03 this version converts to Apache-2.0. See `LICENSE`.
- **`NOTICE`** — a real third-party inventory with actual pinned versions and
  licenses, including the two that need care: `psycopg` (LGPL-3.0) and
  `certifi` (MPL-2.0), plus the bundled PostgreSQL.
- **Version metadata** (`atlas_kernel.version`) as the single source of truth,
  exposed at `GET /version`, with build commit and date injected by CI.
- **Telemetry** (`atlas_kernel.telemetry`), **disabled by default**. Three
  modes: `disabled`, `crash_only`, `diagnostics`. Events are assembled from an
  allow-list of field names, so user content cannot be collected even by
  accident. Crash reports exclude the exception *message* and every stack
  frame outside the Atlas package. Atlas operates no telemetry server; the
  default sink is a local file you can read. See `docs/PRIVACY.md`.
- **Update checking** (`atlas_kernel.updates`), also disabled by default.
  Reports that a release exists and where to get it. There is no auto-updater
  and no mandatory update.
- **`GET /license`**, `GET /telemetry`, `PUT /telemetry/consent`,
  `POST /updates/check`.
- **Community and contribution files**: `CONTRIBUTING.md` (including how
  contributions are licensed under BSL), `CODE_OF_CONDUCT.md`,
  `.github/SECURITY.md`, issue templates, and a pull request template.
- **`docs/PRIVACY.md`** — what is collected, what is deliberately not, and how
  that is enforced in code.

### Changed

- Kernel version `0.1.0` → `0.12.0a1`; desktop `0.0.0` → `0.12.0-alpha.1`.
  The two were previously inconsistent and neither matched the release tags.

### Packaging

- **Desktop installers**, built with Tauri 2 — chosen over Electron because it
  uses the system webview rather than bundling a browser. Windows
  (NSIS installer + portable zip), macOS (`.app` + `.dmg`), Linux
  (AppImage + tar.gz).
- **PostgreSQL 16.14 is bundled.** Installing Atlas installs nothing else: the
  shell runs `initdb` on first launch, starts the server on a free loopback
  port, and the kernel creates its own database. No system PostgreSQL is
  touched and none is required.
- **The kernel ships as a standalone binary** (PyInstaller), so no Python is
  needed on the machine.
- `infra/packaging/` — reproducible scripts for the icon set, the PostgreSQL
  download (pinned and checksummed), the DMG, and SHA-256 manifests.
- **Release workflow** (`.github/workflows/release.yml`) with a four-platform
  native matrix. Tauri cannot cross-compile, so each target needs its own
  runner. Release notes are extracted from this changelog.
- **Rust CI job** — `cargo fmt --check` and `cargo clippy -D warnings`.

### Fixed during packaging

- **Atlas would start only once.** After a force-quit or crash the shell's
  shutdown handler never ran, leaving PostgreSQL holding `postmaster.pid`.
  Every later launch died with "lock file postmaster.pid already exists" and
  Atlas never started again until the user killed the process by hand. The
  shell now reclaims its own data directory and any kernel it recorded.
- **A packaged Atlas reported itself degraded.** PyInstaller omits
  distribution metadata, so `importlib.metadata` could not see FastAPI,
  SQLAlchemy, uvicorn or httpx even though they were imported and serving.
  `/health/report` therefore declared every dependency missing on a fresh
  install.
- **Quitting Atlas left it running.** macOS does not always emit
  `ExitRequested`, so the kernel and database survived the window closing.
- **Killing the kernel left half of it alive** — PyInstaller runs the real
  interpreter as a child process, so only the bootloader was being stopped.
- **The Linux AppImage would not build.** linuxdeploy inspects every ELF file
  in the bundle to resolve shared libraries, and the bundled PostgreSQL shipped
  procedural-language extensions linked against runtimes Atlas does not
  include — `plpython3` wants `libpython3.6m.so.1.0`, which no current
  distribution carries. One unresolvable file aborts the whole bundle. Atlas
  runs no in-database Python, Perl or Tcl, so these are now pruned along with
  `psql`. Tauri reported only `failed to run linuxdeploy` because it discards
  the bundler's output unless built with `--verbose`, which the release
  workflow now always passes.
- **The macOS Intel installer was never built.** GitHub retired the `macos-13`
  runner, so that job queued until it was cancelled rather than failing — which
  looks like a slow build, not a missing machine. Now on `macos-15-intel`.

### Known limitations

Stated plainly rather than discovered later:

- **The kernel API has no authentication.** It binds to localhost and assumes
  one trusted operator. Do not expose port 8000 to an untrusted network.
- **Alpha builds are unsigned.** Gatekeeper and SmartScreen will warn. Verify
  the published SHA-256 checksum.
- **The test suite cannot be run twice concurrently** against one database.
- Provider credentials live in local configuration, not an OS keychain.
- **Installers are large** — roughly 140 MB compressed, mostly PostgreSQL.
  `libicudata` alone is 55 MB and cannot be removed; PostgreSQL 16 links ICU
  for collation and will not start without it.
- **The macOS DMG has no styled window background.** Tauri's DMG bundler
  drives Finder over AppleScript, which needs an interactive GUI session and
  fails on a CI runner. Atlas builds the image with `hdiutil` instead:
  functionally identical, no background art.

## [0.11.0] — Production Hardening — 2026-08-03

Tag `v0.11-production`, commit `acd61c6`.

### Added

- Configuration profiles, structured logging, diagnostics, checksummed
  backup/restore, and a crash-recovery sweep with isolated stages.
- 38 database indexes, startup schema validation and integrity checks.
- `docs/DEPLOYMENT.md`, `CONFIGURATION.md`, `TROUBLESHOOTING.md`,
  `ADMINISTRATOR_GUIDE.md`.

### Fixed

- `PATCH /agents/{id}` wrote `None` over fields the client did not send,
  silently destroying name, role, status and capabilities on a partial update.
  Present since the Foundation release.
- A zero timeout raced the provider, so a fast job could finish before the
  deadline was checked. Work with no time budget now never starts.
- The in-process worker aged out after 90 seconds with no heartbeat agent,
  making a single-machine Atlas declare its own worker dead and stall all
  placement.
- A recovery sweep aborted entirely when a reservation referenced a deleted
  worker.
- Removed two API routes that FastAPI could never reach — both paths were
  registered twice and the second pair was shadowed.

### Infrastructure

- CI had no PostgreSQL service, so the pytest gate could never have passed.
  Added it. All four gates (ruff, black, mypy, pytest at 90% coverage) pass
  for the first time.

## [0.10.0] — Enterprise Platform — 2026-08-02

Tag `v0.10-enterprise`, commit `0e3680a`. Organizations, teams, roles and
declarative permissions with scope inheritance and locked keys; identity and
membership with expiry; append-only audit.

## [0.9.0] — Distributed Runtime — 2026-08-01

Tag `v0.9-cluster`, commit `640b7a6`. Worker registry, heartbeats, dispatcher,
leases and reservations, and placement recovery. Execution location is a
scheduling decision, never a user decision.

## [0.8.0] — Approval & Governance — 2026-07-31

Tag `v0.8-governance`, commit `2ef4189`. Declarative approval policies that
pause execution before a job exists. `WAITING_APPROVAL` is distinct from
`READY`. A requester can never approve their own request.

## [0.7.0] — Foundation and Automation Engine

Tags `v0.7-foundation`, commits `6c28739` and `514ccc3`. The platform
foundation through Milestone 006F, then the Automation Engine — deterministic,
trigger-driven, and structurally unable to call a provider directly or bypass
the scheduler.

[Unreleased]: https://github.com/hellnight333/atlas/compare/v0.12.0-alpha.2...HEAD
[0.12.0-alpha.2]: https://github.com/hellnight333/atlas/releases/tag/v0.12.0-alpha.2
[0.12.0-alpha.1]: https://github.com/hellnight333/atlas/releases/tag/v0.12.0-alpha.1
[0.11.0]: https://github.com/hellnight333/atlas/releases/tag/v0.11-production
[0.10.0]: https://github.com/hellnight333/atlas/releases/tag/v0.10-enterprise
[0.9.0]: https://github.com/hellnight333/atlas/releases/tag/v0.9-cluster
[0.8.0]: https://github.com/hellnight333/atlas/releases/tag/v0.8-governance
[0.7.0]: https://github.com/hellnight333/atlas/releases/tag/v0.7-foundation
