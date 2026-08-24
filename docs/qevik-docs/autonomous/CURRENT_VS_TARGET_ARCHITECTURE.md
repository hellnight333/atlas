# Current vs target architecture

25 August 2026, at `961873c`. Companion to `MUNDER_DIFFLIN_REVIEW.md` and
`QEVIK_AGENT_FABRIC_ARCHITECTURE.md`.

**Nothing here is implemented. P1–P8 is unchanged and no phase is renamed.**

---

## The honest position

Qevik is **further along than the fabric framing suggests**. Seven of the ten
concerns are built, tested and in production. What is missing is not a rewrite —
it is four additions and one deterministic layer that was never written.

| Layer | Now | Target | Gap |
|---|---|---|---|
| Control plane | `app.qevik.ai` live, 13 surfaces | + live status, mobile-first home | **small** |
| Policy & approval | `ALLOWED`, `EXECUTORS`, `REQUIRES_CUSTOMER_INPUT`, two approval boundaries, `owns()`, `QuotaLedger` | + capability approval, budget-before-dispatch | **small** |
| Planner | `chat/planner.py` — refuses to invent | + multi-step, dependency-aware | **medium** |
| Scheduler | **none** — the worker takes one queued mission per pass | NOW/NEXT/SCHEDULED/WAITING/BLOCKED | **large — the biggest gap** |
| Mission ledger | event-sourced, nine states, durable | unchanged | **none** |
| Worker fabric | one process, proven independent | many, cloud + local, leases | **medium** — needs the atomic claim |
| Agent adapters | `LLMCodingAgent` over `ModelRegistry` | + CLI backend, + agent registry | **medium** |
| Tools | git, publication, research, executors | + browser, email, marketplace, social | **large, but incremental** |
| Evidence & memory | three-state, provenance, `Timeline` | + agent memory under the same rules | **small** |
| Credentials | vault, 16 providers, no read-back | + capability mapping | **small** |
| Reporting | durable per mission | + per-step attribution, message trail | **small** |

---

## KEEP — do not touch these

These are load-bearing and were expensive to get right. Several were corrected
after real failures, and the corrections are the value.

- **Event-sourced missions.** `fold()` takes the latest by timestamp, not by
  position — learned when a *completed* mission folded back to
  `awaiting_approval`.
- **The `ALLOWED` transition table.** Refuses `queued → complete`. Both the
  worker and the HTTP surface obey the same table rather than each having a rule.
- **Two approval boundaries**, the artefact one fingerprinted over published
  bytes via `bundle_hash`.
- **`EXECUTORS` + `REQUIRES_CUSTOMER_INPUT`.** An offer existing did not imply an
  executor; an executor existing did not imply it could receive its input. Both
  corrections point the same way: fewer things promised, each one true.
- **The three-state evidence model**, and readiness dimensions returning `None`
  rather than `0.0` when nothing was measured.
- **`cost_status`.** UNKNOWN is never zero.
- **Tenancy: absent, not forbidden.** 403-vs-404 tells a caller which ids exist.
- **The credential vault.** Sealed rather than degrading; no route returns a
  secret in any state or error path.
- **Worker independence.** Proven by killing the application and running the
  worker as a separate process.
- **Git isolation.** Worktree per mission, subcommand allow-list, protected
  branches, pre-commit secret scan, failed worktrees kept as evidence.
- **The SSRF address guard.** Every resolved address, every redirect hop.
- **`chat/` executing nothing.** The prompt-injection boundary.
- **Two applications, two services.** `/api/` is an alias namespace in the
  monolith and a real one in the control plane; they cannot share a process.

## REFACTOR — extend, never replace

| What | Why | Rule |
|---|---|---|
| `ModelRegistry` | must carry CLI backends alongside API models | **one registry** — the no-second-registry test stays |
| `Roles(planner, implementer, reviewer)` | fixed trio per mission; a fabric needs N capabilities | keep `Role`; make the set open |
| `mission/worker.py` | one mission per pass, no placement | add leases and placement; keep claim/release/stale |
| `Timeline` | carries mission events only | carry agent messages too — one log, not two |
| `credentials` | knows what a key is, not what it unlocks | add capability mapping |
| `reports` | attributes per mission | attribute per step |
| `LocalClaims` | correct for one process, says so | `PostgresClaims` is written and unverified; verify it before multi-worker |

## ADD — genuinely missing

Four things, in dependency order.

**1. Agent registry.** Declarative records: capability, role, backend, tools,
budget, approval policy, placement, owner. This is the missing primitive — 300
records cost nothing; 300 processes are impossible.

**2. Agent message protocol.** Speech acts (`request`/`query`/`propose` obligate
a reply; `inform`/`done` are terminal), a `hops` cap with escalation, on the
existing `Timeline`. Adopted from Munder because two agents informing each other
forever is the real failure mode.

**3. Scheduler.** The largest gap. Priority, dependencies, cost, placement,
credential and rate-limit awareness; five queues, with `WAITING` and `BLOCKED`
kept apart — one resolves itself, the other never will.

**4. CLI agent backend.** A real process with its own tool loop. **Needs a
sandbox** — Qevik's isolation is a process and a worktree, which is right for an
API agent and insufficient for one that writes files. `PENDING_INFRASTRUCTURE`.

## STOP BUILDING

- **More offers without customers.** Six offers have executors; none has been
  delivered to a paying customer. The constraint is not capability breadth.
- **More surfaces before live status.** Thirteen exist. None updates without a
  reload.
- **Marketplace, social and CRM adapters before one delivery.** Buildable, and
  the commercial review argues against it: they are a different customer and a
  different sales motion.
- **A second control plane.** Including a desktop app.

## DEFER

| | Until |
|---|---|
| Voice | chat → plan → approval is used in anger; voice is an input adapter, not a workflow |
| The visual floor | there are enough agents to make it legible — a view, never a model |
| Multi-worker | Postgres exists and `PostgresClaims` is verified |
| Product C (media business) | explicitly promoted; still a different business |
| Strix / Context7 / Supabase | a concrete need names them; do not adopt for fashion |

## RISK

| Risk | Severity | Mitigation |
|---|---|---|
| **An LLM orchestrator acquires authority** | **highest** | policy stays code; a plan proposes and never authorises. This is the one that would undo everything |
| CLI agents before a sandbox | high | `PENDING_INFRASTRUCTURE`; permission prompts become `HumanAction`s, never auto-answered |
| Two workers on `LocalClaims` | high | `/api/health` reports `SINGLE_WORKER_ONLY`; verify Postgres before running two |
| Irreversible tools without artefact approval | high | email, social and marketplace cannot be recalled — artefact approval over the exact payload |
| Agents recruiting agents | high | only the scheduler dispatches |
| Cost runaway across many agents | medium | budget-before-dispatch; UNKNOWN consumes at estimate |
| Approval fatigue | medium | standing capability approval; per-action only for irreversible tools |
| A second registry | medium | the no-second-registry test already exists; extend it |
| Building the fabric instead of delivering | **high** | the commercial finding stands: three capabilities are sellable and none is delivered |

---

## Recommended order

Each step is useful alone. None requires the next.

**0. Live status** — small, and it is what makes the console feel like mission
control rather than a report. SSE over the authenticated origin, degrading to
polling.

**1. Agent registry** — the primitive everything else needs. No behaviour
change: describe today's three roles as records and prove the fabric can express
what already works.

**2. Scheduler** — the largest gap and the most leverage. Turns one-mission-per-
pass into an operations department. Depends on nothing new.

**3. Message protocol** — only useful once there are several agents, which is
after 1 and 2.

**4. Budget-before-dispatch and capability approval** — needed before many
agents can spend.

**5. Verify `PostgresClaims`** — unlocks multi-worker. Needs a database.

**6. CLI backend** — needs a sandbox. Highest capability gain, highest risk.

**7. Tool agents** — browser, email, CRM, marketplace, social, in that order:
increasing blast radius, so the reversible ones prove the pattern first.

**Against all of it:** step 0 and a first delivered customer are worth more than
steps 1–7. The fabric makes Qevik able to do more; a delivered customer makes it
a business. If they compete, delivery wins — that is `SHIP_RULE.md`, and this
review does not overrule it.

---

## The single most important finding

**Orchestration is not intelligence.**

Munder's god agent is a language model deciding what to escalate. That is
defensible when the blast radius is one repository and the human is in the same
session. It is not defensible when the system publishes to customer domains,
spends money, sends email and holds credentials for sixteen providers.

Qevik's advantage is that its boundaries are code: `ALLOWED` refuses illegal
transitions, `EXECUTORS` refuses unbackable promises, the gate compares a hash,
`owns()` refuses cross-tenant reads. Every one becomes advisory the moment a
model decides what matters.

The fabric should make Qevik able to do **far more things**, and to decide
**none of them**.
