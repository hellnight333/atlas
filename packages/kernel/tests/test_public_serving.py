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
    """
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


def resolve(root: Path, url_path: str) -> Path | None:
    """What `root * <root>` + `file_server` serves for a URL, or None for a 404.

    The rule the fixed config expresses, applied to the real build output: a
    path ending in "/" is a directory served by its `index.html`, anything else
    is a file, and a miss is a miss.
    """
    candidate = root / url_path.lstrip("/")
    if url_path.endswith("/"):
        candidate = candidate / "index.html"
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
    """A search result reading "Page not found" is worse than no result."""
    listed = re.findall(r"<loc>https://qevik\.ai(/[^<]*)</loc>", build.sitemap())
    for path in build.NOINDEX:
        assert path not in listed, f"{path} is advertised in the sitemap"
        html = (dist / path.lstrip("/")).read_text(encoding="utf-8")
        assert '<meta name="robots" content="noindex">' in html, path
        assert "hreflang" not in html, f"{path} advertises a language alternate"


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

    `deploy_public.sh --check` reads the Caddyfile, works out which files it
    names, and exits non-zero if the build lacks one — without touching a host.
    Driving the script itself rather than asserting on its text is the point:
    a test that greps a shell script for a filename passes on a script that
    never runs the check.
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


def caddyfile_with(root: str, rewrites: tuple[str, ...]) -> str:
    """A minimal production-shaped config, for asking what the check reads."""
    handlers = "\n".join(
        f"\t\thandle {{\n\t\t\trewrite * {path}\n\t\t\tfile_server {{\n"
        f"\t\t\t\tstatus 404\n\t\t\t}}\n\t\t}}"
        for path in rewrites
    )
    return f"qevik.ai {{\n\troot * {root}\n\tfile_server\n\n\thandle_errors {{\n{handlers}\n\t}}\n}}\n"


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
    # The invocation with its argument, not the bare filename: the comment above
    # it names the script too, and matching that would put "ships" before
    # "installs" no matter what the script actually does.
    ships = console.index('bash "$HERE/deploy_public.sh" "$TARGET"')
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
        assert f"/{missing}" in result.stderr, result.stderr


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
