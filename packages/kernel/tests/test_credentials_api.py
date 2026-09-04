"""The credential surface, tested from the position of somebody trying to read a key.

The single property worth most of this file: no route, in any state, through any
error path, returns a stored secret. That is not provable by testing the happy
path — a leak lives in the 409, the traceback, the validation error and the
provider's own echo of the request. So the secret here is a distinctive string,
and it is searched for in every response body the surface can produce.

The rest tests the two lies a credential UI tells most easily: showing a stored
key as working before anything tested it, and keeping the old green tick across a
rotation that replaced it.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atlas_kernel.auth import Scope, User
from atlas_kernel.auth import api as auth_api
from atlas_kernel.auth.models import hash_password
from atlas_kernel.auth.store import AuthStore
from atlas_kernel.credentials import api as credentials_api
from atlas_kernel.credentials.service import CredentialService, Status
from atlas_kernel.credentials.vault import Vault

A, B = "tenant-alpha", "tenant-beta"

#: Distinctive enough that finding it anywhere in a response is unambiguous.
SECRET = "sk-CANARY-9f3b2a1c-do-not-leak-this-value"
OTHER = "sk-CANARY-different-value-entirely-0000"


def _user(tenant: str, *scopes: Scope) -> User:
    return User(username=f"u-{tenant}",
                password_hash=hash_password("test-only-password"),
                tenant_id=tenant, scopes=frozenset(scopes or frozenset(Scope)))


@pytest.fixture
def service() -> CredentialService:
    # A real master key, so the vault is unsealed and actually encrypts.
    return CredentialService(Vault(master_key="test-only-master-key-not-real"))


@pytest.fixture
def app(service) -> FastAPI:
    application = FastAPI()
    auth_api.install(application, AuthStore())
    credentials_api.install(application)
    application.state.credentials = service
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


# ============================================ nothing gives a secret back

def test_no_route_in_any_state_returns_the_stored_secret(client, app) -> None:
    """Swept across every route, in both the configured and unconfigured state.

    A leak does not live on the happy path. It lives in the error body, the
    validation message and the provider's echo — so this looks at all of them.
    """
    def probe(_secret: str) -> tuple[Status, str]:
        # A provider that hands the key straight back in its error text, which
        # is a normal thing for a real API to do with a bad header.
        return Status.INVALID_CREDENTIAL, f"rejected token {_secret}"

    app.state.credential_probes = {"qwen": probe}

    responses = [
        client.get("/api/credentials"),
        client.get("/api/credentials/qwen"),
        client.put("/api/credentials/qwen", json={"secret": SECRET}),
        client.get("/api/credentials"),
        client.get("/api/credentials/qwen"),
        client.post("/api/credentials/qwen/test"),
        client.post("/api/credentials/qwen/rotate", json={"secret": OTHER}),
        client.post("/api/credentials/qwen/enabled", json={"enabled": False}),
        client.get("/api/credentials/qwen"),
        client.delete("/api/credentials/qwen"),
        client.post("/api/credentials/qwen/rotate", json={"secret": SECRET}),
        client.put("/api/credentials/qwen", json={"secret": ""}),
        client.get("/api/credentials/nonexistent-provider"),
    ]
    for response in responses:
        assert SECRET not in response.text, response.request.url
        assert OTHER not in response.text, response.request.url


def test_the_surface_has_no_route_that_reveals_a_credential() -> None:
    """By construction, not by having tested the routes that exist today."""
    from pathlib import Path

    source = Path(credentials_api.__file__).read_text(encoding="utf-8")
    # `resolve()` is the one method that returns a secret. It belongs to the
    # code that *uses* a credential, never to the code that serves HTTP.
    assert ".resolve(" not in source
    assert "secret=record" not in source


def test_a_fingerprint_identifies_a_key_without_reconstructing_it(client) -> None:
    """Enough to answer "is this the same key as last week", and no more."""
    first = client.put("/api/credentials/qwen", json={"secret": SECRET}).json()
    client.delete("/api/credentials/qwen")
    again = client.put("/api/credentials/qwen", json={"secret": SECRET}).json()
    different = client.put("/api/credentials/anthropic",
                           json={"secret": OTHER}).json()

    assert first["fingerprint"] == again["fingerprint"]
    assert first["fingerprint"] != different["fingerprint"]
    assert SECRET not in first["fingerprint"]
    assert len(first["fingerprint"]) <= 16


# ============================================ storing is not connecting

def test_a_stored_credential_is_pending_not_connected(client) -> None:
    """Somebody pasted a key. That is not evidence it works."""
    body = client.put("/api/credentials/qwen", json={"secret": SECRET}).json()
    assert body["status"] == Status.PENDING_CREDENTIAL.value
    assert body["status"] != Status.CONNECTED.value
    assert "not yet tested" in body["note"]


def test_testing_a_credential_is_what_makes_it_connected(client, app) -> None:
    app.state.credential_probes = {"qwen": lambda s: (Status.CONNECTED, "ok")}
    client.put("/api/credentials/qwen", json={"secret": SECRET})

    result = client.post("/api/credentials/qwen/test").json()
    assert result["works"] is True
    assert (client.get("/api/credentials/qwen").json()["status"]
            == Status.CONNECTED.value)


def test_a_provider_with_no_probe_says_so_rather_than_guessing(client, app) -> None:
    """501, not a green tick and not a red one. We have not built the check."""
    app.state.credential_probes = {}
    client.put("/api/credentials/qwen", json={"secret": SECRET})
    response = client.post("/api/credentials/qwen/test")
    assert response.status_code == 501
    assert "no probe is implemented" in response.json()["detail"]
    # And the credential is still stored, still pending.
    assert (client.get("/api/credentials/qwen").json()["status"]
            == Status.PENDING_CREDENTIAL.value)


def test_rotation_clears_the_previous_verification(client, app) -> None:
    """The old key worked. That says nothing about the new one."""
    app.state.credential_probes = {"qwen": lambda s: (Status.CONNECTED, "ok")}
    client.put("/api/credentials/qwen", json={"secret": SECRET})
    client.post("/api/credentials/qwen/test")
    assert (client.get("/api/credentials/qwen").json()["status"]
            == Status.CONNECTED.value)

    rotated = client.post("/api/credentials/qwen/rotate",
                          json={"secret": OTHER}).json()
    assert rotated["status"] == Status.PENDING_CREDENTIAL.value, (
        "a rotated credential must not inherit the old key's green tick")


def test_rotating_into_an_empty_slot_is_refused(client) -> None:
    """A button labelled Rotate that performs a first write is a lie."""
    response = client.post("/api/credentials/qwen/rotate", json={"secret": SECRET})
    assert response.status_code == 409
    assert "nothing is stored" in response.json()["detail"]


def test_disabling_keeps_the_key_so_it_can_be_turned_back_on(client) -> None:
    client.put("/api/credentials/qwen", json={"secret": SECRET})
    off = client.post("/api/credentials/qwen/enabled", json={"enabled": False}).json()
    assert off["status"] == Status.DISABLED.value
    assert off["configured"] is True, "the key is still there"

    on = client.post("/api/credentials/qwen/enabled", json={"enabled": True}).json()
    assert on["status"] == Status.PENDING_CREDENTIAL.value


# ============================================ who may do what

def test_writing_a_credential_needs_admin(client) -> None:
    """A credential is authority to act as the customer somewhere else."""
    client.acting_as(_user(A, Scope.READ, Scope.EXECUTE))
    assert client.put("/api/credentials/qwen",
                      json={"secret": SECRET}).status_code == 403
    assert client.delete("/api/credentials/qwen").status_code == 403
    assert client.post("/api/credentials/qwen/rotate",
                       json={"secret": SECRET}).status_code == 403


def test_testing_a_credential_needs_only_execute(client, app) -> None:
    """Diagnosing must not require the scope that can replace the key."""
    app.state.credential_probes = {"qwen": lambda s: (Status.CONNECTED, "ok")}
    client.put("/api/credentials/qwen", json={"secret": SECRET})

    client.acting_as(_user(A, Scope.READ, Scope.EXECUTE))
    assert client.post("/api/credentials/qwen/test").status_code == 200


def test_one_tenant_never_sees_or_touches_anothers_credential(client, service
                                                              ) -> None:
    client.put("/api/credentials/qwen", json={"secret": SECRET})

    client.acting_as(_user(B))
    body = client.get("/api/credentials/qwen").json()
    assert body["status"] == Status.NOT_CONFIGURED.value
    assert body.get("fingerprint", "") == ""

    # And B deleting `qwen` must not remove A's.
    client.delete("/api/credentials/qwen")
    assert service.record(provider="qwen", tenant=A) is not None


def test_an_account_with_no_tenant_reaches_none_of_it(client) -> None:
    """A tenantless account reaches nothing — unless it is the operator.

    `_user("")` grants every scope by default, ADMIN included, so this asserted
    a 403 for the one account that must not get one: the administrator running
    the console has no customer tenant, and refusing them here refused them on
    every tenant-scoped page at once. They are scoped to the house tenant
    instead. A tenantless account without ADMIN is still refused, which is the
    isolation this test was written for.
    """
    client.acting_as(_user("", Scope.READ))
    assert client.get("/api/credentials").status_code == 403

    client.acting_as(_user(""))  # every scope, ADMIN included
    assert client.get("/api/credentials").status_code == 200


def test_an_unknown_provider_is_absent(client) -> None:
    assert client.get("/api/credentials/not-a-provider").status_code == 404
    assert client.put("/api/credentials/not-a-provider",
                      json={"secret": SECRET}).status_code == 404


# ============================================ sealed rather than degraded

def test_a_sealed_vault_refuses_to_store_rather_than_falling_back(app, monkeypatch
                                                                 ) -> None:
    """No master key means no storage. Never plaintext-as-a-fallback."""
    app.state.credentials = CredentialService(Vault(master_key=""))
    monkeypatch.setattr(AuthStore, "authenticate", lambda self, token: _user(A))
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer test"
        response = client.put("/api/credentials/qwen", json={"secret": SECRET})
        assert response.status_code == 503
        assert SECRET not in response.text
        assert client.get("/api/credentials").json()["vault"]["sealed"] is True


def test_a_deployment_with_no_vault_says_so(app, monkeypatch) -> None:
    app.state.credentials = None
    monkeypatch.setattr(AuthStore, "authenticate", lambda self, token: _user(A))
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer test"
        assert client.get("/api/credentials").status_code == 503


# ============================================ forgetting says nothing

def test_forgetting_does_not_reveal_whether_anything_was_there(client) -> None:
    """A delete that answers differently is a way to ask which providers a
    tenant uses."""
    absent = client.delete("/api/credentials/qwen")
    client.put("/api/credentials/qwen", json={"secret": SECRET})
    present = client.delete("/api/credentials/qwen")

    assert absent.status_code == present.status_code == 200
    assert absent.json() == present.json()


def test_a_forgotten_credential_is_actually_gone(client, service) -> None:
    client.put("/api/credentials/qwen", json={"secret": SECRET})
    client.delete("/api/credentials/qwen")
    assert service.record(provider="qwen", tenant=A) is None
    assert client.get("/api/credentials/qwen").json()["configured"] is False
