"""The channel seam: correct shape, no capability, and Qevik is not a company.

Two separate concerns, both of which fail quietly if untested.

A channel that cannot send is easy to write and easy to accidentally complete —
someone adds a client "to test locally" and the architecture becomes a sender.
These tests assert the absence of capability structurally, not by checking a
flag, because a flag is exactly what would get flipped.

And Qevik is a brand operated by Asia Link Internet Content Provider LLC. Writing
"Qevik LLC" to a UAE business is a false claim about a regulated status, made to
someone who can look it up.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas_kernel.outreach import (
    BRAND_LINE,
    EMAIL_SIGNATURE,
    LEGAL_ENTITY,
    NAME,
    PHONE,
    WHATSAPP_SIGNATURE,
    ChannelNotConnected,
    EmailChannel,
    NotApproved,
    NotReachable,
    WhatsAppChannel,
    connected,
    entity_claims,
    registry,
)


class Approved:
    approved = True


class TestNothingCanSend:
    def test_no_channel_is_connected(self) -> None:
        assert connected() == []
        assert all(not c.configured() for c in registry().values())

    def test_no_provider_client_is_imported_anywhere_in_the_package(self) -> None:
        """Structural, because a flag is what gets flipped.

        If any of these appear, the architecture stopped being an architecture.
        """
        import atlas_kernel.outreach as package

        root = Path(package.__file__).parent
        forbidden = ("smtplib", "twilio", "sendgrid", "httpx", "requests", "aiohttp")
        for source in root.glob("*.py"):
            text = source.read_text(encoding="utf-8")
            for name in forbidden:
                assert f"import {name}" not in text, f"{source.name} imports {name}"

    def test_an_approved_reachable_send_still_refuses(self) -> None:
        """The last line. Everything correct, and it still cannot deliver."""
        with pytest.raises(ChannelNotConnected, match="deliberate"):
            EmailChannel().send(
                recipient="clinic@example.com", subject="s", body="b", approval=Approved()
            )
        with pytest.raises(ChannelNotConnected):
            WhatsAppChannel().send(
                recipient="0501234567", subject="", body="b", approval=Approved()
            )


class TestReachability:
    """The half that works today, and the one that matters most.

    Sixteen of the twenty audited clinics publish a landline. A WhatsApp message
    to one is not an error — it is silence.
    """

    @pytest.mark.parametrize("number", ["0501234567", "0521514300", "971582256900"])
    def test_a_uae_mobile_is_reachable(self, number: str) -> None:
        assert WhatsAppChannel().can_reach(number)

    @pytest.mark.parametrize("number", ["043558808", "80037569", "97143474339", ""])
    def test_a_landline_or_toll_free_is_not(self, number: str) -> None:
        assert not WhatsAppChannel().can_reach(number)

    def test_whatsapp_to_a_landline_is_refused_before_the_connection_check(self) -> None:
        """Reachability first, on purpose.

        "That number cannot receive WhatsApp" stays true after a provider is
        added. Learning it now is worth more than learning it on send day.
        """
        with pytest.raises(NotReachable):
            WhatsAppChannel().send(
                recipient="043558808", subject="", body="b", approval=Approved()
            )

    def test_a_malformed_email_is_refused(self) -> None:
        with pytest.raises(NotReachable):
            EmailChannel().send(recipient="not-an-address", subject="s", body="b", approval=Approved())


class TestApproval:
    def test_a_send_without_approval_is_refused(self) -> None:
        for approval in (None, object()):
            with pytest.raises(NotApproved):
                EmailChannel().send(
                    recipient="clinic@example.com", subject="s", body="b", approval=approval
                )


class TestQevikIsNotACompany:
    """It is a brand operated by Asia Link Internet Content Provider LLC."""

    @pytest.mark.parametrize(
        "text",
        [
            "Sent on behalf of Qevik LLC",
            "Qevik FZ-LLC, Dubai",
            "Qevik FZCO",
            "Qevik is a licensed Dubai company",
            "Qevik is a registered UAE business",
            "Qevik's trade licence number is 12345",
            "registered as Qevik in the UAE",
        ],
    )
    def test_a_legal_entity_claim_is_caught(self, text: str) -> None:
        assert entity_claims(text), f"{text!r} passed"

    @pytest.mark.parametrize(
        "text",
        [
            "Qevik — by Asia Link Internet Content Provider LLC",
            "I build websites under the Qevik name.",
            "Qevik is the product I work on.",
        ],
    )
    def test_honest_phrasing_is_not_caught(self, text: str) -> None:
        """A guard that fires on every mention of the brand gets switched off."""
        assert entity_claims(text) == []

    def test_the_email_signature_names_the_licensed_entity(self) -> None:
        assert LEGAL_ENTITY in EMAIL_SIGNATURE
        assert BRAND_LINE in EMAIL_SIGNATURE
        assert NAME in EMAIL_SIGNATURE and PHONE in EMAIL_SIGNATURE
        assert entity_claims(EMAIL_SIGNATURE) == []

    def test_the_whatsapp_signature_is_short_and_still_honest(self) -> None:
        assert NAME in WHATSAPP_SIGNATURE and PHONE in WHATSAPP_SIGNATURE
        # No postal address — it reads as a mail-merge on a phone.
        assert "Office 301" not in WHATSAPP_SIGNATURE
        assert entity_claims(WHATSAPP_SIGNATURE) == []
