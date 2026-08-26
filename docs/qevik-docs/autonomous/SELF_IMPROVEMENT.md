# "Add this feature" — from a phone to a commit

*26/26 acceptance, real processes and real restarts. Both screens read at
390×844 and 1280×900.*

    phone → feature request → conversation → model plan OR explicit blocker
    → deterministic policy → approval → mission → scheduler → agent
    → isolated worktree → tests → commit → durable report → mobile status

**No second orchestration system was built.** The path is the existing
chat → plan → approval → mission → worker pipeline. What was missing was a
surface worth trusting and one honest classification.

## The two refusals this rests on

Everything else is plumbing that already worked. These are the parts that had to
be right.

### Qevik never invents a plan

A plan is produced by a model that saw the request, or it is a blocker. There is
no third kind. A template plan is the most damaging possible output: it *looks*
like understanding, a person approves it, and a worker implements steps nobody
derived from anything — wrong in a way that survives review.

The acceptance asserts this directly, not by proxy: with no model reachable the
proposal is `blocked`, has **zero steps**, and names **no model** in its
provenance. Approving it returns 409.

### A rejected credential is not a missing one

This was wrong and is now fixed. When no model could be reached, the blocker
said `PENDING_CREDENTIAL` — *"Add a model credential in the Credential
Centre"* — which is useless advice to somebody who already added one, and sends
them to re-enter a key that is present and behaving exactly as configured.

`BLOCKED_EXTERNAL_PROVIDER` is the honest classification for the state this
deployment is actually in:

> A credential for qwen is configured and the provider is refusing it, so no
> model could be reached.
>
> **This is a problem at qwen, not a missing credential. Nothing here can fix
> it.**

It is also distinct from `PENDING_PROVIDER`, which means the provider *was*
reached and gave a bad answer — worth retrying. This is not.

The screen draws it differently too: a violet rule rather than the red one a
local failure gets, because a provider refusing is not the deployment's fault
and must not read as something somebody here forgot.

## Qevik does not authorise Qevik

The most permissive plan a planner could propose — `approval_required=False`,
half a unit of cost, touching only reviewed-free paths — is still held for a
person, because it changes Qevik's own source. The acceptance drives exactly
that plan and asserts it, with the negative control that the same plan against
customer work is *not* held. The rule is a boundary, not a stop switch.

## What the screen shows

Five states, each with a word and a sentence, because a raw status string made
"blocked", "declined" and "failed" the same shade of bad and hid the one state a
person can act on.

| | |
|---|---|
| Blocked | *This cannot proceed. Nothing here resolves it on its own.* |
| Waiting for you | *Nothing runs until you approve it.* |
| Running | *A worker has it. You can close this page.* |
| Failed | *It ran and did not succeed. The report says what happened.* |
| Complete | *Done. The report is below.* |

Derived from the **mission** where one exists, because the mission is what is
actually happening; the conversation only records how it started.

The plan preview shows the goal, the numbered steps, and — as mono chips rather
than inline prose — **the exact files about to be edited**, which is the part a
reviewer actually has to look at. Then cost, security impact, how it is checked,
and rollback.

Cost goes through one function so no caller can render it another way:

    UNKNOWN — nothing priced this. It is not zero.

The approve control sits *below* the plan. Deliberately: you should not be able
to approve without scrolling past what you are approving.

## Acceptance — 26/26

`infra/verify_self_improvement.py`. Every step through the real HTTP surface,
with a real worker subprocess and the control plane genuinely killed.

1. A feature request becomes a conversation, and **is not a mission** — typing a
   sentence must not queue work.
2. The control plane is killed; nothing serves.
3. Restarted, the request survives **with the words the person typed**.
4. Planning produces a blocker with no steps and no model named.
5. Approving a blocked plan returns 409 and explains itself.
6. The most permissive self-modifying plan cannot authorise itself; the same
   plan against customer work is not held.
7. An approved mission runs in a worker process **with the control plane down**,
   and is complete after a restart with a durable report carrying the evidence.
8. An unpriced mission reports `total_cost` absent, never zero.
9. No key-shaped string in any response or in either durable timeline.

## What is honest about the deterministic agent

Step 6 of the acceptance runs the approved path with `self-check`, a real
executor-backed agent record. It is **not passed off as model work**: the
mission records the agent that ran it, and the conversation in the same run
still says no model produced a plan. `--agent fake` exists and is deliberately
never used here.

When a provider credential works, the same path runs with `LLMCodingAgent` — the
same agent abstraction the worker already uses — with no architectural change.
That is the point of the acceptance being written against the boundary rather
than against the agent.

## Live refresh, and the defect it was hiding

The poll already covered this screen — `chat` is in the list of pages a change
re-renders, and the conversation detail is that page with an argument.

Which meant a real bug. The conversation screen holds the box a feature request
is typed into, so a mission moving from *running* to *complete* re-rendered the
page underneath the person and took the half-written sentence with it — every
four seconds, on the screen whose entire purpose is composing that sentence. The
comment beside the poll already warned about exactly this for Credentials; the
guard was never written.

`typing()` now suppresses the re-render while a field has focus **or** unsent
content. Focus alone is not enough: dismissing a phone keyboard drops focus
while the text stays on screen.

## Not done

- **No push notification**, so "it finished" still requires looking at the
  screen.
- The request input is the existing chat form; it has not had a phone-specific
  pass of its own.
- The five states are derived and displayed, but a mission that fails shows the
  report rather than a summary of *why* — the report has to be read.
