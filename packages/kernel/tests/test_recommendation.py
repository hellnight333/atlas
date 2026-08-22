"""Recommendations: evidence-gated, capability-backed, and unable to execute.

The twelve properties this phase was gated on. The ones that matter most are
negative: a recommendation cannot be built without evidence, cannot name a
capability the system does not have, cannot turn an unverified observation into
a confirmed problem, and cannot start work.

The AHS case is the standing test of the last point. A twenty-year-old business
with a 484ms site must be able to receive useful recommendations without any of
them implying its website is poor.
"""

from __future__ import annotations

import pytest

from atlas_kernel.composition_root import _register_default_capabilities
from atlas_kernel.opportunity.tenancy import ALL_TENANTS, TenantRequired
from atlas_kernel.outreach import opportunity as opp
from atlas_kernel.recommendation import (
    CapabilityOffer,
    CustomerTask,
    OFFERS,
    QevikTask,
    Recommendation,
    RecommendationState,
    TaskKind,
    Unsupported,
    offers_for_opportunity,
)
from atlas_kernel.recommendation import service
from atlas_kernel.recommendation.offers import Availability
from atlas_kernel.registry import Registry

AHS_ABSENT = frozenset({"arabic", "click_to_call", "orphan_pages", "blog_cadence"})
AHS_PRESENT = frozenset({"social_proof", "portfolio_depth", "structured_data", "blog"})
STRENGTHS = ("20+ years trading", "site loads in 484ms", "32 published events",
             "501-item media library")


@pytest.fixture(scope="module")
def registry() -> Registry:
    made = Registry()
    _register_default_capabilities(made)
    return made


@pytest.fixture
def ahs():
    ranked = opp.for_host("ahscatering.com", category="food",
                          absent=AHS_ABSENT, present=AHS_PRESENT)
    return service.propose(business_id="ahs", tenant_id="t-qevik", opportunities=ranked,
                           business_model="CATERING", plan="ADVANCED",
                           strengths=STRENGTHS)


# 1 --- opportunity to recommendation provenance ---------------------------

def test_every_recommendation_traces_to_an_opportunity_and_its_evidence(ahs) -> None:
    assert ahs
    for rec in ahs:
        assert rec.opportunity_key, rec.title
        assert rec.evidence, rec.title
        why = rec.why()
        assert why["opportunity"] == rec.opportunity_key
        assert why["evidence"] == list(rec.evidence)


def test_a_recommendation_cannot_exist_without_evidence() -> None:
    with pytest.raises(Unsupported, match="sales pitch"):
        Recommendation(business_id="b", opportunity_key="proof", evidence=(),
                       title="Do a thing", rationale="because")


def test_a_recommendation_must_say_why_it_matters() -> None:
    with pytest.raises(Unsupported):
        Recommendation(business_id="b", opportunity_key="proof", evidence=("seen",),
                       title="Do a thing", rationale="   ")


# 2, 3 --- capability backing -----------------------------------------------

def test_every_offer_names_a_capability_the_system_has(registry) -> None:
    for offer in OFFERS:
        spec = offer.validate_against(registry)
        assert spec.id == offer.capability_id


def test_an_offer_for_an_unknown_capability_is_refused(registry) -> None:
    invented = CapabilityOffer(id="offer-invented", capability_id="cap-does-not-exist",
                               name="Invented", summary="x")
    with pytest.raises(Unsupported, match="no capability"):
        invented.validate_against(registry)


def test_every_recommendation_names_a_registered_capability(ahs, registry) -> None:
    for rec in ahs:
        assert registry.get_capability(rec.capability_id) is not None, rec.title


# 4 --- unverified never becomes confirmed ---------------------------------

def test_unverified_evidence_is_carried_separately_and_never_as_grounds() -> None:
    """A stage that could not look has not found a problem."""
    ranked = opp.derive(category="food", absent=frozenset({"arabic"}),
                        present=frozenset())
    recs = service.propose(business_id="b", tenant_id="t", opportunities=ranked,
                           unverified=("whatsapp could not be checked",))
    assert recs
    for rec in recs:
        assert "could not be checked" not in " ".join(rec.evidence)
        assert rec.unverified == ("whatsapp could not be checked",)
        assert rec.why()["not_verified"] == ["whatsapp could not be checked"]


def test_an_unverified_feature_produces_no_opportunity_and_so_no_recommendation() -> None:
    """The gate is upstream and must stay that way."""
    nothing = opp.derive(category="food", absent=frozenset(), present=frozenset())
    assert nothing == ()
    assert service.propose(business_id="b", tenant_id="t", opportunities=nothing) == ()


# 5, 6 --- a strong business ------------------------------------------------

def test_a_strong_business_can_receive_no_recommendations_at_all() -> None:
    assert service.propose(business_id="b", tenant_id="t", opportunities=()) == ()


def test_the_ahs_case_never_says_the_website_is_poor(ahs) -> None:
    """The standing test. Useful recommendations, no manufactured weakness."""
    assert ahs, "a strong business should still get additive recommendations"
    forbidden = ("bad", "poor", "terrible", "outdated", "broken", "unprofessional",
                 "amateur", "ugly", "slow website")
    for rec in ahs:
        text = f"{rec.title} {rec.rationale}".lower()
        for word in forbidden:
            assert word not in text, f"{rec.title!r} calls the business {word!r}"


def test_a_strong_business_carries_its_strengths_into_every_recommendation(ahs) -> None:
    """So the proposal reads as an addition rather than a complaint."""
    for rec in ahs:
        assert rec.strengths == STRENGTHS
        assert "484ms" in " ".join(rec.strengths)


def test_an_opportunity_with_no_capability_produces_nothing() -> None:
    """Never invent work because a capability exists, nor promise work it does not."""
    ranked = opp.derive(category="food", absent=frozenset({"google_maps"}),
                        present=frozenset())
    assert ranked, "the opportunity is real"
    assert offers_for_opportunity("maps") == (), "and Qevik has no offer for it"
    assert service.propose(business_id="b", tenant_id="t", opportunities=ranked) == ()


# 7 --- customer tasks and Qevik tasks stay distinct -----------------------

def test_customer_and_qevik_tasks_are_separate_and_both_present(ahs) -> None:
    for rec in ahs:
        assert rec.customer_tasks, f"{rec.title} asks nothing of the customer"
        assert rec.qevik_tasks, f"{rec.title} has Qevik doing nothing"
        assert not set(rec.customer_tasks) & set(rec.qevik_tasks)
        for task in rec.customer_tasks:
            assert task.kind is TaskKind.CUSTOMER_TASK and task.action


def test_a_customer_task_must_say_what_to_do() -> None:
    with pytest.raises(Unsupported, match="nobody can complete"):
        CustomerTask("Approve the thing", "")


def test_a_qevik_task_is_never_silently_a_customer_task(ahs) -> None:
    for rec in ahs:
        for task in rec.qevik_tasks:
            assert not task.action, f"{task.title!r} asks the customer to act"


def test_approval_is_always_a_customer_task(ahs) -> None:
    for rec in ahs:
        assert any("approve" in t.title.lower() for t in rec.customer_tasks), rec.title


# 8, 9 --- tenant isolation -------------------------------------------------

def _events(recs):
    return [service.to_event(r) for r in recs]


def test_recommendations_carry_the_tenant_they_were_proposed_under(ahs) -> None:
    for rec in ahs:
        assert rec.tenant_id == "t-qevik"


def test_one_tenant_cannot_read_anothers_recommendations(ahs) -> None:
    other = service.propose(business_id="ahs", tenant_id="t-other",
                            opportunities=opp.derive(category="food",
                                                     absent=frozenset({"arabic"}),
                                                     present=frozenset()))
    timeline = _events(ahs) + _events(other)
    mine = service.fold(timeline, tenant="t-qevik")
    theirs = service.fold(timeline, tenant="t-other")
    assert mine and theirs
    assert {r["recommendation_id"] for r in mine}.isdisjoint(
        {r["recommendation_id"] for r in theirs})
    assert all(r["tenant_id"] == "t-qevik" for r in mine)


def test_reading_recommendations_requires_a_tenant(ahs) -> None:
    with pytest.raises(TenantRequired):
        service.fold(_events(ahs))


def test_the_operator_console_can_read_across_tenants_explicitly(ahs) -> None:
    assert service.fold(_events(ahs), tenant=ALL_TENANTS)


def test_a_recommendation_with_no_tenant_belongs_to_nobody() -> None:
    orphan = service.propose(
        business_id="b", tenant_id=None,
        opportunities=opp.derive(category="food", absent=frozenset({"arabic"}),
                                 present=frozenset()))
    assert service.fold(_events(orphan), tenant="t-qevik") == []
    assert service.fold(_events(orphan), tenant=ALL_TENANTS)


# 10 --- it cannot execute --------------------------------------------------

def test_a_proposed_recommendation_is_never_executable(ahs) -> None:
    for rec in ahs:
        assert rec.state is RecommendationState.PROPOSED
        assert rec.executable is False


def test_acceptance_alone_does_not_make_it_executable(ahs) -> None:
    """A customer task still outstanding blocks it, whatever the state says."""
    accepted = ahs[0].model_copy(update={"state": RecommendationState.ACCEPTED})
    assert accepted.waiting_on_customer
    assert accepted.executable is False


def test_it_becomes_executable_only_once_nothing_is_outstanding(ahs) -> None:
    unblocked = ahs[0].model_copy(update={
        "state": RecommendationState.ACCEPTED,
        "tasks": tuple(t for t in ahs[0].tasks if t.kind is TaskKind.QEVIK_TASK)})
    assert unblocked.executable is True, "and even then, execution is P1.3's job"


def test_the_module_cannot_publish_or_spend() -> None:
    """A guard on what this layer is even able to do."""
    from pathlib import Path
    source = Path(service.__file__).read_text(encoding="utf-8")
    for forbidden in ("httpx", "requests", "publish(", "deploy(", "charge(", "smtplib"):
        assert forbidden not in source, f"{forbidden} reached the recommendation layer"


def test_every_recommendation_requires_approval_by_default(ahs) -> None:
    for rec in ahs:
        assert rec.requires_approval is True


# 11 --- no second capability registry -------------------------------------

def test_offers_are_a_view_over_the_existing_registry_not_a_second_one() -> None:
    from pathlib import Path

    from atlas_kernel.recommendation import offers as offers_module

    source = Path(offers_module.__file__).read_text(encoding="utf-8")
    assert "from ..models import CapabilitySpec" in source
    assert "from ..registry import Registry" in source
    for forbidden in ("class CapabilityRegistry", "class Capability(", "CAPABILITIES ="):
        assert forbidden not in source, f"{forbidden} is a second capability registry"


def test_publication_targets_are_not_modelled_as_capabilities() -> None:
    """One capability reaches many targets; the reverse duplicates approval,
    credentials and QA per marketplace."""
    for offer in OFFERS:
        assert not offer.capability_id.startswith(("amazon", "noon", "social",
                                                   "instagram")), offer.id
        assert offer.publication_target in ("", "website", "marketplace", "social",
                                            "email", "ads")


def test_an_offer_can_be_recommendable_while_unconnectable() -> None:
    """How Qevik offers marketplace work honestly before marketplace access."""
    offer = CapabilityOffer(id="offer-x", capability_id="cap-reasoning", name="X",
                            summary="y", availability=Availability.REQUIRES_CONNECTION)
    assert offer.eligible() is True
    dead = offer.model_copy(update={"availability": Availability.UNAVAILABLE})
    assert dead.eligible() is False


# 12 --- nothing upstream changed ------------------------------------------

def test_the_opportunity_engine_is_untouched() -> None:
    ranked = opp.for_host("ahscatering.com", category="food",
                          absent=AHS_ABSENT, present=AHS_PRESENT)
    assert ranked[0].key == "proof"
    assert opp.headline(ranked) == "Proof system"
    for o in ranked:
        assert o.evidence


def test_one_recommendation_per_offer_not_per_opportunity(ahs) -> None:
    """Two opportunities answered by one piece of work is one proposal."""
    offer_ids = [r.offer_id for r in ahs]
    assert len(offer_ids) == len(set(offer_ids)), "the same work proposed twice"
    portfolio = next(r for r in ahs if r.offer_id == "offer-portfolio-system")
    assert len(portfolio.evidence) > 5, "merged evidence from both opportunities"
