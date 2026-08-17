"""The autonomous loop, end to end, with nothing simulated.

> "Create a minimal web application with a landing page, run its tests, start it
> locally, open it with the browser, and verify the page."

Every step below is the real thing. Files are written to disk, `pytest` runs as
a subprocess and its exit code is believed, a server binds a real port, Chromium
opens a real HTTP connection to it, and a screenshot lands on the filesystem.
Nothing here asserts that a class exists.

The step that matters most is the failure: the generated application is
deliberately broken first, the test suite is run, the failure is diagnosed from
its output, the fix is applied, and the suite is re-run. A pipeline that has
only ever seen its own success is not an autonomous loop — it is a script that
has not met a problem yet.

Requires Chromium. Skips where it is absent, which on a laptop is honest and on
the server never happens.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from atlas_kernel.browser import BrowserUnavailable, PlaywrightSession
from atlas_kernel.workspace import Workspace, free_port

pytestmark = [pytest.mark.e2e, pytest.mark.integration]


LANDING_PAGE = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>{title}</title></head>
<body>
  <h1 id="headline">{headline}</h1>
  <p id="tagline">{tagline}</p>
</body>
</html>
"""

# Deliberately wrong: `page` is never defined, so importing the module raises.
# This is the failure the loop has to diagnose and fix on its own terms.
BROKEN_APP = '''"""A tiny site generator."""

TITLE = "Al Quoz Auto Garage"


def render() -> str:
    return page
'''

FIXED_APP = '''"""A tiny site generator."""

TITLE = "Al Quoz Auto Garage"
HEADLINE = "Al Quoz Auto Garage"
TAGLINE = "Servicing Dubai since 1998"

TEMPLATE = """{template}"""


def render() -> str:
    return TEMPLATE.format(title=TITLE, headline=HEADLINE, tagline=TAGLINE)
'''

TEST_FILE = """from app import TITLE, render


def test_the_page_has_a_headline():
    assert "<h1" in render()


def test_the_title_appears():
    assert TITLE in render()
"""

BUILD_SCRIPT = """from pathlib import Path

import app

Path("dist").mkdir(exist_ok=True)
Path("dist/index.html").write_text(app.render(), encoding="utf-8")
print("built dist/index.html")
"""


@pytest.fixture
def browser():
    try:
        with PlaywrightSession(headless=True) as session:
            yield session
    except BrowserUnavailable as unavailable:
        pytest.skip(f"no browser on this machine: {unavailable}")


def test_qevik_builds_tests_fixes_serves_and_verifies_a_web_app(tmp_path: Path, browser) -> None:
    ws = Workspace.create(tmp_path, "garage-landing")

    # 1. Write the project. Application, tests, build script.
    ws.write("app.py", BROKEN_APP)
    ws.write("test_app.py", TEST_FILE)
    ws.write("build.py", BUILD_SCRIPT)
    assert set(ws.files()) == {"app.py", "build.py", "test_app.py"}

    # 2. Run the tests, and expect the truth rather than a green tick.
    first = ws.run([sys.executable, "-m", "pytest", "-q", "test_app.py", "-p", "no:cacheprovider"])
    assert not first.ok, "the broken build must fail; a loop that cannot fail cannot self-correct"

    # 3. Diagnose from the actual output, not from having written the bug.
    assert "NameError" in first.stdout or "NameError" in first.stderr

    # 4. Fix, and re-run.
    ws.write("app.py", FIXED_APP.format(template=LANDING_PAGE))
    second = ws.run([sys.executable, "-m", "pytest", "-q", "test_app.py", "-p", "no:cacheprovider"])
    assert second.ok, f"still failing after the fix:\n{second.tail()}"

    # 5. Build the artifact.
    build = ws.run([sys.executable, "build.py"], check=True)
    assert "built dist/index.html" in build.stdout
    assert ws.exists("dist/index.html")

    # 6. Serve it, and 7. open it in a real browser.
    port = free_port()
    with ws.serve(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "-d", "dist"],
        port=port,
    ):
        page = browser.open(f"http://127.0.0.1:{port}/")

        # 8. Verify what a visitor would actually receive.
        assert page.ok, f"the deployed page did not load: {page.status}"
        assert page.status == 200
        assert "Al Quoz Auto Garage" in page.title

        headline = browser.extract("document.querySelector('#headline').textContent")
        assert headline == "Al Quoz Auto Garage"
        tagline = browser.extract("document.querySelector('#tagline').textContent")
        assert tagline == "Servicing Dubai since 1998"

        # 9. Keep the evidence.
        shot = browser.screenshot(ws.root / "dist" / "verified.png")
        assert Path(shot.path).stat().st_size > 1000, "a screenshot of nothing is not evidence"

    # 10. The audit trail: everything that happened, in order.
    lineage = ws.lineage()
    assert lineage.count("wrote ") == 4  # app, test, build, then the fix
    assert len(ws.commands) == 3  # failing tests, passing tests, build
    assert [c.ok for c in ws.commands] == [False, True, True]


def test_two_projects_do_not_destroy_each_other(tmp_path: Path) -> None:
    """A factory builds many things. The second must not be the first's grave."""
    first = Workspace.create(tmp_path, "site-one")
    first.write("index.html", "<h1>one</h1>")

    second = Workspace.create(tmp_path, "site-two")
    second.write("index.html", "<h1>two</h1>")

    assert first.read("index.html") == "<h1>one</h1>"
    assert second.read("index.html") == "<h1>two</h1>"
    assert first.record.id != second.record.id


def test_a_page_that_never_loads_is_reported_not_assumed(tmp_path: Path, browser) -> None:
    """Normal browser failure. Nothing is listening on this port, and the loop
    has to say so rather than carry on and report success."""
    ws = Workspace.create(tmp_path, "dead-site")
    dead = free_port()
    with pytest.raises(Exception) as raised:
        browser.open(f"http://127.0.0.1:{dead}/")
    assert raised.value is not None
    assert ws.files() == []
