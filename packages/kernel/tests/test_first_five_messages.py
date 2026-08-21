"""The outreach generator, tested on the claims it must never make.

These messages go to real businesses who can check every sentence. The tests
below are the sentences that would cost the most if one slipped through, and
each corresponds to something the generator actually produced during the first
run against real data:

- a compliment about "the doctor profiles" addressed to a staffing agency,
  because the multi-industry audit reuses the dental feature vocabulary;
- an offer to fix booking, which Qevik does not build;
- a complaint about a missing Arabic version attached to an English-only sample.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from atlas_kernel.outreach import demos, identity, offer, scoring

INFRA = Path(__file__).resolve().parents[3] / "infra"


@pytest.fixture(scope="module")
def first_five():
    """Load the script by path — `infra/` is tooling, not an installed package."""
    sys.path.insert(0, str(INFRA))
    spec = importlib.util.spec_from_file_location("first_five", INFRA / "first_five.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make(category="dental", absent=("arabic", "whatsapp"), present=("contact_form",),
         unknown=("insurance_info",), unfixable=("booking_link",)) -> scoring.Score:
    observations = (
        [{"feature": f, "status": "not_found"} for f in (*absent, *unfixable)]
        + [{"feature": f, "status": "present"} for f in present]
        + [{"feature": f, "status": "unverified"} for f in unknown]
    )
    return scoring.score(
        business_id="b", name="Test Business | Dubai", website="https://x.ae/",
        phone="052 151 4300", email="", category=category, audit_count=1,
        audit={"http_status": 200, "observations": observations},
    )


#: The generator takes a Selection rather than a bare URL, so the link, the
#: demo's name and the trade it is described as cannot come apart.
DEMO = demos.Selection(demo=None, matched=True,
                       prospect_url="https://sites.qevik.ai/demo-test-business/")
SAMPLE = demos.Selection(demo=demos.BY_SLUG["sample-nar"], matched=True)


# --- what may never appear -------------------------------------------------

def test_no_message_offers_to_fix_booking(first_five) -> None:
    score = make()
    for text in (first_five.whatsapp(score, DEMO, "dental"),
                 first_five.email(score, DEMO, "dental")[1]):
        assert "booking_link" not in text
        assert first_five.audit_message(text, score, chosen=DEMO, category="dental") == []


def test_no_message_mentions_a_not_verified_feature(first_five) -> None:
    score = make(unknown=("insurance_info", "emergency_info"))
    for text in (first_five.whatsapp(score, DEMO, "dental"),
                 first_five.email(score, DEMO, "dental")[1]):
        assert "insurance" not in text.lower()
        assert "emergency" not in text.lower()


def test_no_first_message_names_a_price(first_five) -> None:
    score = make()
    body = first_five.whatsapp(score, DEMO, "dental")
    assert offer.PRICE_IN_FIRST_MESSAGE is False
    assert str(offer.SETUP_AED) not in body and "AED" not in body


def test_no_message_presents_qevik_as_a_licensed_company(first_five) -> None:
    score = make()
    _subject, body = first_five.email(score, DEMO, "dental")
    assert identity.entity_claims(body) == []
    assert identity.LEGAL_ENTITY in body, "the operating entity must still be named"


def test_the_email_states_that_the_form_is_a_placeholder(first_five) -> None:
    """Qevik has no booking backend, and the demo must not imply otherwise."""
    _subject, body = first_five.email(make(), DEMO, "dental")
    assert "placeholder" in body and "does not send anywhere" in body


# --- claims must match what we are linking to ------------------------------

def test_arabic_is_not_raised_when_the_linked_demo_is_english_only(first_five) -> None:
    """Raising it and then linking an English-only page invites the obvious reply."""
    score = make(absent=("arabic", "click_to_call"))
    with_demo = first_five.whatsapp(score, DEMO, "dental")
    with_sample = first_five.whatsapp(score, SAMPLE, "food")
    assert "Arabic version" in with_demo
    assert "Arabic version" not in with_sample
    assert "isn't tappable" in with_sample, "it should fall through to the next gap"


def test_a_sample_is_never_implied_to_be_their_own_site(first_five) -> None:
    score = make()
    sample = first_five.whatsapp(score, SAMPLE, "food")
    assert "Ours, not a client's" in sample
    assert "built you a working example" not in sample

    theirs = first_five.whatsapp(score, DEMO, "dental")
    assert "built you a working example" in theirs
    assert "using only your own details" in theirs


# --- compliments must be true of *this* business ---------------------------

def test_clinical_praise_never_reaches_a_business_that_is_not_a_clinic(first_five) -> None:
    """The generator praised a staffing agency's "doctor profiles"."""
    score = make(category="professional", present=("doctors_team", "social_proof",
                                                   "opening_hours"))
    body = first_five.whatsapp(score, SAMPLE, "professional")
    assert "doctor" not in body.lower()
    assert "patient" not in body.lower()
    assert "opening hours" in body.lower(), "a true, visible strength should still be named"


def test_a_clinic_may_be_praised_clinically(first_five) -> None:
    score = make(category="dental", present=("doctors_team",))
    assert "doctor profiles" in first_five.whatsapp(score, DEMO, "dental")


def test_a_business_with_no_visible_strength_gets_no_invented_one(first_five) -> None:
    score = make(present=("structured_data",))
    body = first_five.whatsapp(score, DEMO, "dental")
    assert "well done" not in body
    assert "I had a look at your site this week." in body


# --- the greeting must not read as a mail merge ----------------------------

@pytest.mark.parametrize(
    "listing,expected",
    [
        ("The TopDent: Dental Clinic in Dubai", "The TopDent"),
        ("Malabar Dental Clinic | Dubai", "Malabar Dental Clinic"),
        ("AHS Catering And Events In Dubai", "AHS Catering And Events"),
        ("Dubai Sky Clinic (by Trio Dental Center)", "Dubai Sky Clinic"),
        ("360 Agency | StaffFinder.io", "360 Agency"),
    ],
)
def test_the_listing_headline_is_trimmed_to_a_usable_name(first_five, listing, expected) -> None:
    assert first_five.short_name(listing) == expected


# --- the guard has to be able to fail --------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "Qevik LLC is a licensed Dubai agency.",
        "We can add online booking for you.",
        "It's AED 1,500 to set up.",
        "I couldn't find any insurance info on your site.",
    ],
)
def test_the_guard_rejects_a_message_that_oversteps(first_five, text) -> None:
    assert first_five.audit_message(text, make(), chosen=DEMO, category="dental") != [], \
        f"guard let through: {text!r}"


def test_a_link_nobody_selected_is_itself_a_fault(first_five) -> None:
    """A message may not carry a demo URL the context never chose."""
    nothing = demos.Selection(demo=None)
    problems = first_five.audit_message(
        "Hello.\n\nhttps://sites.qevik.ai/sample-nar/", make(),
        chosen=nothing, category="dental")
    assert any("none was selected" in p for p in problems), problems


def test_the_guard_passes_a_genuinely_generated_message(first_five) -> None:
    """A check that rejects everything is not a check."""
    score = make()
    assert first_five.audit_message(
        first_five.whatsapp(score, DEMO, "dental"), score,
        chosen=DEMO, category="dental") == []


def test_the_whatsapp_draft_stays_short(first_five) -> None:
    """The brief asks for five to seven short lines, not a technical report."""
    body = first_five.whatsapp(make(), DEMO, "dental")
    prose = [line for line in body.splitlines() if line.strip()]
    assert len(prose) <= 9, prose
    assert len(body) < 700, len(body)
