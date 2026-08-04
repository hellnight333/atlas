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

import pytest

from atlas_kernel import db
from atlas_kernel.opportunity.models import (
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
    Prospect,
    Severity,
)
from atlas_kernel.opportunity.repository import OpportunityRepository


@pytest.fixture(scope="module", autouse=True)
def schema():
    db.init_db()


@pytest.fixture
def repo() -> OpportunityRepository:
    return OpportunityRepository()


def _prospect(name: str = "Al Noor Dental Clinic") -> Prospect:
    return Prospect(
        name=name,
        niche="test-niche",
        geography="United Arab Emirates",
        website="https://clinic.test",
        email="hello@clinic.test",
        source="seed-list",
        metadata={"area": "Jumeirah"},
    )


def _finding(prospect_id: str) -> Finding:
    return Finding(
        prospect_id=prospect_id,
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


class TestProspects:
    def test_round_trip(self, repo: OpportunityRepository) -> None:
        saved = repo.save_prospect(_prospect())
        loaded = repo.get_prospect(saved.id)
        assert loaded is not None
        assert loaded.name == saved.name
        assert loaded.metadata == {"area": "Jumeirah"}

    def test_saving_twice_updates_rather_than_duplicating(
        self, repo: OpportunityRepository
    ) -> None:
        prospect = repo.save_prospect(_prospect())
        repo.save_prospect(prospect.model_copy(update={"email": "new@clinic.test"}))
        loaded = repo.get_prospect(prospect.id)
        assert loaded is not None and loaded.email == "new@clinic.test"

    def test_unknown_prospect_is_none(self, repo: OpportunityRepository) -> None:
        assert repo.get_prospect("does-not-exist") is None


class TestFindings:
    def test_evidence_survives_the_round_trip(self, repo: OpportunityRepository) -> None:
        """Evidence that does not come back intact cannot be re-checked, which
        would leave a claim standing on nothing."""
        prospect = repo.save_prospect(_prospect())
        finding = repo.save_finding(_finding(prospect.id))
        loaded = repo.list_findings(prospect.id)
        assert len(loaded) == 1
        assert loaded[0].evidence[0].observed == {"title": None}
        assert loaded[0].evidence[0].detector == "website"
        assert loaded[0].fingerprint == finding.fingerprint

    def test_saving_an_opportunity_saves_its_findings(self, repo: OpportunityRepository) -> None:
        prospect = repo.save_prospect(_prospect())
        opportunity = Opportunity(
            prospect_id=prospect.id,
            niche="test-niche",
            findings=[_finding(prospect.id)],
            stage=OpportunityStage.QUALIFIED,
            score=5.0,
        )
        repo.save_opportunity(opportunity)
        assert len(repo.list_findings(prospect.id)) == 1


class TestProposalsAndMessages:
    def test_a_proposal_round_trips_with_its_citations(self, repo: OpportunityRepository) -> None:
        prospect = repo.save_prospect(_prospect())
        proposal = repo.save_proposal(
            Proposal(
                prospect_id=prospect.id,
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
        prospect = repo.save_prospect(_prospect())
        message = repo.save_message(
            OutreachMessage(
                proposal_id="p1",
                prospect_id=prospect.id,
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
        assert history.last_contacted(prospect.id) is not None


class TestEvents:
    def test_events_are_append_only(self, repo: OpportunityRepository) -> None:
        prospect = repo.save_prospect(_prospect())
        opportunity = Opportunity(prospect_id=prospect.id, niche="event-niche")
        repo.save_opportunity(opportunity)
        for kind in (PipelineEventKind.DISCOVERED, PipelineEventKind.QUALIFIED):
            repo.record_event(
                PipelineEvent(opportunity_id=opportunity.id, prospect_id=prospect.id, kind=kind)
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
        prospect = repo.save_prospect(_prospect())
        repo.record_event(
            PipelineEvent(
                opportunity_id="o1",
                prospect_id=prospect.id,
                kind=PipelineEventKind.SENT,
                detail={"message_id": "recorded-1"},
            )
        )
        stored = [e for e in repo.list_events() if e.prospect_id == prospect.id]
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
        contacted = repo.save_prospect(_prospect("Contacted Business"))
        attempted = repo.save_prospect(_prospect("Failed Business"))

        repo.save_message(
            OutreachMessage(
                proposal_id="p1",
                prospect_id=contacted.id,
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
                prospect_id=attempted.id,
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
