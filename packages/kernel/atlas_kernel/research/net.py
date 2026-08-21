"""Bounded, polite fetching. The part that has to be right before anything else.

This runs against other people's servers, 1,100 of them, unattended. So the
limits are the design rather than a setting: a budget that cannot be exceeded, a
delay that cannot be skipped, a robots policy that is consulted before the first
request rather than after, and a hard refusal to leave the host it was pointed
at.

`Budget` is deliberately mutable and passed down. Every fetch spends from the
same one, so a stage cannot quietly get its own allowance by constructing a
second fetcher.
"""

from __future__ import annotations

import ssl
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx

#: Identifies us and says where to complain. A crawler that will not say who it
#: is has no business on somebody's server.
USER_AGENT = ("Mozilla/5.0 (compatible; QevikResearch/1.0; "
              "+https://qevik.ai/crawler)")

#: Per the architecture report.
MAX_PAGES = 40
MAX_DEPTH = 3
MIN_DELAY_S = 1.5
REQUEST_TIMEOUT_S = 10.0
TOTAL_BUDGET_S = 120.0
MAX_BYTES = 2 * 1024 * 1024

#: Query strings that mean "a view of the same content". Following them is how a
#: crawler spends forty pages on one filterable listing.
_TRAP_KEYS = {"s", "q", "search", "filter", "sort", "orderby", "add-to-cart",
              "replytocom", "share", "print", "page_id", "utm_source"}
_TRAP_PATHS = ("/wp-admin", "/wp-login", "/cart", "/checkout", "/my-account",
               "/login", "/signin", "/register", "/logout", "/feed", "/cdn-cgi/")
_SKIP_SUFFIX = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico",
                ".zip", ".mp4", ".mp3", ".css", ".js", ".xml", ".json", ".woff",
                ".woff2", ".ttf", ".avif", ".doc", ".docx", ".xls", ".xlsx")


class BudgetSpent(RuntimeError):
    """The run is over. Not an error in the site — an error in asking for more."""


@dataclass
class Budget:
    """What one prospect is allowed to cost."""

    max_pages: int = MAX_PAGES
    max_depth: int = MAX_DEPTH
    total_seconds: float = TOTAL_BUDGET_S
    delay_seconds: float = MIN_DELAY_S
    pages_fetched: int = 0
    started_at: float = field(default_factory=time.monotonic)
    #: Why the crawl stopped, in words, so a partial result can say so.
    stopped_because: str = ""

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started_at

    @property
    def exhausted(self) -> bool:
        if self.pages_fetched >= self.max_pages:
            self.stopped_because = f"page budget reached ({self.max_pages})"
            return True
        if self.elapsed >= self.total_seconds:
            self.stopped_because = f"time budget reached ({self.total_seconds:.0f}s)"
            return True
        return False

    def spend(self) -> None:
        if self.exhausted:
            raise BudgetSpent(self.stopped_because)
        self.pages_fetched += 1


@dataclass(frozen=True)
class Page:
    """One fetched document, and how it was reached."""

    url: str
    status: int
    html: str = ""
    content_type: str = ""
    bytes: int = 0
    elapsed_ms: int = 0
    depth: int = 0
    discovered_from: str = ""
    redirect_chain: tuple[str, ...] = ()
    error: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300 and not self.error

    @property
    def is_html(self) -> bool:
        return "html" in self.content_type.lower()


def normalise(url: str) -> str:
    """One spelling per page, so a cycle is a repeat rather than a new URL."""
    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "https").lower()
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return urlunparse((scheme, host, path, "", "", ""))


def same_host(a: str, b: str) -> bool:
    return urlparse(a).netloc.lower().removeprefix("www.") == \
        urlparse(b).netloc.lower().removeprefix("www.")


def crawlable(url: str, *, root: str) -> str:
    """Empty string if it may be fetched, otherwise the reason it may not."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"scheme {parsed.scheme!r}"
    if not same_host(url, root):
        return "off-host"
    lowered = parsed.path.lower()
    if lowered.endswith(_SKIP_SUFFIX):
        return "not a document"
    if any(lowered.startswith(p) or p in lowered for p in _TRAP_PATHS):
        return "private or non-content path"
    if parsed.query:
        keys = {pair.split("=")[0].lower() for pair in parsed.query.split("&") if pair}
        if keys & _TRAP_KEYS:
            return "search or filter view"
    return ""


class Robots:
    """robots.txt, consulted before the first request and obeyed."""

    def __init__(self, root: str, body: str = "", *, available: bool = False) -> None:
        self.root = root
        self.body = body
        self.available = available
        self._parser = RobotFileParser()
        self._parser.parse(body.splitlines() if body else [])

    def allows(self, url: str) -> bool:
        # No robots.txt is permission by convention, not a reason to be greedy —
        # the budget still applies.
        if not self.available:
            return True
        return self._parser.can_fetch(USER_AGENT, url)

    @property
    def crawl_delay(self) -> float:
        try:
            value = self._parser.crawl_delay(USER_AGENT)
        except Exception:                       # noqa: BLE001 - malformed robots
            return 0.0
        return float(value or 0.0)

    @property
    def sitemaps(self) -> tuple[str, ...]:
        found = []
        for line in self.body.splitlines():
            if line.lower().startswith("sitemap:"):
                found.append(line.split(":", 1)[1].strip())
        return tuple(found)


class Fetcher:
    """The only thing in the engine that touches the network."""

    def __init__(self, root: str, *, budget: Budget | None = None,
                 robots: Robots | None = None, client: httpx.Client | None = None) -> None:
        self.root = root
        self.budget = budget or Budget()
        self.robots = robots or Robots(root)
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=REQUEST_TIMEOUT_S, follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*"},
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=1))
        self._last_request = 0.0
        self._cache: dict[str, Page] = {}

    # -- politeness --------------------------------------------------------
    def _wait(self) -> None:
        delay = max(self.budget.delay_seconds, self.robots.crawl_delay)
        gap = time.monotonic() - self._last_request
        if self._last_request and gap < delay:
            time.sleep(delay - gap)
        self._last_request = time.monotonic()

    def get(self, url: str, *, depth: int = 0, discovered_from: str = "",
            enforce_robots: bool = True) -> Page:
        """Fetch one document, or explain why not. Never raises for a bad site."""
        key = normalise(url)
        if key in self._cache:
            return self._cache[key]
        if enforce_robots and not self.robots.allows(url):
            return Page(url=url, status=0, depth=depth, discovered_from=discovered_from,
                        error="disallowed by robots.txt")
        try:
            self.budget.spend()
        except BudgetSpent as stop:
            return Page(url=url, status=0, depth=depth, discovered_from=discovered_from,
                        error=str(stop))
        self._wait()
        started = time.monotonic()
        try:
            response = self.client.get(url)
            body = response.text if len(response.content) <= MAX_BYTES else ""
            page = Page(
                url=str(response.url), status=response.status_code, html=body,
                content_type=response.headers.get("content-type", ""),
                bytes=len(response.content),
                elapsed_ms=int((time.monotonic() - started) * 1000), depth=depth,
                discovered_from=discovered_from,
                redirect_chain=tuple(str(r.url) for r in response.history),
                error="" if len(response.content) <= MAX_BYTES else "response too large")
        except Exception as error:              # noqa: BLE001 - a bad site is data
            page = Page(url=url, status=0, depth=depth, discovered_from=discovered_from,
                        elapsed_ms=int((time.monotonic() - started) * 1000),
                        error=f"{type(error).__name__}: {error}"[:200])
        self._cache[key] = page
        return page

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> Fetcher:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


def load_robots(fetcher_client: httpx.Client, root: str) -> Robots:
    """Read robots.txt before anything else is requested."""
    url = urljoin(root, "/robots.txt")
    try:
        response = fetcher_client.get(url, timeout=REQUEST_TIMEOUT_S)
    except Exception:                            # noqa: BLE001
        return Robots(root)
    if response.status_code != 200 or "html" in response.headers.get("content-type", ""):
        return Robots(root)
    return Robots(root, response.text, available=True)


def tls_state(url: str) -> tuple[bool, str]:
    """Whether TLS validates, and what went wrong if not."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return False, "not served over https"
    try:
        context = ssl.create_default_context()
        with context.wrap_socket(__import__("socket").create_connection(
                (parsed.hostname, parsed.port or 443), timeout=REQUEST_TIMEOUT_S),
                server_hostname=parsed.hostname) as sock:
            cert = sock.getpeercert()
        return True, f"valid to {cert.get('notAfter', 'unknown')}"
    except Exception as error:                   # noqa: BLE001
        return False, f"{type(error).__name__}: {error}"[:160]
