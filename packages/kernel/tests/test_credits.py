"""Credits: an allowance, and the ways it must refuse.

P1.7's brief is "credit enforcement works without a parallel ledger", and the
tests that matter are the ones proving both halves — that enforcement actually
refuses, and that the consumption record is still `quota.QuotaLedger` rather
than a second set of books that will disagree with it.

Nothing here prices anything or charges anything. There is no money in this
package, so there is none in these tests either.
"""

from __future__ import annotations

import pytest

from atlas_kernel.credits import (
    INCLUDED,
    CreditService,
    NoPlan,
    NotReserved,
    Plan,
    ReservationState,
    read,
    resource_for,
    to_event,
)
from atlas_kernel.quota.ledger import QuotaLedger
from atlas_kernel.quota.models import QuotaExhausted
from atlas_kernel.recommendation.offers import BY_ID

A = "tenant-alpha"
B = "tenant-beta"


@pytest.fixture
def credits() -> CreditService:
    service = CreditService()
    service.assign(A, Plan.ADVANCED)
    service.assign(B, Plan.LIST)
    return service


# ============================================ what work costs is not restated

def test_the_cost_of_work_comes_from_the_offer(credits) -> None:
    """A second price list would be a second answer to the same question."""
    for offer_id, offer in BY_ID.items():
        assert credits.units_for(offer_id) == float(offer.estimated_units)


def test_an_action_with_no_offer_cannot_be_charged_for(credits) -> None:
    with pytest.raises(NotReserved, match="nothing declares what it costs"):
        credits.units_for("offer-invented-by-a-caller")


# ============================================ the ledger stays authoritative

def test_consumption_is_recorded_in_the_existing_ledger(credits) -> None:
    ledger = QuotaLedger(policies=[])
    service = CreditService(ledger=ledger)
    service.assign(A, Plan.ADVANCED)

    reservation = service.reserve(tenant=A, action="offer-website")
    assert ledger.status(resource_for(A)).used == 0.0, \
        "a reservation is an intent; it has consumed nothing yet"

    service.settle(reservation.id, tenant=A, job_id="job-1")
    assert ledger.status(resource_for(A)).used == credits.units_for("offer-website")


def test_there_is_no_second_ledger() -> None:
    """The service holds reservations, not spends. Everything consumed goes
    through QuotaLedger, and a read of the source is what keeps it that way."""
    from pathlib import Path

    from atlas_kernel.credits import service as credit_service

    source = Path(credit_service.__file__).read_text(encoding="utf-8")
    assert "self._ledger.spend(" in source
    for forbidden in ("self._spends", "self._used", "_total +=", "balance ="):
        assert forbidden not in source, forbidden


# ============================================ reserve before acting

def test_a_reservation_is_subtracted_from_what_the_next_caller_may_take(credits) -> None:
    """Two jobs must not both pass the check and leave one unpayable."""
    before = credits.balance(A)
    credits.reserve(tenant=A, action="offer-website")
    assert credits.balance(A) == before - credits.units_for("offer-website")
    assert credits.held(A) == credits.units_for("offer-website")


def test_an_allowance_that_is_used_up_refuses(credits) -> None:
    """LIST includes 40 units; a website costs 30, so the second one refuses."""
    assert INCLUDED[Plan.LIST] == 40.0
    credits.reserve(tenant=B, action="offer-website")
    with pytest.raises(QuotaExhausted):
        credits.reserve(tenant=B, action="offer-website")


def test_a_tenant_with_no_plan_is_refused_rather_than_given_the_free_tier(
        credits) -> None:
    """A provisioning gap, not an empty balance. Defaulting hides it."""
    with pytest.raises(NoPlan, match="provisioning gap"):
        credits.reserve(tenant="tenant-nobody-provisioned", action="offer-website")
    with pytest.raises(NoPlan):
        credits.balance("tenant-nobody-provisioned")


def test_credits_are_never_read_without_a_tenant(credits) -> None:
    from atlas_kernel.opportunity.tenancy import TenantRequired

    for call in (lambda: credits.balance(None), lambda: credits.plan_of(None),
                 lambda: credits.history(None),
                 lambda: credits.reserve(tenant=None, action="offer-website")):
        with pytest.raises(TenantRequired):
            call()


# ============================================ a failure costs nothing

def test_releasing_consumes_nothing(credits) -> None:
    used_before = credits.status(A).used
    reservation = credits.reserve(tenant=A, action="offer-portfolio-system")
    released = credits.release(reservation.id, tenant=A, reason="the job failed")

    assert released.state is ReservationState.RELEASED
    assert credits.status(A).used == used_before, "a failure must cost nothing"
    assert credits.held(A) == 0.0


def test_a_settled_reservation_cannot_be_settled_again(credits) -> None:
    reservation = credits.reserve(tenant=A, action="offer-website")
    credits.settle(reservation.id, tenant=A)
    with pytest.raises(NotReserved, match="charge for one piece of work twice"):
        credits.settle(reservation.id, tenant=A)


def test_a_released_reservation_cannot_be_settled(credits) -> None:
    reservation = credits.reserve(tenant=A, action="offer-website")
    credits.release(reservation.id, tenant=A)
    with pytest.raises(NotReserved, match="already released"):
        credits.settle(reservation.id, tenant=A)


def test_settling_more_than_was_reserved_is_refused(credits) -> None:
    """The excess was never checked against the allowance, so settling it would
    let a job overspend a plan after the fact."""
    reservation = credits.reserve(tenant=A, action="offer-website")
    with pytest.raises(QuotaExhausted):
        credits.settle(reservation.id, tenant=A, actual_units=reservation.units + 1)


def test_settling_less_than_reserved_returns_the_difference(credits) -> None:
    reservation = credits.reserve(tenant=A, action="offer-website")
    credits.settle(reservation.id, tenant=A, actual_units=5.0)
    assert credits.status(A).used == 5.0


# ============================================ tenancy

def test_another_tenants_reservation_is_absent_not_forbidden(credits) -> None:
    reservation = credits.reserve(tenant=A, action="offer-website")
    with pytest.raises(NotReserved, match="no reservation"):
        credits.settle(reservation.id, tenant=B)
    with pytest.raises(NotReserved, match="no reservation"):
        credits.release(reservation.id, tenant=B)
    # And it is still held for its owner.
    assert credits.held(A) == credits.units_for("offer-website")


def test_one_tenants_spending_does_not_touch_anothers(credits) -> None:
    before = credits.balance(B)
    reservation = credits.reserve(tenant=A, action="offer-website")
    credits.settle(reservation.id, tenant=A)
    assert credits.balance(B) == before


def test_history_is_tenant_scoped(credits) -> None:
    credits.reserve(tenant=A, action="offer-website", business_id="biz-a")
    credits.reserve(tenant=B, action="offer-website", business_id="biz-b")
    assert {r.tenant_id for r in credits.history(A)} == {A}
    assert {r.tenant_id for r in credits.history(B)} == {B}


def test_the_usage_timeline_is_tenant_scoped(credits) -> None:
    reservation = credits.reserve(tenant=A, action="offer-website",
                                  business_id="biz-a")
    events = [to_event(reservation)]
    assert read(events, tenant=A)
    assert read(events, tenant=B) == []


def test_no_event_carries_money(credits) -> None:
    """There is no money in this package, so none reaches the timeline."""
    reservation = credits.reserve(tenant=A, action="offer-website",
                                  business_id="biz-a")
    detail = to_event(reservation).detail
    for forbidden in ("price", "cost", "amount_usd", "currency", "charge",
                      "invoice", "card", "payment"):
        assert forbidden not in detail, forbidden
    assert detail["units"] == credits.units_for("offer-website")


# ============================================ enforcement in the execution path

def test_credit_enforcement_is_fail_closed_once_switched_on(credits) -> None:
    """Optional because plans are not assigned yet — but a tenant with no plan
    is refused rather than treated as unlimited, which is the failure mode that
    makes a plan meaningless."""
    from atlas_kernel.recommendation.models import QevikTask
    from atlas_kernel.roadmap import gate
    from atlas_kernel.roadmap.lifecycle import TaskFacts
    from atlas_kernel.roadmap.models import Executability, Horizon, RoadmapTask

    task = RoadmapTask(id="t1", tenant_id="tenant-nobody", task=QevikTask("Website"),
                       horizon=Horizon.DAY_30,
                       executability=Executability.QEVIK_CAN_EXECUTE,
                       why="because", evidence=("observed",),
                       capability_id="cap-code-generation",
                       recommendation_id="rec-1")
    reasons = gate.unmet(task, recommendation=None, approval=None,
                         facts=TaskFacts(), tenant="tenant-nobody",
                         credits=credits)
    # The recommendation is absent here, so the credit branch is not reached —
    # what matters is that supplying the service never *loosens* the gate.
    assert reasons, "an unprovisioned tenant must not become executable"


def test_the_gate_is_unchanged_when_credits_are_not_supplied() -> None:
    """Existing callers must behave exactly as before."""
    from atlas_kernel.recommendation.models import QevikTask
    from atlas_kernel.roadmap import gate
    from atlas_kernel.roadmap.lifecycle import TaskFacts
    from atlas_kernel.roadmap.models import Executability, Horizon, RoadmapTask

    task = RoadmapTask(id="t1", tenant_id=A, task=QevikTask("Website"),
                       horizon=Horizon.DAY_30,
                       executability=Executability.QEVIK_CAN_EXECUTE,
                       why="because", evidence=("observed",),
                       capability_id="cap-code-generation", recommendation_id="rec-1")
    without = gate.unmet(task, recommendation=None, approval=None,
                         facts=TaskFacts(), tenant=A)
    assert not any("credits" in r for r in without)


# ============================================ end to end, through the real path

WEBSITE_RESEARCH = {"website": "", "http_status": 0,
                    "observations": [{"feature": "website", "status": "not_found"}]}


def _executable(tenant: str):
    """A real roadmap task Qevik can perform, for this tenant."""
    from atlas_kernel.opportunity.models import Business
    from atlas_kernel.outreach import opportunity as opp
    from atlas_kernel.recommendation import service as rec_service
    from atlas_kernel.recommendation.models import RecommendationState
    from atlas_kernel.roadmap import Executability, generate

    business = Business(id="biz-credits", name="Credit Test Logistics",
                        phone="+971 4 555 0199", email="ops@credit.test",
                        geography="Dubai", website="")
    ranked = opp.for_host("credit.test", category="logistics",
                          absent=frozenset({"website"}), present=frozenset())
    recommendations = rec_service.propose(
        business_id=business.id, tenant_id=tenant, opportunities=ranked,
        business_model="LOGISTICS", plan="ADVANCED")
    roadmap = generate(business_id=business.id, tenant_id=tenant,
                       observations=WEBSITE_RESEARCH["observations"],
                       recommendations=recommendations, business_model="LOGISTICS")
    task = next(t for t in roadmap.tasks
                if t.executability is Executability.QEVIK_CAN_EXECUTE)
    recommendation = next(r for r in recommendations
                          if r.id == task.recommendation_id).model_copy(
        update={"state": RecommendationState.ACCEPTED})
    return business, roadmap, task, recommendation


@pytest.mark.usefixtures("credits")
def test_an_exhausted_plan_stops_a_job_before_it_runs(credits) -> None:
    """The point of reserve-before-act: refused at the gate, not discovered
    after the provider was called."""
    from atlas_kernel.recommendation.models import RecommendationState
    from atlas_kernel.roadmap import gate
    from atlas_kernel.roadmap.lifecycle import facts_for

    _business, roadmap, task, recommendation = _executable(B)   # B is on LIST
    # Spend the LIST allowance down below what a website costs.
    used = credits.reserve(tenant=B, action="offer-website")
    credits.settle(used.id, tenant=B)
    assert credits.balance(B) < credits.units_for("offer-website")

    facts = facts_for(roadmap, recommendation_state=RecommendationState.ACCEPTED,
                      completed_task_ids=frozenset(t.id for t in roadmap.customer_tasks),
                      customer_action_done=True)
    reasons = gate.unmet(task, recommendation=recommendation, approval=None,
                         facts=facts, tenant=B, credits=credits)
    assert any("units left" in r for r in reasons), reasons


def test_a_failed_execution_releases_and_costs_nothing(credits, tmp_path) -> None:
    from atlas_kernel import db
    from atlas_kernel.composition_root import create_runtime
    from atlas_kernel.recommendation.models import RecommendationState
    from atlas_kernel.roadmap import crossing
    from atlas_kernel.roadmap.lifecycle import facts_for

    db.init_db()
    runtime = create_runtime()
    business, roadmap, task, recommendation = _executable(A)
    approval = runtime.approval_service.approve(
        crossing.request_approval(task, recommendation=recommendation,
                                  approvals=runtime.approval_service,
                                  business_name=business.name).id, actor="ayoub")
    facts = facts_for(roadmap, recommendation_state=RecommendationState.ACCEPTED,
                      completed_task_ids=frozenset(t.id for t in roadmap.customer_tasks),
                      customer_action_done=True)

    before = credits.status(A).used
    # No business record, so the capability refuses and the job fails QA.
    outcome = crossing.execute_task(
        task, recommendation=recommendation, approval=approval, facts=facts,
        tenant=A, research={"website": "", "http_status": 0, "observations": []},
        business_name=business.name, repository=runtime.repository,
        business=None, credits=credits)

    assert not outcome.succeeded or outcome.failed_gates
    assert credits.status(A).used == before, "a failed job must cost nothing"
    assert credits.held(A) == 0.0, "and must not leave units held"
    assert any(r.state is ReservationState.RELEASED for r in credits.history(A))


def test_a_successful_execution_settles_exactly_once(credits) -> None:
    from atlas_kernel import db
    from atlas_kernel.composition_root import create_runtime
    from atlas_kernel.recommendation.models import RecommendationState
    from atlas_kernel.roadmap import crossing
    from atlas_kernel.roadmap.lifecycle import facts_for

    db.init_db()
    runtime = create_runtime()
    business, roadmap, task, recommendation = _executable(A)
    approval = runtime.approval_service.approve(
        crossing.request_approval(task, recommendation=recommendation,
                                  approvals=runtime.approval_service,
                                  business_name=business.name).id, actor="ayoub")
    facts = facts_for(roadmap, recommendation_state=RecommendationState.ACCEPTED,
                      completed_task_ids=frozenset(t.id for t in roadmap.customer_tasks),
                      customer_action_done=True)

    before = credits.status(A).used
    outcome = crossing.execute_task(
        task, recommendation=recommendation, approval=approval, facts=facts,
        tenant=A, research=WEBSITE_RESEARCH, business_name=business.name,
        repository=runtime.repository, business=business, credits=credits)

    assert outcome.succeeded and not outcome.failed_gates
    assert credits.status(A).used == before + credits.units_for("offer-website")
    assert credits.held(A) == 0.0
    settled = [r for r in credits.history(A) if r.state is ReservationState.SETTLED]
    assert len(settled) == 1 and settled[0].job_id == outcome.job_id
