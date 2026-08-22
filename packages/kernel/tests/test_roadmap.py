"""The roadmap, tested on the plans it must never produce.

A 0→100 plan is the easiest thing in this system to fake. A template with the
scores dropped in reads exactly like a derived plan until you put two businesses
side by side, and by then it has been sent. So most of what follows checks for
absence: the task that should not be there, the claim that should not be made,
the customer obligation that should not have quietly become ours.

The two fixtures are real shapes, not convenient ones. `ahs` is the audited
caterer — world-class proof, a fast site, no Arabic and no tappable phone
number. `clinic` is its mirror: already bilingual and reachable, with no proof
at all and a site that fails on HTTPS and speed. If one generator produces
similar plans for those two, it is not reading the evidence.
"""

from __future__ import annotations

from typing import NamedTuple

import pytest
from pydantic import ValidationError

from atlas_kernel.measurement import attribution
from atlas_kernel.opportunity.tenancy import TenantRequired
from atlas_kernel.outreach import opportunity as opp
from atlas_kernel.recommendation import service as rec_service
from atlas_kernel.recommendation.models import QevikTask, TaskKind
from atlas_kernel.roadmap import (
    Confidence,
    Dimension,
    Executability,
    Horizon,
    Roadmap,
    RoadmapTask,
    assess,
    changed,
    generate,
    read,
    to_event,
)
from atlas_kernel.roadmap.readiness import STRONG

TENANT = "tenant-qevik"


class Case(NamedTuple):
    """A plan together with what it was made from.

    Recommendation ids carry a timestamp, so proposing a second time for the
    same business produces the same content under different ids. Tests that
    need to compare a plan against its inputs have to hold the inputs that
    actually produced it.
    """

    recommendations: tuple
    roadmap: Roadmap


def _build(spec: dict, **kwargs) -> Case:
    observations = [{"feature": f, "status": s} for f, s in spec["features"]]
    ranked = opp.for_host(spec["host"], category=spec["category"],
                          absent=frozenset(spec["absent"]),
                          present=frozenset(spec["present"]))
    recommendations = rec_service.propose(
        business_id=spec["business_id"], tenant_id=TENANT, opportunities=ranked,
        business_model=spec["model"], plan="ADVANCED")
    return Case(recommendations, generate(
        business_id=spec["business_id"], tenant_id=TENANT,
        observations=observations, recommendations=recommendations,
        business_model=spec["model"], **kwargs))


#: The audited caterer: strong proof and speed, no Arabic, no tap-to-call.
AHS = dict(
    business_id="ahs", host="ahscatering.com", category="food", model="CATERING",
    features=[("https", "present"), ("page_speed", "present"),
              ("broken_links", "present"), ("viewport_meta", "present"),
              ("click_to_call", "not_found"), ("whatsapp", "not_found"),
              ("contact_form", "present"), ("arabic", "not_found"),
              ("hreflang", "not_found"), ("social_proof", "present"),
              ("portfolio_depth", "present"), ("market_position", "present"),
              ("orphan_pages", "not_found"), ("page_title", "present"),
              ("blog", "present"), ("blog_cadence", "not_found")],
    absent={"arabic", "click_to_call", "orphan_pages", "blog_cadence"},
    present={"portfolio_depth", "social_proof", "blog"})

#: Its mirror: bilingual and reachable, no proof, a broken site.
CLINIC = dict(
    business_id="clinic", host="example-clinic.ae", category="dental", model="CLINIC",
    features=[("https", "not_found"), ("page_speed", "not_found"),
              ("broken_links", "not_found"), ("viewport_meta", "not_found"),
              ("click_to_call", "present"), ("whatsapp", "present"),
              ("contact_form", "present"), ("arabic", "present"),
              ("hreflang", "present"), ("social_proof", "not_found"),
              ("portfolio_depth", "not_found"), ("market_position", "not_found"),
              ("page_title", "present"), ("blog", "not_found")],
    absent={"social_proof", "portfolio_depth", "https", "page_speed"},
    present={"arabic", "whatsapp", "click_to_call"})


@pytest.fixture(scope="module")
def ahs_case() -> Case:
    return _build(AHS)


@pytest.fixture(scope="module")
def ahs(ahs_case) -> Roadmap:
    return ahs_case.roadmap


@pytest.fixture(scope="module")
def clinic() -> Roadmap:
    return _build(CLINIC).roadmap


# --- 1. two businesses, two plans ------------------------------------------

def test_two_different_businesses_do_not_get_the_same_roadmap(ahs, clinic) -> None:
    """The failure this whole phase is judged against."""
    assert ahs.fingerprint() != clinic.fingerprint()
    assert ahs.readiness_overall != clinic.readiness_overall

    shared = {t.task.title for t in ahs.tasks} & {t.task.title for t in clinic.tasks}
    # One measurement task is legitimately shared: neither has ever been checked
    # for AI visibility, and that is a fact about both. Anything beyond it would
    # mean the generator is filling space rather than reading evidence.
    assert shared == {"Measure AI search visibility"}, shared


def test_each_plan_addresses_what_that_business_is_actually_missing(ahs, clinic) -> None:
    ahs_dimensions = {t.dimension for t in ahs.tasks}
    clinic_dimensions = {t.dimension for t in clinic.tasks}

    # AHS: no Arabic, no tappable number. Its proof is the best thing it has.
    assert Dimension.MULTILINGUAL.value in ahs_dimensions
    assert Dimension.PROOF.value not in ahs_dimensions

    # The clinic is the inverse on every one of those.
    assert Dimension.PROOF.value in clinic_dimensions
    assert Dimension.MULTILINGUAL.value not in clinic_dimensions
    assert Dimension.REACHABILITY.value not in clinic_dimensions


def test_the_same_business_under_a_different_model_is_weighted_differently() -> None:
    """Weighting is per business model, so the ranking must move with it."""
    observations = [{"feature": f, "status": s} for f, s in AHS["features"]]
    catering = assess(business_id="x", observations=observations,
                      business_model="CATERING")
    ecommerce = assess(business_id="x", observations=observations,
                       business_model="ECOMMERCE")
    assert catering.overall != ecommerce.overall


# --- 2. a strong dimension produces nothing --------------------------------

def test_a_strong_dimension_never_produces_a_task(ahs) -> None:
    """AHS's proof and speed are its strengths. A plan that proposes work on
    them is selling, not advising."""
    strong = {d.dimension.value for d in assess(
        business_id="ahs",
        observations=[{"feature": f, "status": s} for f, s in AHS["features"]],
        business_model="CATERING").dimensions if d.strong}
    assert strong, "the fixture must actually have a strength for this to test anything"
    for task in ahs.tasks:
        assert task.dimension not in strong, \
            f"{task.task.title!r} proposes work on {task.dimension}, which is already strong"
    assert set(ahs.left_alone) == strong


def test_a_strong_dimension_does_not_drag_in_its_customer_prerequisites(ahs) -> None:
    """The first version asked AHS to approve portfolio work it never scheduled.

    Filtering at scheduling time is not enough: the customer obligations attached
    to a dropped recommendation have to go with it, or the plan opens by asking
    for material nothing will consume.
    """
    for task in ahs.customer_tasks:
        assert task.dimension not in set(ahs.left_alone), task.task.title


def test_a_business_strong_everywhere_gets_no_invented_work() -> None:
    everything = [{"feature": f, "status": "present"} for f in (
        "click_to_call", "whatsapp", "contact_form", "opening_hours",
        "page_title", "meta_description", "canonical", "structured_data",
        "sitemap", "h1", "open_graph", "indexability", "image_alt_text",
        "social_proof", "portfolio_depth", "market_position", "https",
        "page_speed", "broken_links", "viewport_meta", "arabic", "hreflang",
        "blog", "blog_quality", "blog_freshness", "blog_cadence")]
    plan = generate(business_id="perfect", tenant_id=TENANT,
                    observations=everything, business_model="CATERING")
    assert plan.readiness_overall is not None and plan.readiness_overall >= STRONG
    fixes = [t for t in plan.tasks
             if t.executability is not Executability.MEASURE_FIRST]
    assert fixes == [], [t.task.title for t in fixes]


# --- 3. UNKNOWN is not zero ------------------------------------------------

def test_an_unmeasured_dimension_is_not_scored_as_a_failure(ahs) -> None:
    """Nobody has queried AI assistants about AHS. That is our blind spot, not
    their weakness, and the two must not be recorded the same way."""
    readiness = assess(business_id="ahs",
                       observations=[{"feature": f, "status": s} for f, s in AHS["features"]],
                       business_model="CATERING")
    ai = readiness.by_dimension[Dimension.AI_VISIBILITY]
    assert ai.score is None, "an unmeasured dimension must not carry a number"
    assert ai.confidence is Confidence.UNKNOWN
    assert ai.unmeasured and not ai.weak, "unmeasured must not read as weak"

    task = next(t for t in ahs.tasks if t.dimension == Dimension.AI_VISIBILITY.value)
    assert task.executability is Executability.MEASURE_FIRST
    assert task.confidence == Confidence.UNKNOWN.value
    assert "baseline" in task.expected_outcome


def test_unverified_evidence_lowers_confidence_and_not_the_score() -> None:
    confirmed = assess(business_id="a", business_model="CATERING", observations=[
        {"feature": "click_to_call", "status": "present"},
        {"feature": "whatsapp", "status": "present"},
        {"feature": "contact_form", "status": "present"}])
    partly = assess(business_id="b", business_model="CATERING", observations=[
        {"feature": "click_to_call", "status": "present"},
        {"feature": "whatsapp", "status": "unverified"},
        {"feature": "contact_form", "status": "unverified"}])
    a = confirmed.by_dimension[Dimension.REACHABILITY]
    b = partly.by_dimension[Dimension.REACHABILITY]
    assert a.score == b.score, "unverified inputs must not move the score"
    assert b.confidence is not a.confidence, "they must move the confidence"


def test_a_dimension_already_measured_elsewhere_is_not_asked_for_again(ahs) -> None:
    """If Search Console is already connected, the plan must not open by asking
    for it. Re-requesting what a customer already gave is how a plan reads as
    generated."""
    with_data = _build(AHS, measured_metrics=frozenset({"ai_mention_rate"})).roadmap
    assert any(t.metric_key == "ai_mention_rate" for t in ahs.tasks)
    assert not any(t.metric_key == "ai_mention_rate" for t in with_data.tasks)


# --- 4. a customer task stays a customer task ------------------------------

def test_a_customer_task_is_never_relabelled_as_qevik_work(ahs, clinic) -> None:
    """A plan that lists the customer's obligations as ours stalls in week two
    and nobody can see why."""
    for plan in (ahs, clinic):
        for task in plan.tasks:
            if task.executability is Executability.CUSTOMER_MUST_ACT:
                assert task.kind is TaskKind.CUSTOMER_TASK, task.task.title
            if task.executability is Executability.QEVIK_CAN_EXECUTE:
                assert task.kind is TaskKind.QEVIK_TASK, task.task.title


def test_every_customer_task_survives_from_its_recommendation(ahs_case) -> None:
    proposed = {t.title for r in ahs_case.recommendations for t in r.customer_tasks}
    scheduled = {t.task.title for t in ahs_case.roadmap.customer_tasks}
    assert scheduled <= proposed, scheduled - proposed
    assert scheduled, "the fixture must have customer obligations to test this"


def test_work_waiting_on_the_customer_is_reported_as_waiting(ahs) -> None:
    waiting = {t.task.title for t in ahs.waiting_on_customer}
    assert waiting, "AHS cannot be translated without its own pages"
    assert all(t.is_customer for t in ahs.waiting_on_customer)


# --- 5. an unavailable capability is not presented as executable ------------

def test_nothing_claims_qevik_can_execute_without_naming_a_capability(ahs, clinic) -> None:
    for plan in (ahs, clinic):
        for task in plan.tasks:
            if task.executability is Executability.QEVIK_CAN_EXECUTE:
                assert task.capability_id, task.task.title
            else:
                assert not task.capability_id, \
                    f"{task.task.title!r} names a capability it does not claim to use"


def test_a_weakness_with_no_offer_is_shown_and_not_promised(clinic) -> None:
    """The clinic has no proof at all and no offer matched it. Dropping the
    finding would make the plan capability-shaped — only the weaknesses Qevik
    sells against would ever appear."""
    uncovered = [t for t in clinic.tasks
                 if t.executability is Executability.NO_CAPABILITY]
    assert {t.dimension for t in uncovered} >= {Dimension.PROOF.value,
                                                Dimension.TECHNICAL_HEALTH.value}
    for task in uncovered:
        assert not task.capability_id
        assert task.evidence, "a finding must still rest on something observed"


def test_the_capability_claim_cannot_be_faked() -> None:
    with pytest.raises(ValidationError, match="names no capability"):
        RoadmapTask(id="t", task=QevikTask("Anything"), horizon=Horizon.DAY_30,
                    executability=Executability.QEVIK_CAN_EXECUTE,
                    why="because", evidence=("observed",))


def test_a_task_with_no_evidence_must_be_a_measurement_task() -> None:
    with pytest.raises(ValidationError, match="no evidence"):
        RoadmapTask(id="t", task=QevikTask("Anything"), horizon=Horizon.DAY_30,
                    executability=Executability.NO_CAPABILITY, why="because")
    # The negative control: the same task, as measurement, is legitimate.
    RoadmapTask(id="t", task=QevikTask("Measure it"), horizon=Horizon.DAY_7,
                executability=Executability.MEASURE_FIRST, why="never measured")


# --- 6. dependencies are respected -----------------------------------------

def test_work_never_precedes_what_it_depends_on(ahs, clinic) -> None:
    order = {h: i for i, h in enumerate(Horizon)}
    for plan in (ahs, clinic):
        position = {t.id: order[t.horizon] for t in plan.tasks}
        for task in plan.tasks:
            for dependency in task.depends_on:
                assert dependency in position, f"{task.id} depends on unknown {dependency}"
                assert position[dependency] <= position[task.id], \
                    f"{task.task.title!r} is scheduled before {dependency}"


def test_blocked_work_is_not_ready_until_its_prerequisite_is_done(ahs) -> None:
    blocked = [t for t in ahs.tasks if t.depends_on]
    assert blocked, "the fixture must have a dependency for this to test anything"
    ready = {t.id for t in ahs.ready_now()}
    assert not any(t.id in ready for t in blocked)

    first = blocked[0]
    now_ready = {t.id for t in ahs.ready_now(frozenset(first.depends_on))}
    assert first.id in now_ready


def test_work_depends_only_on_its_own_prerequisites(ahs_case) -> None:
    """Depending on every outstanding customer task stalls each piece of work
    behind all of them, which is a plan that finishes in one lump or not at all.

    Identity here is the task's title, not its recommendation: an obligation two
    recommendations share — approving the result — is listed once and depended
    on twice, which is correct and would look like a stray dependency if the
    recommendation id were compared instead.
    """
    ahs = ahs_case.roadmap
    needed = {r.id: {t.title for t in r.customer_tasks if t.blocks}
              for r in ahs_case.recommendations}
    by_id = {t.id: t for t in ahs.tasks}
    for task in ahs.qevik_tasks:
        for dependency in task.depends_on:
            assert by_id[dependency].task.title in needed[task.recommendation_id], \
                f"{task.task.title!r} waits on {by_id[dependency].task.title!r}, " \
                "which its own recommendation never asked for"

    # And the converse: not everything waits on everything.
    blocking = {t.id for t in ahs.customer_tasks if t.task.blocks}
    assert any(set(t.depends_on) < blocking for t in ahs.qevik_tasks if t.depends_on), \
        "every task waits on every obligation, which is one lump, not a plan"


def test_the_first_week_is_measurement_and_customer_obligations(ahs) -> None:
    """A plan whose opening week contains both "send us your articles" and "the
    articles are published" is not a plan."""
    for task in ahs.at(Horizon.DAY_7):
        assert task.executability in (Executability.MEASURE_FIRST,
                                      Executability.CUSTOMER_MUST_ACT), task.task.title


# --- 7. finishing a task is not the same as succeeding ---------------------

def test_completing_every_task_asserts_nothing_about_the_business(ahs) -> None:
    """The plan is a list of work, not a promise. With every task done and
    nothing measured, the honest attribution is still UNKNOWN."""
    done = frozenset(t.id for t in ahs.tasks)
    assert len(ahs.ready_now(done)) == len(ahs.tasks), "all work is unblocked once done"

    level = attribution.Attribution.UNKNOWN
    assert not attribution.permits(level, "Qevik increased their enquiries.")
    assert not attribution.permits(level, "Enquiries rose after the work.")
    assert attribution.permits(level, "The work was completed.")


def test_expected_outcome_is_stated_as_expectation_not_result(ahs, clinic) -> None:
    for plan in (ahs, clinic):
        for task in plan.tasks:
            claim = attribution.claim_of(task.expected_outcome)
            assert claim in (attribution.Claim.NOTHING, attribution.Claim.CHANGE), \
                f"{task.task.title!r} states its outcome as fact: {task.expected_outcome!r}"


# --- 8. priorities do not claim causation ---------------------------------

def test_no_rationale_in_a_plan_claims_causation(ahs, clinic) -> None:
    """Every sentence a customer reads in a roadmap goes through the same gate
    the measurement layer uses. A plan is written before anything is measured,
    so nothing in it can license an attribution claim."""
    unmeasured = attribution.Attribution.UNKNOWN
    for plan in (ahs, clinic):
        for task in plan.tasks:
            for sentence in (task.why, task.task.title, task.expected_outcome):
                assert attribution.permits(unmeasured, sentence), \
                    attribution.refuse(unmeasured, sentence)


def test_the_causation_gate_can_actually_fail() -> None:
    """A check that passes everything is not a check."""
    unmeasured = attribution.Attribution.UNKNOWN
    for sentence in ("Qevik increased their enquiries by 40%.",
                     "This will drive more leads.",
                     "Bookings grew because of the new pages."):
        assert not attribution.permits(unmeasured, sentence), sentence


def test_a_high_score_does_not_manufacture_a_priority(ahs) -> None:
    """Priority comes from how weak a dimension is, never from how good the
    overall number looks."""
    ordered = [t for t in ahs.qevik_tasks
               if t.executability is Executability.QEVIK_CAN_EXECUTE]
    readiness = assess(business_id="ahs",
                       observations=[{"feature": f, "status": s} for f, s in AHS["features"]],
                       business_model="CATERING")
    scores = {d.dimension.value: d.score for d in readiness.dimensions}
    ranked = [scores.get(t.dimension) for t in ordered if scores.get(t.dimension) is not None]
    assert ranked == sorted(ranked), f"work is not ordered worst-first: {ranked}"


# --- re-evaluation ---------------------------------------------------------

def test_new_evidence_changes_the_plan(ahs) -> None:
    """The point of re-evaluation: research arrives, priorities move."""
    fixed = dict(AHS)
    fixed["features"] = [(f, "present" if f in ("arabic", "hreflang") else s)
                         for f, s in AHS["features"]]
    fixed["absent"] = AHS["absent"] - {"arabic"}
    fixed["present"] = AHS["present"] | {"arabic"}

    after = _build(fixed).roadmap
    diff = changed(ahs, after)
    assert diff["changed"]
    assert any("Arabic" in title for title in diff["removed"]), diff
    assert after.readiness_overall > ahs.readiness_overall


def test_re_evaluation_with_nothing_new_changes_nothing(ahs) -> None:
    """A plan that regenerates differently from identical evidence invalidates
    work a customer is part-way through."""
    diff = changed(ahs, _build(AHS).roadmap)
    assert diff["changed"] is False, diff


def test_the_plan_records_what_it_was_derived_from(ahs) -> None:
    assert ahs.derived_from["observations"] == len(AHS["features"])
    assert ahs.derived_from["recommendations"]
    assert set(ahs.derived_from["scheduled"]) <= set(ahs.derived_from["recommendations"])
    assert ahs.derived_from["readiness"]


# --- persistence and tenancy ----------------------------------------------

def test_a_roadmap_is_readable_only_by_its_own_tenant(ahs) -> None:
    events = [to_event(ahs)]
    assert read(events, tenant=TENANT)
    assert read(events, tenant="someone-else") == []


def test_reading_a_roadmap_without_a_tenant_is_refused(ahs) -> None:
    with pytest.raises(TenantRequired):
        read([to_event(ahs)], tenant=None)


def test_the_event_carries_the_whole_plan(ahs) -> None:
    event = to_event(ahs)
    assert event.factory == "roadmap"
    stored = event.detail["tasks"]
    assert len(stored) == len(ahs.tasks)
    assert {t["title"] for t in stored} == {t.task.title for t in ahs.tasks}
    assert event.detail["left_alone"] == list(ahs.left_alone)
