"""The worker and the UI are separate processes, proven by killing one.

The claim "closing the browser does not stop a mission" is the kind that passes
review, ships, and turns out to be false the first time somebody deploys during
a run. An in-process test cannot catch that: mocking the worker and asserting it
was called proves the wiring, not the independence.

So this spawns `infra/mission_worker.py` as a real subprocess, with **no HTTP
application alive at all** while it runs, and then builds a *new* application
afterwards to read the result. If the two were coupled — a shared object, an
import, a parent process — the mission would not finish here.

The timeline file is the only thing they share, which is the design.
"""

from __future__ import annotations

import json
import subprocess
import sys
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
from atlas_kernel.mission.models import MissionStatus, Plan, PlanStep
from atlas_kernel.mission.timeline import Timeline

ROOT = Path(__file__).resolve().parents[3]
WORKER = ROOT / "infra" / "mission_worker.py"
TENANT = "tenant-independence"


def _user() -> User:
    return User(username="operator",
                password_hash=hash_password("test-only-password"),
                tenant_id=TENANT, scopes=frozenset(Scope))


def _app(timeline: Timeline, root: Path) -> FastAPI:
    """A fresh application over the same timeline. Deliberately fresh: this is
    what "restart the API" means."""
    application = FastAPI()
    auth_api.install(application, AuthStore())
    mission_api.install(application)
    application.state.mission_events = timeline
    application.state.mission_sink = timeline.append
    application.state.repository_root = str(root)
    return application


@pytest.fixture
def repository(tmp_path) -> Path:
    """A real git repository, because the worker makes a real worktree in one."""
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *args: subprocess.run(args, cwd=repo, capture_output=True,  # noqa: E731
                                       check=True)
    run("git", "init", "-q", "-b", "main")
    run("git", "config", "user.email", "test@qevik.local")
    run("git", "config", "user.name", "test")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    run("git", "add", "-A")
    run("git", "commit", "-q", "-m", "seed")
    return repo


@pytest.fixture
def timeline(tmp_path) -> Timeline:
    return Timeline(tmp_path / "missions.jsonl")


def _client(app, monkeypatch) -> TestClient:
    monkeypatch.setattr(AuthStore, "authenticate", lambda self, token: _user())
    client = TestClient(app)
    client.headers["Authorization"] = "Bearer test"
    return client


def _run_worker(timeline: Timeline, repository: Path, tmp_path: Path,
                *, name: str = "worker-detached", agent: str = "fake"
                ) -> subprocess.CompletedProcess:
    """Run the real worker binary.

    `--agent fake` is passed explicitly, because that is the only way to get a
    stub agent — see `test_the_worker_refuses_to_run_without_a_model`. A test
    that got one by default would also be a production run that got one by
    default.
    """
    return subprocess.run(
        [sys.executable, str(WORKER), "--timeline", str(timeline.path),
         "--tenant", TENANT, "--name", name, "--repository", str(repository),
         "--worktrees", str(tmp_path / f"worktrees-{name}"), "--agent", agent,
         # The state directory, not a file: the credential file names belong to
         # `credentials.location`, and a caller choosing one is how the control
         # plane and the worker drifted apart.
         "--state", str(tmp_path / f"state-{name}"), "--once"],
        capture_output=True, text=True, timeout=180, check=False)


# ============================================ the acceptance test

@pytest.mark.integration
def test_a_mission_runs_to_completion_with_no_http_process_alive(
        timeline, repository, tmp_path, monkeypatch) -> None:
    """Submit and approve over HTTP, destroy the app, let the worker finish.

    The four phases are the point. If the application object were still alive
    during phase 3, this would prove nothing about a deploy that restarts it.
    """
    # 1. Submit and approve through the HTTP surface.
    app = _app(timeline, repository)
    with _client(app, monkeypatch) as client:
        created = client.post("/api/missions",
                              json={"title": "Write a file in isolation"})
        assert created.status_code == 201, created.text
        mission_id = created.json()["mission_id"]

        # Plan it, as the planner would, and approve.
        mission = service.rehydrate(created.json(), tenant=TENANT)
        mission, event = service.transition(mission, MissionStatus.PLANNING,
                                            tenant=TENANT)
        timeline.append(event)
        _, event = service.attach_plan(
            mission, Plan(goal="write a file", approval_required=True,
                          steps=(PlanStep(order=1, title="write it"),)),
            tenant=TENANT)
        timeline.append(event)

        approved = client.post(f"/api/missions/{mission_id}/approve", json={})
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "queued"

    # 2. The API is gone. Not mocked out — gone.
    del app, client

    # 3. The worker runs as its own process, with nothing serving HTTP.
    finished = _run_worker(timeline, repository, tmp_path)
    assert finished.returncode == 0, finished.stderr[-2000:]

    # 4. A brand-new application, as though the deploy just finished.
    restarted = _app(Timeline(timeline.path), repository)
    with _client(restarted, monkeypatch) as client:
        body = client.get(f"/api/missions/{mission_id}").json()
        assert body["status"] == "complete", body
        assert body["commits"], "the worker committed nothing"
        # Released on completion — a finished mission is held by nobody. The
        # evidence of *which* process ran it is in the history, where each entry
        # is a snapshot taken at the moment of the transition.
        assert body["claimed_by"] == ""

        history = client.get(f"/api/missions/{mission_id}/history").json()
        statuses = [h["status"] for h in history["history"]]
        # The whole lifecycle, in order, recorded by two different processes.
        assert statuses[0] == "draft" and statuses[-1] == "complete"
        assert "processing" in statuses and "committing" in statuses
        assert "worker-detached" in {h["claimed_by"] for h in history["history"]}, (
            "no snapshot records the detached worker holding this mission")


@pytest.mark.integration
def test_the_worker_refuses_to_run_without_a_model(timeline, repository, tmp_path
                                                   ) -> None:
    """A silent fallback to a stub is the worst failure this worker could have.

    It would claim missions, commit files, write reports and mark everything
    complete — and every artefact would describe work no model ever did. So a
    missing credential is a refusal with a non-zero exit, not a downgrade.
    """
    mission, event = service.create(tenant=TENANT, title="Needs a model",
                                    requested_by="ayoub")
    timeline.append(event)
    timeline.append(service._event(
        mission.model_copy(update={"status": MissionStatus.QUEUED}),
        actor="test", note="queued"))

    refused = _run_worker(timeline, repository, tmp_path, agent="llm")
    assert refused.returncode == 2, refused.stdout[-1000:]
    assert "will not substitute one silently" in refused.stderr

    folded = service.fold(Timeline(timeline.path).read(), tenant=TENANT)
    still = next(m for m in folded if m["mission_id"] == mission.id)
    assert still["status"] == "queued", "the refused mission must be untouched"
    assert still["claimed_by"] == ""


@pytest.mark.integration
def test_the_worker_never_imports_the_http_surface() -> None:
    """Independence by construction, not by convention.

    A worker that imports the API can be broken by a change to the API, and a
    single shared module is all it takes for someone to reach for `app.state`
    from inside the worker later.
    """
    source = WORKER.read_text(encoding="utf-8")
    for forbidden in ("fastapi", "mission.api", "app.state", "TestClient",
                      "uvicorn"):
        assert forbidden not in source, forbidden


@pytest.mark.integration
def test_a_worker_that_dies_mid_mission_releases_its_claim(
        timeline, repository, tmp_path) -> None:
    """Otherwise the mission sits there looking busy forever.

    Simulated by writing the claim a dead worker would have left, with an
    `updated_at` old enough to be stale, and letting a fresh worker start.
    """
    from datetime import UTC, datetime, timedelta

    mission, event = service.create(tenant=TENANT, title="Abandoned",
                                    requested_by="ayoub")
    timeline.append(event)
    abandoned = mission.model_copy(update={
        "status": MissionStatus.PROCESSING, "claimed_by": "worker-that-died",
        "updated_at": datetime.now(UTC) - timedelta(hours=6)})
    timeline.append(service._event(abandoned, actor="worker-that-died",
                                   note="claimed then died"))

    finished = _run_worker(timeline, repository, tmp_path, name="worker-fresh")
    assert finished.returncode == 0, finished.stderr[-2000:]

    folded = service.fold(Timeline(timeline.path).read(), tenant=TENANT)
    found = next(m for m in folded if m["mission_id"] == mission.id)
    assert found["status"] != "processing", "still looks busy after recovery"
    assert found["claimed_by"] != "worker-that-died"


# ============================================ the file they share

def test_the_timeline_survives_a_corrupt_line(tmp_path) -> None:
    """One bad line must not take down every mission written before it."""
    path = tmp_path / "t.jsonl"
    path.write_text('{"kind": "a"}\nnot json at all\n{"kind": "b"}\n',
                    encoding="utf-8")
    line = Timeline(path)
    assert [e["kind"] for e in line.read()] == ["a", "b"]
    assert line.corrupt == 1, "the loss must be counted, not silent"


def test_an_append_is_one_whole_line(tmp_path) -> None:
    """Two processes appending must interleave records, never shred them."""
    line = Timeline(tmp_path / "t.jsonl")
    mission, event = service.create(tenant=TENANT, title="x", requested_by="a")
    line.append(event)
    line.append({"kind": "other", "detail": {}})

    raw = (tmp_path / "t.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(raw) == 2
    assert json.loads(raw[0])["detail"]["mission_id"] == mission.id


def test_reading_a_timeline_that_does_not_exist_yet_is_empty_not_an_error(tmp_path
                                                                         ) -> None:
    """The API starts before the first mission is ever created."""
    assert Timeline(tmp_path / "nothing.jsonl").read() == []
