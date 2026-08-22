"""One research run, twelve stages, and no stage able to take down the others.

The order is a dependency chain rather than a preference: discovery finds the
routes, the crawl fetches them, and everything after that reads what the crawl
brought back. Only discovery is essential — without it there is nothing to read,
and a run that cannot resolve the site is FAILED rather than a set of confident
statements about a website nobody reached.

Every other stage degrades alone. A failed SEO pass costs the SEO category and
nothing else, and the categories it would have established come back
`NOT_VERIFIED`, because a stage that crashed has not discovered that a customer's
site lacks anything.

Nothing here decides what to sell. It produces evidence and stops.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime

import httpx

from ..opportunity.website_audit import Finding, audit_html
from . import classify, content, discovery, journeys, position, presence, seo, technical
from .cms import read_cms
from .cms.base import CMSFacts
from .crawler import Crawl, crawl
from .job import ResearchResult, StageResult, StageState, fold
from .net import USER_AGENT, Budget, Fetcher

log = logging.getLogger(__name__)

#: Every stage, in dependency order. Named here so the dashboard and the tests
#: agree on what a complete run consists of without a second list.
STAGES = ("discovery", "crawl", "cms", "homepage", "technical", "seo",
          "content", "classify", "journey", "presence", "position")


class Context:
    """What the stages read and write. One per run."""

    def __init__(self, business_id: str, website: str, budget: Budget) -> None:
        self.business_id = business_id
        self.website = website
        self.budget = budget
        self.client: httpx.Client | None = None
        self.fetcher: Fetcher | None = None
        self.discovery: discovery.Discovery | None = None
        self.walk: Crawl | None = None
        self.cms: CMSFacts = CMSFacts()
        self.model: str = "NOT_VERIFIED"
        self.official_channels: int = 0

    @property
    def html(self) -> list[str]:
        return [p.html for p in self.walk.html_pages] if self.walk else []


def _run(name: str, work: Callable[[], tuple[dict, list[Finding]]]) -> StageResult:
    """Run one stage. It fails alone, loudly in the log and quietly on the page."""
    started = time.monotonic()
    try:
        facts, findings = work()
        return StageResult(stage=name, state=StageState.OK, facts=facts,
                           findings=tuple(findings),
                           duration_ms=int((time.monotonic() - started) * 1000))
    except Exception as error:                   # noqa: BLE001 - deliberately broad
        log.exception("research: stage %s failed", name)
        return StageResult(stage=name, state=StageState.FAILED,
                           reason=f"{type(error).__name__}: {error}"[:200],
                           duration_ms=int((time.monotonic() - started) * 1000))


def _skip(name: str, reason: str) -> StageResult:
    return StageResult(stage=name, state=StageState.SKIPPED, reason=reason)


def research(business_id: str, website: str, *, budget: Budget | None = None,
             client: httpx.Client | None = None) -> ResearchResult:
    """Everything the engine can establish about one business's digital presence.

    `client` is an injection point rather than a convenience. Without it the only
    way to test the pipeline is to patch `httpx.Client` on this module — which
    patches httpx itself, so the replacement calls the replacement. One
    parameter removes a whole class of test that is really testing the mock.
    """
    started = datetime.now(UTC)
    context = Context(business_id, website, budget or Budget())
    stages: list[StageResult] = []

    if not (website or "").strip():
        return fold(business_id, website, [StageResult(
            stage="discovery", state=StageState.FAILED,
            reason="no website recorded for this business")], started=started)

    owns_client = client is None
    context.client = client or httpx.Client(follow_redirects=True, timeout=20.0,
                                            headers={"User-Agent": USER_AGENT})
    try:
        # -- discovery: the one stage everything else depends on -------------
        def _discovery() -> tuple[dict, list[Finding]]:
            found, findings = discovery.discover(website, client=context.client)
            context.discovery = found
            if not found.reachable:
                raise RuntimeError(f"site not reachable: HTTP {found.http_status}"
                                   f"{'; ' + found.notes[0] if found.notes else ''}")
            return found.facts, findings

        stages.append(_run("discovery", _discovery))
        if stages[-1].state is StageState.FAILED:
            return fold(business_id, website, stages, started=started)

        found = context.discovery
        context.fetcher = Fetcher(found.canonical, budget=context.budget,
                                  robots=found.robots, client=context.client)

        # -- crawl: sitemap routes first, then whatever they link ------------
        def _crawl() -> tuple[dict, list[Finding]]:
            seeds = [found.canonical] + found.routes
            context.walk = crawl(context.fetcher, seeds=seeds, root=found.canonical)
            return context.walk.facts, []

        stages.append(_run("crawl", _crawl))

        # -- CMS: the difference between what is linked and what exists ------
        def _cms() -> tuple[dict, list[Finding]]:
            home = context.walk.html_pages[0].html if (context.walk and context.walk.html_pages) \
                else ""
            facts, findings = read_cms(context.client, found.canonical, home)
            context.cms = facts
            return facts.summary(), findings

        stages.append(_run("cms", _cms) if context.walk and context.walk.html_pages
                      else _skip("cms", "nothing was crawled"))

        # -- the existing single-page audit, kept as one stage among many ----
        def _homepage() -> tuple[dict, list[Finding]]:
            page = context.walk.html_pages[0]
            findings = audit_html(page.html, url=page.url, page_bytes=page.bytes)
            return {"url": page.url, "checks": len(findings)}, findings

        stages.append(_run("homepage", _homepage) if context.walk and context.walk.html_pages
                      else _skip("homepage", "the homepage was not retrieved"))

        stages.append(_run("technical", lambda: technical.inspect(
            context.walk, fetcher=context.fetcher, reachable=found.reachable))
            if context.walk else _skip("technical", "nothing was crawled"))

        stages.append(_run("seo", lambda: seo.analyse(
            context.walk, cms=context.cms, sitemap_routes=found.routes))
            if context.walk else _skip("seo", "nothing was crawled"))

        stages.append(_run("content", lambda: content.analyse(
            context.cms,
            service_slugs=tuple(p.slug for p in context.cms.pages[:60] if p.slug))))

        # -- what kind of business, then the journey that model requires -----
        def _classify() -> tuple[dict, list[Finding]]:
            model, confidence, evidence = classify.classify(context.html)
            context.model = model
            return {"model": model, "confidence": confidence, **evidence}, []

        stages.append(_run("classify", _classify))
        stages.append(_run("journey", lambda: journeys.walk(context.model, context.html)))

        def _presence() -> tuple[dict, list[Finding]]:
            facts, findings = presence.assess(context.html)
            context.official_channels = facts.get("linked_count", 0)
            return facts, findings

        stages.append(_run("presence", _presence))
        stages.append(_run("position", lambda: position.assess(
            context.html, cms=context.cms, official_channels=context.official_channels)))

        return fold(business_id, found.canonical, stages, started=started)
    finally:
        if owns_client and context.client is not None:
            context.client.close()


def to_event_detail(result: ResearchResult) -> dict:
    """The shape written to the business timeline.

    `observations` is the same list `website_audited` already carries, which is
    how an entire research engine arrives underneath the scoring and opportunity
    layers without either of them changing.
    """
    return {
        "state": result.state.value,
        "website": result.website,
        "http_status": next((s.facts.get("http_status", 0) for s in result.stages
                             if s.stage == "discovery"), 0),
        "load_ms": next((s.facts.get("median_ms") for s in result.stages
                         if s.stage == "technical"), None),
        "observations": result.observations(),
        "stages": {s.stage: {"state": s.state.value, "reason": s.reason,
                             "ms": s.duration_ms} for s in result.stages},
        "facts": result.facts,
        "ran": list(result.ran),
        "failed": list(result.failed_stages),
        "started_at": result.started_at.isoformat(),
        "finished_at": result.finished_at.isoformat(),
    }
