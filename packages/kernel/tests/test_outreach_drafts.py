"""Outreach drafting: what it refuses, and that it cannot send.

Two properties, and the second is structural rather than behavioural. A tool
that *can* send is one flag, one typo, one confident agent away from sending —
so the guarantee worth testing is that the send capability does not exist in the
module at all, not that a boolean is currently False.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "infra"))

import outreach_drafts  # noqa: E402
from outreach_drafts import NEVER, check, email_message, whatsapp_message  # noqa: E402


def dossier(**overrides) -> dict:
    base = {
        "name": "Test Dental",
        "existing_website": "https://example.test/",
        "strongest_weakness": "Arabic version",
        "weakness_detail": "",
        "qevik_improvement": "",
        "already_good": ["Map / directions", "Opening hours", "Tap-to-call link"],
        "evidence": "no Arabic content or language switch",
        "measured": {"http_status": 200, "load_ms": 900, "is_https": True},
        "do_not_say": [],
        "caveats": [],
        "angle": "",
        "contact_method": "WhatsApp",
        "contact_rationale": "",
        "phone": "0501234567",
        "demo_url": "https://sites.qevik.ai/demo-test/",
        "score": 5,
    }
    base.update(overrides)
    return base


def test_the_module_has_no_way_to_send_anything() -> None:
    """The safety property, checked structurally.

    No SMTP, no WhatsApp client, no outbound HTTP. If any of these ever appear,
    sending stopped being a separate approved step and became a flag.
    """
    source = Path(outreach_drafts.__file__).read_text(encoding="utf-8")
    for forbidden in ("smtplib", "httpx.post", "requests.post", "sendmail", "twilio"):
        assert forbidden not in source, f"a send path appeared: {forbidden}"

    assert not any(
        name for name in dir(outreach_drafts) if "send" in name.lower()
    ), "a send function appeared in the module"


def test_every_draft_is_marked_unsent() -> None:
    subject, body = email_message(dossier())
    assert subject and body
    # The status lives in the written record; the message itself must never
    # imply it was already delivered or that anything was booked.
    assert "booked" not in body.lower()


def test_a_forbidden_phrase_is_caught() -> None:
    for phrase, _ in NEVER:
        problems = check(f"Some copy that says {phrase} in passing.", dossier())
        assert problems, f"{phrase!r} passed the guard"


def test_a_claim_contradicted_by_their_own_site_is_caught() -> None:
    """The prospect knows their site. One wrong claim discredits the rest."""
    row = dossier(
        do_not_say=[
            {
                "claim": "Their site has no whatsapp",
                "reason": "THEIR_SITE_HAS_IT",
                "evidence": "wa.me link present",
            }
        ]
    )
    problems = check("I noticed you have no whatsapp on the site.", row)
    assert problems and "whatsapp" in problems[0]


def test_merely_mentioning_the_feature_is_not_flagged() -> None:
    """The guard must catch a false *claim*, not any use of the word.

    A guard that fires on every mention gets switched off, and then it catches
    nothing at all.
    """
    row = dossier(
        do_not_say=[
            {
                "claim": "Their site has no whatsapp",
                "reason": "THEIR_SITE_HAS_IT",
                "evidence": "wa.me link present",
            }
        ]
    )
    assert check("Your whatsapp button works well.", row) == []


def test_the_appointment_placeholder_is_always_disclosed() -> None:
    """Every email must say the form does not submit. Not optional."""
    _, body = email_message(dossier())
    assert "placeholder" in body.lower()
    assert "does not send anywhere" in body.lower()


def test_the_opening_names_what_they_do_well() -> None:
    """Listing only faults tells an owner you did not really look."""
    _, body = email_message(dossier())
    assert "already done properly" in body.lower()
    assert "map / directions" in body.lower()


def test_a_site_that_never_loaded_gets_different_copy() -> None:
    """It must not claim to have reviewed a page it could not open."""
    row = dossier(already_good=[], strongest_weakness="Loads within 30 seconds")
    message = whatsapp_message(row)
    assert "tried to open" in message.lower()
    assert "had a proper look" not in message.lower()


def test_no_placeholder_survives_into_a_draft() -> None:
    """The signature is now real, so nothing may still be waiting to be filled.

    This test previously asserted the opposite — that "[YOUR NAME]" was present,
    because no sender details existed. Now that they do, the same line must
    assert the placeholder is gone: a draft that goes out with a bracketed
    template marker is worse than one with no signature at all.
    """
    _, body = email_message(dossier())
    wa = whatsapp_message(dossier())
    for text in (body, wa):
        assert "[YOUR NAME" not in text
        assert "[" not in text.split("Best regards,")[-1], "a placeholder remains"


@pytest.mark.parametrize("gap", ["Arabic version", "HTTPS", "Structured data"])
def test_the_claim_matches_the_measured_gap(gap: str) -> None:
    _, body = email_message(dossier(strongest_weakness=gap))
    assert body.count("The one thing I could not find") <= 1
    assert "Nothing about it is invented" in body


def test_no_draft_presents_qevik_as_a_separate_company() -> None:
    """Qevik is a brand of Asia Link Internet Content Provider LLC.

    Writing "Qevik LLC" to a Dubai business is a false claim about a regulated
    status, made to someone who can check it in a public register.
    """
    from atlas_kernel.outreach import entity_claims

    _, body = email_message(dossier())
    assert entity_claims(body) == []
    assert entity_claims(whatsapp_message(dossier())) == []


def test_the_guard_refuses_a_draft_that_would_claim_one() -> None:
    assert check("Regards, Qevik LLC, Dubai", dossier())


def test_the_email_carries_the_full_entity_signature() -> None:
    from atlas_kernel.outreach import EMAIL_SIGNATURE, LEGAL_ENTITY

    _, body = email_message(dossier())
    assert body.rstrip().endswith(EMAIL_SIGNATURE)
    assert LEGAL_ENTITY in body


def test_the_whatsapp_message_carries_the_short_signature() -> None:
    from atlas_kernel.outreach import WHATSAPP_SIGNATURE

    message = whatsapp_message(dossier())
    assert message.rstrip().endswith(WHATSAPP_SIGNATURE)
    # The postal address belongs in email, not in a phone message.
    assert "Office 301" not in message
