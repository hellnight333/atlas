# The Worker API

The contract between the Atlas kernel and a machine that does work for it, and
what that machine is assumed to have.

Written while waiting for the first GPU worker. It describes **what exists
today**, which is a single-worker contract, and marks separately what is
deliberately not built yet. Multi-worker scheduling and distributed execution
are not implemented and should not be until one worker has actually run — every
choice in that area is a guess until there is a machine to be wrong about.

Companion document: `docs/GPU_WORKER.md` covers what a GPU box specifically
needs. This one covers the contract any worker honours.

---

## The shape

A worker is a process that leases work from Postgres and does it. It is not a
server. Nothing connects to it.

```
                    ┌──────────────────────────┐
   kernel host      │  Postgres (control plane)│      GPU worker
   ───────────      │   atlas_jobs             │      ───────────
   enqueue ────────►│   status = queued        │◄──── poll  (outbound)
                    │                          │
                    │   status = running       │◄──── claim (outbound)
                    │   status = succeeded     │◄──── report(outbound)
                    └──────────────────────────┘
```

**The worker opens no ports.** That is the load-bearing property: a GPU box that
accepts inbound connections is one you have to firewall, certificate, monitor
and patch. Outbound-only means a laptop on hotel wifi is as valid a worker as a
rack machine, and the security surface is Tailscale's rather than ours.

---

## What exists today

### `Worker` — `atlas_kernel/worker.py`

| Method | Behaviour |
|---|---|
| `poll_once()` | Returns the first `QUEUED` job and marks it `RUNNING`, or `None` |
| `execute_job(job)` | Resolves the capability, evaluates placement, executes, returns a result dict |
| `execute(job, cancellation_token=None)` | `execute_job` with a cancellation check first |
| `run_loop(interval_seconds, stop_after)` | Poll, execute, sleep, repeat |

`execute_job` always returns the same shape, whether it succeeded or not:

```python
{
    "job_id": str,
    "status": "succeeded" | "failed" | "cancelled",
    "provider": str | None,
    "output": dict,
    "error": str | None,
    "asset_id": str | None,
}
```

Two failures are handled before any provider is touched, and both mark the job
*and its run* failed and publish `JobFailed` + `RunFailed`:

- an unknown `capability_id` on the job
- a placement decision the policy engine refuses

### The unit of work — `Job`

```python
Job(
    id, run_id, action,
    payload: dict,                  # what to do; shape is the action's business
    status: JobStatus,              # queued → running → succeeded | failed | cancelled
    attempts: int,
    priority: int,
    capability_req: CapabilityRequest,   # what the work needs; how placement is decided
    execution_decision_id: str | None,   # written by the kernel when placed
    provider_name: str | None,
    output: dict,
    produced_asset_ids: list[str],
)
```

`capability_req` is the only thing placement reads. A worker advertises
capabilities; a job requires them; nothing in between names a provider or a
machine.

### The entrypoint — `workers/gpu/run_worker.py`

```bash
python workers/gpu/run_worker.py --interval 1.0
```

Builds a runtime from `create_runtime()` and loops. `--stop-after N` exits after
N iterations, which is how it is tested.

### Cluster primitives that exist but are **not** wired to the media path

M009 built these. They work and are tested. The Media Factory does not use them
yet, and connecting them is part of finishing M013 rather than something to do
speculatively now.

| Service | What it offers |
|---|---|
| `WorkerRegistry` | register, pause, resume, drain, mark offline/error, adjust load |
| `HeartbeatService` | `record()`, `stale_workers()`, `detect_timeouts()`, history |
| `LeaseManager` | reserve → acquire → renew → release, and `expire_due()` |
| `ClusterStateService` | health, load, snapshot |

A worker registers with `WorkerRegistration(hostname, resources, capabilities,
max_concurrency, …)` and reports `HeartbeatReport(worker_id, status, metrics)`.
`WorkerCapability` has known values — `video`, `image`, `audio`, `render`,
`python`, `docker`, and others — and workers may advertise custom strings
beyond them.

---

## Deployment assumptions

What a worker machine is assumed to have. Everything here is an assumption the
first bring-up should confirm or correct rather than a specification anyone has
validated.

### Process model

- **One worker process per machine**, `max_concurrency = 1`, for now. One GPU
  serialises anyway, and concurrency is a scheduling question that should not be
  answered before there is a machine to measure.
- Run under a supervisor — systemd on Ubuntu — with restart-on-failure. The loop
  has no internal recovery: if it dies, something outside it must start it again.
- Stateless between jobs. Everything durable is in Postgres or the asset store,
  so a worker can be destroyed and rebuilt with no migration.

### Configuration

Environment only, no config file:

| Variable | Purpose |
|---|---|
| `ATLAS_DATABASE_URL` | Control-plane Postgres over the tailnet. **Required.** |
| `ATLAS_PROFILE` | `production` on a real worker |
| `ATLAS_DATA_DIR` | Scratch and local assets |
| `ATLAS_LOG_LEVEL`, `ATLAS_LOG_JSON` | Logging; JSON when shipping to a collector |
| `ATLAS_HEARTBEAT_TIMEOUT_SECONDS` | When the kernel calls a worker stale |
| `ATLAS_LEASE_SECONDS` | How long a claim is held before it can be reclaimed |
| `ATLAS_OFFLINE` | Refuse cloud providers entirely |
| `ATLAS_ALLOW_CLOUD_PROVIDERS` | Local-first is routing; this is a hard switch |

### Network

- **Outbound only.** Postgres over Tailscale. No listening sockets.
- ComfyUI, when present, binds **loopback** — the adapter is on the same box, so
  nothing else has a reason to reach it.
- No inbound firewall rules should be needed. If bring-up seems to want one,
  something has been placed on the wrong side of the line.

### Storage

- Scratch for renders, cleaned between jobs.
- Assets go to the store the kernel is configured with. A worker writing only to
  local disk is fine for one worker and becomes wrong the moment there are two,
  which is a NAS/MinIO decision to make when the second machine exists.

### Failure expectations

| Failure | Today | Intended |
|---|---|---|
| Worker dies mid-job | Job stays `RUNNING` forever | Lease expiry requeues it |
| Provider fails | Job `FAILED`, run `FAILED`, events published | Same |
| Postgres unreachable | Loop raises and the process exits | Supervisor restarts; backoff |
| Two workers, one job | **Both take it** | `SKIP LOCKED` |

---

## Deliberately not built yet

Named so nobody builds them speculatively, and so nobody is surprised to find
them missing.

**`Worker.poll_once` has no `SKIP LOCKED`.** It scans for the first queued job
and marks it running, in two statements. Two workers will race and both will
take the same job. `CLAUDE.md` specifies `SKIP LOCKED`; the code predates having
anything to run it on.

**No lease expiry on the render path.** `LeaseManager` exists and does exactly
this, and the media path does not call it. A worker killed mid-render leaves its
job `RUNNING` with nothing to notice.

**No worker registration in the render path.** `WorkerRegistry` and
`HeartbeatService` exist; the media render path does not register or heartbeat,
so the kernel cannot currently tell a busy worker from an absent one.

**No placement across workers.** `ExecutionPolicyEngine` picks a provider; it
does not pick a machine. With one worker that distinction does not exist.

**No concurrency within a worker.** One job at a time.

All five are correct to defer. Every one of them is a guess about behaviour that
has never been observed, and the cost of guessing wrong is a design that has to
be undone rather than extended. The first worker will answer most of them in an
afternoon.

---

## The order to do this in

1. **One worker, one job, end to end.** Nothing else matters until a real render
   completes and lands in the Library.
2. **Then** registration and heartbeats, so the kernel knows the worker exists.
3. **Then** leases and `SKIP LOCKED`, when there is a second machine to race.
4. **Then** placement and concurrency, informed by measurements rather than
   estimates.

Steps 2–4 are cheap once step 1 is real, and are all guesswork before it.
