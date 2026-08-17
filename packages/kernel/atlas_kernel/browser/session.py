"""The browser interface, and the Playwright backend behind it.

Playwright is imported lazily, inside the backend that needs it. The kernel runs
on machines that will never open a browser, and making every import of this
package require a 300 MB dependency would be a poor trade for one adapter.
"""

from __future__ import annotations

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


class PlaywrightSession:
    """Playwright/Chromium backend.

    Runs headless with a hard concurrency expectation set by the caller.
    Chromium is roughly 400 MB resident per context, and the canonical server
    has 8 GB shared with PostgreSQL and the API — so contexts are created per
    session and closed eagerly rather than pooled.
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

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> PlaywrightSession:
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
        self._page = self._context.new_page()
        self._page.set_default_timeout(self._timeout)
        # Console errors are evidence. §17 asks for them, and they distinguish
        # "the page loaded" from "the page works".
        self._page.on(
            "console",
            lambda msg: self._console.append(f"{msg.type}: {msg.text}"[:300])
            if msg.type in ("error", "warning")
            else None,
        )
        return self

    def close(self) -> None:
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

    def open(self, url: str) -> PageSnapshot:
        page = self._require_page()
        self._console.clear()
        try:
            response = page.goto(url, wait_until="domcontentloaded")
        except Exception as error:  # noqa: BLE001 - any navigation failure
            raise BrowserError(f"could not open {url}: {str(error)[:200]}") from error
        return self._snapshot(status=response.status if response else None)

    def snapshot(self) -> PageSnapshot:
        return self._snapshot(status=None)

    def click(self, ref: str) -> PageSnapshot:
        page = self._require_page()
        try:
            page.locator(ref).first.click(timeout=self._timeout)
        except Exception as error:  # noqa: BLE001
            raise BrowserError(f"could not click {ref}: {str(error)[:200]}") from error
        return self._snapshot(status=None)

    def type(self, ref: str, text: str) -> PageSnapshot:
        page = self._require_page()
        try:
            page.locator(ref).first.fill(text, timeout=self._timeout)
        except Exception as error:  # noqa: BLE001
            raise BrowserError(f"could not type into {ref}: {str(error)[:200]}") from error
        return self._snapshot(status=None)

    def extract(self, expression: str) -> Any:
        page = self._require_page()
        try:
            return page.evaluate(expression)
        except Exception as error:  # noqa: BLE001
            raise BrowserError(f"extraction failed: {str(error)[:200]}") from error

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
