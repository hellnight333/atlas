# Atlas Distributed Runtime & Worker Cluster

## Objective

Atlas remains a single desktop while execution becomes distributed. Workers may run on the
local machine, office servers, GPU workstations, a home lab, or cloud instances. Where a job
runs is a scheduling decision, never a user decision.

```
Runtime execution requested
        │
        ▼
   Approval gate (M008) ──── withheld ────► WAITING_APPROVAL
        │
        ▼
   Placement gate (M009)
        ├─ no eligible worker ─────────────► WAITING_PLACEMENT
        └─ worker chosen
              │  Reservation + Lease
              ▼
        Job → Worker → Provider → Asset
              │
              ▼
        lease + reservation released, slot returned
```

## Responsibilities

- worker registration, capabilities and lifecycle
- heartbeat tracking and timeout detection
- reservation and lease management
- deterministic worker selection
- execution ownership and recovery
- cluster health and load aggregation

## Non-Responsibilities

- no Kubernetes, Docker orchestration, Ray, Celery or message broker
- no cloud-specific logic
- no distributed planner or distributed graph
- no autonomous migration — recovery requeues, it does not silently relocate running work

`test_no_forbidden_orchestration_dependencies` asserts the first point against the source.

## The load-bearing rules

**Work is created only after a slot is reserved.** The placement gate runs after approval and
before the job exists. When nothing can take the entry: no `Job`, no provider, no worker
contact — the execution becomes `WAITING_PLACEMENT` and the queue entry follows.

**Every terminal path releases the slot.** Completed, failed, cancelled and timed-out
executions all call `_release_placement`. A leaked lease would permanently shrink capacity.

**Every runtime carries the gate.** `AgentFoundation` builds its own `AgentRuntime`, so the
composition root wires the dispatcher into both — the same trap that left an ungated path in
Milestone 008. `test_every_agent_runtime_in_the_api_carries_the_placement_gate` guards it.

## Naming

The cluster's machine model is `WorkerNode`, not `Worker`. The kernel already has a `Worker`
(the job executor), and the architecture contract test correctly rejected the collision. The
API, UI and docs still say "worker"; only the Python class differs.

## Capability is a routing hint, not a feasibility verdict

Workers advertise `text`, `image`, `video`, `audio`, `training`, `embedding`, `render`,
`python`, `filesystem`, `docker`, plus any custom strings. Plan-step capabilities are workflow
vocabulary; `_CAPABILITY_ALIASES` in `dispatcher.py` is the only place the two meet.

A capability outside the known worker vocabulary imposes **no** placement constraint. Work the
provider layer would reject therefore still reaches the provider layer and fails there, rather
than stalling forever waiting for a machine that cannot exist. Without this, two pre-existing
runtime tests turned a clean provider failure into an indefinite hang.

## Dispatcher

Selection inputs, in order of authority: health → capability → affinity → load → priority.
Ties break on worker id, so the same cluster state always produces the same placement.

- `ONLINE` and `BUSY` may receive work.
- `DRAINING` keeps what it has and accepts nothing new.
- `PAUSED`, `OFFLINE`, `ERROR`, `UPDATING` are skipped.
- A worker at `current_load >= max_concurrency` is skipped.

Affinity comes from `payload.worker_affinity` or the schedule's `queue_metadata`, matched
against worker tags. The UI never selects a worker, and providers never learn which machine
ran them.

## Reservations and leases

A **reservation** is the claim on a worker slot. A **lease** is the time-bounded right to
execute. Both are released explicitly; a lease that outlives its deadline is expired and
reclaimed so work is never stranded on a dead machine.

## Failure recovery

| Failure | Detection | Response |
|---|---|---|
| Worker offline | operator action or heartbeat timeout | dispatcher stops selecting it |
| Heartbeat timeout | `HeartbeatService.detect_timeouts()` (90s default) | worker marked `OFFLINE` |
| Worker crash | lease outlives its deadline | `LeaseManager.expire_due()` reclaims it |
| Lease expiration | `expire_due()` | `recover_execution` requeues the entry |
| Manual intervention | `POST /cluster/executions/{id}/recover` | same requeue path |

`POST /cluster/sweep` runs all detectors and recovers anything stranded. It is idempotent.

Recovery expires the lease, returns the slot, clears `worker_id`, sets the execution back to
`QUEUED` and the entry back to `READY` with `retry_count` incremented — so the next attempt is
placed fresh, possibly elsewhere. A heartbeat from a worker Atlas had given up on brings it
back online, but never overrides a deliberate operator state (`PAUSED`, `DRAINING`, `UPDATING`).

## The local worker

`create_runtime` registers an in-process worker (`worker-local`) advertising every known
capability with four slots. A single-machine install is a cluster of one, and nothing needs
configuring for Atlas to behave exactly as it did before Milestone 009.

## Persistence

Additive tables: `atlas_workers`, `atlas_worker_heartbeats`, `atlas_reservations`,
`atlas_leases`. `atlas_runtime_executions` gains `worker_id`, `lease_id`, `reservation_id` and
`placement_reason`.

## States

`QueueEntryStatus` and `RuntimeExecutionStatus` both gain `waiting_placement` — distinct from
`waiting_approval` and from `ready`.

## API

| Method | Path |
|---|---|
| GET | `/workers` |
| POST | `/workers/register` |
| POST | `/workers/heartbeat` |
| GET | `/workers/{id}` |
| POST | `/workers/{id}/pause` |
| POST | `/workers/{id}/resume` |
| POST | `/workers/{id}/drain` |
| GET | `/cluster` |
| GET | `/cluster/health` |
| GET | `/cluster/load` |
| GET | `/cluster/reservations` |
| GET | `/cluster/leases` |
| GET | `/cluster/waiting-placement` |
| POST | `/cluster/sweep` |
| POST | `/cluster/executions/{id}/recover` |
| POST | `/cluster/executions/{id}/retry-placement` |

Registration is idempotent per hostname: a reconnecting worker keeps its id and history.

## Events

`WorkerRegistered`, `WorkerDisconnected`, `WorkerHeartbeatReceived`, `WorkerPaused`,
`WorkerResumed`, `WorkerDraining`, `ExecutionAssigned`, `ExecutionMoved`, `ExecutionRecovered`,
`LeaseExpired`, `ReservationCreated`, `ReservationReleased`.

## Desktop

**Cluster Studio** (`/cluster`) — worker list with live load bars, cluster health and capacity,
execution placement table, awaiting-placement queue with retry, recovery sweep, and per-worker
detail: machine spec, GPU/memory/storage utilisation, reservations, leases and heartbeat log.

**Mission Control** — cluster health, worker map, execution placement, worker failures and
recovery status.

**Inspector** — execution worker, lease, reservation, worker health, capability match and
retry history.

**Activity Center** — worker failures and awaiting-placement executions appear as first-class
activities linking into Cluster Studio.

## What this milestone does not include

Placement, ownership, leasing and recovery are complete and exercised end to end. The
**remote worker agent process** — the long-polling client that would run on another machine
and pull leased work over a tunnel — is not part of this milestone; the endpoint list defines
no work-pull contract for it. Today every placed execution runs through the local
`JobExecutor`. The cluster layer is transport-ready; the transport itself is future work.

## Import constraint

`event_bus` imports `cluster.events`, so `cluster/__init__.py` performs **no eager imports** —
the same rule as `approval`. Import cluster submodules directly.

## Tests

`packages/kernel/tests/test_cluster.py` — 44 tests across registration, heartbeat and timeout,
dispatcher selection, reservations and leases, runtime placement, recovery, cluster state, the
API surface, and the architecture contracts.
