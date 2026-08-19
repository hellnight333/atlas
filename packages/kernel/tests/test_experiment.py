"""The commercial experiment: recorded as events, read by folding them.

The question is whether any of twenty businesses will engage with the offer. The
risk in measuring it is not a crash — it is a number that looks answered and is
not: a prospect nobody contacted counted as "no reply", a reply summarised until
the reason is gone, a funnel computed from a status column that was overwritten.

These tests are about those.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from atlas_kernel.outreach import experiment as ex

BUSINESS = "biz-1"
NOW = datetime(2026, 8, 19, 10, 30, tzinfo=UTC)
BODY = "Hello — I'm Ayoub. I build websites for dental clinics in Dubai."


def test_a_prospect_nobody_contacted_is_not_a_no_reply() -> None:
    """The distinction the whole measurement rests on.

    "No reply" is a result. "Not contacted" is an absence of an experiment.
    Counting the second as the first puts a zero in the numerator and a one in
    the denominator of the only ratio this exercise produces.
    """
    prepared = ex.record_prepared(
        BUSINESS, prospect="Test", channel="whatsapp", body=BODY,
        demo_url="https://x/y", claim="",
    )
    state = ex.fold([prepared])
    assert state["response"] == "not_contacted"
    assert state["sent_at"] is None
    assert state["result"] == "open"


def test_sending_then_silence_is_a_no_reply() -> None:
    events = [
        ex.record_prepared(
            BUSINESS, prospect="Test", channel="whatsapp", body=BODY,
            demo_url="https://x/y", claim="",
        ),
        ex.record_sent(
            BUSINESS, prospect="Test", channel="whatsapp", body=BODY, sent_at=NOW
        ),
    ]
    state = ex.fold(events)
    assert state["sent_at"] == NOW.isoformat()
    assert state["response"] == "no_reply"


def test_a_naive_sent_time_is_refused() -> None:
    """The operator is at +04:00 and the server records UTC.

    A naive timestamp silently shifts by four hours, and the one thing this
    experiment measures is how long a reply took.
    """
    with pytest.raises(ValueError, match="timezone-aware"):
        ex.record_sent(
            BUSINESS, prospect="Test", channel="whatsapp", body=BODY,
            sent_at=datetime(2026, 8, 19, 10, 30),
        )


def test_the_message_version_distinguishes_wordings() -> None:
    """Two prospects who got different words are two data points, not one."""
    first = ex.message_version("Hello, version one.")
    second = ex.message_version("Hello, version two.")
    assert first != second
    assert ex.message_version("  Hello, version one.  ") == first, "whitespace only"


def test_the_reply_is_kept_verbatim() -> None:
    """"We already pay someone" and "we don't need a website" are the same
    category and completely different problems."""
    events = [
        ex.record_sent(
            BUSINESS, prospect="T", channel="whatsapp", body=BODY, sent_at=NOW
        ),
        ex.record_response(
            BUSINESS,
            response=ex.Response.NOT_NOW,
            at=NOW + timedelta(hours=2),
            verbatim="we already pay an agency for this",
        ),
    ]
    state = ex.fold(events)
    assert state["response"] == "not_now"
    assert state["response_verbatim"] == "we already pay an agency for this"


def test_objections_accumulate_and_stay_countable() -> None:
    """The most actionable output: the same objection across five prospects."""
    events = [
        ex.record_sent(BUSINESS, prospect="T", channel="whatsapp", body=BODY, sent_at=NOW),
        ex.record_objection(BUSINESS, objection="already pay someone"),
        ex.record_objection(BUSINESS, objection="no arabic patients"),
    ]
    assert ex.fold(events)["objections"] == ["already pay someone", "no arabic patients"]


def test_a_price_is_recorded_before_it_is_answered() -> None:
    events = [
        ex.record_sent(BUSINESS, prospect="T", channel="whatsapp", body=BODY, sent_at=NOW),
        ex.record_price(BUSINESS, amount=1500, currency="AED", recurring=False),
    ]
    price = ex.fold(events)["price_discussed"]
    assert price["amount"] == "1500" and price["currency"] == "AED"
    assert price["accepted"] is None, "unanswered must not read as refused"


def test_the_whole_sequence_survives_going_backwards() -> None:
    """Replied, met, then went quiet. A status column cannot express this.

    This is the shape the append-only record exists for: the outcome is a loss,
    and the history still shows they engaged — which is a completely different
    lesson from never answering.
    """
    events = [
        ex.record_prepared(
            BUSINESS, prospect="T", channel="whatsapp", body=BODY,
            demo_url="https://x/y", claim="",
        ),
        ex.record_sent(BUSINESS, prospect="T", channel="whatsapp", body=BODY, sent_at=NOW),
        ex.record_response(
            BUSINESS, response=ex.Response.INTERESTED, at=NOW + timedelta(hours=1)
        ),
        ex.record_meeting(BUSINESS, happened=True, at=NOW + timedelta(days=2)),
        ex.record_price(BUSINESS, amount=2000),
        ex.record_objection(BUSINESS, objection="too expensive"),
        ex.record_outcome(BUSINESS, result=ex.Result.LOST, reason="price"),
    ]
    state = ex.fold(events)
    assert state["response"] == "interested"
    assert state["meeting"] is True
    assert state["objections"] == ["too expensive"]
    assert state["result"] == "lost"
    assert state["events"] == 7


def test_events_from_other_factories_are_ignored() -> None:
    """The timeline is shared. Folding must read only this experiment's events."""
    from atlas_kernel.opportunity.models import BusinessEvent

    noise = BusinessEvent(
        business_id=BUSINESS, factory="website", kind="website_audited", detail={}
    )
    events = [
        noise,
        ex.record_sent(BUSINESS, prospect="T", channel="whatsapp", body=BODY, sent_at=NOW),
    ]
    assert ex.fold(events)["events"] == 1


def test_every_field_the_experiment_must_capture_is_present() -> None:
    """The ten things asked for, checked as a set rather than one at a time."""
    state = ex.fold(
        [
            ex.record_prepared(
                BUSINESS, prospect="T", channel="whatsapp", body=BODY,
                demo_url="https://x/y", claim="c",
            ),
            ex.record_sent(BUSINESS, prospect="T", channel="whatsapp", body=BODY, sent_at=NOW),
            ex.record_response(BUSINESS, response=ex.Response.QUESTIONS, at=NOW),
            ex.record_meeting(BUSINESS, happened=True, at=NOW),
            ex.record_objection(BUSINESS, objection="o"),
            ex.record_price(BUSINESS, amount=1),
            ex.record_outcome(BUSINESS, result=ex.Result.WON),
        ]
    )
    for field in (
        "prospect", "channel", "message_version", "sent_at", "response",
        "meeting", "objections", "price_discussed", "result",
    ):
        assert field in state, field
        assert state[field] not in (None, ""), f"{field} was not captured"
