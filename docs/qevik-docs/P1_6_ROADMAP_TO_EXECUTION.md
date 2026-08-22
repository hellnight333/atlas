# P1.6 — Roadmap → Execution, and the loop closed

Joins the plan to the machinery that does the work, without building any new
machinery. The loop now runs end to end:

```
Research → Evidence → Opportunity → Recommendation → Roadmap → Task
  → Approval → Job → Execution → Asset → QA → READY_TO_PUBLISH
  → Measurement → Re-evaluation → Updated Roadmap
```

Every stage after **Task** already existed. What P1.6 adds is the crossing, the
conditions guarding it, and the honest reporting on both sides of it.

---

## 1. Files changed

| File | |
|---|---|
| `roadmap/lifecycle.py` | new — derived task state |
| `roadmap/gate.py` | new — the seven conditions |
| `roadmap/crossing.py` | new — task → approval → job |
| `roadmap/presentation.py` | new — the customer-facing view |
| `tests/test_roadmap_execution.py` | new — 36 tests |
| `roadmap/models.py` | `RoadmapTask.tenant_id` |
| `roadmap/service.py` | executability now consults `EXECUTORS`; `changed()` explains itself |
| `roadmap/readiness.py` | `INVERTED` polarity registry |
| `measurement/service.py` | `open_baseline` · `close_measurement` · `awaiting_source` |
| `execution/service.py` | `may_execute`/`execute` accept `customer_done` |
| `recommendation/service.py` | customer-task completion events |
| `tests/test_roadmap.py` | two assertions corrected by the polarity fix |

**No schema or migration changes.** A roadmap, a customer completion and an
execution are all `BusinessEvent`s on the existing timeline.

## 2. Existing systems reused

`ApprovalService` / `ApprovalRequest` / `ApprovalState` (the same service the
Media Factory publishes through and outreach contacts strangers through) ·
`Run` · `Job` · `JobStatus` · `Asset` and its provenance metadata ·
`execution.service.execute` and its six QA gates · `RecommendationState` ·
`CapabilityOffer` and `EXECUTORS` · `opportunity.tenancy` · `BusinessEvent` ·
the P1.4 attribution model.

No second job system, task registry, approval system or lifecycle.

## 3. New models and functions

`TaskState` · `TaskFacts` · `facts_for()` · `state_of()` · `blockers()` ·
`NotExecutable` · `Readiness` · `fingerprint()` · `unmet()` · `check()` ·
`require()` · `request_approval()` · `execute_task()` · `requested_event()` ·
`executed_event()` · `Overclaim` · `vet()` · `task_view()` · `view()` ·
`SourceUnavailable` · `open_baseline()` · `close_measurement()` ·
`awaiting_source()` · `customer_task_event()` · `completed_customer_tasks()`.

## 4. Task lifecycle — derived, never stored

Nine states, none of them owning any data: `state_of(task, facts)` folds from
`RecommendationState`, `ApprovalState`, `JobStatus` and the roadmap's own
dependency graph.

A stored status can disagree with the job it describes, and when it does nobody
can tell which is lying. A derived one has nothing of its own to disagree with.

Two ordering decisions carry meaning:

- **What already happened outranks what is merely allowed.** A task whose job
  completed is COMPLETED whatever its approval now says.
- **Acceptance outranks blockers.** Before a customer accepts, a task is
  PROPOSED — saying something is "blocked" on work nobody agreed to reads as a
  problem on a plan they have not said yes to.

`FAILED` is deliberately distinct from `COMPLETED`: collapsing them is the same
error as calling a completed task a success.

## 5. Approval integration

`request_approval()` builds an `ApprovalContext` and calls
`ApprovalService.create_request`. The decision is an authenticated human call;
nothing in `roadmap/` can approve anything, and a test reads the source to
confirm it.

The approval carries `TASK_FINGERPRINT`, over what the act *is* — capability,
recommendation, evidence, title. Change any of those and the decision no longer
applies. **Rescheduling does not invalidate it**: invalidating a decision
because a task moved from the 30-day to the 60-day horizon would train people to
re-approve without reading.

The payload states `"publishes": false` in words, because what is being approved
is the work, not its publication.

## 6. Execution readiness — seven conditions, fail-closed

Whose task it is · a capability is named · the recommendation exists and matches
· evidence is recorded · tenancy on both task and recommendation · dependencies
and outstanding customer work · an approval that is APPROVED and fingerprint-
matched. Then `execution.service.may_execute` is **called**, not restated, so
the two cannot drift.

`unmet()` returns *every* reason. Reporting one at a time turns a blocked task
into a queue of surprises. A missing tenant is refused rather than treated as
"any" — the opposite default would make an unscoped call the most permissive
one available.

## 7. Measurement integration

`open_baseline()` records what a metric read before anything was done to it.

- **No source → `SourceUnavailable`.** Not a zero-valued baseline: a zero is a
  reading, and a reading nobody took is the most damaging thing this layer can
  invent, because every later comparison against it shows improvement.
- **`value=None` is allowed** and means the source was reachable and had nothing
  to report — reported as `NO_BASELINE`, `UNKNOWN` confidence, `improved=None`.
- `close_measurement()` requires the intervention timestamp rather than
  defaulting it, because whether the work preceded the observation is what
  separates OBSERVED from ASSOCIATED.
- `awaiting_source()` answers "why is there no number yet" in words that cannot
  be read as poor performance.

An 80% rise with correct ordering still reports **ASSOCIATED**, not ATTRIBUTED,
and refuses `"Qevik increased their clicks"`. Even ATTRIBUTED does not license
sole agency.

## 8. Re-evaluation

`changed()` now returns `dimensions_moved`, `newly_measured` and `why` — one
sentence per change, naming the evidence that moved it. Neither roadmap is
mutated; both remain in the event timeline, and this is a reading across them.

Identical evidence produces `changed: False` and an empty `why`.

Real output when AHS's Arabic gap is closed:

> `'Arabic experience'` is no longer proposed: multilingual is now confirmed in
> place, so there is nothing to do there.

A statement about the site. `"the work succeeded"` would be a claim about a
result, and a roadmap has no standing to make one — every explanation is passed
through the attribution gate at UNKNOWN.

## 9. Presentation

`view()` returns readiness with its confidence and what is already working,
`next`, the four horizons, `qevik_can_execute`, `your_tasks`, `no_capability`,
`not_yet_measured`, `blocked`, and per task: who acts, why, dependencies, what
is in the way, expected measurement, confidence and evidence.

**The gate runs at build time and raises.** Returning an unvetted view and
checking it at the edge would put the check in whichever surface remembered to
call it, and the one that forgets is the one that ships. `_measurement()` says a
metric "would be watched", never that it will improve.

Not a portal. No billing, credits or publishing.

## 10. Two real bugs found

**Five capabilities were presented as executable that nothing could perform.**
Six `CapabilityOffer`s exist; `EXECUTORS` has one. The roadmap read the offer
catalogue and marked all of them `QEVIK_CAN_EXECUTE` — a promise the execution
gate would then refuse, after the customer had read it as a plan. `EXECUTORS` is
now the authority, and the customer obligations attached to unexecutable work
are no longer requested either.

**`portfolio_depth` was scored as a strength and is a defect.** The research
pipeline normalises polarity almost everywhere — `orphan_pages` is PRESENT when
there are none. `research/cms/base.py` emits `portfolio_depth` PRESENT with the
evidence *"N pages are photographs with almost no text"*, and
`outreach/opportunity.py` uses that same PRESENT as the trigger for the proof
opportunity. Readiness read it as proof of proof, scored AHS **strong** on it,
and suppressed the one opportunity their audit calls their biggest gap.

Fixed with an explicit `INVERTED` registry rather than by renaming the feature:
three modules already agree on the name and the meaning, and only this module's
reading of it was wrong. AHS's proof moved from 100 to 67, and the portfolio
system — the capability that actually has an executor — is now on their plan.

Two P1.5 assertions had encoded the wrong belief and were corrected.

## 11. Tenant enforcement

`RoadmapTask.tenant_id` is denormalised exactly as P1.1 did for businesses and
P1.2 for recommendations, so the gate scopes a single task without needing the
roadmap it came from. Checked on the task *and* its recommendation; `None` is
refused; `completed_customer_tasks()` is tenant-scoped.

## 12. Tests — 36 new, 2123 passing overall

| Required control | Test |
|---|---|
| QEVIK_TASK without capability | `test_a_task_cannot_execute_without_its_capability` |
| Qevik executing a CUSTOMER_TASK | `test_qevik_cannot_execute_a_customer_task`, `…never_relabelled_on_the_way_to_execution` |
| Unresolved dependencies | `test_a_task_with_unresolved_dependencies_cannot_execute` + `…is_what_unblocks_it` |
| Bypassing approval | `test_a_task_cannot_bypass_approval`, `test_a_rejected_approval_does_not_execute`, `…cannot_be_spent_on_another`, `test_nothing_in_this_module_can_approve_anything` |
| Another tenant | `test_a_task_from_another_tenant_cannot_execute`, `test_a_task_with_no_tenant_belongs_to_nobody` |
| Completion ⇒ success | `test_a_completed_task_does_not_imply_a_successful_outcome`, `test_a_failed_job_is_not_reported_as_completed` |
| Missing baseline ⇒ zero | `test_a_missing_baseline_does_not_become_zero`, `…not_reported_as_poor_performance` |
| Manufactured causation | `test_measurement_cannot_manufacture_causation`, `test_reaching_attributed_requires_a_named_source` |
| Unchanged evidence regenerating | `test_unchanged_evidence_does_not_regenerate_the_roadmap` |
| Explainable delta | `test_changed_evidence_produces_an_explainable_delta`, `…does_not_destroy_the_previous_plan` |
| Unavailable capability shown executable | `test_an_unavailable_capability_is_never_presented_as_executable`, `test_a_capability_with_no_executor_is_not_marked_executable` |
| READY_TO_PUBLISH ⇒ PUBLISHED | `test_a_ready_to_publish_asset_is_not_treated_as_published`, `…says_plainly_that_it_does_not_publish` |

Plus the AHS controls (§9 of the brief): no work on what is already working, at
most one promised capability, and every non-measurement task resting on
evidence — and the whole-loop proof,
`test_the_complete_transition_from_roadmap_to_ready_to_publish`.

**Full suite: 2123 passed, 25 skipped.** ruff 35 (was 43), mypy 135 (unchanged);
P1.6 adds none.

## 13. Scope held

No credits, billing, payments, Amazon/Noon, advertising, social publishing,
autopilot, CRM, new provider integrations or production publishing. `publish()`
still raises.

## 14. Remaining P1 work

- **One executor.** Five offers have none, and the roadmap is now honest about
  it — but honest and useful are different. Each new executor is a capability
  with a QA gate, not framework work.
- **Task completion is not yet an event.** `state_of` reads a `JobStatus` handed
  to it; nothing yet folds job completion from the timeline into `TaskFacts`.
- **`close_measurement` has no scheduler.** Nothing re-reads a metric 30 days
  after an intervention; the function exists and must be called.
- **No surface renders `view()`.** It is a structure with a gate, and no HTTP
  route or page yet returns it.

## 15. What begins in P2

Publication — a target, a credential and a second approval on the artefact
itself. Then the capabilities beyond the website: marketplaces, advertising,
social, CRM, and the billing that makes any of it a business. All of it sits
behind the same boundary this phase drew, and none of it changes the rule that
`READY_TO_PUBLISH` is not `PUBLISHED`.
