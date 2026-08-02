# Atlas Human Approval & Governance System

## Objective

The Approval System is the safety layer between Automation, Scheduler, Runtime and human
operators. Nothing in Atlas becomes autonomous. Anything capable of modifying important state
must be reviewable, pausable and auditable.

```
Runtime execution requested
        │
        ▼
   Approval gate ──── no policy matched ────► execution proceeds
        │
   policy matched
        │
        ▼
 ApprovalRequest (pending)   Runtime: WAITING_APPROVAL   Scheduler: WAITING_APPROVAL
        │
   human decides
        ├── approved ──► execution resumes ──► Worker ──► Provider ──► Asset
        ├── rejected ──► execution terminates as APPROVAL_REJECTED
        └── expired  ──► execution terminates as APPROVAL_REJECTED
```

## Responsibilities

- approval request lifecycle (create, approve, reject, cancel, expire, escalate)
- declarative policy evaluation
- immutable approval history
- runtime pause and resume
- approval queue with priority ordering

## Non-Responsibilities

- no autonomous approval
- no AI approval
- no self approval
- no policy learning
- no autonomous retries
- no execution without approval

## The load-bearing rule

**Runtime pauses before any work is created.** The gate runs at the top of `execute_entry`,
before the job exists. When consent is withheld:

- no `Job` is created
- no provider is selected
- the Worker is never reached
- the queue entry becomes `WAITING_APPROVAL`, which is a state distinct from `READY`

`test_runtime_pauses_and_creates_approval_when_policy_requires_it` asserts all four.

## Every runtime must carry the gate

`AgentFoundation` constructs its own `AgentRuntime`, so the composition root wires the gate
into **both** — the one it exposes and the one the agent service builds. Gating only the
composition-root runtime once left the `/runtime/schedule/{id}/start` path ungated;
`test_api_runtime_start_is_gated_too` and
`test_every_agent_runtime_in_the_api_carries_the_gate` exist to keep that hole closed.

## Policies are declarative

`ApprovalPolicyEngine` contains no rule of its own. Which scopes need approval, which cost is
too high, which project is exempt — all of it is policy data in `atlas_approval_policies`.
Adding a rule never means editing the engine.

| Mode | Behaviour |
|---|---|
| `always` | every action matching the policy requires approval |
| `never` | exempts matching actions |
| `scoped` | requires approval when a declared scope matches, or cost exceeds a threshold |

Scopes: `external_api`, `filesystem_write`, `network`, `provider_cost`, `project_publish`,
`delete`, `plugin_action`, `enterprise`.

Condition operators: `equals`, `not_equals`, `in`, `not_in`, `contains`, `greater_than`,
`less_than`, `exists`, `not_exists`. Fields support dotted paths (`payload.env`), so a policy
can address payload shape the engine knows nothing about.

**Scopes are declared, never inferred.** The gate reads `payload.approval_scopes` supplied by
the caller. The engine never guesses that an action named "delete" is destructive.

### Resolution order

Most specific first (project-scoped beats workspace-scoped beats global), then priority, then
creation time, then id — a total order, so the same context always resolves to the same policy.

## Decision guards

- **No self-approval.** The requester may never decide their own request (`403`).
- **Designated approvers only.** If a policy names approvers, nobody else may decide (`409`).
- **No double-voting.** The same actor cannot approve twice to satisfy a quorum.
- **Terminal is terminal.** An approved/rejected/cancelled/expired request cannot be re-decided.
- **Quorum.** `approvals_required` > 1 keeps the request pending until enough distinct
  approvers have signed off.

## Expiry

Policies may set `expires_after_seconds`. Expiry is checked lazily on read and by the
`expire_due()` sweep. An expired request cannot be approved, and its execution terminates.
Expiry is the only transition out of `PENDING` that carries no human actor — it is driven by
wall-clock time that a human configured.

## Persistence

Additive tables only:

- `atlas_approval_requests`
- `atlas_approval_history` — **append-only**; the repository deliberately exposes no update or
  delete method for it (`test_history_is_append_only`)
- `atlas_approval_policies`

`atlas_runtime_executions` gains one nullable column, `approval_id`.

## States

`QueueEntryStatus` gains `waiting_approval`. `RuntimeExecutionStatus` gains `waiting_approval`
and `approval_rejected`. Both are additive enum members; nothing matches these enums
exhaustively.

## Resume

A resumed execution **keeps its execution id**. `execute_entry` accepts an optional existing
record so the approval that gated it still points at a live execution. The gate is consulted
again on resume, so a still-pending approval simply pauses once more.

## API

| Method | Path |
|---|---|
| POST | `/approvals` |
| GET | `/approvals` |
| GET | `/approvals/{id}` |
| POST | `/approvals/{id}/approve` |
| POST | `/approvals/{id}/reject` |
| POST | `/approvals/{id}/request-changes` |
| POST | `/approvals/{id}/cancel` |
| POST | `/approvals/{id}/view` |
| POST | `/approvals/{id}/escalate` |
| POST | `/approvals/{id}/resume-execution` |
| GET | `/approvals/history` |
| GET | `/approvals/waiting-executions` |
| GET | `/approval-policies` |
| PUT | `/approval-policies` |

## Events

Approval: `ApprovalCreated`, `ApprovalViewed`, `ApprovalApproved`, `ApprovalRejected`,
`ApprovalExpired`, `ApprovalCancelled`, `ApprovalEscalated`.

Execution: `ExecutionRequested`, `ExecutionWaitingApproval`, `ExecutionApproved`,
`ExecutionRejected`, `ExecutionExpired`.

## Desktop

`/approvals` — **Approval Center**. Pending queue with priority, age and conflict context;
decision panel that visibly refuses self-approval and non-approvers; object, asset, graph and
execution context; approvers and decision history; resume control once approved.

Keyboard: `A` approve · `R` reject · `C` request changes · `O` open context · `J` jump to asset
· `X` jump to runtime. Shortcuts are suppressed while typing in an input.

**Inspector** shows approval status, required approvers, decision history, waiting reason and
policy source.

**Activity Center** renders waiting approvals as first-class activities that link straight into
the Approval Center.

## Import constraint

`event_bus` imports `approval.events`, so `approval/__init__.py` performs **no eager imports** —
anything it pulled in would become a dependency of the event bus itself. Import approval
submodules directly.

## Tests

`packages/kernel/tests/test_approval.py` — 48 tests covering policy evaluation, request
lifecycle, decision guards, quorum, expiry, escalation, runtime pause, scheduler waiting state,
resume, rejection, API surface, events, and architecture contracts.
