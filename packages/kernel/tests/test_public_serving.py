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
rather than only in `test_public_site.py`. Four parts, and all four are needed:

1. The **web server config** is the one that resolves a directory to its own
   index and answers a miss with 404. Asserted against
   `infra/qevik-production.Caddyfile`, which `infra/deploy_public.sh` copies to
   `/etc/caddy/Caddyfile` — so this file is the origin of the production
   behaviour, not a description of it.
2. The **built artefact** actually satisfies that config: every URL the sitemap
   advertises has its own file with its own title, and the 404 page the config
   names exists at exactly the path it names.
3. The **deploy** carries both to the host together, and carries nothing away.
   This was the third way to be broken and it was live: the config named
   `/404.html` and `/ar/404.html` inside `/srv/qevik-public`, and nothing in
   this repository had ever written to that directory. Rolling out §1 alone
   would have pointed `handle_errors` at files the host does not have, so an
   unknown URL would answer with a bare file-server error — while the deploy
   exited zero. The same file is also the *whole* web server, so §3b asks the
   other half of the question: what does installing it stop the host serving?
4. The deploy **that anything actually runs** is that deploy. This is the fourth
   way, and it is the one that let §1–§3 be committed, reviewed, tested and
   marked production-verified while every URL on qevik.ai still served the
   homepage. The publishing script existed and was correct; it was called by
   `infra/deploy_console.sh`, and the development loop's `deployed` gate runs
   `infra/deploy_control.sh`, which called neither it nor the console script.
   Nothing applied the fix, so §4 reads the script name out of
   `infra/devloop/gates.py` and follows what that script runs.

Together they say "every page serves its own page, on the live host, by a deploy
something runs". Any one alone passed while the site was broken.
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
    admin API is off so `reload` is not available. Validate, then restart.

    Validated at the path it is staged at rather than the live one, because it
    is now validated *before* it is installed — so there is no moment in which
    `/etc/caddy/Caddyfile` holds a config no binary has accepted. `--adapter`
    goes with that: Caddy infers the adapter from the file name, and the staged
    copy is not called `Caddyfile` yet.
    """
    deploy = (REPO / "infra" / "deploy_public.sh").read_text(encoding="utf-8")
    validates = "caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile.incoming"
    assert validates in deploy
    assert 'echo "==> restarting Caddy"' in deploy
    assert deploy.index(validates) < deploy.index('echo "==> restarting Caddy"')


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
DEPLOY_CONTROL = REPO / "infra" / "deploy_control.sh"
GATES = REPO / "infra" / "devloop" / "gates.py"


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


def check_config(live: Path, caddyfile: Path | None = None):
    """`deploy_public.sh --check-config` — what installing this repository's
    config over `live` would stop the host serving, asked without a host.

    The deploy replaces `/etc/caddy/Caddyfile` wholesale, and that file is four
    hostnames including the console and every customer site. Driving the script
    rather than reading it, for the same reason `preflight` does.
    """
    env = dict(os.environ)
    if caddyfile is not None:
        env["QEVIK_CADDYFILE"] = str(caddyfile)
    return subprocess.run(
        ["bash", str(DEPLOY_PUBLIC), "--check-config", str(live)],
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


def test_one_script_ships_the_pages_and_the_config_that_names_them() -> None:
    """The gap itself, and then the gap that replaced it.

    `/srv/qevik-public` had no writer in this repository at all. Once it had
    one, the pages and the config that rewrites to them were installed by two
    different scripts — and the second was never run.
    """
    # Matched without the closing quote: the config is copied to a staging path
    # beside the live one now, so the destination reads `…/Caddyfile.incoming"`.
    # What this is looking for is a script that sends a Caddyfile to that host
    # at all, whatever it lands on.
    installers = sorted(
        path.name
        for path in sorted((REPO / "infra").glob("*.sh"))
        if '"$TARGET:/etc/caddy/Caddyfile' in path.read_text(encoding="utf-8")
    )
    assert installers == ["deploy_public.sh"], (
        "the config that serves /srv/qevik-public must be installed by the same "
        f"script that writes it, and by only that script; found {installers}")
    public = DEPLOY_PUBLIC.read_text(encoding="utf-8")
    assert 'python3 "$ROOT/apps/public/build.py"' in public, (
        "the script that installs the config must be the one that builds the "
        "pages it names")


def test_the_site_is_shipped_before_the_config_that_names_its_pages() -> None:
    """Order, not merely presence.

    The new files are inert under the old config, which rewrites everything to
    the homepage regardless — so content first is free. The reverse order leaves
    a window in which the server rewrites to a page that is not there.
    """
    public = DEPLOY_PUBLIC.read_text(encoding="utf-8")
    ships = public.index("rsync -az --partial")
    installs = public.index('"$TARGET:/etc/caddy/Caddyfile')
    # The banner rather than `systemctl restart caddy`: the rollback path calls
    # that too, above, and matching it would compare against the wrong restart.
    restarts = public.index('echo "==> restarting Caddy"')
    assert ships < installs < restarts, (
        "the Caddyfile is installed before the pages it rewrites to are on the host")


def test_the_config_it_replaces_is_kept_and_put_back_if_caddy_will_not_start() -> None:
    """This file fronts four hostnames. A config that validates and then fails
    to start takes down the marketing site, the console, the customer sites and
    the operator's fallback door at once — so the one being replaced is kept
    beside it and restored rather than left for someone to notice.

    Every path that can leave a config live and wrong ends in the rollback: one
    that will not move into place, one that installs and will not start, and —
    reached from `deploy_control.sh`, which is the only place that can see it —
    one that starts and stops routing the API. A config that does not validate
    is deliberately *not* one of them: it was never installed, so there is
    nothing live to put back and a needless Caddy restart is not free.
    """
    public = DEPLOY_PUBLIC.read_text(encoding="utf-8")
    backs_up = public.index("cp -a /etc/caddy/Caddyfile /etc/caddy/Caddyfile.previous")
    installs = public.index('"$TARGET:/etc/caddy/Caddyfile')
    assert backs_up < installs, "the config is overwritten before it is kept"
    assert "systemctl is-active --quiet caddy" in public, (
        "`systemctl restart` succeeds on a unit that then exits")
    assert public.count("restore_config || true") >= 2, (
        "the rollback must run for a config that will not move into place and "
        "for one that installs and does not come up")
    assert "restore_config || exit $?" in public, (
        "`--restore-config` must report whether the rollback itself worked; "
        "deploy_control.sh branches on that")


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


# --- 3b. and does not carry away what it did not know the host was serving ---
#
# The fix for this task installs a whole `/etc/caddy/Caddyfile` from this
# repository, and that file is the entire web server: qevik.ai, the operator's
# console at app.qevik.ai, every customer site at sites.qevik.ai, and the
# fallback door on the bare IP. Anything the host serves that this copy does not
# declare stops being served at the restart — silently, with a zero exit, and
# unseen by every check the deploy makes afterwards, all of which ask about
# qevik.ai.
#
# Two host-side mechanisms in this same directory produce exactly that:
# `enable_domain.sh` puts a customer domain in `/etc/caddy/sites.d/` behind an
# `import`, and `secure_8443.sh` rewrites the `:8443` block's address in place to
# take that port off the public internet. Neither is in
# `infra/qevik-production.Caddyfile`.


def test_the_check_reads_site_addresses_and_not_the_blocks_inside_them() -> None:
    """What "what the host serves" means, pinned.

    A Caddyfile nests: `handle_errors` inside a site, `handle` inside that,
    `log`, `tls` and `file_server` blocks throughout — every one of them a line
    ending in `{`. A reader that took those for addresses would compare two
    lists of directives and find them equal, which is a check that cannot fail.

    Comparing the config against itself is also the negative control for the
    refusals below: without this, they could be a check that refuses everything,
    which is a deploy that never runs.
    """
    result = check_config(CADDYFILE)
    assert result.returncode == 0, result.stderr
    listed = set(re.findall(r"^\s+site (\S+)$", result.stdout, re.M))
    # Hard-coded deliberately: a hostname appearing or disappearing here is a
    # change to what this server answers for, and is worth an edit to a test.
    assert listed == {
        "qevik.ai",
        "www.qevik.ai",
        "app.qevik.ai",
        "sites.qevik.ai",
        "https://2.28.62.83:8443",
        ":80",
    }, result.stdout


def test_a_config_that_stops_serving_a_hostname_the_host_serves_is_refused(
    tmp_path,
) -> None:
    """A customer domain added on the host and never written down here.

    Not reported, the way a host-only file under the document root is: that
    404s one URL and might have been left by anybody, while this takes a whole
    hostname off the air and every site block on a server is deliberate.
    """
    live = tmp_path / "Caddyfile"
    live.write_text(
        CADDYFILE.read_text(encoding="utf-8")
        + "\ncustomer.example.com {\n\troot * /srv/sites/customer/current\n"
        "\tfile_server\n}\n",
        encoding="utf-8",
    )

    result = check_config(live)
    assert result.returncode != 0, (
        f"the deploy would have taken customer.example.com off the air: "
        f"{result.stdout}")
    assert "customer.example.com" in result.stderr, result.stderr


def test_a_hostname_reached_through_an_import_is_not_silently_dropped(
    tmp_path,
) -> None:
    """`enable_domain.sh` writes the block into `/etc/caddy/sites.d/` and never
    touches the Caddyfile except through the `import` that pulls it in. The
    hostname is therefore invisible in the live file, and only the `import` line
    says it is there at all."""
    live = tmp_path / "Caddyfile"
    live.write_text(
        CADDYFILE.read_text(encoding="utf-8")
        + "\nimport /etc/caddy/sites.d/*.caddy\n",
        encoding="utf-8",
    )

    result = check_config(live)
    assert result.returncode != 0, result.stdout
    assert "/etc/caddy/sites.d/*.caddy" in result.stderr, result.stderr


def test_a_config_that_only_adds_hostnames_is_not_refused(tmp_path) -> None:
    """The other negative control, and the one that matters most: this deploy
    exists to replace exactly this config, so refusing it would be a guard that
    blocks the fix it was written to protect."""
    live = tmp_path / "Caddyfile"
    live.write_text(
        "qevik.ai {\n\troot * /srv/qevik-public\n"
        "\ttry_files {path} /index.html\n\tfile_server\n}\n",
        encoding="utf-8",
    )

    result = check_config(live)
    assert result.returncode == 0, result.stderr
    assert "app.qevik.ai" in result.stdout, result.stdout


def test_a_live_config_that_reads_as_no_sites_at_all_is_not_taken_for_consent(
    tmp_path,
) -> None:
    """A cut transfer and a host serving nothing look identical from here, and
    only one of them is safe to install over. Unmeasured is not a pass."""
    live = tmp_path / "Caddyfile"
    live.write_text("# a truncated read, or a file this cannot parse\n",
                    encoding="utf-8")

    result = check_config(live)
    assert result.returncode != 0, result.stdout


def test_the_deploy_asks_what_it_would_stop_serving_before_it_touches_the_host() -> None:
    """Order again, and this one is stricter than the others: the refusal has to
    come before the pages are copied, not merely before the config is installed.
    A deploy that swaps the document root and then declines to install the
    config that resolves it has changed production and fixed nothing."""
    public = DEPLOY_PUBLIC.read_text(encoding="utf-8")
    asks = public.index("read_live_config || LIVE_STATUS=$?")
    ships = public.index("rsync -az --partial")
    installs = public.index('"$TARGET:/etc/caddy/Caddyfile')
    assert asks < ships < installs, (
        "the host is modified before anything asks what this config would stop "
        "serving")
    assert "check_config_against_live \"$LIVE_CONFIG\" || exit 7" in public, (
        "the comparison is made and its answer is not acted on")


def test_the_deploy_verifies_the_live_404_instead_of_reporting_success(dist) -> None:
    """`scp` exiting zero is not evidence that a URL answers.

    Two assertions, because the status alone is not enough: a rewrite to a file
    the host does not have *also* answers 404, as a bare file-server error. The
    deploy greps for a string only the built page contains, and that string is
    asserted here against the real build so the two cannot drift apart.
    """
    public = DEPLOY_PUBLIC.read_text(encoding="utf-8")

    # At the origin. This deploy changes what the origin serves, and Cloudflare
    # can still be answering for what it served before.
    assert "--resolve qevik.ai:443:127.0.0.1" in public, public

    assert '[ "$miss_code" = "404" ]' in public
    marker = "That page is not here"
    assert f"grep -q '{marker}'" in public
    assert marker in (dist / "404.html").read_text(encoding="utf-8"), (
        "the deploy checks the live 404 for a string the 404 page no longer has, "
        "so the check would fail on a correct deploy")
    assert 'grep -q \'dir="rtl"\'' in public, "a wrong /ar/ URL must 404 in Arabic"


def test_the_deploy_checks_that_a_page_serves_its_own_page(dist) -> None:
    """The measured defect, as the deploy's own gate.

    `/services/` answering 200 was never the question — it always did. The
    deploy looks for the title only that page carries, and the title is checked
    here against the real build so a rename cannot leave the deploy grepping
    for a string production will never send.
    """
    public = DEPLOY_PUBLIC.read_text(encoding="utf-8")
    assert "grep -q '<title>Services'" in public
    served = title_of((dist / "services" / "index.html").read_text(encoding="utf-8"))
    assert served.startswith("Services"), served
    assert not title_of((dist / "index.html").read_text(encoding="utf-8")).startswith(
        "Services"), "the check would pass on a homepage served for /services/"


# --- 4. and something actually runs that deploy ------------------------------
#
# §1–§3 were all true, committed and reviewed, and qevik.ai still served the
# homepage on every URL. The publishing script was correct; nothing called it.
# `infra/deploy_console.sh` did, and the development loop's `deployed` gate runs
# `infra/deploy_control.sh` — a different script, which shipped the kernel, the
# console and `infra/`, restarted the services, verified the worker fingerprint,
# exited zero, and touched neither the public site nor `/etc/caddy/Caddyfile`.
#
# So these read the entry point out of the gate rather than naming it here. A
# test that hard-coded "deploy_control.sh" would be wrong in exactly the way the
# deploy was: right about a script, silent about which one runs.


def deploy_gate_entry_point() -> Path:
    """The script `infra/devloop/gates.py` runs for the `deployed` gate."""
    source = GATES.read_text(encoding="utf-8")
    body = source[source.index("def deployed("):]
    body = body[: body.index("\ndef ")]
    named = re.findall(r'"\./infra/([\w.-]+\.sh)"', body)
    assert len(named) == 1, f"the deployed gate runs {named}, expected one script"
    return REPO / "infra" / named[0]


def scripts_run_by(entry: Path) -> set[str]:
    """Every deploy script `entry` runs, transitively, by name.

    Follows `bash "$VAR/.../name.sh"` — the form every script here uses, and
    deliberately not a bare mention: the comment above an invocation names the
    script too, and matching prose would report a call that is not made.
    """
    seen: set[str] = set()
    pending = [entry]
    while pending:
        script = pending.pop()
        if script.name in seen or not script.is_file():
            continue
        seen.add(script.name)
        for name in re.findall(
            r'bash "\$[A-Z_]+(?:/[\w.-]+)*/([\w.-]+\.sh)"',
            script.read_text(encoding="utf-8"),
        ):
            pending.append(REPO / "infra" / name)
    return seen


def test_the_deploy_the_loop_runs_publishes_the_public_site() -> None:
    """The reopened defect, stated as a rule.

    Not "a deploy script publishes qevik.ai" — that was already true. *The one
    the gate executes* publishes qevik.ai, or the fix sits in the repository
    while production serves the homepage for every URL and the task is marked
    done.
    """
    entry = deploy_gate_entry_point()
    run = scripts_run_by(entry)
    assert "deploy_public.sh" in run, (
        f"the deployed gate runs {entry.name}, which runs {sorted(run)} — "
        "nothing there publishes qevik.ai or installs the config that serves it")


def test_both_deploy_paths_publish_the_site() -> None:
    """`deploy_console.sh` is the operator's path and `deploy_control.sh` is the
    loop's. Whichever of the two is run must leave qevik.ai correct, because the
    one certainty here is that somebody will run the other one."""
    for script in (DEPLOY_CONSOLE, DEPLOY_CONTROL):
        assert "deploy_public.sh" in scripts_run_by(script), (
            f"{script.name} deploys to the host that serves qevik.ai and does "
            "not publish it")


def test_the_reachability_check_can_answer_no(tmp_path) -> None:
    """Negative control. A follower that always finds what it looks for would
    have passed on the broken deploy too, which is the whole point of §4."""
    lonely = tmp_path / "deploy_nothing.sh"
    lonely.write_text('#!/usr/bin/env bash\n# mentions deploy_public.sh in prose\n',
                      encoding="utf-8")
    assert scripts_run_by(lonely) == {"deploy_nothing.sh"}


def test_the_loops_deploy_counts_the_site_builder_among_what_it_ships() -> None:
    """`deploy_control.sh` refuses to run when a changed runtime file is not
    covered by anything it sends — a guard that exists because `infra/` went
    unshipped for the life of the script. Now that it publishes the public site,
    `apps/public/` is shipped; while it was not listed, a change to the site
    builder would have refused every deploy of anything."""
    control = DEPLOY_CONTROL.read_text(encoding="utf-8")
    declared = re.search(r'^SHIPPED_PREFIXES="([^"]*)"', control, re.M)
    assert declared, "deploy_control.sh no longer declares what it ships"
    assert "apps/public/" in declared.group(1).split(), declared.group(1)


def test_the_public_site_is_published_after_the_control_plane_is_up() -> None:
    """Order, for the same reason the pages go before the config.

    Publishing restarts Caddy, and Caddy fronts the console and the API as well
    as the marketing site. Restarting it before the control plane has answered
    turns one failure into two, and the second one is the one that gets read.
    """
    control = DEPLOY_CONTROL.read_text(encoding="utf-8")
    fingerprint = control.index("all $COUNT worker(s) report $FINGERPRINT")
    publishes = control.index('bash "$ROOT/infra/deploy_public.sh" "$TARGET"')
    assert fingerprint < publishes, (
        "Caddy is restarted before the code behind it has been verified")


def test_restarting_caddy_is_followed_by_asking_the_console_if_it_still_answers() -> None:
    """The same Caddyfile serves app.qevik.ai. A config that fixes the
    marketing site and 404s the API is not a good deploy, and the deploy that
    installs it is the one place that can tell."""
    control = DEPLOY_CONTROL.read_text(encoding="utf-8")
    publishes = control.index('bash "$ROOT/infra/deploy_public.sh" "$TARGET"')
    # At the origin, like every other post-deploy check here: this run changed
    # what the origin serves and Cloudflare can still answer for what it did.
    checks = control.index("--resolve app.qevik.ai:443:127.0.0.1")
    assert publishes < checks
    assert "application/json*" in control[checks:], (
        "a static handler answering /api/health with HTML would pass a status check")


# --- 5. and building here changes nothing for the rest of the suite ----------


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
