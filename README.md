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
