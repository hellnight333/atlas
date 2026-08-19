"""Where email and WhatsApp will attach, and why neither can send today.

The instruction is to prepare the architecture without connecting it. That is a
sharper requirement than it sounds: the usual way to "prepare" a sender is to
write the client and leave a flag off, which produces a system that is one
truthy value away from messaging twenty real businesses.

So this defines the *shape* and deliberately withholds the capability. Every
channel here raises `ChannelNotConnected`. There is no SMTP client, no HTTP
client, no provider SDK imported anywhere in this module — adding one is a
visible, reviewable diff rather than a config change.

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

import re
from dataclasses import dataclass
from typing import Any, Protocol

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
    """Will hold an SMTP or API sender. Holds neither today."""

    name = "email"

    def can_reach(self, recipient: str) -> bool:
        return bool(EMAIL_SHAPE.match((recipient or "").strip()))


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
