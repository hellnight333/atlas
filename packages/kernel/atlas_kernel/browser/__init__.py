"""Browser execution (§4, §5).

Qevik's own interface, with Playwright as one backend. The kernel asks for
``browser.operate`` and never for Playwright, so a second runtime — a remote
browser service, an Iran worker, OpenClaw — registers rather than replaces.

Deliberately free of eager imports, matching ``media``, ``approval``,
``opportunity`` and ``website``: importing this package must not require
Playwright to be installed, because the kernel runs on machines that will never
open a browser.
"""

__all__: list[str] = []
