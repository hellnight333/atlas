"""The first commercial test, recorded as events rather than as a status column.

The question this exists to answer is narrow and expensive to get wrong: **will
any of these twenty businesses engage with the offer?** Answering it needs the
whole sequence — what was sent, in which wording, on which channel, what came
back, what they objected to, what price was named, and how it ended.

Recorded as `BusinessEvent`s on the timeline each business already has. No new
table, and no mutable `stage` field, for the reason the model itself gives: a
funnel computed from current state cannot tell you that a prospect replied, took
a meeting, and then went quiet. Only the sequence can, and only if nothing
overwrites it.

`message_version` is a digest of the exact words sent. Two prospects who receive
different wording are two data points, not one, and "which version got replies"
is unanswerable a week later from memory. The digest is short on purpose — it is
a label for a human comparing runs, not a security property.

Nothing here sends anything. The first contact is made by hand, from a phone,
and `record_sent` is how a person tells the system it happened.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from ..opportunity.models import BusinessEvent

#: This experiment's namespace on the shared timeline.
FACTORY = "sales_experiment"


class Stage(StrEnum):
    """What happened, in the order it can happen.

    Not a state machine — a vocabulary. A prospect can object before a meeting
    or after one, name a price and then go quiet, or reply once and never again.
    Forcing an order here would mean discarding the sequences that are most
    worth knowing about.
    """

    PREPARED = "experiment_prepared"
    SENT = "experiment_sent"
    RESPONSE = "experiment_response"
    MEETING = "experiment_meeting"
    OBJECTION = "experiment_objection"
    PRICE_DISCUSSED = "experiment_price_discussed"
    OUTCOME = "experiment_outcome"


class Response(StrEnum):
    """How a prospect answered, if they did."""

    NONE = "no_reply"
    INTERESTED = "interested"
    QUESTIONS = "questions"
    NOT_NOW = "not_now"
    DECLINED = "declined"
    HOSTILE = "hostile"


class Result(StrEnum):
    """How it ended."""

    OPEN = "open"
    NO_REPLY = "no_reply"
    LOST = "lost"
    WON = "won"
    #: They engaged and it went nowhere for a reason worth keeping separate from
    #: a flat loss — the offer was wrong, not the prospect.
    DISQUALIFIED = "disqualified"


def message_version(body: str) -> str:
    """A short, stable label for one exact wording."""
    return hashlib.sha256(body.strip().encode("utf-8")).hexdigest()[:12]


def _event(
    business_id: str, stage: Stage, detail: dict[str, Any], *, actor: str
) -> BusinessEvent:
    return BusinessEvent(
        business_id=business_id,
        factory=FACTORY,
        kind=str(stage),
        actor=actor,
        detail=detail,
    )


def record_prepared(
    business_id: str,
    *,
    prospect: str,
    channel: str,
    body: str,
    demo_url: str,
    claim: str,
    actor: str = "operator",
) -> BusinessEvent:
    """A draft exists and is ready to be sent by hand. Nothing has gone out."""
    return _event(
        business_id,
        Stage.PREPARED,
        {
            "prospect": prospect,
            "channel": channel,
            "message_version": message_version(body),
            "demo_url": demo_url,
            "claim": claim,
            "sent": False,
        },
        actor=actor,
    )


def record_sent(
    business_id: str,
    *,
    prospect: str,
    channel: str,
    body: str,
    sent_at: datetime,
    actor: str = "operator",
) -> BusinessEvent:
    """A human sent this, by hand, at this time.

    `sent_at` is required and passed in rather than defaulted to now, because
    this is usually recorded after the fact — typing a message on a phone and
    logging it are two separate moments, and defaulting quietly records the
    second as if it were the first.
    """
    if sent_at.tzinfo is None:
        raise ValueError("sent_at must be timezone-aware; a naive time is ambiguous")
    return _event(
        business_id,
        Stage.SENT,
        {
            "prospect": prospect,
            "channel": channel,
            "message_version": message_version(body),
            "sent_at": sent_at.isoformat(),
            "sent_by": "manual",
        },
        actor=actor,
    )


def record_response(
    business_id: str,
    *,
    response: Response,
    at: datetime,
    verbatim: str = "",
    actor: str = "operator",
) -> BusinessEvent:
    """What came back. `verbatim` is their words, unsummarised.

    Summarising a reply loses the thing most worth having — a prospect saying
    "we already pay someone for this" and one saying "we don't need a website"
    are the same category and completely different problems.
    """
    return _event(
        business_id,
        Stage.RESPONSE,
        {"response": str(response), "at": at.isoformat(), "verbatim": verbatim},
        actor=actor,
    )


def record_meeting(
    business_id: str,
    *,
    happened: bool,
    at: datetime,
    note: str = "",
    actor: str = "operator",
) -> BusinessEvent:
    return _event(
        business_id,
        Stage.MEETING,
        {"happened": happened, "at": at.isoformat(), "note": note},
        actor=actor,
    )


def record_objection(
    business_id: str, *, objection: str, verbatim: str = "", actor: str = "operator"
) -> BusinessEvent:
    """One objection per event.

    Kept separate rather than as a list on an outcome, so the same objection
    appearing across five prospects is countable. That count is the most
    actionable output of the whole experiment: it says what to change.
    """
    return _event(
        business_id,
        Stage.OBJECTION,
        {"objection": objection, "verbatim": verbatim},
        actor=actor,
    )


def record_price(
    business_id: str,
    *,
    amount: Decimal | float | int,
    currency: str = "AED",
    recurring: bool = False,
    accepted: bool | None = None,
    actor: str = "operator",
) -> BusinessEvent:
    """A price was named out loud. `accepted` is None until they answer."""
    return _event(
        business_id,
        Stage.PRICE_DISCUSSED,
        {
            "amount": str(amount),
            "currency": currency,
            "recurring": recurring,
            "accepted": accepted,
        },
        actor=actor,
    )


def record_outcome(
    business_id: str,
    *,
    result: Result,
    reason: str = "",
    actor: str = "operator",
) -> BusinessEvent:
    return _event(
        business_id,
        Stage.OUTCOME,
        {"result": str(result), "reason": reason, "at": datetime.now(UTC).isoformat()},
        actor=actor,
    )


def fold(events: list[BusinessEvent]) -> dict[str, Any]:
    """Current state of one prospect's experiment, derived from its events.

    Derived rather than stored. The events remain the truth; this is a view, and
    a wrong view can be fixed by changing this function rather than by rewriting
    history.
    """
    ordered = sorted(
        (e for e in events if e.factory == FACTORY), key=lambda e: (e.at, e.kind)
    )

    state: dict[str, Any] = {
        "prospect": "",
        "channel": "",
        "message_version": "",
        "demo_url": "",
        "sent_at": None,
        "response": str(Response.NONE),
        "response_verbatim": "",
        "meeting": False,
        "objections": [],
        "price_discussed": None,
        "result": str(Result.OPEN),
        "events": len(ordered),
    }

    for event in ordered:
        detail = event.detail or {}
        kind = event.kind

        if kind == Stage.PREPARED:
            state.update(
                prospect=detail.get("prospect", state["prospect"]),
                channel=detail.get("channel", state["channel"]),
                message_version=detail.get("message_version", ""),
                demo_url=detail.get("demo_url", ""),
            )
        elif kind == Stage.SENT:
            state["sent_at"] = detail.get("sent_at")
            state["channel"] = detail.get("channel", state["channel"])
            state["message_version"] = detail.get(
                "message_version", state["message_version"]
            )
        elif kind == Stage.RESPONSE:
            state["response"] = detail.get("response", state["response"])
            state["response_verbatim"] = detail.get("verbatim", "")
        elif kind == Stage.MEETING:
            state["meeting"] = bool(detail.get("happened"))
        elif kind == Stage.OBJECTION:
            state["objections"].append(detail.get("objection", ""))
        elif kind == Stage.PRICE_DISCUSSED:
            state["price_discussed"] = {
                "amount": detail.get("amount"),
                "currency": detail.get("currency", "AED"),
                "recurring": detail.get("recurring", False),
                "accepted": detail.get("accepted"),
            }
        elif kind == Stage.OUTCOME:
            state["result"] = detail.get("result", state["result"])

    # An experiment with no send is not "no reply" — nobody was asked. Reporting
    # it as no_reply would put a zero in the denominator of the only number this
    # experiment produces.
    if state["sent_at"] is None:
        state["response"] = "not_contacted"

    return state
