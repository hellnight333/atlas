"""Nothing reaches a stranger without a human, and it stays that way (M014).

These are the tests that make "no spam" a property rather than a promise. Each
guard is proved twice: that it refuses what it should, and that **the channel was
never touched** when it refused. A guard that raises after delivering has already
sent the email.

The last class is the one worth reading. It walks the four ways a message could
plausibly reach a channel without a live human decision behind it, and asserts
each one is closed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from atlas_kernel.approval.models import (
    ApprovalDecision,
    ApprovalDecisionType,
    ApprovalRequest,
    ApprovalState,
)
from atlas_kernel.opportunity.gate import (
    PROPOSAL_FINGERPRINT,
    OutreachGate,
    OutreachNotApproved,
)
from atlas_kernel.opportunity.models import (
    Evidence,
    EvidenceKind,
    Finding,
    FindingKind,
    Opportunity,
    OutreachMessage,
    OutreachStatus,
    Proposal,
    ProposalClaim,
    Prospect,
    Severity,
)
from atlas_kernel.opportunity.outreach import (
    ContactHistory,
    OutreachRefused,
    OutreachService,
    RecordingChannel,
    SuppressionList,
)
from atlas_kernel.opportunity.profiles import EXAMPLE_PROFILE


class ExplodingChannel:
    """Fails the test loudly if a guard lets anything through."""

    name = "exploding"

    def deliver(self, message):  # pragma: no cover - the point is never reaching here
        raise AssertionError(f"a guard let {message.id} through to the channel")


def _prospect() -> Prospect:
    return Prospect(
        name="Al Noor Dental Clinic",
        niche=EXAMPLE_PROFILE.id,
        geography="United Arab Emirates",
        website="https://clinic.test",
        email="hello@clinic.test",
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
                summary="No <title> element.",
                detector="website",
            )
        ],
    )


def _proposal(prospect: Prospect, opportunity: Opportunity, body: str = "Body text") -> Proposal:
    return Proposal(
        prospect_id=prospect.id,
        opportunity_id=opportunity.id,
        subject="Your site has no title",
        body=body,
        claims=[ProposalClaim(finding_id=opportunity.findings[0].id, text="No title.")],
        findings_fingerprint=opportunity.findings_fingerprint,
    )


def _message(prospect: Prospect, proposal: Proposal, **overrides) -> OutreachMessage:
    payload = {
        "proposal_id": proposal.id,
        "prospect_id": prospect.id,
        "channel": "recording",
        "recipient": prospect.email or "",
        "subject": proposal.subject,
        "body": proposal.body,
    }
    payload.update(overrides)
    return OutreachMessage(**payload)


def _approved(fingerprint: str) -> ApprovalRequest:
    return ApprovalRequest(
        title="Contact Al Noor Dental Clinic",
        state=ApprovalState.APPROVED,
        metadata={PROPOSAL_FINGERPRINT: fingerprint},
        decisions=[ApprovalDecision(decision=ApprovalDecisionType.APPROVE, actor="ayoub")],
    )


@pytest.fixture
def scenario():
    prospect = _prospect()
    opportunity = Opportunity(
        prospect_id=prospect.id, niche=EXAMPLE_PROFILE.id, findings=[_finding(prospect.id)]
    )
    proposal = _proposal(prospect, opportunity)
    return prospect, opportunity, proposal


class TestTheGate:
    def test_an_approved_request_produces_a_sendable_message(self, scenario) -> None:
        prospect, _, proposal = scenario
        gate = OutreachGate(approvals=None)  # type: ignore[arg-type]
        authorised = gate.authorise(
            _message(prospect, proposal), _approved(proposal.fingerprint), proposal
        )
        assert authorised.status is OutreachStatus.APPROVED
        assert authorised.approved_fingerprint == proposal.fingerprint

    @pytest.mark.parametrize(
        "state",
        [
            ApprovalState.PENDING,
            ApprovalState.REJECTED,
            ApprovalState.EXPIRED,
            ApprovalState.CANCELLED,
        ],
    )
    def test_anything_short_of_approved_is_refused(self, scenario, state) -> None:
        prospect, _, proposal = scenario
        request = _approved(proposal.fingerprint).model_copy(update={"state": state})
        gate = OutreachGate(approvals=None)  # type: ignore[arg-type]
        with pytest.raises(OutreachNotApproved, match=state.value):
            gate.authorise(_message(prospect, proposal), request, proposal)

    def test_editing_the_proposal_after_approval_voids_it(self, scenario) -> None:
        """The property that makes approving in advance legitimate."""
        prospect, _, proposal = scenario
        approval = _approved(proposal.fingerprint)
        edited = proposal.model_copy(update={"body": "A different pitch entirely"})
        gate = OutreachGate(approvals=None)  # type: ignore[arg-type]
        with pytest.raises(OutreachNotApproved, match="changed after approval"):
            gate.authorise(_message(prospect, edited), approval, edited)

    def test_re_running_a_detector_voids_an_approval(self, scenario) -> None:
        """Approval was granted on a set of facts. Different facts, different
        thing — even if every word of the message is identical."""
        prospect, opportunity, proposal = scenario
        approval = _approved(proposal.fingerprint)

        refreshed = Opportunity(
            prospect_id=prospect.id,
            niche=EXAMPLE_PROFILE.id,
            findings=[
                _finding(prospect.id).model_copy(update={"statement": "The page has no heading."})
            ],
        )
        restated = proposal.model_copy(
            update={"findings_fingerprint": refreshed.findings_fingerprint}
        )
        gate = OutreachGate(approvals=None)  # type: ignore[arg-type]
        with pytest.raises(OutreachNotApproved, match="changed after approval"):
            gate.authorise(_message(prospect, restated), approval, restated)

    def test_an_approval_with_no_fingerprint_is_refused(self, scenario) -> None:
        prospect, _, proposal = scenario
        approval = _approved(proposal.fingerprint).model_copy(update={"metadata": {}})
        gate = OutreachGate(approvals=None)  # type: ignore[arg-type]
        with pytest.raises(OutreachNotApproved, match="records no proposal fingerprint"):
            gate.authorise(_message(prospect, proposal), approval, proposal)


class TestSendGuards:
    def _service(self, channel=None, **kwargs) -> OutreachService:
        return OutreachService(channel or ExplodingChannel(), **kwargs)

    def test_an_unapproved_message_never_reaches_the_channel(self, scenario) -> None:
        prospect, _, proposal = scenario
        with pytest.raises(OutreachRefused, match="not approved"):
            self._service().send(_message(prospect, proposal), proposal, EXAMPLE_PROFILE)

    def test_a_message_claiming_approval_without_a_fingerprint_is_refused(self, scenario) -> None:
        """Status is a field anyone can set. The fingerprint is the thing that
        cannot be forged by flipping a flag."""
        prospect, _, proposal = scenario
        forged = _message(prospect, proposal, status=OutreachStatus.APPROVED)
        with pytest.raises(OutreachRefused, match="no approved fingerprint"):
            self._service().send(forged, proposal, EXAMPLE_PROFILE)

    def test_a_stale_fingerprint_is_caught_at_send_not_only_at_approval(self, scenario) -> None:
        """Belt and braces on purpose: the gate checks at authorisation, and the
        send checks again, because time passes in between."""
        prospect, _, proposal = scenario
        approved = _message(
            prospect,
            proposal,
            status=OutreachStatus.APPROVED,
            approved_fingerprint="something-else",
        )
        with pytest.raises(OutreachRefused, match="changed after approval"):
            self._service().send(approved, proposal, EXAMPLE_PROFILE)

    def test_suppression_added_after_approval_still_stops_the_send(self, scenario) -> None:
        """The ordering that matters. Someone says "never contact me again"
        after approval was granted; every approved message to them must die."""
        prospect, _, proposal = scenario
        approved = _message(
            prospect,
            proposal,
            status=OutreachStatus.APPROVED,
            approved_fingerprint=proposal.fingerprint,
        )
        service = self._service(suppression=SuppressionList(["hello@clinic.test"]))
        with pytest.raises(OutreachRefused, match="suppression list"):
            service.send(approved, proposal, EXAMPLE_PROFILE)

    def test_suppressing_a_domain_covers_their_colleagues(self, scenario) -> None:
        prospect, _, proposal = scenario
        approved = _message(
            prospect,
            proposal,
            status=OutreachStatus.APPROVED,
            approved_fingerprint=proposal.fingerprint,
            recipient="someone.else@clinic.test",
        )
        service = self._service(suppression=SuppressionList(["@clinic.test"]))
        with pytest.raises(OutreachRefused, match="suppression list"):
            service.send(approved, proposal, EXAMPLE_PROFILE)

    def test_a_prospect_inside_the_cooldown_is_not_contacted_again(self, scenario) -> None:
        prospect, _, proposal = scenario
        approved = _message(
            prospect,
            proposal,
            status=OutreachStatus.APPROVED,
            approved_fingerprint=proposal.fingerprint,
        )
        history = ContactHistory({prospect.id: datetime.now(UTC) - timedelta(days=10)})
        service = self._service(history=history)
        with pytest.raises(OutreachRefused, match="cooldown"):
            service.send(approved, proposal, EXAMPLE_PROFILE)

    def test_past_the_cooldown_it_sends(self, scenario) -> None:
        prospect, _, proposal = scenario
        approved = _message(
            prospect,
            proposal,
            status=OutreachStatus.APPROVED,
            approved_fingerprint=proposal.fingerprint,
        )
        channel = RecordingChannel()
        elapsed = EXAMPLE_PROFILE.contact_cooldown_days + 1
        service = OutreachService(
            channel,
            history=ContactHistory({prospect.id: datetime.now(UTC) - timedelta(days=elapsed)}),
        )
        sent = service.send(approved, proposal, EXAMPLE_PROFILE)
        assert sent.status is OutreachStatus.SENT
        assert len(channel.delivered) == 1


class TestSending:
    def test_a_clean_send_records_what_happened(self, scenario) -> None:
        prospect, _, proposal = scenario
        approved = _message(
            prospect,
            proposal,
            status=OutreachStatus.APPROVED,
            approved_fingerprint=proposal.fingerprint,
        )
        channel = RecordingChannel()
        service = OutreachService(channel)
        sent = service.send(approved, proposal, EXAMPLE_PROFILE)

        assert sent.status is OutreachStatus.SENT
        assert sent.sent_at is not None
        assert sent.provider_message_id == "recorded-1"
        assert channel.delivered[0].body == proposal.body

    def test_the_recording_channel_says_it_did_not_deliver(self, scenario) -> None:
        """Atlas has no sending identity yet. The pipeline runs end to end, and
        the output says plainly that nothing left the building."""
        prospect, _, proposal = scenario
        approved = _message(
            prospect,
            proposal,
            status=OutreachStatus.APPROVED,
            approved_fingerprint=proposal.fingerprint,
        )
        sent = OutreachService(RecordingChannel()).send(approved, proposal, EXAMPLE_PROFILE)
        assert "not delivered" in (sent.detail or "")

    def test_sending_starts_the_cooldown(self, scenario) -> None:
        prospect, _, proposal = scenario
        approved = _message(
            prospect,
            proposal,
            status=OutreachStatus.APPROVED,
            approved_fingerprint=proposal.fingerprint,
        )
        service = OutreachService(RecordingChannel())
        service.send(approved, proposal, EXAMPLE_PROFILE)
        assert service.history.within_cooldown(prospect.id, EXAMPLE_PROFILE.contact_cooldown_days)

    def test_a_channel_failure_is_recorded_rather_than_raised(self, scenario) -> None:
        """A provider outage is data about a message, not a crash — and the
        detail must never be silently empty on failure."""
        prospect, _, proposal = scenario

        class Failing:
            name = "failing"

            def deliver(self, message):
                raise RuntimeError("smtp refused connection")

        approved = _message(
            prospect,
            proposal,
            status=OutreachStatus.APPROVED,
            approved_fingerprint=proposal.fingerprint,
        )
        result = OutreachService(Failing()).send(approved, proposal, EXAMPLE_PROFILE)
        assert result.status is OutreachStatus.FAILED
        assert "smtp refused connection" in (result.detail or "")

    def test_a_failed_send_does_not_start_the_cooldown(self, scenario) -> None:
        """Otherwise one SMTP outage silences a prospect for three months."""
        prospect, _, proposal = scenario

        class Failing:
            name = "failing"

            def deliver(self, message):
                raise RuntimeError("smtp refused connection")

        approved = _message(
            prospect,
            proposal,
            status=OutreachStatus.APPROVED,
            approved_fingerprint=proposal.fingerprint,
        )
        service = OutreachService(Failing())
        service.send(approved, proposal, EXAMPLE_PROFILE)
        assert service.history.last_contacted(prospect.id) is None


class TestSuppressionList:
    def test_it_matches_addresses_and_domains_case_insensitively(self) -> None:
        suppression = SuppressionList(["Hello@Clinic.test", "@Blocked.test", "other.test"])
        assert suppression.contains("hello@clinic.test")
        assert suppression.contains("ANYONE@blocked.test")
        assert suppression.contains("someone@other.test")
        assert not suppression.contains("hello@allowed.test")

    def test_blank_entries_are_ignored_rather_than_suppressing_everything(self) -> None:
        suppression = SuppressionList(["", "   "])
        assert len(suppression) == 0
        assert not suppression.contains("anyone@anywhere.test")
