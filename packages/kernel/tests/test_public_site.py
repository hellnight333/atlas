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

from build import (  # noqa: E402
    ARTWORK,
    BUILDERS,
    FORBIDDEN,
    NOINDEX,
    PAGES,
    check,
    robots,
    shell,
    sitemap,
)


@pytest.fixture(scope="module")
def pages() -> dict[str, str]:
    return {path: shell(path, builder()) for path, (builder, _) in BUILDERS.items()}


@pytest.fixture
def artwork() -> None:
    """For the two tests that read the image files rather than the HTML.

    `apps/public/assets/` is covered by the blanket `assets/` rule in .gitignore
    — see the note at the top of `infra/deploy_public.sh` — so it is not in the
    repository and a checkout is not guaranteed to have it. Everything else in
    this file asserts against strings and runs anywhere; these two cannot, and
    a missing local prerequisite has to say so by name rather than report the
    site as broken.

    The directory being absent is the whole of the condition. A directory that
    is here and short a file is the drift these two exist to catch, and still
    fails.
    """
    if not ARTWORK.is_dir():
        pytest.skip(
            f"{ARTWORK} is not in this working tree. The artwork is covered by the "
            "blanket `assets/` rule in .gitignore and is not in the repository — "
            "see infra/deploy_public.sh."
        )


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
    """Qevik is a brand. The licensed company must appear on every page.

    The entity name stays Latin in both languages — an Arabic rendering of it
    would name a company that does not legally exist — but the disclaimer is
    translated, so both phrasings are accepted.
    """
    for path, html in pages.items():
        assert "Asia Link Internet Content Provider LLC" in html, path
        assert (
            "not a separately licensed company" in html
            or "ليست شركة مرخّصة بشكل منفصل" in html
        ), path


def test_the_arabic_routes_exist_and_are_canonical_for_themselves(pages) -> None:
    """Pointing the Arabic canonical at English declares it a duplicate."""
    import re as _re

    for path in ("/ar/", "/ar/services/", "/ar/work/", "/ar/about/", "/ar/contact/"):
        assert path in pages, f"{path} was not built"
        html = pages[path]
        canonical = _re.search(r'rel="canonical" href="([^"]*)"', html).group(1)
        assert canonical == f"https://qevik.ai{path}", f"{path} -> {canonical}"
        assert 'lang="ar" dir="rtl"' in html, path


def test_english_and_arabic_point_at_each_other(pages) -> None:
    for english, arabic in (
        ("/", "/ar/"), ("/services/", "/ar/services/"), ("/work/", "/ar/work/"),
        ("/about/", "/ar/about/"), ("/contact/", "/ar/contact/"),
    ):
        for path in (english, arabic):
            html = pages[path]
            assert f'hreflang="en" href="https://qevik.ai{english}"' in html, path
            assert f'hreflang="ar" href="https://qevik.ai{arabic}"' in html, path


def test_no_arabic_page_is_mostly_english(pages) -> None:
    """A page that renders RTL but reads English is a toggle, not a translation."""
    import re as _re

    for path in ("/ar/", "/ar/services/", "/ar/work/", "/ar/about/", "/ar/contact/"):
        text = _re.sub(r"<[^>]+>", " ", pages[path])
        arabic_chars = len(_re.findall(r"[\u0600-\u06ff]", text))
        latin_words = len(_re.findall(r"\b[A-Za-z]{4,}\b", text))
        assert arabic_chars > 400, f"{path}: only {arabic_chars} Arabic characters"
        assert arabic_chars > latin_words * 3, (
            f"{path}: {latin_words} Latin words against {arabic_chars} Arabic characters"
        )


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
    """Minus the error pages, which are built and served but never advertised."""
    listed = set(re.findall(r"<loc>https://qevik\.ai(/[^<]*)</loc>", sitemap()))
    assert listed == set(PAGES) - set(NOINDEX), "sitemap and PAGES disagree"


def test_the_error_pages_are_built_from_the_same_shell_as_the_rest(pages) -> None:
    """A 404 is the page most likely to be somebody's first sight of the site.

    It is built here rather than left to the web server so it arrives with the
    navigation, the phone number and the operating-entity line — see
    `test_public_serving.py` for the serving half of the same fix.
    """
    for path in NOINDEX:
        assert path in pages, f"{path} was not built"
        assert '<meta name="robots" content="noindex">' in pages[path], path


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


# --- the showcase is a promise about things that exist ----------------------
#
# Three ways a showcase entry ships broken, all silently: the thumbnail is
# missing so the card renders a blank box; the sample is never deployed so
# "Open the live product" 404s; or it is flagged bilingual, which emits a link
# to a separate /ar/ URL that was never built. Word Rush switches language in
# place rather than by URL, and marking it bilingual would have published
# exactly that dead link.

from build import SHOWCASE, SHOWCASE_TABS  # noqa: E402

#: Generated by samples.py through the vertical renderer, not a hand-built file.
_GENERATED = {"clinic"}


def _portfolio() -> dict[str, str]:
    source = (PUBLIC.parents[1] / "infra" / "deploy_samples.py").read_text(encoding="utf-8")
    block = source[source.index("PORTFOLIO = {"):source.index("}", source.index("PORTFOLIO = {"))]
    return dict(re.findall(r'"([\w-]+)":\s*"([\w-]+)"', block))


def test_every_showcase_entry_has_the_thumbnail_it_renders(artwork) -> None:
    missing = [
        f"{key} -> {data['shot']}"
        for key, data in SHOWCASE.items()
        if not (ARTWORK / data["shot"]).exists()
    ]
    assert missing == [], missing


def test_every_hand_built_showcase_entry_is_actually_deployed() -> None:
    published = set(_portfolio().values())
    undeployed = [
        f"{key} -> {data['slug']}"
        for key, data in SHOWCASE.items()
        if key not in _GENERATED and data["slug"] not in published
    ]
    assert undeployed == [], undeployed


def test_a_bilingual_flag_means_a_real_arabic_route(pages) -> None:
    """The flag emits `<live>/ar/`, so only the vertical renderer earns it.

    A sample that switches language in place has no second URL, and claiming
    otherwise publishes a link to nothing.
    """
    wrong = [
        key for key, data in SHOWCASE.items()
        if data["bilingual"] and key not in _GENERATED
    ]
    assert wrong == [], wrong


def test_every_switcher_tab_points_at_a_real_sample() -> None:
    unknown = [(key, sample) for key, _, _, sample, *_ in SHOWCASE_TABS if sample not in SHOWCASE]
    assert unknown == [], unknown


def test_switcher_tabs_do_not_show_the_same_sample_twice() -> None:
    shown = [sample for _, _, _, sample, *_ in SHOWCASE_TABS]
    assert len(shown) == len(set(shown)), shown


def test_every_switcher_tab_is_written_in_both_languages() -> None:
    arabic = re.compile(r"[؀-ۿ]")
    thin = [
        key for key, en_label, ar_label, _, en_desc, ar_desc, en_do, ar_do in SHOWCASE_TABS
        if not arabic.search(ar_label) or not arabic.search(ar_desc) or not arabic.search(ar_do)
        or not en_label.strip() or not en_desc.strip() or not en_do.strip()
    ]
    assert thin == [], thin


def test_every_asset_a_page_references_exists(pages, artwork) -> None:
    """A page may only point at files that are actually there.

    `fingerprinted()` falls back to the bare filename for an asset it does not
    know, so a card referencing an uncopied image builds clean, deploys clean,
    and renders a broken box. Two did: the copy list was maintained by hand
    beside SHOWCASE and drifted the moment SHOWCASE grew.
    """
    missing = sorted(
        {
            name
            for html in pages.values()
            for name in re.findall(r"/assets/([\w.\-]+)", html)
            # Built at render time rather than copied from disk.
            if not name.startswith("favicon") and not (ARTWORK / name).exists()
        }
    )
    assert missing == [], missing
