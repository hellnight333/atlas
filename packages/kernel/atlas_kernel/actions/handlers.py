"""The real handlers. Each does the work; none of them simulate it.

The providers that shipped before these were stubs — `time.sleep(0.75)` and a
hashed `example.com` URL. Everything here calls the verified capability: Brave
for search, a subprocess for commands, Chromium for verification, and the
website factory's publish-then-promote target for deployment.

One rule governs the whole file: **an action never constructs its own runtime.**
Browsers, search clients and deployment targets arrive through the context. That
is what lets the same plan run against a local directory on a laptop and a real
host on the server without the plan changing.
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

from .context import ExecutionContext

#: Capability names. Asked for by name; never a vendor.
WEB_SEARCH = "web.search"
CODE_GENERATE = "code.generate"
CODE_WRITE = "code.write"
CODE_EXECUTE = "code.execute"
BROWSER_OPERATE = "browser.operate"
SITE_DEPLOY = "site.deploy"


class ActionError(RuntimeError):
    """An action could not do its job."""


class PublishNotAuthorised(ActionError):
    """An outward-facing publish was attempted without authorisation.

    Its own type because it is a policy refusal rather than a failure, and the
    two must never be retried the same way.
    """


# -- research ------------------------------------------------------------


def web_search(payload: dict[str, Any], ctx: ExecutionContext) -> dict[str, Any]:
    """Search the open web and keep the provenance.

    Results are untrusted text from strangers; they are stored as data and
    never concatenated into an instruction. See `research/models.py`.
    """
    from ..research import SearchQuery

    query = str(payload.get("query") or "").strip()
    if not query:
        raise ActionError("web.search needs a query")

    client = ctx.search()
    results = client.search(
        SearchQuery(
            text=query,
            count=int(payload.get("count", 5)),
            country=payload.get("country"),
        )
    )
    return {
        "query": results.query,
        "count": len(results),
        # Provenance, per §18: every finding keeps the URL it came from.
        "sources": [
            {"url": r.url, "title": r.title, "description": r.description} for r in results.results
        ],
        "top_url": results.urls[0] if results.urls else "",
        "provider": results.provider,
        "approx_cost_usd": results.approx_cost_usd,
    }


# -- generation ----------------------------------------------------------

#: Marks of text lifted from somebody else's page rather than written for this
#: one. Search results are *evidence*; publishing one verbatim puts another
#: site's branding on a customer's page and is a copyright question as well as
#: an embarrassing one.
#:
#: This happened: given research about children's games, the model titled the
#: generated page "Children's game | Types, Rules & Benefits | Britannica" and
#: every step reported success.
_SOURCE_MARKS = (
    " | ",  # site-branding separator, near-universal in page titles
    " - Wikipedia",
    "http://",
    "https://",
    "www.",
    "…",
    "...",
)

#: Longer than any headline a person would write, and typical of a scraped
#: description pasted whole.
MAX_CONTENT_CHARS = 160


def looks_forwarded(value: str) -> str:
    """Why this text looks copied rather than written. Empty when it looks fine.

    Deliberately conservative — it flags the shapes that only occur in scraped
    metadata, not merely long or unusual prose, because a false positive here
    blocks a legitimate page and is noticed immediately while a false negative
    is published.
    """
    text = value.strip()
    if len(text) > MAX_CONTENT_CHARS:
        return f"{len(text)} characters — longer than written copy, typical of a scraped snippet"
    for mark in _SOURCE_MARKS:
        if mark in text:
            return f"contains {mark!r}, which is a mark of a copied page title or URL"
    return ""

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: system-ui, sans-serif; margin: 0; padding: 3rem 1.5rem;
         background: {bg}; color: {fg}; }}
  main {{ max-width: 42rem; margin: 0 auto; }}
  h1 {{ font-size: clamp(2rem, 6vw, 3rem); margin: 0 0 .5rem; }}
  p {{ line-height: 1.6; }}
  ul {{ padding-left: 1.2rem; }}
</style>
</head>
<body>
<main>
  <h1 id="headline">{headline}</h1>
  <p id="tagline">{tagline}</p>
  <ul id="features">
{features}
  </ul>
</main>
</body>
</html>
"""


def code_generate(payload: dict[str, Any], ctx: ExecutionContext) -> dict[str, Any]:
    """Produce the files for a small static site.

    Deterministic by design. The website factory already established that a
    generated site must be reproducible from stored inputs — a template renders
    the same site twice, and a language model does not. Where a model is
    genuinely better (prose, naming) it supplies the *content* through the
    payload; it never emits the markup.

    Everything interpolated is escaped. A site name is attacker-controllable the
    moment prospect data feeds a generator.
    """
    title = str(payload.get("title") or "Untitled").strip()
    headline = str(payload.get("headline") or title).strip()
    tagline = str(payload.get("tagline") or "").strip()
    features = [str(f) for f in payload.get("features") or []]

    # Evidence has its own slot, and it is not published.
    #
    # Asking a planner to "pass the research into the step that decides" while
    # that step's payload was title/headline/tagline/features gave it nowhere to
    # put it — so it either dropped the reference, or stuffed a source's title
    # into `title`, which is how another site's branding reached a customer's
    # page. A schema that has no place for something is a schema that asks to be
    # abused.
    #
    # What arrives here informs the record of *why* the copy says what it says;
    # the copy itself is still written by the planner. Kept out of the markup on
    # purpose: evidence that renders is just forwarding with extra steps.
    evidence = payload.get("evidence") or []
    if isinstance(evidence, dict):
        evidence = [evidence]
    sources = [
        str(item.get("url", "")) if isinstance(item, dict) else str(item)
        for item in (evidence if isinstance(evidence, list) else [])
    ]

    # Research is evidence to reason from, not copy to publish. A step that
    # forwards a search result straight into user-facing content has skipped the
    # deciding it was asked to do, and the result is indistinguishable from
    # success unless someone reads the page.
    for field, value in (("title", title), ("headline", headline), ("tagline", tagline)):
        problem = looks_forwarded(value)
        if problem:
            raise ActionError(
                f"{field} looks like forwarded external content: {problem}. "
                f"Got {value[:80]!r}. Research is evidence — write the copy from it "
                "rather than passing a source's own words through."
            )

    rendered = _PAGE.format(
        title=html.escape(title),
        headline=html.escape(headline),
        tagline=html.escape(tagline),
        bg=html.escape(str(payload.get("background") or "#fffdf7")),
        fg=html.escape(str(payload.get("foreground") or "#1a1a1a")),
        features="\n".join(f"    <li>{html.escape(f)}</li>" for f in features),
    )

    # The escaped forms are what actually appear in the markup, so they are what
    # the generated tests must assert on. Emitting the raw title and comparing it
    # to rendered output means any title containing an apostrophe or ampersand
    # fails its own test suite — which is exactly what happened the first time a
    # model chose "Children's Game", and it looked like a broken pipeline rather
    # than a quoting bug.
    escaped_title = html.escape(title)
    escaped_headline = html.escape(headline)

    module = (
        '"""Generated site. Reproducible from the same inputs."""\n\n'
        f"TITLE = {title!r}\n"
        f"HEADLINE = {headline!r}\n"
        f"TITLE_IN_MARKUP = {escaped_title!r}\n"
        f"HEADLINE_IN_MARKUP = {escaped_headline!r}\n\n"
        "HTML = " + repr(rendered) + "\n\n\n"
        "def render() -> str:\n"
        "    return HTML\n"
    )
    tests = (
        "from app import HEADLINE_IN_MARKUP, TITLE_IN_MARKUP, render\n\n\n"
        "def test_the_page_has_a_headline():\n"
        "    assert 'id=\"headline\"' in render()\n\n\n"
        "def test_the_headline_is_the_one_we_asked_for():\n"
        "    assert HEADLINE_IN_MARKUP in render()\n\n\n"
        "def test_the_title_is_set():\n"
        '    assert f"<title>{TITLE_IN_MARKUP}</title>" in render()\n'
    )
    build = (
        "from pathlib import Path\n\n"
        "import app\n\n"
        'Path("dist").mkdir(exist_ok=True)\n'
        'Path("dist/index.html").write_text(app.render(), encoding="utf-8")\n'
        'print("built dist/index.html")\n'
    )
    return {
        "files": {"app.py": module, "test_app.py": tests, "build.py": build},
        "title": title,
        # Carried into the report so the chain from source to published page is
        # answerable later without re-deriving it.
        "informed_by": [s for s in sources if s],
    }


# -- code ----------------------------------------------------------------


def code_write(payload: dict[str, Any], ctx: ExecutionContext) -> dict[str, Any]:
    """Write files into the workspace. Paths are confined there by `safe_join`."""
    files = payload.get("files") or {}
    if not isinstance(files, dict) or not files:
        raise ActionError("code.write needs a non-empty {path: content} mapping")
    written = [ctx.workspace.write(path, str(content)).path for path, content in files.items()]
    return {"written": written, "count": len(written)}


def code_execute(payload: dict[str, Any], ctx: ExecutionContext) -> dict[str, Any]:
    """Run a command in the workspace and hand back everything it produced.

    A non-zero exit is returned rather than raised. The plan runner decides
    whether a failure is fatal or something to repair, and it cannot decide that
    if the output has already been thrown away as an exception.
    """
    argv = payload.get("argv")
    if not isinstance(argv, list) or not argv:
        raise ActionError("code.execute needs argv as a non-empty list — never a shell string")

    result = ctx.workspace.run(
        [str(a) for a in argv],
        timeout=float(payload.get("timeout", 300.0)),
        cwd=str(payload.get("cwd", "")),
    )
    return {
        "argv": result.argv,
        "command": result.command,
        "exit_code": result.exit_code,
        "ok": result.ok,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "timed_out": result.timed_out,
        "duration_seconds": result.duration_seconds,
        "tail": result.tail(),
    }


# -- browser -------------------------------------------------------------


def browser_operate(payload: dict[str, Any], ctx: ExecutionContext) -> dict[str, Any]:
    """Open a page, check what a visitor would actually receive, keep evidence.

    Verification is what a *visitor* gets, not what the generator intended: the
    status, the rendered title, and text pulled out of the live DOM. A file
    existing on disk has never been proof that a site works.
    """
    url = str(payload.get("url") or "").strip()
    if not url:
        raise ActionError("browser.operate needs a url")

    expect_title = payload.get("expect_title")
    selectors: dict[str, str] = payload.get("expect_text") or {}
    shot_name = payload.get("screenshot")

    session = ctx.browser()
    with session as browser:
        page = browser.open(url)
        extracted: dict[str, str] = {}
        for selector in selectors:
            got = browser.extract(f"(document.querySelector({selector!r})||{{}}).textContent || ''")
            extracted[selector] = (got or "").strip()

        evidence: list[str] = []
        if shot_name:
            shot = browser.screenshot(ctx.evidence_path(str(shot_name)))
            evidence.append(str(shot.path))

        problems: list[str] = []
        if not page.ok:
            problems.append(f"status {page.status}")
        if expect_title and str(expect_title) not in (page.title or ""):
            problems.append(f"title {page.title!r} does not contain {expect_title!r}")
        for selector, expected in selectors.items():
            if str(expected) not in extracted.get(selector, ""):
                problems.append(f"{selector} said {extracted.get(selector, '')!r}")

        return {
            "url": url,
            "status": page.status,
            "title": page.title,
            "ok": not problems,
            "verified": not problems,
            "problems": problems,
            "extracted": extracted,
            "evidence": evidence,
        }


# -- deployment ----------------------------------------------------------

_SLUG = re.compile(r"[^a-z0-9-]+")


def _slugify(value: str) -> str:
    return _SLUG.sub("-", value.strip().lower()).strip("-") or "site"


def site_deploy(payload: dict[str, Any], ctx: ExecutionContext) -> dict[str, Any]:
    """Publish a built site, then promote it.

    Two versions of the same act with different consequences. Publishing puts
    files somewhere nobody is looking; promoting points the public at them. The
    website factory separated them for that reason and this preserves it.

    **Outward-facing targets require authorisation.** A local directory is a
    preview on our own disk and needs none; anything a stranger can reach is a
    publication, and a plan must not be able to make one by composing steps. The
    refusal has its own type so it is never retried as though it were a failure.
    """
    target = ctx.deploy_target
    if target is None:
        raise ActionError("site.deploy needs a deployment target in the context")

    # Authorisation is checked before anything is read or written. Refusing
    # after gathering the files would still be correct, but it does work on
    # behalf of a request that was never permitted — and it makes the refusal
    # depend on the workspace being valid, which has nothing to do with it.
    public = bool(getattr(target, "is_public", False)) or payload.get("public") is True
    if public:
        approved = getattr(ctx, "approvals", None) is not None and getattr(
            ctx.approvals, "approved", False
        )
        if not approved:
            raise PublishNotAuthorised(
                f"{target.name} is outward-facing. A plan may not publish to it without an "
                "explicit approval; nothing was sent."
            )

    source = str(payload.get("source_dir") or "dist")
    slug = _slugify(str(payload.get("slug") or ctx.workspace.record.name))

    root = Path(ctx.workspace.root) / source
    if not root.is_dir():
        raise ActionError(f"nothing to deploy: {source!r} is not a directory in the workspace")

    files = {
        str(path.relative_to(root)): path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix in {".html", ".css", ".js", ".json", ".txt", ".xml"}
    }
    if not files:
        raise ActionError(f"nothing to deploy: no publishable files under {source!r}")

    version = target.publish(slug, files)
    url = target.promote(slug, version.id) if payload.get("promote", True) else ""
    return {
        "target": target.name,
        "slug": slug,
        "version_id": version.id,
        "preview_url": version.preview_url,
        "url": url,
        "files": sorted(files),
        "public": public,
        "promoted": bool(url),
    }
