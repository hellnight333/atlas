"""The end-to-end slice, and the ten ways it must refuse.

Research → Evidence → Opportunity → Recommendation → Approval → Job → Execution
→ Asset → QA → READY_TO_PUBLISH, on the AHS case that motivated it.

Most of this file is negative. The happy path is one test; the value is in the
refusals, because every one of them is a way a system like this quietly does
work nobody authorised or reports success for something that did not happen.
"""

from __future__ import annotations

import pytest

from atlas_kernel.execution import service
from atlas_kernel.execution.capabilities import EXECUTORS, build_portfolio_index
from atlas_kernel.execution.models import (
    NotApproved,
    PublicationState,
    QAResult,
    QAVerdict,
    UnsupportedCapability,
)
from atlas_kernel.execution.qa import Context, run_gates
from atlas_kernel.opportunity.tenancy import ALL_TENANTS
from atlas_kernel.outreach import opportunity as opp
from atlas_kernel.recommendation import service as rec_service
from atlas_kernel.recommendation.models import (
    RecommendationState,
    TaskKind,
    Unsupported,
)

#: The AHS research record, in the shape the research engine actually emits.
RESEARCH = {
    "state": "READY",
    "facts": {
        "cms": {"pages": 60, "posts": 4, "media_total": 501,
                "image_page_list": [
                    {"slug": f"case-{i}", "title": f"Event {i}",
                     "url": f"https://ahscatering.com/case-{i}/", "images": 5}
                    for i in range(32)]},
        "seo": {"orphan_count": 34},
        "position": {"grade": "STRONG"},
        "technical": {"speed_class": "FAST"},
    },
}
STRENGTHS = ("20+ years trading", "site loads in 484ms", "32 published events")


def _recommendation(tenant: str | None = "t-qevik"):
    ranked = opp.for_host("ahscatering.com", category="food",
                          absent=frozenset({"orphan_pages"}),
                          present=frozenset({"portfolio_depth", "social_proof"}))
    return rec_service.propose(business_id="ahs", tenant_id=tenant,
                               opportunities=ranked, business_model="CATERING",
                               plan="ADVANCED", strengths=STRENGTHS)[0]


def _ready(rec):
    """Accepted, and with the customer's part done."""
    return rec.model_copy(update={
        "state": RecommendationState.ACCEPTED,
        "tasks": tuple(t for t in rec.tasks if t.kind is TaskKind.QEVIK_TASK)})


@pytest.fixture
def outcome():
    return service.execute(_ready(_recommendation()), approved=True,
                           research=RESEARCH, business_name="AHS Catering & Events")


# --- the slice itself ------------------------------------------------------

def test_the_whole_slice_reaches_ready_to_publish(outcome) -> None:
    assert outcome.succeeded and not outcome.error
    assert outcome.state is PublicationState.READY_TO_PUBLISH
    assert outcome.asset_ids
    assert outcome.publishable is True
    assert not outcome.failed_gates


def test_every_gate_ran_and_passed(outcome) -> None:
    from atlas_kernel.execution.qa import GATES
    assert {r.gate for r in outcome.qa} == {name for name, _ in GATES}
    assert all(r.verdict is QAVerdict.PASS for r in outcome.qa)


def test_the_artefact_is_built_only_from_what_the_business_publishes() -> None:
    artefact, provenance = build_portfolio_index(
        business_name="AHS", research=RESEARCH, strengths=STRENGTHS)
    assert provenance["cases"] == 32
    assert provenance["photographs"] == 160
    assert provenance["invented_fields"] == 0
    assert "not published" in artefact, "unpublished fields must say so"


def test_provenance_reaches_from_the_asset_back_to_the_evidence(outcome) -> None:
    """The question this whole architecture exists to answer."""
    assert outcome.recommendation_id and outcome.job_id and outcome.run_id
    assert outcome.capability_id
    assert outcome.baseline["research_facts"]["media_total"] == 501


def test_measurement_hooks_are_captured_without_being_interpreted(outcome) -> None:
    """P1.4 reads these. Nothing here turns an observation into a cause."""
    assert outcome.measures
    assert outcome.baseline["orphans"] == 34
    assert "captured_at" in outcome.baseline


# --- 1. recommendation without evidence -----------------------------------

def test_a_recommendation_without_evidence_cannot_be_built() -> None:
    from atlas_kernel.recommendation.models import Recommendation
    with pytest.raises(Unsupported):
        Recommendation(business_id="ahs", opportunity_key="proof", evidence=(),
                       title="Portfolio", rationale="because")


# --- 2. cross-tenant recommendation access --------------------------------

def test_one_tenant_cannot_see_anothers_execution(outcome) -> None:
    assert service.visible_to(outcome, "t-qevik") is True
    assert service.visible_to(outcome, "t-other") is False


def test_an_untenanted_outcome_is_visible_to_nobody() -> None:
    orphan = service.execute(_ready(_recommendation(tenant=None)), approved=True,
                             research=RESEARCH, business_name="X")
    assert service.visible_to(orphan, "t-qevik") is False
    assert service.visible_to(orphan, ALL_TENANTS) is True


# --- 3. execution without approval ----------------------------------------

def test_execution_without_approval_is_refused() -> None:
    with pytest.raises(NotApproved, match="not been approved"):
        service.execute(_ready(_recommendation()), approved=False,
                        research=RESEARCH, business_name="AHS")


def test_acceptance_is_not_approval() -> None:
    """A customer wanting something is not the same as consenting to it now."""
    proposed = _recommendation()
    assert proposed.state is RecommendationState.PROPOSED
    with pytest.raises(NotApproved):
        service.execute(proposed, approved=True, research=RESEARCH,
                        business_name="AHS")


# --- 4. execution with an outstanding customer task -----------------------

def test_an_outstanding_customer_task_blocks_execution() -> None:
    accepted = _recommendation().model_copy(
        update={"state": RecommendationState.ACCEPTED})
    assert accepted.waiting_on_customer
    with pytest.raises(NotApproved, match="waiting on the customer"):
        service.execute(accepted, approved=True, research=RESEARCH,
                        business_name="AHS")


# --- 5. job without valid recommendation provenance -----------------------

def test_a_job_whose_recommendation_cites_nothing_fails_qa() -> None:
    class Hollow:
        evidence = ()

    results = run_gates(Context(outcome_error="", assets=[], recommendation=Hollow(),
                                offer=None, artefact="x"))
    evidence = next(r for r in results if r.gate == "evidence")
    assert evidence.verdict is QAVerdict.FAIL


def test_a_job_with_no_recommendation_at_all_fails_qa() -> None:
    results = run_gates(Context(outcome_error="", assets=[], recommendation=None,
                                offer=None, artefact="x"))
    assert next(r for r in results if r.gate == "evidence").verdict is QAVerdict.FAIL


# --- 6. asset without provenance ------------------------------------------

def test_an_asset_without_provenance_fails_qa() -> None:
    class Bare:
        id = "a1"
        uri = "atlas://x"
        job_id = None
        run_id = "r"
        content_hash = None

    results = run_gates(Context(outcome_error="", assets=[Bare()],
                                recommendation=None, offer=None, artefact="x"))
    provenance = next(r for r in results if r.gate == "provenance")
    assert provenance.verdict is QAVerdict.FAIL
    assert "job_id" in provenance.detail


def test_the_real_asset_carries_full_provenance(outcome) -> None:
    assert outcome.asset_ids
    assert outcome.job_id and outcome.run_id


# --- 7. a QA failure never reaches READY_TO_PUBLISH -----------------------

def test_a_failed_gate_rejects_the_artefact() -> None:
    """Research with no pages: the capability refuses, and QA rejects."""
    result = service.execute(_ready(_recommendation()), approved=True,
                             research={}, business_name="AHS")
    assert result.succeeded is False
    assert result.state is PublicationState.REJECTED
    assert result.publishable is False
    assert any(r.gate == "execution" and r.verdict is QAVerdict.FAIL for r in result.qa)


def test_an_unrun_gate_blocks_exactly_like_a_failure() -> None:
    """A check that could not run has established nothing."""
    assert QAResult(gate="g", verdict=QAVerdict.NOT_RUN).blocks is True
    assert QAResult(gate="g", verdict=QAVerdict.FAIL).blocks is True
    assert QAResult(gate="g", verdict=QAVerdict.PASS).blocks is False


def test_generation_succeeding_is_not_enough_on_its_own(outcome) -> None:
    forced = outcome.model_copy(update={
        "qa": (QAResult(gate="honesty", verdict=QAVerdict.FAIL, detail="x"),)})
    assert forced.succeeded is True
    assert forced.publishable is False, "a job must not be publishable because it ran"


# --- 8. READY_TO_PUBLISH is not PUBLISHED ---------------------------------

def test_ready_to_publish_is_a_different_state_from_published(outcome) -> None:
    assert outcome.state is PublicationState.READY_TO_PUBLISH
    assert outcome.state is not PublicationState.PUBLISHED
    assert PublicationState.READY_TO_PUBLISH != PublicationState.PUBLISHED


def test_nothing_in_this_package_can_reach_published() -> None:
    """The state exists so the enum is honest; no path here sets it."""
    from pathlib import Path
    for module in ("service.py", "qa.py", "models.py"):
        source = (Path(service.__file__).parent / module).read_text(encoding="utf-8")
        assert "PublicationState.PUBLISHED" not in source, module


# --- 9. unauthorized publication attempt ----------------------------------

def test_attempting_to_publish_raises(outcome) -> None:
    with pytest.raises(NotImplementedError, match="not part of P1.3"):
        service.publish(outcome)


def test_the_execution_layer_has_no_way_to_reach_the_outside_world() -> None:
    from pathlib import Path
    source = Path(service.__file__).read_text(encoding="utf-8")
    for forbidden in ("httpx", "requests", "smtplib", "boto3", "urllib.request"):
        assert forbidden not in source, f"{forbidden} reached the execution layer"


# --- 10. unsupported capability -------------------------------------------

def test_a_capability_with_no_executor_is_refused() -> None:
    unknown = _ready(_recommendation()).model_copy(
        update={"offer_id": "offer-does-not-exist"})
    with pytest.raises(UnsupportedCapability, match="no executor"):
        service.execute(unknown, approved=True, research=RESEARCH,
                        business_name="AHS")


def test_the_executor_table_is_keyed_on_real_offers() -> None:
    from atlas_kernel.recommendation.offers import BY_ID
    for offer_id in EXECUTORS:
        assert offer_id in BY_ID, f"{offer_id} executes an offer that does not exist"


# --- AHS remains the negative control -------------------------------------

def test_the_artefact_never_calls_a_strong_business_weak(outcome) -> None:
    artefact, _ = build_portfolio_index(business_name="AHS Catering",
                                        research=RESEARCH, strengths=STRENGTHS)
    lowered = artefact.lower()
    for word in ("bad", "poor", "outdated", "broken", "unprofessional", "weak"):
        assert word not in lowered, f"the artefact calls the business {word!r}"
    assert "484ms" in artefact, "its strengths are carried into the output"


def test_the_honesty_gate_rejects_an_unsupported_claim() -> None:
    class R:
        evidence = ("seen",)

    results = run_gates(Context(
        outcome_error="", assets=[], recommendation=R(), offer=None,
        artefact="<p>Your website is bad and we increased traffic 40%.</p>"))
    honesty = next(r for r in results if r.gate == "honesty")
    assert honesty.verdict is QAVerdict.FAIL
    assert "unsupported claim" in honesty.detail


def test_the_ahs_recommendation_is_still_evidence_backed() -> None:
    rec = _recommendation()
    assert rec.evidence
    assert rec.strengths == STRENGTHS
    assert "170 photographs" in " ".join(rec.evidence)
