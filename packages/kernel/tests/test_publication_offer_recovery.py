"""What a publication published, recovered from the mission that published it.

Found by reading production: four of the five addresses Qevik has put on the
internet record no `offer`. They were written before the field existed, and
`outreach.preparation` refuses a publication that cannot say what it is — so two
real businesses with a live artefact, an accepted review and a reachable number
could never be written to, permanently, because nothing re-publishes them.

The value was never lost. `offer` is read from the delivering mission's recipe
at publication time, and that recipe id is on the mission's own ledger.

The whole risk here is a recovery that becomes an invention, so every test below
is about what it must *refuse* to conclude:

* an unknown recipe, a recipe that delivers nothing, a mission with no ledger
  entry and a publication with no mission all stay empty, and
* a recovered offer is labelled as recovered. It is as true as a recorded one
  and did not come from the same place, and a reader that cannot tell them apart
  cannot audit either.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text

from atlas_kernel import db
from atlas_kernel.db import SessionLocal
from atlas_kernel.opportunity.repository import OpportunityRepository

TENANT = "tenant-offer-recovery"


@pytest.fixture(scope="module", autouse=True)
def schema():
    db.init_db()


@pytest.fixture
def repo() -> OpportunityRepository:
    return OpportunityRepository()


def _ledger(mission_id: str, recipe: str, *, business_id: str) -> None:
    """One mission transition, the way `mission.service` writes them."""
    with SessionLocal() as session:
        session.execute(
            text("""
            INSERT INTO atlas_business_events
                (id, business_id, factory, kind, opportunity_id, actor, detail, at)
            VALUES (:id, :business, 'mission', 'mission_transition', '',
                    'worker', :detail, :at)
            """),
            {"id": f"evt-{uuid4().hex[:12]}", "business": business_id,
             "detail": json.dumps({"mission_id": mission_id, "recipe": recipe,
                                   "status": "complete"}),
             "at": datetime.now(UTC)})
        session.commit()


def _published(repo: OpportunityRepository, business_id: str, *,
               mission_id: str, offer: str = "") -> None:
    repo.record_publication(
        mission_id=mission_id, business_id=business_id, signal_id="sig-x",
        commit="abc123", site_id="s", url="https://sites.test/s",
        files=["index.html"], actor="worker", offer=offer, tenant=TENANT)


def _clean(business_id: str) -> None:
    with SessionLocal() as session:
        session.execute(
            text("DELETE FROM atlas_business_events WHERE business_id = :b"),
            {"b": business_id})
        session.commit()


def test_a_publication_recovers_what_it_published_from_its_own_mission(repo):
    business = f"biz-{uuid4().hex[:10]}"
    try:
        _ledger("mission-1", "deliver-health-check", business_id=business)
        _published(repo, business, mission_id="mission-1")   # no offer recorded

        one = repo.publications_of(business)[-1]
        assert one["offer"] == "offer-health-check"
        assert one["offer_recorded"] is False
        assert one["offer_from"] == "the recipe the mission ran"
    finally:
        _clean(business)


def test_a_recorded_offer_is_never_overwritten_by_the_recipe(repo):
    """The record wins. It is what was true when the page went up."""
    business = f"biz-{uuid4().hex[:10]}"
    try:
        _ledger("mission-2", "deliver-health-check", business_id=business)
        _published(repo, business, mission_id="mission-2", offer="offer-website")

        one = repo.publications_of(business)[-1]
        assert one["offer"] == "offer-website"
        assert one["offer_recorded"] is True
        assert one["offer_from"] == "the publication record"
    finally:
        _clean(business)


@pytest.mark.parametrize("recipe,why", [
    # A real declared recipe that delivers nothing — `publish-website` puts
    # any artefact on the host and knows only that it published files.
    ("publish-website", "a declared recipe that delivers no offer"),
    ("no-such-recipe-at-all", "a recipe nothing declares"),
])
def test_a_recipe_that_cannot_say_leaves_it_unknown(repo, recipe, why):
    business = f"biz-{uuid4().hex[:10]}"
    try:
        _ledger("mission-3", recipe, business_id=business)
        _published(repo, business, mission_id="mission-3")

        one = repo.publications_of(business)[-1]
        assert one["offer"] == "", why
        assert one["offer_from"] == ""
    finally:
        _clean(business)


def test_a_mission_with_no_ledger_entry_leaves_it_unknown(repo):
    business = f"biz-{uuid4().hex[:10]}"
    try:
        _published(repo, business, mission_id="mission-that-never-ran")
        one = repo.publications_of(business)[-1]
        assert one["offer"] == ""
        assert one["offer_from"] == ""

        # Negative control: the same publication recovers once its mission has
        # a ledger entry, so the emptiness above is the missing entry and not a
        # resolver that never resolves anything.
        _ledger("mission-that-never-ran", "deliver-website",
                business_id=business)
        assert repo.publications_of(business)[-1]["offer"] == "offer-website"
    finally:
        _clean(business)


def test_both_readers_describe_a_publication_the_same_way(repo):
    """One publication, two callers, one answer.

    `publications_for` feeds the thing that composes the message and
    `publications_of` feeds the dossier that shows it. A publication that
    described itself one way to the operator and another to the composer is the
    disagreement an approval fingerprint would then certify.
    """
    business = f"biz-{uuid4().hex[:10]}"
    try:
        _ledger("mission-4", "deliver-health-check", business_id=business)
        _published(repo, business, mission_id="mission-4")

        mine = repo.publications_of(business)[-1]
        theirs = repo.publications_for("mission-4")[-1]
        for field in ("offer", "offer_recorded", "offer_from", "url", "commit"):
            assert mine[field] == theirs[field], field
    finally:
        _clean(business)


def test_a_recovered_offer_is_enough_to_prepare_the_message(repo):
    """The point of the recovery, end to end.

    Two production businesses have a live artefact, an accepted review and a
    number, and `prepare` refuses them because the publication cannot say what
    it is. This is that refusal lifting — and it lifts into a *draft*, which is
    still behind the same approval boundary as everything else.
    """
    from atlas_kernel.opportunity.models import Business
    from atlas_kernel.outreach import preparation

    saved = repo.save_business(Business(
        name="Al Waha Dental", geography="United Arab Emirates",
        website="https://alwaha.test", email="hello@alwaha.test",
        sources=["seed"]))
    try:
        _ledger("mission-5", "deliver-health-check", business_id=saved.id)
        _published(repo, saved.id, mission_id="mission-5")
        publication = repo.publications_of(saved.id)[-1]

        prepared = preparation.prepare(
            business=saved, signal={"id": "sig-x", "evidence_fingerprints": []},
            publication=publication, approved_scope="the published health check")
        assert prepared.subject and prepared.body
        assert prepared.recipient == "hello@alwaha.test"
        # Composed, and still unsendable: no sending identity is configured.
        assert prepared.blocked_on

        # Negative control: with no ledger entry the refusal is back, so the
        # composition above came from the recovery and not from a default.
        _clean(saved.id)
        _published(repo, saved.id, mission_id="mission-5")
        with pytest.raises(preparation.NotPreparable):
            preparation.prepare(
                business=saved, signal={"id": "sig-x", "evidence_fingerprints": []},
                publication=repo.publications_of(saved.id)[-1],
                approved_scope="the published health check")
    finally:
        _clean(saved.id)
        with SessionLocal() as session:
            session.execute(text("DELETE FROM atlas_businesses WHERE id = :b"),
                            {"b": saved.id})
            session.commit()
