# Atlas

A personal AI Operating System. Not an app — a modular ecosystem that builds software,
media and businesses, running primarily on local hardware and reaching for cloud models
only when they are a clear win.

> **Start here:** [`CLAUDE.md`](CLAUDE.md) is the master context. Read it before
> writing or reviewing anything.

## Documentation

| Doc | What it covers |
|---|---|
| [CLAUDE.md](CLAUDE.md) | Master context, principles, scope discipline |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Layers, kernel components, compute topology, worker protocol |
| [docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md) | Local setup, commands, and engineering guardrails |
| [docs/CI.md](docs/CI.md) | CI pipeline and failure policy |
| [docs/TESTING.md](docs/TESTING.md) | Test suites, contract checks, and coverage |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Phases and their exit criteria |
| [docs/LESSONS_FROM_NAML.md](docs/LESSONS_FROM_NAML.md) | Production bugs already paid for once — read before writing provider or deploy code |
| [docs/decisions/](docs/decisions/) | Architecture Decision Records |

## The one rule

**No studio may call a provider directly.** All capability flows through the kernel.
This is what stops Atlas from decaying into a pile of disconnected tools. A change that
breaks it does not merge.

## Layout

```
packages/kernel      registry · queue · scheduler · bus · library · memory · recipes
packages/providers   uniform adapters (local + cloud), one module each
studios/             plugins: actions + recipes + one UI page each
workers/gpu          HP Z8 worker agent — polls the queue, never listens
apps/web             Next.js control surface
recipes/             versioned recipe YAML + ComfyUI API graphs
infra/               compose, Tailscale, MinIO, migrations
```

## Status

**Phase 0 — Kernel + vertical slice.** See [docs/ROADMAP.md](docs/ROADMAP.md) for the
exit criterion and the GitHub milestone for open work.

## Engineering

Local quality commands:

- `python -m ruff check packages/kernel workers`
- `python -m black --check packages/kernel workers`
- `python -m mypy packages/kernel/atlas_kernel`
- `python -m pytest packages/kernel/tests`

Contributing: [CONTRIBUTING.md](CONTRIBUTING.md) ·
Security: [.github/SECURITY.md](.github/SECURITY.md) ·
Changes: [CHANGELOG.md](CHANGELOG.md)

## Privacy

Atlas collects nothing by default. Telemetry is opt-in and off, the update
check is opt-in and off, and there is no Atlas-operated server for either to
talk to. See [docs/PRIVACY.md](docs/PRIVACY.md).

## License

Atlas is **source-available** under the
[Business Source License 1.1](LICENSE) — not an OSI open-source license.

Permitted, including commercially: personal use, use inside your own company,
research, education, and consulting work for a client. Not permitted: offering
Atlas to third parties as a hosted, managed or embedded service.

On **2030-08-03** this version converts to Apache-2.0 automatically.

Third-party components keep their own licenses — see [NOTICE](NOTICE), which
covers the two that need care: `psycopg` (LGPL-3.0) and `certifi` (MPL-2.0),
plus the bundled PostgreSQL.
