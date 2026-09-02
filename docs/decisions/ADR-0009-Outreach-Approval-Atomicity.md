# ADR-0009 Outreach approval and the message it decides: what must be atomic

## Status

**Proposed — a decision input, not an implementation approval.** Written
2026-09-02 on Ayoub's instruction after two development-loop tasks on this line
(`t-b0dfd18dd170`, `t-6057acdb0b35`) ended CONTESTED after three review rounds
each. Both are frozen; neither is retried. Nothing in this document changes
production code, and no option below may be built until the owner chooses one
(DQ-010 in `.qevik/DECISION_QUEUE.md`).

Every claim here is against `main` at `28edb9c` and carries the file and line it
was read from. Where a claim comes from a frozen branch rather than `main`, it
says so.

## Context

Qevik writes to strangers only after a person approves the exact words. The
records of that approval live in two systems that grew separately:

- the **mission outreach path** — `POST /missions/{id}/outreach/approve` and
  `/send` in `packages/kernel/atlas_kernel/mission/api.py`, which is the only
  path production runs;
- the **Opportunity pipeline** — `OpportunityService` + `OutreachGate` over the
  kernel `ApprovalService`, in `packages/kernel/atlas_kernel/opportunity/`,
  which is complete as a module and **constructed nowhere in production**
  (`grep -rn "OpportunityService(\|OutreachGate(" packages/kernel/atlas_kernel`
  finds only `opportunity/service.py` itself and a docstring in
  `outreach/unreviewed.py`; the composition root at `composition_root.py:139`
  builds `ApprovalService` and `RuntimeApprovalGate`, not `OutreachGate`).

The two frozen tasks tried to wire the second system's approval outcomes back
onto the persisted message. The reviewer's sixteen findings across six rounds
reduce to one question this document exists to answer: **which writes must
succeed or fail together, and at which layer is that guaranteed?**

The repository already answers that question once, for signals:
`OpportunityRepository.approve_signal` (`opportunity/repository.py:558-620`)
does a guarded `UPDATE … WHERE state = 'open'` and the timeline `INSERT` in one
session, one commit, with the docstring "two writes that can half-happen would
leave either an approval nobody can attribute or a decision that never took
effect". That precedent is the anchor for everything below.

---

## A. Current reality

### A0. The persistence model every path is built on

- `SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False,
  future=True)` — `atlas_kernel/db.py:19`.
- **Every repository method opens its own `with SessionLocal() as session:`
  and commits inside it.** `opportunity/repository.py` has 52 such blocks and
  18 commits. Four of them execute more than one statement before committing
  (`approve_signal`, `record_contactability`, `save_opportunity`,
  `_save_message_expecting`); every other write is one statement, one commit.
- There is no session passing, no unit of work, no outbox. A service method
  that calls two repository methods has two transactions with a gap between
  them. That is a property of the codebase, not of one module.
- The event bus is **synchronous and in-process**: `EventBus.publish`
  (`event_bus.py:494-499`) calls each handler in order with no `try/except`. A
  handler that raises propagates into the publisher, after whatever the
  publisher already committed.
- `atlas_outreach_messages.status` is `TEXT NOT NULL DEFAULT 'draft'` with no
  CHECK constraint (`db.py:1334`). A new status value is a Python enum change,
  not a schema migration.

### A1. Production approval — `POST /missions/{id}/outreach/approve`

`mission/api.py:1178-1268`. Reads first (`_one`, `get_signal`, `get_business`,
`publications_for`, `_prepare_for` — the server recomposes the message and
derives the fingerprint itself, then compares it to the client's claim at
`:1231-1237`). Then two writes:

| # | Write | Where | Session / commit |
|---|---|---|---|
| W1 | `INSERT atlas_business_events` kind `OUTREACH_EVENT`, detail `{mission_id, commit, recipient, channel, message_fingerprint, delivery: manual_by_operator, sent: false, note}` | `repository.approve_outreach`, `opportunity/repository.py:1364-1430` (statement at `:1417-1427`) | own session, commit |
| W2 | `INSERT … ON CONFLICT (id) DO UPDATE` on `atlas_outreach_messages` with `status = approved`, `approval_id = W1.id`, `approved_fingerprint`, `authorized_automated_at = now()` | `memory.save_message(message)` at `mission/api.py:1261` → `repository.save_message`, `opportunity/repository.py:1796-1860` (unconditional branch) | own session, commit |

**Failure windows and the states they leave**

- **F1 — after W1 commits, before W2 commits** (process death, connection
  loss, or any exception constructing `OutreachMessage` at `:1252-1260`).
  State: an approval event exists; no approved message row. `send_outreach`
  answers 409 "nothing has been approved for automated sending"
  (`:1297-1302`); `outreach_approvals_for` lists the approval; the dossier
  shows an approval with nothing behind it. **Repairable by a person
  re-approving** — that creates a second event and the row. The first event
  stays as an orphan for ever, which is the shape of confusion `t-cf853b7dbf36`
  had to explain away in the dossier.
- **C1 — two concurrent approves.** Neither write is guarded. Each request
  creates its own `OutreachMessage` (fresh `id`), so the result is two events
  and **two approved rows** for one mission. `message_for_mission` returns the
  newest by `created_at` (`:1910-1925`); the older approved row is never sent
  and never closed. No repair path exists in code; it is invisible unless
  somebody queries the table.

### A2. Production send — `POST /missions/{id}/outreach/send`

`mission/api.py:1271-1364`. Reads: `message_for_mission` (`:1296`; returns
"already sent" without writing if the newest row is SENT, `:1303-1308`), then
signal/business/publications, then `_prepare_for` again so the fingerprint is
re-derived (`:1327-1330`), `load_suppression`, `load_contact_history`
(`:1345-1348`). Then:

| # | Effect | Where | Transactional? |
|---|---|---|---|
| G | Guards inside `OutreachService.send`: status is APPROVED, `authorized_automated_at` set, fingerprint equal, not suppressed, not inside cooldown | `opportunity/outreach.py:252-334` | pure reads over already-loaded state |
| **X** | **SMTP delivery** | `self._channel.deliver(message)`, `outreach.py:337` | **no — external, irreversible** |
| — | `history.record(...)` | `outreach.py:342` | in-memory only (`outreach.py:169`: "the repository is the durable record") |
| W3 | unconditional upsert `status = sent` (or `failed` on a transport exception, `:339-341`), `provider_message_id`, `sent_at` | `memory.save_message(result)` at `mission/api.py:1356` | own session, commit |

Contact history is **derived from `status = 'sent'` rows**
(`load_contact_history`, `opportunity/repository.py:2197-2230`: `WHERE
m.status = 'sent' AND m.sent_at IS NOT NULL`). There is no other durable
record of a delivery. No business event is written on send in this path at
all — "sent" lives only in the message row.

**Failure windows**

- **F2 — after X, before W3 commits.** The message row still says
  `approved`. Contact history has nothing. The next `POST /send` — an operator
  clicking again, an HTTP retry, a second worker — passes every guard in G and
  **delivers the same message to the same stranger again.** This is the one
  window that is **not repairable from Qevik's records**: nothing in the
  database says the first send happened; only the SMTP provider knows. No
  database transaction can close it, because X is not in the database.
- **C2 — two concurrent sends.** Both read `approved`, both pass G, both
  deliver; W3 is an unconditional upsert so the second write silently wins.
  The guarded write that would prevent this — `save_message(...,
  expecting=OutreachStatus.APPROVED)`, landed at `b1ee024` — exists and **is
  not wired to this caller** (that task's brief forbade touching callers).
- **A refusal writes nothing.** `OutreachRefused` (suppressed, cooldown,
  fingerprint moved, wrong approval kind) returns `state: BLOCKED` at
  `:1351-1354` with no row change and no event. `outreach.py:306-313` even
  composes a `SUPPRESSED` copy of the message and then raises with only its
  detail, so `OutreachStatus.SUPPRESSED` is a value nothing ever persists.
  Consistent, not partial — but the timeline does not know the send was
  refused.

### A3. The Opportunity pipeline — not constructed in production

`opportunity/service.py` + `opportunity/gate.py` + `approval/service.py`. Every
sequence below is real code on `main`; none of it runs in production today.

**`OpportunityService.prepare`** (`service.py:127-173`): `save_proposal` →
`_record(PROPOSAL_GENERATED)` → `save_message(message)` with `status = draft`
(`:159`). Three sessions. The message row is born DRAFT and **nothing on
`main` ever moves it to AWAITING_APPROVAL** — `request_approval` does not
write the row.

**`OpportunityService.request_approval`** (`service.py:175-183`):

| # | Write | Where | Session |
|---|---|---|---|
| W4 | `INSERT atlas_approval_requests … ON CONFLICT (id) DO NOTHING`, metadata `{proposal fingerprint, business_id, proposal_id, recipient, channel}` — **no message id** | `gate.request` (`gate.py:89-112`) → `ApprovalService.create_request` (`approval/service.py:84-145`, persist at `:131`) → kernel `repository.create_approval_request` (`atlas_kernel/repository.py:3960-3983`) | own |
| W5 | `INSERT` approval history `created` | `ApprovalService._record` (`approval/service.py:132`, `:390-410`) → `create_approval_history_event` (`repository.py:4038`) | own |
| E1 | `event_bus.publish(ApprovalCreated)` — synchronous; a raising subscriber propagates here, **after W4 and W5 are durable** | `approval/service.py:139` | — |
| W6 | `INSERT atlas_business_events` kind `APPROVAL_REQUESTED` with `{approval_id}` | `OpportunityService._record` (`service.py:177-182`, `:286-314`) → `record_event` (`opportunity/repository.py:2087`) | own |

Windows: **F4** (W4 durable, no history), **F5** (a subscriber raises in E1:
the caller sees an exception while the approval request already exists — the
round-3 finding "Preserve claims when request creation persisted before
raising" on `t-6057acdb0b35`), **F6** (approval exists, timeline lacks
APPROVAL_REQUESTED). All three are **repairable by reading
`atlas_approval_requests`** — the approval row is sufficient truth — except
that on `main` the approval carries no message id, so "which message did this
approval ask about" is answerable only by fingerprint + proposal id.

**`OpportunityService.send`** (`service.py:187-222`):

| # | Effect | Where |
|---|---|---|
| — | `gate.authorise` — pure; `model_copy(status = APPROVED, approval_id, approved_fingerprint)` (`gate.py:114-158`); refuses unless the approval is APPROVED and the fingerprint matches | in memory |
| W7 | `_record(APPROVED)` business event | `service.py:197-202` — own session |
| **X** | SMTP via `OutreachService.send` | `service.py:205` |
| W8 | on `OutreachRefused`: `_record(SUPPRESSED)` then re-raise — the message row is **not** written | `service.py:206-212` |
| W9 | `save_message(sent)` — unconditional; the row goes `draft → sent/failed` directly, **`approved` is never persisted on the row** in this path | `service.py:218-219` |
| W10 | `_record(SENT / SEND_FAILED)` | `service.py:220-225` |

Windows: the same **F2** as production (after X, before W9 — not repairable
from records); **F9** (row sent, timeline lacks SENT — repairable: derive from
the row); **W7 before X** means the timeline says APPROVED even when the send
is then refused or fails, which is true (the approval happened) but reads as a
delivery to anybody who does not also read W8/W10.

**`ApprovalService.reject`** (`approval/service.py:238-265`; `approve` at
`:196-236` has the same shape):

| # | Write | Where |
|---|---|---|
| — | `_require_pending` — a **Python** read-then-check | `:239` |
| W11 | `UPDATE atlas_approval_requests SET state … WHERE id = :id` — **no state predicate** | `:249` → `repository.update_approval_request`, `atlas_kernel/repository.py:3985-4005` |
| W12 | history `rejected` | `:250-257` |
| E2 | `publish(ApprovalRejected)` | `:258-264` |

**Nothing on `main` subscribes to `ApprovalRejected`, `ApprovalExpired` or
`ApprovalCancelled` on behalf of outreach** (`grep -rn "subscribe(Approval"
packages/kernel/atlas_kernel` finds nothing). So in this pipeline a rejected
approval leaves the message row exactly where it was — DRAFT — for ever. That
is the defect both frozen tasks set out to fix. Two concurrent decisions race
at the Python check (C3); compare `ApprovalStore.decide` at
`actions/approval_gate.py:406-448`, the control plane's own approval table,
which guards in SQL: `WHERE id = :i AND status = 'pending'` and raises when
`rowcount` is 0.

### A4. What the frozen branches built (for the record, not for reuse)

- `devloop/t-b0dfd18dd170` (base `21dd3fc`): +1175 lines across `gate.py`,
  `service.py`, a test file. Added `record_decision(approval)` that finds the
  message behind an approval and writes REJECTED with `expecting=`. Findings
  ended on "claim the message atomically before creating an approval" and
  "persist the refusal only while the message remains open".
- `devloop/t-6057acdb0b35` (base `13cbf61`): +2034 lines across six files,
  including `composition_root.py`. Added a claim/release pair
  (`_claim`/`_release`, draft → awaiting_approval and back), a foreclosure
  subscriber `_foreclosed` registered via `watch_outreach_decisions`, and —
  the one piece that matches the `approve_signal` precedent exactly —
  `OpportunityRepository.close_message(message, *, expecting, event)`
  (`repository.py:1936-1961` on that branch): guarded `UPDATE` + timeline
  `INSERT`, one session, one commit. Round-3 findings: the handler is never
  registered in the API runtime (no composition root constructs
  `OpportunityService`); decisions are looked up by fingerprint rather than a
  bound message id; suppression and its event are two commits.

Neither branch is wrong about the requirement. Both are too large for one
review unit, and both wire a pipeline production does not run.

### A5. Summary of partial states

| State | How it arises | Detectable from records? | Repairable? |
|---|---|---|---|
| approval event, no approved row | F1 | yes (event without row) | yes — re-approve; orphan event remains |
| two approved rows, one mission | C1 | yes (query) | no code path; manual |
| **delivered, row still `approved`** | **F2** | **no** | **no — provider logs only; a retry resends** |
| double delivery | C2 | no | no |
| refusal not in timeline | any refusal | no | n/a — nothing wrong in the DB, only missing |
| approval request without history / pipeline event | F4, F6 | yes | yes — derive |
| caller raised after request durable | F5 | yes | yes — idempotent `ON CONFLICT DO NOTHING` |
| approval rejected, message still open | always, on `main` (no subscriber) | yes — join approval → message by fingerprint | yes — but only by hand today |
| row terminal, no event explaining it | any "guarded update then event" pair | yes | **no** — a guarded retry finds no open row (frozen-branch docstring, verified against `_save_message_expecting`) |

---

## B. The atomicity requirement

Stated as what must hold, separated by the layer that can hold it.

### B1. Database atomicity — same database, two tables, one fact

**A message's status change and the business event that attributes it must
commit together or not at all.** The event is the only record of *who* decided
and *why*; once the row is terminal, a guarded retry cannot recreate the event
(last row of A5). This is exactly the case `approve_signal` already handles for
signals, and it is achievable with a single session — no new machinery.

Applies to: reject (approval → message), suppression (if it is ever persisted),
send-recorded (row `sent` + event `SENT`), approve-for-automation (production
W1 + W2: the event and the row are one decision).

### B2. Application consistency — two aggregates, two services, one link

**An approval's terminal state and the message it decides must be reconcilable
from the records without a person.** They live in `atlas_approval_requests`
(kernel repository) and `atlas_outreach_messages` (opportunity repository).
They *could* share a transaction — same database — but only if one repository
call writes both, which today would mean one module reaching into the other's
tables. The weaker requirement is sufficient and is what the frozen branches
were reaching for: (i) the link is persisted in both directions (`approval_id`
on the message; the message id in the approval's metadata — not on `main`,
where the metadata carries only fingerprint and proposal id); (ii) the
follower write is idempotent and guarded (`expecting=`); (iii) a missed
follower is found by a scan, not by luck.

### B3. Not atomic and never will be — the external send

**SMTP is outside every transaction.** The requirement is idempotency, not
atomicity:

1. **Claim before delivering** — a guarded write `approved → sending` (or
   equivalent) so a concurrent or retried send finds no open row (closes C2).
2. **Record after delivering** — `sending → sent/failed` guarded on `sending`.
3. **A crash between the two leaves `sending`,** which means "may have been
   delivered; do not resend automatically; a person reconciles against the
   provider." That turns F2 from *undetectable and repeatable* into
   *detectable and blocked*. It does not make the send atomic; nothing can.

This is the requirement with the highest consequence — the only failure mode
that writes to a stranger twice — and it needs no transaction change at all,
only a caller that uses the guarded write that already exists.

### B4. Explicitly *not* required to be atomic

Approval-request creation with its history and the pipeline event (W4/W5/W6):
the approval row alone is sufficient truth and idempotent by `ON CONFLICT DO
NOTHING`; history and pipeline events are derivable. Making these one
transaction would buy nothing and would run the event bus's subscribers inside
an open transaction.

---

## C. Options

Each option is judged against the codebase as it is: per-method sessions,
a synchronous in-process bus, a production path that does not use the
Opportunity pipeline, and a development loop that now fails any task whose diff
leaves its declared paths.

### Option 1 — Named compound repository operations (the `approve_signal` shape)

**Approach.** Add to `OpportunityRepository` the few operations that need B1,
each doing its guarded `UPDATE` and its `INSERT atlas_business_events` in one
session: `close_message(message, *, expecting, event)` (lift from
`devloop/t-6057acdb0b35`, `repository.py:1936-1961`, unchanged in shape) and a
`claim_message(message, *, expecting, to, event)` for `approved → sending` and
`draft → awaiting_approval`. Services compose these; sessions stay inside the
repository as they do everywhere else. No status transition outside the
repository, no session leaves it.

- **Affected files.** `opportunity/repository.py` (+~70 lines);
  `packages/kernel/tests/test_outreach_repository_conditional.py`. Then, as a
  *separate* task, the two live callers: `mission/api.py` `approve_outreach`
  (W1+W2 → one call) and `send_outreach` (claim → deliver → record);
  `packages/kernel/tests/test_mission_api.py`.
- **Blast radius.** The repository's public surface grows by two methods;
  `save_message` and every existing caller are untouched. The caller task
  touches two routes.
- **Migration.** None. A `sending` status is a Python enum value; the column is
  unconstrained `TEXT`.
- **Backward compatibility.** Response shapes unchanged. Rows already
  `approved` continue to send under the new guard. Readers that switch on
  status (`unreviewed.py`, the dossier) must learn `sending` — one value.
- **Test impact.** Repository tests run against real Postgres (the existing
  conditional-write file, 757 s task, landed clean). Route tests already exist.
- **Operational / recovery.** F2 becomes a visible `sending` row; a control
  query "messages in `sending` older than N minutes" is the reconciliation
  list. B1 windows disappear.
- **Pros.** Matches the repo's only existing atomic precedent line for line;
  smallest change that closes the worst window; each half is one contract-sized
  task; nothing generic is introduced.
- **Cons.** Each compound operation is bespoke; the transaction boundary is
  implicit in the method name. At 52 sessions and four multi-statement
  methods that is the current convention, not a new cost.

### Option 2 — Session passing / Unit of Work

**Approach.** Give every repository method an optional `session` parameter
(default: open its own, as today); add a `UnitOfWork` context that opens
`SessionLocal.begin()` and threads it through; services wrap multi-write
sequences in it. `ApprovalService` and `OpportunityService` could then share a
transaction.

- **Affected files.** `opportunity/repository.py` (52 session blocks),
  `atlas_kernel/repository.py` (approval methods), `db.py`, both services,
  `gate.py`, every test that patches `SessionLocal`.
- **Blast radius.** The whole opportunity module and part of the kernel
  repository. This is the expansion shape that contested `t-422b20848039`.
- **Migration.** None to the schema; a wide, mechanical code change.
- **Backward compatibility.** Default `session=None` keeps old behaviour, so
  the change is additive at the signature level.
- **Test impact.** Broad: any test asserting one commit per call changes.
- **Operational / recovery.** Handlers on the synchronous bus would run inside
  an open transaction; a handler that opens its own session while the caller's
  is open is the idle-in-transaction pattern this project's Naml lessons warn
  about (`docs/LESSONS_FROM_NAML.md`). Recovery semantics do not improve over
  Option 1 for B1, and B3 is untouched.
- **Pros.** General; B2 becomes DB-atomic if one really wants approval and
  message in a single commit.
- **Cons.** A speculative abstraction the master context forbids ("no
  speculative abstraction"); closes no window Option 1 does not; large enough
  that the loop cannot review it in one unit; and the most dangerous window
  (F2) is not a transaction problem.

### Option 3 — Wire the Opportunity pipeline's decisions back (subscriber + reconciler)

**Approach.** The frozen branches' design with the reviewer's gaps filled:
persist the message id in the approval's metadata and `approval_id` on the
message at request time (a guarded claim `draft → awaiting_approval`);
subscribe an idempotent `record_decision` to `ApprovalRejected` /
`ApprovalExpired` / `ApprovalCancelled` **in the composition root** (which
means production starts constructing `OpportunityService` — a change to what
runs, not only to what exists); use Option 1's `close_message` for the write;
add a reconciler that scans "approval terminal ∧ message still open" and closes
what the subscriber missed.

- **Affected files.** `composition_root.py`, `opportunity/service.py`,
  `opportunity/gate.py`, `opportunity/repository.py` (Option 1 first), a new
  reconciler (module or control action), `tests/test_opportunity_approval_wiring.py`
  and the composition test.
- **Blast radius.** Medium-to-large: it is the union of both frozen branches
  minus their defects, plus a reconciler. It also makes a pipeline production
  does not use start receiving production events.
- **Migration.** None.
- **Backward compatibility.** Approvals created before the metadata carries a
  message id are matched by fingerprint (the fallback the reviewer objected
  to) or left for the reconciler.
- **Test impact.** Large; the two frozen test files total ~1,500 lines.
- **Operational / recovery.** Two mechanisms for one fact (subscriber for
  latency, reconciler for correctness). F5 remains: the bus is synchronous, so
  a raising subscriber still surfaces in the publisher after W11 is durable —
  the reconciler is what makes that acceptable.
- **Pros.** Keeps the kernel approval machinery (scopes, expiry, required
  approvers, policy engine) as the authority for outreach; honours the
  original design intent.
- **Cons.** Bridges a boundary rather than removing it; three review rounds
  twice could not fit it in one unit; wires a path with no production traffic
  while the path with traffic (A1/A2) keeps its windows unless Option 1 is
  done anyway.

### Option 4 — One state machine: the message row is the approval record

**Approach.** Accept what production already does. In the mission path the
approval *is* a business event plus the message row (A1); make that one
compound repository operation (`approve_outreach` writes event and row in one
session, guarded on the row's current status), add `reject_outreach` with the
same shape, and treat `OutreachGate` / `ApprovalService` as not the authority
for outreach — leaving the kernel approval system to jobs and runtime steps,
where `RuntimeApprovalGate` and `ApprovalStore` already use it.

- **Affected files.** `opportunity/repository.py` (two compound operations;
  Option 1 is a subset), `mission/api.py` (two routes, plus a reject route
  that does not exist today), `tests/test_mission_api.py`,
  `tests/test_outreach_repository_conditional.py`. The Opportunity pipeline's
  gate is left as is — unused, as it is now.
- **Blast radius.** The live path only.
- **Migration.** None.
- **Backward compatibility.** Existing approval events keep their shape
  (`delivery: manual_by_operator, sent: false`); the row gains guards, not
  columns.
- **Test impact.** Route and repository tests; no change to approval-service
  tests.
- **Operational / recovery.** B1 and B2 collapse into one table plus one event
  table written together; B3 as Option 1. Nothing to reconcile across
  services because there is one writer.
- **Pros.** Removes the cross-service seam instead of bridging it; smallest
  total surface that closes every window in A5; it is the path that has
  production evidence.
- **Cons.** Decides that outreach approval is a *mission* decision and not a
  *kernel* approval — no policy engine, no expiry, no required-approver
  count for outreach unless re-added on the row. **That is a product
  decision, and it is the owner's.**

---

## D. Recommendation

**Do Option 1 first, unconditionally; then choose between Option 3 and
Option 4 — and that choice is the decision being asked for.** Option 2 is not
recommended under any answer.

Evidence for the ordering:

1. **The worst window is not a transaction problem.** F2 (delivered, row
   still `approved`, retry resends) is closed by a claim-before-send using the
   guarded write that already exists (`b1ee024`, `repository.py:1862-1907`).
   Every option needs this; none of the frozen work touched the route that
   has the window.
2. **The repository already has the pattern.** `approve_signal`
   (`repository.py:558-620`) is a guarded update plus an event in one session,
   with the same justification in its docstring. `close_message` on the frozen
   branch is that pattern applied to messages, unchanged in shape. Lifting it
   is a repository-only task with an explicit contract
   (`opportunity/repository.py` + one test file), the same shape as `b1ee024`,
   which landed in one clean round.
3. **It is the intersection of Options 3 and 4.** Whichever the owner picks,
   the compound operations are used as-is. Doing them first does not
   pre-empt the decision.
4. **The loop can now bound it.** Every task carries an allowed-path contract
   measured on the committed diff (`docs/DEVLOOP_SCOPE_CONTRACT.md`); the
   expansion that sank both frozen tasks is structurally impossible for the
   next attempt.

On the decision itself, the evidence leans to **Option 4**: production runs
the mission path and nothing else; the kernel approval system has no outreach
subscriber on `main` and never had one; the two attempts to bridge the seam
were the two largest review units this loop has produced. But the thing
Option 4 gives up — policy, expiry and approver-count for outreach — is a
property of how Qevik wants to govern writing to strangers, and DQ-005
("outreach policy for businesses that did not request contact") is still OPEN.
Choosing Option 4 without that answer would be deciding DQ-005 by
architecture. So this document stops at the recommendation and the owner
chooses.

**What this document does not authorise.** No retry of `t-b0dfd18dd170` or
`t-6057acdb0b35`; no unit of work; no session passing; no repository redesign;
no change to any production route. When an option is chosen, the work is
enqueued as contract-bounded tasks in this order: repository compound
operations (repository + its test file) → the send route (claim/record) → the
approve route (event + row in one call) → whatever the chosen option adds.

## Consequences

- Until an option is chosen, F2/C2 remain live on the production send route.
  Mitigation in force today: sending is a separate, deliberate operator action
  (`mission/api.py:1271-1290`), and the SMTP channel is the only automated
  transport. No automated sender runs on a schedule.
- `OutreachStatus.SUPPRESSED` remains a value nothing persists; the refusal
  reason reaches the operator only in the HTTP response.
- The two frozen branches stay as they are — evidence of the requirement, not
  a starting point. Their one reusable artefact is `close_message`.
