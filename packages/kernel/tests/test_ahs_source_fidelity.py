"""The AHS concept must keep carrying AHS's own business, on every route.

The first build of this page was a good design that quietly dropped the
business: no phone, no email, no WhatsApp, no social accounts, no address. That
was one page. It is now ninety-eight, in two languages, and a generator makes
that same mistake everywhere at once — so this checks the generated output
rather than a file somebody remembered to look at.

Every value below was read off ahscatering.com and is carried in
`apps/samples/ahs/source.py` with its provenance.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

AHS = Path(__file__).resolve().parents[3] / "apps" / "samples" / "ahs"


def _load_build():
    """Load the AHS generator under a name of its own.

    Two things bite here. `apps/public/build.py` is already registered as
    `build`, so loading this one under that name silently returns the other
    module. And the dataclasses in `source` resolve their annotations through
    `sys.modules[cls.__module__]`, so `source` has to be genuinely imported
    rather than executed anonymously — which happens for free, because the
    generator imports it itself.
    """
    if "ahs_build" in sys.modules:
        return sys.modules["ahs_build"]
    sys.path.insert(0, str(AHS))
    spec = importlib.util.spec_from_file_location("ahs_build", AHS / "build.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["ahs_build"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def src():
    _load_build()
    return sys.modules["source"]


@pytest.fixture(scope="module")
def pages() -> dict[str, str]:
    return _load_build().build()


@pytest.fixture(scope="module")
def routes(pages) -> dict[str, str]:
    return {k: v for k, v in pages.items() if k.endswith("index.html")}


def text_of(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


# --- their business, on every page ----------------------------------------

def test_the_build_produces_both_languages(routes) -> None:
    arabic = [r for r in routes if r.startswith("ar/")]
    assert len(arabic) == len(routes) - len(arabic), "every English route needs an Arabic one"
    assert len(routes) > 90, len(routes)


def test_every_route_carries_every_published_contact(routes, src) -> None:
    required = (f'href="tel:{src.PHONE_E164}"', f'href="https://wa.me/{src.WHATSAPP}"',
                f'href="mailto:{src.EMAIL}"', src.INSTAGRAM, src.LINKEDIN)
    for route, html in routes.items():
        for needle in required:
            assert needle in html, f"{route} lost {needle}"


def test_every_route_has_a_persistent_whatsapp_affordance(routes) -> None:
    for route, html in routes.items():
        assert 'class="wafloat"' in html, route


def test_the_address_is_shown_and_no_map_is_invented(routes, src) -> None:
    for route, html in routes.items():
        assert src.ADDRESS in text_of(html) or "مجمع دبي للاستثمار" in text_of(html), route
        assert "maps.google" not in html and "goo.gl/maps" not in html, route


def test_no_account_they_do_not_publish_appears(routes) -> None:
    for route, html in routes.items():
        for absent in ("facebook.com", "tiktok.com", "youtube.com", "twitter.com", "x.com/"):
            assert absent not in html, f"{absent} in {route}"


# --- it is a concept, and says so ------------------------------------------

def test_every_route_disclaims_the_relationship(routes) -> None:
    for route, html in routes.items():
        body = text_of(html)
        assert "Not a client website" in body, route
        assert "Not affiliated with" in body, route
        assert "ahscatering.com" in body, route


def test_nothing_anywhere_reads_as_a_price(routes) -> None:
    for route, html in routes.items():
        assert not re.search(r"\bAED\b|\bper person\b", text_of(html), re.I), route


def test_no_photograph_of_theirs_is_rehosted(pages) -> None:
    """Rights are uncertain, so every image region is a composed treatment."""
    for route, html in pages.items():
        assert "ahscatering.com/wp-content" not in html, route
        assert "<img" not in html, f"{route} embeds an image; treatments are CSS"


# --- the language pair -----------------------------------------------------

def test_hreflang_is_reciprocal(routes) -> None:
    for route, html in routes.items():
        en = re.search(r'hreflang="en" href="([^"]+)"', html)
        ar = re.search(r'hreflang="ar" href="([^"]+)"', html)
        assert en and ar, route
        assert en.group(1) != ar.group(1), route
        assert "/ar/" in ar.group(1) and "/ar/" not in en.group(1), route


def test_the_arabic_routes_are_actually_arabic(routes) -> None:
    for route, html in routes.items():
        if not route.startswith("ar/"):
            continue
        assert 'lang="ar" dir="rtl"' in html, route
        arabic_chars = len(re.findall(r"[؀-ۿ]", text_of(html)))
        assert arabic_chars > 200, f"{route} has only {arabic_chars} Arabic characters"


def test_the_arabic_build_translates_our_own_labels(pages) -> None:
    """An "Arabic version" that leaves our classifications in English is a
    laid-out-backwards English page. Their page titles stay verbatim — those are
    their words — but every label the concept itself chose must be translated."""
    index = pages["ar/work/index.html"]
    chips = re.findall(r'data-g="(?:kind|sector)" data-v="[^"]*" aria-pressed="[a-z]+">([^<]+)<',
                       index)
    assert len(chips) > 20, chips
    latin = [c for c in chips if re.search(r"[A-Za-z]{3}", c)]
    assert not latin, f"untranslated filter labels: {latin}"


def test_the_english_routes_are_ltr(routes) -> None:
    for route, html in routes.items():
        if route.startswith("ar/"):
            continue
        assert 'lang="en" dir="ltr"' in html, route


# --- the thing the concept is arguing --------------------------------------

def test_unpublished_fields_are_shown_as_unpublished(pages, src) -> None:
    """The argument to AHS is their own missing data. It must be visible."""
    page = pages["work/nestle/index.html"]
    assert "Not published" in text_of(page)
    assert "Nestlé" in text_of(page), "what they do publish must be there too"


def test_the_work_index_lists_every_case(pages, src) -> None:
    index = pages["work/index.html"]
    assert index.count('class="rec"') == len(src.CASES) == 32
    for case in src.CASES:
        assert f'/work/{case.slug}/' in index, case.slug


def test_every_case_has_its_own_route(pages, src) -> None:
    for case in src.CASES:
        assert f"work/{case.slug}/index.html" in pages, case.slug
        assert f"ar/work/{case.slug}/index.html" in pages, case.slug


def test_seo_basics_are_present_and_unique(routes) -> None:
    titles = {}
    for route, html in routes.items():
        title = re.search(r"<title>(.*?)</title>", html, re.S)
        desc = re.search(r'name="description" content="([^"]*)"', html)
        assert title and title.group(1).strip(), route
        assert desc and desc.group(1).strip(), route
        assert 'rel="canonical"' in html, route
        titles.setdefault(title.group(1), []).append(route)
    dupes = {t: r for t, r in titles.items() if len(r) > 1}
    assert not dupes, f"duplicate titles: {list(dupes)[:3]}"


def test_no_aspect_ratio_box_can_dictate_its_own_width(pages) -> None:
    """`aspect-ratio` with a `min-height` and an auto width sets the *width*.

    The hero did exactly that — 16/9 against a 640px min-height demanded 1138px
    — so the mobile homepage rendered zoomed out to a third of its size while a
    scrollWidth-vs-innerWidth check reported no overflow, because innerWidth had
    expanded to match. Every ratio box pins its width.
    """
    css = next(v for k, v in pages.items() if k.endswith(".css"))
    ratio = re.search(r"\.ratio\{([^}]*)\}", css)
    assert ratio and "width:100%" in ratio.group(1), ratio.group(1) if ratio else "no .ratio"
    for page in pages.values():
        assert "plate ratio wide\"\nstyle=\"min-height" not in page


def test_the_generator_refuses_a_page_missing_its_contacts(pages) -> None:
    """A guard nobody has seen fail is a guard nobody knows works."""
    build = _load_build()
    broken = dict(pages)
    broken["work/index.html"] = broken["work/index.html"].replace(
        f'href="https://wa.me/{sys.modules["source"].WHATSAPP}"', 'href="#"')
    with pytest.raises(build.Incomplete):
        build.verify(broken)
