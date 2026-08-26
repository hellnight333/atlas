# MASTER_STATE

The single reconciliation point for Qevik. Read this before starting a
workstream; update it when one lands. Everything here is meant to be checkable
against the repository — if a line cannot be verified, it does not belong.

**Last reconciled:** 2026-08-26 (origin surface, no-fallback gates, recipes)

---

## Hard architectural constraints

These are not preferences. A change that breaks one does not land.

1. Policy is deterministic and sits **above** the planner.
2. The planner proposes; it never authorises.
3. Approval is a real boundary, not a flag on a plan.
4. Evidence and provenance are first-class.
5. Credentials live behind the vault boundary only.
6. Workers are disposable and independently recoverable.
7. Agents are declarative records, not permanent processes.
8. The scheduler is the only component that dispatches.
9. No agent recruits another agent.
10. No LLM becomes an orchestrator with authority.
11. Chat never executes anything directly.
12. Self-modification always requires human approval.
13. Unknown cost is never rendered as zero.
14. **Tests passing is not completion.** The live operational path is verified.

---

## Operational now

| Capability | Evidence |
|---|---|
| Mission lifecycle, event-sourced | `mission/service.py`, `ALLOWED` table |
| Deterministic policy above the planner | `mission/policy.py` |
| Atomic multi-worker claims | `mission/claims.py`, `verify_two_workers` 7/7 on the real DB |
| Isolated git workspace per mission | `mission/gitspace.py` |
| **Scratch clone; production read-only** | `mission/scratch.py`, `verify_scratch_isolation` 34/34 |
| Sandboxed deterministic agents | `mission/adapter.py`, `fabric/sandbox.py` |
| Chat → plan → approval → mission → worker | `verify_self_improvement` 29/29 |
| Credential vault, one boundary | `credentials/location.py`, `verify_vault_boundary` |
| Recurrence → missions | `mission/recurrence.py`, `verify_recurrence` 10/10 |
| **Per-mission origin allow-list** | `mission/origins.py`, `test_origins.py` 31 |
| **Unattended nightly recurrence** | `rec-execution-canary`, `verify_recurrence` 19/19 |
| **Budgets + credentials checked before dispatch** | `tenant_headroom`, `usable_for`, `test_worker_dispatch.py` 14 |
| Provable branch cleanup | `infra/prune_mission_branches.py`, 17 tests |
| Console, mobile-first | `apps/control/src/index.html`, `verify_console_logic` 27/27 |
| Backups, verified by restore | `qevik-backup.service`, nightly |

Full suite: **3208 passed, 33 skipped**.

---

## Roadmap components — verified, not assumed

Checked what is **wired**, not what exists. Three of the four first items were
built and only partly connected, which is a different problem from missing.

| Component | Module | Status |
|---|---|---|
| Agent registry | `fabric/agents.py` | **now wired into dispatch.** Was consulted by policy and the adapter, but not by the scheduler: `demands_from` got no `agent_for`, so every mission looked like it needed no credentials and had `placement=EITHER` |
| Scheduler | `fabric/scheduler.py` | wired (worker + control plane) |
| Budgets | `fabric/budgets.py` | **now checked before dispatch.** `assess()` exists so "the scheduler can decline to start work it cannot finish" and nothing called it — the budget was consulted only *after* the work, by `_charge` |
| Message protocol | `fabric/protocol.py` | **built, imported by nothing.** Its consumer is agent-to-agent capability routing, which needs the CLI/tool agents. Not wired speculatively |
| Tools | `fabric/tools.py` | wired, **and now enforced per step** |
| Recipes | `fabric/recipes.py` | the unit of work; `execution-canary` declared |
| Sandbox | `fabric/sandbox.py` | wired, `verify_sandbox` |

### What the two dispatch gaps cost

A mission whose agent needs a model credential nobody had configured was
**dispatched, reported as running, and failed at the provider** — exactly what
`usable_credentials`'s own docstring warns about. Demonstrated:

    no agent_for (how it ran)      dispatchable=['m-1']  missing=()
    with agent_for, no creds       dispatchable=[]       missing=('qwen','anthropic','openai')
    with agent_for, qwen present   dispatchable=['m-1']  missing=()

`Mission.agent_id` is now recorded when the plan is attached, from the same
value `policy.decide` was given — so the blast radius a person approved and the
one read at dispatch are the same value, and the control plane's schedule view
stops showing a mission as dispatchable that the worker would hold.

## Closed since

**Origin surface.** `GET /api/missions/origins` lists what a mission may be
pointed at — names and kinds, **no filesystem paths**. (Declared above
`/{mission_id}`: it was first written below it, where every request for it was
answered by the detail handler looking for a mission called "origins". Pinned by
a test that reads the route table, because a 404 from either reads the same.) `QEVIK_ORIGINS` is the
single declaration the control plane *and* the worker read, so a customer origin
configured once is one the console can offer and the worker can serve; a name
given both by env and `--origin` is refused rather than one silently winning.
Both `POST /api/missions` and chat `/decide` validate the key server-side (400
on unknown) and the worker re-checks at dispatch. The approval screen offers
radio options — a name and a sentence each, Qevik preselected and marked before
it is chosen. Verified at 390×844: `doc.scrollWidth 390`, no overflow.

**No silent fallback.** Three refusals now sit together in the worker, all
before any agent runs:

| substitution | refusal |
|---|---|
| a worker running an agent the plan was not approved with | `policy.refuse_agent_substitution` |
| a repository the mission did not name | `origins.UnknownOrigin` → BLOCKED |
| work an allowance cannot carry | `refuse_over_budget`, via `budgets.assess` across every scope |

`infra/verify_no_fallback.py` — 23 checks against **real worker processes**,
each with a paired positive control.

## Known gap, found by looking

*(The previous gap — the console could only create Qevik-origin missions — is
closed above.)*

## Agents, tools, recipes — the 300-assistant infrastructure

An agent is a **record**, not a process. There are no 300 daemons; there is a
registry of declarations and a scheduler that dispatches against them.

| | |
|---|---|
| `fabric/agents.py` | who does it, and the worst it can do |
| `fabric/tools.py` | what it may reach — **now enforced per step** |
| `fabric/recipes.py` | how one job is done, versioned, in git |
| `fabric/sandbox.py` | the containment those steps run inside |

**The tool contract was consulted only in aggregate** — to decide network and
sandbox needs — and never per step, so an agent declaring `("filesystem",)`
could run any command including one reaching the network, under isolation
derived from a declaration that no longer described the work. `Step.tool` closes
it, and the *whole sequence* is refused before the first step runs.

**Recipes** are the primitive `CLAUDE.md` names: a model's only job is choosing
one by name. Not a plan (cannot authorise itself), not a workflow engine (no
conditionals, loops or variables), not runtime-configurable (the agent is
declared, because a runtime agent choice is a runtime blast radius). Validated
at **import**, so a bad declaration is a failing build rather than a blocked
mission at 3am.

`SELF_CHECK_STEPS` is now derived from the `execution-canary` recipe rather than
being a second copy of the same three commands.

## Next

**Business discovery / opportunity engine** — the first recipe-driven assistant
that is not about code, and the thing that proves the abstraction is generic.
Then the mobile control surface and flagship `qevik.ai`.

`fabric/protocol.py` remains built and unconsumed. Its consumer is agent-to-agent
capability routing; a single recipe execution does not need it, and wiring it
speculatively would be architecture for its own sake.

## Completed and in progress

### 1. Origin as a per-mission property — **DONE**
`--repository` is gone; the worker refuses it rather than ignoring it. A mission
declares `origin_name` (a **key**, never a path) and the worker resolves it
against `mission/origins.py` at dispatch. Built-ins `qevik` (derived from
`__file__`) and `none`; customer repositories come from `--origin NAME=PATH` and
a entry pointing at Qevik's own repository is **refused at start-up**. An
unregistered name blocks the mission — never falls back to the default, because
the default is Qevik. `test_origins.py` 31 tests; `verify_scratch_isolation`
38/38 including the unregistered-name path end to end.

### 2. First real unattended recurrence — **DONE**
`rec-execution-canary`, nightly at 02:30 UTC. Runs the self-check agent end to
end so a broken execution path is found by a failed mission on the phone rather
than when somebody needs the path. Reaches the queue with nobody asked, and only
because its origin is `none` — the identical plan against `qevik` waits for a
person. `Recurrence.modifies_qevik_itself` (a field that could lie) is replaced
by `origin_name` (resolved). `verify_recurrence` 19/19 including the canary run
through the real worker.

### 3. Production leftovers — **mechanism DONE, cleanup correctly refused**
`infra/prune_mission_branches.py`, dry run by default, 17 tests. Inspected
production 2026-08-26: **0 provably stale, 13 protected** — the control plane has
no `missions.jsonl`, so nothing can be checked against and the tool refuses.
Three branches carry corroborating evidence of harness origin (`/tmp/qevik-e2e-*`
worktrees), reported and deliberately not treated as proof. Re-run once the
worker has recorded missions.

---

## Roadmap, in dependency order

agent registry → scheduler → message protocol → budgets → CLI/tool agents →
business discovery / opportunity engine → mobile control surface → flagship
`qevik.ai`

The first four exist as modules (`fabric/agents.py`, `fabric/scheduler.py`,
`fabric/protocol.py`, `fabric/budgets.py`). **Verify before treating any as
missing.**

---

## A regression this session introduced and caught

Removing the `report_root or repository` fallback (which used to write reports
*into* the origin repository) left `run_console_acceptance` with no `--reports`
at all, so the worker wrote to a temp directory the API could not look in and
the console correctly said "no report". Both sides now name the same directory
explicitly, rather than agreeing by both defaulting to the repository.

**Production was never affected** — its worker unit passes
`--reports /var/lib/qevik/control/reports` and `QEVIK_STATE` gives the control
plane the same path. Checked rather than assumed.

Found by running the acceptance harness, not by any unit test. It is the
standing reason for constraint 14.

## Deployment state

`qevik-core-01` runs the **previously deployed** code and is healthy —
`qevik-api`, `qevik-control`, `qevik-worker` all active, worker logging normally.

The origin model, the no-fallback gates, the origin surface and recipes are
**committed locally and not deployed**, on instruction. Deploying them requires,
in this order:

1. `rsync` the kernel and `infra/mission_worker.py`
2. install `infra/qevik-worker.service` — the unit still passes `--repository`,
   which the new worker **refuses to start on**. The unit in the repo is already
   correct; it has to land in the same step as the code.
3. set `QEVIK_ORIGINS` in `/opt/qevik/worker.env` and the control plane's env if
   any customer origin is wanted; the built-ins need no configuration
4. `systemctl daemon-reload && restart` worker and control
5. re-run `infra/verify_no_fallback.py` and `infra/verify_recurrence.py` on the
   host

Until then the nightly canary does not run in production: `RECURRENCES` lives in
the undeployed code.

## Externally blocked

- **`BLOCKED_EXTERNAL_PROVIDER`** — no provider accepts the configured model
  credential. Test credentials, deliberately in use for provider-boundary
  testing. **Not a project blocker. Do not raise rotation.**

## Open findings

- **F-001** — `/tmp/db.bak` on `qevik-core-01`. Not read, not deleted, `0600`.
  Awaiting an explicit operational decision. `docs/SECURITY_FINDINGS.md`.

---

## Product direction (not permission to bypass the architecture)

Qevik should behave like a 300-person digital operations team run from a phone:
"add this feature", "find businesses in Dubai today", "investigate this
traffic", "what needs my approval". The phone is a serious control plane —
voice, status, approvals, reports, notifications, scheduling, asset requests.

The flagship surface must be mobile-first, visual and operational — live mission
activity, opportunity maps, asset generation, actionable recommendations. **Not
another generic admin panel, and not more dashboard surfaces for their own
sake.** Preserve the architecture that makes it possible; do not build it yet.
