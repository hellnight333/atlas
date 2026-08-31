"""The browser interface, and the Playwright backend behind it.

Playwright is imported lazily, inside the backend that needs it. The kernel runs
on machines that will never open a browser, and making every import of this
package require a 300 MB dependency would be a poor trade for one adapter.
"""

from __future__ import annotations

import functools
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .models import ElementRef, PageSnapshot, Screenshot

#: How much page text to keep. Enough to decide what to do next and to serve as
#: evidence; not so much that it becomes a cost problem when handed to a model.
MAX_TEXT_CHARS = 4000
#: Interactive elements per snapshot. A page with more than this is a page where
#: a planner should be narrowing, not enumerating.
MAX_ELEMENTS = 120
DEFAULT_TIMEOUT_MS = 30_000


class BrowserError(RuntimeError):
    """The browser could not do it. Distinct from the page being broken."""


class BrowserUnavailable(BrowserError):
    """No browser runtime installed. A configuration problem, not a page problem."""


@runtime_checkable
class BrowserSession(Protocol):
    """One browser context. Deterministic actions only.

    No ``do_the_task``. Qevik plans; the browser performs single named steps
    that can be logged, replayed and authorised individually.
    """

    def open(self, url: str) -> PageSnapshot: ...
    def snapshot(self) -> PageSnapshot: ...
    def click(self, ref: str) -> PageSnapshot: ...
    def type(self, ref: str, text: str) -> PageSnapshot: ...
    def extract(self, expression: str) -> Any: ...
    def screenshot(self, path: Path, *, full_page: bool = True) -> Screenshot: ...
    def close(self) -> None: ...


def _max_sessions() -> int:
    """How many browsers may be alive at once.

    Chromium is roughly 400MB resident and the canonical server has 8GB shared
    with PostgreSQL and the API. Running the end-to-end suite without a cap took
    that host down hard enough that sshd could no longer fork a session — the
    kernel still completed TCP handshakes while nothing in userspace could
    answer, which looks like a network fault and is not one.

    So this is a survival limit, not a tuning knob.
    """
    try:
        return max(1, int(os.environ.get("QEVIK_MAX_BROWSERS", "2")))
    except ValueError:
        return 2


#: Acquired for the life of a session. Bounded rather than fair: a queue of
#: browser jobs waiting politely is still better than a box that stops
#: responding.
_SESSION_SLOTS = threading.BoundedSemaphore(_max_sessions())

#: How long to wait for a slot before giving up. A refusal that names the limit
#: is recoverable; an indefinite wait inside a test suite is the same silent
#: hang this cap exists to prevent.
SLOT_TIMEOUT_SECONDS = 120.0


def _on_browser_thread(method):
    """Route a call onto the session's own thread.

    Playwright's sync API refuses to run inside a live asyncio event loop, and
    the Qevik API is FastAPI — so without this the browser capability works from
    a script and fails from the server, which is the worst place to find out.
    Confirmed by running it: `PlaywrightSession` raised "Playwright Sync API
    inside the asyncio loop" the moment it was called from a coroutine.

    A dedicated thread has no running loop, so the sync API is happy and the
    interface stays synchronous for every caller. Applied uniformly rather than
    only when a loop is detected, because a capability that behaves differently
    under the server than under a test is not one anybody can reason about.
    """

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        return self._submit(lambda: method(self, *args, **kwargs))

    return wrapper


class PlaywrightSession:
    """Playwright/Chromium backend.

    Runs headless with a hard concurrency expectation set by the caller.
    Chromium is roughly 400 MB resident per context, and the canonical server
    has 8 GB shared with PostgreSQL and the API — so contexts are created per
    session and closed eagerly rather than pooled.

    Every Playwright call happens on one dedicated thread. See
    `_on_browser_thread` for why.
    """

    def __init__(
        self,
        *,
        headless: bool = True,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        user_agent: str | None = None,
        viewport: tuple[int, int] = (1440, 900),
    ) -> None:
        self._timeout = timeout_ms
        self._headless = headless
        self._user_agent = user_agent or (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36 Qevik/0.1"
        )
        self._viewport = viewport
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._console: list[str] = []
        self._holds_slot = False
        #: One thread, owning every Playwright object. Playwright's sync API is
        #: not thread-safe, so "one thread" is a correctness requirement rather
        #: than a throughput choice.
        self._pool: ThreadPoolExecutor | None = None
        self._thread_id: int | None = None

    def _submit(self, call):
        """Run `call` on the browser thread and wait for it.

        Re-entrant: a method already running on that thread calls straight
        through. Submitting again would queue work behind the task currently
        waiting for it, on a pool of exactly one thread — a deadlock, not a
        slowdown.
        """
        if self._pool is None or threading.get_ident() == self._thread_id:
            return call()
        return self._pool.submit(call).result()

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> PlaywrightSession:
        if self._holds_slot:
            return self
        if not _SESSION_SLOTS.acquire(timeout=SLOT_TIMEOUT_SECONDS):
            raise BrowserUnavailable(
                f"no browser slot free after {SLOT_TIMEOUT_SECONDS:g}s "
                f"(limit {_max_sessions()}, set QEVIK_MAX_BROWSERS to change it). "
                "Something is holding a session open without closing it."
            )
        self._holds_slot = True

        try:
            if self._pool is None:
                self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="qevik-browser")
                self._thread_id = self._pool.submit(threading.get_ident).result()
            return self._submit(self._start_on_thread)
        except BaseException:
            # Whatever was created before the failure is closed here. Without
            # this, a launch that succeeds and a context that does not leaves a
            # Chromium process alive with no reference to it and no __exit__
            # coming, because __enter__ never returned.
            self.close()
            raise

    def _start_on_thread(self) -> PlaywrightSession:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:  # pragma: no cover - environment dependent
            raise BrowserUnavailable(
                "Playwright is not installed. `pip install playwright` then "
                "`playwright install chromium`."
            ) from error

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self._headless,
            # /dev/shm is small in containers and Chromium crashes without this
            # in a way that looks like a page failure rather than a host limit.
            args=["--disable-dev-shm-usage", "--no-sandbox"],
        )
        self._context = self._browser.new_context(
            user_agent=self._user_agent,
            viewport={"width": self._viewport[0], "height": self._viewport[1]},
        )
        self._page = self._new_page()
        return self

    def _new_page(self):
        """One page, configured the way every page here is configured.

        Extracted so `open()` can start each navigation on a fresh one. The
        console handler has to be attached per page, and attaching it in one
        place is what stops a replacement page from silently collecting no
        evidence.
        """
        page = self._context.new_page()
        page.set_default_timeout(self._timeout)
        # Console errors are evidence. §17 asks for them, and they distinguish
        # "the page loaded" from "the page works".
        page.on(
            "console",
            lambda msg: (
                self._console.append(f"{msg.type}: {msg.text}"[:300])
                if msg.type in ("error", "warning")
                else None
            ),
        )
        return page

    def close(self) -> None:
        """Release everything. Safe to call twice, and on a session that never
        started — cleanup runs on paths where the caller cannot know how far
        start() got."""
        try:
            if self._pool is not None:
                try:
                    self._submit(self._close_on_thread)
                finally:
                    self._pool.shutdown(wait=True)
                    self._pool = None
                    self._thread_id = None
            else:
                self._close_on_thread()
        finally:
            if self._holds_slot:
                self._holds_slot = False
                _SESSION_SLOTS.release()

    def _close_on_thread(self) -> None:
        for closer in (self._context, self._browser):
            try:
                if closer is not None:
                    closer.close()
            except Exception:  # noqa: BLE001 - closing must not raise
                pass
        try:
            if self._playwright is not None:
                self._playwright.stop()
        except Exception:  # noqa: BLE001
            pass
        self._page = self._context = self._browser = self._playwright = None

    def __enter__(self) -> PlaywrightSession:
        return self.start()

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _require_page(self):
        if self._page is None:
            raise BrowserError("session is not started; call start() or use a with-block")
        return self._page

    # -- actions -----------------------------------------------------------

    @_on_browser_thread
    def open(self, url: str) -> PageSnapshot:
        """Go to one address, on a page of its own.

        **A fresh page per navigation, and that is a correctness fix rather than
        hygiene.** `wait_until="domcontentloaded"` returns while a page may
        still be navigating — a client-side redirect, a meta refresh — and the
        callers here loop over sites reusing one session. The next site's
        `goto` then interrupted the previous one, and Playwright raised
        *"Navigation to <previous> is interrupted by another navigation to
        <next>"* against the **previous** call.

        The audit recorded that as `reachable=False` for the previous business.
        Seven of sixty audited businesses were marked unreachable that way,
        including two large retailers whose sites are plainly fine, and each was
        then dropped from the funnel for a defect that was ours.

        A page cannot interrupt a navigation it was not part of. The old page is
        closed after the new one is created, so a failure to close never leaves
        the session without a page.
        """
        self._require_page()
        previous = self._page
        self._page = self._new_page()
        try:
            if previous is not None:
                previous.close()
        except Exception:                          # noqa: BLE001 - best effort
            # A page that will not close is a leak, not a reason to refuse the
            # navigation the caller asked for.
            pass

        page = self._page
        self._console.clear()
        try:
            response = page.goto(url, wait_until="domcontentloaded")
        except Exception as error:  # noqa: BLE001 - any navigation failure
            raise BrowserError(f"could not open {url}: {str(error)[:200]}") from error
        return self._snapshot(status=response.status if response else None)

    @_on_browser_thread
    def snapshot(self) -> PageSnapshot:
        return self._snapshot(status=None)

    @_on_browser_thread
    def click(self, ref: str) -> PageSnapshot:
        page = self._require_page()
        try:
            page.locator(ref).first.click(timeout=self._timeout)
        except Exception as error:  # noqa: BLE001
            raise BrowserError(f"could not click {ref}: {str(error)[:200]}") from error
        return self._snapshot(status=None)

    @_on_browser_thread
    def type(self, ref: str, text: str) -> PageSnapshot:
        page = self._require_page()
        try:
            page.locator(ref).first.fill(text, timeout=self._timeout)
        except Exception as error:  # noqa: BLE001
            raise BrowserError(f"could not type into {ref}: {str(error)[:200]}") from error
        return self._snapshot(status=None)

    @_on_browser_thread
    def extract(self, expression: str) -> Any:
        page = self._require_page()
        try:
            return page.evaluate(expression)
        except Exception as error:  # noqa: BLE001
            raise BrowserError(f"extraction failed: {str(error)[:200]}") from error

    @_on_browser_thread
    def screenshot(self, path: Path, *, full_page: bool = True) -> Screenshot:
        page = self._require_page()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            page.screenshot(path=str(path), full_page=full_page)
        except Exception as error:  # noqa: BLE001
            raise BrowserError(f"screenshot failed: {str(error)[:200]}") from error
        return Screenshot(
            url=page.url,
            path=str(path),
            width=self._viewport[0],
            height=self._viewport[1],
            full_page=full_page,
        )

    # -- internals ---------------------------------------------------------

    def _snapshot(self, *, status: int | None) -> PageSnapshot:
        page = self._require_page()
        try:
            text = (page.inner_text("body") or "").strip()
        except Exception:  # noqa: BLE001 - a page with no body is still a page
            text = ""
        return PageSnapshot(
            url=page.url,
            title=page.title() or "",
            status=status,
            text=text[:MAX_TEXT_CHARS],
            elements=self._elements(),
            console_errors=list(self._console),
        )

    def _elements(self) -> list[ElementRef]:
        """Interactive elements, with refs a caller can act on.

        Refs are CSS paths generated here rather than selectors a caller wrote.
        The distinction matters: the caller never has to know the page's
        structure, which is what lets a planner drive a site it has never seen.
        """
        page = self._require_page()
        try:
            raw = page.evaluate(
                """() => {
                    const out = [];
                    const nodes = document.querySelectorAll(
                        'a[href], button, input, textarea, select, [role=button]'
                    );
                    nodes.forEach((el, i) => {
                        const r = el.getBoundingClientRect();
                        if (r.width === 0 && r.height === 0) return;
                        const tag = el.tagName.toLowerCase();
                        out.push({
                            ref: `${tag}:nth-of-type(${i + 1})`,
                            css: el.id ? `#${CSS.escape(el.id)}` : null,
                            role: el.getAttribute('role') || tag,
                            name: (el.innerText || el.value || el.getAttribute('aria-label')
                                   || el.getAttribute('placeholder') || '').trim().slice(0, 80),
                            editable: ['input', 'textarea', 'select'].includes(tag)
                        });
                    });
                    return out;
                }"""
            )
        except Exception:  # noqa: BLE001
            return []
        return [
            ElementRef(
                ref=item.get("css") or item["ref"],
                role=item.get("role", ""),
                name=item.get("name", ""),
                editable=bool(item.get("editable")),
            )
            for item in (raw or [])[:MAX_ELEMENTS]
        ]
