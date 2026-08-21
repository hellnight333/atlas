"""The research engine: what it may conclude, and what it must refuse to.

The engine's danger is not that it breaks. It is that it produces a confident
sentence about somebody's business that is wrong — and the two ways that happens
are turning a failure into an absence, and finding fault in a company that is
doing well. Most of what follows guards those two things.

Everything runs against fixtures. A suite that depends on a stranger's server is
a suite that fails for reasons that have nothing to do with the code.
"""

from __future__ import annotations

import pytest

from atlas_kernel.opportunity.website_audit import Category, Finding, Status
from atlas_kernel.research import classify, content, journeys, net, position, presence, seo
from atlas_kernel.research.cms.base import CMSFacts, ContentItem, read_cms
from atlas_kernel.research.crawler import Crawl, crawl, links_in, next_page
from atlas_kernel.research.job import JobState, StageResult, StageState, fold
from atlas_kernel.research.net import Budget, Page
from atlas_kernel.research.technical import SpeedClass, classify_speed


def page(url: str, html: str = "", status: int = 200, **kw) -> Page:
    return Page(url=url, status=status, html=html, content_type="text/html", **kw)


def walk_of(*pages: Page) -> Crawl:
    found = Crawl("https://x.test")
    found.pages = list(pages)
    return found


class FakeFetcher(net.Fetcher):
    """A site in a dict. Spends the real budget so limits are genuinely tested."""

    def __init__(self, pages: dict[str, str], budget: Budget | None = None) -> None:
        self.root = "https://x.test"
        self.budget = budget or Budget(max_pages=40, delay_seconds=0)
        self.robots = net.Robots(self.root)
        self._pages = pages
        self._cache: dict[str, Page] = {}

    def get(self, url, *, depth=0, discovered_from="", enforce_robots=True):
        if enforce_robots and not self.robots.allows(url):
            return Page(url=url, status=0, depth=depth, error="disallowed by robots.txt")
        try:
            self.budget.spend()
        except net.BudgetSpent as stop:
            return Page(url=url, status=0, depth=depth, error=str(stop))
        body = self._pages.get(net.normalise(url))
        if body is None:
            return Page(url=url, status=404, depth=depth, error="HTTP 404")
        return page(url, body, depth=depth, discovered_from=discovered_from)


# --- the crawler is safe to point at a stranger ---------------------------

def test_the_crawler_never_leaves_the_host() -> None:
    site = {"https://x.test/": '<a href="https://elsewhere.test/x">away</a><a href="/in">in</a>',
            "https://x.test/in": "<p>in</p>"}
    found = crawl(FakeFetcher(site), seeds=["https://x.test/"])
    assert all("elsewhere" not in p.url for p in found.pages)
    assert ("https://elsewhere.test/x", "off-host") in found.skipped


@pytest.mark.parametrize("url,reason", [
    ("https://x.test/cart", "private or non-content path"),
    ("https://x.test/wp-admin/x", "private or non-content path"),
    ("https://x.test/?s=cake", "search or filter view"),
    ("https://x.test/a.pdf", "not a document"),
    ("ftp://x.test/a", "scheme 'ftp'"),
])
def test_the_crawler_refuses_what_it_should(url, reason) -> None:
    assert net.crawlable(url, root="https://x.test") == reason


def test_robots_disallow_is_obeyed() -> None:
    robots = net.Robots("https://x.test", "User-agent: *\nDisallow: /private/",
                        available=True)
    fetcher = FakeFetcher({"https://x.test/private/x": "<p>secret</p>"})
    fetcher.robots = robots
    assert fetcher.get("https://x.test/private/x").error == "disallowed by robots.txt"


def test_the_page_budget_is_a_ceiling_not_a_suggestion() -> None:
    site = {f"https://x.test/p{i}": f'<a href="/p{i + 1}">n</a>' for i in range(30)}
    site["https://x.test/"] = '<a href="/p0">go</a>'
    found = crawl(FakeFetcher(site, Budget(max_pages=4, delay_seconds=0)),
                  seeds=["https://x.test/"])
    assert len(found.html_pages) <= 4
    assert "page budget" in found.stopped_because


def test_a_cycle_terminates() -> None:
    site = {"https://x.test/a": '<a href="/b">b</a>', "https://x.test/b": '<a href="/a">a</a>'}
    found = crawl(FakeFetcher(site, Budget(max_pages=20, delay_seconds=0)),
                  seeds=["https://x.test/a"])
    assert len(found.pages) == 2


def test_a_broken_link_is_recorded_not_fatal() -> None:
    site = {"https://x.test/": '<a href="/gone">g</a><a href="/ok">o</a>',
            "https://x.test/ok": "<p>ok</p>"}
    found = crawl(FakeFetcher(site), seeds=["https://x.test/"])
    assert found.failed and found.failed[0][0].endswith("/gone")
    assert len(found.html_pages) == 2


def test_pagination_is_followed_and_duplicates_are_not() -> None:
    assert next_page('<link rel="next" href="/page/2">', base="https://x.test/") \
        == "https://x.test/page/2"
    assert links_in('<a href="/a">1</a><a href="/a/">2</a>', base="https://x.test/") \
        == ["https://x.test/a"]


# --- a failure is never an absence ----------------------------------------

def test_a_failed_stage_fails_alone_and_the_run_is_partial() -> None:
    result = fold("b", "https://x.test", [
        StageResult(stage="discovery"),
        StageResult(stage="seo", state=StageState.FAILED, reason="timeout"),
    ], started=__import__("datetime").datetime.now(__import__("datetime").UTC))
    assert result.state is JobState.PARTIAL
    assert result.failed_stages == ("seo",)


def test_a_failed_discovery_fails_the_whole_run() -> None:
    result = fold("b", "https://x.test", [
        StageResult(stage="discovery", state=StageState.FAILED, reason="dns"),
        StageResult(stage="seo"),
    ], started=__import__("datetime").datetime.now(__import__("datetime").UTC))
    assert result.state is JobState.FAILED


def test_an_unverified_reading_never_displaces_a_confirmed_one() -> None:
    """Two stages, one certain, one blind. The certain one must survive."""
    confirmed = Finding(feature="arabic", category=Category.MULTILINGUAL,
                        status=Status.NOT_FOUND, evidence="no hreflang on 18 pages")
    blind = Finding(feature="arabic", category=Category.MULTILINGUAL,
                    status=Status.UNVERIFIED, evidence="stage crashed")
    for order in ((confirmed, blind), (blind, confirmed)):
        result = fold("b", "u", [StageResult(stage="a", findings=(order[0],)),
                                 StageResult(stage="b", findings=(order[1],))],
                      started=__import__("datetime").datetime.now(__import__("datetime").UTC))
        assert result.observations()[0]["status"] == "not_found", order


@pytest.mark.parametrize("stage,call", [
    ("seo", lambda: seo.analyse(Crawl("https://x.test"))),
    ("journey", lambda: journeys.walk("CATERING", [])),
    ("presence", lambda: presence.assess([])),
    ("position", lambda: position.assess([])),
    ("content", lambda: content.analyse(CMSFacts())),
])
def test_a_stage_with_nothing_to_read_reports_unverified(stage, call) -> None:
    """Negative control on the rule the whole engine turns on."""
    _facts, findings = call()
    assert findings, stage
    assert all(f.status is Status.UNVERIFIED for f in findings), \
        f"{stage} turned an empty input into a claim: {[f.evidence for f in findings]}"


def test_speed_never_calls_a_slow_site_broken() -> None:
    assert classify_speed([7000], reachable=True)[0] is SpeedClass.SLOW
    assert classify_speed([], reachable=False)[0] is SpeedClass.UNAVAILABLE
    assert classify_speed([], reachable=True)[0] is SpeedClass.NOT_VERIFIED
    assert classify_speed([400], reachable=True)[0] is SpeedClass.FAST


# --- SEO needs more than one page -----------------------------------------

def test_duplicate_titles_need_two_pages_to_exist() -> None:
    both = walk_of(page("https://x.test/", "<title>Same</title>"),
                   page("https://x.test/b", "<title>Same</title>"))
    facts, _ = seo.analyse(both)
    assert facts["duplicate_titles"] == ["Same"]


def test_an_orphan_is_only_an_orphan_when_we_know_the_page_exists() -> None:
    walk = walk_of(page("https://x.test/", '<title>H</title><a href="/a">a</a>'),
                   page("https://x.test/a", "<title>A</title>"))
    facts, findings = seo.analyse(walk, sitemap_routes=["https://x.test/",
                                                        "https://x.test/a",
                                                        "https://x.test/buried"])
    assert facts["orphans"] == ["https://x.test/buried"]

    blind, findings = seo.analyse(walk)          # no sitemap, no CMS
    orphan = next(f for f in findings if f.feature == "orphan_pages")
    assert orphan.status is Status.UNVERIFIED, "absence of a sitemap is not absence of orphans"


def test_arabic_is_confirmed_absent_only_across_the_whole_crawl() -> None:
    english = walk_of(page("https://x.test/", '<html lang="en"><title>T</title>'))
    _facts, findings = seo.analyse(english)
    arabic = next(f for f in findings if f.feature == "arabic")
    assert arabic.status is Status.NOT_FOUND and "18" not in arabic.evidence

    bilingual = walk_of(page("https://x.test/", '<html lang="en"><title>T</title>'),
                        page("https://x.test/ar", '<html lang="ar"><title>ت</title>'))
    _facts, findings = seo.analyse(bilingual)
    assert next(f for f in findings if f.feature == "arabic").status is Status.PRESENT


# --- journeys test the business it is, never the business it is not -------

@pytest.mark.parametrize("model", sorted(journeys.JOURNEYS))
def test_every_journey_has_steps_and_an_intent(model) -> None:
    for step in journeys.JOURNEYS[model]:
        assert step.signals and step.intent


def test_a_caterer_is_never_judged_on_a_shopping_cart() -> None:
    facts, _ = journeys.walk("CATERING", ["<p>catering for guests</p>"])
    assert not any(s["step"] in ("cart", "checkout") for s in facts["steps"])


def test_an_optional_step_is_an_opportunity_not_a_defect() -> None:
    _facts, findings = journeys.walk("CATERING", ["<p>catering, guests, gallery</p>"])
    whatsapp = next(f for f in findings if f.feature == "journey_whatsapp")
    assert whatsapp.status is Status.UNVERIFIED, "an optional step must not count against them"


def test_the_journey_names_the_step_that_breaks() -> None:
    facts, findings = journeys.walk(
        "CATERING", ["<p>catering, guests, occasion, gallery</p><form></form>"])
    assert facts["first_break"] == "call"
    summary = next(f for f in findings if f.feature == "journey")
    assert "cannot phone the business" in summary.evidence


def test_journey_findings_reach_the_vocabulary_the_engine_already_knows() -> None:
    _facts, findings = journeys.walk("CATERING", ["<p>catering guests</p>"])
    assert any(f.feature == "click_to_call" for f in findings)


# --- classification is evidence, not the company name ---------------------

def test_a_name_alone_classifies_nothing() -> None:
    model, confidence, _ = classify.classify(["<h1>Al Noor Catering LLC</h1>"])
    assert confidence == 0.0 or model == "OTHER"


def test_nothing_to_read_is_not_verified_but_nothing_decisive_is_other() -> None:
    assert classify.classify([])[0] == "NOT_VERIFIED"
    assert classify.classify(["<p>We deliver quality and excellence.</p>"])[0] == "OTHER"


# --- a strong business must be describable as strong ----------------------

def test_a_strong_business_is_graded_strong_and_suppresses_criticism() -> None:
    cms = CMSFacts(platform="WordPress", detected=True, media_total=501)
    cms.image_pages = [ContentItem(slug=str(i), title="t", url="u", images=5)
                       for i in range(32)]
    facts, findings = position.assess(
        ["<p>20+ years. Our clients include Nestle. HACCP certified. "
         "What our clients say.</p>"], cms=cms, official_channels=2)
    assert facts["grade"] == "STRONG"
    assert position.suppresses_criticism("STRONG")
    assert any(f.feature == "established_business" for f in findings)


def test_a_bare_site_is_weak_and_that_is_also_evidenced() -> None:
    facts, findings = position.assess(["<p>We do things.</p>"])
    assert facts["grade"] == "WEAK"
    assert findings[0].status is Status.NOT_FOUND


def test_a_strong_blog_produces_no_start_a_blog_finding() -> None:
    """The instruction is explicit: never tell a publisher to start publishing."""
    cms = CMSFacts(platform="WordPress", detected=True)
    cms.posts = [ContentItem(slug=f"p{i}", title="t", url="u", kind="post",
                             published=f"2026-0{i % 9 + 1}-01T00:00:00", words=900,
                             images=3, categories=("Guides",)) for i in range(20)]
    _facts, findings = content.analyse(cms)
    quality = next(f for f in findings if f.feature == "blog_quality")
    assert quality.status is Status.PRESENT
    assert not any(f.feature == "blog_cadence" for f in findings)


def test_a_one_day_blog_with_no_images_is_caught() -> None:
    cms = CMSFacts(platform="WordPress", detected=True, media_total=501)
    cms.posts = [ContentItem(slug=f"p{i}", title="t", url="u", kind="post",
                             published="2025-11-11T00:00:00", words=120, images=0,
                             categories=("Uncategorized",)) for i in range(4)]
    _facts, findings = content.analyse(cms)
    by = {f.feature: f for f in findings}
    assert by["blog_cadence"].status is Status.NOT_FOUND
    assert by["blog_media"].status is Status.NOT_FOUND
    assert "501" in by["blog_media"].evidence


# --- presence must not claim absence, or attach a stranger ----------------

def test_a_channel_the_site_does_not_link_is_unverified_not_absent() -> None:
    _facts, findings = presence.assess(["<p>no links here</p>"])
    instagram = next(f for f in findings if f.feature == "instagram_presence")
    assert instagram.status is Status.UNVERIFIED


def test_a_linked_channel_is_official_and_share_buttons_are_not() -> None:
    channels = presence.from_site([
        '<a href="https://instagram.com/real">us</a>'
        '<a href="https://www.facebook.com/sharer/sharer.php?u=x">share</a>'])
    assert channels["instagram"].confidence is presence.Confidence.OFFICIAL
    assert "facebook" not in channels


def test_a_searched_channel_is_never_official() -> None:
    searched = {"instagram": presence.Channel(
        name="instagram", handle="maybe", url="https://instagram.com/maybe",
        confidence=presence.Confidence.PROBABLE, found=True)}
    facts, _ = presence.assess(["<p>nothing</p>"], searched=searched)
    assert facts["channels"]["instagram"]["confidence"] == "probable"
    assert "instagram" not in facts["official"]


# --- the CMS reader ------------------------------------------------------

def test_no_cms_is_not_a_finding_against_them() -> None:
    class Nothing:
        platform = "None"

        def detect(self, client, root, html):
            return False

        def read(self, client, root):
            raise AssertionError("must not be called")

    facts, findings = read_cms(None, "https://x.test", "<html></html>", readers=[Nothing()])
    assert facts.detected is False and findings == []


def test_a_cms_that_breaks_mid_read_is_unverified() -> None:
    class Broken:
        platform = "Broken"

        def detect(self, client, root, html):
            return True

        def read(self, client, root):
            raise RuntimeError("malformed json")

    _facts, findings = read_cms(None, "https://x.test", "", readers=[Broken()])
    assert findings[0].status is Status.UNVERIFIED
