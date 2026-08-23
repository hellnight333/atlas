"""The action centre, tested on the ways a blocker list stops being useful.

An action list fails in two directions. It fails when a satisfied action keeps
appearing, because then nobody trusts it. And it fails when everything is marked
blocking, because then nothing is. Both are tested here, along with the rule
that matters most: an action names what is needed and never carries a value.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atlas_kernel.approval.models import ApprovalRequest, ApprovalState
from atlas_kernel.auth import Scope, User
from atlas_kernel.auth import api as auth_api
from atlas_kernel.auth.models import hash_password
from atlas_kernel.auth.store import AuthStore
from atlas_kernel.controlplane import (
    ActionKind,
    HumanAction,
    approval_actions,
    centre,
    credential_actions,
    customer_task_actions,
)
from atlas_kernel.customer import api as customer_api
from atlas_kernel.integrations import INTEGRATIONS
from atlas_kernel.publication import Connection, ConnectionStore

A, B = "tenant-alpha", "tenant-beta"


@pytest.fixture
def store() -> ConnectionStore:
    return ConnectionStore()


# ============================================ derived, not stored

def test_every_unconnected_integration_becomes_an_action(store) -> None:
    actions = credential_actions(store, tenant=A)
    assert {a.service for a in actions} == {i.id for i in INTEGRATIONS}
    for action in actions:
        assert action.kind is ActionKind.CREDENTIAL
        assert action.instructions and action.verification
        assert action.requires, "an action must name what it asks for"


def test_connecting_a_provider_removes_its_action(store) -> None:
    """A satisfied action stops being produced. An action list that keeps
    showing done work is one nobody trusts."""
    before = {a.service for a in credential_actions(store, tenant=A)}
    assert "local" in before

    store.register(Connection(id="c1", tenant_id=A, target="local",
                              reference="/srv/sites"))
    after = {a.service for a in credential_actions(store, tenant=A)}
    assert "local" not in after
    assert after == before - {"local"}


def test_an_action_keeps_its_identity_across_derivations(store) -> None:
    """Or a UI cannot tell "the same action, still open" from "a new action"."""
    first = {a.id for a in credential_actions(store, tenant=A)}
    second = {a.id for a in credential_actions(store, tenant=A)}
    assert first == second


def test_actions_are_tenant_scoped(store) -> None:
    store.register(Connection(id="c1", tenant_id=A, target="local",
                              reference="/srv/sites"))
    for_a = {a.service for a in credential_actions(store, tenant=A)}
    for_b = {a.service for a in credential_actions(store, tenant=B)}
    assert "local" not in for_a
    assert "local" in for_b, "B has connected nothing, so B is still asked"
    assert all(a.tenant_id == B for a in credential_actions(store, tenant=B))


def test_an_action_centre_needs_a_tenant(store) -> None:
    from atlas_kernel.opportunity.tenancy import TenantRequired

    with pytest.raises(TenantRequired):
        credential_actions(store, tenant=None)
    with pytest.raises(TenantRequired):
        centre(store=store, tenant=None)


# ============================================ not everything is an emergency

def test_blocking_is_reserved_for_work_that_is_actually_stopped(store) -> None:
    """If everything is blocking, nothing is."""
    tasks = ({"task_id": "t1", "title": "Send the logo", "do": "Upload it",
              "why": "", "unblocks": []},
             {"task_id": "t2", "title": "Approve the site", "do": "Review it",
              "why": "", "unblocks": ["Website"]})
    actions = customer_task_actions(tasks, tenant=A)
    by_title = {a.title: a for a in actions}
    assert by_title["Approve the site"].blocking is True
    assert by_title["Send the logo"].blocking is False


def test_the_centre_puts_blocking_work_first(store) -> None:
    tasks = ({"task_id": "t1", "title": "Optional thing", "do": "x", "unblocks": []},)
    listed = centre(store=store, tenant=A, outstanding_tasks=tasks)
    blocking = [a["blocking"] for a in listed["open"]]
    assert blocking == sorted(blocking, reverse=True), "blocking first"
    assert listed["counts"]["blocking"] < listed["counts"]["total"]


def test_an_ignored_action_becomes_stale(store) -> None:
    old = HumanAction(id="a", kind=ActionKind.CREDENTIAL, title="t", service="s",
                      created_at=datetime.now(UTC) - timedelta(days=30))
    fresh = HumanAction(id="b", kind=ActionKind.CREDENTIAL, title="t", service="s")
    assert old.stale and not fresh.stale


# ============================================ approvals are read, never made

def test_a_pending_approval_becomes_an_action(store) -> None:
    request = ApprovalRequest(title="Publish to harbour", action="qevik.publish",
                              state=ApprovalState.PENDING,
                              metadata={"tenant_id": A})
    actions = approval_actions([request], tenant=A)
    assert len(actions) == 1 and actions[0].kind is ActionKind.APPROVAL
    assert actions[0].blocking is True


def test_a_decided_approval_produces_no_action(store) -> None:
    for state in (ApprovalState.APPROVED, ApprovalState.REJECTED,
                  ApprovalState.CANCELLED, ApprovalState.EXPIRED):
        request = ApprovalRequest(title="x", state=state, metadata={"tenant_id": A})
        assert approval_actions([request], tenant=A) == ()


def test_another_tenants_approval_is_not_shown(store) -> None:
    request = ApprovalRequest(title="x", state=ApprovalState.PENDING,
                              metadata={"tenant_id": B})
    assert approval_actions([request], tenant=A) == ()


def test_the_control_plane_cannot_approve_anything() -> None:
    """A control plane that could satisfy its own approvals has no control in it."""
    from pathlib import Path

    from atlas_kernel.controlplane import actions as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    for forbidden in (".approve(", ".reject(", "ApprovalState.APPROVED)"):
        assert forbidden not in source, forbidden


# ============================================ no action carries a value

def test_no_action_contains_a_credential(store, monkeypatch) -> None:
    monkeypatch.setenv("QEVIK_AI_VISIBILITY_TOKEN", "a-real-looking-secret")
    listed = centre(store=store, tenant=A)
    blob = repr(listed["open"])
    assert "a-real-looking-secret" not in blob
    # It names the variable, which is the point — that is safe and actionable.
    assert "QEVIK_AI_VISIBILITY_TOKEN" in blob


# ============================================ through the API

def _as(tenant: str) -> User:
    return User(username=f"u-{tenant}", password_hash=hash_password("test-only-password"),
                tenant_id=tenant, scopes=frozenset(Scope))


@pytest.fixture
def client(monkeypatch, store):
    app = FastAPI()
    auth_api.install(app, AuthStore())
    customer_api.install(app)
    app.state.connections = store
    holder = {"user": _as(A)}
    monkeypatch.setattr(AuthStore, "authenticate", lambda self, token: holder["user"])

    class Acting(TestClient):
        def acting_as(self, user: User):
            holder["user"] = user
            return self

    with Acting(app) as test_client:
        test_client.headers["Authorization"] = "Bearer test"
        yield test_client


def test_the_actions_route_returns_this_tenants_work(client, store) -> None:
    response = client.get("/api/customer/actions")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["counts"]["total"] >= 1
    assert all(a["tenant_id"] == A for a in body["open"])


def test_the_integrations_route_shows_status_without_secrets(client, store) -> None:
    store.register(Connection(id="c1", tenant_id=A, target="local",
                              reference="/srv/sites"))
    body = client.get("/api/customer/integrations").json()
    assert [e["provider"] for e in body["connected"]] == ["local"]
    assert body["pending_credential"]
    for entry in body["connected"]:
        assert entry["connection_id"] == "c1"


def test_one_tenant_never_sees_anothers_actions(client, store) -> None:
    store.register(Connection(id="c1", tenant_id=A, target="local",
                              reference="/srv/sites"))
    client.acting_as(_as(B))
    body = client.get("/api/customer/actions").json()
    assert all(a["tenant_id"] == B for a in body["open"])
    # B has connected nothing, so B is still asked for `local`.
    assert any(a["service"] == "local" for a in body["open"])


def test_an_account_with_no_tenant_sees_no_actions(client) -> None:
    client.acting_as(_as(""))
    assert client.get("/api/customer/actions").status_code == 403
    assert client.get("/api/customer/integrations").status_code == 403
