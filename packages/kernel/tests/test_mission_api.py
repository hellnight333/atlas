"""Mission control, tested on the ways a control plane stops being trustworthy.

Three failures matter more than the rest.

A control plane that *runs* the work makes the browser tab load-bearing, so
closing it kills a deployment halfway. A control plane that reports a cost total
built only from the calls that happened to report one presents a floor as a fact.
And a control plane that answers 403 for another tenant's mission and 404 for a
missing one has told the caller which mission ids exist.

Each of those is tested directly rather than through a happy path that would
pass in all three broken versions.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atlas_kernel.auth import Scope, User
from atlas_kernel.auth import api as auth_api
from atlas_kernel.auth.models import hash_password
from atlas_kernel.auth.store import AuthStore
from atlas_kernel.mission import api as mission_api
from atlas_kernel.mission import service
from atlas_kernel.mission.api import blockers, costs
from atlas_kernel.mission.models import (
    AgentInvocation,
    Blocker,
    Mission,
    MissionStatus,
    Plan,
    PlanStep,
)

A, B = "tenant-alpha", "tenant-beta"


def _user(tenant: str, *scopes: Scope) -> User:
    return User(username=f"u-{tenant}",
                password_hash=hash_password("test-only-password"),
                tenant_id=tenant,
                scopes=frozenset(scopes or frozenset(Scope)))


@pytest.fixture
def app(tmp_path):
    application = FastAPI()
    auth_api.install(application, AuthStore())
    mission_api.install(application)
    application.state.mission_events = []
    application.state.mission_sink = application.state.mission_events.append
    application.state.repository_root = str(tmp_path)
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


def _seed(app, *, tenant: str = A, status: MissionStatus | None = None,
          **fields) -> Mission:
    """Put one mission on the timeline, at whatever status the test needs."""
    mission, event = service.create(tenant=tenant, title=fields.pop("title", "Work"),
                                    description=fields.pop("description", ""),
                                    requested_by="ayoub")
    app.state.mission_sink(event)
    if status and status is not MissionStatus.DRAFT:
        mission = mission.model_copy(update={"status": status, **fields})
        app.state.mission_sink(
            service._event(mission, actor="test", note="seeded"))
    elif fields:
        mission = mission.model_copy(update=fields)
        app.state.mission_sink(
            service._event(mission, actor="test", note="seeded"))
    return mission


# ============================================ the browser is never load-bearing

def test_the_http_surface_cannot_run_a_mission() -> None:
    """Every write appends an event and returns.

    If a route could call the worker, closing the tab or restarting the API to
    deploy would kill a mission mid-commit. This reads the module rather than
    trusting the docstring, because the docstring is exactly what stays true
    while the code stops being.
    """
    source = Path(mission_api.__file__).read_text(encoding="utf-8")
    for forbidden in ("Worker(", ".run(", "subprocess", "GitWorkspace",
                      "os.system", "Popen"):
        assert forbidden not in source, forbidden


def test_approving_only_queues_and_does_not_execute(client, app) -> None:
    mission = _seed(app, status=MissionStatus.AWAITING_APPROVAL,
                    plan=Plan(goal="g", steps=(PlanStep(order=1, title="s"),)))
    before = len(app.state.mission_events)

    response = client.post(f"/api/missions/{mission.id}/approve", json={})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "queued"

    # Exactly one new event, and nothing claimed it.
    assert len(app.state.mission_events) == before + 1
    assert response.json()["claimed_by"] == ""


def test_a_write_with_nowhere_to_persist_refuses_rather_than_pretending(app, client
                                                                       ) -> None:
    """A 200 that persisted nothing is how an approval disappears."""
    app.state.mission_sink = None
    response = client.post("/api/missions", json={"title": "Something"})
    assert response.status_code == 503
    assert "lost" in response.json()["detail"]


def test_a_submission_lands_in_draft_not_queued(client, app) -> None:
    """Or holding EXECUTE would be enough to start unreviewed work."""
    response = client.post("/api/missions", json={"title": "Rebuild the site"})
    assert response.status_code == 201
    assert response.json()["status"] == "draft"


def test_an_illegal_transition_is_refused_by_the_same_table_the_worker_obeys(
        client, app) -> None:
    """Not by a second rule written into the handler."""
    mission = _seed(app, status=MissionStatus.COMPLETE)
    response = client.post(f"/api/missions/{mission.id}/approve", json={})
    assert response.status_code == 409
    assert "cannot become queued" in response.json()["detail"]


def test_a_claimed_mission_cannot_be_cancelled_from_the_ui(client, app) -> None:
    """The button that appears to kill a process and does not.

    A worker holding this mission is writing to a worktree and about to commit.
    Recording it as cancelled would show the operator a cancelled mission that
    goes on producing commits, so the refusal is the honest answer and it names
    the worker rather than returning a generic state error.
    """
    mission = _seed(app, status=MissionStatus.PROCESSING, claimed_by="worker-1")
    response = client.post(f"/api/missions/{mission.id}/cancel", json={})
    assert response.status_code == 409
    assert "worker-1" in response.json()["detail"]
    assert "still writing" in response.json()["detail"]


def test_an_unclaimed_mission_cancels_cleanly(client, app) -> None:
    mission = _seed(app, status=MissionStatus.QUEUED)
    body = client.post(f"/api/missions/{mission.id}/cancel", json={}).json()
    assert body["status"] == "cancelled"


# ============================================ a cost total is a floor, and says so

def test_unpriced_calls_are_counted_not_treated_as_free() -> None:
    """A missing cost is not a zero cost."""
    summary = costs([{"invocations": [
        {"cost": 0.5, "cost_status": "REPORTED", "currency": "USD"},
        {"cost": None, "cost_status": "UNKNOWN"},
        {"cost": None, "cost_status": "UNKNOWN"},
    ]}])
    assert summary["known_total"] == 0.5
    assert summary["unpriced_calls"] == 2
    assert summary["complete"] is False
    assert "floor" in summary["note"]


def test_reported_and_estimated_costs_are_never_merged() -> None:
    """One was told to us, the other we computed. Adding them loses which."""
    summary = costs([{"invocations": [
        {"cost": 1.0, "cost_status": "REPORTED", "currency": "USD"},
        {"cost": 2.0, "cost_status": "ESTIMATED", "currency": "USD"},
    ]}])
    assert summary["reported"] == 1.0
    assert summary["estimated"] == 2.0
    assert summary["known_total"] == 3.0
    assert summary["complete"] is True


def test_mixed_currencies_are_flagged_rather_than_summed_behind_one_figure() -> None:
    summary = costs([{"invocations": [
        {"cost": 1.0, "cost_status": "REPORTED", "currency": "USD"},
        {"cost": 1.0, "cost_status": "REPORTED", "currency": "AED"},
    ]}])
    assert summary["mixed_currencies"] is True
    assert summary["currency"] == ""


def test_no_invocations_at_all_is_not_reported_as_complete() -> None:
    """Nothing ran, so "every call reported a cost" would be a true sentence
    that reads as "we know what this cost"."""
    summary = costs([{"invocations": []}])
    assert summary["complete"] is False
    assert summary["known_total"] == 0.0


def test_the_cost_route_survives_a_real_invocation(client, app) -> None:
    mission = _seed(app, status=MissionStatus.COMPLETE, invocations=(
        AgentInvocation(provider="qwen", model="qwen-max", cost=0.25,
                        cost_status="REPORTED", currency="USD"),
        AgentInvocation(provider="qwen", model="qwen-max"),))
    body = client.get("/api/missions/costs").json()
    assert body["known_total"] == 0.25
    assert body["unpriced_calls"] == 1
    assert mission.id


# ============================================ absent, not forbidden

def test_another_tenants_mission_is_absent_not_forbidden(client, app) -> None:
    """403-versus-404 tells a caller which ids exist."""
    mine = _seed(app, tenant=A)
    theirs = _seed(app, tenant=B)

    missing = client.get("/api/missions/mission-000000000000")
    other = client.get(f"/api/missions/{theirs.id}")
    assert other.status_code == missing.status_code == 404
    assert other.json() == missing.json(), "the bodies must be identical too"
    assert client.get(f"/api/missions/{mine.id}").status_code == 200


def test_history_establishes_the_mission_before_reading_it(client, app) -> None:
    """An empty history for "not yours" is the same leak, quieter."""
    theirs = _seed(app, tenant=B)
    assert client.get(f"/api/missions/{theirs.id}/history").status_code == 404


def test_a_report_belonging_to_another_tenant_is_absent(client, app) -> None:
    theirs = _seed(app, tenant=B, report_path="docs/x.md")
    assert client.get(f"/api/missions/{theirs.id}/report").status_code == 404


def test_one_tenant_never_sees_anothers_missions(client, app) -> None:
    _seed(app, tenant=A, title="Mine")
    _seed(app, tenant=B, title="Theirs")
    body = client.get("/api/missions").json()
    assert [m["title"] for m in body["missions"]] == ["Mine"]
    assert all(m["tenant_id"] == A for m in body["missions"])


def test_an_account_with_no_tenant_reaches_none_of_it(client) -> None:
    client.acting_as(_user(""))
    for path in ("/api/missions", "/api/missions/costs", "/api/missions/blockers"):
        assert client.get(path).status_code == 403, path


def test_reading_requires_read_and_writing_requires_execute(client, app) -> None:
    mission = _seed(app, status=MissionStatus.AWAITING_APPROVAL)
    client.acting_as(_user(A, Scope.READ))
    assert client.get("/api/missions").status_code == 200
    assert client.post(f"/api/missions/{mission.id}/approve",
                       json={}).status_code == 403


# ============================================ the report is not a file read

def test_a_report_path_that_escapes_the_reports_directory_is_refused(client, app,
                                                                    tmp_path) -> None:
    """`report_path` arrives on an event, and an event is data."""
    secret = tmp_path / "secret.txt"
    secret.write_text("private", encoding="utf-8")
    mission = _seed(app, status=MissionStatus.COMPLETE,
                    report_path="docs/qevik-docs/autonomous/reports/../../../secret.txt")

    response = client.get(f"/api/missions/{mission.id}/report")
    assert response.status_code == 404
    assert "private" not in response.text


def test_a_real_report_is_served(client, app, tmp_path) -> None:
    reports = tmp_path / "docs/qevik-docs/autonomous/reports"
    reports.mkdir(parents=True)
    (reports / "r.md").write_text("# Report\n", encoding="utf-8")
    mission = _seed(app, status=MissionStatus.COMPLETE,
                    report_path="docs/qevik-docs/autonomous/reports/r.md")

    body = client.get(f"/api/missions/{mission.id}/report").json()
    assert body["report"] == "# Report\n"


def test_a_mission_with_no_report_says_so_rather_than_404_ing_as_absent(client, app
                                                                       ) -> None:
    mission = _seed(app, status=MissionStatus.COMPLETE)
    response = client.get(f"/api/missions/{mission.id}/report")
    assert response.status_code == 404
    assert "has not produced a report" in response.json()["detail"]


# ============================================ blockers are classified, not listed

def test_blockers_group_by_kind_rather_than_reading_as_one_stuck_list() -> None:
    """A credential blocker is five minutes; an architecture one is a decision."""
    summary = blockers([
        {"mission_id": "m1", "title": "A", "status": "blocked",
         "blockers": [{"kind": "PENDING_CREDENTIAL", "detail": "no key"}]},
        {"mission_id": "m2", "title": "B", "status": "blocked",
         "blockers": [{"kind": "PENDING_ARCHITECTURE", "detail": "undecided"}]},
    ])
    assert set(summary["by_kind"]) == {"PENDING_CREDENTIAL", "PENDING_ARCHITECTURE"}
    assert summary["total"] == 2
    assert len(summary["blocked_missions"]) == 2


def test_a_blocker_names_the_mission_it_is_stopping() -> None:
    summary = blockers([{"mission_id": "m1", "title": "Ship it", "status": "blocked",
                         "blockers": [{"kind": "PENDING_HOST", "detail": "no host"}]}])
    entry = summary["by_kind"]["PENDING_HOST"][0]
    assert entry["mission_id"] == "m1" and entry["title"] == "Ship it"


def test_the_blockers_route_reads_this_tenants_missions_only(client, app) -> None:
    _seed(app, tenant=B, status=MissionStatus.BLOCKED,
          blockers=(Blocker(kind="PENDING_CREDENTIAL", detail="theirs"),))
    body = client.get("/api/missions/blockers").json()
    assert body["total"] == 0


# ============================================ routing cannot be ambiguous

def test_a_collection_route_can_never_be_read_as_a_mission_id(client, app) -> None:
    """`/costs` resolving as a mission id would be a 404 that looks like a bug
    in the fold rather than a routing collision."""
    for path in ("costs", "blockers", "actions"):
        assert client.get(f"/api/missions/{path}").status_code == 200, path
    assert not mission_api.MISSION_ID.match("costs")
    assert mission_api.MISSION_ID.match("mission-0123456789ab")


def test_an_unknown_status_filter_is_refused_rather_than_returning_nothing(client
                                                                          ) -> None:
    """Silently returning zero rows reads as "no missions", not "bad filter"."""
    response = client.get("/api/missions", params={"status": "nonsense"})
    assert response.status_code == 400
    assert "unknown status" in response.json()["detail"]


def test_the_status_filter_works(client, app) -> None:
    _seed(app, status=MissionStatus.BLOCKED, title="Stuck")
    _seed(app, status=MissionStatus.COMPLETE, title="Done")
    body = client.get("/api/missions", params={"status": "blocked"}).json()
    assert [m["title"] for m in body["missions"]] == ["Stuck"]
    assert body["counts"]["blocked"] == 1


# ============================================ the fold must round-trip

def test_a_folded_mission_rehydrates_losslessly() -> None:
    """Approving means acting on what the read model returned. If the round trip
    dropped the plan, the operator would approve a plan the mission no longer
    carries."""
    mission, _ = service.create(tenant=A, title="x", description="d",
                                requested_by="ayoub")
    mission, _ = service.transition(mission, MissionStatus.PLANNING, tenant=A)
    mission, _ = service.attach_plan(
        mission, Plan(goal="g", steps=(PlanStep(order=1, title="s"),)), tenant=A)

    assert service.rehydrate(mission.summary(), tenant=A) == mission


def test_rehydrating_another_tenants_summary_is_refused() -> None:
    mission, _ = service.create(tenant=B, title="x", requested_by="ayoub")
    with pytest.raises(service.NotPermitted):
        service.rehydrate(mission.summary(), tenant=A)
