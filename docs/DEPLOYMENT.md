# Atlas Deployment

## What Atlas is, physically

| Component | What it is | How it runs |
|---|---|---|
| Kernel | Python package `atlas_kernel`, served by uvicorn | `python -m uvicorn atlas_kernel.api:app` |
| Desktop | Vite + React single-page application | `npm run build` → static `dist/` |
| Database | PostgreSQL 16 | required; the kernel will not start without it |
| Assets | Content-addressed files on disk | `data_dir` from configuration |

## Packaging status — read this before promising installers

Milestone 011 lists Windows, macOS and Linux packaging. **Native installers do
not exist and this milestone did not create them.** The reason is structural,
not effort:

`apps/desktop` is a browser application. Its dependencies are React, React
Router and Zustand — there is no Electron, no Tauri, no native shell. Producing
a signed `.exe`, `.dmg` or `.AppImage` requires *adding a desktop shell
framework*, which is a new architectural dependency. Milestone 011 forbids
architectural change and says "only hardening", so adding one here would have
contradicted the brief.

What exists today:

- **Production web build** — `npm run build`, emitted to `apps/desktop/dist`,
  and published as a CI artifact on every run.
- **Portable profile** — `ATLAS_PROFILE=portable` keeps all state beside the
  binary in `./atlas-data`, which is the prerequisite for a portable bundle.
- **Offline profile** — `ATLAS_PROFILE=offline` refuses cloud providers.

What a future milestone must add for real installers: a shell framework
(Tauri is the lighter fit for this stack), platform build matrices, code signing
and notarisation, and an update channel. That is release engineering, which
Milestone 012 owns.

## Running the kernel

```bash
export ATLAS_DATABASE_URL="postgresql+psycopg://atlas:atlas@localhost:5432/atlas"
export ATLAS_PROFILE=production
python -m uvicorn atlas_kernel.api:app --host 0.0.0.0 --port 8000
```

The kernel creates its own schema and indexes on startup. `init_db()` is
idempotent: restarting never destroys data.

## Running the desktop

```bash
cd apps/desktop
npm ci
npm run build          # static bundle in dist/
npm run dev            # development server
```

Point the desktop at a kernel with `VITE_ATLAS_API_BASE_URL`.

## Startup sequence

1. Configuration resolves (defaults → profile → environment).
2. Logging configures for the profile.
3. `init_db()` creates missing tables and indexes.
4. The composition root builds every service.
5. The local worker registers, so a single machine is a cluster of one.

Schema validation and integrity checks **report** rather than raise. A degraded
database shows up in `/health/report` instead of preventing boot, because an
operator who cannot start the process cannot read the diagnostics either.

## Health and readiness

| Endpoint | Use |
|---|---|
| `GET /health` | liveness — cheap, no database work |
| `GET /health/report` | readiness — every component, with detail |
| `GET /diagnostics` | full export for a bug report |
| `GET /recovery/report` | what a recovery sweep would repair |

`/health/report` returns `healthy: false` when any component is degraded; the
`components` array names which one and why.

## Recovery after a crash

A process that dies mid-execution leaves work stranded. Run:

```bash
curl -X POST localhost:8000/recovery/sweep -d '{"dry_run": true}'   # preview
curl -X POST localhost:8000/recovery/sweep -d '{"dry_run": false}'  # repair
```

The sweep expires dead leases, marks unreachable workers offline, requeues
orphaned executions and releases stale reservations. It is idempotent, additive
and never deletes work. Each stage is isolated: one unrecoverable target cannot
prevent the rest of the sweep from repairing what it can.

## Backup

```bash
curl -X POST localhost:8000/backups/export -d '{"scope":"project","scope_id":"..."}' > backup.json
curl -X POST localhost:8000/backups/validate -d "{\"archive\": $(cat backup.json)}"
curl -X POST localhost:8000/backups/restore  -d "{\"archive\": $(cat backup.json), \"dry_run\": true}"
```

Backups carry **asset metadata, not asset bytes** — those live in the
content-addressed store. Archives are checksummed; a modified archive fails
validation before any restore is attempted. Restore is additive and idempotent:
existing rows are skipped, and audit records are never restored, because
rewriting history through a backup would defeat the append-only guarantee.

## Database

38 indexes are created at startup, covering every hot-path lookup. Verify with:

```python
from atlas_kernel.db import verify_schema, check_integrity
verify_schema()    # missing tables and indexes
check_integrity()  # orphaned rows across the joins the kernel relies on
```

Integrity checks report orphans; they never delete.

## Scaling out

Register a worker on another machine:

```bash
curl -X POST http://kernel:8000/workers/register -d '{
  "hostname": "office-a6000",
  "display_name": "Office-A6000",
  "capabilities": ["image", "video", "training"],
  "max_concurrency": 2,
  "tags": ["office", "gpu"]
}'
```

Then heartbeat every 30s or so (`POST /workers/heartbeat`); a worker silent for
90 seconds is marked offline and stops receiving work.

**The remote worker agent process does not exist yet** — see
`DISTRIBUTED_RUNTIME.md`. Placement, leasing, ownership and recovery are real
and tested, but every placed execution currently runs through the local
`JobExecutor`. Registering a remote worker records it in the cluster; it does
not yet cause work to execute on that machine.
