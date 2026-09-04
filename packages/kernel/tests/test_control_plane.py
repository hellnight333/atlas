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

def test_every_buildable_unconnected_integration_becomes_an_action(store) -> None:
    """Every integration with an adapter — and only those.

    A provider whose adapter is not built produces no action: "we have not
    built this" is our move, not the customer's, and asking them for a key
    nothing could use is how a credential sits unused in a store for a year.
    """
    actions = credential_actions(store, tenant=A)
    buildable = {i.id for i in INTEGRATIONS if i.adapter_ready}
    unbuilt = {i.id for i in INTEGRATIONS if not i.adapter_ready}

    assert {a.service for a in actions} == buildable
    assert unbuilt, "the fixture must include an unbuilt provider to test this"
    assert not ({a.service for a in actions} & unbuilt)

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

def _as(tenant: str, *, scopes=frozenset(Scope)) -> User:
    return User(username=f"u-{tenant}", password_hash=hash_password("test-only-password"),
                tenant_id=tenant, scopes=scopes)


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
    """`_as("")` grants every scope, ADMIN included — so this asserted a 403 for
    the one account that must not get one. An administrator with no customer
    tenant acts for the house; anybody else with no tenant is still refused."""
    from atlas_kernel.auth import Scope

    client.acting_as(_as("", scopes=frozenset({Scope.READ})))
    assert client.get("/api/customer/actions").status_code == 403
    assert client.get("/api/customer/integrations").status_code == 403

    client.acting_as(_as(""))  # the operator
    assert client.get("/api/customer/actions").status_code == 200


# ============================================ the plan surface

@pytest.fixture
def paid_client(client):
    """A client whose tenant is on a plan."""
    from atlas_kernel.credits import CreditService, Plan

    service = CreditService()
    service.assign(A, Plan.ADVANCED)
    client.app.state.credits = service
    return client


def test_a_customer_can_see_their_plan_and_what_is_left(paid_client) -> None:
    body = paid_client.get("/api/customer/plan").json()
    assert body["plan"] == "ADVANCED"
    assert body["included_units"] == 600.0
    # 600 included, 60 held back for essential work, so ordinary work sees 540.
    # Both numbers are shown: quoting only the larger one would let a customer
    # plan against units ordinary work cannot reach.
    assert body["remaining"] == 540.0
    assert body["reserved_for_essential"] == 60.0
    assert body["remaining_including_reserve"] == 600.0
    assert body["used"] == 0.0


def test_the_plan_surface_shows_units_and_never_money(paid_client) -> None:
    body = paid_client.get("/api/customer/plan").json()
    # The field names and values, not the note — the note is prose *about* not
    # pricing anything, and matching on it tests the wrong thing.
    fields = {k: v for k, v in body.items() if k != "note"}
    blob = repr(fields).lower()
    for money in ("price", "usd", "aed", "currency", "$", "invoice", "charged"):
        assert money not in blob, money
    assert "units, not money" in body["note"].lower()


def test_spending_shows_up_on_the_plan(paid_client) -> None:
    service = paid_client.app.state.credits
    reservation = service.reserve(tenant=A, action="offer-website")
    held = paid_client.get("/api/customer/plan").json()
    assert held["held"] == 30.0 and held["used"] == 0.0

    service.settle(reservation.id, tenant=A)
    settled = paid_client.get("/api/customer/plan").json()
    assert settled["used"] == 30.0 and settled["held"] == 0.0
    assert settled["remaining"] == 510.0, "540 ordinary, less the 30 just spent"


def test_a_tenant_with_no_plan_is_told_it_is_a_provisioning_gap(paid_client) -> None:
    paid_client.acting_as(_as(B))
    response = paid_client.get("/api/customer/plan")
    assert response.status_code == 409
    assert "provisioning gap" in response.json()["detail"]


def test_one_tenant_never_sees_anothers_usage(paid_client) -> None:
    from atlas_kernel.credits import Plan

    service = paid_client.app.state.credits
    service.assign(B, Plan.LIST)
    reservation = service.reserve(tenant=A, action="offer-website")
    service.settle(reservation.id, tenant=A)

    paid_client.acting_as(_as(B))
    body = paid_client.get("/api/customer/plan").json()
    assert body["plan"] == "LIST"
    assert body["used"] == 0.0, "A's spending must not appear on B's plan"
    assert body["history"] == []


class TestMachinesThatHaveNotJoined:
    """The HP Z8 and the Lenovo are in the documented topology and have never
    registered. The only remaining step is somebody standing in front of them,
    which is what a provisioning action is for."""

    def _names(self, actions):
        return {a.service for a in actions}

    def test_a_machine_that_has_not_joined_is_asked_for(self) -> None:
        from atlas_kernel.controlplane.actions import EXPECTED_NODES, node_actions

        found = node_actions((), tenant="t")

        assert self._names(found) == {n["name"] for n in EXPECTED_NODES}

    def test_a_machine_that_joined_stops_being_asked_for(self) -> None:
        """Worker ids are `machine:worker-name`, so the match is on the machine."""
        from atlas_kernel.controlplane.actions import node_actions

        found = node_actions(("atlas-z8:worker-research", "qevik-core-01:worker-1"),
                             tenant="t")

        assert "atlas-z8" not in self._names(found)
        assert "atlas-lenovo" in self._names(found)

    def test_an_unreadable_fleet_asks_for_nothing(self) -> None:
        """`None` is "could not be read", not "nothing has joined". Telling
        somebody to go and provision a machine that is already running because a
        query failed is precisely the wrong instruction."""
        from atlas_kernel.controlplane.actions import node_actions

        assert node_actions(None, tenant="t") == ()

    def test_they_do_not_claim_to_be_blocking(self) -> None:
        """No agent declares a GPU tool, so nothing is waiting on these machines.
        Two permanent emergencies at the top of the list would destroy the one
        property that makes the list worth reading."""
        from atlas_kernel.controlplane.actions import node_actions

        assert all(not a.blocking for a in node_actions((), tenant="t"))

    def test_each_one_says_how_it_will_be_known_to_be_done(self) -> None:
        from atlas_kernel.controlplane.actions import node_actions

        for action in node_actions((), tenant="t"):
            assert "Fabric" in action.verification
            assert "heartbeat" in action.verification
            assert "physical access to the machine" in action.requires

    def test_the_instructions_name_the_step_only_a_person_can_take(self) -> None:
        """Tailscale opens a browser URL for approval. That is the whole reason
        this cannot be automated, and the instructions say so."""
        from atlas_kernel.controlplane.actions import node_actions

        for action in node_actions((), tenant="t"):
            assert "tailscale up" in action.instructions
            assert action.service in action.instructions

    def test_no_action_promises_gpu_work(self) -> None:
        """Nothing dispatches to a GPU. An action implying otherwise would be
        inventing a factory to justify hardware."""
        from atlas_kernel.controlplane.actions import node_actions

        for action in node_actions((), tenant="t"):
            assert action.affects == ()
            assert "GPU work" not in action.instructions


class TestWhatStopsTheDomainSending:
    """The `smtp` credential and the DNS records are different blockers with
    different fixes. Satisfying one does nothing for the other, and a channel
    reporting itself configured while the domain proves nothing sends mail
    straight to spam."""

    class _Measured:
        def __init__(self, *, missing=(), unreadable=False, domain="qevik.ai"):
            from atlas_kernel.outreach.deliverability import Record, State

            self.domain, self.unreadable, self.missing = domain, unreadable, missing
            self.records = tuple(
                Record(name=name, matters_because="a real consequence, at length",
                       state=State.ABSENT) for name in missing)

    def test_a_domain_missing_records_produces_a_blocking_action(self) -> None:
        from atlas_kernel.controlplane.actions import sending_identity_actions

        found = sending_identity_actions(
            self._Measured(missing=("MX", "SPF")), tenant="t")

        assert len(found) == 1
        assert found[0].blocking is True
        assert found[0].affects == ("outreach:send",)
        assert "a DNS MX record on qevik.ai" in found[0].requires

    def test_an_unreadable_resolver_produces_no_action(self) -> None:
        """Telling somebody to create records that already exist is how a
        working zone gets broken by a well-meant edit."""
        from atlas_kernel.controlplane.actions import sending_identity_actions

        assert sending_identity_actions(
            self._Measured(missing=("MX",), unreadable=True), tenant="t") == ()
        assert sending_identity_actions(None, tenant="t") == ()

    def test_a_healthy_domain_produces_no_action(self) -> None:
        from atlas_kernel.controlplane.actions import sending_identity_actions

        assert sending_identity_actions(self._Measured(), tenant="t") == ()

    def test_it_says_how_the_entry_closes_itself(self) -> None:
        from atlas_kernel.controlplane.actions import sending_identity_actions

        action = sending_identity_actions(
            self._Measured(missing=("DMARC",)), tenant="t")[0]

        assert "disappears by" in action.verification
        assert "dig finds DMARC" in action.verification

    def test_it_is_a_separate_action_from_the_smtp_credential(self) -> None:
        """Same service would mean one satisfying the other."""
        from atlas_kernel.controlplane.actions import sending_identity_actions

        action = sending_identity_actions(
            self._Measured(missing=("MX",)), tenant="t")[0]

        assert action.service == "dns:qevik.ai"
        assert "SMTP" not in action.requires[0]

    def test_it_names_no_credential_value(self) -> None:
        from atlas_kernel.controlplane.actions import sending_identity_actions

        rendered = repr(sending_identity_actions(
            self._Measured(missing=("MX", "SPF", "DMARC")), tenant="t"))

        assert "QEVIK_SMTP_PASSWORD" not in rendered
        assert "sk-" not in rendered
