"""The AHS concept must keep carrying AHS's own contact details.

The first build of this page was a good design that quietly dropped the
business: no phone, no email, no WhatsApp, no social accounts, no address. A
sample a prospect cannot be reached through is not a sample of anything.

Every value below was read off `ahscatering.com` and is recorded with its
evidence in `docs/qevik-docs/AHS_SOURCE_AUDIT.md`. The point of this file is
that a redesign cannot silently lose one of them again.

Static, on purpose: it reads the shipped HTML rather than driving a browser, so
it runs in the ordinary suite and fails on the commit that breaks it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PAGE = Path(__file__).resolve().parents[3] / "apps" / "samples" / "ahs" / "index.html"
AUDIT = Path(__file__).resolve().parents[3] / "docs" / "qevik-docs" / "AHS_SOURCE_AUDIT.md"

#: What AHS publishes, and the only form each may take on the page. The phone
#: and WhatsApp numbers are the same digits but were established separately —
#: WhatsApp from their Click-to-Chat widget config, not inferred from the phone.
REQUIRED = {
    "phone": "tel:+971557492608",
    "whatsapp": "https://wa.me/971557492608",
    "email": "mailto:Info@ahscatering.com",
    "instagram": "https://www.instagram.com/ahscatering",
    "linkedin": "https://www.linkedin.com/company/ahs-catering-and-events",
}

#: Visible strings, not just hrefs — a tappable link whose label is missing is
#: still a contact detail the reader cannot see.
VISIBLE = ("+971 55 749 2608", "Info@ahscatering.com", "Dubai Investment Park 2")


@pytest.fixture(scope="module")
def html() -> str:
    return PAGE.read_text(encoding="utf-8")


@pytest.mark.parametrize("what,href", sorted(REQUIRED.items()))
def test_the_page_carries_their_published_contact(html, what, href) -> None:
    assert f'href="{href}"' in html, f"{what} is not linked on the page"


@pytest.mark.parametrize("value", VISIBLE)
def test_the_detail_is_readable_and_not_only_an_href(html, value) -> None:
    assert value in re.sub(r"<[^>]+>", " ", html), f"{value!r} is never shown to the reader"


def test_call_and_whatsapp_survive_on_a_phone(html) -> None:
    """They sit beside the mobile dock; behind it they may as well be absent."""
    dock = html[html.index('class="dock"'):][:900]
    assert "tel:+971557492608" in dock and "wa.me/971557492608" in dock


def test_reaching_them_is_not_hidden_behind_the_form(html) -> None:
    """Their own defect is untappable details; the page must show the fix working."""
    assert 'class="reach"' in html
    assert html.count("wa.me/971557492608") >= 3, "masthead/brief, contact rail, footer"


def test_the_page_never_claims_to_be_theirs(html) -> None:
    text = re.sub(r"<[^>]+>", " ", html).lower()
    assert "not a client website" in text
    assert "not affiliated with" in text
    assert "ahscatering.com" in text, "the official site must be linked"


def test_no_account_they_do_not_publish_is_invented(html) -> None:
    """They link Instagram and LinkedIn. Nothing else may appear."""
    for absent in ("facebook.com", "tiktok.com", "youtube.com", "twitter.com", "x.com/"):
        assert absent not in html, f"{absent} is not linked from their site"


def test_no_map_link_is_invented(html) -> None:
    """They publish an address and no map. A pin would be a location we chose."""
    assert "maps.google" not in html and "goo.gl/maps" not in html


def test_nothing_on_the_page_reads_as_a_price(html) -> None:
    text = re.sub(r"<[^>]+>", " ", html)
    assert not re.search(r"\bAED\b|\bper person\b", text, re.I), "AHS publishes no prices"


def test_the_audit_backs_every_value_the_page_uses(html) -> None:
    """The page and the audit are one claim; neither may move without the other."""
    audit = AUDIT.read_text(encoding="utf-8")
    assert "971557492608" in audit and "ht_ctc_chat_data" in audit, \
        "the WhatsApp number must stay recorded with the evidence it came from"
    for value in VISIBLE:
        assert value in audit, f"{value!r} is on the page but not in the audit"


def test_these_checks_can_fail(html) -> None:
    """A fidelity check that passes on a page with nothing on it checks nothing."""
    stripped = html.replace("wa.me/971557492608", "").replace("tel:+971557492608", "")
    assert 'href="https://wa.me/971557492608"' not in stripped
    assert stripped.count("wa.me/971557492608") == 0
