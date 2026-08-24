"""Choosing which model does which job.

Two properties carry this file.

**A model that cannot run is listed, with the reason.** A screen showing only
the usable models cannot answer "why isn't Claude here", and that is the exact
question that brings somebody to it. Returning the blocked ones with the
credential they need turns a dead end into one click.

**A selection naming an unavailable model is reported, never silently
replaced.** Substituting the next available model would run somebody's
implementation work on a model they did not pick — and the invocation record
would name the substitute as though it had been chosen, which makes the cost
attribution wrong as well as the work.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atlas_kernel.auth import Scope, User
from atlas_kernel.auth import api as auth_api
from atlas_kernel.auth.models import hash_password
from atlas_kernel.auth.store import AuthStore
from atlas_kernel.credentials.models import Role
from atlas_kernel.credentials.service import CredentialService
from atlas_kernel.credentials.vault import Vault
from atlas_kernel.modelchoice import api as models_api
from atlas_kernel.modelchoice.store import SelectionStore, available, chosen
from atlas_kernel.opportunity.tenancy import TenantRequired

A, B = "tenant-alpha", "tenant-beta"
SECRET = "sk-CANARY-modelchoice-do-not-leak"


def _user(tenant: str, *scopes: Scope) -> User:
    return User(username=f"u-{tenant}",
                password_hash=hash_password("test-only-password"),
                tenant_id=tenant, scopes=frozenset(scopes or frozenset(Scope)))


@pytest.fixture
def credentials() -> CredentialService:
    return CredentialService(Vault(master_key="test-only-master-key-not-real"))


@pytest.fixture
def app(credentials):
    application = FastAPI()
    auth_api.install(application, AuthStore())
    models_api.install(application)
    application.state.credentials = credentials
    application.state.model_selections = SelectionStore()
    return application


@pytest.fixture
def client(app, monkeypatch):
    holder = {"user": _user(A)}
    monkeypatch.setattr(AuthStore, "authenticate", lambda self, token: holder["user"])

    class Acting(TestClient):
        def acting_as(self, user: User):
            holder["user"] = user
            return self

    with Acting(app) as test_client:
        test_client.headers["Authorization"] = "Bearer test"
        yield test_client


# ============================================ blocked models are shown

def test_a_model_with_no_credential_is_listed_with_the_reason(credentials) -> None:
    """Not omitted. "Why isn't Claude here" is the question this screen exists
    to answer."""
    rows = available(credentials, tenant=A)
    assert rows, "the catalogue must not be empty"

    blocked = [r for r in rows if not r["usable"]]
    assert blocked
    for row in blocked:
        assert row["blocked_by"], row["model"]
        assert row["credential"], "it must name the credential it needs"


def test_a_usable_model_says_nothing_about_being_blocked(credentials) -> None:
    credentials.store(provider="qwen", tenant=A, secret=SECRET)
    rows = {r["model"]: r for r in available(credentials, tenant=A)}
    qwen = [r for r in rows.values() if r["provider"] == "qwen"]
    assert qwen and all(r["usable"] for r in qwen)
    assert all(r["blocked_by"] == "" for r in qwen)


def test_a_stored_but_untested_credential_still_makes_its_models_usable(
        credentials) -> None:
    """PENDING_CREDENTIAL is not a refusal. Refusing to plan until somebody
    tests a key would mean nothing works on a fresh install."""
    credentials.store(provider="qwen", tenant=A, secret=SECRET)
    record = credentials.record(provider="qwen", tenant=A)
    assert record is not None and record.status.value == "PENDING_CREDENTIAL"
    assert any(r["usable"] for r in available(credentials, tenant=A))


def test_a_disabled_provider_blocks_its_models(credentials) -> None:
    credentials.store(provider="qwen", tenant=A, secret=SECRET)
    credentials.set_enabled(provider="qwen", tenant=A, enabled=False)
    qwen = [r for r in available(credentials, tenant=A) if r["provider"] == "qwen"]
    assert all(not r["usable"] for r in qwen)
    assert all("switched off" in r["blocked_by"] for r in qwen)


def test_the_catalogue_never_carries_a_secret(credentials) -> None:
    credentials.store(provider="qwen", tenant=A, secret=SECRET)
    assert SECRET not in repr(available(credentials, tenant=A))


# ============================================ an unavailable choice is reported

def test_choosing_a_model_whose_credential_is_missing_is_allowed_and_flagged(
        client) -> None:
    """Refusing would make it impossible to configure Qevik before entering
    keys, which is the order most people work in."""
    body = client.put("/api/models/selection/implementation",
                      json={"model": "claude-opus-5"}).json()
    assert body["selection"]["implementation"] == "claude-opus-5"
    assert body["resolved"]["available"] is False
    assert "Credential Centre" in body["note"]


def test_an_unavailable_selection_is_never_silently_replaced(credentials) -> None:
    """Running the work on a model nobody picked, and recording the substitute
    as chosen, is worse than refusing."""
    from atlas_kernel.credentials.models import Selection

    credentials.store(provider="qwen", tenant=A, secret=SECRET)
    selection = Selection(by_role={Role.IMPLEMENTATION.value: "claude-opus-5"})
    choices = {c.role: c for c in chosen(credentials, selection, tenant=A)}

    implementation = choices[Role.IMPLEMENTATION.value]
    assert implementation.available is False
    assert implementation.model == "", "no substitute may appear here"
    assert "not available" in implementation.reason


def test_a_role_with_no_choice_defaults_and_says_it_defaulted(credentials) -> None:
    """A fallback presented as a decision is the thing this distinguishes."""
    from atlas_kernel.credentials.models import Selection

    credentials.store(provider="qwen", tenant=A, secret=SECRET)
    choices = {c.role: c for c in chosen(credentials, Selection(), tenant=A)}
    planning = choices[Role.PLANNING.value]
    assert planning.available is True
    assert "defaulted" in planning.reason


def test_a_chosen_model_reports_that_it_was_selected(credentials) -> None:
    from atlas_kernel.credentials.models import Selection

    credentials.store(provider="qwen", tenant=A, secret=SECRET)
    selection = Selection(by_role={Role.PLANNING.value: "qwen-max"})
    planning = {c.role: c for c in chosen(credentials, selection, tenant=A)}[
        Role.PLANNING.value]
    assert planning.model == "qwen-max"
    assert planning.reason == "selected"


def test_the_selection_route_names_which_roles_cannot_run(client) -> None:
    client.put("/api/models/selection/review", json={"model": "claude-opus-5"})
    body = client.get("/api/models/selection").json()
    assert "review" in body["unavailable"]
    assert "never silently reassigned" in body["note"]


# ============================================ one registry, not two

def test_the_selection_survives_a_credential_being_rotated(client, credentials
                                                           ) -> None:
    """A choice is not a secret and must not share a lifetime with one."""
    credentials.store(provider="qwen", tenant=A, secret=SECRET)
    client.put("/api/models/selection/planning", json={"model": "qwen-max"})

    credentials.rotate(provider="qwen", tenant=A, secret="sk-CANARY-rotated-value")
    assert client.get("/api/models/selection").json()["selection"] == {
        "planning": "qwen-max"}


def test_the_selection_survives_a_credential_being_forgotten(client, credentials
                                                             ) -> None:
    credentials.store(provider="qwen", tenant=A, secret=SECRET)
    client.put("/api/models/selection/planning", json={"model": "qwen-max"})
    credentials.forget(provider="qwen", tenant=A)

    body = client.get("/api/models/selection").json()
    assert body["selection"] == {"planning": "qwen-max"}, "the choice is kept"
    assert "planning" in body["unavailable"], "and reported as unrunnable"


def test_no_second_registry_is_defined_here() -> None:
    """`credentials/models.py` decides what can run. Two systems that both
    believe they decide is how an invocation gets recorded against a model that
    never saw the request."""
    from pathlib import Path

    from atlas_kernel.modelchoice import store

    source = Path(store.__file__).read_text(encoding="utf-8")
    assert "registry_for" in source, "it must use the existing one"
    assert "class ModelRegistry" not in source
    assert "Registration(" not in source


# ============================================ refusals

def test_an_unknown_model_is_refused_rather_than_stored(client) -> None:
    """Storing it would fail at the first invocation, far from here."""
    response = client.put("/api/models/selection/planning",
                          json={"model": "gpt-9-imaginary"})
    assert response.status_code == 422
    assert "not a model Qevik knows" in response.json()["detail"]


def test_an_unknown_role_is_absent(client) -> None:
    response = client.put("/api/models/selection/telepathy", json={"model": ""})
    assert response.status_code == 404
    assert "planning" in response.json()["detail"], "it lists the real roles"


def test_choosing_needs_admin_because_it_is_a_spending_decision(client) -> None:
    client.acting_as(_user(A, Scope.READ, Scope.EXECUTE))
    assert client.get("/api/models").status_code == 200
    assert client.put("/api/models/selection/planning",
                      json={"model": "qwen-max"}).status_code == 403


def test_clearing_returns_every_role_to_the_registrys_preference(client) -> None:
    client.put("/api/models/selection/planning", json={"model": "qwen-max"})
    assert client.delete("/api/models/selection").json()["selection"] == {}


def test_an_empty_model_clears_one_role(client) -> None:
    client.put("/api/models/selection/planning", json={"model": "qwen-max"})
    body = client.put("/api/models/selection/planning", json={"model": ""}).json()
    assert "planning" not in body["selection"]


# ============================================ tenancy

def test_one_tenants_selection_is_not_anothers(client) -> None:
    client.put("/api/models/selection/planning", json={"model": "qwen-max"})
    client.acting_as(_user(B))
    assert client.get("/api/models/selection").json()["selection"] == {}


def test_every_entry_point_requires_a_tenant(credentials) -> None:
    from atlas_kernel.credentials.models import Selection

    store = SelectionStore()
    for call in (lambda: available(credentials, tenant=None),
                 lambda: chosen(credentials, Selection(), tenant=None),
                 lambda: store.get(tenant=None),
                 lambda: store.set_role(tenant=None, role=Role.PLANNING,
                                        model="qwen-max"),
                 lambda: store.clear(tenant=None)):
        with pytest.raises(TenantRequired):
            call()


def test_an_account_with_no_tenant_reaches_nothing(client) -> None:
    client.acting_as(_user(""))
    assert client.get("/api/models").status_code == 403
    assert client.get("/api/models/selection").status_code == 403
