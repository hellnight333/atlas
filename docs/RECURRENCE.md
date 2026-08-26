# Recurring work

## The incident this came from

On **2026-08-26** the database backup on `qevik-core-01` was found to have failed
on every run since **2026-08-18**. Eight days with no verified backup.

The cause was small: `qevik-backup.service` runs as `User=qevik`, and the script
sourced `/opt/qevik/atlas.env` itself — a `root`-owned `0600` file. The other four
units never hit it because they use `EnvironmentFile=`, which systemd reads **as
root, before dropping privileges**. The script exited 1 into the journal.

The cause is not the interesting part. **Nothing anywhere reported it.** Not the
console, not the phone, not a report, not a blocker. The failure would have been
discovered during a restore.

That is what happens to any scheduled work that lives outside the mission
system. A systemd timer has no budget, no policy, no evidence, no report, and no
route to a screen anybody looks at. Qevik already does all four of those things
well — and stops at the edge of the mission fabric.

## The decision

**Recurring work is expressed as missions.** `packages/kernel/atlas_kernel/mission/recurrence.py`
declares work that repeats and creates a mission when an occurrence comes due.
Everything after that is unchanged: the scheduler orders it, the atomic claim
guards it, the worker proves it, the report survives a restart, and a failure
appears exactly where every other mission failure appears.

It is **not** a scheduler and **not** an orchestrator. It calls `service.create`
and `service.attach_plan` — the same two functions a request typed into the
console goes through — and stops. It never claims, dispatches, or runs anything.
There is one queue and one worker path, and this adds neither.

### Why not `AutomationEngine`

Atlas already has `AutomationEngine` + `AgentScheduler` (M007). It was inspected
first and deliberately not used: it enqueues via **Scheduler → Runtime → Worker**
and never touches `mission/`. The path that actually runs in production is the
mission fabric — `qevik-worker.service` → `infra/mission_worker.py` →
`mission/worker.py`. Putting recurring work on the other path would have been
the second orchestration system, not the avoidance of one.

## Three rules that are easy to get wrong

**Only the latest occurrence fires.** A daily job whose host was down for eight
days produces *one* mission, not eight. Eight market scans cost eight times as
much to say what one current scan says. Work where every occurrence genuinely
matters — billing periods, statements — is not a recurrence.

**An occurrence fires once.** `key_for(id, occurrence)` is a pure function of the
recurrence and the instant, so every process computes the same string. Two
guards, deliberately different in kind:

1. the caller holds the key through the existing `Claims` — the same
   `FOR UPDATE SKIP LOCKED` primitive missions use, no second claim system;
2. `assess` independently refuses an occurrence a mission already carries.

A lock can be reclaimed after a crash. A mission is a fact. Proven against the
production database in `infra/verify_recurrence.py`, with a negative control.

**A slow occurrence does not stack.** Yesterday still running means today does
not start. `BLOCKED` is treated as settled rather than live: a blocked mission
holds no worker, and treating it as live would let one blocked run end the
series in silence — the exact failure above, in a new costume.

## Unattended is a property of the work, not of the hour

`policy.decide` is asked the same question as for any mission, with one
difference: a recurrence states whether its work changes Qevik's own source.
Nothing that does may run unattended, whatever the hour. **A schedule is not a
person.**

`attach_plan` gained a `modifies_qevik_itself` passthrough, defaulting to `True`,
so no existing caller changed behaviour.

## The first real recurrence

`rec-execution-canary` — nightly at 02:30 UTC, inside the scheduler's night
window and clear of the 03:30 backup so the two do not contend for the disk.

It runs the self-check agent end to end: write into the workspace, read it back,
confirm nothing outside the workspace is reachable. If the scheduler, the claim,
the workspace, the sandbox, the agent, the evidence or the report stops working,
a **failed mission appears on the phone the next morning** — instead of the
failure being discovered when somebody needs the path to work.

That is the backup incident done the other way round.

It reaches the queue **with nobody asked**, and only because its origin is
`none`:

| | origin | outcome |
|---|---|---|
| the canary | `none` (EMPTY) | queued, unattended |
| the identical plan | `qevik` | awaiting approval |

Same plan, same agent, same cost. Only the origin differs — asserted directly in
`test_the_same_plan_against_qevik_waits_for_a_person`.

Proven end to end in `infra/verify_recurrence.py`: the tick creates it, policy
queues it, the real worker claims and runs it in an empty origin, and the report
is read back through a fresh `Timeline` object. A second tick in the same window
creates nothing.

## Origin, not a boolean

`Recurrence.modifies_qevik_itself` was a **field** — a claim that could disagree
with what the worker actually handed the mission. It is now `origin_name`, and
the kind comes from the resolved origin. `enqueue` additionally refuses a firing
whose resolved origin does not match the name the recurrence declared, because
creating the mission anyway would record one repository and use another.

## What was blocked, and no longer is

`RECURRENCES` was **empty**, for one specific reason.

Nothing can honestly declare `modifies_qevik_itself=False` today. The production
worker runs with `--repository /opt/qevik/atlas` — Qevik's own checkout — and its
committer writes a real commit into a worktree of that repository on every
mission. The branch is never merged and nothing reaches the running system, but
"a mission that writes into Qevik's own repo" is exactly what the flag asks
about. Answering `False` because the branch is discardable would be picking the
convenient reading of a claim the policy layer relies on.

That was resolved by `mission/scratch.py` and `mission/origins.py`: a mission
with an EMPTY origin has a real repository to work in that is not a clone of
Qevik, so it can honestly say it does not modify Qevik — and unattended overnight
work follows.

A recurrence naming `qevik` still waits for a person. A schedule is not a person.

## Files

| Path | What |
|---|---|
| `packages/kernel/atlas_kernel/mission/recurrence.py` | the module |
| `packages/kernel/tests/test_recurrence.py` | 31 tests |
| `infra/verify_recurrence.py` | real processes, real Postgres race |
| `infra/mission_worker.py` → `tick_recurrences` | the tick, inside the existing worker |
| `infra/qevik-backup.service` | `EnvironmentFile=`, the incident fix |
