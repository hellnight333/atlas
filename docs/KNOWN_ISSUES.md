# Known issues

Version 0.12.0-alpha.1. Everything here is confirmed, not suspected.

Reporting one of these again is not needed — but extra detail on how it affects
you is genuinely useful.

## Classification for Alpha RC1

| Class | Meaning | Count |
|---|---|---|
| **Release blocker** | Must be fixed before RC1 ships | **0** |
| **Post-alpha** | Real, planned for 0.13 | 5 |
| **Future roadmap** | Deliberate scope, not defects | 4 |

**No release blockers remain.** The one blocker found during RC preparation —
four sidebar links pointing at sample identifiers that do not exist in a real
installation — was fixed rather than documented, because a navigation item that
leads to an empty screen is exactly the dishonesty this release is meant to
avoid.

Nothing below prevents a user installing Atlas, completing setup, installing a
demo and running real work. That is the RC1 bar, and it is met.

## Post-alpha — planned for 0.13

### Significant

**No model provider integrations.** The two shipped adapters are simulations.
No API key will connect anything. This is the alpha's defining limit —
[PROVIDER_SETUP.md](PROVIDER_SETUP.md).

**The kernel API has no authentication.** It binds to localhost and assumes one
trusted operator. Do not expose port 8000 to an untrusted network.

**Builds are unsigned.** macOS Gatekeeper and Windows SmartScreen will warn.
Verify the SHA-256 — [INSTALLATION.md](INSTALLATION.md).

### Moderate

**The `/studios` endpoint returns fixed sample data** rather than a registry.
The studio screens themselves are real.

**The cluster is one machine.** There is no remote worker agent yet. Placement,
reservations and leases are fully implemented; there is simply nothing else to
place onto.

**Installers are large** — about 140 MB compressed, mostly PostgreSQL.
`libicudata` is 55 MB on its own and cannot be removed.

### Minor

**The macOS DMG has no styled background.** Tauri's DMG bundler drives Finder
over AppleScript, which fails on a headless machine. Atlas builds the image
with `hdiutil` instead — functionally identical, no artwork.

**The kernel test suite cannot run twice concurrently** against one database.
Several tests compare row counts to assert no work was created. Affects
contributors only.

**Provider credentials would live in local configuration**, not an OS keychain,
once providers exist.

## Future roadmap — deliberate, not defects

These are decisions. See [ROADMAP](https://github.com/hellnight333/atlas/blob/main/docs/ROADMAP.md).

- **No auto-update.** Software that replaces its own code unasked is a security
  property nobody agreed to.
- **No telemetry by default**, and no server to receive it.
- **No autonomous execution.** Anything irreversible waits for a human.
- **No marketplace, cloud, billing or mobile.** Out of scope by design.

## Fixed since the last milestone

Listed so you know they are gone:

- Atlas would start only once — a crash left PostgreSQL holding
  `postmaster.pid` and every later launch failed permanently.
- A packaged Atlas reported itself degraded because PyInstaller omitted
  dependency metadata.
- Quitting Atlas left the kernel and database running.
- The desktop showed mock data while a real kernel ran underneath it.
- `PATCH /agents/{id}` destroyed unsent fields.
- Four sidebar links navigated to sample identifiers that do not exist in a
  real installation (fixed during RC1 preparation).

## Reporting something new

[Issue templates](https://github.com/hellnight333/atlas/issues/new/choose).
Include the diagnostics export — it contains no credentials.
