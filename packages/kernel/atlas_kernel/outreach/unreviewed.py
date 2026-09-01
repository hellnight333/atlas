"""Drafted outreach nobody has decided about, and why each one is there.

Messages accumulate in `atlas_outreach_messages` as `DRAFT`. Writing the words
is deliberately not asking anybody about them — `outreach_drafts.py` says so in
as many words, and leaves every row it writes at `DRAFT` rather than
`AWAITING_APPROVAL` precisely so that composing text never reads as a request
for a decision. The consequence is a pile of drafts that nobody has decided
about, and no record anywhere of *why* any particular one is still sitting
there.

"Unreviewed" without a reason is the same fault this package refuses everywhere
else: a state nobody can clear, because nobody can tell whether it is waiting on
a person, on an address, or on nothing at all. So each row gets a **named**
answer, read out of the records and never guessed.

## What this module is not

It does not decide, approve, reject, send or delete. There is no write path
here and no channel — the same structural guarantee `outreach_drafts.py` holds,
and for the same reason: a reader that can also act is one flag away from acting
on everything it lists. Surfacing a draft is not asking about it, and a person
reading this list has been told nothing except what is already recorded.

It also does not read "the channel cannot send today" as a reason. Reviewing is
deciding whether these words may go to this business; sending is a separate act
behind its own authorisation, and folding a missing SMTP credential in here
would tell an operator that a decision they *can* take is blocked on one they
cannot.

## The two questions, kept apart

**Has anyone been asked?** Always answerable from the row itself, and it is one
of exactly two states — `NEVER_PUT_TO_A_PERSON` or `ASKED_AND_UNANSWERED`.

**Is there something in the record a reviewer would have to settle first?** Zero
or more named conditions: the draft was replaced, it is addressed to nobody, the
channel cannot reach the address, or the evidence under its claims moved after
it was written.

Kept as separate fields rather than one flat verdict because they answer
different things and a reader needs both. `reason` picks the one that best
explains the row — the first condition that applies, or the request state when
none do — and `blocked_on` still carries the rest, so nothing is hidden behind
the headline.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

#: Nobody was ever asked. The row has been a draft since it was written and
#: carries no approval, no fingerprint and no authorisation of any kind.
NEVER_ASKED = "NEVER_PUT_TO_A_PERSON"

#: Somebody was asked and has not answered. `AWAITING_APPROVAL` is the only
#: status that records the question having been put at all.
ASKED = "ASKED_AND_UNANSWERED"

#: A later message for the same business, channel and origin exists. This one
#: was replaced before anybody read it, and deciding about it now would be
#: deciding about words that are no longer the current ones.
SUPERSEDED = "REPLACED_BY_A_LATER_DRAFT"

#: `recipient` is empty. There is no address, so there is nothing to approve a
#: message *to* — approval binds words to a recipient, not to a slot.
NO_RECIPIENT = "ADDRESSED_TO_NOBODY"

#: There is an address and the channel refuses it. A WhatsApp message to a
#: landline is not an error anybody sees; it is silence.
UNREACHABLE = "THE_CHANNEL_CANNOT_REACH_IT"

#: A later reading of the business disagrees with what was observed when these
#: words were written. The words are still the words; the ground under them
#: moved, and that is a fact a reviewer has to see before deciding.
EVIDENCE_MOVED = "EVIDENCE_MOVED_AFTER_IT_WAS_WRITTEN"

#: The order in which conditions answer "why is this one still undecided".
#:
#: Decisiveness, not severity. A superseded draft is moot whatever else is true
#: of it; an unaddressed one cannot be decided about at all; only then does a
#: claim whose evidence has moved become the most useful thing to say.
LADDER: tuple[str, ...] = (SUPERSEDED, NO_RECIPIENT, UNREACHABLE, EVIDENCE_MOVED)

#: Statuses that mean nobody has decided. Everything else — approved, rejected,
#: suppressed, sent, failed — is a decision somebody took, and this module has
#: no business listing it as waiting.
UNDECIDED_STATUSES: tuple[str, ...] = ("draft", "awaiting_approval")

#: Columns whose presence *is* a decision, whatever the status column says. Any
#: one of them set means somebody acted on this message.
#:
#: Named here rather than spelled out inside `undecided` because the SQL that
#: picks candidates out of the database has to narrow by the same four. It
#: narrowed by `status` alone, and the gap was not merely wasteful: the query
#: takes its `LIMIT` before this function ever runs, so a row that only *looked*
#: undecided spent a place in the queue and a genuinely undecided draft behind
#: it was never read at all. One list, applied in both places, and
#: `test_the_queue_narrows_by_every_signal_that_means_decided` fails if a fifth
#: signal is added here and not there.
DECISION_COLUMNS: tuple[str, ...] = ("approval_id", "approved_fingerprint",
                                     "sent_at", "authorized_automated_at")

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _aware(value: Any) -> datetime | None:
    """A comparable moment, or `None`.

    Rows come back timezone-aware and hand-built fixtures often do not. Sorting
    a mixture raises, and the failure would land in a list whose whole purpose
    is to be readable when things are untidy.
    """
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _iso(value: Any) -> str:
    moment = _aware(value)
    return moment.isoformat() if moment else ""


def undecided(message: Any) -> bool:
    """Whether nobody has decided about this message.

    Four independent signals, not one status column. `delete_unsent_drafts`
    already reasons this way and for the same reason: a status is one edit away
    from lying, and what is being protected here is the opposite direction —
    an approved message must never be listed as undecided, because listing it
    invites somebody to decide it a second time.

    The two messages approved by hand on 2026-08-19 and never sent are exactly
    that case. They carry `approved_fingerprint`, so they are decisions and are
    not this module's business. What is to happen to them is DQ-008, and it is a
    person's to answer.

    Absence is read as falsiness rather than `is None`, which is the same test
    for both kinds of column: the two text ones are absent when empty as well as
    when null, and a `datetime` is never falsy, so a timestamp is caught exactly
    when it is `None`.
    """
    status = str(getattr(message, "status", "") or "")
    return (status in UNDECIDED_STATUSES
            and not any(getattr(message, column, None)
                        for column in DECISION_COLUMNS))


@dataclass(frozen=True)
class Unreviewed:
    """One drafted message, and what the records say about why it is still one.

    Carries the trace for every named condition rather than a rendered
    paragraph. A person deciding whether to contact a stranger has to be able to
    follow each statement back to the row it was read from, and a sentence
    asserting that the records were consulted is not that.
    """

    message_id: str
    business_id: str
    business_name: str
    channel: str
    recipient: str
    subject: str
    #: When the words were written, from `created_at`.
    drafted_at: str
    #: Whole days it has sat undecided. Zero is a real answer, not a missing one.
    waiting_days: int
    #: `NEVER_ASKED` or `ASKED`. Always one of them.
    state: str
    #: Which pipeline composed it. Both empty for the manual drafts, which is
    #: itself the honest answer rather than an invented origin.
    mission_id: str = ""
    proposal_id: str = ""
    blocked_on: tuple[str, ...] = ()
    #: Named condition (and the state) → the record it was read from.
    traces: dict[str, str] = field(default_factory=dict)

    @property
    def reason(self) -> str:
        """The one thing to say about this row, if only one thing can be said."""
        return self.blocked_on[0] if self.blocked_on else self.state

    @property
    def why(self) -> str:
        """That reason, as the record states it."""
        return self.traces.get(self.reason, "")

    def summary(self) -> dict:
        return {"message_id": self.message_id,
                "business_id": self.business_id,
                "business_name": self.business_name,
                "channel": self.channel,
                "recipient": self.recipient,
                "subject": self.subject,
                "drafted_at": self.drafted_at,
                "waiting_days": self.waiting_days,
                "state": self.state,
                "mission_id": self.mission_id,
                "proposal_id": self.proposal_id,
                "blocked_on": list(self.blocked_on),
                "traces": dict(self.traces),
                "reason": self.reason,
                "why": self.why}


def _origin(message: Any) -> tuple[str, str, str, str]:
    """What makes two messages successive versions of the same one.

    Business and channel are not enough. Two missions can each prepare an email
    to one business about two different published artefacts, and calling the
    older of those "replaced" would retire a message nobody replaced. The
    pipeline that composed it is part of its identity.
    """
    return (str(getattr(message, "business_id", "") or ""),
            str(getattr(message, "channel", "") or ""),
            str(getattr(message, "mission_id", "") or ""),
            str(getattr(message, "proposal_id", "") or ""))


def _reachable(channel: str, recipient: str,
               channels: Mapping[str, Any] | None) -> bool | None:
    """Whether that channel could deliver to that address, or `None` if unknown.

    `None` for a channel nothing knows about, and it must stay distinguishable
    from `False`: "we have never heard of this channel" is not "this address is
    unreachable", and reporting the first as the second would put a condition on
    a draft that nothing in the record supports.
    """
    known = channels if channels is not None else _registry()
    channel_impl = known.get(channel)
    if channel_impl is None:
        return None
    return bool(channel_impl.can_reach(recipient))


def _registry() -> Mapping[str, Any]:
    from .channels import registry

    return registry()


def classify(message: Any, *, business_name: str = "",
             superseded_by: Any = None,
             changes: Sequence[Mapping[str, Any]] = (),
             now: datetime | None = None,
             channels: Mapping[str, Any] | None = None) -> Unreviewed:
    """One message, against the records held about it.

    Everything it needs is passed in. Reading the database from here would put
    the derivation and the query in one place, and the derivation is the half
    that has to be testable without one.
    """
    moment = _aware(now) or datetime.now(UTC)
    written = _aware(getattr(message, "created_at", None))
    recipient = str(getattr(message, "recipient", "") or "").strip()
    channel = str(getattr(message, "channel", "") or "")
    status = str(getattr(message, "status", "") or "")
    waiting = max(0, (moment - written).days) if written else 0

    written_at = _iso(written) or "a time that was not recorded"
    if status == "awaiting_approval":
        state = ASKED
        said = (f"awaiting_approval since {written_at} — put to a person "
                f"{waiting} day(s) ago and not answered")
    else:
        state = NEVER_ASKED
        said = (f"a draft since {written_at}, carrying no approval, no "
                "fingerprint and no authorisation: the record shows the "
                "question was never put to anybody")
    traces: dict[str, str] = {state: said}

    blocked: list[str] = []

    if superseded_by is not None:
        blocked.append(SUPERSEDED)
        traces[SUPERSEDED] = (
            f"a later message on the same channel and origin "
            f"({getattr(superseded_by, 'id', '')}) was written "
            f"{_iso(getattr(superseded_by, 'created_at', None))}; this one was "
            "replaced before anybody read it")

    if not recipient:
        blocked.append(NO_RECIPIENT)
        traces[NO_RECIPIENT] = (
            "atlas_outreach_messages.recipient is empty, so there is no "
            "address these words could be approved to")
    else:
        reachable = _reachable(channel, recipient, channels)
        if reachable is False:
            blocked.append(UNREACHABLE)
            traces[UNREACHABLE] = (
                f"{recipient!r} cannot receive on {channel} — the channel's own "
                "can_reach refuses it, so approving would authorise a message "
                "that goes nowhere and reports nothing")

    if changes:
        latest = max((str(change.get("at", "")) for change in changes),
                     default="")
        blocked.append(EVIDENCE_MOVED)
        traces[EVIDENCE_MOVED] = (
            f"{len(changes)} change(s) about the business were recorded after "
            f"these words were written{f', the latest at {latest}' if latest else ''}. "
            "The words still say what was observed then")

    ordered = tuple(name for name in LADDER if name in blocked)
    return Unreviewed(
        message_id=str(getattr(message, "id", "") or ""),
        business_id=str(getattr(message, "business_id", "") or ""),
        business_name=business_name,
        channel=channel,
        recipient=recipient,
        subject=str(getattr(message, "subject", "") or ""),
        drafted_at=_iso(written),
        waiting_days=waiting,
        state=state,
        mission_id=str(getattr(message, "mission_id", "") or ""),
        proposal_id=str(getattr(message, "proposal_id", "") or ""),
        blocked_on=ordered,
        traces=traces)


def from_records(messages: Iterable[Any], *,
                 names: Mapping[str, str] | None = None,
                 changes: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
                 now: datetime | None = None,
                 channels: Mapping[str, Any] | None = None) -> list[Unreviewed]:
    """Every message nobody has decided about, oldest first.

    Takes **every** message, not only the undecided ones, and that is what makes
    supersession answerable: a draft replaced by one that was later approved is
    just as moot as one replaced by another draft, and a reader given only the
    undecided rows cannot tell.
    """
    named = dict(names or {})
    moved = dict(changes or {})
    ordered = sorted(
        messages,
        key=lambda message: (_aware(getattr(message, "created_at", None)) or _EPOCH,
                             str(getattr(message, "id", "") or "")))

    latest: dict[tuple[str, str, str, str], Any] = {}
    for message in ordered:
        latest[_origin(message)] = message

    found: list[Unreviewed] = []
    for message in ordered:
        if not undecided(message):
            continue
        current = latest.get(_origin(message))
        replaced = current if current is not None and current is not message else None
        found.append(classify(
            message,
            business_name=named.get(str(getattr(message, "business_id", "")), ""),
            superseded_by=replaced,
            changes=moved.get(str(getattr(message, "id", "")), ()),
            now=now, channels=channels))
    return found


def counts(rows: Sequence[Unreviewed]) -> dict:
    """The tally, by the same names the rows carry.

    Deliberately not a single "blocked" number. An operator deciding where to
    spend an afternoon needs to know that four drafts are addressed to nobody
    and one is waiting on them personally; a count of five blocked things says
    neither.
    """
    return {"total": len(rows),
            "never_asked": sum(1 for row in rows if row.state == NEVER_ASKED),
            "asked": sum(1 for row in rows if row.state == ASKED),
            "superseded": sum(1 for row in rows if SUPERSEDED in row.blocked_on),
            "addressed_to_nobody": sum(
                1 for row in rows if NO_RECIPIENT in row.blocked_on),
            "unreachable": sum(1 for row in rows if UNREACHABLE in row.blocked_on),
            "evidence_moved": sum(
                1 for row in rows if EVIDENCE_MOVED in row.blocked_on)}
