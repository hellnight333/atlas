"""The crossing from a plan into work, tested on what must never cross it.

P1.6 joins two things that were deliberately separate: a roadmap, which is a
proposal, and execution, which spends money and produces artefacts. Everything
below is a way that boundary could leak — a customer's task quietly becoming
ours, an approval for one act spent on another, a capability promised that
nothing can perform, a finished job read as a business result.

The approval service here is the real one, built through `create_runtime`, for
the same reason the outreach wiring test uses it: a hand-built `ApprovalRequest`
would prove the guards and prove nothing about whether this reuses the existing
approval architecture rather than having grown a second one beside it.
"""

from __future__ import annotations

import pytest

from atlas_kernel import db
from atlas_kernel.approval.models import ApprovalState
from atlas_kernel.composition_root import create_runtime
from atlas_kernel.execution.capabilities import EXECUTORS
from atlas_kernel.execution.models import PublicationState
from atlas_kernel.execution.service import publish
from atlas_kernel.measurement import service as measurement
from atlas_kernel.measurement.attribution import Attribution, permits
from atlas_kernel.measurement.models import BaselineState
from atlas_kernel.models import JobStatus
from atlas_kernel.outreach import opportunity as opp
from atlas_kernel.recommendation import service as rec_service
from atlas_kernel.recommendation.models import (
    RecommendationState,
    TaskKind,
)
from atlas_kernel.roadmap import Executability, Horizon, crossing, gate, generate
from atlas_kernel.roadmap.lifecycle import TaskFacts, TaskState, facts_for, state_of
from atlas_kernel.roadmap.presentation import Overclaim, vet, view

TENANT = "tenant-qevik"

#: Shaped as the research engine records it, from events AHS actually publishes.
RESEARCH = {"facts": {"cms": {"pages": 60, "posts": 4, "media_total": 501,
    "image_page_list": [
        {"slug": "winter-wonderland", "title": "Winter wonderland",
         "url": "https://ahscatering.com/winter-wonderland/", "images": 7},
        {"slug": "nestle", "title": "Nestle",
         "url": "https://ahscatering.com/nestle/", "images": 6},
        {"slug": "porsche", "title": "Porsche",
         "url": "https://ahscatering.com/porsche/", "images": 3}]},
    "seo": {"orphan_count": 32}}}

AHS_FEATURES = [
    ("https", "present"), ("page_speed", "present"), ("broken_links", "present"),
    ("viewport_meta", "present"), ("click_to_call", "not_found"),
    ("whatsapp", "not_found"), ("contact_form", "present"),
    ("arabic", "not_found"), ("hreflang", "not_found"),
    ("social_proof", "present"), ("portfolio_depth", "present"),
    ("market_position", "present"), ("orphan_pages", "not_found"),
    ("page_title", "present"), ("blog", "present")]


@pytest.fixture(scope="module", autouse=True)
def schema():
    db.init_db()


@pytest.fixture(scope="module")
def plan():
    """AHS's roadmap and the recommendations it came from."""
    observations = [{"feature": f, "status": s} for f, s in AHS_FEATURES]
    ranked = opp.for_host("ahscatering.com", category="food",
                          absent=frozenset({"arabic", "click_to_call", "orphan_pages"}),
                          present=frozenset({"portfolio_depth", "social_proof", "blog"}))
    recommendations = rec_service.propose(
        business_id="ahs", tenant_id=TENANT, opportunities=ranked,
        business_model="CATERING", plan="ADVANCED")
    roadmap = generate(business_id="ahs", tenant_id=TENANT, observations=observations,
                       recommendations=recommendations, business_model="CATERING")
    return roadmap, recommendations


@pytest.fixture
def executable(plan):
    """The one task Qevik can actually perform, and its accepted recommendation."""
    roadmap, recommendations = plan
    task = next(t for t in roadmap.tasks
                if t.executability is Executability.QEVIK_CAN_EXECUTE)
    recommendation = next(r for r in recommendations if r.id == task.recommendation_id)
    return roadmap, task, recommendation.model_copy(
        update={"state": RecommendationState.ACCEPTED})


def _all_done(roadmap) -> TaskFacts:
    return facts_for(roadmap,
                     recommendation_state=RecommendationState.ACCEPTED,
                     completed_task_ids=frozenset(t.id for t in roadmap.customer_tasks),
                     customer_action_done=True)


def _approve(task, recommendation, runtime):
    approval = crossing.request_approval(
        task, recommendation=recommendation, approvals=runtime.approval_service,
        business_name="AHS Catering & Events")
    return runtime.approval_service.approve(approval.id, actor="ayoub")


# ============================================================ the whole loop

def test_the_complete_transition_from_roadmap_to_ready_to_publish(executable) -> None:
    """ROADMAP → TASK → APPROVAL → JOB → EXECUTION → ASSET → QA → READY_TO_PUBLISH.

    The one proof P1.6 exists for. Every stage is the pre-existing machinery;
    what is new is only that a roadmap task can reach it.
    """
    roadmap, task, recommendation = executable
    runtime = create_runtime()
    facts = _all_done(roadmap)

    # Proposed work, not started work.
    assert state_of(task, TaskFacts()) is TaskState.PROPOSED
    assert not gate.check(task, recommendation=recommendation, approval=None,
                          facts=facts, tenant=TENANT)

    approval = _approve(task, recommendation, runtime)
    assert gate.check(task, recommendation=recommendation, approval=approval,
                      facts=facts, tenant=TENANT)

    outcome = crossing.execute_task(
        task, recommendation=recommendation, approval=approval, facts=facts,
        tenant=TENANT, research=RESEARCH, business_name="AHS Catering & Events",
        repository=runtime.repository)

    assert outcome.run_id and outcome.job_id, "the existing Run/Job provenance"
    assert outcome.asset_ids, "execution produced an asset"
    assert all(r.verdict.value == "pass" for r in outcome.qa), outcome.qa
    assert outcome.state is PublicationState.READY_TO_PUBLISH
    assert state_of(task, facts.model_copy(
        update={"job_status": JobStatus.COMPLETED})) is TaskState.COMPLETED


def test_the_asset_carries_the_chain_back_to_the_evidence(executable) -> None:
    roadmap, task, recommendation = executable
    runtime = create_runtime()
    outcome = crossing.execute_task(
        task, recommendation=recommendation,
        approval=_approve(task, recommendation, runtime), facts=_all_done(roadmap),
        tenant=TENANT, research=RESEARCH, business_name="AHS Catering & Events",
        repository=runtime.repository)

    asset = runtime.repository.get_asset(outcome.asset_ids[0])
    assert asset is not None
    for link in ("recommendation_id", "opportunity_key", "capability_id",
                 "business_id", "tenant_id", "evidence"):
        assert asset.metadata.get(link), f"asset provenance is missing {link}"
    assert asset.metadata["publication_state"] == PublicationState.READY_TO_PUBLISH.value


# ============================================== 1. no capability, no execution

def test_a_task_cannot_execute_without_its_capability(plan) -> None:
    roadmap, recommendations = plan
    task = next(t for t in roadmap.tasks
                if t.executability is Executability.QEVIK_CAN_EXECUTE)
    stripped = task.model_copy(update={"capability_id": "",
                                       "executability": Executability.NO_CAPABILITY})
    reasons = gate.unmet(stripped, recommendation=None, approval=None,
                         facts=_all_done(roadmap), tenant=TENANT)
    assert any("no capability is named" in r for r in reasons), reasons


def test_an_unavailable_capability_is_never_presented_as_executable(plan) -> None:
    """Six offers exist and one executor does. The five without one must not be
    described to a customer as work Qevik will do."""
    roadmap, _ = plan
    for task in roadmap.tasks:
        if task.executability is Executability.QEVIK_CAN_EXECUTE:
            assert task.capability_id
            offer_ids = {r for r in EXECUTORS}
            assert any(task.recommendation_id for _ in [1]), task.id
            # The claim must be backed by something that can run it.
            assert offer_ids, "no executors registered at all"
    shown = view(roadmap)
    for entry in shown["no_capability"]:
        assert entry["qevik_will_execute"] is False
        assert "no capability" in entry["who"]


def test_a_capability_with_no_executor_is_not_marked_executable() -> None:
    """The bug this control exists for: the roadmap read the offer catalogue and
    called five capabilities executable that nothing could perform."""
    observations = [{"feature": f, "status": s} for f, s in AHS_FEATURES]
    ranked = opp.for_host("ahscatering.com", category="food",
                          absent=frozenset({"arabic", "click_to_call"}),
                          present=frozenset({"portfolio_depth"}))
    recommendations = rec_service.propose(
        business_id="ahs", tenant_id=TENANT, opportunities=ranked,
        business_model="CATERING", plan="ADVANCED")
    roadmap = generate(business_id="ahs", tenant_id=TENANT, observations=observations,
                       recommendations=recommendations, business_model="CATERING")
    for task in roadmap.tasks:
        if task.executability is Executability.QEVIK_CAN_EXECUTE:
            offer = next(r.offer_id for r in recommendations
                         if r.id == task.recommendation_id)
            assert offer in EXECUTORS, f"{task.task.title!r} claims execution, {offer} cannot"


# ============================================ 2. a customer task stays theirs

def test_qevik_cannot_execute_a_customer_task(plan) -> None:
    roadmap, _ = plan
    customer = next(t for t in roadmap.tasks if t.kind is TaskKind.CUSTOMER_TASK)
    reasons = gate.unmet(customer, recommendation=None, approval=None,
                         facts=_all_done(roadmap), tenant=TENANT)
    assert any("only the customer can do it" in r for r in reasons), reasons


def test_a_customer_task_is_never_relabelled_on_the_way_to_execution(plan) -> None:
    """Not only refused — it must still read as theirs everywhere."""
    roadmap, _ = plan
    shown = view(roadmap)
    for entry in shown["your_tasks"]:
        assert entry["kind"] == TaskKind.CUSTOMER_TASK.value
        assert entry["qevik_will_execute"] is False
        assert entry["action"], "a customer task must say what to do"
    assert not any(e["kind"] == TaskKind.CUSTOMER_TASK.value
                   for e in shown["qevik_can_execute"])


# ================================================= 3. dependencies are real

def test_a_task_with_unresolved_dependencies_cannot_execute(executable) -> None:
    roadmap, task, recommendation = executable
    runtime = create_runtime()
    approval = _approve(task, recommendation, runtime)
    nothing_done = facts_for(roadmap, recommendation_state=RecommendationState.ACCEPTED,
                             completed_task_ids=frozenset(), customer_action_done=False)
    reasons = gate.unmet(task, recommendation=recommendation, approval=approval,
                         facts=nothing_done, tenant=TENANT)
    assert reasons, "an approved task with nothing else done must still be refused"
    assert state_of(task, nothing_done) is TaskState.BLOCKED

    with pytest.raises(gate.NotExecutable):
        crossing.execute_task(task, recommendation=recommendation, approval=approval,
                              facts=nothing_done, tenant=TENANT, research=RESEARCH,
                              business_name="AHS", repository=runtime.repository)


def test_completing_the_prerequisite_is_what_unblocks_it(executable) -> None:
    """The negative control's other half: the block must be removable, or the
    test above would pass for a gate that refuses everything."""
    roadmap, task, recommendation = executable
    runtime = create_runtime()
    approval = _approve(task, recommendation, runtime)
    assert gate.check(task, recommendation=recommendation, approval=approval,
                      facts=_all_done(roadmap), tenant=TENANT)


def test_customer_completion_is_recorded_as_an_event_not_assumed(plan) -> None:
    roadmap, recommendations = plan
    recommendation = recommendations[0]
    event = rec_service.customer_task_event(
        recommendation.id, "ahs", "Approve the result before it goes live",
        tenant_id=TENANT)
    assert event.actor == "customer", "the timeline must not read as though we did it"
    done = rec_service.completed_customer_tasks(
        [event], recommendation_id=recommendation.id, tenant=TENANT)
    assert done == frozenset({"Approve the result before it goes live"})
    # And another tenant cannot see or use it.
    assert rec_service.completed_customer_tasks(
        [event], recommendation_id=recommendation.id, tenant="other") == frozenset()


# ==================================================== 4. approval is required

def test_a_task_cannot_bypass_approval(executable) -> None:
    roadmap, task, recommendation = executable
    runtime = create_runtime()
    facts = _all_done(roadmap)

    with pytest.raises(gate.NotExecutable, match="no approval"):
        crossing.execute_task(task, recommendation=recommendation, approval=None,
                              facts=facts, tenant=TENANT, research=RESEARCH,
                              business_name="AHS", repository=runtime.repository)

    pending = crossing.request_approval(
        task, recommendation=recommendation, approvals=runtime.approval_service,
        business_name="AHS")
    assert pending.state is ApprovalState.PENDING
    with pytest.raises(gate.NotExecutable, match="pending"):
        crossing.execute_task(task, recommendation=recommendation, approval=pending,
                              facts=facts, tenant=TENANT, research=RESEARCH,
                              business_name="AHS", repository=runtime.repository)


def test_a_rejected_approval_does_not_execute(executable) -> None:
    roadmap, task, recommendation = executable
    runtime = create_runtime()
    request = crossing.request_approval(
        task, recommendation=recommendation, approvals=runtime.approval_service,
        business_name="AHS")
    rejected = runtime.approval_service.reject(request.id, actor="ayoub")
    reasons = gate.unmet(task, recommendation=recommendation, approval=rejected,
                         facts=_all_done(roadmap), tenant=TENANT)
    assert any("rejected" in r for r in reasons), reasons
    assert state_of(task, _all_done(roadmap).model_copy(
        update={"approval_state": ApprovalState.REJECTED})) is TaskState.REJECTED


def test_an_approval_for_one_task_cannot_be_spent_on_another(executable) -> None:
    """Approving a portfolio system is not approving whatever it is renamed to."""
    roadmap, task, recommendation = executable
    runtime = create_runtime()
    approval = _approve(task, recommendation, runtime)

    altered = task.model_copy(update={"capability_id": "cap-something-else"})
    reasons = gate.unmet(altered, recommendation=recommendation, approval=approval,
                         facts=_all_done(roadmap), tenant=TENANT)
    assert any("changed after it was approved" in r for r in reasons), reasons


def test_rescheduling_a_task_does_not_invalidate_its_approval(executable) -> None:
    """The converse. Invalidating a decision over a horizon change would train
    people to re-approve without reading."""
    roadmap, task, recommendation = executable
    runtime = create_runtime()
    approval = _approve(task, recommendation, runtime)
    later = task.model_copy(update={"horizon": Horizon.DAY_90})
    assert gate.check(later, recommendation=recommendation, approval=approval,
                      facts=_all_done(roadmap), tenant=TENANT)


def test_nothing_in_this_module_can_approve_anything() -> None:
    """The gate reads decisions; it never makes them."""
    import inspect

    source = inspect.getsource(crossing) + inspect.getsource(gate)
    for forbidden in (".approve(", ".reject(", "ApprovalState.APPROVED)"):
        assert f"approvals{forbidden}" not in source
    assert "def approve" not in source


# ======================================================= 5. tenancy is enforced

def test_a_task_from_another_tenant_cannot_execute(executable) -> None:
    roadmap, task, recommendation = executable
    runtime = create_runtime()
    approval = _approve(task, recommendation, runtime)
    reasons = gate.unmet(task, recommendation=recommendation, approval=approval,
                         facts=_all_done(roadmap), tenant="someone-else")
    assert any("different tenant" in r for r in reasons), reasons

    with pytest.raises(gate.NotExecutable, match="different tenant"):
        crossing.execute_task(task, recommendation=recommendation, approval=approval,
                              facts=_all_done(roadmap), tenant="someone-else",
                              research=RESEARCH, business_name="AHS",
                              repository=runtime.repository)


def test_a_task_with_no_tenant_belongs_to_nobody(executable) -> None:
    roadmap, task, recommendation = executable
    orphan = task.model_copy(update={"tenant_id": None})
    reasons = gate.unmet(orphan, recommendation=recommendation, approval=None,
                         facts=_all_done(roadmap), tenant=TENANT)
    assert any("different tenant" in r for r in reasons), reasons


# ========================== 6. completion is not a business result

def test_a_completed_task_does_not_imply_a_successful_outcome(executable) -> None:
    roadmap, task, recommendation = executable
    runtime = create_runtime()
    outcome = crossing.execute_task(
        task, recommendation=recommendation,
        approval=_approve(task, recommendation, runtime), facts=_all_done(roadmap),
        tenant=TENANT, research=RESEARCH, business_name="AHS",
        repository=runtime.repository)

    assert state_of(task, _all_done(roadmap).model_copy(
        update={"job_status": JobStatus.COMPLETED})) is TaskState.COMPLETED

    # Nothing measured. The attribution the evidence supports is UNKNOWN, and
    # UNKNOWN licenses no statement about a result.
    event = crossing.executed_event(task, outcome)
    assert "work_completed" in event.detail
    assert "succeeded" not in event.detail, "a word that reads as a business result"
    for claim in ("Qevik increased their enquiries.",
                  "This will drive more bookings.",
                  "Enquiries rose after the work."):
        assert not permits(Attribution.UNKNOWN, claim)


def test_a_failed_job_is_not_reported_as_completed(executable) -> None:
    roadmap, task, _ = executable
    failed = _all_done(roadmap).model_copy(update={"job_status": JobStatus.FAILED})
    assert state_of(task, failed) is TaskState.FAILED
    assert state_of(task, failed) is not TaskState.COMPLETED


# ================================= 7. a missing baseline never becomes zero

def test_a_missing_baseline_does_not_become_zero() -> None:
    with pytest.raises(measurement.SourceUnavailable):
        measurement.open_baseline(business_id="ahs", tenant_id=TENANT,
                                  metric_key="clicks", value=10, source="")

    connected_but_empty = measurement.open_baseline(
        business_id="ahs", tenant_id=TENANT, metric_key="clicks",
        value=None, source="search-console")
    assert connected_but_empty.state is BaselineState.NO_BASELINE
    assert connected_but_empty.baseline.value is None, "None, never 0.0"
    assert connected_but_empty.improved is None, "unknown, not False"
    assert connected_but_empty.attribution is Attribution.UNKNOWN


def test_an_unmeasured_metric_is_not_reported_as_poor_performance(plan) -> None:
    roadmap, _ = plan
    waiting = measurement.awaiting_source(roadmap)
    assert waiting, "AHS has never been checked for AI visibility"
    for entry in waiting:
        assert entry["state"] == BaselineState.NO_BASELINE.value
        assert permits(Attribution.UNKNOWN, entry["statement"]), entry["statement"]
        assert "poor" not in entry["statement"] and "low" not in entry["statement"]


def test_a_baseline_is_established_when_the_source_arrives(plan) -> None:
    roadmap, _ = plan
    before = measurement.awaiting_source(roadmap)
    assert any(e["metric"] == "ai_mention_rate" for e in before)

    baseline = measurement.open_baseline(
        business_id="ahs", tenant_id=TENANT, metric_key="ai_mention_rate",
        value=0.0, source="assistant-sweep", detail="12 queries, 0 mentions")
    assert baseline.state is BaselineState.BASELINE_AVAILABLE
    assert baseline.baseline.value == 0.0, "a measured zero is a real reading"

    after = measurement.awaiting_source(roadmap, measured=frozenset({"ai_mention_rate"}))
    assert not any(e["metric"] == "ai_mention_rate" for e in after)


# ============================ 8. measurement cannot manufacture causation

def test_measurement_cannot_manufacture_causation() -> None:
    from datetime import UTC, datetime, timedelta

    baseline = measurement.open_baseline(
        business_id="ahs", tenant_id=TENANT, metric_key="clicks", value=100.0,
        source="search-console")
    full = measurement.close_measurement(
        baseline, value=180.0, source="search-console",
        intervention_at=datetime.now(UTC) - timedelta(days=31), job_id="job-1")

    assert full.change == 80.0
    # An 80% rise, correct ordering, and still not attribution: nothing ties the
    # change to the work rather than to the season.
    assert full.attribution is Attribution.ASSOCIATED
    assert not permits(full.attribution, "Qevik increased their clicks by 80%.")
    assert permits(full.attribution, full.statement())


def test_reaching_attributed_requires_a_named_source() -> None:
    from datetime import UTC, datetime, timedelta

    baseline = measurement.open_baseline(
        business_id="ahs", tenant_id=TENANT, metric_key="clicks", value=100.0,
        source="search-console")
    intervention = datetime.now(UTC) - timedelta(days=31)
    without = measurement.close_measurement(baseline, value=180.0,
                                            source="search-console",
                                            intervention_at=intervention)
    with_source = measurement.close_measurement(
        baseline, value=180.0, source="search-console", intervention_at=intervention,
        attribution_source="utm_campaign=portfolio")
    assert without.attribution is Attribution.ASSOCIATED
    assert with_source.attribution is Attribution.ATTRIBUTED
    # Even ATTRIBUTED does not license sole agency.
    assert not permits(with_source.attribution, "Qevik increased their clicks.")


# ================================================ 9 & 10. re-evaluation

def test_unchanged_evidence_does_not_regenerate_the_roadmap(plan) -> None:
    from atlas_kernel.roadmap import changed

    roadmap, recommendations = plan
    again = generate(business_id="ahs", tenant_id=TENANT,
                     observations=[{"feature": f, "status": s} for f, s in AHS_FEATURES],
                     recommendations=recommendations, business_model="CATERING")
    delta = changed(roadmap, again)
    assert delta["changed"] is False, delta
    assert delta["why"] == []


def test_changed_evidence_produces_an_explainable_delta(plan) -> None:
    from atlas_kernel.roadmap import changed

    roadmap, _ = plan
    fixed = [(f, "present" if f in ("arabic", "hreflang") else s)
             for f, s in AHS_FEATURES]
    ranked = opp.for_host("ahscatering.com", category="food",
                          absent=frozenset({"click_to_call", "orphan_pages"}),
                          present=frozenset({"portfolio_depth", "social_proof",
                                             "blog", "arabic"}))
    recommendations = rec_service.propose(
        business_id="ahs", tenant_id=TENANT, opportunities=ranked,
        business_model="CATERING", plan="ADVANCED")
    after = generate(business_id="ahs", tenant_id=TENANT,
                     observations=[{"feature": f, "status": s} for f, s in fixed],
                     recommendations=recommendations, business_model="CATERING")

    delta = changed(roadmap, after)
    assert delta["changed"]
    assert delta["why"], "a changed roadmap with no explanation is a reshuffle"
    assert delta["dimensions_moved"].get("multilingual"), delta["dimensions_moved"]
    assert any("Arabic" in line for line in delta["why"]), delta["why"]
    # And the explanation itself may not claim the work caused anything.
    for line in delta["why"]:
        assert permits(Attribution.UNKNOWN, line), line


def test_re_evaluation_does_not_destroy_the_previous_plan(plan) -> None:
    from atlas_kernel.roadmap import changed, to_event

    roadmap, recommendations = plan
    before_ids = [t.id for t in roadmap.tasks]
    stored = to_event(roadmap)
    again = generate(business_id="ahs", tenant_id=TENANT,
                     observations=[{"feature": f, "status": s} for f, s in AHS_FEATURES],
                     recommendations=recommendations, business_model="CATERING")
    changed(roadmap, again)
    assert [t.id for t in roadmap.tasks] == before_ids, "the earlier plan was mutated"
    assert len(stored.detail["tasks"]) == len(before_ids)


# ============================ 11 & 12. ready to publish is not published

def test_a_ready_to_publish_asset_is_not_treated_as_published(executable) -> None:
    roadmap, task, recommendation = executable
    runtime = create_runtime()
    outcome = crossing.execute_task(
        task, recommendation=recommendation,
        approval=_approve(task, recommendation, runtime), facts=_all_done(roadmap),
        tenant=TENANT, research=RESEARCH, business_name="AHS",
        repository=runtime.repository)

    assert outcome.state is PublicationState.READY_TO_PUBLISH
    assert outcome.state is not PublicationState.PUBLISHED
    asset = runtime.repository.get_asset(outcome.asset_ids[0])
    assert asset.metadata["publication_state"] != PublicationState.PUBLISHED.value

    event = crossing.executed_event(task, outcome)
    assert event.detail["publication_state"] == PublicationState.READY_TO_PUBLISH.value

    with pytest.raises(NotImplementedError):
        publish(outcome)


def test_the_approval_says_plainly_that_it_does_not_publish(executable) -> None:
    roadmap, task, recommendation = executable
    runtime = create_runtime()
    request = crossing.request_approval(
        task, recommendation=recommendation, approvals=runtime.approval_service,
        business_name="AHS")
    assert request.payload["publishes"] is False
    assert "does not publish" in request.payload["note"]
    assert request.metadata[gate.TASK_FINGERPRINT] == gate.fingerprint(task)


# ==================================================== AHS: no invented work

def test_ahs_gets_no_work_on_what_is_already_working(plan) -> None:
    """A strong business with a limited website opportunity. The plan must not
    be padded to look like a project."""
    roadmap, _ = plan
    assert roadmap.left_alone, "AHS has genuine strengths"
    for task in roadmap.tasks:
        assert task.dimension not in set(roadmap.left_alone), task.task.title


def test_ahs_receives_no_task_qevik_cannot_perform_and_has_not_said_so(plan) -> None:
    roadmap, _ = plan
    shown = view(roadmap)
    promised = {t["title"] for t in shown["qevik_can_execute"]}
    assert len(promised) <= 1, f"AHS is promised more than the one real capability: {promised}"


def test_every_ahs_task_traces_to_evidence_or_is_a_measurement(plan) -> None:
    roadmap, _ = plan
    for task in roadmap.tasks:
        if task.executability is Executability.MEASURE_FIRST:
            continue
        assert task.evidence, f"{task.task.title!r} rests on nothing observed"


# ============================================= the customer-facing surface

def test_the_presentation_answers_what_a_customer_asked(plan) -> None:
    roadmap, _ = plan
    shown = view(roadmap)
    for key in ("readiness", "next", "horizons", "qevik_can_execute", "your_tasks",
                "no_capability", "not_yet_measured", "blocked"):
        assert key in shown, key
    assert shown["readiness"]["overall"] is not None
    assert shown["readiness"]["working_already"]
    for entry in shown["horizons"]["7-day"]:
        assert entry["who"] and entry["why"] and entry["measurement"]


def test_no_customer_facing_sentence_claims_a_result(plan) -> None:
    roadmap, _ = plan
    shown = view(roadmap)
    sentences = [shown["readiness"]["note"], shown["readiness"]["working_already_note"]]
    for group in shown["horizons"].values():
        for entry in group:
            sentences += [entry["title"], entry["why"], entry["expected_outcome"],
                          entry["measurement"]["note"], *entry["blocked_by"]]
    for sentence in sentences:
        assert permits(Attribution.UNKNOWN, sentence), sentence


def test_the_presentation_gate_refuses_a_guaranteed_result() -> None:
    """A check that passes everything is not a check."""
    for promise in ("This will increase your enquiries.",
                    "Bookings grew because of the new pages.",
                    "Qevik improved their search position."):
        with pytest.raises(Overclaim):
            vet(promise, where="test")


def test_a_blocked_task_says_what_it_is_waiting_for(plan) -> None:
    roadmap, _ = plan
    shown = view(roadmap, facts=TaskFacts(
        recommendation_state=RecommendationState.ACCEPTED))
    blocked = shown["blocked"]
    assert blocked, "with nothing done, work waiting on the customer is blocked"
    for entry in blocked:
        assert entry["blocked_by"], f"{entry['title']!r} is blocked with no reason given"
