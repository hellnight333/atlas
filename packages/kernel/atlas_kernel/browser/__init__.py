"""Browser execution (§4, §5).

Qevik's own interface, with Playwright as one backend. The kernel asks for
``browser.operate`` and never for Playwright, so a second runtime — a remote
browser service, an Iran worker, OpenClaw — registers rather than replaces.

Deliberately free of eager imports of *Playwright*, matching ``media``,
``approval``, ``opportunity`` and ``website``: importing this package must not
require Playwright to be installed, because the kernel runs on machines that
will never open a browser.

That constraint applies to the runtime, not to this package's own names. They
were previously withheld too, which made the public interface empty — the
package could only be used by reaching into its modules, which is the same as
having no public interface at all. ``session`` imports Playwright lazily inside
``start()``, so re-exporting these costs nothing on a machine without it.
"""

from .models import (
    BROWSER_OPERATE,
    BrowserJob,
    BrowserJobStatus,
    BrowserProfile,
    ElementRef,
    PageSnapshot,
    Screenshot,
)
from .session import BrowserError, BrowserSession, BrowserUnavailable, PlaywrightSession

__all__ = [
    "BROWSER_OPERATE",
    "BrowserError",
    "BrowserJob",
    "BrowserJobStatus",
    "BrowserProfile",
    "BrowserSession",
    "BrowserUnavailable",
    "ElementRef",
    "PageSnapshot",
    "PlaywrightSession",
    "Screenshot",
]
