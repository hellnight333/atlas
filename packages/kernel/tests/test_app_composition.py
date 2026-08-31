"""The application exists, and every surface built is reachable from it.

This file exists because of a finding, not a hypothesis. Before `qevik/app.py`,
grepping the whole kernel for calls to `install(app)` outside tests returned
nothing, and `atlas_kernel/api.py` — the module `launcher.py` actually serves —
contained no `include_router` call at all. Every route built across P2.4, P-B1
and the mission work had only ever been reached through a `TestClient` in a
fixture.

The suite was green the entire time. It proved the handlers were correct and
said nothing about whether the product existed.

So the first test here reads the kernel for router modules and asserts each one
is mounted. A new surface that nobody composes fails the suite instead of
shipping unreachable, which is the only mechanism that would have caught the
original.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from atlas_kernel.qevik import SURFACES, Wiring, create_app, health

KERNEL = Path(__file__).resolve().parents[1] / "atlas_kernel"

#: Router modules that are deliberately not part of the Qevik control plane.
#: Named individually, with the reason, because "everything except a pattern" is
#: how the next unmounted surface hides.
NOT_QEVIK = {
    # The Atlas monolith. Its own application, served separately.
    "atlas_kernel/api.py",
    # An operator surface that needs a JobRunner and a provisioned host; it is
    # mounted by the Atlas control plane, not by Qevik's.
    "atlas_kernel/control/api.py",
}


def _router_modules() -> set[str]:
    """Every module in the kernel that builds an HTTP router."""
    found = set()
    for path in KERNEL.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        if "APIRouter(" in source and "def build_router" in source:
            found.add(str(path.relative_to(KERNEL.parent)))
    return found


# ============================================ everything built is reachable

def test_every_router_in_the_kernel_is_mounted_by_the_application() -> None:
    """A router nobody mounts is a route nobody can reach.

    Not a hypothetical: this was true of every Qevik surface simultaneously,
    while the suite passed, because a TestClient in a fixture mounts routers the
    application never does.
    """
    app = create_app(Wiring())
    # The OpenAPI document, not `app.routes`. FastAPI wraps an included router
    # in an `_IncludedRouter` that carries no `.path`, so walking the route list
    # reports every mounted surface as missing — and generating this document is
    # itself a check, because a model declared inside a route factory makes it
    # raise and takes `/docs` down with it.
    mounted = set(app.openapi().get("paths", {}))

    unmounted = []
    for module in sorted(_router_modules() - NOT_QEVIK):
        prefix = _prefix_of(KERNEL.parent / module)
        if not any(path.startswith(prefix) for path in mounted):
            unmounted.append(f"{module} (prefix {prefix})")

    assert unmounted == [], (
        f"these routers exist and the application does not mount them, so "
        f"nothing can reach them: {unmounted}. Add them to "
        f"qevik/app.py::create_app, or to NOT_QEVIK with the reason.")


def _prefix_of(path: Path) -> str:
    """The router prefix a module declares."""
    import re

    match = re.search(r'APIRouter\(prefix="([^"]+)"', path.read_text(encoding="utf-8"))
    return match.group(1) if match else "/"


def test_the_scan_finds_the_routers_that_exist() -> None:
    """A completeness check that passes by finding nothing is not a check."""
    found = _router_modules()
    assert len(found) >= 5, found
    assert "atlas_kernel/mission/api.py" in found
    assert "atlas_kernel/credentials/api.py" in found
    assert "atlas_kernel/chat/api.py" in found


def test_every_named_surface_is_actually_mounted() -> None:
    """`SURFACES` is documentation until something checks it against routes."""
    app = create_app(Wiring())
    paths = " ".join(sorted(app.openapi().get("paths", {})))
    for surface in SURFACES:
        if surface == "auth":
            # `/auth`, not `/api/auth` — it predates the convention and the
            # prefix is part of every existing client's URL, so it is asserted
            # as it is rather than moved to make this line tidier.
            assert "/auth/login" in paths, surface
            continue
        if surface == "sales":
            assert "/control/sales" in paths, surface
            continue
        assert f"/api/{surface}" in paths, surface


# ============================================ auth wraps everything

@pytest.fixture
def client(tmp_path):
    app = create_app(Wiring(repository_root=tmp_path,
                            vault_path=tmp_path / "vault.json"))
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.real_auth
def test_an_unauthenticated_request_reaches_no_surface(client) -> None:
    """Auth is installed before any router, because middleware only sees routes
    added after it. A surface mounted first would be served open.

    `real_auth`, because the session fixture patches `AuthStore.authenticate` to
    a fixed operator — under that patch every request is authenticated and this
    test would pass on an application with no middleware at all.
    """
    for path in ("/api/missions", "/api/credentials", "/api/chat",
                 "/api/models", "/api/customer/actions"):
        assert client.get(path).status_code == 401, path


def test_the_api_documentation_generates(client) -> None:
    """`/docs` and `/openapi.json` are the first thing anybody opens.

    They were broken across the whole application by one model declared inside
    a route factory: the schema generator cannot see it, and generating the
    document raised rather than skipping that route.
    """
    assert client.get("/openapi.json").status_code == 200


def test_the_health_route_is_reachable_without_a_session(client) -> None:
    """A health check that needs a credential cannot tell you the vault is
    sealed, which is the thing it most needs to tell you."""
    response = client.get("/api/health")
    assert response.status_code == 200, response.text


# ============================================ health does not flatter itself

def test_a_deployment_with_nothing_configured_is_degraded_not_ready(tmp_path
                                                                   ) -> None:
    """"Healthy" would be true of an installation that cannot do anything."""
    app = create_app(Wiring(repository_root=tmp_path,
                            vault_path=tmp_path / "vault.json"))
    report = health(app)
    assert report["status"] == "degraded"
    assert "research" in report["degraded"]
    assert "approvals" in report["degraded"]


def test_an_in_memory_timeline_is_reported_as_not_durable(tmp_path) -> None:
    """It is a real timeline. It just does not survive a restart, and no
    separate worker process can see it — which is the whole point of it."""
    app = create_app(Wiring(repository_root=tmp_path,
                            vault_path=tmp_path / "vault.json"))
    missions = health(app)["components"]["missions"]
    assert missions["durable"] is False
    assert "do not survive a restart" in missions["detail"]


def test_a_file_timeline_is_reported_as_durable(tmp_path) -> None:
    app = create_app(Wiring(repository_root=tmp_path,
                            vault_path=tmp_path / "vault.json",
                            mission_timeline=tmp_path / "missions.jsonl"))
    missions = health(app)["components"]["missions"]
    assert missions["durable"] is True
    assert "missions.jsonl" in missions["detail"]


def test_a_sealed_vault_is_reported_as_sealed(tmp_path, monkeypatch) -> None:
    """With no master key the vault refuses to store rather than degrading to
    plaintext, and health says so rather than reporting credentials as fine."""
    monkeypatch.delenv("QEVIK_VAULT_MASTER_KEY", raising=False)
    app = create_app(Wiring(repository_root=tmp_path,
                            vault_path=tmp_path / "vault.json"))
    credentials = health(app)["components"]["credentials"]
    assert credentials["sealed"] is True
    assert "plaintext" in credentials["detail"]


def test_probes_are_reported_separately_from_the_vault(tmp_path) -> None:
    """They fail differently: a working vault with no probes stores keys it
    cannot test, and one number would hide which half is missing.

    This asserted `configured is False`, which pinned a real defect: the
    deployment registered no probes at all, so `/test` answered 501 for every
    provider and a stored credential could never leave PENDING_CREDENTIAL. The
    separation is still the point; the default is now real probes.
    """
    app = create_app(Wiring(repository_root=tmp_path,
                            vault_path=tmp_path / "vault.json"))
    components = health(app)["components"]
    assert "probes" in components and "credentials" in components
    assert components["probes"]["configured"] is True
    assert {"anthropic", "qwen"} <= set(app.state.credential_probes), (
        "the two providers reported broken must be testable")


def test_a_deployment_may_still_supply_its_own_probes(tmp_path) -> None:
    """The negative control on the default: an explicit set wins, so a test or
    an air-gapped deployment is not forced to make real calls."""
    app = create_app(Wiring(repository_root=tmp_path,
                            vault_path=tmp_path / "vault.json",
                            credential_probes={"anthropic": lambda _: None}))
    assert set(app.state.credential_probes) == {"anthropic"}


def test_health_never_claims_ready_because_nothing_has_failed(tmp_path) -> None:
    report = health(create_app(Wiring(repository_root=tmp_path,
                                      vault_path=tmp_path / "vault.json")))
    assert "nothing has broken yet" in report["note"]


# ============================================ wiring is injected, not imported

def test_a_deployment_supplies_its_own_sources(tmp_path) -> None:
    """The kernel does not know where an installation keeps research."""
    events: list = []
    app = create_app(Wiring(business_events=events, repository_root=tmp_path,
                            vault_path=tmp_path / "vault.json",
                            research_reader=lambda **_: {"observations": []}))
    assert app.state.business_events is events
    assert health(app)["components"]["research"]["configured"] is True


def test_the_mission_sink_is_absent_rather_than_a_no_op(tmp_path) -> None:
    """With no durable timeline there is nothing to write to, and the routes
    return 503 rather than accepting a write and dropping it."""
    app = create_app(Wiring(repository_root=tmp_path,
                            vault_path=tmp_path / "vault.json"))
    assert app.state.mission_sink is None


# ============================================ the console

def test_the_console_shell_loads_without_a_session(client) -> None:
    """The login form has to be reachable before anybody has a session, and the
    shell carries nothing private — every number on screen is fetched from an
    API that authenticates separately."""
    response = client.get("/")
    assert response.status_code == 200
    assert "Qevik Control" in response.text


def test_a_deep_link_serves_the_shell_so_reload_works(client) -> None:
    """`/missions` is a client-side route. A 404 here means every reload of a
    deep link loses the page."""
    assert client.get("/missions").status_code == 200


@pytest.mark.real_auth
def test_the_console_being_public_does_not_open_the_api(client) -> None:
    """The one thing that could go wrong with making the shell public.

    `real_auth`: the session fixture patches `authenticate` to a fixed
    operator, so without it every request here is already authenticated and the
    test would pass against an application with no middleware at all.
    """
    for path in ("/api/missions", "/api/chat", "/api/credentials",
                 "/api/models", "/api/customer/actions"):
        assert client.get(path).status_code == 401, path


def test_the_console_carries_no_secret_and_no_business_logic() -> None:
    """It arranges what the API returns. The moment it decides anything there
    are two answers to that question, and the one on screen is untested."""
    from pathlib import Path

    from atlas_kernel.qevik.app import CONSOLE

    source = (CONSOLE / "index.html").read_text(encoding="utf-8")
    # The calls, not the word. The file explains in a comment *why* it does not
    # use localStorage, and matching on raw text fails on the explanation —
    # the same trap the chat execution scan hit.
    assert "localStorage.getItem" not in source and "localStorage.setItem" not in source, (
        "a session in localStorage outlives the tab on a shared machine")
    assert "sessionStorage.getItem" in source
    # A hardcoded *value*, not the word. The login form legitimately sends
    # `password: $('p').value`, and forbidding the field name would forbid the
    # form.
    import re

    literals = re.findall(
        r"""(?:password|secret|token|api[_-]?key)\s*[:=]\s*['"][^'"]{8,}['"]""",
        source, re.I)
    assert literals == [], literals
    assert "sk-" not in source
    # A proxy for "still a thin arranger", not an architectural invariant. It
    # is raised when a genuine surface is added and never to make a failure go
    # away — the assertions below are the actual rule, and they got stricter at
    # the same time this number moved for the opportunities view.
    # Raised for the artefact review card, the awaiting-publication queue and
    # the outreach card — genuine surfaces, not a failure being silenced. The
    # rules below got stricter each time, which is the condition on moving this.
    # Raised again for the Fabric view. The rule below got stricter with it: the
    # console may not decide whether a worker is healthy. Nothing renders a
    # fleet the dispatcher would disagree with, because nothing on this side
    # computes staleness — it prints the `state` and `healthy` the API sent.
    for deriving in ("last_heartbeat", "last_seen_at -", "> 7200", "> 90",
                     "stale_after", "HEARTBEAT", "STALE_"):
        assert deriving not in source, (
            f"the console derives worker health itself via {deriving!r}; two "
            "answers to 'is this machine alive', and the one on screen is the "
            "untested one")
    # Approving and sending are two acts. A console that sends straight from
    # the review, or that posts message content back with the send, is how the
    # words that go out stop being the words that were approved.
    # Approving is a decision a person makes, and belongs on a page. Sending is
    # not, and the assertion further down keeps it off one. The console may
    # therefore approve, and must not carry the words back when it does: the
    # server re-composes and compares, so a browser that posted a subject and
    # body could approve something other than what was displayed.
    assert "outreach/approve" in source, (
        "the console reads outreach drafts it has no way to act on")
    approving = source[source.index("outreach/approve"):][:260]
    for content in ("subject", "body:", "recipient:"):
        assert content not in approving, (
            f"the approve call carries {content!r}; approval must echo only the "
            "fingerprint of what the server composed")
    assert "fingerprint" in approving, (
        "an approval that echoes nothing cannot be checked against what was read")
    assert "w.state" in source and "w.healthy" in source, (
        "the Fabric view must render the state the scheduler reported")
    # The console may not own a state vocabulary. `discoveryLine` used to
    # collapse four kernel discovery states into a boolean and write its own
    # prose for each half, so DISCOVERED_BY_QEVIK and NEW_TO_QEVIK — different
    # claims — were drawn identically, and the wording could drift from the
    # kernel's with nothing failing. /api/discovery/states exists so a surface
    # cannot invent a friendlier meaning than the one the kernel gives.
    assert "/api/discovery/states" in source, (
        "the console renders discovery states without asking what they mean")
    for invented in ("New to Qevik'", "new to the world'",
                     "claims_about_the_world === true"):
        assert invented not in source, (
            f"the console writes its own meaning for a discovery state "
            f"({invented!r}); it must render what /states returned")
    # Publication state is derived from the timeline by the API. A console that
    # worked it out from the presence of a URL would report a site as live
    # because a disk had it.
    assert "pill(d.publication_state" in source, (
        "the console has the four-state publication chain and does not draw it. "
        "Mentioning the field somewhere is not showing it — an earlier version "
        "of this assertion passed while the state was rendered as a literal")
    for derived in ("published.length ? 'PUBLISHED'", "? 'AUTHORISED' :"):
        assert derived not in source, (
            "the console derives publication state instead of reading it")
    # Mission Control groups missions by whose move it is. Grouping by
    # predicate means a status no predicate matches vanishes from the page, and
    # a mission an operator cannot see is worse than an ugly extra section — so
    # there is a catch-all, and it is not decoration.
    assert "const rest = all.filter" in source and "Other" in source, (
        "the grouped mission list has no catch-all; a status no group matches "
        "would disappear from the page entirely")
    # The reason a mission is in its state comes from the kernel's fold, never
    # from the latest event's note — which is how six failed missions each
    # reported that they ended because a "report written".
    assert "mission.because" in source, (
        "the console reads a reason from somewhere other than `because`")
    assert "mission.note ||" not in source, (
        "the console is back to reading `note` as the reason a mission ended")
    # Publications shows what is actually on the internet, read from the
    # timeline. The page promised that in its header and rendered only the
    # authorisation queue.
    assert "/api/missions/published" in source, (
        "the Publications page does not list what has been published")
    # Liveness is a measurement with a time on it. Held across the render that
    # displays it and dropped after, so a stale verdict is never shown as the
    # current state — that is how a dead demo keeps looking fine.
    assert "state.checkedPublications = null" in source, (
        "a liveness result is kept beyond the render that shows it")
    # A health check asserts things about a real business, over Qevik's name.
    # The reviewer approving it sees every claim and its evidence in the
    # existing artefact card — not in a new card, and not only inside the HTML
    # they would otherwise have to open and read.
    assert "provenance || {}).claims" in source, (
        "the reviewer cannot see what a health check claims about a business")
    assert "NOT_VERIFIED: 'could not check'" in source, (
        "an unfinished check is drawn as a finding in the review")
    # Inbound is read separately from opportunities and rendered in both
    # branches: one read failing says nothing about the other, and a business
    # that came to us disappearing because the opportunity memory was briefly
    # away is the strongest signal this system has, lost silently.
    assert "/api/missions/inbound" in source, (
        "the console does not show businesses that asked about themselves")
    assert source.count("${inboundBlock}") == 2, (
        "inbound is not rendered on both branches of the opportunities view")
    # An allowance has three states and the console draws three. `.catch(() =>
    # null)` collapsed "this tenant is not on a plan" into "nothing to show",
    # so the card vanished and an operator whose metered work was about to be
    # refused had no way to learn why.
    assert "'no-plan'" in source and "'unreadable'" in source, (
        "the console cannot tell a provisioning gap from a failed read")
    assert "e.status === 409" in source, (
        "the plan route raises 409 for a provisioning gap; nothing reads it")
    assert "not on a plan" in source, (
        "the provisioning gap is not named in the console")
    assert "provisioning gap, not an" in source, (
        "an operator must not read a provisioning gap as a spent balance")
    # The most important operator decision in the commercial chain, and the
    # console could not make it: `POST /api/missions/deliver` approves the
    # opportunity and creates the mission, and nothing called it.
    assert "/api/missions/deliver" in source, (
        "an operator cannot approve an opportunity from the console")
    approving = source[source.index("/api/missions/deliver"):][:200]
    assert "signal_id" in approving, "the approval must name the opportunity"
    for decided in ("recipe", "origin", "approved_scope"):
        assert decided not in approving, (
            f"the approval body carries {decided!r}; what the work is came from "
            "the opportunity's own evidence and a caller must not redecide it")
    assert "confirm(" in source[:source.index("/api/missions/deliver")][-900:], (
        "approving work about a real business must not be one unguarded click")
    # A business Qevik cannot fetch leaves the funnel without appearing as a
    # loss — the operator sees a shorter list, not a gap. Coverage is that gap,
    # and the half that is ours is drawn apart from the half that is theirs.
    assert "/api/missions/coverage" in source, (
        "the operator cannot see how much of the population Qevik can fetch")
    assert "blocked by us" in source and "their site did not answer" in source, (
        "our failure and theirs are drawn the same way")
    assert source.count("${coverageBlock}") == 2, (
        "coverage is not rendered on both branches of the discovery view")
    # One prospect, answered from the models that own each fact. The screen it
    # replaced printed `JSON.stringify(roadmap || research)` into a `<pre>`,
    # which is a structural answer to a commercial question.
    assert "/dossier" in source, (
        "an operator cannot read one prospect's file from the console")
    assert "What exactly would be sent" in source, (
        "the console does not show what a business would actually receive")
    # The gaps are the point. A dossier that filled them would be most
    # confident exactly where it knows least.
    assert "gap" in source and "not established" in source, (
        "a fact that does not exist is not drawn as missing")

    # A ceiling on drift, not a technical limit: this console is one file, and
    # without a number somebody has to justify crossing, it acquires a screen
    # at a time until nobody can read it. Raise it for a capability an operator
    # gains, as the prospect dossier did — never to fit a longer comment.
    assert Path(CONSOLE / "index.html").stat().st_size < 132_000

    # The console cannot be the thing that sends. Nothing in this codebase can
    # today, and the console is where a send button would be most natural and
    # most wrong: the outreach card shows a message that is deliberately
    # unsendable, and a control there would make an approval boundary look like
    # a queue. When sending exists it will be a mission with an agent and a
    # tool, dispatched like every other outward act — never a POST from a page.
    sends = re.findall(r"""['"][^'"]*/(?:send|deliver-message|outreach/send)[^'"]*['"]""",
                       source, re.I)
    assert sends == [], (
        f"the console posts to {sends}. Sending is a mission with a bounded "
        "agent, not a button on a page.")

    # Artefact bytes are a customer's generated markup, rendered in the page
    # that holds the operator's session. They reach the DOM as text or they do
    # not reach it at all. `verify_console_logic.mjs` proves this by recording
    # which property is written; this catches the edit that changes it.
    pane = re.search(r"data-artefact\b[\s\S]{0,800}?\.(textContent|innerHTML)\s*=",
                     source)
    assert pane is not None, "the artefact pane is never written to"
    assert pane.group(1) == "textContent", (
        "the artefact pane is written with innerHTML; that executes a "
        "customer's markup in the operator's session")

    # The real invariant: the console renders what the API returns and decides
    # nothing. A threshold here is a second answer to a question the kernel
    # already answers, and the one on screen is the untested one.
    decisions = re.findall(
        r"""(?:score|confidence|value|amount)\s*[<>]=?\s*[0-9]""", source)
    assert decisions == [], (
        f"the console compares {decisions} against a number. Ranking, "
        "confidence and worth are decided in the kernel; a threshold here is a "
        "second answer nobody tests.")

    # It must not invent the words the evidence rules exist to prevent.
    for invented in ("is new to Google", "definitely", "guaranteed"):
        assert invented.lower() not in source.lower(), invented


def test_the_console_asset_route_refuses_to_escape_its_directory(client) -> None:
    """The path comes from the URL, and serving whatever it names is an
    arbitrary-file-read with extra steps."""
    for attempt in ("/../../etc/passwd", "/etc/passwd", "/....//etc/passwd"):
        body = client.get(attempt).text
        assert "root:" not in body, attempt


# ============================================ the two applications are separate

def test_the_api_prefix_is_not_an_alias_in_the_composed_app() -> None:
    """The monolith and the control plane cannot share one application.

    `atlas_kernel/api.py` carries `accept_api_prefix`, a middleware that
    rewrites `/api/X` to `/X` so the Atlas desktop client can address the kernel
    either way. Mounting the control plane there made `/api/missions` become
    `/missions` — a console path — and answer **200 with HTML** instead of 401
    with JSON. An unauthenticated 200 where an authenticated API belongs, and
    HTML that anything not checking content type reads as success.

    The composed app must never grow that middleware: here `/api/` is a real
    namespace, not an alias.
    """
    import ast
    from pathlib import Path

    from atlas_kernel.qevik import app as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    rewrites = [n for n in ast.walk(tree)
                if isinstance(n, ast.Subscript)
                and isinstance(n.value, ast.Attribute)
                and n.value.attr == "scope"]
    assert rewrites == [], "nothing here may rewrite request.scope['path']"
    assert "accept_api_prefix" not in source


@pytest.mark.real_auth
def test_unauthenticated_api_returns_401_json_and_never_html(client) -> None:
    """The exact regression. Both halves matter: the status *and* the type."""
    for path in ("/api/missions", "/api/chat", "/api/credentials",
                 "/api/models", "/api/customer/actions", "/api/health"):
        response = client.get(path)
        assert response.status_code == 401, path
        assert response.headers["content-type"].startswith("application/json"), (
            f"{path} answered {response.headers['content-type']} — HTML here is "
            "worse than a 404, because only the 404 is obviously broken")


def test_the_spa_fallback_never_captures_an_api_path(client) -> None:
    """Not by registration order — by the handler refusing.

    Order is invisible at the call site, and one `install()` moving would
    silently reopen the shadowing.
    """
    for path in ("/api/missions", "/api/nothing-here", "/api/"):
        assert "Qevik Control" not in client.get(path).text, path


def test_an_unknown_path_is_not_the_console(client) -> None:
    body = client.get("/definitely-not-a-console-route").text
    assert "Qevik Control" not in body


def test_health_is_liveness_only_and_says_nothing_about_posture(client) -> None:
    """Public, because systemd and Caddy check it before anybody has a session.
    So it must not leak whether the vault is sealed."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"status": "ok"}
    blob = response.text.lower()
    for posture in ("vault", "sealed", "degraded", "credential", "claiming"):
        assert posture not in blob, posture


def test_authenticated_api_routes_reach_the_control_plane(client, monkeypatch
                                                          ) -> None:
    """The other half: refusing everything is not correctness either.

    A tenanted operator, because the session fixture's default has no tenant and
    the customer boundary refuses that with 403 — correctly, and it would hide
    whether the route was reached at all.
    """
    from atlas_kernel.auth import Scope, User
    from atlas_kernel.auth.models import hash_password
    from atlas_kernel.auth.store import AuthStore

    monkeypatch.setattr(AuthStore, "authenticate", lambda self, token: User(
        username="tenanted", password_hash=hash_password("test-only-password"),
        tenant_id="tenant-alpha", scopes=frozenset(Scope)))

    for path in ("/api/missions", "/api/chat", "/api/credentials",
                 "/api/models", "/api/models/selection",
                 "/api/missions/blockers", "/api/missions/costs"):
        response = client.get(path)
        assert response.status_code == 200, (path, response.text[:120])
        assert response.headers["content-type"].startswith("application/json")


def test_every_control_plane_route_is_still_mounted(client) -> None:
    """A guard against a fix for the above quietly removing a surface."""
    served = set(client.app.openapi()["paths"])
    for required in ("/api/missions", "/api/missions/{mission_id}",
                     "/api/missions/{mission_id}/report", "/api/chat",
                     "/api/chat/{conversation_id}/plan",
                     "/api/chat/{conversation_id}/decide",
                     "/api/credentials", "/api/credentials/{provider}",
                     "/api/models", "/api/models/selection",
                     "/api/customer/actions", "/auth/login",
                     "/control/sales/summary"):
        assert required in served, required


# ============================================ the schema this app depends on

def test_the_composed_app_ensures_its_own_auth_schema() -> None:
    """It did not, and production reached the state that follows from that.

    `init_auth()` carries the auth tables *and their migrations* — including the
    `tenant_id` column every customer route reads. It was called only by
    `atlas_kernel/api.py`, so this application assumed a schema it never
    created: `qevik_users` on the server had six columns and no `tenant_id`
    while the code reading it was deployed, and the failure surfaced at the
    first login rather than at start-up.

    A deployment must not depend on some *other* application having been started
    first to create its tables.
    """
    import ast
    from pathlib import Path

    from atlas_kernel.qevik import app as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "init_auth" in called, (
        "create_app must ensure the auth schema before anything uses it")


def test_a_schema_failure_refuses_rather_than_running_open(tmp_path,
                                                           monkeypatch) -> None:
    """The wrapping matters as much as the call.

    A control plane that cannot reach its schema must refuse requests. It must
    not fail to start — that breaks tooling with no database — and it must
    certainly not start without authentication.
    """
    from atlas_kernel.qevik import app as module

    def unreachable() -> None:
        raise RuntimeError("no database")

    monkeypatch.setattr(module, "init_auth", unreachable)
    app = create_app(Wiring(repository_root=tmp_path,
                            vault_path=tmp_path / "vault.json"))

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200, "liveness still answers"


@pytest.mark.real_auth
def test_attaching_a_tenant_is_an_admin_route_not_a_database_edit(client
                                                                  ) -> None:
    """Granting a tenant decides which customer's data an account reaches, so it
    belongs on the same guarded surface as granting a scope — not in a script
    that opens the database directly."""
    served = client.app.openapi()["paths"]
    assert "/auth/users/tenant" in served
    assert "post" in served["/auth/users/tenant"]
    # And it is closed by default, like everything else.
    assert client.post("/auth/users/tenant",
                       json={"username": "x", "tenant_id": "y"}
                       ).status_code == 401


# ============================================ live status

def test_status_is_tenant_scoped_and_refuses_without_one(client) -> None:
    """A change in another tenant's work must not even signal."""
    assert client.get("/api/status").status_code == 403


def _tenanted(monkeypatch, tenant: str = "tenant-alpha"):
    from atlas_kernel.auth import Scope, User
    from atlas_kernel.auth.models import hash_password
    from atlas_kernel.auth.store import AuthStore

    monkeypatch.setattr(AuthStore, "authenticate", lambda self, token: User(
        username="operator", password_hash=hash_password("test-only-password"),
        tenant_id=tenant, scopes=frozenset(Scope)))


def test_an_unchanged_version_answers_without_a_payload(client, monkeypatch
                                                        ) -> None:
    """What makes asking every few seconds cheap. A summary on every poll
    would make a live view cost more than the page it lives on."""
    _tenanted(monkeypatch)
    first = client.get("/api/status").json()
    again = client.get("/api/status", params={"since": first["version"]}).json()

    assert again["changed"] is False
    assert "counts" not in again, "an unchanged poll must not ship the summary"
    assert again["version"] == first["version"]


def test_a_new_mission_changes_the_version(client, monkeypatch) -> None:
    from atlas_kernel.mission import service as mission_service

    _tenanted(monkeypatch)
    before = client.get("/api/status").json()["version"]

    _mission, event = mission_service.create(
        tenant="tenant-alpha", title="Ship it", requested_by="operator")
    client.app.state.mission_events.append(event)

    after = client.get("/api/status", params={"since": before}).json()
    assert after["changed"] is True
    assert after["counts"]["missions"] == 1


def test_another_tenants_work_never_changes_this_tenants_version(
        client, monkeypatch) -> None:
    from atlas_kernel.mission import service as mission_service

    _tenanted(monkeypatch, "tenant-alpha")
    before = client.get("/api/status").json()["version"]

    _mission, event = mission_service.create(
        tenant="tenant-beta", title="Theirs", requested_by="them")
    client.app.state.mission_events.append(event)

    assert client.get("/api/status",
                      params={"since": before}).json()["changed"] is False


def test_the_digest_ignores_the_order_events_arrive_in(client, monkeypatch
                                                       ) -> None:
    """Two workers appending concurrently produce the same set in a different
    order, and that is not a change a viewer should see."""
    from atlas_kernel.qevik.live import snapshot

    _tenanted(monkeypatch)
    from atlas_kernel.mission import service as mission_service

    events = []
    for title in ("One", "Two", "Three"):
        _m, event = mission_service.create(tenant="tenant-alpha", title=title,
                                           requested_by="operator")
        events.append(event)

    forwards = snapshot(events, [], tenant="tenant-alpha")["version"]
    backwards = snapshot(list(reversed(events)), [], tenant="tenant-alpha")["version"]
    assert forwards == backwards


def test_needs_me_counts_both_kinds_of_waiting(client, monkeypatch) -> None:
    """A mission awaiting approval and a plan awaiting a decision are the same
    question to a person, and the home screen exists to answer it once."""
    from atlas_kernel.chat import service as chat_service
    from atlas_kernel.mission import service as mission_service
    from atlas_kernel.mission.models import MissionStatus, Plan, PlanStep

    _tenanted(monkeypatch)
    mission, event = mission_service.create(tenant="tenant-alpha", title="M",
                                            requested_by="operator")
    client.app.state.mission_events.append(event)
    client.app.state.mission_events.append(mission_service._event(
        mission.model_copy(update={"status": MissionStatus.AWAITING_APPROVAL}),
        actor="test", note="seeded"))

    conversation, opened = chat_service.start(tenant="tenant-alpha", text="hello")
    client.app.state.chat_events.append(opened)
    _updated, proposed = chat_service.plan_for(
        conversation, Plan(goal="g", steps=(PlanStep(order=1, title="s"),)),
        tenant="tenant-alpha")
    client.app.state.chat_events.append(proposed)

    counts = client.get("/api/status").json()["counts"]
    assert counts["awaiting_approval"] == 1
    assert counts["plans_proposed"] == 1
    assert counts["needs_me"] == 2


def test_the_console_polls_rather_than_streaming() -> None:
    """A decision, not a shortcut: this page is served through Cloudflare, which
    buffers streaming responses by default. An SSE channel would work locally,
    pass review, and deliver nothing in production."""
    from atlas_kernel.qevik.app import CONSOLE

    source = (CONSOLE / "index.html").read_text(encoding="utf-8")
    assert "EventSource" not in source
    assert "/api/status?since=" in source
    # And it stops when the tab is hidden — a phone in a pocket should not ask
    # every four seconds.
    assert "visibilitychange" in source


def test_the_live_view_never_makes_the_page_load_bearing() -> None:
    """Polling decides when to re-read. It must not drive a mission."""
    from atlas_kernel.qevik.app import CONSOLE

    source = (CONSOLE / "index.html").read_text(encoding="utf-8")
    live = source[source.index("const live = {"):source.index("document.addEventListener('visibilitychange'")]
    for forbidden in ("/approve", "/decide", "/plan", "method: 'POST'"):
        assert forbidden not in live, forbidden


class TestWhichAppsAreActuallyRunning:
    """`apps/desktop` is the largest tree in `apps/` and nothing runs it.

    Source-file count reads as product progress to anybody who has not checked,
    and the check is not obvious: the code is intact and its tests pass. So the
    status is written down, and these assertions stop the note going stale.
    """

    def _root(self):
        from pathlib import Path

        return Path(__file__).resolve().parents[3] / "apps"

    def _status(self):
        return (self._root() / "STATUS.md").read_text(encoding="utf-8")

    def test_every_app_has_a_row(self) -> None:
        """A new app with no row fails here. Without this the table is a README
        that was true once."""
        listed = self._status()
        for app in sorted(p.name for p in self._root().iterdir() if p.is_dir()):
            assert f"`{app}`" in listed, (
                f"apps/{app} has no row in apps/STATUS.md — it cannot be told "
                "apart from a running application")

    def test_no_parked_app_is_shipped_by_a_deploy_script(self) -> None:
        """The claim that makes 'parked' meaningful. If a deploy path started
        shipping one, the word would be wrong and nothing else would notice."""
        from pathlib import Path

        infra = Path(__file__).resolve().parents[3] / "infra"
        scripts = "\n".join(
            path.read_text(encoding="utf-8")
            for path in infra.glob("deploy_*.sh"))

        for parked in ("desktop", "web", "prototype"):
            assert f"apps/{parked}" not in scripts, (
                f"apps/{parked} is marked parked and a deploy script ships it")

    def test_the_live_console_is_not_marked_parked(self) -> None:
        """Negative control for the assertion above: it must be able to tell a
        running app from a parked one, not merely find the word absent."""
        listed = self._status()
        control = next(line for line in listed.splitlines()
                       if line.startswith("| `control`"))

        assert "**live**" in control and "parked" not in control

    def test_it_does_not_claim_a_decision_nobody_recorded(self) -> None:
        """Parked is not retired. Nothing in the repository records a decision
        to end these surfaces, and writing one down would be inventing it."""
        listed = self._status()

        assert "Parked is **not** retired" in listed
        assert "retired" not in listed.replace("Parked is **not** retired", "")
