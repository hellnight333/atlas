"""A bounded walk of one site, preferring what the site itself declared.

Order matters and is deliberate: sitemap routes first, then links found while
reading them. A sitemap is the site's own statement about its content, so
spending the budget there finds the important pages; crawling blind spends it on
whatever the homepage happens to link.

The budget is not advisory. It is checked before every request and the reason it
ran out is recorded, so a partial crawl can say *why* it is partial instead of
looking like a small site.
"""

from __future__ import annotations

import re
from collections import deque
from urllib.parse import urljoin

from .net import Fetcher, Page, crawlable, normalise

_HREF = re.compile(r'<a\b[^>]*\bhref\s*=\s*["\']([^"\'#]+)', re.I)
_NEXT = re.compile(r'<link\b[^>]*\brel\s*=\s*["\']next["\'][^>]*\bhref\s*=\s*["\']([^"\']+)', re.I)


def links_in(html: str, *, base: str) -> list[str]:
    """Every on-page link, absolute and de-duplicated, in document order."""
    out: list[str] = []
    seen: set[str] = set()
    for match in _HREF.finditer(html or ""):
        url = urljoin(base, match.group(1).strip())
        key = normalise(url)
        if key not in seen:
            seen.add(key)
            out.append(url)
    return out


def next_page(html: str, *, base: str) -> str:
    """`rel=next`, so paginated archives advance rather than being re-walked."""
    match = _NEXT.search(html or "")
    return urljoin(base, match.group(1).strip()) if match else ""


class Crawl:
    """What the walk reached, what it did not, and where it stopped."""

    def __init__(self, root: str) -> None:
        self.root = root
        self.pages: list[Page] = []
        self.skipped: list[tuple[str, str]] = []
        self.failed: list[tuple[str, str]] = []
        self.stopped_because = ""

    @property
    def html_pages(self) -> list[Page]:
        return [p for p in self.pages if p.ok and p.is_html and p.html]

    @property
    def facts(self) -> dict:
        return {
            "fetched": len(self.pages),
            "ok": len(self.html_pages),
            "failed": len(self.failed),
            "skipped": len(self.skipped),
            "stopped_because": self.stopped_because,
            "routes": [p.url for p in self.html_pages][:60],
            "unreachable": [{"url": u, "reason": r} for u, r in self.failed[:20]],
        }


def crawl(fetcher: Fetcher, *, seeds: list[str], root: str = "") -> Crawl:
    """Breadth-first from the seeds, inside the budget, on one host only.

    The budget is the fetcher's and cannot be passed separately. An earlier
    version took one as an argument, which let the loop check one allowance
    while the fetcher spent from another — so a caller could hold the walk to
    two pages while forty were actually requested. One run, one budget.
    """
    budget = fetcher.budget
    root = root or fetcher.root
    found = Crawl(root)
    queue: deque[tuple[str, int, str]] = deque()
    seen: set[str] = set()

    for seed in seeds:
        key = normalise(seed)
        if key not in seen:
            seen.add(key)
            queue.append((seed, 0, "seed"))

    while queue:
        if budget.exhausted:
            found.stopped_because = budget.stopped_because
            break
        url, depth, came_from = queue.popleft()
        refusal = crawlable(url, root=root)
        if refusal:
            found.skipped.append((url, refusal))
            continue

        page = fetcher.get(url, depth=depth, discovered_from=came_from)
        found.pages.append(page)
        if not page.ok:
            found.failed.append((url, page.error or f"HTTP {page.status}"))
            # A budget refusal is the run ending, not the page being broken.
            if "budget" in page.error:
                found.stopped_because = page.error
                break
            continue
        if not page.is_html or depth >= budget.max_depth:
            continue

        candidates = links_in(page.html, base=page.url)
        following = next_page(page.html, base=page.url)
        if following:
            candidates.insert(0, following)
        for link in candidates:
            key = normalise(link)
            if key in seen:
                continue
            seen.add(key)
            queue.append((link, depth + 1, page.url))

    if not found.stopped_because and budget.exhausted:
        found.stopped_because = budget.stopped_because
    elif not found.stopped_because:
        found.stopped_because = "crawl completed"
    return found
