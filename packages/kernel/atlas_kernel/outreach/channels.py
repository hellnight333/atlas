"""Where email and WhatsApp will attach, and why neither can send today.

The instruction is to prepare the architecture without connecting it. That is a
sharper requirement than it sounds: the usual way to "prepare" a sender is to
write the client and leave a flag off, which produces a system that is one
truthy value away from messaging twenty real businesses.

So this defines the *shape* and withholds the capability until a decision is
taken to grant it. **Email was granted at M1 and is the only channel that was.**
WhatsApp still raises `ChannelNotConnected`, and no HTTP client or provider SDK
is imported here — adding one remains a visible, reviewable diff rather than a
config change.

Email is granted through `smtplib` alone: the standard library, no account with
a third party, no SDK, nothing that can quietly gain features. The structural
guard in `test_outreach_channels.py` narrowed by exactly this much and no more.

What a channel must satisfy before it may ever send, encoded in `send`:

1. **It is configured.** A channel with no credential refuses rather than
   pretending to succeed.
2. **The recipient is reachable on that channel.** WhatsApp to a landline is a
   message that silently goes nowhere, which is worse than an error — this is
   the same fault the generated sites refuse to reproduce.
3. **An approval exists, bound to this exact message.** Not "sending is enabled"
   — consent to *these words to this recipient*, so an edit invalidates it.
4. **The message has not already been sent.** Re-sending on a retry is how one
   approval becomes three messages to the same person.

`SendResult` is what a connected channel would return. It exists now so that the
record shape does not change on the day a provider is added.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Any, Protocol

log = logging.getLogger(__name__)

#: Everything an email identity needs before this channel may send. All of them
#: or none: a partially configured sender is the state that produces a
#: half-authenticated message which the recipient's provider silently files as
#: spam, and nobody learns why.
#:
#: `QEVIK_SMTP_PASSWORD` is the id the integrations registry already uses. The
#: others are named beside it rather than in a second place.
SMTP_SETTINGS: tuple[str, ...] = (
    "QEVIK_SMTP_HOST",
    "QEVIK_SMTP_PORT",
    "QEVIK_SMTP_USER",
    "QEVIK_SMTP_PASSWORD",
    "QEVIK_SMTP_FROM",
)

#: The domain the Message-ID is built from.
#:
#: `make_msgid()` defaults to the *machine's* hostname, which on the production
#: host produced `<...@1.0.0.0.0...ip6.arpa>` -- a Message-ID whose domain has
#: nothing to do with the sender. It affects neither SPF, DKIM nor DMARC, and
#: some filters still read the mismatch as a weak signal on a domain with no
#: sending history, which is exactly what qevik.ai is.
#:
#: A constant rather than a value read from `QEVIK_SMTP_FROM`: deriving it would
#: keep the two aligned automatically if the sending identity ever changed, and
#: is the better long-term shape, but it is more than this fix needs today.
MESSAGE_ID_DOMAIN = "qevik.ai"

#: Sends this process has already made, keyed by what identifies a message.
#:
#: Best effort and deliberately in memory: the durable record of a send is the
#: `SENT` transition the caller writes, and this is the backstop that stops an
#: immediate retry inside one process becoming a second message to a stranger.
#: A caller that persists `sent_message_id` on its approval gets the durable
#: half; nothing here invents storage to do it for them.
_ALREADY_SENT: set[tuple[str, str, str]] = set()

#: A UAE mobile. The only kind of number WhatsApp can deliver to.
UAE_MOBILE = re.compile(r"^(?:971)?0?5[024568]\d{7}$")

#: Deliberately permissive — enough to catch an obviously malformed address
#: without pretending to validate deliverability, which only a send can do.
EMAIL_SHAPE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class OutreachError(RuntimeError):
    """Base for everything in this module."""


class ChannelNotConnected(OutreachError):
    """No provider is wired for this channel. The current state of all of them."""


class NotReachable(OutreachError):
    """The recipient cannot receive on this channel."""


class NotApproved(OutreachError):
    """No approval, or one that does not match this exact message."""


class AlreadySent(OutreachError):
    """This exact message has already gone to this recipient.

    Separate from `NotApproved` because the caller's response differs: an
    unapproved message needs a decision, an already-sent one needs nothing at
    all and must not be retried.
    """


class Unsendable(OutreachError):
    """The message itself cannot safely be put on the wire."""


@dataclass(frozen=True)
class SendResult:
    channel: str
    recipient: str
    provider_message_id: str
    detail: str = ""


class Channel(Protocol):
    """What a sender must provide. Implementations arrive later, one per file."""

    name: str

    def configured(self) -> bool: ...

    def can_reach(self, recipient: str) -> bool: ...

    def send(self, *, recipient: str, subject: str, body: str, approval: Any) -> SendResult: ...


class _Unconnected:
    """Shared refusal logic, so each channel states only what differs.

    The checks run in order and the reachability check runs *before* the
    connection check on purpose: "that number cannot receive WhatsApp" is a fact
    about the recipient that stays true after a provider is added, and finding it
    out now is worth more than finding it out on the day of the first send.
    """

    name = "unconnected"

    def configured(self) -> bool:
        return False

    def can_reach(self, recipient: str) -> bool:  # pragma: no cover - overridden
        return False

    def send(self, *, recipient: str, subject: str, body: str, approval: Any) -> SendResult:
        if not self.can_reach(recipient):
            raise NotReachable(f"{recipient!r} cannot receive on {self.name}")
        if approval is None or not getattr(approval, "approved", False):
            raise NotApproved(
                f"a {self.name} message needs an approval bound to these exact words. "
                "Nothing here creates its own."
            )
        raise ChannelNotConnected(
            f"{self.name} has no provider configured. This is deliberate: the "
            "architecture is in place and the capability is not. Adding one is a "
            "reviewable change, not a setting."
        )


class EmailChannel(_Unconnected):
    """The one connected channel, and only through the standard library.

    Granted at M1 because Qevik had a proven pipeline that ended one step short
    of a person: a website built, reviewed, approved and published, and no way
    to tell the owner it existed.

    What did **not** change when it was granted:

    * the four gates below still run, in the same order, for every send;
    * `smtp` is still absent from `toolrunner.DISPATCHABLE`, so no recipe and no
      mission can send mail — an email leaves this system only when a person
      approved these exact words to this exact recipient;
    * one approval still produces exactly one message.

    An email cannot be unsent. Every refusal here is cheaper than the send it
    prevents.
    """

    name = "email"

    def can_reach(self, recipient: str) -> bool:
        return bool(EMAIL_SHAPE.match((recipient or "").strip()))

    def configured(self) -> bool:
        """All five settings present, or the channel is not connected.

        Presence only. Whether the credential *works* is answered by a send, and
        treating a probe as proof of capability is the error this project
        already made once.
        """
        return all(os.environ.get(name, "").strip() for name in SMTP_SETTINGS)

    def send(self, *, recipient: str, subject: str, body: str,
             approval: Any) -> SendResult:
        """Deliver one approved message to one verified recipient.

        The gates run in the order `_Unconnected` established, so a message that
        would have been refused before M1 for reachability or approval is still
        refused for the same reason and at the same point.
        """
        recipient = (recipient or "").strip()

        # 1. Reachable. First, because it stays true regardless of configuration.
        if not self.can_reach(recipient):
            raise NotReachable(f"{recipient!r} cannot receive on {self.name}")

        # 2. Approved, to these words. An approval that names no message is not
        #    an approval of this one.
        if approval is None or not getattr(approval, "approved", False):
            raise NotApproved(
                f"a {self.name} message needs an approval bound to these exact "
                "words. Nothing here creates its own.")

        # 3. Configured. Unchanged for an unconfigured channel: refuse loudly.
        if not self.configured():
            missing = [n for n in SMTP_SETTINGS if not os.environ.get(n, "").strip()]
            raise ChannelNotConnected(
                f"{self.name} is not configured: {', '.join(missing)} absent. "
                "A partly configured sender is worse than none — it authenticates "
                "badly and the message is filed as spam without an error.")

        # 4. Not already sent. An approval is consent to one message.
        fingerprint = self._fingerprint(recipient, subject, body)
        already = str(getattr(approval, "sent_message_id", "") or "")
        if already:
            raise AlreadySent(
                f"this message already went to {recipient} as {already}. "
                "An approval is consent to one message, not to a retry.")
        if fingerprint in _ALREADY_SENT:
            raise AlreadySent(
                f"this message has already been sent to {recipient} in this "
                "process. Re-sending on a retry is how one approval becomes two "
                "messages to the same person.")

        message = self._compose(recipient, subject, body)
        message_id = message["Message-ID"]

        host = os.environ["QEVIK_SMTP_HOST"].strip()
        port = int(os.environ["QEVIK_SMTP_PORT"].strip())
        user = os.environ["QEVIK_SMTP_USER"].strip()
        password = os.environ["QEVIK_SMTP_PASSWORD"]

        try:
            with smtplib.SMTP(host, port, timeout=30) as server:
                server.starttls()
                server.login(user, password)
                server.send_message(message)
        except smtplib.SMTPException as failure:
            # The status, never the credential. A failed send is retried by a
            # person, not by a loop: a loop that retries an irreversible action
            # is how one approval becomes many.
            log.error("email to %s refused by %s: %s",
                      recipient, host, type(failure).__name__)
            raise OutreachError(
                f"{host} did not accept the message ({type(failure).__name__}). "
                "The approval still stands; nothing was sent.") from failure

        _ALREADY_SENT.add(fingerprint)
        # The durable half, when the caller's approval can hold it. Best effort
        # by design -- a frozen approval simply keeps the in-process guard.
        try:
            approval.sent_message_id = message_id
        except Exception:                        # noqa: BLE001 - not our object
            pass

        log.info("email accepted for %s as %s", recipient, message_id)
        return SendResult(channel=self.name, recipient=recipient,
                          provider_message_id=message_id,
                          detail=f"accepted by {host}")

    def _compose(self, recipient: str, subject: str, body: str) -> EmailMessage:
        """The message, with the header split refused rather than escaped.

        A newline in a subject or an address is a second header. `EmailMessage`
        would raise on some of these, which is right but late -- refusing here
        names the field, and refusing is the only safe direction.

        No signature is added: `preparation.compose()` already ends the body with
        the one that names the licensed entity, and a second would be a second
        claim about who is writing.
        """
        for field, value in (("recipient", recipient), ("subject", subject)):
            if any(character in value for character in "\r\n"):
                raise Unsendable(
                    f"the {field} contains a line break, which would become a "
                    "second header. Refused rather than stripped.")

        message = EmailMessage()
        message["From"] = os.environ["QEVIK_SMTP_FROM"].strip()
        message["To"] = recipient
        message["Subject"] = subject
        reply_to = os.environ.get("QEVIK_SMTP_REPLY_TO", "").strip()
        if reply_to:
            message["Reply-To"] = reply_to
        message.set_content(body)
        # Set explicitly so the id we record is the id that was sent, rather
        # than one a relay invented after we stopped looking, and domained to
        # the sender rather than to whatever host happens to run this.
        message["Message-ID"] = make_msgid(domain=MESSAGE_ID_DOMAIN)
        return message

    @staticmethod
    def _fingerprint(recipient: str, subject: str, body: str) -> tuple[str, str, str]:
        """What makes two sends the same send. Editing any of it makes it a
        different message, which is the behaviour the approval already requires."""
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
        return (recipient, subject, digest)


class WhatsAppChannel(_Unconnected):
    """Will hold a WhatsApp Business sender. Holds none today.

    `can_reach` is the valuable half and works already: sixteen of the twenty
    audited clinics publish a landline, and a WhatsApp message to a landline is
    not an error the sender sees — it is silence. Refusing here is what stops a
    campaign reporting twenty sends and producing four.
    """

    name = "whatsapp"

    def can_reach(self, recipient: str) -> bool:
        return bool(UAE_MOBILE.match(re.sub(r"\D", "", recipient or "")))


def registry() -> dict[str, Channel]:
    """Every channel Qevik knows about. None of them can send."""
    return {channel.name: channel for channel in (EmailChannel(), WhatsAppChannel())}


def connected() -> list[str]:
    """Which channels could actually deliver. Empty, and that is the point."""
    return [name for name, channel in registry().items() if channel.configured()]
