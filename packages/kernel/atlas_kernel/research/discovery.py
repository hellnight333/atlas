"""Where the site actually is, and what it will tell us about itself.

Runs before anything else and everything else depends on it, which is why a
failure here fails the whole run rather than degrading: without a resolved host
there are no routes, and every later stage would be reporting on a site it never
reached.

What it establishes: the canonical URL after redirects, whether TLS validates,
what robots.txt permits, and every route the site volunteers through its own
sitemaps. A sitemap is worth more than any amount of crawling — it is the site
telling us what it considers its content.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

import httpx

from ..opportunity.website_audit import Category, Finding, Status
from .net import (
    REQUEST_TIMEOUT_S,
    USER_AGENT,
    Fetcher,
    Resolution,
    Robots,
    host_of,
    load_robots,
    normalise,
    resolution,
    tls_state,
)

#: Where sitemaps live when robots.txt does not say.
COMMON_SITEMAPS = ("/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml",
                   "/sitemap-index.xml", "/sitemap1.xml")

_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
_IS_INDEX = re.compile(r"<sitemapindex", re.I)


def _finding(feature: str, status: Status, category: Category, evidence: str) -> Finding:
    return Finding(feature=feature, category=category, status=status, evidence=evidence[:300])


class Discovery:
    """The result of looking the site up."""

    def __init__(self, requested: str) -> None:
        self.requested = requested
        self.canonical = ""
        self.reachable = False
        self.http_status = 0
        self.redirect_chain: tuple[str, ...] = ()
        self.tls_valid = False
        self.tls_note = ""
        self.dns: Resolution = Resolution.UNKNOWN
        self.robots: Robots | None = None
        self.robots_available = False
        self.sitemaps: list[str] = []
        self.routes: list[str] = []
        self.unreachable: list[tuple[str, str]] = []
        self.notes: list[str] = []

    @property
    def facts(self) -> dict:
        return {
            "requested": self.requested, "canonical": self.canonical,
            "reachable": self.reachable, "http_status": self.http_status,
            "dns": self.dns.value,
            "redirects": list(self.redirect_chain), "tls_valid": self.tls_valid,
            "tls": self.tls_note, "robots_txt": self.robots_available,
            "sitemaps": self.sitemaps[:10], "sitemap_routes": len(self.routes),
            "notes": self.notes,
        }


def _sitemap_urls(client: httpx.Client, url: str, *, seen: set[str],
                  depth: int = 0, limit: int = 5000) -> tuple[list[str], list[str]]:
    """Every URL a sitemap offers, following one level of sitemap index.

    Sitemaps are cheap and authoritative, so they are read outside the crawl
    budget — but not without limits, because a sitemap index can fan out
    forever.
    """
    if url in seen or depth > 2 or len(seen) > 50:
        return [], []
    seen.add(url)
    try:
        response = client.get(url, timeout=REQUEST_TIMEOUT_S)
    except Exception as error:                   # noqa: BLE001
        return [], [f"{url}: {type(error).__name__}"]
    if response.status_code != 200 or "<" not in response.text[:200]:
        return [], [f"{url}: HTTP {response.status_code}"]
    locations = [m.group(1) for m in _LOC.finditer(response.text)][:limit]
    if _IS_INDEX.search(response.text):
        routes: list[str] = []
        problems: list[str] = []
        for child in locations[:20]:             # bounded fan-out
            found, failed = _sitemap_urls(client, child, seen=seen, depth=depth + 1)
            routes += found
            problems += failed
        return routes, problems
    return locations, []


def discover(website: str, *, client: httpx.Client | None = None) -> tuple[Discovery, list[Finding]]:
    """Resolve the site and read what it publishes about its own structure."""
    owns = client is None
    client = client or httpx.Client(
        follow_redirects=True, timeout=REQUEST_TIMEOUT_S,
        headers={"User-Agent": USER_AGENT})
    found = Discovery(website)
    findings: list[Finding] = []

    # Nothing on file is a confirmed absence and needs no lookup.
    if not (website or "").strip():
        findings.append(_finding("website", Status.NOT_FOUND, Category.TECHNICAL,
                                 "no website recorded for this business"))
        return found, findings

    try:
        candidate = website if "://" in website else f"https://{website}"
        try:
            response = client.get(candidate)
            found.http_status = response.status_code
            found.canonical = str(response.url)
            found.redirect_chain = tuple(str(r.url) for r in response.history)
            found.reachable = response.status_code < 400
        except Exception as error:               # noqa: BLE001
            found.notes.append(f"{type(error).__name__}: {error}"[:180])
            findings.append(_finding("https", Status.UNVERIFIED, Category.TECHNICAL,
                                     f"site did not answer: {found.notes[-1]}"))
            # Now, and only now, ask DNS. Everything downstream — the CREATE
            # opportunity, the readiness score, what a customer is told — turns
            # on the difference between "this business has no website" and "we
            # could not reach theirs", and a name server answering *no such
            # host* is the one signal that settles it. A timeout does not.
            #
            # Asked here rather than before the request for two reasons: the
            # happy path spends no lookup, and a caller supplying its own HTTP
            # transport is not silently overruled by the real network.
            found.dns = resolution(host_of(website))
            conclusive = found.dns is Resolution.NO_SUCH_HOST
            findings.append(_finding(
                "website",
                Status.NOT_FOUND if conclusive else Status.UNVERIFIED,
                Category.TECHNICAL,
                f"DNS reports no such host for {host_of(website)}" if conclusive
                else f"{host_of(website)} did not answer: {found.notes[-1]}"))
            return found, findings

        findings.append(_finding(
            "website",
            Status.PRESENT if found.reachable else Status.UNVERIFIED,
            Category.TECHNICAL,
            f"{found.canonical} answered {found.http_status}"))

        found.tls_valid, found.tls_note = tls_state(found.canonical)
        findings.append(_finding(
            "https", Status.PRESENT if found.tls_valid else Status.NOT_FOUND,
            Category.TECHNICAL,
            f"{found.canonical} — {found.tls_note}"))

        found.robots = load_robots(client, found.canonical)
        found.robots_available = found.robots.available
        findings.append(_finding(
            "robots_txt",
            Status.PRESENT if found.robots_available else Status.NOT_FOUND,
            Category.TECHNICAL,
            "robots.txt served" if found.robots_available else "no robots.txt"))

        declared = list(found.robots.sitemaps)
        candidates = declared or [urljoin(found.canonical, path) for path in COMMON_SITEMAPS]
        seen: set[str] = set()
        for candidate_map in candidates:
            routes, problems = _sitemap_urls(client, candidate_map, seen=seen)
            if routes:
                found.sitemaps.append(candidate_map)
                found.routes += routes
            found.unreachable += [(candidate_map, p) for p in problems]
            if found.routes and not declared:
                break                            # one working guess is enough

        found.routes = list(dict.fromkeys(normalise(r) for r in found.routes))
        findings.append(_finding(
            "sitemap",
            Status.PRESENT if found.sitemaps else Status.NOT_FOUND,
            Category.SEO,
            f"{len(found.routes)} URLs across {len(found.sitemaps)} sitemap(s)"
            if found.sitemaps else "no sitemap found at robots.txt or the usual paths"))
        return found, findings
    finally:
        if owns:
            client.close()


def fetcher_for(found: Discovery, budget=None) -> Fetcher:
    """A fetcher already bound to what discovery established."""
    return Fetcher(found.canonical, budget=budget, robots=found.robots)
