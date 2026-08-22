"""One company, one history — and the rule that keeps it one company (M014).

Two properties, both stated by Ayoub as permanent:

**Business is Atlas's permanent memory of a company.** Every factory contributes
to one chronological timeline, so "what has Atlas ever done with this company"
has a single answer. These tests write to that timeline as factories that do not
exist yet, because the point of the design is that they can.

**Identity resolution stays conservative.** False negatives — duplicate records —
are acceptable. False positives — merging two different companies — are not. A
duplicate costs a row. A wrong merge takes one company's history into another's,
and once that has happened the timeline above is no longer a record of anything.
The asymmetry is not a tuning preference; it decides which way every ambiguous
case goes.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from atlas_kernel import db
from atlas_kernel.opportunity.identity import (
    BusinessIndex,
    is_possible_duplicate,
    is_same_business,
)
from atlas_kernel.opportunity.metrics import build_report
from atlas_kernel.opportunity.models import (
    OPPORTUNITY_FACTORY,
    Business,
    BusinessEvent,
    PipelineEventKind,
)
from atlas_kernel.opportunity.repository import OpportunityRepository
from atlas_kernel.opportunity.tenancy import ALL_TENANTS


@pytest.fixture(scope="module", autouse=True)
def schema():
    db.init_db()


@pytest.fixture
def repo() -> OpportunityRepository:
    return OpportunityRepository()


@pytest.fixture
def unique() -> str:
    return uuid4().hex[:10]


class TestOneCompanyOneHistory:
    def test_every_factory_writes_to_the_same_timeline(
        self, repo: OpportunityRepository, unique: str
    ) -> None:
        """Written as factories that do not exist yet. That is the test: a
        website deployment must be recordable without editing the opportunity
        package or adding a member to its enum."""
        business, _ = repo.resolve_business(
            Business(name="Timeline Co", geography="Dubai", website=f"https://tl-{unique}.ae")
        )

        repo.record_event(BusinessEvent(business_id=business.id, kind=PipelineEventKind.SENT))
        repo.record_event(
            BusinessEvent(business_id=business.id, factory="website", kind="deployed")
        )
        repo.record_event(
            BusinessEvent(business_id=business.id, factory="amazon", kind="listing_updated")
        )
        repo.record_event(
            BusinessEvent(business_id=business.id, factory="support", kind="ticket_closed")
        )

        history = repo.timeline(business.id)

        assert [(e.factory, e.kind) for e in history] == [
            (OPPORTUNITY_FACTORY, "sent"),
            ("website", "deployed"),
            ("amazon", "listing_updated"),
            ("support", "ticket_closed"),
        ]

    def test_the_history_is_chronological(self, repo: OpportunityRepository, unique: str) -> None:
        business, _ = repo.resolve_business(
            Business(name="Order Co", geography="Dubai", website=f"https://ord-{unique}.ae")
        )
        for kind in ("discovered", "qualified", "sent", "replied"):
            repo.record_event(BusinessEvent(business_id=business.id, kind=kind))
        assert [e.kind for e in repo.timeline(business.id)] == [
            "discovered",
            "qualified",
            "sent",
            "replied",
        ]

    def test_one_factory_can_be_read_on_its_own(
        self, repo: OpportunityRepository, unique: str
    ) -> None:
        business, _ = repo.resolve_business(
            Business(name="Slice Co", geography="Dubai", website=f"https://sl-{unique}.ae")
        )
        repo.record_event(BusinessEvent(business_id=business.id, kind="sent"))
        repo.record_event(
            BusinessEvent(business_id=business.id, factory="website", kind="deployed")
        )
        assert [e.kind for e in repo.timeline(business.id, factory="website")] == ["deployed"]

    def test_a_timeline_entry_needs_no_opportunity(
        self, repo: OpportunityRepository, unique: str
    ) -> None:
        """A deployment or a support ticket is not an opportunity. Requiring one
        would force other factories to invent a fake."""
        business, _ = repo.resolve_business(
            Business(name="No Opp Co", geography="Dubai", website=f"https://no-{unique}.ae")
        )
        repo.record_event(
            BusinessEvent(business_id=business.id, factory="support", kind="ticket_opened")
        )
        assert repo.timeline(business.id)[0].opportunity_id is None

    def test_histories_do_not_bleed_between_companies(
        self, repo: OpportunityRepository, unique: str
    ) -> None:
        one, _ = repo.resolve_business(
            Business(name="Bleed A", geography="Dubai", website=f"https://ba-{unique}.ae")
        )
        two, _ = repo.resolve_business(
            Business(name="Bleed B", geography="Dubai", website=f"https://bb-{unique}.ae")
        )
        repo.record_event(BusinessEvent(business_id=one.id, kind="sent"))
        assert repo.timeline(two.id) == []

    def test_an_event_must_say_what_happened(self) -> None:
        with pytest.raises(ValueError, match="say what happened"):
            BusinessEvent(business_id="b1", kind="   ")

    def test_the_timeline_is_append_only(self) -> None:
        """A memory that can be rewritten is not a memory."""
        event = BusinessEvent(business_id="b1", kind="sent")
        with pytest.raises(ValueError):
            event.kind = "not_sent"  # type: ignore[misc]


class TestOtherFactoriesDoNotCorruptTheFunnel:
    def test_another_factory_s_events_are_not_counted_as_funnel_stages(self) -> None:
        """The failure this guards against is silent: a website factory writing
        "sent" to mean a deploy notification would inflate the reply-rate
        denominator and nothing would look wrong."""
        events = [
            BusinessEvent(business_id="b1", kind=PipelineEventKind.SENT),
            BusinessEvent(business_id="b2", factory="website", kind="sent"),
            BusinessEvent(business_id="b3", factory="amazon", kind="won"),
        ]
        report = build_report(events)
        assert report.counts["sent"] == 1
        assert report.counts["won"] == 0

    def test_the_funnel_still_works_when_the_timeline_is_only_outreach(self) -> None:
        events = [
            BusinessEvent(business_id="b1", kind=PipelineEventKind.SENT),
            BusinessEvent(business_id="b1", kind=PipelineEventKind.REPLIED),
        ]
        assert build_report(events).reply_rate == 1.0

    def test_list_events_returns_only_this_factory(
        self, repo: OpportunityRepository, unique: str
    ) -> None:
        business, _ = repo.resolve_business(
            Business(name="Funnel Co", geography="Dubai", website=f"https://fn-{unique}.ae")
        )
        repo.record_event(
            BusinessEvent(business_id=business.id, factory="website", kind="deployed")
        )
        assert all(e.factory == OPPORTUNITY_FACTORY for e in repo.list_events(tenant=ALL_TENANTS))


class TestConservatismIsAnInvariantNotAPreference:
    """False negatives acceptable. False positives never.

    Each case below is one Atlas could plausibly be tempted to merge. Every one
    must be refused, because the cost of being wrong is asymmetric: a duplicate
    is a row, a wrong merge is one company's history inside another's.
    """

    @pytest.mark.parametrize(
        ("left", "right", "why"),
        [
            (
                Business(name="Al Noor Clinic", geography="Dubai", website="https://one.ae"),
                Business(name="Al Noor Clinic", geography="Dubai", website="https://two.ae"),
                "same name and city, different sites — two branches or two companies",
            ),
            (
                Business(name="Al Noor Clinic", geography="Dubai"),
                Business(name="Al Noor Clinic", geography="Dubai"),
                "identical names and nothing else known at all",
            ),
            (
                Business(name="Gulf Trading", geography="Dubai", phone="1234"),
                Business(name="Gulf Trading", geography="Dubai", phone="1234"),
                "a shared four-digit extension is not a phone number",
            ),
            (
                Business(name="Clinic A", geography="Dubai", website="https://a.wixsite.com"),
                Business(name="Clinic B", geography="Dubai", website="https://b.wixsite.com"),
                "a shared hosting platform is not a shared company",
            ),
        ],
    )
    def test_plausible_matches_are_refused(self, left: Business, right: Business, why: str) -> None:
        assert not is_same_business(left, right), f"wrongly merged: {why}"

    def test_refused_matches_still_reach_a_human(self) -> None:
        """Conservative must not mean silent. A refused merge that nobody ever
        sees is a duplicate nobody can fix."""
        left = Business(name="Al Noor Clinic", geography="Dubai", website="https://one.ae")
        right = Business(name="Al Noor Clinic", geography="Dubai", website="https://two.ae")
        assert is_possible_duplicate(left, right)

    def test_a_duplicate_is_the_acceptable_outcome(self) -> None:
        """Stated as a test so the intent survives someone later 'improving'
        the matcher: two rows for one company is the *correct* behaviour when
        nothing strong agrees."""
        index = BusinessIndex()
        index.resolve(Business(name="Same Name", geography="Dubai", website="https://x1.ae"))
        index.resolve(Business(name="Same Name", geography="Dubai", website="https://x2.ae"))
        assert len(index.businesses) == 2

    def test_only_a_strong_key_merges(self) -> None:
        left = Business(name="Totally Different", geography="Abu Dhabi", email="shared@co.ae")
        right = Business(name="Nothing Alike", geography="Dubai", email="shared@co.ae")
        assert is_same_business(left, right), "a shared email is a strong key"

    def test_merging_never_loses_the_earlier_record_s_facts(self) -> None:
        """Even a correct merge must not overwrite. If the merge later turns out
        to be wrong, what was overwritten cannot be recovered."""
        index = BusinessIndex()
        index.resolve(
            Business(
                name="Keep Facts",
                geography="Dubai",
                website="https://keep.ae",
                phone="+97141112222",
            )
        )
        merged, _ = index.resolve(
            Business(
                name="Keep Facts LLC",
                geography="Dubai",
                website="https://keep.ae",
                phone="+97149998888",
            )
        )
        assert merged.phone == "+97141112222"
