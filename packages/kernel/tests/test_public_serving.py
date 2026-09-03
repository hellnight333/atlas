"""How qevik.ai is served: one page per URL, and a real 404.

Every page on the site was unreachable in production and nothing failed. The
builder was correct, the files were on disk, the deploy reported success — and
`https://qevik.ai/services/` returned the homepage, because `/etc/caddy/Caddyfile`
carried the single-page-application fallback:

    root * /srv/qevik-public
    try_files {path} /index.html
    file_server

`try_files` tests for a *file*. `/services/` is a directory, so every candidate
missed and every URL on the site — including the whole Arabic site, seven case
studies, and `/nonsense-does-not-exist/` — was rewritten to `/index.html` and
answered 200. Measured on the live site 2026-09-01.

Nothing in the Python could have caught that, which is why these tests are here
rather than only in `test_public_site.py`. Three parts, and all three are
needed:

1. The **web server config** is the one that resolves a directory to its own
   index and answers a miss with 404. Asserted against
   `infra/qevik-production.Caddyfile`, which `infra/deploy_console.sh` copies to
   `/etc/caddy/Caddyfile` — so this file is the origin of the production
   behaviour, not a description of it.
2. The **built artefact** actually satisfies that config: every URL the sitemap
   advertises has its own file with its own title, and the 404 page the config
   names exists at exactly the path it names.
3. The **deploy** carries both to the host together. This was the third way to
   be broken and it was live: the config named `/404.html` and `/ar/404.html`
   inside `/srv/qevik-public`, and nothing in this repository had ever written
   to that directory. Rolling out §1 alone would have pointed `handle_errors` at
   files the host does not have, so an unknown URL would answer with a bare
   file-server error — while the deploy exited zero.

Together they say "every page serves its own page, on the live host". Any one
alone would have passed while the site was broken.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
PUBLIC = REPO / "apps" / "public"
CADDYFILE = REPO / "infra" / "qevik-production.Caddyfile"

sys.path.insert(0, str(PUBLIC))

import build  # noqa: E402

pytestmark = pytest.mark.integration


def site_block(name: str) -> str:
    """The body of one site block from the production Caddyfile.

    Read by brace depth rather than by regex: the blocks nest (`handle_errors`
    inside a site, `handle` inside that), and a line-based match would stop at
    the first closing brace and silently assert against a fragment.
    """
    source = CADDYFILE.read_text(encoding="utf-8")
    start = source.index(f"\n{name} {{") + 1
    depth, index = 0, start
    while True:
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
        index += 1


@pytest.fixture(scope="module")
def public() -> str:
    return site_block("qevik.ai")


@pytest.fixture(scope="module")
def dist(tmp_path_factory) -> Path:
    """A real build, in a temporary directory, leaving the module as it found it.

    `build.ASSETS` is a process-global map from `site.css` to
    `site.9f3a2b1c.css`, filled by `build.main()` as it hashes and copies assets
    and read by `shell()` every time it writes an `/assets/` URL. It is module
    state, and this file imports the same `build` module every other test file
    imports.

    Leaving it filled is not harmless. `test_public_site.py` renders pages
    through `shell()` in this same process and asserts every `/assets/` URL a
    page emits exists in `apps/public/assets/` — where only the un-hashed
    originals live. This file sorts before that one, so adding it turned a
    passing test in another file red, reporting missing assets with nothing
    pointing back here. Restore what the build changed: the tests below read the
    built files off disk and never need the map.

    Skipped, not failed, where the artwork is not in the working tree. The
    stylesheet and photography are covered by the blanket `assets/` rule in
    .gitignore — see the note at the top of `infra/deploy_public.sh` — so they
    are not in the repository and a checkout is not guaranteed to have them.
    Without them `build.main()` refuses, this fixture asserted on the refusal,
    and the thirteen tests that ask for `dist` all errored: a report that reads
    exactly like a broken site, on a machine where nothing about the site is
    being asserted at all. A missing local prerequisite has to say so by name.

    The directory being absent is the whole of that condition. A directory that
    is here but short a file is a real defect and still fails: that is the drift
    `test_every_showcase_entry_has_the_thumbnail_it_renders` exists to catch.
    """
    if not build.ARTWORK.is_dir():
        pytest.skip(
            f"{build.ARTWORK} is not in this working tree, so the site cannot be "
            "built here. The artwork is covered by the blanket `assets/` rule in "
            ".gitignore and is not in the repository — see infra/deploy_public.sh. "
            "Nothing below is being asserted about the site."
        )

    out = tmp_path_factory.mktemp("public") / "dist"
    before = dict(build.ASSETS)
    try:
        assert build.main(["--out", str(out)]) == 0, "the build refused"
    finally:
        build.ASSETS.clear()
        build.ASSETS.update(before)
    return out


# --- 1. the web server config ------------------------------------------------


def test_the_public_site_is_not_served_as_a_single_page_application(public) -> None:
    """The defect itself, stated as a rule.

    `apps/public/build.py` writes a directory per page. An SPA fallback on top
    of that does not degrade gracefully — it replaces the entire site with its
    homepage while reporting 200 for every URL.
    """
    assert "try_files" not in public, (
        "the SPA fallback is back: try_files rewrites every directory URL to the homepage"
    )


def test_a_directory_is_served_by_its_own_index(public) -> None:
    """`file_server` resolves /services/ to /services/index.html unaided.

    The `sites.qevik.ai` block has always relied on exactly this, which is how
    a customer site's /slug/ar/ resolves. Nothing else is needed here.
    """
    assert re.search(r"^\troot \* /srv/qevik-public$", public, re.M), public
    assert re.search(r"^\tfile_server$", public, re.M), public


def test_an_unknown_url_gets_the_site_404_page(public) -> None:
    """Not a bare server error, and not the homepage with a 200."""
    errors = public[public.index("handle_errors"):]
    assert "rewrite * /404.html" in errors, errors
    assert "rewrite * /ar/404.html" in errors, "an Arabic URL must 404 in Arabic"


def test_the_404_page_is_served_with_a_404_status(public) -> None:
    """`file_server` answers 200 unless told otherwise.

    A 200 carrying "page not found" is a soft 404: it is the same lie the SPA
    fallback told, and search engines index it as a real page.
    """
    errors = public[public.index("handle_errors"):]
    statuses = re.findall(r"file_server \{\s*status (\d+)", errors)
    assert statuses == ["404", "404"], errors


def test_an_unexpected_failure_is_not_dressed_as_a_designed_page(public) -> None:
    """Only 404 gets the written page; anything else answers with its own code."""
    errors = public[public.index("handle_errors"):]
    assert "{err.status_code} == 404" in errors
    assert 'respond "{err.status_code} {err.status_text}" {err.status_code}' in errors


def test_the_deploy_validates_the_config_before_restarting_caddy() -> None:
    """A malformed Caddyfile has taken this server down once already, and the
    admin API is off so `reload` is not available. Validate, then restart."""
    deploy = (REPO / "infra" / "deploy_console.sh").read_text(encoding="utf-8")
    assert "caddy validate --config /etc/caddy/Caddyfile" in deploy
    assert "systemctl restart caddy" in deploy
    assert deploy.index("caddy validate") < deploy.index("systemctl restart caddy")


# --- 2. the artefact that config serves --------------------------------------


def served_by(root: Path, url_path: str) -> Path:
    """Where `root * <root>` + `file_server` looks for a URL.

    The rule the fixed config expresses, and the rule `build.py` writes by: a
    path ending in "/" is a directory served by its `index.html`, anything else
    is a file at exactly that path. Written once, because a second copy of it
    drifts and this file's whole subject is a server and a builder that
    disagreed about where a page lives.
    """
    candidate = root / url_path.lstrip("/")
    return candidate / "index.html" if url_path.endswith("/") else candidate


def resolve(root: Path, url_path: str) -> Path | None:
    """What that rule serves for a URL against a real build, or None for a 404."""
    candidate = served_by(root, url_path)
    return candidate if candidate.is_file() else None


def title_of(html: str) -> str:
    return re.search(r"<title>(.*?)</title>", html, re.S).group(1)


def test_every_url_in_the_sitemap_serves_its_own_page(dist) -> None:
    """The measured defect, against the artefact: fourteen URLs, one page.

    Distinctness is the assertion that matters. Every one of these resolved
    under the old config too — to the same 25,331 bytes of homepage.
    """
    listed = re.findall(r"<loc>https://qevik\.ai(/[^<]*)</loc>", build.sitemap())
    assert len(listed) > 10, listed

    served = {}
    for url in listed:
        page = resolve(dist, url)
        assert page is not None, f"{url} is in the sitemap and serves nothing"
        served[url] = title_of(page.read_text(encoding="utf-8"))

    assert served["/services/"] == "Services — Qevik"
    assert served["/"] == "Qevik — digital products built around your business"
    assert len(set(served.values())) == len(served), "two URLs serve the same page"


def test_an_unknown_url_resolves_to_nothing_so_the_server_can_404(dist) -> None:
    for url in ("/nonsense-does-not-exist/", "/services/nope/", "/ar/nope/", "/wrong.html"):
        assert resolve(dist, url) is None, f"{url} resolved to a page"


def test_the_404_page_exists_at_the_path_the_web_server_rewrites_to(dist, public) -> None:
    """A rewrite to a file that is not there produces a bare server 404."""
    for rewrite in re.findall(r"rewrite \* (\S+)", public):
        assert (dist / rewrite.lstrip("/")).is_file(), f"{rewrite} was not built"


def test_the_404_page_is_a_real_page_of_this_site(dist) -> None:
    """Same shell as everything else — header, nav, phone, operating entity."""
    html = (dist / "404.html").read_text(encoding="utf-8")
    assert "Asia Link Internet Content Provider LLC" in html
    assert "+971 50 102 9104" in html
    for href in ("/services/", "/work/", "/about/", "/contact/"):
        assert f'href="{href}"' in html, href


def test_the_arabic_404_answers_in_arabic_and_right_to_left(dist) -> None:
    html = (dist / "ar" / "404.html").read_text(encoding="utf-8")
    assert 'lang="ar" dir="rtl"' in html
    assert len(re.findall(r"[؀-ۿ]", html)) > 200
    for href in ("/ar/services/", "/ar/work/", "/ar/contact/"):
        assert f'href="{href}"' in html, href


def test_the_404_pages_are_kept_out_of_the_index(dist) -> None:
    """A search result reading "Page not found" is worse than no result.

    The assertion is against `<link rel="alternate">` specifically, not against
    the word "hreflang". That pair is the statement to a search engine — "index
    these two pages as one another's translations" — and it is the statement
    these two pages must not make. The `hreflang` attribute on the header's
    language link is a different thing: it describes where a link goes, to a
    person clicking it, and the test below requires it.
    """
    listed = re.findall(r"<loc>https://qevik\.ai(/[^<]*)</loc>", build.sitemap())
    for path in build.NOINDEX:
        assert path not in listed, f"{path} is advertised in the sitemap"
        html = (dist / path.lstrip("/")).read_text(encoding="utf-8")
        assert '<meta name="robots" content="noindex">' in html, path
        assert '<link rel="alternate"' not in html, (
            f"{path} advertises a language alternate to a search engine")


def test_the_404_keeps_the_language_switch_the_rest_of_the_site_has(dist) -> None:
    """Both languages have a 404, so both 404s must offer the other one.

    hreflang and the visible switch were decided by one flag, so excluding the
    404 pages from the index also stripped the header's language link — leaving
    the single page on the site where a visitor is most lost as the only page
    with no way back into their own language. The two are separate statements:
    one is for a crawler, one is for a person.
    """
    english = (dist / "404.html").read_text(encoding="utf-8")
    arabic = (dist / "ar" / "404.html").read_text(encoding="utf-8")

    assert '<a class="lang" href="/ar/404.html"' in english, english[:2000]
    assert '<a class="lang" href="/404.html"' in arabic, arabic[:2000]
    # And it goes somewhere. A switch is only navigation if the page it names is
    # on disk under the same rule `file_server` resolves URLs by.
    assert resolve(dist, "/ar/404.html") is not None
    assert resolve(dist, "/404.html") is not None


def test_the_404_offers_every_route_the_site_actually_has(dist) -> None:
    """The page's whole content is the list of pages, in both languages."""
    english = (dist / "404.html").read_text(encoding="utf-8")
    arabic = (dist / "ar" / "404.html").read_text(encoding="utf-8")
    for route in build.PRIMARY:
        assert f'<li><a href="{route}">' in english, route
        assert f'<li><a href="{build.counterpart(route)}">' in arabic, route


def test_a_route_added_to_the_site_cannot_go_missing_from_the_404(monkeypatch) -> None:
    """So the list on the page is driven by the routes, not written out again.

    Kept by hand it drifts, and the direction it drifts in is the one where the
    site gains a page the 404 does not offer — on the one page whose entire job
    is to name the pages that exist. A route with no line of its own now fails
    the build asking for one, instead of vanishing from the list.
    """
    monkeypatch.setitem(build.PAGES, "/pricing/", ("Pricing", "Pricing — Qevik", "."))
    monkeypatch.setattr(build, "PRIMARY", build.PRIMARY + ("/pricing/",))

    with pytest.raises(KeyError):
        build.not_found()

    monkeypatch.setitem(build.NOT_FOUND_GLOSS, "/pricing/", "What it costs.")
    offered = build.not_found()
    assert '<li><a href="/pricing/">Pricing</a>' in offered, offered
    assert "What it costs." in offered, offered


# --- 3. the deploy that puts both of those on the host -----------------------
#
# The two halves above are each necessary and together still not sufficient. The
# config was correct in this repository and the pages were built in this
# repository, and there was no path from here to `/srv/qevik-public` at all:
# `infra/deploy_console.sh` copied the Caddyfile and restarted Caddy, and
# nothing anywhere shipped `apps/public`. Installing that config on its own
# points `handle_errors` at two files the host has never had, and every unknown
# URL answers with a bare file-server error instead of the written page — while
# the deploy exits zero, which is how the original defect survived for weeks.


DEPLOY_PUBLIC = REPO / "infra" / "deploy_public.sh"
DEPLOY_CONSOLE = REPO / "infra" / "deploy_console.sh"


def preflight(dist: Path, caddyfile: Path | None = None):
    """The deploy's own pre-flight, run for real against a built directory.

    `deploy_public.sh --check` reads the Caddyfile, refuses a config that has
    gone back to serving the site as a single-page application, and exits
    non-zero where the build cannot answer a URL the config or the sitemap
    names — without touching a host. Driving the script itself rather than
    asserting on its text is the point: a test that greps a shell script for a
    filename passes on a script that never runs the check.
    """
    env = dict(os.environ)
    if caddyfile is not None:
        env["QEVIK_CADDYFILE"] = str(caddyfile)
    return subprocess.run(
        ["bash", str(DEPLOY_PUBLIC), "--check", str(dist)],
        capture_output=True,
        text=True,
        env=env,
    )


def caddyfile_with(
    root: str, rewrites: tuple[str, ...], *, spa_fallback: bool = False
) -> str:
    """A minimal production-shaped config, for asking what the check reads."""
    handlers = "\n".join(
        f"\t\thandle {{\n\t\t\trewrite * {path}\n\t\t\tfile_server {{\n"
        f"\t\t\t\tstatus 404\n\t\t\t}}\n\t\t}}"
        for path in rewrites
    )
    fallback = "\ttry_files {path} /index.html\n" if spa_fallback else ""
    return (
        f"qevik.ai {{\n\troot * {root}\n{fallback}\tfile_server\n\n"
        f"\thandle_errors {{\n{handlers}\n\t}}\n}}\n"
    )


def test_the_deploy_that_installs_this_config_also_ships_the_site_it_serves() -> None:
    """The gap itself. `/srv/qevik-public` had no writer in this repository."""
    console = DEPLOY_CONSOLE.read_text(encoding="utf-8")
    assert "deploy_public.sh" in console, (
        "deploy_console.sh installs a Caddyfile that serves /srv/qevik-public "
        "and nothing puts the site there")
    assert DEPLOY_PUBLIC.is_file()


def test_the_site_is_shipped_before_the_config_that_names_its_pages() -> None:
    """Order, not merely presence.

    The new files are inert under the old config, which rewrites everything to
    the homepage regardless — so content first is free. The reverse order leaves
    a window in which the server rewrites to a page that is not there.
    """
    console = DEPLOY_CONSOLE.read_text(encoding="utf-8")
    # The invocation, not the bare filename: the comment above it names the
    # script too, and matching that would put "ships" before "installs" no
    # matter what the script actually does. The target is no longer passed as an
    # argument — it is exported by the resolver and inherited, so the two halves
    # of one deploy cannot land on different hosts.
    ships = console.index('bash "$HERE/deploy_public.sh"')
    installs = console.index('"$TARGET:/etc/caddy/Caddyfile"')
    restarts = console.index("systemctl restart caddy")
    assert ships < installs < restarts, (
        "the Caddyfile is installed before the pages it rewrites to are on the host")


def test_the_deploy_accepts_the_build_this_repository_produces(dist) -> None:
    """Negative control. Without this, the refusal below could be a script that
    refuses everything, which would be a deploy that never runs."""
    result = preflight(dist)
    assert result.returncode == 0, result.stderr
    assert "/srv/qevik-public" in result.stdout, result.stdout


def test_the_deploy_refuses_a_build_missing_a_page_the_config_rewrites_to(
    dist, tmp_path
) -> None:
    """The finding, as a gate.

    Each of the two error pages is removed in turn, because a check that only
    looks for `/404.html` would ship an Arabic site that answers in English.
    """
    for missing in ("404.html", "ar/404.html"):
        broken = tmp_path / missing.replace("/", "-")
        shutil.copytree(dist, broken)
        (broken / missing).unlink()

        result = preflight(broken)
        assert result.returncode != 0, (
            f"the deploy would have shipped a config rewriting to /{missing} "
            f"with no such file: {result.stdout}")
        # A whole line: "/ar/404.html" contains "/404.html", so a refusal naming
        # only the Arabic page would otherwise satisfy the English case.
        assert f"    /{missing}\n" in result.stderr, result.stderr


def test_the_deploy_reads_what_to_check_from_the_config_rather_than_repeating_it(
    dist, tmp_path
) -> None:
    """A rewrite added to the Caddyfile with no page behind it fails on the
    operator's machine, not on qevik.ai.

    Written down twice, the two lists drift, and the direction they drift in is
    always the one where the config names more than the build has.
    """
    fixture = tmp_path / "Caddyfile"
    fixture.write_text(
        caddyfile_with("/srv/somewhere-else", ("/404.html", "/gone.html")),
        encoding="utf-8",
    )

    result = preflight(dist, caddyfile=fixture)
    assert result.returncode != 0, result.stdout
    assert "/gone.html" in result.stderr, result.stderr
    # And the document root it would have shipped to comes from the same read.
    assert "/srv/somewhere-else" in result.stdout, result.stdout


def test_the_deploy_verifies_the_live_404_instead_of_reporting_success(dist) -> None:
    """`scp` exiting zero is not evidence that a URL answers.

    Two assertions, because the status alone is not enough: a rewrite to a file
    the host does not have *also* answers 404, as a bare file-server error. The
    deploy greps for a string only the built page contains, and that string is
    asserted here against the real build so the two cannot drift apart.
    """
    console = DEPLOY_CONSOLE.read_text(encoding="utf-8")

    # At the origin. This deploy changes what the origin serves, and Cloudflare
    # can still be answering for what it served before.
    assert "--resolve qevik.ai:443:127.0.0.1" in console, console

    assert '[ "$miss_code" = "404" ]' in console
    marker = "That page is not here"
    assert f"grep -q '{marker}'" in console
    assert marker in (dist / "404.html").read_text(encoding="utf-8"), (
        "the deploy checks the live 404 for a string the 404 page no longer has, "
        "so the check would fail on a correct deploy")
    assert 'grep -q \'dir="rtl"\'' in console, "a wrong /ar/ URL must 404 in Arabic"


# --- 3b. the check itself, in a checkout that cannot build the site ----------
#
# Everything above that takes `dist` skips where `apps/public/assets/` is absent,
# and it is absent in this repository by design — the blanket `assets/` rule in
# .gitignore covers the stylesheet and the twenty-odd photographs. So on a fresh
# clone, on CI, and on the machine this loop runs on, the gate whose entire job
# is to refuse a build the config cannot serve is never exercised at all. That
# is the shape of every defect this file records: a check that cannot fail
# because nothing runs it.
#
# `--check` reads a *directory*, so it does not need the real build to be
# checkable. These drive the same script against directories shaped like one.

FIXTURE_URLS = ("/", "/services/", "/work/", "/work/apex/", "/ar/", "/ar/services/")


def a_sitemap(urls: tuple[str, ...]) -> str:
    entries = "\n".join(
        f"  <url><loc>https://qevik.ai{url}</loc><priority>0.8</priority></url>"
        for url in urls
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{entries}\n</urlset>\n"
    )


def a_built_site(
    root: Path,
    urls: tuple[str, ...] = FIXTURE_URLS,
    error_pages: tuple[str, ...] = ("/404.html", "/ar/404.html"),
) -> Path:
    """A directory shaped like a build of the site, without building one.

    Laid out by `served_by`, the same rule the builder and the config agree on,
    so a fixture cannot be right here and wrong on the host.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "robots.txt").write_text("User-agent: *\nAllow: /\n", encoding="utf-8")
    for url in (*urls, *error_pages):
        page = served_by(root, url)
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(f"<title>{url}</title>", encoding="utf-8")
    (root / "sitemap.xml").write_text(a_sitemap(urls), encoding="utf-8")
    return root


def test_the_check_accepts_a_directory_that_satisfies_the_production_config(
    tmp_path,
) -> None:
    """Negative control, and it runs everywhere.

    Without it every refusal below is satisfied by a check that refuses
    everything, which is a deploy that can never run.
    """
    result = preflight(a_built_site(tmp_path / "dist"))
    assert result.returncode == 0, result.stderr
    assert "/srv/qevik-public" in result.stdout, result.stdout
    # And it says what it checked. A stage that silently did nothing passes too.
    assert "every path the config names is present" in result.stdout, result.stdout
    assert f"all {len(FIXTURE_URLS)} URLs in the sitemap" in result.stdout, result.stdout


def test_the_check_refuses_a_build_missing_a_page_the_config_names(tmp_path) -> None:
    """The finding this whole task came from, asserted without the artwork.

    Each error page in turn, because a check that only looks for `/404.html`
    ships an Arabic site that answers a missing page in English.

    The name is matched as a whole line, because "/ar/404.html" contains
    "/404.html": a refusal naming only the Arabic page would otherwise satisfy
    the English case.
    """
    for missing in ("/404.html", "/ar/404.html"):
        dist = a_built_site(tmp_path / f"without{missing.replace('/', '-')}")
        served_by(dist, missing).unlink()

        result = preflight(dist)
        assert result.returncode != 0, result.stdout
        assert f"    {missing}\n" in result.stderr, result.stderr


def test_the_check_refuses_a_directory_where_the_config_names_a_file(tmp_path) -> None:
    """`rewrite * /404.html` names a file. A directory of that name 404s the 404."""
    dist = a_built_site(tmp_path / "dist")
    page = dist / "404.html"
    page.unlink()
    page.mkdir()
    (page / "index.html").write_text("<title>not found</title>", encoding="utf-8")

    result = preflight(dist)
    assert result.returncode != 0, result.stdout
    assert "    /404.html\n" in result.stderr, result.stderr


def test_the_check_refuses_a_url_the_sitemap_advertises_and_the_build_cannot_serve(
    tmp_path,
) -> None:
    """The other half of the same defect, pointing the other way.

    The rewrite targets are files the *config* names; these are pages the
    *sitemap* names. A build that stops emitting `services/index.html` satisfies
    every check on the config and still 404s a URL this site tells search
    engines is a page — and `/services/` is exactly the URL that was broken.
    """
    dist = a_built_site(tmp_path / "dist")
    served_by(dist, "/services/").unlink()

    result = preflight(dist)
    assert result.returncode != 0, result.stdout
    # A whole line: "/ar/services/" is still built and must not be what is named.
    assert "    /services/\n" in result.stderr, result.stderr


def test_the_check_refuses_a_sitemap_that_advertises_nothing(tmp_path) -> None:
    """Otherwise the URL check passes by having no URLs, which is not a pass."""
    dist = a_built_site(tmp_path / "dist")
    (dist / "sitemap.xml").write_text(a_sitemap(()), encoding="utf-8")

    result = preflight(dist)
    assert result.returncode != 0, result.stdout
    assert "sitemap.xml" in result.stderr, result.stderr


def test_the_check_refuses_the_single_page_application_fallback(tmp_path) -> None:
    """The premise the rest of the check rests on, made a refusal.

    Under `try_files {path} /index.html` every directory URL is rewritten to the
    homepage and answers 200, so nothing ever reaches `handle_errors` — and then
    "is /404.html present" and "does /services/ resolve" both pass against a
    site serving one page to every URL on it. The build here satisfies every
    other check, so only the config is being judged.
    """
    fixture = tmp_path / "Caddyfile"
    fixture.write_text(
        caddyfile_with("/srv/qevik-public", ("/404.html",), spa_fallback=True),
        encoding="utf-8",
    )

    result = preflight(a_built_site(tmp_path / "dist"), caddyfile=fixture)
    assert result.returncode != 0, result.stdout
    assert "try_files" in result.stderr, result.stderr


def test_the_check_needs_no_credentials_and_so_can_run_anywhere(tmp_path) -> None:
    """A gate an operator cannot run is a gate that does not run.

    The other mode of this script resolves a deploy target from
    `infra/deploy_targets.conf` and opens SSH connections with that identity.
    `--check` is run here with `HOME` pointing at an empty directory and no
    target named, so there is no key to find and no host to reach: it must
    still decide, both ways.
    """
    home = tmp_path / "no-keys-here"
    home.mkdir()
    env = dict(os.environ, HOME=str(home))

    def check(dist: Path):
        return subprocess.run(
            ["bash", str(DEPLOY_PUBLIC), "--check", str(dist)],
            capture_output=True,
            text=True,
            env=env,
        )

    assert check(a_built_site(tmp_path / "good")).returncode == 0

    broken = a_built_site(tmp_path / "broken")
    served_by(broken, "/ar/404.html").unlink()
    refusal = check(broken)
    assert refusal.returncode != 0, refusal.stdout
    assert "    /ar/404.html\n" in refusal.stderr, refusal.stderr


# --- 4. and building here changes nothing for the rest of the suite ----------


def test_a_build_leaves_the_asset_map_as_it_found_it(dist) -> None:
    """The guard on the `dist` fixture's cleanup, stated as the thing that broke.

    `build.ASSETS` maps `site.css` to `site.9f3a2b1c.css` and `shell()` reads it
    for every `/assets/` URL it writes. A build fills it and it is module state,
    so `test_public_site.py` — same process, same imported module, and it sorts
    after this file — then rendered its pages pointing at hashed filenames that
    exist only inside a `dist` directory. Its asset check went red the day this
    file was added, naming missing files and nothing about a fixture over here.

    Asserted by rendering a page rather than by comparing the dict, because the
    URL a page emits is what actually broke.
    """
    html = build.shell("/", build.home())
    referenced = set(re.findall(r"/assets/([\w.\-]+)", html))
    assert referenced, "the home page points at no assets at all"
    # `favicon.svg` is written at build time rather than copied from disk, and
    # is excluded here for the same reason `test_public_site.py` excludes it.
    missing = sorted(
        name
        for name in referenced
        if not name.startswith("favicon") and not (PUBLIC / "assets" / name).exists()
    )
    assert missing == [], f"a build leaked hashed asset names into shell(): {missing}"


# --- 5. and a checkout that cannot build the site says which, not "it failed" -


def test_the_build_refuses_whole_when_the_artwork_is_not_in_this_checkout(
    monkeypatch, tmp_path, capsys
) -> None:
    """What the `dist` fixture's skip is derived from, asserted on the builder.

    `apps/public/assets/` is covered by the blanket `assets/` rule in .gitignore,
    so the stylesheet and the twenty-odd photographs are not in the repository
    and a checkout is not guaranteed to have them. That is a deliberate decision
    — `infra/deploy_public.sh` says so at the top — and its cost landed on the
    wrong reader: the build refused, the fixture asserted on the refusal, and
    every test that wanted a built site errored at once. Thirteen errors and no
    line naming a file is indistinguishable from a broken site, and it was read
    as one.

    Two properties make the difference, and neither held before: the refusal
    names *every* file it wants, so one name reads as a file that went missing
    and the whole list reads as a working tree that never had them; and it comes
    before `out` is emptied, so a run that cannot build the site does not also
    destroy the build already sitting there.
    """
    monkeypatch.setattr(build, "ARTWORK", tmp_path / "assets")  # never created

    out = tmp_path / "dist"
    out.mkdir()
    (out / "index.html").write_text("the previous build", encoding="utf-8")

    assert build.main(["--out", str(out)]) == 1

    refusal = capsys.readouterr().err
    assert "site.css" in refusal, refusal
    assert "og.png" in refusal, refusal
    for data in build.SHOWCASE.values():
        assert data["shot"] in refusal, f"{data['shot']} missing from: {refusal}"

    assert (out / "index.html").read_text(encoding="utf-8") == "the previous build", (
        "the build emptied the output directory before finding out it could not "
        "write a new one")


def test_artwork_that_is_here_but_short_a_file_fails_rather_than_skipping(
    monkeypatch, tmp_path, capsys
) -> None:
    """The skip is narrow on purpose: absent directory, and nothing else.

    A directory that exists and is missing a file is the drift the asset checks
    are for — a SHOWCASE entry pointing at a thumbnail nobody copied, which
    builds clean and renders a broken box. Skipping on "some file is missing"
    would have swallowed exactly that. So the condition is the directory, and a
    build with the directory present still has to satisfy every name in it.
    """
    artwork = tmp_path / "assets"
    artwork.mkdir()
    monkeypatch.setattr(build, "ARTWORK", artwork)

    # The `dist` fixture skips on this being false, and here it is true — so a
    # working tree in this state runs the build and reports what it finds.
    assert build.ARTWORK.is_dir()

    assert build.main(["--out", str(tmp_path / "dist")]) == 1
    assert "site.css" in capsys.readouterr().err
