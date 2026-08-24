# The Qevik Agent Fabric — target architecture

Written 25 August 2026. **Design only. Nothing here is implemented, no phase is
renamed, and P1–P8 is unchanged.**

Answers questions E–Q of the review brief, and evaluates the proposed target
stack against an alternative.

---

## The proposed stack, evaluated

```
YOU → QEVIK OS → GOD/ORCHESTRATOR → AGENT FABRIC → models → tools
```

**Mostly right. One layer is wrong, and two are missing.**

**Wrong: `GOD/ORCHESTRATOR` as one layer.** It fuses two things with opposite
requirements. *Deciding what may happen* must be deterministic, inspectable and
testable. *Deciding what should happen* is judgement, and is best done by a
model. Fusing them makes a language model the authority over spending,
publication and tenancy — and its input is attacker-influenced, since a plan
quotes the customer's own website and email.

**Missing: the evidence layer.** The proposal has models and tools but nothing
about *what is true*. That is Qevik's actual differentiator and it is not a
sub-detail of orchestration.

**Missing: approval as a layer.** It is a boundary crossed by many paths, not a
step inside an orchestrator.

### The corrected stack

```
        YOU  —  web · mobile · voice · chat
         │
   CONTROL PLANE          surfaces, read models, live status
         │
   POLICY & APPROVAL      deterministic. scopes · tenancy · quota ·
         │                publication gate · REQUIRES_CUSTOMER_INPUT
         │                ── never a model ──
   PLANNER                model-driven. proposes only, authorises nothing
         │
   SCHEDULER              priority · dependencies · cost · resource · time
         │
   MISSION LEDGER         append-only events. the single truth
         │
   WORKER FABRIC          claim/lease. cloud workers + your machines
         │
   AGENT ADAPTERS         API models │ CLI agents │ deterministic executors
         │
   TOOLS                  git · browser · email · APIs · servers · marketplaces

   cross-cutting:  EVIDENCE & MEMORY   ·   CREDENTIALS   ·   REPORTING
```

The one-line difference from the proposal: **the orchestrator is split into
Policy (code) and Planner (model), and Policy sits above Planner.** A plan is a
proposal that Policy may refuse. That is already how `chat/` works and it is the
property worth generalising rather than replacing.

---

## The ten concerns, kept separate

The brief asks these be distinguished. They are separate because they fail
differently and belong to different owners.

| Concern | Owner | Deterministic? | Exists in Qevik |
|---|---|---|---|
| **Business intelligence** | evidence engine | yes — three-state | `opportunity/`, `readiness`, `recommendation/` |
| **Planning** | planner model | no | `chat/planner.py` |
| **Orchestration** | policy + scheduler | **yes** | `ALLOWED`, `gate`, `EXECUTORS` — scheduler missing |
| **Agent execution** | worker + adapters | no | `mission/worker.py`, `agents.py` |
| **Tool execution** | tool adapters | yes | `gitspace`, `publication/targets`, executors |
| **Human approval** | approval service | yes | two boundaries, both built |
| **Scheduling** | scheduler | yes | **missing** |
| **Credentials** | vault | yes | `credentials/` |
| **Memory** | timeline + evidence | yes | `BusinessEvent`, `Timeline` |
| **Reporting** | reports | yes | `mission/reports.py` |

**Seven of ten are deterministic.** Only planning and agent execution are
model-driven, and both are proposals that deterministic layers accept or refuse.
That ratio is the architecture.

---

## E. How Claude, Codex, Qwen, DeepSeek, Kimi, Gemini fit as one fabric

They do not enter as "agents". They enter as **backends behind two adapters**,
because there are exactly two integration shapes and conflating them is how a
registry rots.

```
Capability  (what work this is)          e.g. implement · review · research
     │
Agent       (a thing that can do it)     addressable, has an identity
     │
Backend     (how it actually runs)
     ├── APIModelBackend   → ModelRegistry → provider + ModelSpec
     └── CLIAgentBackend   → a real process, its own cwd, its own session
```

`ModelRegistry` stays the **only** registry of what can run. Adding DeepSeek or
Kimi is a registration plus a credential, never a new subsystem — the discipline
`modelchoice` already enforces with a test asserting no second registry exists.

Per-role selection already exists (`Role.PLANNING`/`IMPLEMENTATION`/`REVIEW`/…)
and generalises: a Capability declares which Role it needs, the tenant's
`Selection` decides the model, and `chosen_for` reports whether that was a choice
or a default. A selection naming an unavailable model is **reported, never
silently replaced** — running work on a model nobody picked, then recording the
substitute as chosen, is worse than refusing.

## F. API models and CLI agents coexisting

They differ in four ways that matter, and the adapter boundary should make each
explicit rather than pretending they are the same:

| | API model | CLI agent |
|---|---|---|
| Filesystem | none | full, within its cwd |
| Tool loop | ours | **its own** |
| Permission prompts | none | its own, interactively |
| Cost reporting | usually per call | often not at all → `UNKNOWN` |

The consequence: **a CLI agent is a sandboxing question, not a provider
question.** An API model that misbehaves returns bad text; a CLI agent that
misbehaves writes files. Qevik's isolation today is a process and a worktree,
which is right for an API-driven agent and insufficient for a CLI one.

So: `CLIAgentBackend` is designed now and marked `PENDING_INFRASTRUCTURE` until
a container boundary exists. Its permission prompts must surface as Qevik
`HumanAction`s rather than being auto-answered — auto-answering a CLI's
permission prompt is exactly the "LLM decides what is safe" failure in a
different costume.

## G. Cloud workers and your Mac/Windows/Linux machines

One worker protocol, two deployment shapes, and the local one is **outbound
only**.

```
worker → claims a mission → leases it → heartbeats → reports → releases
```

A laptop must never accept an inbound connection. It long-polls the control
plane over an outbound connection, exactly as the Atlas fleet already does, so
there is no port to open, no address to leak, and sleeping the lid is
indistinguishable from a slow worker.

Placement is a **declared requirement of the mission**, not a preference:

- `requires_local` — a task needing your filesystem, a local GPU, or a CLI agent
  logged in as you
- `requires_cloud` — a task needing to be always-on
- `either` — most engineering work

A mission requiring local execution with no local worker attached is `BLOCKED`
with a named reason, not silently queued forever.

## H. How app.qevik.ai talks to local workers

**It does not, and must not.** The control plane never dials a worker.

```
app.qevik.ai ──writes──> MISSION LEDGER <──polls── worker (anywhere)
```

Both sides touch only the ledger. This is already true — `test_chat_to_commit.py`
kills the application entirely and a separate process completes the mission —
and it is the property that makes laptops, phones and cloud workers
interchangeable. A control plane that dialled workers would need to know where
they are, which is a directory, a NAT problem and an inbound port.

Lease-based claiming makes a sleeping laptop safe: the lease expires, `stale()`
finds it, `release()` returns the mission with the reason recorded.

## I. Surviving browser close, sleep, restart, worker and model failure

| Failure | Mechanism | Status |
|---|---|---|
| Browser closed | nothing lives in the browser; the ledger is the state | **built and proven** |
| Application restarted | event-sourced; `fold()` rebuilds | **built** |
| Machine sleeps mid-mission | lease expires → `stale()` → `release()` | **built** (`recover()`) |
| Worker crashes | same path; the worktree is **kept** as failure evidence | **built** |
| Two workers race | atomic claim | `PENDING_INFRASTRUCTURE` — Postgres |
| Model returns nothing usable | `MalformedResult` → bounded retry → blocker | **built** |
| Model unavailable | `chosen_for` reports it; the plan becomes a blocker, never a template | **built** |
| Provider bills unexpectedly | reserve-before-act on `QuotaLedger` | **built** |

The one genuine gap is the atomic claim, and it is already specified with the
right SQL, refusing to construct unverified.

## J. Credentials, spending, approval

**Credentials.** The Credential Centre is the only door. Sixteen providers, no
route returns a secret in any state or error path, stored ≠ connected, rotation
clears the previous verification. A sealed vault refuses to store rather than
degrading to plaintext. For a fabric, one addition: a credential should declare
**which capabilities it unlocks**, so "what does this key buy me" and "what
breaks without it" are the same question.

**Spending.** `QuotaLedger` with reserve-before-act. For the fabric: a budget per
mission, per day and per tenant, checked **before** dispatch. A mission that
would exceed its budget is `BLOCKED` with the number, not stopped halfway with a
bill. `UNKNOWN` cost is never counted as zero — an unmetered provider must
consume budget at its estimate or be refused.

**Approval.** Both existing boundaries generalise unchanged:

- *Execution*: should Qevik do this work — before dispatch
- *Artefact*: may this exact output go live — fingerprinted over the bytes

A third is needed for a fabric: **capability approval** — may this agent use this
tool at all. Standing, not per-action, or approval fatigue makes it noise.

## K. 100–300 agents without a swarm

**The mistake to avoid: 300 processes.** Munder's model — one PTY per agent, a
seat on a floor — is right for a dozen and impossible at 300.

An agent is a **declarative record**, not a process:

```
Agent:  id · capability · role · backend · tools · budget ·
        approval policy · placement · owner
```

Records are cheap: three hundred cost nothing when idle. **Processes** are
instantiated on demand and pooled — a handful of workers serving whichever
capability the scheduler dispatches.

Three properties keep it manageable:

1. **A hierarchy of capability, not of authority.** Agents are grouped by domain
   (engineering, customer, discovery, CRM, media, infrastructure). The grouping
   is for *routing and permissions*, never for one agent commanding another.
   Authority stays in policy code.
2. **Agents cannot recruit agents.** Only the scheduler dispatches. An agent that
   could spawn agents is an unbounded resource commitment made by a model, and
   it is how a swarm happens.
3. **A conversation budget.** Munder's `hops` counter, adopted: inter-agent
   exchanges are capped and escalate at the cap.

At 300, the interface must summarise by domain and exception —
*what needs me · what is blocked · what finished · what is running* — because
nobody reads 300 rows.

## L. Scheduling with many missions competing

The scheduler is the largest missing piece. It decides **order and placement**;
it never decides *whether* — policy did that.

Inputs: priority · deadline · dependencies · estimated cost · remaining budget ·
required placement · model availability · credential availability · provider rate
limits · worker capacity · whether a human is awake.

Five queues, and the distinction is the product:

| | |
|---|---|
| `NOW` | dispatch immediately |
| `NEXT` | ready, waiting for capacity |
| `SCHEDULED` | deliberately later — a night window |
| `WAITING` | a dependency, a human, a credential |
| `BLOCKED` | cannot proceed; the reason is named |

`WAITING` and `BLOCKED` must not merge. One resolves by itself; the other never
will.

## M. Now, tonight, or elsewhere

A decision procedure, deterministic:

**Now** — a person is waiting, or it unblocks something they are waiting on;
cost is within the immediate budget; the capability is available.

**Tonight** — cheaper off-peak; large batch work (re-researching every business,
media generation, full re-evaluation); nothing downstream needs it before
morning. The night run exists so the morning brief has something in it.

**Elsewhere** — placement is a requirement rather than a preference. Local when
it needs your filesystem, your GPU, or a CLI logged in as you. Cloud when it must
survive your laptop closing.

**Never** — refused by policy. This is a decision, and it is recorded with its
reason rather than left in a queue looking like a delay.

## N. Reports, history, provenance, auditability

Mostly built. Every mission produces a durable report answering what was
requested, planned, done, by which model, what changed, what was tested, what
failed, what was committed, what it cost, what remains.

Three additions for a fabric:

1. **Agent attribution per step**, not per mission. With ten agents on one
   mission, "which model did this" must resolve to a step.
2. **A message trail.** Inter-agent conversations are provenance: "why did the
   CRM agent contact this business" must have an answer.
3. **Evidence links surviving into the report.** A claim in a report should
   reach back to the observation, exactly as customer-facing claims already do.

**Chat is never the source of truth.** Conversations are provenance for a
request; the ledger is what happened.

## O. Mobile

Mobile-first is not "responsive". The phone answers four questions, in this
order:

1. **What needs me?** — approvals, blocked-on-human, credentials
2. **What is running?**
3. **What finished, and what came of it?**
4. **What did Qevik find?** — opportunities

Everything else is a drill-down. Approving on a phone must be a real approval —
identity, the artefact's fingerprint, a record of who decided — not a
notification tap.

The console already does the first three. What it lacks is **live status**:
Mission Control shows state on load and does not move. Server-sent events over
the same authenticated origin, degrading to polling, and nothing that makes the
page load-bearing for the work.

## P. Voice

Voice is **an input adapter, not a workflow**. It produces the same
`POST /api/chat` a keyboard does.

```
speech → transcript → conversation → plan → SHOWN → approved → mission
```

The plan is still shown and still approved. Speaking a request must not skip the
step that exists because language is attacker-influenced — and voice is worse,
not better: transcription errors are invisible to the speaker, and "delete the
old pages" mis-transcribed is not recoverable by intent.

For genuinely low-risk reads — *what needs my attention* — a spoken answer is
fine, because reading is not acting.

## Q. Browser, email, server, git, CRM, marketplace, social agents

All the same shape. What differs is only their **blast radius**, and that is
what the tool boundary encodes:

| Agent | Tool | Reversible? | Approval |
|---|---|---|---|
| Engineering | git worktree | yes — branch, never main | execution |
| Browser/research | fetch (SSRF-guarded) | yes — reads only | none |
| Server admin | shell on a host | **no** | per-action |
| Email/CRM | SMTP | **no — cannot be unsent** | artefact, per message |
| Marketplace | Amazon/Noon | **no — creates orders** | artefact + spending |
| Social | YouTube/Instagram | **no — cannot be recalled** | artefact, explicit |
| Media | generation providers | yes, but costs money | budget |

The rule that follows: **an irreversible tool requires artefact approval over the
exact payload.** Not "may the CRM agent send email" — *may this message go to
this person.* Qevik's artefact boundary already works this way for publication,
and it generalises unchanged.

Two already have their guards: the browser agent inherits the SSRF address check
(every resolved address, every redirect hop), and the git agent inherits the
worktree, the subcommand allow-list, the protected branches and the pre-commit
secret scan.

---

## What this architecture is *not*

- **Not a swarm.** Agents do not recruit agents; the scheduler dispatches.
- **Not an intelligent orchestrator.** Policy is code. A model proposes.
- **Not a second control plane.** `app.qevik.ai` is it.
- **Not a replacement.** Every layer above maps to something already built or
  already specified. The fabric is a *composition* of Qevik's existing parts plus
  four additions: the agent registry, the message protocol, the scheduler, and
  the CLI backend.
