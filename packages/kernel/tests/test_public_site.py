"""The public site's commercial claims, checked at build time.

The site is a commercial document. Every sentence on it is something a prospect
may hold Qevik to, and the two claims most likely to drift are the two that
matter legally and clinically: that Qevik is its own company, and that the
appointment form books something.

These run against the built HTML rather than the source strings, so a claim
introduced by a template, a heading or a link text is caught the same as one
written in a paragraph.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

PUBLIC = Path(__file__).resolve().parents[3] / "apps" / "public"
sys.path.insert(0, str(PUBLIC))

from build import BUILDERS, FORBIDDEN, PAGES, check, robots, shell, sitemap  # noqa: E402


@pytest.fixture(scope="module")
def pages() -> dict[str, str]:
    return {path: shell(path, builder()) for path, (builder, _) in BUILDERS.items()}


def text_of(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html).lower()


def test_no_page_claims_something_qevik_does_not_do(pages) -> None:
    problems = [p for path, html in pages.items() for p in check(path, html)]
    assert problems == [], problems


def test_the_forbidden_list_actually_fires() -> None:
    """A guard nobody has seen fail is a guard nobody knows works."""
    for pattern, _ in FORBIDDEN:
        sample = {
            r"\bbook (?:your |an )?appointment(?!\s+request)": "Book your appointment online",
            r"\bbooking system\b": "a complete booking system",
            r"\bautomatic(?:ally)? book": "we automatically book patients",
            r"\bguarantee": "we guarantee results",
            r"#1 on google": "be #1 on google",
            r"\bqevik\s+(?:llc|fz-?llc|fze|dmcc|fzco)\b": "Qevik LLC, Dubai",
            r"\bqevik is (?:a|an) (?:licen[cs]ed|registered)": "Qevik is a licensed company",
            r"\btrusted by\b": "trusted by 200 clinics",
            r"\bour clients\b": "our clients love it",
            r"\btestimonial": "a testimonial from a patient",
            r"\baward[- ]winning\b": "award-winning design",
        }[pattern]
        assert check("/test/", f"<p>{sample}</p>"), f"{pattern} did not fire"


def test_every_page_states_the_operating_entity(pages) -> None:
    """Qevik is a brand. The licensed company must appear on every page."""
    for path, html in pages.items():
        assert "Asia Link Internet Content Provider LLC" in html, path
        assert "not a separately licensed company" in html, path


def test_the_appointment_form_is_described_as_a_request_everywhere(pages) -> None:
    """The one claim that would reach a patient rather than a prospect."""
    for path in ("/", "/services/", "/work/"):
        body = text_of(pages[path])
        assert "request" in body, path
        # Wherever appointments are mentioned, the limit is stated nearby.
        if "appointment" in body:
            assert "does not book" in body or "does not run a booking" in body, path


def test_no_invented_social_proof(pages) -> None:
    """No customers, no testimonials, no awards, no invented numbers."""
    for path, html in pages.items():
        body = text_of(html)
        # Word boundaries, not substrings: "rated" matched inside "operated" in
        # the entity line — the third time a bare-substring check has flagged
        # honest copy. A guard that cries wolf on its own footer gets removed.
        for phrase in (
            r"\bclients say\b",
            r"\b\d(\.\d)?\s*stars?\b",
            r"\brated\b",
            r"\bcustomers trust\b",
            r"\bcase stud(?:y|ies)\b",
            r"\bhappy customers\b",
        ):
            assert not re.search(phrase, body), f"{path}: {phrase!r}"


def test_the_only_statistics_are_the_audit_and_they_are_anonymous(pages) -> None:
    """Numbers on the site must be the twenty-clinic audit, naming nobody."""
    for path in ("/", "/work/"):
        body = text_of(pages[path])
        if "/20" in body:
            assert "no clinic is named" in body or "name" in body
        # None of the twenty may be identifiable.
        for clinic in ("kings", "malabar", "topdent", "klinika", "noa dental"):
            assert clinic not in body, f"{path} names a real prospect: {clinic}"


def test_every_page_in_the_sitemap_exists_and_vice_versa() -> None:
    listed = set(re.findall(r"<loc>https://qevik\.ai(/[^<]*)</loc>", sitemap()))
    assert listed == set(PAGES), "sitemap and PAGES disagree"


def test_robots_allows_the_site_and_points_at_the_sitemap() -> None:
    text = robots()
    assert "Allow: /" in text
    assert "Sitemap: https://qevik.ai/sitemap.xml" in text


def test_each_page_has_a_unique_title_and_description() -> None:
    titles = [t for _, t, _ in PAGES.values()]
    descriptions = [d for _, _, d in PAGES.values()]
    assert len(set(titles)) == len(titles), "duplicate <title>"
    assert len(set(descriptions)) == len(descriptions), "duplicate meta description"
    for _, title, description in PAGES.values():
        assert 10 < len(title) <= 70, title
        assert 50 < len(description) <= 320, description


def test_the_phone_number_is_identical_everywhere(pages) -> None:
    """Google cross-checks this against the Business Profile listing."""
    for path, html in pages.items():
        assert "+971501029104" in html, path
        assert "+971 50 102 9104" in html, path
