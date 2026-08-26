# Policy above the planner

*The planner could authorise its own work. It cannot now.*

## The defect

`attach_plan` routed on `Plan.approval_required` — a field set by whatever
produced the plan:

```python
destination = (MissionStatus.AWAITING_APPROVAL if plan.approval_required
               else MissionStatus.QUEUED)
```

`FakeCodingAgent` sets that field to `False`. Its plans went **straight to
QUEUED with nobody asked**, and an LLM agent emitting the same value would have
been obeyed identically. The model deciding whether the model's work needs
approval is the one thing the architecture exists to prevent.

## What replaced it

`mission/policy.py` — deterministic, deny by default, above the planner.

    required = policy_says_yes  OR  plan.approval_required

A planner asking for review gets review. A planner saying "no review needed" is
ignored. Same shape as an agent's blast radius against its tools: more cautious
than the rule is allowed, less is not — and when the planner raises it, the
verdict says so, so a planner that always asks is visible rather than
indistinguishable from policy.

### Three requirements, not a boolean

| | |
|---|---|
| `NONE` | cheap, reversible, confined |
| `EXECUTION` | a person agrees the work should happen |
| `ARTEFACT` | a person agrees to the exact output before it leaves |

"Somebody agreed this should happen" and "somebody agreed to *this output* going
live" are different decisions made at different times. Collapsing them turns an
execution approval into permission to publish.

### Qevik does not authorise Qevik

Checked **above every other rule**, including the cheap paths.

The production worker's `--repository` is `/opt/qevik/atlas` — Qevik's own
source. So every mission today edits the system that is deciding whether to
allow it, and a cheap docs-only plan satisfied every rule below and reached the
queue with nobody asked. Self-modification arrived as a side effect of a path
allow-list rather than as anybody's decision.

"Reversible" is doing a lot of work when the thing being changed is the thing
that decides what reversible means.

`modifies_qevik_itself` defaults to **True** — a caller has to state otherwise
to get the cheaper path, so forgetting the argument produces approval rather
than a bypass. A test asserts that default, because a safe default that drifts
to `False` is a bypass nobody notices.

This is the precondition for the self-improvement feature, not an obstacle to
it: "tell Qevik to add a feature" is exactly a mission that edits Qevik, and it
must reach a person before it runs.

### The rules

1. **Irreversible work always needs artefact approval.** Checked first, because
   nothing below can lower it — an email cannot be unsent however cheap it was.
2. **An unnamed agent needs approval.** Work whose performer is unknown has an
   unknown blast radius, and the architecture's own rule is that an unknown
   blast radius is the thing approval cannot work around.
3. **An agent nobody declared is treated as the worst case**, not the best. The
   registry is the record of what an agent may do.
4. **An unpriced plan needs approval** on a metered tenant — the same rule the
   scheduler applies. An unpriced call is not a free one.
5. **Above `COSTLY_UNITS` needs approval.** The question is not "is this
   expensive" but "would somebody want to have been asked".
6. **Writing outside `SAFE_PREFIXES` needs approval.** An allow-list, because a
   deny-list is a promise to have thought of every dangerous path anybody will
   ever add.

The only path to `NONE` is satisfying **every** rule. A new capability arriving
with no matching rule needs a person, which is the correct failure direction for
authority.

### Deterministic

No model, no network, no clock. A source-reading test fails if `policy.py` ever
imports `httpx`, `anthropic`, `random` or `time` — a policy that asked a model
what it should allow would be the same defect wearing a different hat. Another
test runs the same verdict twenty times and asserts it does not move.

That determinism is what makes "the model proposed X and policy allowed it" a
sentence somebody can check.

## What the change surfaced

`chat.approve` transitioned to QUEUED unconditionally after attaching the plan.
That was only safe because `attach_plan` *always* routed to AWAITING_APPROVAL —
the planner's flag was always `True` for a real plan. With policy able to clear
a cheap plan straight to QUEUED, the unconditional transition became
`QUEUED → QUEUED`, which `ALLOWED` refuses — it would have failed the approval a
person had just given.

Three test fixtures also relied on the defect: they built plans with
`approval_required=False` and expected a queued mission. They now **approve**
what policy holds, which is the path production actually has. A fixture that
routed around approval would be testing something production does not do.

The mission lifecycle gained a step it should always have had:

    draft → planning → awaiting_approval → queued → processing → …

## Also fixed

`business_events` — Atlas's permanent memory of a company, which every factory
writes to and every metric derives from — was a plain list in production. A
restart erased the entire history of every business while the businesses
themselves remained. It now folds from `businesses.jsonl`, beside the other
timelines.
