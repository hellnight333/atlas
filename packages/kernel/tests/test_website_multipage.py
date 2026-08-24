"""Splitting a site into pages, tested against the defect the split can create.

Atlas detects thin content on strangers' websites and sells the fix. A generator
that splits a modest business into four pages of 200 characters each has shipped
that exact defect, on a customer's domain, under our name — and it would look
like an improvement in every test that only asked "did it render".

So the rules here are self-consistency rules. A page exists only if it clears the
same threshold the detector applies to everybody else; a site splits only if at
least two pages earn it; and nothing may be lost on the way, because a fact that
was on the one-page site and is on none of the four is a fact the customer told
us and we dropped.
"""

from __future__ import annotations

import re

import pytest

from atlas_kernel.opportunity.detectors.website import THIN_CONTENT_CHARS
from atlas_kernel.website.content import (
    ContactDetails,
    Fact,
    FactSource,
    OpeningHours,
    Prose,
    Service,
    SiteContent,
)
from atlas_kernel.website.themes import clean

WEEK = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
        "Sunday")


def _f(value: str) -> Fact:
    return Fact(value=value, source=FactSource.OPERATOR)


def _prose(text: str) -> Prose:
    return Prose(text=text, source=FactSource.OPERATOR)


@pytest.fixture
def substantial() -> SiteContent:
    """A business with genuinely enough to fill several pages."""
    return SiteContent(
        business_name=_f("Al Hamra Facilities Management"),
        tagline=_f("Air-conditioning, plumbing and electrical across Dubai"),
        about=_prose(
            "Al Hamra has looked after homes and offices in Dubai since 2011. "
            "We employ our own technicians rather than subcontracting, so the "
            "person who quotes a job is the person who does it. Most call-outs "
            "are answered the same day, and we do not charge for the visit if "
            "we cannot fix the problem. Annual maintenance contracts cover "
            "quarterly servicing and priority response."),
        services=[
            Service(name=_f(f"Service {i}"),
                    description=_prose(
                        f"What service {i} covers, what is included in the "
                        "quoted price and what is charged separately."))
            for i in range(6)],
        hours=OpeningHours(days={day: _f("8am to 6pm") for day in WEEK},
                           note=_prose("Emergency call-outs outside these "
                                       "hours are charged at the weekend rate.")),
        contact=ContactDetails(phone=_f("+971 4 555 0100"),
                               email=_f("hello@alhamra.ae"),
                               whatsapp=_f("+971 50 555 0100"),
                               address=_f("Unit 4, Al Quoz Industrial 3, Dubai")),
        location=_f("Dubai"),
        extras={"Founded": _f("2011"), "Trade licence": _f("CN-1234567")})


@pytest.fixture
def modest() -> SiteContent:
    """A real small business: a name, a couple of services, a phone number."""
    return SiteContent(
        business_name=_f("Corner Cafe"),
        tagline=_f("Coffee and pastries in Jumeirah"),
        services=[Service(name=_f("Coffee")), Service(name=_f("Pastries"))],
        contact=ContactDetails(phone=_f("+971 4 555 0111")),
        location=_f("Dubai"))


# ============================================ Atlas passes its own detector

def test_no_page_is_thinner_than_the_threshold_we_sell_against(substantial) -> None:
    """The defect this factory exists to fix, shipped by the factory."""
    files = clean.render(substantial)
    assert len(files) > 1, "the fixture must actually split for this to test anything"

    for name, markup in files.items():
        length = clean.visible_length(markup)
        assert length >= THIN_CONTENT_CHARS, (
            f"{name} has {length} characters, under the {THIN_CONTENT_CHARS} "
            "our own detector calls thin")


def test_the_threshold_is_the_detectors_own_not_a_copy() -> None:
    """Two numbers that must agree will not, eventually."""
    from pathlib import Path

    source = Path(clean.__file__).read_text(encoding="utf-8")
    assert "THIN_CONTENT_CHARS" in source
    assert "400" not in source, "the threshold must be imported, never restated"


def test_visible_length_ignores_markup_and_scripts() -> None:
    """Or a page of structured data would measure as a page of prose."""
    assert clean.visible_length("<p>hello there</p>") == len("hello there")
    assert clean.visible_length('<script>{"a":"'+ "x" * 500 + '"}</script><p>hi</p>') == 2
    assert clean.visible_length("<style>body{color:red}</style><p>hi</p>") == 2


# ============================================ splitting is earned, not configured

def test_a_modest_business_gets_one_page(modest) -> None:
    """Four thin pages read worse and rank worse than one honest one."""
    assert list(clean.render(modest)) == ["index.html"]


def test_a_substantial_business_gets_several(substantial) -> None:
    files = clean.render(substantial)
    assert set(files) == {"index.html", "services.html", "about.html",
                          "contact.html"}


def test_a_site_never_splits_into_exactly_two_pages() -> None:
    """Home plus one is a navigation bar holding two links."""
    #: Enough services to fill a services page, and nothing else worth one.
    content = SiteContent(
        business_name=_f("Single Trade Ltd"),
        services=[Service(name=_f(f"Service {i}"),
                          description=_prose("A description long enough to "
                                             "matter, several words of it."))
                  for i in range(8)])
    assert list(clean.render(content)) == ["index.html"]


def test_the_home_page_is_never_a_stub(substantial) -> None:
    """A home page reduced to a nav bar is the worst page on the site.

    It is also the page the detector actually looks at, so a stub here is a
    thin_content finding against the site Atlas just built.
    """
    home = clean.render(substantial)["index.html"]
    assert clean.visible_length(home) >= THIN_CONTENT_CHARS
    # It says something about every part of the business, not just contact.
    assert "What we do" in home and "About" in home and "Contact" in home


def test_the_home_page_does_not_repeat_the_full_text_of_other_pages(substantial
                                                                   ) -> None:
    """Duplicate content across the two pages a search engine compares first."""
    files = clean.render(substantial)
    home, services = files["index.html"], files["services.html"]

    description = substantial.services[0].description
    assert description is not None
    assert description.text in services
    assert description.text not in home, (
        "the service descriptions are why the services page exists")


# ============================================ nothing is lost

def test_every_fact_survives_the_split(substantial) -> None:
    """A fact the customer told us, on the one-page site and on none of the four."""
    whole = " ".join(clean.render(substantial).values())
    missing = [fact.value for fact in substantial.facts if fact.value not in whole]
    assert missing == []


def test_every_service_description_survives_the_split(substantial) -> None:
    whole = " ".join(clean.render(substantial).values())
    for service in substantial.services:
        assert service.description is not None
        assert service.description.text in whole


def test_a_section_no_page_claims_still_appears(substantial) -> None:
    """Home takes the leftovers, computed rather than listed.

    A section added to SECTIONS and forgotten in LAYOUT must land on the home
    page, not vanish — the failure mode of every layout written as two lists
    that have to agree.
    """
    unclaimed = set(clean.SECTIONS) - {
        section for _, _, sections in clean.LAYOUT for section in sections}
    home = clean.render(substantial)["index.html"]
    for section in unclaimed:
        rendered = clean.SECTIONS[section](substantial)
        assert rendered, f"{section} renders nothing for this fixture"
        assert rendered[0] in home, f"{section} is claimed by no page and shown on none"


# ============================================ every page is a real page

def test_every_page_carries_what_the_detector_checks(substantial) -> None:
    """The gate checks pages, not sites. An inner page missing a title is a
    page that fails our own detector on the customer's domain."""
    for name, markup in clean.render(substantial).items():
        assert "<title>" in markup, name
        assert '<meta name="description"' in markup, name
        assert '<meta name="viewport"' in markup, name
        assert "<h1>" in markup, name
        assert 'application/ld+json' in markup, name


def test_every_page_is_reachable_from_every_other(substantial) -> None:
    """A page nothing links to is invisible to a reader and to a crawler."""
    files = clean.render(substantial)
    for name, markup in files.items():
        for other in files:
            if other == name:
                assert 'aria-current="page"' in markup, name
            else:
                assert f'href="{other}"' in markup, f"{name} does not link to {other}"


def test_links_are_relative_so_a_preview_works(substantial) -> None:
    """A preview is served under /preview/<id>/, and it is where a customer
    looks first. An absolute href 404s in every one of them."""
    for name, markup in clean.render(substantial).items():
        assert 'href="/' not in markup, name
        assert 'src="/' not in markup, name


def test_inner_page_titles_are_distinguishable(substantial) -> None:
    """Four tabs all reading the business name are four tabs nobody can tell
    apart."""
    titles = [re.search(r"<title>(.*?)</title>", markup).group(1)  # type: ignore[union-attr]
              for markup in clean.render(substantial).values()]
    assert len(set(titles)) == len(titles)


def test_an_inner_page_still_names_the_business(substantial) -> None:
    """Or a search result for it cannot be attributed to anybody."""
    name = substantial.business_name.value
    for filename, markup in clean.render(substantial).items():
        assert name in markup, filename


# ============================================ still deterministic

def test_the_same_content_renders_the_same_bytes(substantial, modest) -> None:
    """Rebuild-from-memory is a fingerprint comparison, not a person looking."""
    for content in (substantial, modest):
        assert clean.render(content) == clean.render(content)


def test_the_split_decision_is_stable(substantial) -> None:
    assert clean.pages(substantial) == clean.pages(substantial)


def test_escaping_survives_the_split() -> None:
    """A business name is attacker-controlled on every page, not just home."""
    hostile = "</script><script>alert(1)</script>"
    content = SiteContent(
        business_name=_f(hostile),
        about=_prose("A" * 400),
        services=[Service(name=_f(f"S{i}"), description=_prose("D" * 60))
                  for i in range(8)],
        hours=OpeningHours(days={day: _f("8am to 6pm") for day in WEEK}),
        contact=ContactDetails(phone=_f("+971 4 555 0100"),
                               email=_f("a@b.ae"), address=_f("Somewhere")))
    for filename, markup in clean.render(content).items():
        assert "<script>alert(1)</script>" not in markup, filename
