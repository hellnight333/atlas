"""The offer, and the rules about when it may be mentioned.

The price is AED 1,500 setup + AED 199/month, and it must not appear in a first
contact. A number in an opening message turns a conversation about their website
into a negotiation before they have looked at anything — the demo is the
argument, and the price answers a question they have not asked yet.

The replies are checked for the claims they must not contain. Every one of them
is a sentence a person will paste into a live conversation, where nothing catches
an overstatement.
"""

from __future__ import annotations

import pytest

from atlas_kernel.outreach import (
    LEGAL_ENTITY,
    MONTHLY_AED,
    PRICE_IN_FIRST_MESSAGE,
    SETUP_AED,
    entity_claims,
    not_interested_reply,
    playbook,
    price_reply,
    send_details_reply,
    who_is_qevik_reply,
)

DEMO = "https://sites.qevik.ai/demo-test/"


def test_the_price_is_what_was_agreed() -> None:
    assert SETUP_AED == 1500
    assert MONTHLY_AED == 199


def test_the_price_is_not_for_a_first_message() -> None:
    assert PRICE_IN_FIRST_MESSAGE is False


def test_no_opening_message_carries_a_number() -> None:
    """The rule, enforced against the actual drafts rather than the intent."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "infra"))
    from outreach_drafts import email_message, whatsapp_message

    row = {
        "name": "Test Dental",
        "existing_website": "https://example.test/",
        "strongest_weakness": "Arabic version",
        "weakness_detail": "",
        "qevik_improvement": "",
        "already_good": ["Map / directions", "Opening hours"],
        "evidence": "",
        "measured": {"http_status": 200, "load_ms": 900, "is_https": True},
        "do_not_say": [],
        "caveats": [],
        "angle": "",
        "contact_method": "WhatsApp",
        "contact_rationale": "",
        "phone": "0501234567",
        "demo_url": DEMO,
        "score": 5,
    }
    _, email = email_message(row)
    whatsapp = whatsapp_message(row)
    for text in (email, whatsapp):
        assert str(SETUP_AED) not in text
        assert str(MONTHLY_AED) not in text
        assert "1,500" not in text
        assert "AED" not in text


def test_the_price_reply_states_both_numbers_plainly() -> None:
    reply = price_reply()
    assert "1,500" in reply and "199" in reply
    assert "AED" in reply
    # No discount, no urgency, no anchoring. Checked as phrases rather than bare
    # words: an earlier version rejected "today" and caught "the appointment form
    # is a placeholder today" — the most honest sentence in the reply. Unlike the
    # "booking system" case, where the phrase is dangerous in any context and the
    # copy was reworded, here the copy is right and the check was wrong.
    for pressure in (
        "discount",
        "limited time",
        "today only",
        "only today",
        "special price",
        "normally aed",
        "usually aed",
        "act now",
    ):
        assert pressure not in reply.lower(), pressure


def test_the_price_reply_repeats_the_placeholder_caveat() -> None:
    """The moment money is discussed is the moment it matters most."""
    reply = price_reply().lower()
    assert "placeholder" in reply
    assert "doesn't submit" in reply or "does not submit" in reply


@pytest.mark.parametrize(
    "reply",
    [price_reply(), send_details_reply(DEMO), not_interested_reply(), who_is_qevik_reply()],
)
def test_no_reply_promises_something_that_does_not_exist(reply: str) -> None:
    lowered = reply.lower()
    for forbidden in (
        "guarantee",
        "guaranteed",
        "#1",
        "rank",
        "traffic",
        "book your appointment",
        "booking system",
        "more patients",
    ):
        assert forbidden not in lowered, f"{forbidden!r} appears in a reply"


@pytest.mark.parametrize(
    "reply",
    [price_reply(), send_details_reply(DEMO), not_interested_reply(), who_is_qevik_reply()],
)
def test_no_reply_presents_qevik_as_a_company(reply: str) -> None:
    assert entity_claims(reply) == []


def test_the_who_is_qevik_reply_names_the_licensed_entity() -> None:
    """Asked directly who they are dealing with, the answer must be complete."""
    reply = who_is_qevik_reply()
    assert LEGAL_ENTITY in reply
    assert "not an agency" in reply.lower()


def test_the_not_interested_reply_does_not_argue() -> None:
    """A long answer to "no" reads as arguing someone out of their decision.

    The only thing it reliably buys is a blocked number.
    """
    reply = not_interested_reply()
    assert len(reply) < 250
    for push in ("but ", "however", "just one", "before you", "are you sure"):
        assert push not in reply.lower(), push


def test_send_details_gives_the_demo_rather_than_a_brochure() -> None:
    reply = send_details_reply(DEMO)
    assert DEMO in reply
    assert "/ar/" in reply
    assert "invented" in reply.lower()


def test_the_playbook_covers_every_question_that_was_asked_for() -> None:
    entries = playbook(DEMO)
    assert len(entries) == 4
    joined = " ".join(entries).lower()
    for topic in ("price", "details", "not interested", "qevik"):
        assert topic in joined, topic
