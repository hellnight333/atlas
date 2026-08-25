# The fabric, wired

*One mission runs the whole path, on the real host, against real PostgreSQL,
inside a real sandbox. 27/27 end to end, 7/7 for two workers racing.*

Three things were built and connected to nothing. This is the wiring, and it is
deliberately thin — no second orchestrator, no second registry, no second budget.

    control plane → mission → scheduler → atomic claim → worker
    → agent registry → adapter → tool contract → sandbox
    → evidence → report → complete

## What was wired

### The scheduler decides order

`pass_once` sorted queued missions by timestamp and took the first. That is not
an ordering policy, it is the absence of one: it could not tell urgent from
routine, could not honour a deferral, and would start a mission whose budget or
credentials could not carry it to the end.

It now asks `scheduler.plan()` and takes `dispatchable`. When nothing is
dispatchable it **logs why** — a worker that prints nothing while five missions
sit BLOCKED looks healthy, and that is why nobody notices for a week.

The scheduler decides *order*, never *whether*. Every mission it sees is one
policy already queued.

### The atomic claim decides who, and does not pretend

`--claims-dsn` builds `PostgresClaims`; `--require-atomic-claims` makes an
unreachable database a **refusal to start**.

That flag exists because the alternative is the worst kind of failure: an
operator believes two workers are safe, the DSN is wrong, both workers fall back
to local claiming, both run the same mission, and two commits of the same change
appear with no error anywhere. Loud and recoverable beats quiet and wrong.

The claim is taken before anything touches the mission and released in a
`finally`. Losing the race is ordinary, not an error.

### The registry, the adapter and the tool contract decide how

`mission/adapter.py` is the join that did not exist. `Agent.tools` was a list
nobody consulted and the sandbox was a capability nothing used.

The adapter **derives** the isolation from the agent's own record:

    needs_network(agent)  →  Isolation(network=…)
    agent.blocked_by      →  a refusal, before anything starts
    agent.needs_sandbox   →  Bubblewrap, or a refusal

A caller that could hand in its own `Isolation` could hand in one with the
network on and the workspace set to `/`. It reads the declaration instead, so
the confinement matches what the registry promised.

An agent that is *not* required to be sandboxed is still run inside one where
the host has it. Containment costs nothing here, and an executor with a bug is
still a process.

### The control plane can plan

`POST /api/missions/{id}/plan` was missing. A mission could be submitted and
approved through the API but only *planned* through chat, so anything not driven
by a conversation had no way to become executable.

The agent **proposes**; the route moves the mission to `AWAITING_APPROVAL`,
which is exactly where a person decides. Nothing here can queue work. A
model-backed agent is refused with 501 rather than half-implemented — a model
proposal belongs in chat, where the conversation that justifies it is recorded
beside it.

## The acceptance mission

`self-check`, a real agent record: executor-backed, reversible, tools `shell`
and `filesystem`, no credentials, no network, no provider, no spend.

Three declared steps, defined once in `adapter.SELF_CHECK_STEPS` because the
control plane proposes them and the worker executes them — two copies would
drift, and the drift would be invisible: the plan a person approved would stop
describing what ran.

| Step | Proves |
|---|---|
| write a file | the workspace is writable |
| read it back | what was written survives |
| `cat /etc/shadow` must **fail** | nothing outside the workspace is reachable |

The third step is the interesting one. It runs as root on the host. Without the
sandbox it would succeed, the step would fail, and the mission would fail. It
passed, at `confinement=FULL` — so the containment is *asserted by the mission*,
not assumed by the harness.

## Four defects found by running it

None was visible from the source.

**The API and the worker disagreed about where reports live.** The worker wrote
the report, the mission pointed at it, and `GET /api/missions/{id}/report`
returned 404 — the route resolved `report_path` against the *repository* root
while the worker wrote under its `--reports` root. In production the console
would have said "no report" about a report that existed. `reports_root` now has
one owner and both derive it from `QEVIK_STATE`.

**Commits died on the server with "Committer identity unknown".** `--author`
sets who *wrote* a change; git still refuses without a committer, which it takes
from `user.email` in whatever global config happens to exist. On a developer
machine it does; on the server it does not. The mission did all of its work and
died at the last step. A worker's identity belongs to the worker, so it is now
passed through `GIT_COMMITTER_*` per invocation — nothing about the host is
modified, and the argv allow-list in `_git` stays intact rather than being
widened to admit `-c`.

**The agent's own account of its work was computed and dropped.** `result.report`
was set by the worker and never passed to `reports.write`, so a report could say
a mission succeeded without saying what was checked. The report now carries an
**Evidence** section, per step, with what each one establishes.

**A verification check asserted a mechanism rather than a property.** The
two-worker race expected the loser to log "went to another worker". It did not —
the winner had already moved the mission out of `QUEUED`, so the loser's
scheduler pass never saw it. Both outcomes are correct; what would be wrong is
both running it. The check now asserts *that*.

## Verified

### End to end, on qevik-core-01 — 27/27

Real HTTP server in its own process, real worker process, real PostgreSQL, real
bubblewrap, and the control plane **killed** while the worker runs.

- submitted through the API → `draft`
- `self-check` proposed → `awaiting_approval`, **not** queued
- a model-backed agent refused with 501
- the scheduler put it in `WAITING`, `dispatchable=[]` — an agent's proposal is
  not an authority
- operator approved → `queued`, and only then `dispatchable=[the mission]`
- control plane killed; worker ran it as a separate process, reporting
  Postgres-backed claiming
- new control plane: **complete**, with a commit, and the full lifecycle
  `draft → planning → awaiting_approval → queued → processing → testing →
  reviewing → committing → complete`
- durable report exists, names each step, and records that nothing outside the
  workspace was reachable
- restarted **again**: still complete, still pointing at its report

### Two workers, one mission — 7/7

Both started at the same instant against the same queued mission, both required
to use Postgres-backed claims.

- exactly one claimed it
- the other did not run it
- exactly **one** `processing` transition on the timeline
- exactly **one** commit
- the mission completed once

## What is still not wired

Stated rather than implied:

- **`budgets.reserve()` is still not called from the worker.** The scheduler
  consults the tenant balance before dispatch, so a mission that cannot be
  afforded is blocked before it starts — but per-mission, per-agent and
  per-conversation allowances are not charged at execution time.
- **`Conversation` is still not persisted.**
- **No model-backed mission has been run through this path.** The wiring is
  agent-agnostic and the `self-check` agent proves it; a `cli-implementer`
  mission additionally needs a credential.
- **The deployed control plane still runs with `LocalClaims`.** The worker takes
  `--claims-dsn`; setting `QEVIK_CLAIMS_DSN` for the service is a deployment
  decision, and `/api/health` reports `SINGLE_WORKER_ONLY` honestly until it is.
