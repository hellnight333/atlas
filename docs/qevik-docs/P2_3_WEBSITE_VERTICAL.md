# P2.3 — the Website vertical, complete

No new capability. The Website vertical closes into a loop a real customer can
travel end to end, and each stage can say honestly what it does and does not
know:

```
Research → Opportunity → Recommendation → Roadmap → Task → Approval → Job
  → Execution → Asset bundle → QA → Stage/Preview → Artefact approval
  → Publication → Measurement → Re-evaluation
```

---

## 1. Files changed

| File | |
|---|---|
| `publication/staging.py` | new — `ArtefactState`, `StagedVersion`, `stage`, `is_live` |
| `tests/test_website_vertical.py` | new — 26 tests |
| `research/net.py` | `Resolution`, `host_of`, `resolution` |
| `research/discovery.py` | emits the `website` finding |
| `outreach/opportunity.py` | the `no_website` rule |
| `recommendation/offers.py` | `offer-website` answers `no_website` |
| `execution/capabilities/website.py` | `SiteState`, `site_state`, UNVERIFIED refusal |
| `measurement/service.py` | `Progress`, `progress_of`, `record_intervention`, `from_publication`, `report` |
| `measurement/attribution.py` | agency pattern generalised past enumerated subjects |
| `roadmap/service.py` | `Change`, `_outcomes`, reworded measurement copy |
| `roadmap/presentation.py` | `capabilities()` — offered vs executable |
| `publication/{service,__init__}.py` | one staging entry point |
| `tests/{test_website_capability,test_publication}.py` | fixtures declare site state |

**No schema, no migration, no new registry, no new approval mechanism, no new
job-state vocabulary.**

## 2. Systems reused

`ApprovalService` · `Run`/`Job`/`Asset` · the six QA gates · `DeploymentTarget`
publish/promote and `LocalDirectoryTarget` · `PublicationRecord` and
`PublicationStatus` · the P1.4 attribution model · `BusinessEvent` · tenancy ·
`website/content.py` and `website/generation.py` · the opportunity `Rule`
registry · `sales.PRODUCTS` (the `no_website` rule reuses **Landing
experience** rather than adding a product).

## 3. CREATE vs MODIFY — four states, not two

The distinction the phase exists for. `research/discovery.py` now emits a
`website` finding:

| Situation | `website` | Meaning |
|---|---|---|
| Nothing on file | `NOT_FOUND` | Conclusive |
| DNS: no such host | `NOT_FOUND` | Conclusive |
| Resolves, did not answer | `UNVERIFIED` | Establishes nothing |
| Answered | `PRESENT` | A site exists |

`SiteState` folds that into `ABSENT` / `UNVERIFIED` / `WEAK` / `STRONG`, where
weak-vs-strong is whether `improvable()` finds a confirmed-absent feature this
capability fixes.

- **ABSENT → CREATE.** `no_website` fires and `offer-website` answers it.
- **UNVERIFIED → nothing.** No opportunity, and `build_website` raises: *"that
  is a gap in what we checked, not a gap in their business."*
- **WEAK → MODIFY**, addressing only confirmed absences.
- **STRONG → nothing.** Still raises.

**DNS is asked only after the HTTP request failed.** Asking first spent a lookup
on every healthy site and — worse — overrode a caller's injected HTTP transport
with the real network, which broke four research-pipeline tests using a mocked
client. The happy path now costs no lookup, and a test's transport is honoured.

## 4. Staging lifecycle

Four words that get used interchangeably and are not the same:

| | |
|---|---|
| `GENERATED` | The capability ran. QA has not passed. |
| `READY_TO_STAGE` | QA passed. Nothing has left the kernel. |
| `STAGED` | At the target, fetchable at a preview URL, **serving nobody**. |
| `APPROVED` | A person looked at the staged version and said yes. |
| `PUBLISHED` | Promoted. Visitors get it. |

`ArtefactState` folds these from the execution outcome, the stage record, the
approval and the publication record — derived, never stored, for the same reason
as the roadmap's task state.

**Staging is checkably not publishing.** `is_live()` asks the target which
version visitors actually get, and `can_answer_what_is_live()` says whether that
question means anything for this adapter — an adapter that does not know is not
evidence that nothing is live.

`stage()` refuses before `READY_TO_PUBLISH`: staging a rejected artefact puts a
fetchable link to it in an approval request, and somebody will approve it.

A preview URL is a working link to unpublished work, so `staging.read` is
tenant-scoped and `stage` refuses another tenant's execution.

There is now **one** staging entry point. `service.stage` and `staging.stage`
would have been two ways to put files at a target, and the difference would have
been invisible.

## 5. Measurement lifecycle

`Progress` gives the five answers a customer can be given, because "no number
yet" has four different causes:

| | |
|---|---|
| `measurement_unavailable` | No source. Not zero, not bad. |
| `baseline_available` | A reading was taken before the work. |
| `measurement_pending` | The work happened; the window has not closed. |
| `intervention_occurred` | The window closed; nobody has read it again. |
| `observed_change` | Both ends exist. |

`from_publication(baseline, record)` joins the two layers: the record's
`completed_at` **is** the intervention. It refuses a record that did not publish
— a failed attempt changed nothing, and treating it as an intervention starts a
window against work that never happened. `record_intervention` refuses when no
baseline was taken, because a baseline captured afterwards is not a baseline.

`report()` runs `vet` over the measurement's own statement before returning it,
so a wording change that overstepped fails there rather than in front of a
customer.

## 6. Re-evaluation lifecycle

`changed()` now returns typed `outcomes`:

`unchanged` · `newly_measured` · `dimension_improved` · `dimension_worsened` ·
`new_opportunity` · `opportunity_resolved` · `task_no_longer_required`.

Direction is read from the **scores**, not from whether a task disappeared: work
leaves a plan because it was done, because the capability went away, or because
the evidence was withdrawn, and only the first is good news.

Neither roadmap is mutated. A test captures the earlier plan's fingerprint, task
ids and timestamp and asserts all three survive re-evaluation.

## 7. Offered vs executable

`presentation.capabilities()` derives two lists from the two registries at call
time — a hand-maintained "what works" list goes stale the day somebody ships an
executor and forgets it.

**Executable:** `offer-portfolio-system`, `offer-website`.
**Offered only:** Arabic, editorial, imagery, one-tap contact, enquiry builder —
each labelled *"described, not yet buildable — Qevik will not schedule it"*.

Per the brief, none of those four was implemented. What changed is that a
customer can now see the boundary rather than infer it.

## 8. Two more holes found in the attribution gate

**`"The new website caused the increase."` passed at ASSOCIATED.** `_AGENCY`
enumerated its subjects — `this|the campaign|the intervention|it` — so the one
sentence a website capability actually invites was the one not covered. Any
subject followed by `caused`, `resulted in`, `led to` or `brought about` is now
an agency claim.

**Our own roadmap copy failed its own gate**, twice in one sentence: *"a
baseline taken **after the work** has started"* reads as a sequence claim, and
the word *"measured"* reads as a change claim. The gate was right both times and
the sentence changed. A check now confirms every standing `MEASUREMENT_TASK` and
`WEAKNESS` string passes at `UNKNOWN`.

## 9. Negative controls — all twelve, 26 tests

| Required | Test |
|---|---|
| Missing website treated as weak | `test_a_missing_website_is_not_scored_as_a_weak_one` |
| Unverifiable treated as missing | `test_a_website_that_could_not_be_checked_is_not_a_missing_one`, `…_produces_no_opportunity_at_all` |
| Staged site publicly accessible | `test_a_staged_site_is_not_reachable_by_the_public`, `test_staging_an_artefact_that_failed_qa_is_refused` |
| Publication without artefact approval | `test_publication_without_artefact_approval_is_refused` |
| Modified bytes after approval | `test_bytes_modified_after_approval_are_refused` |
| READY_TO_PUBLISH as PUBLISHED | `test_ready_to_publish_is_not_published`, `test_the_four_states_are_distinct` |
| Measurement without baseline | `test_an_intervention_without_a_baseline_is_refused` |
| Measurement without intervention | `test_a_baseline_with_no_intervention_reports_no_result`, `test_a_failed_publication_is_not_an_intervention` |
| Causal claim without evidence | `test_no_causal_claim_survives_without_the_evidence_for_it` |
| Roadmap mutated | `test_re_evaluation_generates_a_new_state_and_leaves_the_old_one` |
| Cross-tenant preview | `test_another_tenant_cannot_stage`, `test_another_tenant_cannot_read_a_preview` |
| Cross-tenant publication | `test_another_tenant_cannot_publish` |

Plus the whole-loop run
(`test_a_business_with_no_website_goes_from_research_to_published`), the
five-state measurement sweep, and the offered-vs-executable controls.

**Full suite: 2211 passed, 25 skipped.** ruff 22 (baseline 43), mypy 135
(baseline 135) — P2.3 adds none.

## 10. What is genuinely production-ready

- **The decision chain.** Research → opportunity → recommendation → roadmap →
  two approvals → publication, every step evidence-backed, tenant-scoped and
  refusable, with negative controls on each refusal.
- **The honesty guarantees.** No fabricated facts on a page, no manufactured
  weakness, no capability promised that cannot run, no causal claim the evidence
  does not license, approved bytes equal published bytes.
- **The website capability itself** for a business whose facts Qevik already
  holds — CREATE and MODIFY, deterministic, refusing when there is nothing to do.
- **Publication to a filesystem target**, with immutable provenance and a
  failure that is recorded rather than lost.

## 11. What is intentionally not implemented

- **No remote host is connected.** The local target is a real target and a real
  web server can sit in front of it, but nothing publishes to Cloudflare or over
  SSH yet. Those adapters exist and each needs a `Connection` kind and a
  resolver.
- **Four offers still have no executor.** Now visible to the customer.
- **The site is one page.** `SiteContent` is medium-agnostic; nothing renders a
  page per service yet.
- **Nothing schedules the second reading.** `close_measurement` exists and must
  be called; no cron closes a window 30 days after publication.
- **No HTTP surface.** `view()`, `capabilities()` and `report()` are structures
  with gates; no route returns them.
- **No credits, billing, portal, CRM, social, video, ecommerce or marketplace
  work**, and none started.
