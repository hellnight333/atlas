# The Scheduler

*Status: implemented and green. Step 2 of the Munder-Difflin ordering.*

The worker used to take one queued mission per pass, oldest first. That was
correct, and it was not an operations department: it could not tell urgent from
routine, could not defer expensive work to a cheaper hour, could not notice that
a mission needed a credential nobody had entered, and could not decline to start
something whose budget would run out halfway.

`packages/kernel/atlas_kernel/fabric/scheduler.py` decides **order and
placement**. It never decides *whether*.

## What it is not allowed to do

Policy already decided whether. `ALLOWED` refuses illegal transitions,
`EXECUTORS` refuses unbackable promises, `REQUIRES_CUSTOMER_INPUT` refuses work
waiting on the customer, the two approval boundaries refuse unapproved work.
The scheduler never overrides any of them — and it does not import them, so it
cannot quietly grow a second, untested copy of a rule in the hot path.
`test_the_scheduler_does_not_re_implement_policy` reads the AST and fails on the
import.

It also cannot act. It returns a `Decision`; something else claims. That is what
keeps the atomic claim the single place two workers race, so a second scheduler
process reaching the same conclusion is harmless rather than a double-dispatch.
`test_the_scheduler_cannot_claim_or_dispatch_anything` checks the calls, not the
docstring.

## Five queues, and two that must never merge

| | |
|---|---|
| `NOW` | dispatch immediately |
| `NEXT` | ready, waiting only for capacity |
| `SCHEDULED` | deliberately later — a window was chosen |
| `WAITING` | a dependency, or a person who has been asked |
| `BLOCKED` | cannot proceed; the reason is named |

`WAITING` resolves by itself. `BLOCKED` never will. Merged, they produce a queue
where half the entries are progressing and half are dead and nobody can tell
which by looking — so the operator either chases things that were fine or
ignores things that were stuck.

Every decision carries a `why` that is a sentence a person can act on. Never
"queued": that is the outcome, not the reason.

One deliberate divergence from section L of the fabric architecture, which files
a missing credential under `WAITING`: it is `BLOCKED` here. Nothing resolves it
but a person typing a key — which is the definition of the other queue — and a
credential sitting in `WAITING` looks like it is on its way.

## The order of the checks is the policy

`decide()` runs them in this order, and the order is the design — asking "is
there capacity" about work that cannot run at all produces a queue full of
things that look imminent.

1. **Policy already refused it** → `BLOCKED`, carrying the recorded reason.
2. **A credential nobody has entered** → `BLOCKED`, naming each one and the
   Credential Centre. Blocked rather than waiting: nothing resolves it but a
   person doing something specific.
3. **Placement it cannot have** → `BLOCKED`. A mission needing a local worker
   with none attached is named, not silently queued forever.
4. **Budget** → `BLOCKED` *before* dispatch. A mission stopped mid-flight has
   spent the money and produced nothing.

   Priced and unpriced work are judged separately, because they are different
   questions. A priced mission is refused when its estimate exceeds what
   remains. An **unpriced** one is refused only when headroom is below
   `UNPRICED_NEEDS`, and the reason names the missing estimate rather than a
   size — the problem is that nobody priced it.

   The first version used the night-window threshold (`EXPENSIVE_UNITS = 50`)
   for both, which blocked every unestimated mission on the LIST plan (40 units)
   for ever. That is a wall, not a budget. Two thresholds, two questions.
5. **Waiting on a person or on other work** → `WAITING`, naming the outstanding
   dependencies rather than counting them.
6. **A window somebody chose** → `SCHEDULED`. A person's decision outranks the
   scheduler's own judgement.
7. **Expensive and unhurried** → `SCHEDULED` in the night window. Interactive
   work is never deferred; cheapness is not the point when somebody is waiting.
8. **Ready** → `NOW` if there is a free worker, `NEXT` if there is not — and
   `NEXT` is not a problem, so it says so.

Within a priority, oldest first. Ordering by priority alone starves the NORMAL
mission that has been waiting since Tuesday behind a steady trickle of newer
NORMAL work.

## Deferring is a decision, and it is enforced

`service.defer()` records `not_before` on the mission as an ordinary append-only
event. The mission **stays queued** — it is still work somebody wants done, and
moving it to `BLOCKED` would file it with the things that are never going to
happen.

`service.claim()` refuses a mission whose window has not arrived. Without that
the worker — which takes the oldest queued mission — would run the night job at
eleven in the morning, and the deferral would be a suggestion.

A deferral must name a future moment and a reason. "Deferred until yesterday"
reads as a decision while behaving as none; a deferral with no reason is
indistinguishable from a queue that is simply long, which is the exact confusion
`SCHEDULED` exists to remove.

## Durability

Nothing new is stored. `not_before` folds from the mission timeline like every
other field, so the window survives a restart.
`test_a_deferral_survives_the_process_that_made_it` writes it in one interpreter
and reads it in a `subprocess` that never saw it — with a negative control that
proves the same fresh process *would* have run the mission without the deferral,
so the test cannot pass against a scheduler that defers everything.

## Credential honesty

`usable_credentials()` in the mission API asks the same question `resolve()`
asks: is this provider's status outside `UNUSABLE`? A credential somebody typed
and nothing ever verified is exactly the case where the scheduler would dispatch
work that fails at the provider, after telling the operator it was running.

A sealed or unreachable vault yields the **empty set**. Not knowing which keys
work is not the same as knowing they all do, and scheduling on the optimistic
reading builds a queue of doomed missions.

An agent listing several providers needs *one* of them — they are alternatives.
Requiring all three would block work that runs perfectly well on the one key
somebody entered.

## Surfaces

- `GET /api/missions/schedule?concurrency=&local_worker=` — the five queues.
  A view: reading it appends no event, so a refreshed stale tab cannot start
  work twice. `concurrency` is clamped, because a query string is a request
  rather than an instruction.
- `POST /api/missions/{id}/defer` — `{until, reason}`. Requires `EXECUTE`:
  changing when work runs is an execution decision, not a read.
- Console → **Schedule**. The five queues drawn apart, each with its reason.

## What is not built yet

- **Provider rate limits** as a scheduling input. Declared in section L of the
  fabric architecture; not implemented. The scheduler cannot currently hold work
  back because a provider is near its ceiling.
- **"Whether a human is awake"** — the night window is a fixed local range
  (01:00–06:00), not a model of the operator's day.
- **Multi-worker capacity discovery.** `concurrency` is supplied by the caller;
  nothing counts live workers. Step 5 (Postgres-backed atomic claims) is what
  makes more than one worker safe at all.
- **Deadline-aware ordering.** A deadline defeats the night window but does not
  yet reorder against priority.

Each is a stated gap rather than a silent one.
