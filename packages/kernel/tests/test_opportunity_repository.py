"""Persistence for the Opportunity Factory (M014).

Most of this is ordinary round-tripping. Two properties are not:

* **The suppression list survives a restart.** A "never contact me again" that
  lives only in memory is not a suppression list, and the failure mode is
  contacting someone who explicitly asked not to be.
* **The contact history is derived from what was actually sent**, so the
  cooldown cannot drift away from reality.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from atlas_kernel import db
from atlas_kernel.opportunity.models import (
    Business,
    Evidence,
    EvidenceKind,
    Finding,
    FindingKind,
    Opportunity,
    OpportunityStage,
    OutreachMessage,
    OutreachStatus,
    PipelineEvent,
    PipelineEventKind,
    Proposal,
    ProposalClaim,
    Severity,
)
from atlas_kernel.opportunity.repository import OpportunityRepository


@pytest.fixture(scope="module", autouse=True)
def schema():
    db.init_db()


@pytest.fixture
def repo() -> OpportunityRepository:
    return OpportunityRepository()


def _business(name: str = "Al Noor Dental Clinic") -> Business:
    return Business(
        name=name,
        geography="United Arab Emirates",
        website="https://clinic.test",
        email="hello@clinic.test",
        sources=["seed-list"],
        metadata={"area": "Jumeirah"},
    )


def _finding(business_id: str) -> Finding:
    return Finding(
        business_id=business_id,
        kind=FindingKind.MISSING_TITLE,
        severity=Severity.HIGH,
        statement="The page has no title.",
        evidence=[
            Evidence(
                kind=EvidenceKind.HTML_CONTENT,
                source="https://clinic.test",
                observed={"title": None},
                summary="No <title> element.",
                detector="website",
            )
        ],
    )


class TestBusinesses:
    def test_round_trip(self, repo: OpportunityRepository) -> None:
        saved = repo.save_business(_business())
        loaded = repo.get_business(saved.id)
        assert loaded is not None
        assert loaded.name == saved.name
        assert loaded.metadata == {"area": "Jumeirah"}

    def test_saving_twice_updates_rather_than_duplicating(
        self, repo: OpportunityRepository
    ) -> None:
        business = repo.save_business(_business())
        repo.save_business(business.model_copy(update={"email": "new@clinic.test"}))
        loaded = repo.get_business(business.id)
        assert loaded is not None and loaded.email == "new@clinic.test"

    def test_unknown_business_is_none(self, repo: OpportunityRepository) -> None:
        assert repo.get_business("does-not-exist") is None


class TestFindings:
    def test_evidence_survives_the_round_trip(self, repo: OpportunityRepository) -> None:
        """Evidence that does not come back intact cannot be re-checked, which
        would leave a claim standing on nothing."""
        business = repo.save_business(_business())
        finding = repo.save_finding(_finding(business.id))
        loaded = repo.list_findings(business.id)
        assert len(loaded) == 1
        assert loaded[0].evidence[0].observed == {"title": None}
        assert loaded[0].evidence[0].detector == "website"
        assert loaded[0].fingerprint == finding.fingerprint

    def test_saving_an_opportunity_saves_its_findings(self, repo: OpportunityRepository) -> None:
        business = repo.save_business(_business())
        opportunity = Opportunity(
            business_id=business.id,
            niche="test-niche",
            findings=[_finding(business.id)],
            stage=OpportunityStage.QUALIFIED,
            score=5.0,
        )
        repo.save_opportunity(opportunity)
        assert len(repo.list_findings(business.id)) == 1


class TestProposalsAndMessages:
    def test_a_proposal_round_trips_with_its_citations(self, repo: OpportunityRepository) -> None:
        business = repo.save_business(_business())
        proposal = repo.save_proposal(
            Proposal(
                business_id=business.id,
                opportunity_id="o1",
                subject="Your site has no title",
                body="We looked at your site today.",
                claims=[ProposalClaim(finding_id="f1", text="No title.", remedy="Add one.")],
                findings_fingerprint="abc123",
            )
        )
        loaded = repo.get_proposal(proposal.id)
        assert loaded is not None
        assert loaded.claims[0].remedy == "Add one."
        assert loaded.fingerprint == proposal.fingerprint

    def test_a_message_updates_in_place_as_it_progresses(self, repo: OpportunityRepository) -> None:
        business = repo.save_business(_business())
        message = repo.save_message(
            OutreachMessage(
                proposal_id="p1",
                business_id=business.id,
                channel="recording",
                recipient="hello@clinic.test",
                subject="s",
                body="b",
            )
        )
        sent = message.model_copy(
            update={
                "status": OutreachStatus.SENT,
                "sent_at": datetime.now(UTC),
                "provider_message_id": "recorded-1",
            }
        )
        repo.save_message(sent)
        history = repo.load_contact_history()
        assert history.last_contacted(business.id) is not None


class TestEvents:
    def test_events_are_append_only(self, repo: OpportunityRepository) -> None:
        business = repo.save_business(_business())
        opportunity = Opportunity(business_id=business.id, niche="event-niche")
        repo.save_opportunity(opportunity)
        for kind in (PipelineEventKind.DISCOVERED, PipelineEventKind.QUALIFIED):
            repo.record_event(
                PipelineEvent(opportunity_id=opportunity.id, business_id=business.id, kind=kind)
            )
        # Scoped to this opportunity: the test database persists between runs,
        # and an assertion that only holds on an empty table is an assertion
        # that will fail for a reason unrelated to the code it is testing.
        events = [
            event
            for event in repo.list_events(niche="event-niche")
            if event.opportunity_id == opportunity.id
        ]
        assert [e.kind for e in events] == [
            PipelineEventKind.DISCOVERED,
            PipelineEventKind.QUALIFIED,
        ]

    def test_event_detail_survives(self, repo: OpportunityRepository) -> None:
        business = repo.save_business(_business())
        repo.record_event(
            PipelineEvent(
                opportunity_id="o1",
                business_id=business.id,
                kind=PipelineEventKind.SENT,
                detail={"message_id": "recorded-1"},
            )
        )
        stored = [e for e in repo.list_events() if e.business_id == business.id]
        assert any(e.detail.get("message_id") == "recorded-1" for e in stored)


class TestNoSpamGuaranteesAreDurable:
    def test_suppression_survives_a_restart(self, repo: OpportunityRepository) -> None:
        """The whole reason this repository exists rather than keeping the list
        in memory."""
        repo.suppress("leave-me-alone@clinic.test", reason="asked to be removed")
        # A fresh repository stands in for a restarted process.
        assert OpportunityRepository().load_suppression().contains("leave-me-alone@clinic.test")

    def test_contact_history_comes_from_messages_that_actually_sent(
        self, repo: OpportunityRepository
    ) -> None:
        """A failed send must not start a cooldown, so the history is read from
        delivered messages rather than from attempts."""
        contacted = repo.save_business(_business("Contacted Business"))
        attempted = repo.save_business(_business("Failed Business"))

        repo.save_message(
            OutreachMessage(
                proposal_id="p1",
                business_id=contacted.id,
                channel="recording",
                recipient="a@clinic.test",
                subject="s",
                body="b",
                status=OutreachStatus.SENT,
                sent_at=datetime.now(UTC) - timedelta(days=3),
            )
        )
        repo.save_message(
            OutreachMessage(
                proposal_id="p2",
                business_id=attempted.id,
                channel="recording",
                recipient="b@clinic.test",
                subject="s",
                body="b",
                status=OutreachStatus.FAILED,
                detail="smtp refused",
            )
        )

        history = repo.load_contact_history()
        assert history.within_cooldown(contacted.id, days=90)
        assert not history.within_cooldown(attempted.id, days=90)


@pytest.fixture
def unique() -> str:
    """A suffix no earlier test run has used.

    Resolution is stateful by design — that is the entire point of it — so a
    test asserting "this business is new" is only meaningful against an identity
    the database has never seen. Without this the suite passes once and fails
    for ever after, for a reason that has nothing to do with the code.
    """
    return uuid4().hex[:10]


@pytest.fixture
def unique_digits() -> str:
    """A run-unique **numeric** suffix, for phone numbers.

    ``uuid4().hex`` is not usable here: ``normalise_phone`` strips non-digits, so
    a hex suffix yields a different number of digits each run and the key
    sometimes falls under the minimum length. That made the test pass or fail
    depending on the draw — worse than a failing test, because it looks like
    flakiness in the code rather than a mistake in the fixture.
    """
    return f"{uuid4().int % 10_000_000:07d}"


class TestIdentityResolutionSurvivesRestarts:
    """The in-memory index dedupes one run. This dedupes across weeks.

    A company found by Google Maps today and by a directory next month must
    resolve to the same row, or the cooldown protects one copy while the other
    is free to contact them again.
    """

    def test_the_same_business_found_again_resolves_to_one_record(
        self, repo: OpportunityRepository, unique: str, unique_digits: str
    ) -> None:
        first, is_new_first = repo.resolve_business(
            Business(
                name="Resolve Test Clinic",
                geography="Dubai",
                website=f"https://resolve-{unique}.ae",
                sources=["google-maps"],
            )
        )
        second, is_new_second = repo.resolve_business(
            Business(
                name="RESOLVE TEST CLINIC LLC",
                geography="Dubai",
                website=f"www.resolve-{unique}.ae",
                phone=f"+9714{unique_digits}",
                sources=["directory"],
            )
        )

        assert is_new_first is True
        assert is_new_second is False
        assert second.id == first.id
        assert second.sources == ["google-maps", "directory"]
        assert second.phone == f"+9714{unique_digits}", "a genuine gap should be filled"

    def test_a_different_business_is_not_merged_into_it(
        self, repo: OpportunityRepository, unique: str
    ) -> None:
        repo.resolve_business(
            Business(name="Distinct A", geography="Dubai", website=f"https://a-{unique}.ae")
        )
        _, is_new = repo.resolve_business(
            Business(name="Distinct B", geography="Dubai", website=f"https://b-{unique}.ae")
        )
        assert is_new is True

    def test_a_shared_name_and_city_does_not_merge_across_runs(
        self, repo: OpportunityRepository, unique: str
    ) -> None:
        """The failure that would attach one company's findings to another's
        proposal. Refused here as it is refused in memory."""
        name = f"Twin Name Clinic {unique}"
        one, _ = repo.resolve_business(
            Business(name=name, geography="Dubai", website=f"https://twin-one-{unique}.ae")
        )
        two, is_new = repo.resolve_business(
            Business(name=name, geography="Dubai", website=f"https://twin-two-{unique}.ae")
        )
        assert is_new is True
        assert two.id != one.id

    def test_lookalikes_are_findable_for_a_human(
        self, repo: OpportunityRepository, unique: str
    ) -> None:
        name = f"Lookalike Co {unique}"
        repo.resolve_business(
            Business(name=name, geography="Sharjah", website=f"https://look-one-{unique}.ae")
        )
        other, _ = repo.resolve_business(
            Business(name=name, geography="Sharjah", website=f"https://look-two-{unique}.ae")
        )
        assert [b.name for b in repo.find_possible_duplicates(other)] == [name]

    def test_a_business_with_no_contact_details_still_gets_stored(
        self, repo: OpportunityRepository, unique: str
    ) -> None:
        """No domain, email or phone means no strong key. It must still resolve
        to a row rather than being dropped."""
        business, is_new = repo.resolve_business(
            Business(name=f"No Details Trading {unique}", geography="Dubai")
        )
        assert is_new is True
        assert repo.get_business(business.id) is not None

    def test_a_sighting_matching_two_records_resolves_the_same_way_every_time(
        self, repo: OpportunityRepository, unique: str, unique_digits: str
    ) -> None:
        """A shared switchboard number can match two stored companies.

        The oldest wins, deterministically. The other is left alone rather than
        folded in: merging two established customer records is irreversible and
        would move one company's history into another's, which is a decision for
        a human. What matters here is that the answer never changes between runs.
        """
        shared_phone = f"+9714{unique_digits}"
        older, _ = repo.resolve_business(
            Business(
                name="Tower Clinic A",
                geography="Dubai",
                website=f"https://tower-a-{unique}.ae",
                phone=shared_phone,
            )
        )
        repo.resolve_business(
            Business(
                name="Tower Clinic B",
                geography="Dubai",
                website=f"https://tower-b-{unique}.ae",
                phone=shared_phone,
            )
        )

        landings = {
            repo.resolve_business(
                Business(name="Tower Clinic C", geography="Dubai", phone=shared_phone)
            )[0].id
            for _ in range(3)
        }
        assert landings == {older.id}, "resolution must not depend on row order"

    def test_identity_keys_round_trip(self, repo: OpportunityRepository, unique: str) -> None:
        business, _ = repo.resolve_business(
            Business(name="Keys Clinic", geography="Dubai", website=f"https://keys-{unique}.ae")
        )
        loaded = repo.get_business(business.id)
        assert loaded is not None
        assert f"domain:keys-{unique}.ae" in loaded.identity_keys


class TestConfidenceIsStored:
    def test_confidence_survives_the_round_trip(self, repo: OpportunityRepository) -> None:
        """Scoring depends on it, so a confidence that silently reset to 1.0 on
        reload would turn every stored guess into a stated fact."""
        business, _ = repo.resolve_business(
            Business(name="Confidence Clinic", geography="Dubai", website="https://conf.ae")
        )

        repo.save_finding(
            Finding(
                business_id=business.id,
                kind=FindingKind.SLOW_RESPONSE,
                severity=Severity.MEDIUM,
                statement="The homepage was slow.",
                confidence=0.45,
                evidence=[
                    Evidence(kind=EvidenceKind.TIMING, source="https://conf.ae", detector="website")
                ],
            )
        )
        loaded = repo.list_findings(business.id)
        assert loaded[0].confidence == 0.45
        assert loaded[0].weight == pytest.approx(2.5 * 0.45)
