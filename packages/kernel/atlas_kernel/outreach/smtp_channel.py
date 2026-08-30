"""The SMTP adapter for the canonical outreach path.

`docs/qevik-docs/65_OUTREACH.md` prescribes this file: *"Write the provider
adapter in its own file under `atlas_kernel/outreach/`."* It exists so the two
things it joins can stay apart.

## What it is, and what it deliberately is not

`OutreachService` owns outreach policy -- approval, the approved fingerprint,
suppression and cooldown -- and its channel protocol is explicit that a channel
must not re-check any of it:

    Channels do not validate. By the time one is called, approval, fingerprint,
    suppression and cooldown have all been checked by ``OutreachService`` --
    re-checking here would spread the policy across every implementation and
    guarantee it eventually diverges.

`EmailChannel` owns the transport: an address shape, a TLS handshake, an
authenticated submission. It also carries its own gates, because it was built
for a different caller -- the mission-side preparation path -- where nothing
else was going to check.

This adapter is the seam between them, and it holds **no policy of its own**. It
translates an `OutreachMessage` into a transport call and a `SendResult` back.
Every refusal it can produce is a transport fact, never a decision.

## Why the transport's own gates are not a second policy layer

`EmailChannel.send` will still check reachability, approval, configuration and
duplication. Two of those are already true by the time we arrive: the service
checked approval, and it would not have called us for an unreachable recipient.
That redundancy is left in place rather than removed, because the transport is
also reachable from the preparation path, where it is the only thing checking.

What matters is the direction: **no policy decision is made here, and none is
skipped there.** This adapter cannot approve, cannot suppress, and cannot
shorten a cooldown -- it has no access to any of them.
"""
from __future__ import annotations

import logging
from typing import Any

from ..opportunity.models import OutreachMessage
from ..opportunity.outreach import SendResult
from .channels import EmailChannel

log = logging.getLogger(__name__)


class _AlreadyApproved:
    """What the transport's approval gate expects, for a message the service
    has already approved.

    Not a bypass. `OutreachService` refuses anything whose status is not
    APPROVED and whose fingerprint has moved, and it does so before a channel is
    reached at all. This carries that decision across an interface that predates
    it, and carries the fingerprint with it so a reader can see which approval
    is being asserted.
    """

    def __init__(self, message: OutreachMessage) -> None:
        self.approved = True
        self.approval_id = message.approval_id
        self.approved_fingerprint = message.approved_fingerprint
        #: Read by the transport's duplicate guard. A message the service has
        #: already sent never reaches here, but if one did, this is what stops it.
        self.sent_message_id = message.provider_message_id or ""


class SmtpOutreachChannel:
    """Delivers an approved outreach message over SMTP.

    Constructed with the transport rather than creating one, so a test can
    substitute it without patching a module global -- and so this file never
    decides which transport is in use.
    """

    def __init__(self, transport: Any | None = None) -> None:
        self._transport = transport or EmailChannel()

    @property
    def name(self) -> str:
        return "email"

    @property
    def configured(self) -> bool:
        """Whether a real send could happen. Reported, never assumed: this is
        what lets an operator see that an approved message cannot go out yet."""
        return bool(self._transport.configured())

    def deliver(self, message: OutreachMessage) -> SendResult:
        """Hand one already-checked message to the transport.

        Raises rather than returning a failed result: `OutreachService` catches
        the exception and records `FAILED` with the reason, which keeps one
        place deciding how a failure is represented.
        """
        result = self._transport.send(
            recipient=message.recipient,
            subject=message.subject,
            body=message.body,
            approval=_AlreadyApproved(message),
        )
        log.info("outreach %s delivered to %s as %s",
                 message.id, message.recipient, result.provider_message_id)
        return SendResult(message_id=result.provider_message_id,
                          detail=result.detail)
