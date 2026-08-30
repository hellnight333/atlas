"""Sending, and the three things that stand in front of it.

No-spam is not a prompt instruction here. It is three mechanisms, each of which
can be tested:

1. **Approval.** ``send`` refuses anything that is not approved, and refuses
   anything whose proposal has changed since it was approved.
2. **Suppression.** Checked immediately before sending rather than at
   generation, so a suppression added *after* approval still takes effect. That
   ordering is the whole point: the moment someone says "never contact me
   again", every already-approved message to them must die, including ones
   approved an hour ago.
3. **Cooldown.** A business contacted once is not contactable again inside the
   niche's window, regardless of how many approvals exist.

``OutreachService.send`` is the only path to a channel. The channel protocol
takes an already-validated message and does no checking of its own, because a
guard duplicated in every channel is a guard that will eventually be missing
from one of them.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable

from .models import (
    NicheProfile,
    OutreachMessage,
    OutreachStatus,
    Proposal,
)


class OutreachRefused(RuntimeError):
    """A send was stopped. The message always says which guard stopped it."""


class SendResult:
    """What a channel reports back."""

    def __init__(self, *, message_id: str | None = None, detail: str | None = None) -> None:
        self.message_id = message_id
        self.detail = detail


@runtime_checkable
class Approved(Protocol):
    """Whatever a pipeline approved, as far as sending is concerned.

    `OutreachService` needs one thing from it: the fingerprint the approval was
    taken over, to re-check that nothing moved since. `Proposal` satisfies this,
    and so does a mission's `Prepared` — which is the point. Requiring a
    `Proposal` specifically would force every upstream pipeline to manufacture
    one, and a mission has a `Signal` and evidence fingerprints rather than the
    `Finding`s a proposal must cite.

    The guards do not change and do not move. Only the question "whose words are
    these" is answered by more than one kind of record.
    """

    @property
    def fingerprint(self) -> str: ...


@runtime_checkable
class OutreachChannel(Protocol):
    """Delivers one already-approved, already-checked message.

    Channels do not validate. By the time one is called, approval, fingerprint,
    suppression and cooldown have all been checked by ``OutreachService`` --
    re-checking here would spread the policy across every implementation and
    guarantee it eventually diverges.
    """

    @property
    def name(self) -> str: ...

    def deliver(self, message: OutreachMessage) -> SendResult: ...


class RecordingChannel:
    """Captures exactly what would have been sent, and sends nothing.

    This is the MVP's only channel, because Atlas has no sending identity yet --
    no domain, no mailbox, no reputation to protect or ruin. A real SMTP channel
    is a small amount of code once those exist, and writing it now would mean
    testing it against nothing.

    It is not a mock. It records the real rendered message, so the pipeline runs
    end to end and the output is reviewable before a single real email is
    possible.
    """

    def __init__(self) -> None:
        self.delivered: list[OutreachMessage] = []

    @property
    def name(self) -> str:
        return "recording"

    def deliver(self, message: OutreachMessage) -> SendResult:
        self.delivered.append(message)
        return SendResult(
            message_id=f"recorded-{len(self.delivered)}",
            detail="Recorded, not delivered — no sending identity is configured.",
        )


class SuppressionList:
    """Addresses and domains that must never be contacted.

    Domain suppression matters as much as address suppression: one person asking
    to be left alone usually means the organisation should be, and a system that
    only honours the exact address will contact their colleague next week.
    """

    def __init__(self, entries: Iterable[str] = ()) -> None:
        self._addresses: set[str] = set()
        self._domains: set[str] = set()
        for entry in entries:
            self.add(entry)

    def add(self, entry: str) -> None:
        value = entry.strip().lower()
        if not value:
            return
        if value.startswith("@"):
            self._domains.add(value[1:])
        elif "@" in value:
            self._addresses.add(value)
        else:
            self._domains.add(value)

    def contains(self, recipient: str) -> bool:
        value = recipient.strip().lower()
        if value in self._addresses:
            return True
        _, _, domain = value.partition("@")
        return bool(domain) and domain in self._domains

    def __len__(self) -> int:
        return len(self._addresses) + len(self._domains)


class ContactHistory:
    """When each business was last contacted.

    In-memory here; the repository is the durable record. Kept as its own object
    so the cooldown rule has one implementation rather than being reimplemented
    at each call site.
    """

    def __init__(self, contacts: dict[str, datetime] | None = None) -> None:
        self._contacts: dict[str, datetime] = dict(contacts or {})

    def record(self, business_id: str, when: datetime | None = None) -> None:
        self._contacts[business_id] = when or datetime.now(UTC)

    def last_contacted(self, business_id: str) -> datetime | None:
        return self._contacts.get(business_id)

    def within_cooldown(self, business_id: str, days: int, now: datetime | None = None) -> bool:
        last = self._contacts.get(business_id)
        if last is None:
            return False
        moment = now or datetime.now(UTC)
        if last.tzinfo is None:  # pragma: no cover - defensive against naive storage
            last = last.replace(tzinfo=UTC)
        return moment - last < timedelta(days=days)


class OutreachService:
    """The only way a message reaches a channel."""

    def __init__(
        self,
        channel: OutreachChannel,
        *,
        suppression: SuppressionList | None = None,
        history: ContactHistory | None = None,
    ) -> None:
        self._channel = channel
        self.suppression = suppression or SuppressionList()
        self.history = history or ContactHistory()

    @property
    def channel_name(self) -> str:
        return self._channel.name

    def send(
        self,
        message: OutreachMessage,
        proposal: Approved,
        profile: NicheProfile,
        *,
        now: datetime | None = None,
    ) -> OutreachMessage:
        """Deliver, or refuse and say why.

        Order matters. Approval is checked first because an unapproved message
        should not even be evaluated against a suppression list -- the answer is
        already no, and reporting the wrong reason for a refusal makes the log
        misleading.
        """
        if message.status is OutreachStatus.APPROVED_FOR_MANUAL_SEND:
            raise OutreachRefused(
                f"message {message.id} was approved for a person to send by "
                "hand, not for automated delivery. Those are different "
                "decisions, and this one was not taken."
            )

        if message.status is not OutreachStatus.APPROVED:
            raise OutreachRefused(
                f"message {message.id} is {message.status.value}, not approved — "
                "nothing sends without a human decision"
            )

        # Before the fingerprint comparison, on purpose. A message approved
        # under the older manual workflow carries a fingerprint of its body
        # alone, which can never equal a proposal fingerprint — so without this
        # check it would be refused as though somebody had edited the proposal,
        # sending the reader to look for a change that was never made.
        if message.authorized_automated_at is None:
            raise OutreachRefused(
                f"message {message.id} carries no authorisation for automated "
                "delivery. Approval that a person may send these words is not "
                "authorisation for Qevik to send them."
            )

        if message.approved_fingerprint is None:
            raise OutreachRefused(
                f"message {message.id} carries no approved fingerprint; "
                "it cannot be shown that a human saw these words"
            )

        current = proposal.fingerprint
        if message.approved_fingerprint != current:
            raise OutreachRefused(
                f"the proposal changed after approval "
                f"(approved {message.approved_fingerprint}, now {current}) — "
                "approval covers a specific message, not a standing permission"
            )

        if self.suppression.contains(message.recipient):
            updated = message.model_copy(
                update={
                    "status": OutreachStatus.SUPPRESSED,
                    "detail": f"{message.recipient} is on the suppression list",
                }
            )
            raise OutreachRefused(updated.detail or "suppressed")

        if self.history.within_cooldown(
            message.business_id, profile.contact_cooldown_days, now=now
        ):
            last = self.history.last_contacted(message.business_id)
            raise OutreachRefused(
                f"{message.business_id} was contacted on {last:%Y-%m-%d}, inside the "
                f"{profile.contact_cooldown_days}-day cooldown for {profile.id}"
            )

        try:
            result = self._channel.deliver(message)
        except Exception as error:  # noqa: BLE001 — a channel failure is data, not a crash
            return message.model_copy(
                update={"status": OutreachStatus.FAILED, "detail": str(error)}
            )

        moment = now or datetime.now(UTC)
        self.history.record(message.business_id, moment)
        return message.model_copy(
            update={
                "status": OutreachStatus.SENT,
                "sent_at": moment,
                "provider_message_id": result.message_id,
                "detail": result.detail,
            }
        )
