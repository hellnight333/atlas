# Atlas Troubleshooting

Start here: `GET /health/report`. It names the failing component and why.
Then `GET /diagnostics` for an export you can paste into a bug report — it
contains no credentials.

---

## The kernel will not start

**`ImportError: cannot import name 'AtlasRepository' … circular import`**

You imported `atlas_kernel.repository` or `atlas_kernel.event_bus` *first*.
Those modules participate in an import cycle and must be reached through the
canonical entry point:

```python
from atlas_kernel.composition_root import create_runtime   # correct
import atlas_kernel.api                                    # correct
from atlas_kernel.repository import AtlasRepository        # fails standalone
```

**`ConfigError: ATLAS_… is invalid`**

A configuration variable could not be parsed. The message names the variable.
This is deliberate: a typo fails loudly rather than silently taking a default.

**Database unreachable**

`/health/report` shows `database` as degraded with `unreachable: …`. Check
`ATLAS_DATABASE_URL` and that Postgres is accepting connections. The kernel
needs a real Postgres; there is no SQLite fallback.

---

## Work is not running

Executions stall in one of two distinct states. Check which:

```bash
curl localhost:8000/approvals/waiting-executions   # waiting_approval
curl localhost:8000/cluster/waiting-placement      # waiting_placement
```

**`waiting_approval`** — a governance policy requires a human decision. Open the
Approval Center, or `GET /approvals?pending_only=true`. Remember an approval
cannot be granted by the identity that requested it (403) or by someone outside
the policy's approver list (409).

**`waiting_placement`** — no worker could take the entry. The execution's
`placement_reason` says which constraint failed:

| Reason | Meaning |
|---|---|
| `no workers registered` | the cluster is empty |
| `no worker is online` | all workers paused, draining or offline |
| `no online worker advertises 'X'` | no machine has that capability |
| `no online worker matches affinity [...]` | tag mismatch |
| `every capable worker is at capacity` | all slots busy |
| `no worker is available to organization …` | cross-organization isolation |

Retry once the cluster can serve it:

```bash
curl -X POST localhost:8000/cluster/executions/{id}/retry-placement
```

---

## A worker went away mid-execution

Run the recovery sweep:

```bash
curl -X POST localhost:8000/recovery/sweep -d '{"dry_run": true}'   # preview first
curl -X POST localhost:8000/recovery/sweep -d '{"dry_run": false}'
```

It marks unreachable workers offline, expires dead leases, requeues orphaned
executions and releases stale reservations. Nothing is deleted — executions are
requeued, so the work survives.

An execution counts as orphaned after 5 minutes without a heartbeat; a
reservation as stale after 10 minutes with no live lease.

---

## Cluster capacity looks wrong

If a worker shows load it is not actually carrying, a lease leaked. Every
terminal path releases its slot, so this should not happen — but the sweep
repairs it:

```bash
curl localhost:8000/cluster/load
curl -X POST localhost:8000/recovery/sweep -d '{"dry_run": false}'
```

`GET /cluster/health` lists `stale_heartbeats` and `expired_leases` explicitly.

---

## Permissions are denied unexpectedly

Ask the system to explain itself:

```bash
curl localhost:8000/organizations/{org}/permissions/{identity}
```

Every granted permission carries the role and membership that produced it.
Common causes:

- The membership **expired** — temporary access grants nothing after
  `expires_at`.
- The membership is **inactive**.
- The role belongs to a **different organization** — roles never leak across
  organizations.
- The membership is **project-scoped** and you are asking outside that project.

---

## A policy setting is not taking effect

Resolve it and read the source:

```bash
curl "localhost:8000/policies/resolve?organization_id=…&domain=security&project_id=…"
```

`sources` names which policy set supplied each key. If a key is in
`locked_keys`, a broader scope locked it and a narrower scope **cannot**
override it — that is the intended behaviour, not a bug.

---

## A backup will not restore

`POST /backups/validate` before restoring. Errors are specific:

| Error | Cause |
|---|---|
| `Checksum mismatch` | the archive was modified or truncated |
| `Section 'x' declares N but contains M` | the manifest disagrees with the data |
| `format … is newer than this build supports` | the archive came from a newer Atlas |

Restore is additive: existing rows are skipped, not overwritten. If restore
reports `restored: 0`, the records already exist — that is success, not failure.

Audit records are always skipped on restore, by design.

---

## Tests fail locally but not in CI (or vice versa)

**The suite is not safe to run twice at once.** Every test shares one Postgres,
and several assert "no new work was created" by comparing row counts before and
after. A second concurrent run inserts rows between those two reads and the
assertions fail — the code is fine. Run one suite at a time. CI is unaffected
because each job gets its own Postgres service container.

The test database **persists between runs**. Tests that use fixed identifiers
pass once and fail on re-run — every test must generate unique ids. If you see
a slug/id uniqueness error on a second run, that is the cause.

Performance smoke tests use deliberately generous thresholds because CI runs
under coverage instrumentation. They catch order-of-magnitude regressions, not
micro-benchmarks.

---

## Diagnostics reports a component I do not use

`plugins` always reports healthy with `sdk_available: false` — Atlas ships no
plugin SDK in this build. That is reported honestly rather than hidden, so the
absence is visible rather than mysterious.
