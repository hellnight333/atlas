"""The files nobody reads, tested on the ways they publish something by mistake.

A sitemap and a robots file are boring until one of them is wrong, and then they
are the mechanism by which a customer's unfinished site appears in Google. That
is not a bug you fix — nobody can withdraw somebody else's page from an index on
their behalf.

So the defaults here are the safe ones and the tests are about the defaults: an
unpublished bundle disallows everything, a sitemap with no agreed domain uses
relative paths, and a canonical tag pointing at a preview address does not exist.

The second theme is self-consistency. Atlas detects missing sitemaps, missing
metadata and broken internal links on strangers' websites and sells the repair.
A generated bundle carrying any of those would be selling a fix for a defect we
ship.
"""

from __future__ import annotations

import pytest

from atlas_kernel.website import seo
from atlas_kernel.website.content import (
    ContactDetails,
    Fact,
    FactSource,
    OpeningHours,
    Prose,
    Service,
    SiteContent,
)
from atlas_kernel.website.generation import generate

WEEK = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
        "Sunday")


def _f(value: str) -> Fact:
    return Fact(value=value, source=FactSource.OPERATOR)


@pytest.fixture
def multipage() -> SiteContent:
    """Enough content that the theme splits, so links are real."""
    return SiteContent(
        business_name=_f("Al Hamra Facilities"),
        tagline=_f("Air-conditioning and plumbing across Dubai"),
        about=Prose(text="A" * 500, source=FactSource.OPERATOR),
        services=[Service(name=_f(f"Service {i}"),
                          description=Prose(text="What it covers and what is "
                                                 "charged separately.",
                                            source=FactSource.OPERATOR))
                  for i in range(6)],
        hours=OpeningHours(days={day: _f("8am to 6pm") for day in WEEK}),
        contact=ContactDetails(phone=_f("+971 4 555 0100"),
                               email=_f("hello@alhamra.ae"),
                               address=_f("Unit 4, Al Quoz")),
        location=_f("Dubai"))


@pytest.fixture
def simple() -> SiteContent:
    return SiteContent(business_name=_f("Corner Cafe"),
                       contact=ContactDetails(phone=_f("+971 4 555 0111")))


# ============================================ nothing is published by accident

def test_an_unpublished_bundle_disallows_every_crawler(simple) -> None:
    """The common case is a preview, and a preview in a search index is the
    customer's unfinished site in somebody else's results."""
    files, _ = generate(simple)
    assert files["robots.txt"] == seo.PREVIEW_ROBOTS
    assert "Disallow: /" in files["robots.txt"]


def test_a_domain_alone_does_not_make_a_site_indexable(simple) -> None:
    """Knowing the address is not the same as having agreed to publish."""
    files, provenance = generate(simple, website="alhamra.ae")
    assert "Disallow: /" in files["robots.txt"]
    assert provenance["seo"]["indexable"] is False


def test_publishing_requires_both_a_domain_and_the_decision(simple) -> None:
    files, provenance = generate(simple, website="alhamra.ae", published=True)
    assert "Allow: /" in files["robots.txt"]
    assert "Sitemap: https://alhamra.ae/sitemap.xml" in files["robots.txt"]
    assert provenance["seo"]["indexable"] is True


def test_publishing_with_no_domain_still_disallows(simple) -> None:
    """`published=True` with nowhere to publish is a configuration mistake, and
    the safe reading of it is "not yet"."""
    files, _ = generate(simple, published=True)
    assert "Disallow: /" in files["robots.txt"]


def test_a_sitemap_with_no_domain_uses_relative_paths(multipage) -> None:
    """Writing a preview address into `<loc>` publishes the preview."""
    files, _ = generate(multipage)
    locations = [line.split("<loc>")[1].split("</loc>")[0]
                 for line in files["sitemap.xml"].splitlines() if "<loc>" in line]
    assert "/" in locations
    # The `<loc>` values, not the whole document — the sitemap namespace is
    # itself an http URL, and asserting on the raw text tests the wrong string.
    assert all(not location.startswith("http") for location in locations)


def test_a_canonical_tag_is_absent_until_a_domain_is_agreed() -> None:
    """A canonical pointing at a preview tells search engines the preview is
    the real page."""
    assert seo.canonical_link("index.html") == ""
    assert seo.canonical_link("index.html", website="alhamra.ae") == (
        '<link rel="canonical" href="https://alhamra.ae/">')


def test_a_canonical_is_always_https() -> None:
    """An http canonical invites a redirect on every crawl, and the site is
    served over https or it fails the gate."""
    assert seo.canonical_host("http://alhamra.ae") == "https://alhamra.ae"


# ============================================ derived, never listed separately

def test_the_sitemap_lists_exactly_the_pages_that_exist(multipage) -> None:
    """Two hand-maintained lists drift, and the sitemap is the one nobody
    looks at — so it names a page that 404s on every crawl."""
    files, _ = generate(multipage, website="alhamra.ae", published=True)
    listed = {line.split("<loc>")[1].split("</loc>")[0]
              for line in files["sitemap.xml"].splitlines() if "<loc>" in line}
    pages = {f for f in files if f.endswith(".html")}

    assert len(listed) == len(pages)
    for page in pages:
        expected = ("https://alhamra.ae/" if page == "index.html"
                    else f"https://alhamra.ae/{page}")
        assert expected in listed, page


def test_the_sitemap_never_lists_itself_or_robots(multipage) -> None:
    files, _ = generate(multipage, website="alhamra.ae", published=True)
    assert "sitemap.xml</loc>" not in files["sitemap.xml"]
    assert "robots.txt" not in files["sitemap.xml"]


def test_adding_a_page_adds_a_sitemap_entry(simple, multipage) -> None:
    """Derivation, demonstrated rather than asserted."""
    thin, _ = generate(simple)
    thick, _ = generate(multipage)
    assert thick["sitemap.xml"].count("<loc>") > thin["sitemap.xml"].count("<loc>")


def test_the_sitemap_carries_no_lastmod(multipage) -> None:
    """The only date available is the build time, and a sitemap claiming every
    page changed today is one a crawler learns to discount."""
    files, _ = generate(multipage, website="alhamra.ae", published=True)
    assert "lastmod" not in files["sitemap.xml"]


# ============================================ hashed with the bundle

def test_the_seo_files_are_in_the_bundle_before_it_is_hashed(multipage) -> None:
    """A file added after `bundle_hash` is a file nobody approved, and the gate
    compares the hash of what is published against the hash of what was agreed."""
    from atlas_kernel.execution.artefacts import bundle_hash

    files, _ = generate(multipage)
    assert "sitemap.xml" in files and "robots.txt" in files

    without = {k: v for k, v in files.items() if k not in
               ("sitemap.xml", "robots.txt")}
    assert bundle_hash(files) != bundle_hash(without), (
        "the SEO files must change the bundle identity, or they are outside "
        "what the approval covers")


def test_generation_stays_deterministic(multipage) -> None:
    """Rebuild-from-memory is a hash comparison, not a person looking."""
    first, _ = generate(multipage, website="alhamra.ae", published=True)
    second, _ = generate(multipage, website="alhamra.ae", published=True)
    assert first == second


# ============================================ Atlas passes its own checks

def test_a_generated_bundle_has_none_of_the_defects_we_sell_against(multipage
                                                                    ) -> None:
    files, provenance = generate(multipage, website="alhamra.ae", published=True)
    assert provenance["seo"]["clean"] is True, provenance["seo"]["findings"]
    assert seo.audit(files, website="alhamra.ae")["findings"] == []


def test_the_audit_catches_a_broken_internal_link() -> None:
    """The `broken` finding Atlas sells against, checkable here with certainty
    rather than by crawling later."""
    result = seo.audit({
        "index.html": '<html><title>t</title><meta name="description" content="d">'
                      '<meta name="viewport" content="w"><h1>H</h1>'
                      '<script type="application/ld+json">{}</script>'
                      '<a href="missing.html">gone</a></html>',
        "sitemap.xml": "", "robots.txt": ""})
    broken = [f for f in result["findings"] if f["kind"] == "broken_link"]
    assert len(broken) == 1
    assert "missing.html" in broken[0]["detail"]


def test_the_audit_ignores_links_it_cannot_resolve_here() -> None:
    """A `tel:` or an external URL is not a broken internal link, and reporting
    it as one would make the check noise nobody reads."""
    result = seo.audit({
        "index.html": '<title>t</title><meta name="description" content="d">'
                      '<meta name="viewport" content="w"><h1>H</h1>'
                      '<script type="application/ld+json">{}</script>'
                      '<a href="tel:+97145550100">call</a>'
                      '<a href="mailto:a@b.ae">mail</a>'
                      '<a href="https://example.com">out</a>'
                      '<a href="#top">top</a>',
        "sitemap.xml": "", "robots.txt": ""})
    assert [f for f in result["findings"] if f["kind"] == "broken_link"] == []


def test_the_audit_catches_each_missing_head_element() -> None:
    result = seo.audit({"index.html": "<html><body>nothing</body></html>",
                        "sitemap.xml": "", "robots.txt": ""})
    kinds = {f["kind"] for f in result["findings"]}
    assert kinds == {"missing_title", "missing_meta_description",
                     "missing_viewport", "missing_h1",
                     "missing_structured_data"}


def test_the_audit_can_actually_fail() -> None:
    """A checker that never fires is not a checker."""
    assert seo.audit({})["findings"], "an empty bundle must not audit clean"


def test_a_missing_sitemap_is_a_finding() -> None:
    result = seo.audit({"index.html": "<title>t</title>"})
    assert any(f["kind"] == "missing_sitemap" for f in result["findings"])
    assert any(f["kind"] == "missing_robots" for f in result["findings"])


def test_the_audit_names_the_page_a_finding_is_about(multipage) -> None:
    """A finding that names no page is one nobody can act on."""
    files, _ = generate(multipage)
    files["services.html"] = "<html>nothing</html>"
    findings = seo.audit(files)["findings"]
    assert findings
    assert all(f.get("page") == "services.html" for f in findings
               if f["kind"].startswith("missing_") and "page" in f)
