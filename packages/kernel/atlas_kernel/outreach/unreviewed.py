"""Drafted outreach nobody has decided about, and why each one is there.

Messages accumulate in `atlas_outreach_messages` as `DRAFT`. Writing the words
is deliberately not asking anybody about them — `infra/outreach_drafts.py` says
so in as many words, and leaves every row it writes at `DRAFT` rather than
`AWAITING_APPROVAL` precisely so that composing text never reads as a request
for a decision. The consequence is fourteen drafts nobody has decided about, and
no record anywhere of *why* any particular one is still sitting there.

"Unreviewed" without a reason is a state nobody can clear, because nobody can
tell whether it is waiting on a person, on an address, or on nothing at all. So
each row gets a **named** answer, read out of the records and never guessed.

## What this module is not

It does not decide, approve, reject, send or delete. There is no write path here
and no channel — the same structural guarantee `outreach_drafts.py` holds, and
for the same reason: a reader that can also act is one flag away from acting on
everything it lists. Surfacing a draft is not asking about it.

It reads nothing either. Every record it reasons over arrives as an argument, so
the derivation is testable without a database and the query that feeds it can be
written separately without either half moving.

It also does not read "the channel cannot send today" as a reason. Reviewing is
deciding whether these words may go to this business; sending is a separate act
behind its own authorisation, and folding a missing SMTP credential in here
would tell an operator that a decision they *can* take is blocked on one they
cannot.

## The two questions, kept apart

**Has anyone been asked?** Three answers, and a row gets whichever the most
specific surviving record supports. The rule is one rule: say what some record
says, and never more.

`ASKED_AND_UNANSWERED` is what the *row itself* says — `AWAITING_APPROVAL`, or
an `approval_id` naming the request these words are bound to. Either is a
message-level record that the question was put about *these* words.

`NEVER_PUT_TO_A_PERSON` is the strong claim, and it is only available when
nothing anywhere says otherwise: not the row, and not the business's history.

Between them sits `ASKED_ABOUT_THE_BUSINESS_NOT_THIS_MESSAGE`, and it exists
because of a gap in the records that this module must not paper over.

The gap is this. `OpportunityService.request_approval` is the only path that
puts the question to a person today, and **it does not touch the message**: it
creates the request through the gate and appends an `approval_requested` entry
to the business's timeline, leaving the row exactly where it was, at `DRAFT`.
Nothing in the repository writes `AWAITING_APPROVAL` onto an `OutreachMessage`
at all — the status is defined on `OutreachStatus` and no code assigns it. So a
draft row on its own does not support the sentence "the record shows the
question was never put to anybody", and stating it anyway would be a fabricated
fact about a person, which is the single thing this list exists not to do.

The event cannot close the gap either, and must not be read as though it could.
It names an approval and an opportunity, never a message, and a business holding
a WhatsApp draft *and* an email draft is exactly the case that decides it:
attributing the event to rows would mark both as asked when at most one was.

So the middle state says precisely what the records hold and stops there —
somebody was asked about this company, and nothing ties that question to these
words — and it names the request, with the moment it was raised, so a reader can
go and settle what this module cannot.

The same gap runs in the other direction, and it is the one that decays quietly.
Asking is an event; being answered is a *later* event somewhere else.
`ApprovalService` records approvals, refusals, cancellations and expiries against
its own request and knows nothing about outreach messages, and there is no path
back: no method on `OpportunityService` writes a terminal decision onto the row.
Which is why nothing here ever claims a request is still open. `ASKED` says the
row records no answer — a statement about the row, provable from the row — and
points at the request record, where the answer actually lives.

Wiring the ask, and the answer, back to the persisted message is what would
collapse these three states to two. That is a change to the approval service and
not to this module, and it is a separate piece of work. Until it lands, this
module reports what today's records say and no more.

*Whether* somebody was asked is answerable to that extent; *when* is not.
Nothing timestamps a status move, so the only moment any row carries is
`created_at`, and every number here is measured from it and says so. Reporting
the age of the words as the age of the request would make up a fact about a
person out of one about a message.

**Is there something in the record a reviewer would have to settle first?** Zero
or more named conditions: the draft was replaced, it is addressed to nobody, the
channel cannot reach the address, or a later reading of the business disagrees
with what was observed when the words were written. That last one is a statement
about the company and is not narrowed to the features these particular words
talk about — no record ties a message to the findings under it, and guessing at
one would either invent a link or hide a change from the person about to send.
`_moved_since` has the whole argument.

Kept as separate fields rather than one flat verdict because they answer
different things and a reader needs both. `reason` picks the one that best
explains the row — the first condition that applies, or the request state when
none do — and `blocked_on` still carries the rest, so nothing is hidden behind
the headline.

## The unit is a message

Everything here is counted in messages, including any limit a caller applies.
A business holds several drafts — `outreach_drafts.py` writes a WhatsApp message
and an email for every one it prepares — so a limit counted in businesses
returns an unpredictable number of messages and silently drops the rest of each
business's drafts without saying so. `only` is what makes a message-counted
limit expressible: it names message ids, the fold is still handed every message
because supersession cannot be answered otherwise, and it reports on exactly the
ones asked about.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

#: No record anywhere says the question was put — not the row, and not the
#: business's history. The strongest of the three claims and the narrowest: it
#: asserts an absence, so it is only reachable once both places have been looked
#: at and both are silent.
NEVER_ASKED = "NEVER_PUT_TO_A_PERSON"

#: The **row** records the question having been put about these exact words, and
#: records no answer. Either `AWAITING_APPROVAL`, or an `approval_id` naming the
#: request the message is bound to.
#:
#: "and records no answer" is the whole of the claim. Whether anybody answered is
#: decided against the request, not here, and no path writes that answer back —
#: so the trace names the request rather than asserting it is still open.
ASKED = "ASKED_AND_UNANSWERED"

#: The business's history records a question being put, and nothing ties it to
#: this message.
#:
#: Not a hedge — the honest reading of records that genuinely say this much and
#: no more. `request_approval` leaves the row untouched and appends an
#: `approval_requested` entry naming an approval and an opportunity, so for a
#: business holding a WhatsApp draft beside an email draft the records show that
#: *something* was asked about and not *which*. Calling that `NEVER_ASKED` would
#: be a false negative about a person; calling it `ASKED` would put a question
#: on a message nobody may have raised. See the module docstring.
ASKED_ABOUT_THE_BUSINESS = "ASKED_ABOUT_THE_BUSINESS_NOT_THIS_MESSAGE"

#: A **provably** later message for the same business, channel and origin
#: exists. These are no longer the current words for that origin, and deciding
#: about them now would be deciding about text a later draft has replaced.
#:
#: What it does *not* say is that nobody read this one. Nothing anywhere records
#: a reading — two dated rows establish that a later message exists and no more
#: — and the row may well be one somebody was asked about, where "nobody read
#: it" beside `ASKED` would be two adjacent fields contradicting each other.
#:
#: Provably, because the claim is about time and only a recorded time can
#: support it. Two rows written in the same instant, or either of them missing
#: `created_at`, establish no order at all — and an undated draft is exactly the
#: row this list exists for, so answering it with an invented ordering would put
#: a fabricated reason on the one message nobody can otherwise account for.
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
#:
#: Recorded about the **company**, which is the only scope the records support:
#: the message names no findings, so nothing here claims that the change bears on
#: a particular sentence. See `_moved_since`.
EVIDENCE_MOVED = "EVIDENCE_MOVED_AFTER_IT_WAS_WRITTEN"

#: The order in which conditions answer "why is this one still undecided".
#:
#: Decisiveness, not severity. A superseded draft is moot whatever else is true
#: of it; an unaddressed one cannot be decided about at all; only then does a
#: claim whose evidence has moved become the most useful thing to say.
LADDER: tuple[str, ...] = (SUPERSEDED, NO_RECIPIENT, UNREACHABLE, EVIDENCE_MOVED)

#: What each condition is called in the tally.
#:
#: Paired with the condition rather than written out again inside `counts`,
#: because the failure it guards against is silent: a fifth condition added to
#: `LADDER` would be named on every row that has it and missing from every
#: total, and a tally that quietly omits a reason is worse than no tally — an
#: operator reads it as "none of those", not as "not counted".
COUNT_KEYS: dict[str, str] = {SUPERSEDED: "superseded",
                              NO_RECIPIENT: "addressed_to_nobody",
                              UNREACHABLE: "unreachable",
                              EVIDENCE_MOVED: "evidence_moved"}

#: What each request state is called in the tally, paired with the state for the
#: same reason `COUNT_KEYS` is paired with the condition. These three *are*
#: slices of `total` and do sum to it: every row is in exactly one.
STATE_KEYS: dict[str, str] = {NEVER_ASKED: "never_asked",
                              ASKED_ABOUT_THE_BUSINESS: "asked_about_the_business",
                              ASKED: "asked"}

#: Statuses that mean nobody has decided. Everything else — approved, rejected,
#: suppressed, sent, failed — is a decision somebody took, and this module has
#: no business listing it as waiting.
UNDECIDED_STATUSES: tuple[str, ...] = ("draft", "awaiting_approval")

#: The timeline entry `request_approval` appends when it puts the question to a
#: person. Spelled as the string rather than imported from `PipelineEventKind`,
#: like the statuses and columns above and for the same reason: this module
#: takes records as arguments from callers that hand over models *or* row
#: mappings, and importing an enum to compare against `str` values would buy
#: nothing and make the opportunity package a dependency of this one.
APPROVAL_REQUESTED = "approval_requested"

#: Whose vocabulary `APPROVAL_REQUESTED` is a word in.
#:
#: `BusinessEvent` is one timeline per company that **every** factory writes to,
#: and `kind` is a plain string rather than an enum precisely so each factory can
#: name its own events under its own `factory` label without editing anybody
#: else's module. Fifteen of them write here today. So the kind alone does not
#: identify an event: `approval_requested` is a name any factory could reach for,
#: and matching it on its own would read a website deployment or a credit spend
#: waiting on somebody as a question put about this company's outreach — which is
#: a fabricated fact about a person, and the one thing this module exists not to
#: produce. Both halves of the namespace are checked, here and for reevaluations.
#:
#: Spelled rather than imported, like the kind above and for the same reason.
OPPORTUNITY_FACTORY = "opportunity"

#: Columns whose presence *is* a decision, whatever the status column says. Any
#: one of them set means somebody acted on this message.
#:
#: Named here rather than spelled out inside `undecided` because the query that
#: picks candidates out of the database has to narrow by the same three. It
#: takes its limit before this module ever runs, so a row that only *looked*
#: undecided would spend a place in the window and a genuinely undecided draft
#: behind it would never be read at all. One list, applied in both places.
#:
#: `approval_id` is **not** among them, and its absence is load-bearing. It names
#: a request, which is a question, and a question is not an act. Today the gate
#: happens to write it only alongside a terminal status — `authorise` with
#: `APPROVED`, `reject` with `REJECTED` — so it never yet appears on an
#: undecided row; the moment the ask is wired back to the message it will, and
#: reading it as an act then would hide every pending request from the queue
#: this module exists to produce. That is the failure in the direction that
#: matters: a draft somebody is waiting on, silently absent from the list of
#: drafts somebody is waiting on. What it is for is the other direction — a
#: reader holding a row can look the request up and check the claim it makes.
DECISION_COLUMNS: tuple[str, ...] = ("approved_fingerprint", "sent_at",
                                     "authorized_automated_at")

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


def _of(record: Any, name: str, default: Any = None) -> Any:
    """One field of a record, whether it is a model or a mapping.

    The same events arrive as `BusinessEvent` instances from one caller and as
    row mappings from another. Requiring one shape would make this module
    dictate how the query that feeds it is written, which is the coupling the
    argument boundary exists to avoid.
    """
    if isinstance(record, Mapping):
        return record.get(name, default)
    return getattr(record, name, default)


def undecided(message: Any) -> bool:
    """Whether nobody has decided about this message.

    Four independent signals — the status and the three columns in
    `DECISION_COLUMNS` — not one status column. A status is one edit away from
    lying, and what is being protected here is a particular direction: an
    approved message must never be listed as undecided, because listing it
    invites somebody to decide it a second time.

    The two messages approved by hand on 2026-08-19 and never sent are exactly
    that case. They carry `approved_fingerprint`, so they are decisions and are
    not this module's business. What is to happen to them is DQ-008, and it is a
    person's to answer.

    Absence is read as falsiness rather than `is None`, which is the same test
    for both kinds of column: the text one is absent when empty as well as when
    null, and a `datetime` is never falsy, so a timestamp is caught exactly when
    it is `None`.
    """
    status = str(_of(message, "status", "") or "")
    return (status in UNDECIDED_STATUSES
            and not any(_of(message, column) for column in DECISION_COLUMNS))


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
    #: Whole days since the words were written, which is how long nobody has
    #: decided about them. Zero is a real answer, not a missing one.
    #:
    #: Never how long an *ask* has waited, even on an `ASKED` row: no column
    #: records when the question was put, so there is no such number to give.
    waiting_days: int
    #: One of `NEVER_ASKED`, `ASKED_ABOUT_THE_BUSINESS` or `ASKED`. Always
    #: exactly one — every row gets whichever the most specific record supports.
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
    return (str(_of(message, "business_id", "") or ""),
            str(_of(message, "channel", "") or ""),
            str(_of(message, "mission_id", "") or ""),
            str(_of(message, "proposal_id", "") or ""))


def _replaces(candidate: Any, written: datetime | None) -> bool:
    """Whether `candidate` is recorded as written after these words were.

    Strictly after, and both moments have to exist. Sorting can always produce
    an order — fall back to the id and there is a "last" message for every
    origin — but an order is not a fact, and `REPLACED_BY_A_LATER_DRAFT` is a
    statement about what the records say happened. Same instant, no timestamp on
    either side, or a timestamp on only one: nothing was shown to have replaced
    anything, so nothing is reported.
    """
    if candidate is None or written is None:
        return False
    at = _aware(_of(candidate, "created_at"))
    return at is not None and at > written


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


def _recorded_by(event: Any, factory: str) -> bool:
    """Whether this entry belongs to that factory's vocabulary.

    An entry naming no factory at all is not a record of a *different* one, and
    it is not excluded: row mappings assembled by a caller and hand-built
    fixtures both arrive without the column, and dropping them would lose a real
    ask over a missing field — the false negative about a person that the middle
    state exists to prevent. Only an entry that says it belongs somewhere else is
    excluded, and it says so in the one field that carries the namespace.
    """
    named = str(_of(event, "factory", "") or "")
    return not named or named == factory


def _asks_on_the_timeline(events: Sequence[Any]) -> list[tuple[datetime | None, str]]:
    """Every question about this *business* the history records, oldest first.

    Not windowed against the draft's own `created_at`, and deliberately so. The
    claim being supported is a claim about the company — that somebody was asked
    about it — and nothing in the entry says which message was meant, so there
    is no message-shaped window to apply. Comparing a business-level record
    against a message-level moment to narrow it would be inventing exactly the
    link the entry does not contain, which is the failure this whole state is
    here to avoid.

    Undated entries sort to the front rather than being dropped. An entry with
    no moment still records that a question was put, and that is the part the
    state rests on; only the reading order of the trace is affected.

    Matched on both halves of the name. `kind` is namespaced by `factory` and
    `approval_requested` is a word any factory could use, so the kind alone would
    let another factory's request stand behind a sentence about this company's
    outreach — see `OPPORTUNITY_FACTORY`.
    """
    found: list[tuple[datetime | None, str]] = []
    for event in events:
        if (str(_of(event, "kind", "") or "") != APPROVAL_REQUESTED
                or not _recorded_by(event, OPPORTUNITY_FACTORY)):
            continue
        detail = _of(event, "detail") or {}
        named = detail.get("approval_id") if isinstance(detail, Mapping) else None
        found.append((_aware(_of(event, "at")), str(named or "")))
    found.sort(key=lambda pair: pair[0] or _EPOCH)
    return found


def _moved_since(written: datetime | None, events: Sequence[Any]) -> list[dict]:
    """Findings about the business recorded after these words were written,
    oldest first.

    Three filters, and all three belong here rather than in whatever fetched the
    events. The first is whose record it is: `kind` is namespaced by `factory`,
    so a reevaluation is `business_reevaluated` **in the reevaluation factory's
    vocabulary**, and both halves are read — see `OPPORTUNITY_FACTORY` for why
    the kind on its own does not identify an entry.

    The second is the window: a reevaluation recorded in the same instant as the
    draft is not one made after it, so the comparison is strict.

    The third is which findings count. `reevaluation` separates a site that
    changed from a reading that could not see, and only the former says anything
    about the company — a draft flagged because our own crawler lost visibility
    would train an operator to ignore the flag. A caller handing over a
    business's history should not have to know that, so this reads it from the
    vocabulary that defines it.

    What is deliberately *not* filtered is which feature moved. The window is the
    business, not the sentence, and it is not narrowed to the features the
    message happens to talk about — for three reasons, in order of how final they
    are. Nothing in an `OutreachMessage` names the evidence under its words: it
    carries a `proposal_id` **or** a `mission_id` and no findings, and the manual
    drafts carry neither, so for those rows the set to filter against does not
    exist at all. Even reaching past this module's arguments for the proposal
    would not close it, because a claim cites a `finding_id` in the `FindingKind`
    vocabulary while a change names a `feature` from the research observations,
    and no record maps one to the other — matching them by the shape of their
    names would invent exactly the link the records do not contain, which is the
    same invention the middle request state refuses to make. And the direction of
    error settles it: a reviewer shown a change that turns out not to bear on
    these words loses a moment, while one *not* shown it because a guess ruled it
    irrelevant approves stale claims about a company. So this reports every
    recorded change about the business and says no more than that — the trace
    counts changes about the business, and never asserts which claim moved.

    Ordered here, by the moment rather than by the rendered text, so that the
    caller can name the latest one without re-deriving it. Events arrive with
    whatever offset they were written in — Dubai's `+04:00` beside the control
    plane's `+00:00` — and sorting the ISO strings orders those by their offset
    instead of by when they happened, which would report a change from the day
    before as the most recent thing anybody found.
    """
    from ..mission.reevaluation import (
        ABOUT_THE_BUSINESS,
        COMPARED,
        FACTORY as REEVALUATION_FACTORY,
    )

    if written is None:
        return []
    about_business = {change.value for change in ABOUT_THE_BUSINESS}
    found: list[tuple[datetime, dict]] = []
    for event in events:
        if (str(_of(event, "kind", "") or "") != COMPARED
                or not _recorded_by(event, REEVALUATION_FACTORY)):
            continue
        at = _aware(_of(event, "at"))
        if at is None or at <= written:
            continue
        detail = _of(event, "detail") or {}
        changes = (detail.get("changes") if isinstance(detail, Mapping) else None) or []
        found.extend((at, {**change, "at": at.isoformat()})
                     for change in changes
                     if isinstance(change, Mapping)
                     and str(change.get("change") or "") in about_business)
    found.sort(key=lambda pair: pair[0])
    return [change for _, change in found]


def _state_of(message: Any, events: Sequence[Any], *,
              written_at: str, waiting: int, dated: bool) -> tuple[str, str]:
    """Has anybody been asked, and which record says so.

    Three answers, taken in order of how specific the record is: the row first,
    the business's history second, silence last. `NEVER_ASKED` is only reachable
    once both have been consulted, because it asserts an absence and an absence
    is not visible from one of the two places.

    What the trace may say is bounded by what arrives here, which is one message
    and one business history — never the row's siblings, and never more of an
    entry than was read out of it. A sentence about the business's other drafts
    would describe records this function was not given, and a sentence about
    what every entry names would describe the shape `request_approval` happens
    to write rather than the entry in hand: `_asks_on_the_timeline` deliberately
    keeps entries whose detail names no approval, and reads no opportunity at
    all. The general argument — that the entry that path appends names an
    approval and an opportunity and never a message — is a claim about
    `request_approval` and lives in the module docstring. The trace is a claim
    about these records, and a reader is meant to be able to check it against
    them.
    """
    status = str(_of(message, "status", "") or "")
    named = str(_of(message, "approval_id", "") or "")

    # `created_at` is when the words were written, and it is the only moment the
    # row carries. Nothing timestamps a status move, so dating an ask from it
    # would be an invention about a person: a draft that sat a month and was
    # raised yesterday would read as somebody ignoring a request for a month.
    carries = (f"The one moment it carries is {written_at}, when the words were "
               f"written, {waiting} day(s) ago."
               if dated else
               "It carries no moment at all — not when the words were written, "
               "and not when anybody was asked.")

    if status == "awaiting_approval" or named:
        said_by = ("atlas_outreach_messages.status is awaiting_approval"
                   if status == "awaiting_approval" else
                   "atlas_outreach_messages.approval_id names a request while "
                   f"the status still reads {status or 'nothing at all'}")
        # Named so the claim is checkable. The status says nobody has answered,
        # and no path writes an answer back onto the row — so pointing at the
        # request that settles it turns a statement an operator would have to
        # trust into one they can go and verify.
        where = (f"The request it is bound to is {named}; that record is where "
                 "the answer would be."
                 if named else
                 "The row names no approval request, so there is nothing to "
                 "check the answer against.")
        return ASKED, (f"{said_by} — the question was put to a person about "
                       "these exact words and the row records no answer. When "
                       f"it was put is not recorded on the row. {carries} "
                       f"{where}")

    asks = _asks_on_the_timeline(events)
    if asks:
        raised = ", ".join(
            f"{approval or 'an approval it does not name'}"
            + (f" raised {at.isoformat()}" if at else " raised at no recorded time")
            for at, approval in asks)
        return ASKED_ABOUT_THE_BUSINESS, (
            f"the row is still {status or 'unset'} and names no approval "
            f"request, and the business's history holds {len(asks)} "
            f"approval_requested entry(ies) — {raised}. Those entries are "
            "recorded against the business, and no identifier ties any of them "
            "to this row, which names no request at all: the records show that "
            "somebody was asked about this company and do not show which words "
            "were meant. Whether that request was answered is in the request "
            "record and not here")

    return NEVER_ASKED, (
        f"a draft since {written_at}, carrying no approval, no fingerprint and "
        "no authorisation, for a business whose history records no approval "
        "request either: no record anywhere shows the question was put to "
        "anybody")


def classify(message: Any, *, business_name: str = "",
             superseded_by: Any = None,
             events: Sequence[Any] = (),
             now: datetime | None = None,
             channels: Mapping[str, Any] | None = None) -> Unreviewed:
    """One message, against the records held about it.

    Everything it needs is passed in. Reading the database from here would put
    the derivation and the query in one place, and the derivation is the half
    that has to be testable without one.

    `events` is this business's history, and it answers two separate questions:
    whether anybody was asked about the company, and whether the ground under
    the message's claims moved. Both are filtered here rather than by the
    caller, so whatever fetched the history does not have to know which kinds
    mean what.
    """
    moment = _aware(now) or datetime.now(UTC)
    written = _aware(_of(message, "created_at"))
    recipient = str(_of(message, "recipient", "") or "").strip()
    channel = str(_of(message, "channel", "") or "")
    waiting = max(0, (moment - written).days) if written else 0

    state, said = _state_of(
        message, events,
        written_at=_iso(written) or "a time that was not recorded",
        waiting=waiting, dated=written is not None)
    traces: dict[str, str] = {state: said}

    blocked: list[str] = []

    if superseded_by is not None:
        blocked.append(SUPERSEDED)
        # Both moments, because the claim is that one is after the other and a
        # reader has to be able to check it. And nothing beyond them: whether
        # anybody read these words is recorded nowhere, so a trace saying they
        # were replaced unread would invent a fact about a person — and would
        # contradict the `ASKED` state on a row somebody was asked about.
        traces[SUPERSEDED] = (
            f"a later message for the same business, channel and origin "
            f"({_of(superseded_by, 'id', '')}) is recorded as written "
            f"{_iso(_of(superseded_by, 'created_at'))}, after these words at "
            f"{_iso(written)}; these are no longer the latest words drafted "
            "for that origin")

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

    moved = _moved_since(written, events)
    if moved:
        latest = str(moved[-1].get("at", ""))
        blocked.append(EVIDENCE_MOVED)
        traces[EVIDENCE_MOVED] = (
            f"{len(moved)} change(s) about the business were recorded after "
            f"these words were written, the latest at {latest}. The words still "
            "say what was observed then. Which of these changes bears on these "
            "particular claims is recorded nowhere, so all of them are shown "
            "rather than a guess at the relevant ones")

    ordered = tuple(name for name in LADDER if name in blocked)
    return Unreviewed(
        message_id=str(_of(message, "id", "") or ""),
        business_id=str(_of(message, "business_id", "") or ""),
        business_name=business_name,
        channel=channel,
        recipient=recipient,
        subject=str(_of(message, "subject", "") or ""),
        drafted_at=_iso(written),
        waiting_days=waiting,
        state=state,
        mission_id=str(_of(message, "mission_id", "") or ""),
        proposal_id=str(_of(message, "proposal_id", "") or ""),
        blocked_on=ordered,
        traces=traces)


def from_records(messages: Iterable[Any], *,
                 only: Iterable[str] | None = None,
                 names: Mapping[str, str] | None = None,
                 events: Mapping[str, Sequence[Any]] | None = None,
                 now: datetime | None = None,
                 channels: Mapping[str, Any] | None = None) -> list[Unreviewed]:
    """Every message nobody has decided about, oldest first.

    Takes **every** message, not only the undecided ones, and that is what makes
    supersession answerable: a draft replaced by one that was later approved is
    just as moot as one replaced by another draft, and a reader given only the
    undecided rows cannot tell.

    Supersession is read out of two recorded moments and never out of the sort
    order. Sorting always yields a last message per origin — the key falls back
    to the id — including for origins whose rows share an instant or carry no
    timestamp at all, and reporting the other one as replaced would be an
    ordering the records do not contain.

    `events` is each business's history, keyed by `business_id`. Handed whole
    and filtered in `classify`, so the caller fetching it does not have to know
    which kinds record a question being put, which record the evidence moving,
    or which window each message asks about.

    `only` narrows what is *reported* without narrowing what is *read*. That
    separation is the whole reason it exists: a caller that has already chosen
    which messages it wants — a limit, a single business, one draft somebody
    asked about — still needs the rest of the records present, because whether a
    draft was replaced is a fact about the messages around it. Narrowing the
    input instead would silently turn a superseded draft into a current one.

    It is counted in messages because it names messages. A window counted in
    businesses would answer a request for twenty rows with an unpredictable
    number, and the ones past the count are not a page anybody asked for — they
    are rows the caller cannot tell it was given.

    A message id in `only` that is not among `messages`, or that somebody has
    decided about, contributes nothing: `only` is a filter, never a guarantee
    that a row exists to report.
    """
    named = dict(names or {})
    history = dict(events or {})
    wanted = None if only is None else {str(one) for one in only}
    ordered = sorted(
        messages,
        key=lambda message: (_aware(_of(message, "created_at")) or _EPOCH,
                             str(_of(message, "id", "") or "")))

    # The newest *dated* message of each origin, which is the only thing that
    # can be shown to have replaced anything. Undated rows are skipped rather
    # than sorted to the front: they take part as messages to be reported, never
    # as evidence that some other message came first.
    newest: dict[tuple[str, str, str, str], Any] = {}
    for message in ordered:
        if _aware(_of(message, "created_at")) is not None:
            newest[_origin(message)] = message

    found: list[Unreviewed] = []
    for message in ordered:
        if not undecided(message):
            continue
        # Matched against the id the row is *reported* under, absence read the
        # same way here as there. A row whose id never arrived reports `""`, and
        # a filter that turned that into `"None"` would make the one identifier
        # a caller was handed unusable for asking about it again.
        if wanted is not None and str(_of(message, "id", "") or "") not in wanted:
            continue
        current = newest.get(_origin(message))
        written = _aware(_of(message, "created_at"))
        replaced = current if _replaces(current, written) else None
        business_id = str(_of(message, "business_id", "") or "")
        found.append(classify(
            message,
            business_name=named.get(business_id, ""),
            superseded_by=replaced,
            events=history.get(business_id, ()),
            now=now, channels=channels))
    return found


def counts(rows: Sequence[Unreviewed]) -> dict:
    """The tally, by the same names the rows carry.

    Deliberately not a single "blocked" number. An operator deciding where to
    spend an afternoon needs to know that four drafts are addressed to nobody
    and one is waiting on them personally; a count of five blocked things says
    neither.

    Counted in messages, like everything else here, and `total` is therefore the
    length of the list a caller was handed rather than a number of companies.

    Both vocabularies are tallied straight off their mappings, so every name a
    row can carry has a total and no name can be counted twice. The states
    partition the list and sum to `total`; the conditions do not — a row with
    three conditions adds one to each of the three.
    """
    tally = {"total": len(rows)}
    for state, key in STATE_KEYS.items():
        tally[key] = sum(1 for row in rows if row.state == state)
    for condition, key in COUNT_KEYS.items():
        tally[key] = sum(1 for row in rows if condition in row.blocked_on)
    return tally
