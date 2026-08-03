# Packaging Atlas

How the installers are made, what is inside them, and what is deliberately
not.

Milestone 011 deferred packaging because building installers meant adding a
desktop shell framework, and 011 forbade architectural change. Milestone 012
owns it. The shell is **Tauri 2**, chosen over Electron because it uses the
system webview instead of bundling a browser — the difference is roughly 6 MB
of shell versus 150 MB.

## What ships inside an installer

| Component | Size | Why it is there |
|---|---|---|
| Tauri shell (Rust) | ~6 MB | Native window, process supervision |
| Web bundle | ~1 MB | The React application, built by Vite |
| `atlas-kernel` | ~23 MB | The FastAPI kernel with an embedded Python runtime |
| PostgreSQL 16.14 | ~131 MB | So installing Atlas installs nothing else |

The kernel is a PyInstaller binary, so **the user needs no Python**. The
database is a real PostgreSQL server, so **the user installs no database**.
That combination is what makes the alpha installable by someone who is not a
developer.

`libicudata` accounts for 55 MB of PostgreSQL on its own. It cannot be dropped:
PostgreSQL 16 links ICU for collation, and removing it produces a server that
will not start.

## Building locally

You need Rust, Node 22, Python 3.13, and (on Linux) the WebKitGTK development
packages listed in `.github/workflows/release.yml`.

```bash
# 1. The kernel binary
pip install pyinstaller
python -m PyInstaller infra/packaging/atlas-kernel.spec \
  --distpath infra/packaging/dist --workpath infra/packaging/build --noconfirm

# 2. Stage it as a sidecar, named for your target triple
TRIPLE=$(rustc -Vv | grep host | cut -d' ' -f2)
mkdir -p apps/desktop/src-tauri/binaries
cp infra/packaging/dist/atlas-kernel "apps/desktop/src-tauri/binaries/atlas-kernel-$TRIPLE"

# 3. The bundled database
python3 infra/packaging/fetch_postgres.py

# 4. The application
cd apps/desktop && npx tauri build
```

Neither the PostgreSQL tree nor the kernel binary is committed — both are
gitignored and rebuilt on demand.

## Cross-compilation does not work

Tauri cannot cross-compile: each platform needs a native runner. A Mac cannot
produce a `.exe` or an `.AppImage`. This is why `release.yml` uses a four-way
matrix (`macos-latest`, `macos-13`, `ubuntu-22.04`, `windows-latest`) and why
release artifacts come from CI rather than from a developer's machine.

Ubuntu **22.04** is deliberate. An AppImage built against a newer glibc
refuses to start on older distributions; the reverse is not a problem.

macOS is built twice, for Apple Silicon and Intel. The *PostgreSQL* artifacts
are universal binaries containing both architectures, so one download serves
both — but the PyInstaller kernel is single-architecture, so the app itself is
not universal.

## Signing — not configured, and why

**Alpha builds are unsigned.** macOS Gatekeeper will say Atlas "cannot be
opened because the developer cannot be verified"; Windows SmartScreen will
show "Windows protected your PC". Both are expected.

No placeholder certificate is committed anywhere. A fake signing identity does
not fail politely — it fails at bundle time in a way that reads like a build
bug rather than a missing credential, which wastes an afternoon for whoever
hits it next.

Because the builds are unsigned, **every release publishes `SHA256SUMS.txt`**,
and the release notes tell users how to check it. That is the alpha's
integrity story.

### Adding an Apple certificate later

Requires an Apple Developer Program membership (99 USD/year) — a
**Developer ID Application** certificate, which is the one for software
distributed outside the App Store.

1. Create the certificate in the Apple Developer portal, export it from
   Keychain Access as a `.p12` with a password.
2. Add these repository secrets:

   | Secret | Value |
   |---|---|
   | `APPLE_CERTIFICATE` | `base64 -i cert.p12` |
   | `APPLE_CERTIFICATE_PASSWORD` | the `.p12` password |
   | `APPLE_SIGNING_IDENTITY` | `Developer ID Application: NAME (TEAMID)` |
   | `APPLE_ID` | the Apple ID used for notarisation |
   | `APPLE_PASSWORD` | an app-specific password, not the account password |
   | `APPLE_TEAM_ID` | the 10-character team identifier |

3. In `release.yml`, the macOS build step already reads
   `APPLE_SIGNING_IDENTITY` — set it from the secret instead of `""`, and add
   an import step before it:

   ```yaml
   - name: Import the Apple certificate
     if: startsWith(matrix.os, 'macos')
     env:
       APPLE_CERTIFICATE: ${{ secrets.APPLE_CERTIFICATE }}
       APPLE_CERTIFICATE_PASSWORD: ${{ secrets.APPLE_CERTIFICATE_PASSWORD }}
     run: |
       echo "$APPLE_CERTIFICATE" | base64 --decode > certificate.p12
       security create-keychain -p actions build.keychain
       security default-keychain -s build.keychain
       security unlock-keychain -p actions build.keychain
       security import certificate.p12 -k build.keychain \
         -P "$APPLE_CERTIFICATE_PASSWORD" -T /usr/bin/codesign
       security set-key-partition-list -S apple-tool:,apple: \
         -s -k actions build.keychain
   ```

4. Notarisation is separate from signing and also required, or Gatekeeper
   still blocks the app on first launch. Tauri performs it when `APPLE_ID`,
   `APPLE_PASSWORD` and `APPLE_TEAM_ID` are present in the build environment.

5. Set `bundle.macOS.signingIdentity` in `tauri.conf.json` (currently `null`).

### Adding a Windows certificate later

Requires an OV or EV code-signing certificate from a commercial CA
(≈200–500 USD/year). An **EV** certificate clears SmartScreen immediately; an
OV certificate builds reputation over time and will still warn at first.

1. Add repository secrets `WINDOWS_CERTIFICATE` (base64 `.pfx`) and
   `WINDOWS_CERTIFICATE_PASSWORD`.
2. Set `bundle.windows.certificateThumbprint` in `tauri.conf.json` to the
   certificate's SHA-1 thumbprint. `digestAlgorithm` and `timestampUrl` are
   already configured.
3. Add an import step before the build:

   ```yaml
   - name: Import the Windows certificate
     if: runner.os == 'Windows'
     run: |
       [IO.File]::WriteAllBytes("cert.pfx", [Convert]::FromBase64String($env:WINDOWS_CERTIFICATE))
       Import-PfxCertificate -FilePath cert.pfx -CertStoreLocation Cert:\CurrentUser\My `
         -Password (ConvertTo-SecureString -String $env:WINDOWS_CERTIFICATE_PASSWORD -AsPlainText -Force)
     shell: pwsh
   ```

Timestamping matters: without it, signatures stop validating when the
certificate expires. `timestampUrl` is already set for that reason.

## Release artifacts

Tag a version and the workflow does the rest:

```bash
git tag -a v0.12.0-alpha.1 -m "Atlas Public Alpha"
git push origin v0.12.0-alpha.1
```

| Platform | Artifacts |
|---|---|
| Windows | `-setup.exe` (NSIS), `_portable.zip` |
| macOS | `.dmg`, `.app.zip` |
| Linux | `.AppImage`, `.tar.gz` |
| All | `SHA256SUMS.txt` |

Release notes are extracted from the matching `## [version]` section of
`CHANGELOG.md`, so the changelog is the source of truth rather than a
hand-written release body.

`workflow_dispatch` builds everything without publishing, which is how to test
a packaging change without cutting a release.

## First run, from the shell's point of view

`apps/desktop/src-tauri/src/bootstrap.rs` owns the sequence:

1. Resolve the data directory — `ATLAS_DATA_DIR` if set (portable installs),
   otherwise the platform's per-user application data directory.
2. `initdb` the bundled PostgreSQL, once, if `PG_VERSION` is absent.
3. Start PostgreSQL on a free loopback port.
4. Start `atlas-kernel`, which waits for the server, creates the `atlas`
   database if needed, and serves.
5. Poll until the API port accepts connections.

Ports are allocated by binding `127.0.0.1:0` and releasing it. There is a
small race between release and re-bind, accepted deliberately: a fixed 5432
would collide with any existing PostgreSQL every single time, whereas this
collides rarely.

Shutdown reverses the order — kernel first, then `pg_ctl stop -m fast`.
Stopping the database under a live kernel fills the log with connection errors
that look like a fault when they are only a shutdown.

## Diagnosing a bundler failure

`tauri build` runs the platform bundler through `std::process::Command::output()`,
which captures the tool's stdout and stderr and then **discards them** unless the
log level is above `Error`. On a failure you get only:

```
failed to bundle project: `failed to run linuxdeploy`
```

That message contains no diagnostic information whatsoever. The release workflow
therefore passes `--verbose`, which switches the bundler to a path that surfaces
the tool's real output. If you are debugging a packaging failure by hand, do the
same — without it you are guessing.

This cost the RC1 Linux build two speculative fixes before anyone saw the actual
error. `APPIMAGE_EXTRACT_AND_RUN=1` was one of them, added on the theory that
linuxdeploy could not self-mount via FUSE on a CI runner. It was inert:
tauri-bundler already sets that variable itself *and* passes
`--appimage-extract-and-run`. The FUSE theory was never in the log; it was
pattern-matching.

### The AppImage / bundled-PostgreSQL interaction

linuxdeploy walks **every ELF file** in the AppDir to resolve shared-library
dependencies, including everything under `resources/`. A single file it cannot
resolve aborts the whole bundle.

The bundled Zonky PostgreSQL tree ships PostgreSQL's procedural-language
extensions, which link against language runtimes Atlas does not bundle:

| Extension | Wants |
|---|---|
| `plpython3`, `hstore_plpython3`, `jsonb_plpython3`, `ltree_plpython3` | `libpython3.6m.so.1.0` |
| `plperl`, `bool_plperl`, `hstore_plperl`, `jsonb_plperl` | `libperl` |
| `pltcl` | `libtcl` |

Python 3.6 is end-of-life and ships on no current distribution, so:

```
ERROR: Could not find dependency: libpython3.6m.so.1.0
ERROR: Failed to deploy dependencies for existing files
```

Atlas runs no in-database Python, Perl or Tcl — it talks to the server through
psycopg — so `prune()` in `infra/packaging/fetch_postgres.py` removes these,
along with the `.control`/`.sql` files that advertise them. This is the same
reasoning that already excludes `psql`.

Note that linuxdeploy stops at the *first* unresolvable dependency, so a build
going green proves only that one offender is gone. To check the whole tree at
once:

```bash
pg=apps/desktop/src-tauri/resources/postgres
export LD_LIBRARY_PATH="$PWD/$pg/lib:$PWD/$pg/lib/postgresql"
find "$pg" -type f -exec sh -c \
  'head -c4 "$1" | grep -q ELF && ldd "$1" 2>/dev/null | grep -q "not found" && echo "$1"' _ {} \;
```

That should print nothing. At the time of RC1 it scanned 99 ELF files clean.

## Known packaging issues

- **The bundle is large.** ~160 MB installed, most of it PostgreSQL. A future
  milestone could ship a smaller ICU-less PostgreSQL build.
- **PyInstaller metadata.** The spec copies distribution metadata explicitly.
  Without it the kernel runs perfectly but `importlib.metadata` cannot see its
  dependencies, so `/health/report` declares them all missing and a fresh
  install reports itself degraded. Adding a runtime dependency means adding it
  to the `copy_metadata` list in `infra/packaging/atlas-kernel.spec`.
- **No auto-update.** Deliberate — see `atlas_kernel/updates.py`. Atlas can
  tell you a release exists; it will not install one.
