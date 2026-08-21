"""Discovery, the WordPress reader and the whole pipeline, over a fake site.

`httpx.MockTransport` runs the real code — the real redirect handling, the real
sitemap parser, the real REST paging — against a site defined in this file. No
network, no dependence on somebody's server staying up, and the parts most
likely to be wrong are the parts being exercised.

The fixture is modelled on the case that motivated the engine: a WordPress site
whose sitemap lists a fraction of what its content API holds, with a portfolio
of picture-only pages nothing links to.
"""

from __future__ import annotations

import httpx
import pytest

from atlas_kernel.research import discovery, pipeline
from atlas_kernel.research.cms.wordpress import WordPress
from atlas_kernel.research.job import JobState
from atlas_kernel.research.net import Budget

ROBOTS = "User-agent: *\nDisallow: /wp-admin/\nSitemap: https://fake.test/sitemap.xml\n"
SITEMAP = """<?xml version="1.0"?><urlset>
<url><loc>https://fake.test/</loc></url>
<url><loc>https://fake.test/about/</loc></url>
<url><loc>https://fake.test/services/</loc></url>
</urlset>"""
HOME = """<html lang="en"><head><title>Fake Catering</title>
<meta name="description" content="Catering in Dubai"><link rel="canonical" href="https://fake.test/">
<meta property="og:title" content="Fake Catering"></head><body>
<h1>Event catering</h1><p>Canape and buffet menus, live station, for guests.</p>
<p>20+ years. Our clients include Someone. HACCP certified.</p>
<a href="/about/">About</a><a href="/services/">Services</a>
<a href="https://instagram.com/fake">Instagram</a>
<img src="/a.jpg" alt="a plate"><form><input name="x"></form>
<script src="/wp-content/themes/x.js"></script></body></html>"""
ABOUT = """<html lang="en"><head><title>About — Fake</title>
<meta name="description" content="About us"><link rel="canonical" href="https://fake.test/about/">
</head><body><h1>About</h1><p>%s</p><a href="/">Home</a></body></html>""" % ("word " * 200)
SERVICES = """<html lang="en"><head><title>Services — Fake</title>
<meta name="description" content="Our services"><link rel="canonical" href="https://fake.test/services/">
</head><body><h1>Our services</h1><p>%s</p><a href="/">Home</a></body></html>""" % ("word " * 200)

#: More pages exist than the sitemap lists — including a picture-only portfolio
#: nothing links to. This is the gap the engine exists to find.
WP_PAGES = [
    {"slug": "about", "link": "https://fake.test/about/", "date": "2024-01-01T00:00:00",
     "title": {"rendered": "About"}, "content": {"rendered": "<p>" + "word " * 200 + "</p>"},
     "categories": []},
    *[{"slug": f"event-{i}", "link": f"https://fake.test/event-{i}/",
       "date": "2024-01-01T00:00:00", "title": {"rendered": f"Event {i}"},
       "content": {"rendered": "<img src='a'><img src='b'><img src='c'>"},
       "categories": []} for i in range(12)],
]
WP_POSTS = [
    {"slug": f"post-{i}", "link": f"https://fake.test/post-{i}/",
     "date": "2025-11-11T10:00:00", "title": {"rendered": f"Post {i}"},
     "content": {"rendered": "<p>" + "word " * 90 + "</p>"}, "categories": [1]}
    for i in range(4)
]


def handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    host = request.url.host
    if host != "fake.test":
        return httpx.Response(404)
    if path == "/robots.txt":
        return httpx.Response(200, text=ROBOTS, headers={"content-type": "text/plain"})
    if path == "/sitemap.xml":
        return httpx.Response(200, text=SITEMAP, headers={"content-type": "application/xml"})
    if path.startswith("/wp-json/wp/v2/"):
        collection = path.rsplit("/", 1)[-1]
        page = int(request.url.params.get("page", 1))
        rows = {"pages": WP_PAGES, "posts": WP_POSTS,
                "categories": [{"id": 1, "name": "Uncategorized", "count": 4}],
                "media": []}.get(collection, [])
        total = {"media": 501}.get(collection, len(rows))
        body = rows if page == 1 else []
        return httpx.Response(200, json=body, headers={"X-WP-Total": str(total)})
    if path == "/wp-json/":
        return httpx.Response(200, json={"name": "Fake"},
                              headers={"content-type": "application/json"})
    html = {"/": HOME, "/about/": ABOUT, "/services/": SERVICES}.get(path)
    if html is None and path.startswith("/event-"):
        html = "<html><head><title>E</title></head><body><img src=a></body></html>"
    if html is None:
        return httpx.Response(404, text="gone")
    return httpx.Response(200, text=html, headers={"content-type": "text/html"})


@pytest.fixture
def client() -> httpx.Client:
    with httpx.Client(transport=httpx.MockTransport(handler),
                      follow_redirects=True) as made:
        yield made


# --- discovery -------------------------------------------------------------

def test_discovery_reads_robots_and_the_sitemap(client) -> None:
    found, findings = discovery.discover("https://fake.test/", client=client)
    assert found.reachable and found.http_status == 200
    assert found.robots_available
    assert found.sitemaps == ["https://fake.test/sitemap.xml"]
    assert len(found.routes) == 3
    by = {f.feature: f for f in findings}
    assert by["robots_txt"].status.value == "present"
    assert by["sitemap"].status.value == "present"


def test_discovery_on_a_site_that_does_not_answer() -> None:
    def dead(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    with httpx.Client(transport=httpx.MockTransport(dead)) as broken:
        found, findings = discovery.discover("https://nowhere.test/", client=broken)
    assert not found.reachable
    assert findings[0].status.value == "unverified", \
        "a site that did not answer has not been shown to lack anything"


def test_a_missing_sitemap_is_a_finding_not_a_crash() -> None:
    def bare(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(200, text="<html><title>t</title></html>",
                                  headers={"content-type": "text/html"})
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(bare),
                      follow_redirects=True) as bare_client:
        found, findings = discovery.discover("https://bare.test/", client=bare_client)
    assert found.reachable and not found.sitemaps
    assert next(f for f in findings if f.feature == "sitemap").status.value == "not_found"


# --- the WordPress reader --------------------------------------------------

def test_wordpress_is_detected_from_the_markup(client) -> None:
    assert WordPress().detect(client, "https://fake.test", HOME) is True


def test_wordpress_reads_more_than_the_sitemap_lists(client) -> None:
    facts = WordPress().read(client, "https://fake.test")
    assert facts.detected
    assert len(facts.pages) == 13 and len(facts.posts) == 4
    assert facts.media_total == 501
    assert len(facts.image_pages) == 12, "picture-only pages are the portfolio"
    assert facts.categories == ["Uncategorized"]


def test_a_site_with_no_wordpress_is_not_misread() -> None:
    def plain(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(200, text="<html><title>t</title></html>",
                                  headers={"content-type": "text/html"})
        return httpx.Response(404, text="not found")

    with httpx.Client(transport=httpx.MockTransport(plain)) as plain_client:
        assert WordPress().detect(plain_client, "https://plain.test",
                                  "<html><title>t</title></html>") is False


# --- the whole pipeline ----------------------------------------------------

@pytest.fixture
def result(client):
    """Run every stage against the fake site, through the real code."""
    return pipeline.research("b1", "https://fake.test/", client=client,
                             budget=Budget(max_pages=12, delay_seconds=0))


def test_the_pipeline_runs_every_stage(result) -> None:
    assert result.state is JobState.READY, result.failed_stages
    assert set(result.ran) == set(pipeline.STAGES)


def test_the_pipeline_produces_evidence_the_engine_can_read(result) -> None:
    observations = result.observations()
    assert len(observations) > 20
    assert all({"feature", "status"} <= set(o) for o in observations)
    assert {o["status"] for o in observations} <= {"present", "not_found", "unverified"}


def test_the_pipeline_finds_what_only_a_crawl_plus_cms_can_find(result) -> None:
    by = {o["feature"]: o for o in result.observations()}
    assert by["portfolio_depth"]["status"] == "present", "picture-only pages"
    assert by["orphan_pages"]["status"] == "not_found", "pages nothing links to"
    assert by["arabic"]["status"] == "not_found", "no hreflang anywhere in the crawl"
    assert by["blog_cadence"]["status"] == "not_found", "every post on one day"


def test_the_pipeline_classifies_and_walks_the_right_journey(result) -> None:
    facts = result.facts
    assert facts["classify"]["model"] == "CATERING"
    assert facts["journey"]["model"] == "CATERING"
    assert not any(s["step"] == "cart" for s in facts["journey"]["steps"])


def test_the_event_detail_is_the_shape_the_timeline_already_carries(result) -> None:
    detail = pipeline.to_event_detail(result)
    assert detail["state"] == "READY"
    assert isinstance(detail["observations"], list) and detail["observations"]
    assert set(detail["stages"]) == set(result.ran)
    assert detail["http_status"] == 200


def test_one_broken_stage_costs_that_stage_only(client, monkeypatch) -> None:
    """The property the whole design turns on, exercised end to end."""
    def explode(*_a, **_k):
        raise RuntimeError("simulated stage failure")

    monkeypatch.setattr(pipeline.seo, "analyse", explode)
    result = pipeline.research("b1", "https://fake.test/", client=client,
                               budget=Budget(max_pages=8, delay_seconds=0))
    assert result.state is JobState.PARTIAL
    assert result.failed_stages == ("seo",)
    assert "position" in result.ran, "later stages must still run"
    assert result.observations(), "the rest of the evidence survives"


def test_a_business_with_no_website_fails_cleanly() -> None:
    result = pipeline.research("b1", "")
    assert result.state is JobState.FAILED
    assert result.stages[0].reason == "no website recorded for this business"
    assert result.observations() == []
