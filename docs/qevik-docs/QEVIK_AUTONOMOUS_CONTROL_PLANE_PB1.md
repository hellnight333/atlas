# QEVIK AUTONOMOUS CONTROL PLANE — P-B1

**Objective:** Build the persistent orchestration layer that lets Qevik turn a human request into a plan, delegate it to an agent, execute it in an isolated Git workspace, test it, commit it, save the complete report/history, and continue working even when the web UI is closed.

## 1. First principle

Do not build another parallel architecture. Inspect and reuse the existing:

- Mission / Delegation / AgentInvocation / Blocker
- BusinessEvent
- ApprovalService
- Job / JobStatus / Run
- Asset provenance
- QuotaLedger / Credits
- Integration / Connection
- HumanAction
- roadmap / execution / publication / measurement
- auth / tenancy / organization / agency

No second mission registry, job-state registry, approval system, quota ledger, tenant mechanism, roadmap, or credential vault.

## 2. Required vertical slice

Implement and verify this real loop:

```text
Human request
→ persisted conversation
→ structured plan
→ roadmap mapping
→ approval where required
→ queued mission
→ persistent worker claims mission
→ isolated Git workspace
→ agent implementation
→ tests / lint / typecheck / QA
→ review
→ commit
→ persistent report
→ mission completion
→ roadmap state update
```

Then prove:

```text
close web UI
→ worker continues
→ mission completes
→ reopen UI
→ complete history/report is visible
```

The browser must never be the execution process.

## 3. Agent provider abstraction

Create one authoritative provider boundary. It must support:

- local/fake provider — mandatory for tests
- Claude adapter
- Codex adapter
- Qwen adapter
- DeepSeek adapter

Do not require live credentials for the architecture tests.

Provider/model must be selectable per mission and support separate roles where useful:

```text
planner_provider/model
implementation_provider/model
review_provider/model
```

Track provider, model, token usage when available, estimated cost, actual cost when available. If cost is unavailable, record `UNKNOWN`; never invent it.

Never store secrets in events, reports, logs, Git, or exceptions.

The fake provider must simulate success, failure, timeout, malformed report, partial work, test failure, and blocker discovery.

## 4. Persistent worker

Implement a worker independent from the API/UI.

Lifecycle:

```text
claim
→ verify tenant
→ verify approval
→ verify blockers
→ create isolated execution context
→ invoke agent
→ run tests
→ review
→ commit when acceptance criteria pass
→ persist report
→ complete/release
```

Requirements:

- atomic claim
- no concurrent duplicate claim
- stale-claim detection
- restart recovery
- bounded retries
- no infinite agent loop
- failed execution is recorded, never silently successful

A worker restart must leave missions recoverable.

## 5. Git isolation

Agents must not casually edit the user's main working tree.

Use Git worktrees or an equivalent isolated workspace.

Persist:

- repository
- base commit
- branch/worktree
- changed files
- commit SHA
- test result
- push status

Never force-push or rewrite history. Never push to `main` automatically. Run secret scanning before commit. Preserve failed worktree information.

## 6. Agent implementation loop

Support:

```text
PLAN
→ IMPLEMENT
→ TEST
→ if failure: ANALYZE → FIX → TEST
→ REVIEW
→ if review failure: FIX → TEST
→ ACCEPT
→ COMMIT
```

Bound repair attempts.

An agent saying "done" is not success. Tests/acceptance/QA determine success.

## 7. Chat → Plan

Persist the full conversation.

A request such as:

> Build multi-page websites for the researched businesses.

must become a structured plan containing:

- request
- roadmap phase(s)
- objective
- tasks
- dependencies
- provider/model
- estimated cost
- risk
- human actions
- blockers
- acceptance criteria
- expected files/systems
- timestamps
- approval state

Do not silently execute a plan before required approval.

Persist:

- user request
- planner response
- plan revisions
- agent prompts
- agent responses
- execution/action summaries
- failures/retries
- approvals
- final report

Never persist credential values.

## 8. Mission lifecycle

Reuse the existing Mission vocabulary if present. Do not invent a conflicting state machine.

The effective lifecycle must represent:

```text
DRAFT
PLANNED
WAITING_APPROVAL
APPROVED
QUEUED
RUNNING
TESTING
REVIEW
BLOCKED
FAILED
COMPLETED
CANCELLED
```

If existing Mission states differ, extend/derive them instead of creating a second registry.

## 9. Reports

Every mission gets a durable report containing:

- mission/request
- plan
- provider/model
- start/end
- attempts
- files changed
- systems reused
- new models
- schema/migrations
- tests
- lint
- typecheck
- security checks
- commit SHA
- cost
- blockers
- human actions
- what was not done
- next action
- complete execution history reference
- agent summary

Save it using the repository's existing report/state convention.

## 10. Cost and credits

Reuse QuotaLedger / Credits.

Track cost per:

- mission
- attempt
- provider
- model
- input/output tokens when available
- estimated cost
- actual cost

Support configurable:

- max cost per mission
- max attempts
- max runtime

A limit becomes a HumanAction/Blocker, not an invisible failure.

Do not create a second pricing/ledger system.

## 11. Human Action / Blocker Center

External dependencies must become explicit actions.

Example:

```text
BLOCKED
Cloudflare API
Required: CLOUDFLARE_API_TOKEN

[Open setup]
[I've completed this]
[Test connection]
```

Support the existing pending integrations, including:

- Claude
- Codex
- Qwen
- DeepSeek
- Cloudflare
- Google Search Console
- Analytics
- Stripe

A blocked integration must block only dependent missions, never unrelated work.

## 12. Mission Control data/API

Expose enough backend data for a polished UI.

Roadmap view:

```text
P1.7 ✓
P2 Website ✓
P2 Multi-page ●
P2 Media ○
P3 AI Visibility ✓
...
```

For every item expose:

- status
- last plan date
- last execution date
- current mission
- blockers
- dependencies
- latest commit
- latest report
- next action

Mission view should expose:

```text
PLANNED → APPROVED → QUEUED → RUNNING → TESTING → REVIEW → COMPLETE
```

and:

- provider/model
- cost/tokens
- attempts
- timestamps
- files
- tests
- commit
- blocker
- report

Do not put UI-specific logic into the domain layer.

## 13. Chat UI contract

Backend must support a future UI such as:

```text
What do you want Qevik to do?
[____________________________]

[Plan]
```

Then:

```text
Plan created
7 tasks
Estimated cost: ...
Requires: ...

[Approve & Execute]
[Edit Plan]
```

History must remain available for old missions.

## 14. Mobile/responsive

Data/API contracts must support mobile clients.

Mobile operations:

- view roadmap
- view mission
- view blocker
- approve plan
- cancel/pause where authorized
- inspect report
- see cost
- submit a new plan

Execution must not depend on the mobile/browser session.

## 15. Security

Mandatory controls:

- tenant isolation
- authorization on every mission action
- no secrets in events/logs/reports/errors
- sandbox agent execution
- repository path allow-list
- command policy/allow-list
- no arbitrary shell from public input
- no untrusted arbitrary repository cloning
- no force push
- no automatic production publication
- outbound network policy
- SSRF protection boundary for future browser/fetch workers
- rate limiting
- atomic claims
- stale lease recovery
- audit trail

Do not weaken `db_safety` or existing approval boundaries.

## 16. Tests

Add negative controls for:

1. duplicate mission claim
2. stale claim recovery
3. cross-tenant mission access
4. execution without approval
5. agent failure
6. test failure
7. malformed agent report
8. secret appearing in logs
9. unauthorized Git push
10. worktree collision
11. cost limit exceeded
12. max attempts exceeded
13. UI unavailable while worker continues
14. worker restart recovery
15. blocked integration not blocking unrelated work
16. fake provider success
17. provider unavailable
18. unsupported model
19. invalid repository path
20. arbitrary command rejection

Also add a positive complete-loop test.

## 17. Self-use proof

Once B1 works, run one genuine mission through the new control plane against Qevik itself:

> Review the current roadmap/state and identify the highest-value unblocked engineering task, then create and execute a safe plan for it.

Do not claim self-use until it actually ran through the worker.

## 18. Existing-business proof

Do not reprocess all researched businesses automatically yet.

First create a mission type that can represent:

```text
business_id
tenant_id
re-evaluation request
```

Then prove it on one safe fixture/test business.

Never fabricate evidence.

## 19. Continuation after B1

After B1 is verified, inspect:

- `01_QEVIK_PHASE_ROADMAP.md`
- `MASTER_EXECUTION_STATE.md`
- `ROADMAP_RECONCILIATION.md`
- `STATE.md`
- `QEVIK_PENDING_IMPLEMENTATION_DOCS/`
- current execution reports
- current Git state

Then continue with the highest-value **unblocked** work.

Do not invent Product-A P9/P10/P11/P12 if its authoritative roadmap ends at P8. Keep Product B's independent Phase 1–12 numbering separate.

Do not stop just because one external credential is missing. Build everything around that boundary and continue with unrelated work.

Stop only for:

- genuine architecture conflict
- unavoidable human decision
- genuinely unavailable infrastructure
- safety/security intervention
- no meaningful unblocked work

If context/session capacity becomes a problem, persist state, commit cleanly, and leave a resumable mission rather than beginning unsafe half-finished work.

## 20. Autonomous product review

After the authoritative roadmap is substantially implemented, run a separate review of the actual product/repository for:

- monetization
- recurring revenue
- agency/white-label
- automation
- retention
- operational savings
- self-use
- integrations
- security
- unnecessary complexity
- reusable commercial capabilities

Classify every idea:

```text
NOW / NEXT / LATER / REJECT
```

Do not automatically implement speculative ideas without evidence.

## 21. Qevik self-improvement

After the control plane works:

1. represent Qevik as its own business
2. run the evidence engine against Qevik
3. generate evidence-backed opportunities
4. generate recommendations
5. create missions
6. plan/execute them through the control plane
7. measure later

No manufactured weaknesses.

## 22. Git policy

Every autonomous run:

```text
git status
git diff
secret scan
tests
lint
typecheck
commit
```

Do not push to `main` automatically.

Every report records:

- commit SHA
- branch
- push status

## 23. Final report

Use this exact structure:

```text
QEVIK AUTONOMOUS IMPLEMENTATION REPORT

1. Roadmap status
2. Missions executed
3. Plans created
4. Files changed
5. Systems reused
6. New models
7. Schema/migrations
8. Agent providers/models
9. Worker lifecycle
10. Git workspaces/commits
11. Tests
12. Security
13. Costs
14. Human actions
15. Blockers
16. What remains
17. Next recommended mission
18. Full execution history reference
```

## 24. Critical instruction

Do not merely produce an architecture report.

Inspect the repository and IMPLEMENT this.

Build the smallest complete vertical slice first, test it, commit it, save the report, then continue into the next unblocked work.

The goal is not merely a better Claude workflow.

The goal is:

**Qevik becomes the persistent orchestration layer through which future Qevik development can be planned, delegated, executed, tested, reported and resumed with minimal manual intervention.**
