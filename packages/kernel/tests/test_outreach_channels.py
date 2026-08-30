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

from atlas_kernel.outreach import channels
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


#: A complete, obviously-fake SMTP configuration. Present so the connected path
#: can be exercised; no value here can reach a real server.
_SMTP_ENV = {
    "QEVIK_SMTP_HOST": "smtp.invalid",
    "QEVIK_SMTP_PORT": "587",
    "QEVIK_SMTP_USER": "nobody@example.invalid",
    "QEVIK_SMTP_PASSWORD": "not-a-real-password",
    "QEVIK_SMTP_FROM": "nobody@example.invalid",
}


class TestNothingCanSend:
    def test_no_channel_is_connected(self) -> None:
        assert connected() == []
        assert all(not c.configured() for c in registry().values())

    def test_no_unauthorised_provider_client_enters_the_package(self) -> None:
        """Structural, because a flag is what gets flipped.

        The guard is unchanged in purpose: no provider integration enters the
        outreach architecture without being an explicit, reviewable decision.

        Its contract narrowed once, at M1, when sending email stopped being
        withheld and became an approved capability. `smtplib` is therefore
        permitted in **`channels.py` and nowhere else** — every other provider
        stays forbidden everywhere, and `smtplib` itself stays forbidden in
        every other file in the package.

        The exception is deliberately as small as the decision that caused it.
        WhatsApp is not part of M1 and no client for it may appear.
        """
        import atlas_kernel.outreach as package

        root = Path(package.__file__).parent
        #: Never, in any file. Adding one is a decision nobody has taken.
        forbidden_everywhere = ("twilio", "sendgrid", "httpx", "requests", "aiohttp")
        #: Permitted only where the approved capability lives.
        allowed_in = {"smtplib": "channels.py"}

        for source in root.glob("*.py"):
            text = source.read_text(encoding="utf-8")
            for name in forbidden_everywhere:
                assert f"import {name}" not in text, (
                    f"{source.name} imports {name}; no provider client may enter "
                    "the outreach package without an explicit decision")
            for name, permitted_file in allowed_in.items():
                if source.name != permitted_file:
                    assert f"import {name}" not in text, (
                        f"{source.name} imports {name}, which is permitted only "
                        f"in {permitted_file}")

    def test_the_narrowed_guard_still_has_teeth(self) -> None:
        """A guard that permits everything is a guard nobody notices failing."""
        import atlas_kernel.outreach as package

        root = Path(package.__file__).parent
        sources = {s.name for s in root.glob("*.py")}
        assert "channels.py" in sources, "the permitted file must exist"
        # The exception is one file and one module, not a category.
        assert len({"smtplib"}) == 1
        for other in sources - {"channels.py"}:
            text = (root / other).read_text(encoding="utf-8")
            assert "import smtplib" not in text

    def test_email_without_a_credential_still_refuses(self, monkeypatch) -> None:
        """M1 connected email. It did not make email unconditional.

        With no credential the refusal is unchanged: an unconfigured channel
        must fail loudly rather than appear to succeed.
        """
        for var in channels.SMTP_SETTINGS:
            monkeypatch.delenv(var, raising=False)
        assert not EmailChannel().configured()
        with pytest.raises(ChannelNotConnected):
            EmailChannel().send(
                recipient="clinic@example.com", subject="s", body="b", approval=Approved()
            )

    def test_whatsapp_still_cannot_send_at_all(self) -> None:
        """Unchanged, and asserted separately so it cannot ride on email's coat
        tails. WhatsApp is not part of M1; no provider exists for it."""
        with pytest.raises(ChannelNotConnected, match="deliberate"):
            WhatsAppChannel().send(
                recipient="0501234567", subject="", body="b", approval=Approved()
            )

    def test_a_configured_email_channel_passes_the_connection_gate(
            self, monkeypatch) -> None:
        """The M1 contract, proven without sending anything.

        `smtplib.SMTP` is replaced, so the real code path runs -- gates,
        header construction, transport call -- and no packet leaves the machine.
        """
        sent: list = []

        class FakeSMTP:
            def __init__(self, host, port, timeout=None):
                sent.append(("connect", host, port))

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def starttls(self, context=None):
                sent.append(("starttls",))

            def login(self, user, password):
                sent.append(("login", user))

            def send_message(self, message):
                sent.append(("send", message["To"], message["Subject"]))

        for var, value in _SMTP_ENV.items():
            monkeypatch.setenv(var, value)
        monkeypatch.setattr(channels.smtplib, "SMTP", FakeSMTP)

        assert EmailChannel().configured()
        result = EmailChannel().send(
            recipient="clinic@example.com", subject="s", body="b",
            approval=Approved())

        assert [step[0] for step in sent] == ["connect", "starttls", "login", "send"]
        assert result.channel == "email"
        assert result.recipient == "clinic@example.com"
        assert result.provider_message_id, "a send must return a Message-ID"


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
