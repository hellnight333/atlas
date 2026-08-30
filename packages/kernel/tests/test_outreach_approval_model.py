"""One canonical approval for automated delivery, and one that is not it.

Two approvals exist in this system and they authorise different actors:

    APPROVED_FOR_MANUAL_SEND   a person may send these words themselves
    APPROVED + authorized_automated_at + fingerprint
                               Qevik may deliver this exact artefact

The second is the canonical automated authorisation. It binds to
`Proposal.fingerprint` -- subject, body, offer, price, findings fingerprint and
claims -- so "what was approved" and "what will be sent" cannot drift apart.

These tests exist because the failure they prevent is silent: a message approved
for a human to send by hand, delivered unattended by a machine, on the strength
of a status column that meant something different when it was written.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from atlas_kernel.opportunity.models import (
    Business,
    Evidence,
    EvidenceKind,
    Finding,
    FindingKind,
    Opportunity,
    OutreachMessage,
    OutreachStatus,
    Proposal,
    ProposalClaim,
    Severity,
)
from atlas_kernel.opportunity.outreach import (
    OutreachRefused,
    OutreachService,
)
from atlas_kernel.opportunity.profiles import EXAMPLE_PROFILE


class ExplodingChannel:
    """Fails loudly if any guard lets something through to delivery."""

    name = "exploding"

    def deliver(self, message):  # pragma: no cover - reaching here is the failure
        raise AssertionError(f"a guard let {message.id} through to the channel")


def _business() -> Business:
    return Business(name="Al Noor Dental Clinic", geography="United Arab Emirates",
                    website="https://clinic.test", email="hello@clinic.test")


def _opportunity(business: Business) -> Opportunity:
    finding = Finding(
        business_id=business.id, kind=FindingKind.MISSING_TITLE,
        severity=Severity.HIGH, statement="The page has no title.",
        evidence=[Evidence(kind=EvidenceKind.HTML_CONTENT,
                           source="https://clinic.test",
                           summary="No <title> element.", detector="website")])
    return Opportunity(business_id=business.id, niche=EXAMPLE_PROFILE.id,
                       findings=[finding])


def _proposal(business: Business, opportunity: Opportunity, **over) -> Proposal:
    payload = {
        "business_id": business.id, "opportunity_id": opportunity.id,
        "subject": "Your site has no title", "body": "Body text",
        "claims": [ProposalClaim(finding_id=opportunity.findings[0].id, text="No title.")],
        "findings_fingerprint": opportunity.findings_fingerprint,
    }
    payload.update(over)
    return Proposal(**payload)


def _message(business: Business, proposal: Proposal, **over) -> OutreachMessage:
    payload = {
        "proposal_id": proposal.id, "business_id": business.id, "channel": "email",
        "recipient": business.email or "", "subject": proposal.subject,
        "body": proposal.body,
    }
    payload.update(over)
    return OutreachMessage(**payload)


def _authorised(business: Business, proposal: Proposal, **over) -> OutreachMessage:
    """The canonical automated authorisation: all three parts present."""
    return _message(business, proposal,
                    status=OutreachStatus.APPROVED,
                    approved_fingerprint=proposal.fingerprint,
                    authorized_automated_at=datetime.now(UTC),
                    approval_id="approval-1", **over)


# ============================================ the fingerprint is the proposal's

class TestTheCanonicalFingerprint:
    def test_it_covers_the_words_and_the_facts_beneath_them(self) -> None:
        """Every component the approval is supposed to bind, proved by moving
        each one and watching the fingerprint change."""
        business = _business()
        opportunity = _opportunity(business)
        base = _proposal(business, opportunity)
        original = base.fingerprint

        for field, value in (("subject", "A different subject"),
                             ("body", "Different words entirely"),
                             ("offer", "A free audit"),
                             ("price", 1500.0)):
            moved = base.model_copy(update={field: value})
            assert moved.fingerprint != original, (
                f"editing {field} left the approval fingerprint unchanged")

    def test_it_moves_when_a_claim_changes(self) -> None:
        business = _business()
        opportunity = _opportunity(business)
        base = _proposal(business, opportunity)
        reworded = base.model_copy(update={
            "claims": [ProposalClaim(finding_id=opportunity.findings[0].id,
                                     text="A different claim.")]})
        assert reworded.fingerprint != base.fingerprint

    def test_it_moves_when_the_evidence_underneath_changes(self) -> None:
        """The half a body digest cannot see: re-run a detector and the words
        may be identical while the facts they rest on are not."""
        business = _business()
        base = _proposal(business, _opportunity(business))
        restated = base.model_copy(update={"findings_fingerprint": "a-different-digest"})
        assert restated.fingerprint != base.fingerprint

    def test_a_body_digest_is_not_the_canonical_fingerprint(self) -> None:
        """The legacy manual approval hashes the body alone. It can never equal
        a proposal fingerprint, which is why a manual approval must be refused
        by its own guard rather than by a fingerprint mismatch."""
        import hashlib

        business = _business()
        proposal = _proposal(business, _opportunity(business))
        body_digest = hashlib.sha256(proposal.body.strip().encode("utf-8")).hexdigest()
        assert body_digest != proposal.fingerprint


# ============================================ the three parts of authorisation

class TestAuthorisationIsThreeThings:
    def test_a_fully_authorised_message_reports_itself_so(self) -> None:
        business = _business()
        proposal = _proposal(business, _opportunity(business))
        assert _authorised(business, proposal).authorized_for_automated_send

    @pytest.mark.parametrize("missing", ["status", "authorized_automated_at",
                                         "approved_fingerprint"])
    def test_removing_any_one_of_them_withdraws_authorisation(self, missing: str) -> None:
        business = _business()
        proposal = _proposal(business, _opportunity(business))
        blank = {"status": OutreachStatus.DRAFT,
                 "authorized_automated_at": None,
                 "approved_fingerprint": None}[missing]
        weakened = _authorised(business, proposal).model_copy(update={missing: blank})
        assert not weakened.authorized_for_automated_send

    def test_a_new_message_is_not_authorised(self) -> None:
        business = _business()
        proposal = _proposal(business, _opportunity(business))
        assert not _message(business, proposal).authorized_for_automated_send


# ============================================ manual stays manual

class TestManualApprovalIsNotMachineAuthorisation:
    def test_a_manually_approved_message_is_refused(self) -> None:
        business = _business()
        proposal = _proposal(business, _opportunity(business))
        message = _message(business, proposal,
                           status=OutreachStatus.APPROVED_FOR_MANUAL_SEND,
                           approved_fingerprint="a-body-digest")
        service = OutreachService(ExplodingChannel())
        with pytest.raises(OutreachRefused, match="send by hand"):
            service.send(message, proposal, EXAMPLE_PROFILE)

    def test_the_refusal_names_the_right_reason(self) -> None:
        """Not "the proposal changed" — nothing changed. The decision to let a
        machine send was never taken, and that is what the message must say."""
        business = _business()
        proposal = _proposal(business, _opportunity(business))
        message = _message(business, proposal,
                           status=OutreachStatus.APPROVED_FOR_MANUAL_SEND,
                           approved_fingerprint="a-body-digest")
        with pytest.raises(OutreachRefused) as refused:
            OutreachService(ExplodingChannel()).send(message, proposal, EXAMPLE_PROFILE)
        assert "changed after approval" not in str(refused.value)

    def test_a_legacy_approved_row_without_the_marker_is_refused(self) -> None:
        """The rows that predate automated sending: status APPROVED, a body
        digest, and no authorisation for a machine. They stay valid history and
        stay unsendable, without being edited."""
        business = _business()
        proposal = _proposal(business, _opportunity(business))
        legacy = _message(business, proposal,
                          status=OutreachStatus.APPROVED,
                          approval_id="manual-abc123def456",
                          approved_fingerprint="a-body-digest",
                          authorized_automated_at=None)
        with pytest.raises(OutreachRefused, match="no authorisation for automated"):
            OutreachService(ExplodingChannel()).send(legacy, proposal, EXAMPLE_PROFILE)

    def test_that_refusal_also_avoids_the_misleading_reason(self) -> None:
        business = _business()
        proposal = _proposal(business, _opportunity(business))
        legacy = _message(business, proposal, status=OutreachStatus.APPROVED,
                          approved_fingerprint="a-body-digest")
        with pytest.raises(OutreachRefused) as refused:
            OutreachService(ExplodingChannel()).send(legacy, proposal, EXAMPLE_PROFILE)
        assert "changed after approval" not in str(refused.value), (
            "a legacy approval was reported as an edited proposal")

    def test_the_manual_state_exists_and_is_distinct(self) -> None:
        assert OutreachStatus.APPROVED_FOR_MANUAL_SEND is not OutreachStatus.APPROVED
        assert OutreachStatus.APPROVED_FOR_MANUAL_SEND.value == "approved_for_manual_send"

    def test_the_manual_tool_never_authorises_a_machine(self) -> None:
        """Structural, over the tool itself: `approve_send.py` may record a
        manual approval and must never write the automated marker."""
        from pathlib import Path

        source = Path("infra/approve_send.py").read_text(encoding="utf-8")
        assert "APPROVED_FOR_MANUAL_SEND" in source
        assert "OutreachStatus.APPROVED," not in source, (
            "the manual tool sets the automated-eligible status")
        assert '"authorized_automated_at": None' in source


# ============================================ the authorised path still guards

class TestAuthorisedStillMeansChecked:
    def test_an_authorised_message_whose_proposal_moved_is_refused(self) -> None:
        business = _business()
        opportunity = _opportunity(business)
        proposal = _proposal(business, opportunity)
        message = _authorised(business, proposal)
        edited = proposal.model_copy(update={"body": "Different words entirely"})
        with pytest.raises(OutreachRefused, match="changed after approval"):
            OutreachService(ExplodingChannel()).send(message, edited, EXAMPLE_PROFILE)

    def test_authorisation_does_not_skip_the_fingerprint(self) -> None:
        """Belt and braces: the marker says a decision of the right kind exists,
        never that the words are still the ones it covered."""
        business = _business()
        proposal = _proposal(business, _opportunity(business))
        message = _authorised(business, proposal).model_copy(
            update={"approved_fingerprint": "something-else"})
        with pytest.raises(OutreachRefused, match="changed after approval"):
            OutreachService(ExplodingChannel()).send(message, proposal, EXAMPLE_PROFILE)


# ============================================ the six states

class TestTheStateModel:
    def test_every_state_the_lifecycle_needs_exists(self) -> None:
        values = {status.value for status in OutreachStatus}
        assert {"draft", "approved_for_manual_send", "approved",
                "sent", "failed", "suppressed"} <= values

    def test_a_status_alone_never_grants_automated_delivery(self) -> None:
        """The property that keeps history safe: no status, on its own, makes a
        message sendable by a machine."""
        business = _business()
        proposal = _proposal(business, _opportunity(business))
        for status in OutreachStatus:
            message = _message(business, proposal, status=status,
                               approved_fingerprint=proposal.fingerprint)
            assert not message.authorized_for_automated_send, (
                f"{status.value} granted automated delivery without an explicit "
                "authorisation")
