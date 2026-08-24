# Munder Difflin — architecture review

Reviewed 25 August 2026 against Qevik at `961873c`. Sources: the repository
README and `HIVE.md`, its multi-agent design specification.

**No code was copied, nothing was installed, and no Qevik subsystem is replaced.**
This is a reading, a comparison, and a set of judgements.

---

## A. What Munder Difflin actually solves

It turns **terminal coding CLIs into a team that keeps working while you are
away**. That is the whole product, and it is a good one.

The concrete problem: you have Claude Code, Codex, Gemini CLI, Qwen and nine
others installed. Each is a competent single-threaded assistant in a terminal.
None of them can talk to another, none survives you closing the laptop with a
clear picture of what it was doing, and coordinating three of them means being
the message bus yourself.

Munder's answer has four parts:

1. **Every agent is a real process.** `node-pty` spawns the actual CLI. Not an
   API imitation of it — the binary, with its own working directory, its own
   session, its own permission prompts.
2. **A filesystem is the message bus.** Agents write JSON to `outbox/`; a router
   delivers to `inbox/`; a `cursor.json` marks the last processed id. Written
   temp-file-then-`rename`, so a message is never half-visible.
3. **A single committer.** Only the Electron main process runs git. Agents write
   plain files and never touch `.git`, which removes index-lock corruption
   entirely rather than retrying around it.
4. **Human approval is native, not queued.** Escalations surface as the CLI's
   *own* permission prompt inside the god agent's session, approvable remotely.
   There is deliberately no separate approval inbox.

The visual layer — an isometric office where agents are avatars at desks — is a
genuinely good *legibility* idea. Watching a character walk to another desk is a
faster read of "these two are talking" than any log.

### What is architecturally strongest

- **Speech acts with obligation semantics.** Messages carry `act`:
  `request`/`query`/`propose` obligate a reply; `inform`/`done` are terminal.
  A `hops` counter increments per reply and escalates at a cap. That is a real
  livelock defence, and most multi-agent systems have none.
- **Single-committer git.** Correct, and arrived at from the same reasoning
  GitHub Desktop's commit queue uses.
- **Atomic file mailboxes.** No broker, no database, no daemon. Trivially
  inspectable, trivially recoverable, and the audit trail is `git log`.
- **The god agent owns the one co-edited file.** `board.md` has a single scribe
  precisely because concurrent edits to a shared plan are where these systems
  rot.

---

## B. What Qevik already solves that Munder does not

This is the more important half of the comparison, and it is asymmetric: Munder
is an **engineering-team harness**. Qevik is a **business operating system that
happens to do engineering**.

| | Munder | Qevik |
|---|---|---|
| Customers | none — there is no notion of a business being worked on | `Business`, one immutable id every factory references |
| Evidence | none | three-state: `CONFIRMED_PRESENT` / `CONFIRMED_ABSENT` / `NOT_VERIFIED`; unverified is never a weakness |
| Provenance | agent memory files | every fact carries a source; `Prose` is `extra="forbid"` so a misspelled provenance field fails loudly |
| Tenancy | single user | `owns()` on every read; another tenant's resource is **absent**, not forbidden |
| Approval | one boundary (a permission prompt) | **two**: execution ("should Qevik do this work") and artefact ("may this exact output go live"), the second fingerprinted over the published bytes |
| Publication | git commit | `READY_TO_PUBLISH ≠ PUBLISHED`, a QA gate, a verified domain, `NOT_AUTHORISED` as a state distinct from `FAILED` |
| Cost | SQLite usage ledger | `cost_status` REPORTED/ESTIMATED/**UNKNOWN**, and UNKNOWN is never rendered as zero |
| Capability | any agent can attempt anything | `EXECUTORS` — an offer with no executor cannot be promised; `REQUIRES_CUSTOMER_INPUT` — an executor that cannot receive its input is not "executable" either |
| Measurement | none | metrics with windows, sample sizes, and a `comparable()` that refuses a dishonest comparison |
| Mission lifecycle | task status in `tasks.json` | nine states with an `ALLOWED` transition table that refuses `queued → complete` |

**The thing Qevik has that Munder structurally cannot get to:** every claim made
to a customer is traceable to evidence, and the system refuses to make claims it
cannot support. That is not a feature; it is the architecture. Munder's agents
are free to be confident, because nobody outside the room reads their output.

---

## C. Which Munder concepts Qevik should take

### ADOPT — the mailbox protocol's *semantics*

Qevik has an append-only timeline and no way for one agent to ask another
anything. When there are twenty specialised agents, that gap becomes the whole
problem.

What to take is not the file layout — Qevik's `Timeline` already does atomic
append with fsync and tolerates corrupt lines — but the **speech acts and the
obligation rules**:

- `act` on every inter-agent message
- only `request`/`query`/`propose` obligate a reply
- a `hops` counter, with escalation at a cap

Two agents politely informing each other forever is the failure mode, and a
counter is the cheapest correct defence against it.

### ADOPT — the single-committer principle, as a principle

Qevik is already **stronger** here: each mission gets its own `git worktree`, so
two missions cannot collide at all. Munder's single committer solves a problem
Qevik avoided by isolation.

But the principle generalises and Qevik will need it: **when N writers share one
resource, route the writes through one owner.** That applies to the mission
timeline the moment two workers run, which is exactly the `PostgresClaims` gap
already marked `PENDING_INFRASTRUCTURE`.

### ADAPT — an agent registry with capabilities

Munder's `registry.json` lists every agent's role, capabilities, status and seat,
and the god reads it to decide who gets a task.

Qevik has `EXECUTORS` (offer → executor) and `ModelRegistry` (what can run), but
**no registry of agents as addressable things with capabilities**. That is the
missing primitive for a fabric — and it must be one registry, extending what
exists, not a second one beside it.

### ADAPT — per-agent working directories and identity

`identity.md` + `memory.md` per agent is a clean idea. Qevik should keep the
worktree isolation it already has and add the identity half — but with Qevik's
provenance rules, not free-form markdown an agent can write anything into.

### ADAPT (carefully) — real CLI agents as first-class

Munder is right that a real `claude` process is not the same thing as an API
call. It has the tool loop, the permission prompts, the file access. Qevik's
`LLMCodingAgent` is API-only.

This is worth having and it is **`PENDING_INFRASTRUCTURE`**: a CLI agent with
filesystem access needs a sandbox, and Qevik's worker isolation today is a
process and a worktree, not a container.

### DEFER — the visual floor

The office metaphor is genuinely good for legibility at 5–20 agents. At 300 it
is a crowd. Worth revisiting as a *view* over the fabric — never as the model.

---

## D. What must NOT be copied

### The god agent as an intelligent authority — **REJECT**

This is the most important judgement in the review.

In Munder, the god agent is an LLM that "reads every request, resolves routine
ones itself, and escalates only critical decisions." **The decision about what is
critical is made by a language model.**

For Munder that is defensible: the blast radius is one developer's repository,
and the human is sitting in the same session.

For Qevik it would be a catastrophe, and specifically it would destroy the
property the last several months of work exist to establish. Qevik's approval
boundaries are **code**: `ALLOWED` refuses illegal transitions, `EXECUTORS`
refuses unbackable promises, the publication gate compares a hash, `owns()`
refuses cross-tenant reads, `REQUIRES_CUSTOMER_INPUT` refuses to promise work
that needs a photograph nobody sent.

Every one of those becomes advisory the moment an LLM decides what to escalate.
And the input to that decision is attacker-influenced: a plan quotes a customer's
website, their email, their research. That is precisely the prompt-injection
boundary `chat/` was built to hold — a plan is a *proposal* until a person looks
at it.

**Orchestration is not intelligence.** Munder conflates them. Qevik must not.
The right split:

- **Policy** — deterministic code. What may run, who may approve, what a
  credential unlocks, what may be published. Never a model.
- **Planning** — model-driven. What should be done, in what order, by whom.
  Proposes only; never authorises.

### The blackboard — **REJECT**

`board.md` is mutable shared state with a single scribe. Qevik is event-sourced:
state is folded from an append-only log, and `fold()` takes the latest by
timestamp rather than by position — a lesson learned when a *completed* mission
folded back to `awaiting_approval`.

A co-edited plan file is a step backwards from that, and the single-scribe rule
exists only to make the mutable thing survivable.

### "No separate approval queue" — **REJECT**

Munder's human-in-the-loop is native to the agent's own session, which is elegant
for a developer at a terminal.

Qevik's approvals are frequently **the customer's**, not the operator's, and they
are about artefacts rather than commands: *may this page go live on your domain*.
That cannot live in a terminal permission prompt. It needs a durable queue with
identity, a fingerprint over the exact bytes, and a record of who decided — all
of which `ApprovalService` and the artefact gate already provide.

### The Electron desktop as the control plane — **REJECT**

Qevik's control plane is `app.qevik.ai`, deliberately mobile-first, and it is
already live. A desktop app would be a second control surface with a second
answer to "what is happening", and the one on the phone would lose.

### The task ledger as a separate system — **REJECT**

`tasks.json` owned by an orchestrator is exactly what `Mission` + the event
timeline already is, with a stricter lifecycle. Adding it would create two
answers to "what is this work's state".

---

## Where Munder is genuinely ahead, stated plainly

Three things, and pretending otherwise would make this review useless:

1. **Agents can talk to each other.** Qevik's agents cannot. There is one
   `Roles(planner, implementer, reviewer)` per mission and no protocol between
   missions or between specialists.
2. **Agents are real processes with real tool access.** Qevik's are API calls
   inside one worker.
3. **It is legible.** You can watch it work. Qevik's Mission Control shows state;
   Munder shows *activity*.

The first is the important one, and it is the subject of
`QEVIK_AGENT_FABRIC_ARCHITECTURE.md`.

---

## Classification summary

| Concept | Verdict | Note |
|---|---|---|
| Mailbox with speech acts + hops cap | **ADOPT** | semantics, not the file layout — `Timeline` already handles durability |
| Single-committer principle | **ADOPT** | as a principle; worktree isolation is already stronger |
| Agent registry with capabilities | **ADAPT** | extend `EXECUTORS`/`ModelRegistry`; never a second registry |
| Per-agent identity + memory | **ADAPT** | under Qevik's provenance rules, not free-form markdown |
| Real CLI/PTY agents | **ADAPT** | needs a sandbox — `PENDING_INFRASTRUCTURE` |
| Parallel execution | **ADAPT** | needs the atomic claim already specified in `mission/claims.py` |
| Retry / stale-lock recovery | **KEEP OURS** | `stale()` + `release()` + bounded retry already exist |
| Cost ledger | **KEEP OURS** | `QuotaLedger` + `cost_status`; ours distinguishes UNKNOWN from zero |
| GOD agent as escalation authority | **REJECT** | orchestration must be deterministic |
| Blackboard (`board.md`) | **REJECT** | mutable shared state; Qevik is event-sourced |
| No-separate-approval-queue | **REJECT** | Qevik's approver is often the customer, about artefacts |
| Electron desktop control plane | **REJECT** | `app.qevik.ai` is live and mobile-first |
| Separate task ledger | **REJECT** | `Mission` + timeline already is one |
| Isometric office floor | **DEFER** | a view, not a model; revisit for legibility |
