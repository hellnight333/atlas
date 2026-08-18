"""The endpoints the console runs on.

The property most worth defending here is that a **decision is attributed to the
authenticated session**, never to a field the client sent. An audit trail that
records what the caller claimed is not an audit trail.
"""

from __future__ import annotations

import tempfile
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atlas_kernel.actions.approval_gate import (
    ApprovalGate,
    ApprovalStore,
    init_approvals,
)
from atlas_kernel.auth import Scope, User
from atlas_kernel.auth.models import hash_password
from atlas_kernel.control import build_router
from atlas_kernel.jobs import JobRunner

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", autouse=True)
def _schema():
    init_approvals()


def _client(user: User) -> TestClient:
    """An app whose requests arrive already authenticated as `user`.

    The middleware is not installed here: these tests are about the routes'
    own scope checks, and auth/api.py has its own tests for the middleware.
    """
    app = FastAPI()
    app.include_router(build_router(JobRunner(tempfile.mkdtemp())))

    @app.middleware("http")
    async def _as_user(request, call_next):
        request.state.user = user
        return await call_next(request)

    return TestClient(app)


def _user(*scopes: Scope) -> User:
    return User(
        username="tester",
        password_hash=hash_password("a-long-test-password"),
        scopes=frozenset(scopes),
    )


def _pending(job: str, **payload) -> str:
    return (
        ApprovalGate()
        .check(
            job_id=job,
            step_id="deploy",
            action="site.deploy",
            payload=payload or {"slug": "clinic"},
        )
        .approval_id
    )


class TestScopes:
    def test_reading_the_queue_needs_read(self) -> None:
        assert _client(_user(Scope.READ)).get("/control/approvals").status_code == 200

    def test_submitting_an_objective_needs_execute(self) -> None:
        response = _client(_user(Scope.READ)).post(
            "/control/objectives", json={"objective": "build me something small"}
        )
        assert response.status_code == 403
        assert "execute scope" in response.json()["detail"]

    def test_asking_to_publish_needs_the_publish_scope(self) -> None:
        """Refused before any work happens, rather than after a site is built."""
        response = _client(_user(Scope.READ, Scope.EXECUTE)).post(
            "/control/objectives",
            json={"objective": "build and publish something", "authorise_publish": True},
        )
        assert response.status_code == 403
        assert "publish" in response.json()["detail"]

    def test_deciding_needs_the_scope_the_proposal_names(self) -> None:
        """Not a scope the caller picks: allowing a publish needs PUBLISH,
        allowing a payment would need FINANCIAL."""
        job = f"job_{uuid.uuid4().hex[:8]}"
        approval_id = _pending(job)
        response = _client(_user(Scope.READ, Scope.EXECUTE)).post(
            f"/control/approvals/{approval_id}", json={"approve": True}
        )
        assert response.status_code == 403
        assert ApprovalStore().get(approval_id)["status"] == "pending", "it decided anyway"


class TestTheDecisionIsTheSession:
    def test_the_decider_is_the_authenticated_user(self) -> None:
        job = f"job_{uuid.uuid4().hex[:8]}"
        approval_id = _pending(job)
        client = _client(_user(Scope.READ, Scope.PUBLISH))
        client.post(f"/control/approvals/{approval_id}", json={"approve": True, "reason": "ok"})
        assert ApprovalStore().get(approval_id)["decided_by"] == "tester"

    def test_a_client_supplied_identity_is_ignored(self) -> None:
        """There is no field for it, and sending one changes nothing."""
        job = f"job_{uuid.uuid4().hex[:8]}"
        approval_id = _pending(job)
        client = _client(_user(Scope.READ, Scope.PUBLISH))
        client.post(
            f"/control/approvals/{approval_id}",
            json={"approve": True, "decided_by": "somebody-else", "user_id": "admin"},
        )
        assert ApprovalStore().get(approval_id)["decided_by"] == "tester"


class TestDecisions:
    def test_a_rejection_is_recorded_with_its_reason(self) -> None:
        job = f"job_{uuid.uuid4().hex[:8]}"
        approval_id = _pending(job)
        client = _client(_user(Scope.READ, Scope.PUBLISH))
        body = client.post(
            f"/control/approvals/{approval_id}",
            json={"approve": False, "reason": "the copy is wrong"},
        ).json()
        assert body["status"] == "rejected"
        assert body["decision_reason"] == "the copy is wrong"
        assert not body["resumed_job"], "a rejected job must not be resumed"

    def test_deciding_twice_is_a_conflict_not_a_silent_overwrite(self) -> None:
        job = f"job_{uuid.uuid4().hex[:8]}"
        approval_id = _pending(job)
        client = _client(_user(Scope.READ, Scope.PUBLISH))
        client.post(f"/control/approvals/{approval_id}", json={"approve": True})
        again = client.post(f"/control/approvals/{approval_id}", json={"approve": False})
        assert again.status_code == 409
        assert ApprovalStore().get(approval_id)["status"] == "approved"

    def test_an_unknown_approval_is_a_404(self) -> None:
        response = _client(_user(Scope.READ, Scope.PUBLISH)).post(
            "/control/approvals/apr_nope", json={"approve": True}
        )
        assert response.status_code == 404


class TestTheQueueShowsEnoughToDecide:
    def test_the_reviewer_sees_the_target_and_the_exact_operation(self) -> None:
        job = f"job_{uuid.uuid4().hex[:8]}"
        _pending(job, slug="clinic", url="http://host/clinic/", promote=True)
        queue = _client(_user(Scope.READ)).get("/control/approvals").json()
        entry = next(a for a in queue if a["job_id"] == job)

        assert entry["target"] == "http://host/clinic/"
        assert entry["proposed"]["slug"] == "clinic"
        assert entry["what"], "a summary in plain words"
        assert entry["risk"] == "public"
        assert entry["required_scope"] == "publish"
        assert entry["fingerprint"], "bound to this exact act"

    def test_nothing_material_is_hidden_behind_a_generic_label(self) -> None:
        job = f"job_{uuid.uuid4().hex[:8]}"
        _pending(job, slug="clinic", promote=True)
        entry = next(
            a
            for a in _client(_user(Scope.READ)).get("/control/approvals").json()
            if a["job_id"] == job
        )
        for field in ("what", "target", "proposed", "risk", "required_scope", "expires_at"):
            assert field in entry, field


class TestHealthAndCapabilities:
    def test_health_reports_the_machine(self) -> None:
        body = _client(_user(Scope.READ)).get("/control/health").json()
        assert "healthy" in body and "memory_total_mb" in body

    def test_capabilities_are_observed_not_declared(self) -> None:
        body = _client(_user(Scope.READ)).get("/control/capabilities").json()
        assert "site.deploy" in body["actions"]
        assert "planner" in body
