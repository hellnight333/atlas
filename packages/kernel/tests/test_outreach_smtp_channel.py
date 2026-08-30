"""The canonical send path, connected to a real transport and still guarded.

`OutreachService.send` is the only path to a channel. These tests prove that
connecting SMTP to it did not create a second one, and did not move any policy
out of the service and into the transport.

Nothing here sends. `smtplib.SMTP` is replaced in every test that reaches the
transport, so the real code path runs and no packet leaves the machine.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

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
    ContactHistory,
    OutreachChannel,
    OutreachRefused,
    OutreachService,
    SuppressionList,
)
from atlas_kernel.opportunity.profiles import EXAMPLE_PROFILE
from atlas_kernel.outreach import channels
from atlas_kernel.outreach.channels import ChannelNotConnected, EmailChannel
from atlas_kernel.outreach.smtp_channel import SmtpOutreachChannel

SMTP_ENV = {
    "QEVIK_SMTP_HOST": "smtp.invalid",
    "QEVIK_SMTP_PORT": "587",
    "QEVIK_SMTP_USER": "nobody@example.invalid",
    "QEVIK_SMTP_PASSWORD": "not-a-real-password",
    "QEVIK_SMTP_FROM": "nobody@example.invalid",
}


class Recorder:
    """Stands in for smtplib.SMTP. Records, never connects."""

    steps: list = []

    def __init__(self, host, port, timeout=None):
        Recorder.steps.append(("connect", host, port))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        Recorder.steps.append(("starttls",))

    def login(self, user, password):
        Recorder.steps.append(("login", user))

    def send_message(self, message):
        Recorder.steps.append(("send", message))


@pytest.fixture
def wire(monkeypatch):
    """A configured transport whose SMTP layer is replaced."""
    Recorder.steps = []
    channels._ALREADY_SENT.clear()
    for name, value in SMTP_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(channels.smtplib, "SMTP", Recorder)
    yield Recorder
    channels._ALREADY_SENT.clear()


@pytest.fixture
def unconfigured(monkeypatch):
    for name in channels.SMTP_SETTINGS:
        monkeypatch.delenv(name, raising=False)
    channels._ALREADY_SENT.clear()
    yield
    channels._ALREADY_SENT.clear()


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


def _proposal(business: Business, opportunity: Opportunity) -> Proposal:
    return Proposal(
        business_id=business.id, opportunity_id=opportunity.id,
        subject="Your site has no title", body="Body text",
        claims=[ProposalClaim(finding_id=opportunity.findings[0].id, text="No title.")],
        findings_fingerprint=opportunity.findings_fingerprint)


def _approved_message(business: Business, proposal: Proposal, **over) -> OutreachMessage:
    payload = {
        "proposal_id": proposal.id, "business_id": business.id, "channel": "email",
        "recipient": business.email or "", "subject": proposal.subject,
        "body": proposal.body, "status": OutreachStatus.APPROVED,
        "approved_fingerprint": proposal.fingerprint, "approval_id": "approval-1",
        # What the gate writes when a person authorises automated delivery.
        # Without it the message is approved for a human to send by hand, and
        # `OutreachService` refuses it — which is the distinction this whole
        # model exists to hold.
        "authorized_automated_at": datetime.now(UTC),
    }
    payload.update(over)
    return OutreachMessage(**payload)


def _service(**kwargs) -> OutreachService:
    return OutreachService(SmtpOutreachChannel(), **kwargs)


# ============================================ the adapter is the shape B wants

class TestTheAdapterIsAChannelAndNothingMore:
    def test_it_satisfies_the_channel_protocol(self) -> None:
        assert isinstance(SmtpOutreachChannel(), OutreachChannel)

    def test_it_reports_the_email_channel_name(self) -> None:
        assert SmtpOutreachChannel().name == "email"

    def test_it_holds_no_policy_of_its_own(self) -> None:
        """Structural. B's protocol says a channel must not validate, and the
        way that rule dies is a well-meaning check added to one adapter."""
        from pathlib import Path

        import atlas_kernel.outreach.smtp_channel as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        body = source.split('"""', 2)[-1]  # past the module docstring
        for forbidden in ("within_cooldown", "OutreachStatus.APPROVED",
                          "SuppressionList", "fingerprint =="):
            assert forbidden not in body, (
                f"the adapter references {forbidden!r}; policy belongs in "
                "OutreachService, which already checks it")

    def test_it_does_not_construct_its_own_transport_when_given_one(self) -> None:
        sentinel = object()
        assert SmtpOutreachChannel(sentinel)._transport is sentinel


# ============================================ 1. unconfigured cannot send

class TestUnconfigured:
    def test_the_adapter_reports_itself_unconfigured(self, unconfigured) -> None:
        assert SmtpOutreachChannel().configured is False

    def test_the_canonical_path_refuses_and_records_the_failure(self, unconfigured) -> None:
        """`OutreachService` turns a channel failure into FAILED with a reason,
        rather than letting it escape as a crash."""
        business = _business()
        proposal = _proposal(business, _opportunity(business))
        result = _service().send(_approved_message(business, proposal),
                                 proposal, EXAMPLE_PROFILE)
        assert result.status is OutreachStatus.FAILED
        assert result.detail and "not configured" in result.detail
        assert result.sent_at is None


# ============================================ 2-4. the guards still guard

class TestTheGuardsAreUnmoved:
    def test_suppression_blocks_before_the_transport(self, wire) -> None:
        business = _business()
        proposal = _proposal(business, _opportunity(business))
        service = _service(suppression=SuppressionList([business.email or ""]))
        with pytest.raises(OutreachRefused, match="suppress"):
            service.send(_approved_message(business, proposal), proposal, EXAMPLE_PROFILE)
        assert wire.steps == [], "a suppressed message reached the transport"

    def test_cooldown_blocks_before_the_transport(self, wire) -> None:
        business = _business()
        proposal = _proposal(business, _opportunity(business))
        history = ContactHistory()
        history.record(business.id, datetime.now(UTC) - timedelta(days=1))
        with pytest.raises(OutreachRefused, match="cooldown"):
            _service(history=history).send(_approved_message(business, proposal),
                                           proposal, EXAMPLE_PROFILE)
        assert wire.steps == [], "a cooled-down message reached the transport"

    def test_an_unapproved_message_never_reaches_the_transport(self, wire) -> None:
        business = _business()
        proposal = _proposal(business, _opportunity(business))
        message = _approved_message(business, proposal, status=OutreachStatus.DRAFT)
        with pytest.raises(OutreachRefused, match="not approved"):
            _service().send(message, proposal, EXAMPLE_PROFILE)
        assert wire.steps == []

    def test_an_edited_proposal_invalidates_the_approval(self, wire) -> None:
        """The binding that matters: consent was to those words."""
        business = _business()
        opportunity = _opportunity(business)
        proposal = _proposal(business, opportunity)
        message = _approved_message(business, proposal)
        edited = proposal.model_copy(update={"body": "Different words entirely"})
        with pytest.raises(OutreachRefused, match="changed after approval"):
            _service().send(message, edited, EXAMPLE_PROFILE)
        assert wire.steps == []


# ============================================ 5-8. the happy path

class TestTheCanonicalPathDelivers:
    def test_it_reaches_the_transport_and_records_the_send(self, wire) -> None:
        business = _business()
        proposal = _proposal(business, _opportunity(business))
        result = _service().send(_approved_message(business, proposal),
                                 proposal, EXAMPLE_PROFILE)

        assert [step[0] for step in wire.steps] == [
            "connect", "starttls", "login", "send"]
        assert result.status is OutreachStatus.SENT
        assert result.sent_at is not None
        assert result.provider_message_id, "the Message-ID must be recorded"

    def test_the_exact_approved_words_are_what_is_delivered(self, wire) -> None:
        business = _business()
        proposal = _proposal(business, _opportunity(business))
        message = _approved_message(business, proposal)
        _service().send(message, proposal, EXAMPLE_PROFILE)

        delivered = wire.steps[-1][1]
        assert delivered["To"] == message.recipient
        assert delivered["Subject"] == message.subject
        assert delivered.get_content().strip() == message.body.strip()

    def test_the_message_id_is_domained_to_qevik(self, wire) -> None:
        business = _business()
        proposal = _proposal(business, _opportunity(business))
        result = _service().send(_approved_message(business, proposal),
                                 proposal, EXAMPLE_PROFILE)
        assert result.provider_message_id.endswith("@qevik.ai>")


# ============================================ 6. duplicates

class TestDuplicateProtection:
    def test_a_second_send_of_a_sent_message_is_refused(self, wire) -> None:
        """The durable guard: once sent, the status is no longer APPROVED."""
        business = _business()
        proposal = _proposal(business, _opportunity(business))
        sent = _service().send(_approved_message(business, proposal),
                               proposal, EXAMPLE_PROFILE)
        with pytest.raises(OutreachRefused, match="not approved"):
            _service().send(sent, proposal, EXAMPLE_PROFILE)

    def test_the_transport_refuses_an_identical_repeat_too(self, wire) -> None:
        """Belt and braces: even resubmitting the same approved record, the
        transport's own guard stops the same words going twice."""
        business = _business()
        proposal = _proposal(business, _opportunity(business))
        message = _approved_message(business, proposal)
        first = _service().send(message, proposal, EXAMPLE_PROFILE)
        assert first.status is OutreachStatus.SENT

        # The same approved record again, as though the first had not happened.
        repeat = _service().send(message, proposal, EXAMPLE_PROFILE)
        assert repeat.status is OutreachStatus.FAILED
        assert "already" in (repeat.detail or "").lower()


# ============================================ 9-10. nothing else became a path

class TestNoSecondProductionPath:
    def test_smtp_is_not_a_dispatchable_mission_tool(self) -> None:
        from atlas_kernel.mission.toolrunner import DISPATCHABLE

        assert "smtp" not in DISPATCHABLE
        # Not vacuous: the tools that are dispatchable still are.
        assert {"site-publish", "http-fetch"} <= set(DISPATCHABLE)

    def test_the_mission_side_transport_is_not_wired_to_a_surface(self) -> None:
        """`EmailChannel` remains reachable only as a transport.

        If a route or command ever constructs it directly, outreach policy is
        being bypassed -- suppression and cooldown live in `OutreachService`,
        and nothing else consults them.
        """
        from pathlib import Path

        import atlas_kernel

        root = Path(atlas_kernel.__file__).parent
        allowed = {"channels.py", "smtp_channel.py", "preparation.py"}
        callers = [
            str(path.relative_to(root))
            for path in root.rglob("*.py")
            if path.name not in allowed
            and "EmailChannel(" in path.read_text(encoding="utf-8", errors="ignore")
        ]
        assert callers == [], (
            f"{callers} construct EmailChannel directly; the canonical path is "
            "OutreachService.send -> SmtpOutreachChannel")

    def test_whatsapp_is_still_unconnected(self) -> None:
        from atlas_kernel.outreach.channels import WhatsAppChannel

        class Approved:
            approved = True

        with pytest.raises(ChannelNotConnected):
            WhatsAppChannel().send(recipient="0501234567", subject="", body="b",
                                   approval=Approved())

    def test_the_transport_still_refuses_without_a_credential(self, unconfigured) -> None:
        class Approved:
            approved = True

        with pytest.raises(ChannelNotConnected):
            EmailChannel().send(recipient="a@b.co", subject="s", body="b",
                                approval=Approved())
