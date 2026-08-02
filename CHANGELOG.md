# Changelog

All notable changes to Atlas. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

Versions before `0.12.0-alpha.1` were internal engineering milestones. They
were tagged and are listed here for continuity, but they were never released
to anyone.

## [Unreleased]

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

### Known limitations

Stated plainly rather than discovered later:

- **The kernel API has no authentication.** It binds to localhost and assumes
  one trusted operator. Do not expose port 8000 to an untrusted network.
- **Alpha builds are unsigned.** Gatekeeper and SmartScreen will warn. Verify
  the published SHA-256 checksum.
- **The test suite cannot be run twice concurrently** against one database.
- Provider credentials live in local configuration, not an OS keychain.

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

[Unreleased]: https://github.com/hellnight333/atlas/compare/v0.12.0-alpha.1...HEAD
[0.12.0-alpha.1]: https://github.com/hellnight333/atlas/releases/tag/v0.12.0-alpha.1
[0.11.0]: https://github.com/hellnight333/atlas/releases/tag/v0.11-production
[0.10.0]: https://github.com/hellnight333/atlas/releases/tag/v0.10-enterprise
[0.9.0]: https://github.com/hellnight333/atlas/releases/tag/v0.9-cluster
[0.8.0]: https://github.com/hellnight333/atlas/releases/tag/v0.8-governance
[0.7.0]: https://github.com/hellnight333/atlas/releases/tag/v0.7-foundation
