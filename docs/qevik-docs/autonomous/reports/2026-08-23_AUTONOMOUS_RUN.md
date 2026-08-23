# Autonomous run — 2026-08-23

**Agent:** Claude Opus 5 (1M context), Claude Code
**Range:** `44f975b` → `f56f46f` (12 commits)
**Cost:** UNKNOWN — this environment exposes no token or price accounting to the
agent. Recorded as UNKNOWN rather than estimated, per the rule that an
unlabelled figure reads as authoritative and cannot be checked.

## Objective

Continue the authoritative roadmap autonomously, reconcile all governing
documents, and build the control-plane foundation.

## What was implemented

| Unit | Commit | Tests |
|---|---|---|
| P1.7 credits / plans / quota | `9953cc8` | 23 |
| P2 editorial capability | `eea841e` | 11 |
| P4 public audit route | `41f47b4` | 6 |
| P3 AI visibility + credential centre | `46d618e` | 15 |
| Blocker-first action centre | `a945c4e` | 17 |
| P4 plan / usage surface | `200190b` | 5 |
| Roadmap reconciliation (3 documents) | `b696f8a` | — |
| P8 agency / white label | `c40f95e` | 13 |
| Mission state machine + persistence | `f56f46f` | 22 |

**Full suite 2374 passed, 25 skipped.** ruff 22, mypy 135 — both unchanged from
the start of the run. ~112 tests added, every one with negative controls.

## Systems reused rather than duplicated

`QuotaLedger` (credits reserve against it) · `ApprovalService` · `Job`/`JobStatus`
(missions reference, never replace) · `publication.Connection` (the only
credential model) · `opportunity.tenancy` · `BusinessEvent` (all new state is
event-sourced) · `CapabilityOffer.estimated_units` (the only price list) ·
`AIVisibilityObservation` · `organization.Membership` (agency access *is*
membership) · `website/content.py` (editorial writes no facts).

## New models

`Plan`, `Reservation`, `Integration`, `HumanAction`, `Sweep`, `Delegation`,
`Mission`, `MissionStatus`, `AgentInvocation`, `Blocker`, `PlanStep`,
`LocalFixtureProvider`, `PendingCredentialProvider`.

## Schema changes

**None this run.** Every new subsystem persists as `BusinessEvent`s.

## Security

Tenant isolation preserved and extended to agency delegation. No credential
value in any event, report, action or error. `db_safety` untouched. Two approval
boundaries intact. Publication still ends at `READY_TO_PUBLISH`.

**Known gaps, not closed:** rate limiting, webhook verification, SSRF protection
on future outbound fetches, multi-worker atomic claim.

## Honest status

The programme is **not complete**. Product A (evidence engine) is substantially
built; Product B (execution platform) is mostly unbuilt and largely gated on
hosts rather than code; Product C (media business) is deferred as a separate
concern.

**Not done and not started:** agent-provider abstraction, chat intake, worker
process, app.qevik.ai UI, multi-page websites, media capability, P5/P6/P7
adapters, Qevik self-use, existing-business reprocessing.

**Nothing was published, sent, charged or connected. No production data was
touched. No external API was called.**

## Next autonomous action

Highest-priority unblocked work, in order:

1. Agent-provider abstraction (`plan`/`implement`/`review`/`summarize`), with a
   local fake provider — the mission layer already records invocations.
2. Worker loop over `claim` → `transition` → `release`, single-worker.
3. P2 multi-page website: the blocker is `themes/clean.py::render` emitting one
   page with no navigation block.
4. Customer write routes (complete a task, request an approval).
