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
    cannot test, and one number would hide which half is missing."""
    app = create_app(Wiring(repository_root=tmp_path,
                            vault_path=tmp_path / "vault.json"))
    components = health(app)["components"]
    assert "probes" in components and "credentials" in components
    assert components["probes"]["configured"] is False


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
