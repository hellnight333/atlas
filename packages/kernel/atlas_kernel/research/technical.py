"""Measured technical health. Every number here was observed, never estimated.

The rule the brief is emphatic about: a slow site is slow, not broken. They are
different findings with different remedies and wildly different tone in a first
message, so `SpeedClass` keeps them apart and `UNAVAILABLE` is reserved for a
site that did not answer at all.

`NOT_VERIFIED` is the default for everything here. A measurement that did not
happen is not a measurement of zero.
"""

from __future__ import annotations

import re
import statistics
from enum import StrEnum
from urllib.parse import urljoin

from ..opportunity.website_audit import Category, Finding, Status
from .crawler import Crawl
from .net import Fetcher, crawlable, normalise

#: Milliseconds to first byte-ish, measured over the pages actually fetched.
FAST_MS = 1200
NORMAL_MS = 3000
SLOW_MS = 6000

_IMG_SRC = re.compile(r'<img\b[^>]*\bsrc\s*=\s*["\']([^"\']+)', re.I)
_LOADING = re.compile(r'<img\b[^>]*\bloading\s*=\s*["\']lazy["\']', re.I)
_VIEWPORT = re.compile(r'<meta\b[^>]*\bname\s*=\s*["\']viewport["\']', re.I)


class SpeedClass(StrEnum):
    FAST = "FAST"
    NORMAL = "NORMAL"
    SLOW = "SLOW"
    #: Did not answer. Not a speed at all.
    UNAVAILABLE = "UNAVAILABLE"
    #: Nothing was measured. Never counted against anybody.
    NOT_VERIFIED = "NOT_VERIFIED"


def classify_speed(samples: list[int], *, reachable: bool) -> tuple[SpeedClass, str]:
    """Median of what was actually measured, with the sample size stated."""
    if not reachable:
        return SpeedClass.UNAVAILABLE, "the site did not answer"
    if not samples:
        return SpeedClass.NOT_VERIFIED, "no page timings were captured"
    median = int(statistics.median(samples))
    note = f"median {median}ms over {len(samples)} page(s)"
    if median <= FAST_MS:
        return SpeedClass.FAST, note
    if median <= NORMAL_MS:
        return SpeedClass.NORMAL, note
    return SpeedClass.SLOW, note


def inspect(walk: Crawl, *, fetcher: Fetcher, reachable: bool,
            check_assets: int = 12) -> tuple[dict, list[Finding]]:
    """Health across everything the crawl reached."""
    pages = walk.html_pages
    timings = [p.elapsed_ms for p in pages if p.elapsed_ms]
    speed, note = classify_speed(timings, reachable=reachable)

    findings: list[Finding] = [Finding(
        feature="page_speed",
        category=Category.PERFORMANCE,
        status={SpeedClass.FAST: Status.PRESENT, SpeedClass.NORMAL: Status.PRESENT,
                SpeedClass.SLOW: Status.NOT_FOUND,
                SpeedClass.UNAVAILABLE: Status.NOT_FOUND,
                SpeedClass.NOT_VERIFIED: Status.UNVERIFIED}[speed],
        evidence=f"{speed.value}: {note}")]

    # Redirect chains — one hop is housekeeping, three is a configuration smell.
    longest = max((len(p.redirect_chain) for p in pages), default=0)
    if longest >= 3:
        findings.append(Finding(
            feature="redirect_chain", category=Category.TECHNICAL, status=Status.NOT_FOUND,
            evidence=f"{longest} redirects before a page renders"))

    # Broken internal links the crawl already proved broken.
    if walk.failed:
        findings.append(Finding(
            feature="broken_links", category=Category.TECHNICAL, status=Status.NOT_FOUND,
            evidence="; ".join(f"{u} ({r})" for u, r in walk.failed[:3])))
    elif pages:
        findings.append(Finding(
            feature="broken_links", category=Category.TECHNICAL, status=Status.PRESENT,
            evidence=f"no broken internal links across {len(pages)} pages"))

    # A sample of images, actually requested rather than assumed present.
    broken_images: list[str] = []
    checked = 0
    seen: set[str] = set()
    for page in pages:
        for match in _IMG_SRC.finditer(page.html):
            url = urljoin(page.url, match.group(1).strip())
            key = normalise(url)
            if key in seen or crawlable(url, root=fetcher.root) == "off-host":
                continue
            seen.add(key)
            if checked >= check_assets:
                break
            checked += 1
            probe = fetcher.get(url, enforce_robots=False)
            if not probe.ok:
                broken_images.append(f"{url} ({probe.error or probe.status})")
        if checked >= check_assets:
            break
    if checked:
        findings.append(Finding(
            feature="broken_images", category=Category.TECHNICAL,
            status=Status.NOT_FOUND if broken_images else Status.PRESENT,
            evidence="; ".join(broken_images[:3]) if broken_images
            else f"{checked} images sampled, all served"))

    lazy = sum(1 for p in pages if _LOADING.search(p.html))
    heavy = [p for p in pages if p.bytes > 3_000_000]
    if heavy:
        findings.append(Finding(
            feature="page_weight", category=Category.PERFORMANCE, status=Status.NOT_FOUND,
            evidence=f"{len(heavy)} page(s) over 3MB, largest "
                     f"{max(p.bytes for p in heavy) // 1024}KB"))

    mobile = sum(1 for p in pages if _VIEWPORT.search(p.html))
    if pages:
        findings.append(Finding(
            feature="viewport_meta", category=Category.MOBILE,
            status=Status.PRESENT if mobile == len(pages) else Status.NOT_FOUND,
            evidence=f"viewport meta on {mobile} of {len(pages)} pages"))

    facts = {
        "speed_class": speed.value, "speed_note": note,
        "timings_ms": sorted(timings)[:20],
        "median_ms": int(statistics.median(timings)) if timings else None,
        "pages_measured": len(pages), "broken_links": len(walk.failed),
        "images_sampled": checked, "broken_images": broken_images[:5],
        "lazy_loading_pages": lazy, "longest_redirect_chain": longest,
        "viewport_pages": mobile,
    }
    return facts, findings
