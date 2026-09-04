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


def Plan_with_cost(units: float) -> Plan:  # noqa: N802 - reads as a constructor
    """A plan whose only interesting property is what it says it will cost."""
    return Plan(goal="do the thing", estimated_cost=units,
                cost_status="ESTIMATED")


def _user(tenant: str, *scopes: Scope) -> User:
    return User(username=f"u-{tenant}",
                password_hash=hash_password("test-only-password"),
                tenant_id=tenant,
                scopes=frozenset(scopes or frozenset(Scope)))


from atlas_kernel.fabric.scheduler import NodeSnapshot


@pytest.fixture
def app(tmp_path):
    application = FastAPI()
    auth_api.install(application, AuthStore())
    mission_api.install(application)
    application.state.mission_events = []
    application.state.mission_sink = application.state.mission_events.append
    application.state.repository_root = str(tmp_path)
    # Which workers this application can see. Stated, because the schedule view
    # now answers "to whom" with the same nodes dispatch uses, and an
    # application that said nothing would read whatever rows happen to be in the
    # developer's database. `self-check` is what `_seed` routes to.
    application.state.worker_nodes = lambda: (
        NodeSnapshot(worker_name="worker-test", serves="self-check",
                     capabilities=frozenset({"filesystem", "shell"}),
                     placements=frozenset({"either"}),
                     node_id="test:worker-test"),
    )
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
    """Put one mission on the timeline, at whatever status the test needs.

    It records `self-check` because this shortcut skips `attach_plan`, which is
    where a real mission gets its agent -- and a mission with none is blocked
    before any of the rules these tests are about. `self-check` needs no
    credentials, so routing it does not trade one block for another. A test that
    means unrouted passes `agent_id=""`.
    """
    fields.setdefault("agent_id", "self-check")
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
    """A tenantless account reaches nothing — unless it is the operator.

    `_user("")` grants every scope by default, ADMIN included, so this asserted
    a 403 for the one account that must not get one: the administrator running
    the console has no customer tenant, and refusing them here refused them on
    every tenant-scoped page at once. They are scoped to the house tenant
    instead. A tenantless account without ADMIN is still refused, which is the
    isolation this test was written for.
    """
    paths = ("/api/missions", "/api/missions/costs", "/api/missions/blockers")

    client.acting_as(_user("", Scope.READ))
    for path in paths:
        assert client.get(path).status_code == 403, path

    client.acting_as(_user(""))  # every scope, ADMIN included
    for path in paths:
        assert client.get(path).status_code == 200, path


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


# ============================================ the schedule view

def test_the_schedule_view_never_starts_anything(client, app) -> None:
    """A view, not a command. If refreshing the page could dispatch, a stale
    tab would start work twice and the atomic claim would stop being the single
    place two workers race."""
    _seed(app, status=MissionStatus.QUEUED)
    before = list(app.state.mission_events)
    body = client.get("/api/missions/schedule").json()
    assert body["counts"]["NOW"] == 1
    assert app.state.mission_events == before, (
        "reading the schedule appended an event; it is no longer a view")


def test_the_schedule_separates_what_is_stuck_from_what_is_progressing(
        client, app) -> None:
    _seed(app, status=MissionStatus.AWAITING_APPROVAL, title="needs a person")
    _seed(app, status=MissionStatus.BLOCKED, title="dead",
          blockers=(Blocker(kind="PENDING_INFRASTRUCTURE", detail="no GPU"),))
    body = client.get("/api/missions/schedule").json()
    assert body["counts"]["WAITING"] == 1
    assert body["counts"]["BLOCKED"] == 1
    assert "no GPU" in body["queues"]["BLOCKED"][0]["why"]


def test_the_schedule_shows_only_this_tenants_work(client, app) -> None:
    _seed(app, tenant=A, status=MissionStatus.QUEUED)
    theirs = _seed(app, tenant=B, status=MissionStatus.QUEUED)
    body = client.get("/api/missions/schedule").json()
    assert theirs.id not in client.get("/api/missions/schedule").text
    assert body["counts"]["NOW"] == 1


def test_concurrency_decides_how_much_is_dispatchable(client, app) -> None:
    for _ in range(3):
        _seed(app, status=MissionStatus.QUEUED)
    one = client.get("/api/missions/schedule").json()
    three = client.get("/api/missions/schedule?concurrency=3").json()
    assert len(one["dispatchable"]) == 1
    assert len(three["dispatchable"]) == 3


def test_an_absurd_concurrency_is_clamped_rather_than_obeyed(client, app) -> None:
    """A query string is a request, not an instruction. `concurrency=100000`
    would name every mission dispatchable at once."""
    for _ in range(3):
        _seed(app, status=MissionStatus.QUEUED)
    body = client.get("/api/missions/schedule?concurrency=100000").json()
    assert len(body["dispatchable"]) == 3
    assert client.get("/api/missions/schedule?concurrency=0").json()["counts"]["NOW"] == 1


def test_a_vault_that_cannot_be_read_yields_no_usable_credentials(app) -> None:
    """Not knowing which keys work is not the same as knowing they all do.

    The optimistic reading dispatches work that fails at the provider, after
    the operator was told it was running.
    """
    from atlas_kernel.mission.api import usable_credentials

    class Sealed:
        def status(self, **_: object) -> str:
            raise RuntimeError("vault is sealed")

    app.state.credentials = Sealed()

    class Req:
        pass
    request = Req()
    request.app = app  # type: ignore[attr-defined]
    assert usable_credentials(request, A) == frozenset()


def test_a_credential_stored_but_never_verified_is_not_treated_as_working(
        app) -> None:
    """`resolve()` refuses it, so scheduling as though it works would queue a
    mission that fails at the provider."""
    from atlas_kernel.credentials.service import CredentialService
    from atlas_kernel.credentials.vault import MemorySecretStore, Vault
    from atlas_kernel.mission.api import usable_credentials

    vault = Vault(MemorySecretStore(), master_key="test-only-master-key")
    credentials = CredentialService(vault)
    credentials.store(provider="smtp", tenant=A, secret="test-only-value")
    app.state.credentials = credentials

    class Req:
        pass
    request = Req()
    request.app = app  # type: ignore[attr-defined]
    assert "smtp" not in usable_credentials(request, A)


# ============================================ deferral

def test_deferring_holds_a_mission_without_cancelling_it(client, app) -> None:
    """It is still work somebody wants done. Moving it to BLOCKED would put it
    in the queue for things that are never going to happen."""
    mission = _seed(app, status=MissionStatus.QUEUED)
    body = client.post(f"/api/missions/{mission.id}/defer",
                       json={"until": "2099-01-01T01:00:00Z",
                             "reason": "expensive and not urgent"}).json()
    assert body["status"] == MissionStatus.QUEUED.value
    assert body["not_before"].startswith("2099-01-01T01:00")

    schedule = client.get("/api/missions/schedule").json()
    assert schedule["counts"]["SCHEDULED"] == 1
    assert schedule["counts"]["NOW"] == 0


def test_a_deferral_needs_a_reason(client, app) -> None:
    mission = _seed(app, status=MissionStatus.QUEUED)
    response = client.post(f"/api/missions/{mission.id}/defer",
                           json={"until": "2099-01-01T01:00:00Z", "reason": ""})
    assert response.status_code == 422


def test_a_deferral_into_the_past_is_refused(client, app) -> None:
    """"Deferred until yesterday" reads as a decision while behaving as none."""
    mission = _seed(app, status=MissionStatus.QUEUED)
    response = client.post(f"/api/missions/{mission.id}/defer",
                           json={"until": "2001-01-01T01:00:00Z",
                                 "reason": "night window"})
    assert response.status_code == 409
    assert "future" in response.json()["detail"]


def test_another_tenants_mission_cannot_be_deferred_and_is_absent(client, app
                                                                  ) -> None:
    """404, not 403 — a refusal would confirm the mission exists."""
    theirs = _seed(app, tenant=B, status=MissionStatus.QUEUED)
    response = client.post(f"/api/missions/{theirs.id}/defer",
                           json={"until": "2099-01-01T01:00:00Z",
                                 "reason": "night window"})
    assert response.status_code == 404
    assert response.json()["detail"] == mission_api.NOT_FOUND


def test_deferring_requires_execute_rather_than_read(client, app) -> None:
    """Holding work back changes when it runs, which is an execution decision."""
    mission = _seed(app, status=MissionStatus.QUEUED)
    client.acting_as(_user(A, Scope.READ))
    response = client.post(f"/api/missions/{mission.id}/defer",
                           json={"until": "2099-01-01T01:00:00Z",
                                 "reason": "night window"})
    assert response.status_code == 403


# ============================================ the budget reaches the schedule

def test_a_tenant_out_of_credit_has_its_work_blocked_before_it_starts(app,
                                                                      client
                                                                      ) -> None:
    """A mission stopped halfway has spent the money and produced nothing."""
    from atlas_kernel.credits.models import Plan
    from atlas_kernel.credits.service import CreditService

    credits = CreditService()
    credits.assign(A, Plan.LIST)
    app.state.credits = credits
    _seed(app, status=MissionStatus.QUEUED,
          plan=Plan_with_cost(credits.balance(A) * 10))

    body = client.get("/api/missions/schedule").json()
    assert body["counts"]["BLOCKED"] == 1
    assert "stopping halfway" in body["queues"]["BLOCKED"][0]["why"]


def test_the_same_mission_runs_when_the_tenant_can_afford_it(app, client
                                                             ) -> None:
    """The negative control. Without it the test above passes against a
    scheduler that blocks everything."""
    from atlas_kernel.credits.models import Plan
    from atlas_kernel.credits.service import CreditService

    credits = CreditService()
    credits.assign(A, Plan.LIST)
    app.state.credits = credits
    _seed(app, status=MissionStatus.QUEUED, plan=Plan_with_cost(1.0))

    assert client.get("/api/missions/schedule").json()["counts"]["NOW"] == 1


def test_units_already_reserved_are_not_offered_to_the_scheduler(app) -> None:
    """Scheduling against the raw remaining would dispatch work whose money is
    already promised to a mission still running."""
    from atlas_kernel.credits.models import Plan
    from atlas_kernel.credits.service import CreditService
    from atlas_kernel.mission.api import tenant_balance

    credits = CreditService()
    credits.assign(A, Plan.LIST)
    app.state.credits = credits

    class Req:
        pass
    request = Req()
    request.app = app  # type: ignore[attr-defined]
    before = tenant_balance(request, A)
    credits.reserve(tenant=A, action="offer-website")
    after = tenant_balance(request, A)
    assert after is not None and before is not None
    assert after < before


def test_a_tenant_with_no_plan_is_unmetered_rather_than_broke(app) -> None:
    """A self-hosted deployment where billing was never set up must still run
    missions. Refusing to *spend* against an allowance nobody set is a separate
    decision, made in `budgets.reserve()`."""
    from atlas_kernel.credits.service import CreditService
    from atlas_kernel.mission.api import tenant_balance

    app.state.credits = CreditService()

    class Req:
        pass
    request = Req()
    request.app = app  # type: ignore[attr-defined]
    assert tenant_balance(request, A) is None


class TestTheFabricSurface:
    """Which machines can run work, read from the scheduler's own snapshot.

    The console must not be able to show a fleet the dispatcher disagrees with,
    so this reads `mission.nodes.snapshots` rather than querying workers itself.
    """

    def _node(self, name, **over):
        from atlas_kernel.fabric.scheduler import NodeSnapshot

        base = dict(worker_name=name, serves="researcher",
                    capabilities=frozenset({"dns", "http-fetch"}),
                    placements=frozenset({"either"}), node_id=f"host:{name}")
        base.update(over)
        return NodeSnapshot(**base)

    def test_it_reports_the_fleet_and_what_each_worker_can_do(
            self, client, app, monkeypatch) -> None:
        from atlas_kernel.mission import nodes

        monkeypatch.setattr(nodes, "snapshots",
                            lambda: (self._node("worker-research"),))
        body = client.get("/api/missions/workers").json()

        assert body["known"] is True
        assert body["counts"] == {"total": 1, "ready": 1, "busy": 0, "stale": 0}
        assert body["workers"][0]["capabilities"] == ["dns", "http-fetch"]
        assert body["capabilities"] == ["dns", "http-fetch"]

    def test_stale_and_busy_are_not_the_same_state(
            self, client, app, monkeypatch) -> None:
        """An operator who cannot tell them apart restarts a machine that was
        halfway through a delivery."""
        from atlas_kernel.mission import nodes

        monkeypatch.setattr(nodes, "snapshots", lambda: (
            self._node("gone", fresh=False),
            self._node("working", free=False, load=1),
        ))
        body = client.get("/api/missions/workers").json()
        states = {w["name"]: w["state"] for w in body["workers"]}

        assert "stale" in states["gone"]
        assert "keeps any mission it holds" in states["gone"]
        assert states["working"] == "busy"
        assert body["counts"] == {"total": 2, "ready": 0, "busy": 1, "stale": 1}

    def test_an_unreadable_cluster_is_not_an_empty_fleet(
            self, client, app, monkeypatch) -> None:
        """Showing an empty list when the database is unreachable tells an
        operator their cluster died."""
        from atlas_kernel.mission import nodes

        monkeypatch.setattr(nodes, "snapshots", lambda: None)
        body = client.get("/api/missions/workers").json()

        assert body["known"] is False
        assert body["workers"] == []
        assert "not the same as there being no workers" in body["detail"]

    def test_it_reads_the_schedulers_snapshot_rather_than_its_own_query(self) -> None:
        """Structural: a second way of asking "which workers exist" is a second
        answer, and they diverge on the day it matters."""
        import inspect

        from atlas_kernel.mission import api

        source = inspect.getsource(api.build_router)
        start = source.index("def worker_fleet")
        end = source.index("def ", start + 10)
        route = source[start:end]

        assert "from .nodes import snapshots" in route
        for forbidden in ("WorkerRegistry", "list_workers", "atlas_workers"):
            assert forbidden not in route, f"the route queries {forbidden} itself"


class TestTheActionCentreRouteSurfacesEverything:
    """Testing the producers directly proved nothing about the endpoint.

    An earlier version of this wiring was lost before it was committed, and the
    production check called `node_actions()` itself — so it verified the
    function and not the route that was supposed to serve it. These go through
    the API.
    """

    def test_the_route_asks_for_machines_that_have_not_joined(
            self, client, app, monkeypatch) -> None:
        from atlas_kernel.mission import nodes

        monkeypatch.setattr(nodes, "snapshots", lambda: ())
        body = client.get("/api/missions/actions").json()

        services = {a["service"] for a in body["open"]}
        assert "atlas-z8" in services and "atlas-lenovo" in services
        assert body["counts"]["provisioning"] >= 2

    def test_a_machine_in_the_fleet_is_not_asked_for_by_the_route(
            self, client, app, monkeypatch) -> None:
        from atlas_kernel.fabric.scheduler import NodeSnapshot
        from atlas_kernel.mission import nodes

        monkeypatch.setattr(nodes, "snapshots", lambda: (
            NodeSnapshot(worker_name="w", serves="researcher",
                         capabilities=frozenset(), placements=frozenset({"either"}),
                         node_id="atlas-z8:w"),))
        body = client.get("/api/missions/actions").json()

        services = {a["service"] for a in body["open"]}
        assert "atlas-z8" not in services
        assert "atlas-lenovo" in services, (
            "negative control: the other machine must still be asked for")

    def test_the_route_reports_what_the_sending_domain_is_missing(
            self, client, app, monkeypatch) -> None:
        from atlas_kernel.outreach import deliverability

        monkeypatch.setattr(deliverability, "_dig", lambda *a, **k: ())
        body = client.get("/api/missions/actions").json()

        dns = [a for a in body["open"] if a["service"].startswith("dns:")]
        assert len(dns) == 1
        assert dns[0]["blocking"] is True
        assert "outreach:send" in dns[0]["affects"]

    def test_an_unreadable_resolver_asks_for_no_dns_record(
            self, client, app, monkeypatch) -> None:
        """The negative control for the test above, and the one that matters:
        silence must not become a demand to edit a working zone."""
        from atlas_kernel.outreach import deliverability

        monkeypatch.setattr(deliverability, "_dig", lambda *a, **k: None)
        body = client.get("/api/missions/actions").json()

        assert [a for a in body["open"] if a["service"].startswith("dns:")] == []

    def test_a_failing_measurement_does_not_take_down_the_page(
            self, client, app, monkeypatch) -> None:
        """This runs inside the read. An exception here would remove the screen
        that tells the operator what to do."""
        from atlas_kernel.outreach import deliverability

        def explode(*_a, **_k):
            raise RuntimeError("resolver on fire")

        monkeypatch.setattr(deliverability, "measure", explode)
        response = client.get("/api/missions/actions")

        assert response.status_code == 200
        assert "open" in response.json()

    def test_no_action_carries_a_secret(self, client, app) -> None:
        body = client.get("/api/missions/actions").text

        assert "sk-" not in body
        assert "QEVIK_VAULT_MASTER_KEY=" not in body


class TestWhatIsOnTheInternet:
    """`sites.qevik.ai` serves 57 directories and the Publications page showed
    none of them — it promised "what has actually gone live" and rendered the
    queue of things waiting for authorisation."""

    def _memory(self, app, rows):
        """The repository is created lazily on first use, so a test that reads
        `app.state.opportunity_repository` before any route has run finds
        nothing. Stated here instead."""
        from types import SimpleNamespace

        app.state.opportunity_repository = SimpleNamespace(
            published_sites=lambda **_: rows)

    def _rows(self):
        return [
            {"kind": "publication_completed",
             "detail": {"url": "https://sites.qevik.ai/site-a/", "site_id": "site-a",
                        "at": "2026-08-27", "mission_id": "m-1"}},
            {"kind": "website_demo_published",
             "detail": {"demo_url": "https://sites.qevik.ai/demo-b/", "slug": "demo-b",
                        "published_at": "2026-08-19"}},
        ]

    def test_it_lists_both_kinds_without_touching_the_network(
            self, client, app, monkeypatch) -> None:
        """The default must be instant. Asking 57 URLs on a page load makes an
        operator wait on the network to find out what exists."""
        self._memory(app, self._rows())

        def refuse(*_a, **_k):
            raise AssertionError("the default listing fetched over the network")

        from atlas_kernel.research import net
        monkeypatch.setattr(net, "Fetcher", refuse)

        body = client.get("/api/missions/published").json()

        assert body["counts"] == {"total": 2, "demos": 1, "live": 0, "down": 0,
                                  "unchecked": 2}
        assert body["checked"] is False

    def test_an_unchecked_row_does_not_read_as_working(
            self, client, app, monkeypatch) -> None:
        self._memory(app, self._rows())

        body = client.get("/api/missions/published").json()

        assert {r["liveness"] for r in body["published"]} == {"NOT_CHECKED"}

    def test_checking_reports_live_and_down_apart_from_unreachable(
            self, client, app, monkeypatch) -> None:
        from types import SimpleNamespace

        from atlas_kernel.research import net

        self._memory(app, self._rows())

        answers = {
            "https://sites.qevik.ai/site-a/": SimpleNamespace(
                status=200, bytes=1967, error=""),
            "https://sites.qevik.ai/demo-b/": SimpleNamespace(
                status=404, bytes=90, error=""),
        }

        class _Fetcher:
            def __init__(self, *a, **k): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def get(self, url, **_): return answers[url]

        monkeypatch.setattr(net, "Fetcher", _Fetcher)
        body = client.get("/api/missions/published?check=true").json()

        assert body["counts"]["live"] == 1
        assert body["counts"]["down"] == 1
        assert body["checked"] is True

    def test_a_url_that_could_not_be_reached_is_not_reported_as_down(
            self, client, app, monkeypatch) -> None:
        """A demo reported down gets rebuilt; a demo reported live goes into an
        approved message. Neither is right when the request simply failed."""
        from types import SimpleNamespace

        from atlas_kernel.research import net

        self._memory(app, self._rows()[:1])

        class _Fetcher:
            def __init__(self, *a, **k): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def get(self, url, **_):
                return SimpleNamespace(status=0, bytes=0, error="timed out")

        monkeypatch.setattr(net, "Fetcher", _Fetcher)
        body = client.get("/api/missions/published?check=true").json()

        assert body["counts"]["down"] == 0
        assert body["counts"]["unchecked"] == 1
        assert "timed out" in body["published"][0]["detail"]

    def test_the_route_is_not_swallowed_by_the_mission_detail_handler(
            self, client, app, monkeypatch) -> None:
        """`/{mission_id}` matches a literal segment happily. Registered after
        it, this would be served as a mission called "published" — a 404 that
        reads as an empty list. This repository has shipped that bug once."""
        self._memory(app, [])

        response = client.get("/api/missions/published")

        assert response.status_code == 200
        assert "published" in response.json()
