# Known issues

Version 0.12.0-alpha.1. Everything here is confirmed, not suspected.

Reporting one of these again is not needed — but extra detail on how it affects
you is genuinely useful.

## Significant

**No model provider integrations.** The two shipped adapters are simulations.
No API key will connect anything. This is the alpha's defining limit —
[PROVIDER_SETUP.md](PROVIDER_SETUP.md).

**The kernel API has no authentication.** It binds to localhost and assumes one
trusted operator. Do not expose port 8000 to an untrusted network.

**Builds are unsigned.** macOS Gatekeeper and Windows SmartScreen will warn.
Verify the SHA-256 — [INSTALLATION.md](INSTALLATION.md).

## Moderate

**Some sidebar links point at sample records.** "Project Workspace", "Studio
Workspace" and "Asset Workspace" navigate to fixed identifiers (`p1`, `s1`,
`a1`) that exist in mock data but not in a real installation. Reach real
projects through Home Workspace instead.

**The `/studios` endpoint returns fixed sample data** rather than a registry.
The studio screens themselves are real.

**The cluster is one machine.** There is no remote worker agent yet. Placement,
reservations and leases are fully implemented; there is simply nothing else to
place onto.

**Installers are large** — about 140 MB compressed, mostly PostgreSQL.
`libicudata` is 55 MB on its own and cannot be removed.

## Minor

**The macOS DMG has no styled background.** Tauri's DMG bundler drives Finder
over AppleScript, which fails on a headless machine. Atlas builds the image
with `hdiutil` instead — functionally identical, no artwork.

**The kernel test suite cannot run twice concurrently** against one database.
Several tests compare row counts to assert no work was created. Affects
contributors only.

**Provider credentials would live in local configuration**, not an OS keychain,
once providers exist.

## Fixed since the last milestone

Listed so you know they are gone:

- Atlas would start only once — a crash left PostgreSQL holding
  `postmaster.pid` and every later launch failed permanently.
- A packaged Atlas reported itself degraded because PyInstaller omitted
  dependency metadata.
- Quitting Atlas left the kernel and database running.
- The desktop showed mock data while a real kernel ran underneath it.
- `PATCH /agents/{id}` destroyed unsent fields.

## Reporting something new

[Issue templates](https://github.com/hellnight333/atlas/issues/new/choose).
Include the diagnostics export — it contains no credentials.
