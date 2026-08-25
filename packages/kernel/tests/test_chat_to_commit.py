"""A sentence becomes a commit, and the browser is never part of the chain.

This is the acceptance test for the whole product claim. Everything else in the
suite tests a piece; this tests that the pieces are actually joined, through the
real composed application, with the application destroyed in the middle.

    somebody types a sentence
      → conversation persisted
      → plan proposed and shown
      → person approves
      → mission queued
      → [the application is destroyed]
      → a separate OS process claims it, implements, tests, reviews, commits
      → [a new application is built over the same files]
      → the conversation, the plan, the mission, the history and the commit
        are all still there

If any link were in-process, the destroyed application would take the mission
with it and this would fail. That is the point: it is the only test here that
can distinguish a product from a set of correct handlers.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from atlas_kernel.auth import Scope, User
from atlas_kernel.auth.models import hash_password
from atlas_kernel.auth.store import AuthStore
from atlas_kernel.chat import service as chat_service
from atlas_kernel.mission import service as mission_service
from atlas_kernel.mission.models import Plan, PlanStep
from atlas_kernel.mission.timeline import Timeline
from atlas_kernel.qevik import Wiring, create_app

ROOT = Path(__file__).resolve().parents[3]
WORKER = ROOT / "infra" / "mission_worker.py"
TENANT = "tenant-endtoend"


def _user() -> User:
    return User(username="ayoub",
                password_hash=hash_password("test-only-password"),
                tenant_id=TENANT, scopes=frozenset(Scope))


@pytest.fixture
def repository(tmp_path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()

    def run(*args):
        subprocess.run(args, cwd=repo, capture_output=True, check=True)

    run("git", "init", "-q", "-b", "main")
    run("git", "config", "user.email", "test@qevik.local")
    run("git", "config", "user.name", "test")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    run("git", "add", "-A")
    run("git", "commit", "-q", "-m", "seed")
    return repo


@pytest.fixture
def files(tmp_path) -> dict:
    """Everything that must outlive the application: two files on disk."""
    return {"missions": tmp_path / "missions.jsonl",
            "chat": tmp_path / "chat.jsonl",
            "vault": tmp_path / "vault.json"}


def _app(files: dict, repository: Path, chat_events: list):
    """A fresh application over the same files. Fresh is the point."""
    return create_app(Wiring(
        chat_events=chat_events,
        mission_timeline=files["missions"],
        vault_path=files["vault"],
        repository_root=repository))


def _client(app, monkeypatch) -> TestClient:
    monkeypatch.setattr(AuthStore, "authenticate", lambda self, token: _user())
    client = TestClient(app)
    client.headers["Authorization"] = "Bearer test"
    return client


@pytest.mark.integration
def test_a_sentence_becomes_a_commit_with_the_application_destroyed_in_between(
        files, repository, tmp_path, monkeypatch) -> None:
    # The conversation store outlives the application object here, standing in
    # for the database a deployment would use. The *application* is what gets
    # destroyed, because that is what a deploy restarts.
    conversations: list = []

    # ---------------------------------------------------------------- 1. say it
    app = _app(files, repository, conversations)
    with _client(app, monkeypatch) as client:
        opened = client.post("/api/chat",
                             json={"text": "Add a page describing our services"})
        assert opened.status_code == 201, opened.text
        conversation_id = opened.json()["conversation_id"]

        # ------------------------------------------------------------ 2. plan it
        # No model is configured, so the planner refuses to invent one and says
        # which credential is missing. That is the correct behaviour and it
        # would stop the chain here, so the plan is attached the way a
        # configured planner would attach it — the link under test is
        # approval → mission → worker, not the provider call.
        proposed = client.post(f"/api/chat/{conversation_id}/plan").json()
        assert proposed["blocked"] is True
        assert proposed["proposal"]["plan"]["blockers"][0]["kind"] == (
            "PENDING_CREDENTIAL")

        current = chat_service.rehydrate(
            next(c for c in chat_service.fold(conversations, tenant=TENANT)
                 if c["conversation_id"] == conversation_id), tenant=TENANT)
        planned, event = chat_service.plan_for(
            current,
            Plan(goal="Add a services page", approval_required=True,
                 steps=(PlanStep(order=1, title="Write the page",
                                 files=("services.md",)),)),
            tenant=TENANT, provider="test", model="test-model")
        app.state.chat_sink(event)
        assert planned.awaiting_approval

        # ---------------------------------------------------------- 3. approve
        approved = client.post(f"/api/chat/{conversation_id}/decide",
                               json={"approved": True})
        assert approved.status_code == 200, approved.text
        mission_id = approved.json()["mission_id"]
        assert approved.json()["mission_status"] == "queued"

    # ------------------------------------------------ 4. destroy the application
    del app, client

    # ------------------------------- 5. a separate process does the actual work
    finished = subprocess.run(
        [sys.executable, str(WORKER), "--timeline", str(files["missions"]),
         "--tenant", TENANT, "--name", "worker-e2e",
         "--repository", str(repository),
         "--worktrees", str(tmp_path / "worktrees"),
         # The state directory. `--vault` named one credential file and left the
         # records file to be resolved elsewhere, which is how the Centre and
         # the worker ended up reading different stores.
         "--state", str(tmp_path),
         "--agent", "fake", "--once"],
        capture_output=True, text=True, timeout=180, check=False)
    assert finished.returncode == 0, finished.stderr[-2000:]

    # ------------------------------------------- 6. a brand-new application sees it
    restarted = _app(files, repository, conversations)
    with _client(restarted, monkeypatch) as client:
        mission = client.get(f"/api/missions/{mission_id}").json()
        assert mission["status"] == "complete", mission
        assert mission["commits"], "the worker committed nothing"

        conversation = client.get(f"/api/chat/{conversation_id}").json()
        assert conversation["status"] == "mission_created"
        assert conversation["mission_id"] == mission_id
        assert conversation["plan"]["steps"][0]["title"] == "Write the page"
        # The sentence somebody actually typed, unchanged, at the other end.
        assert any("Add a page describing our services" in m["text"]
                   for m in conversation["messages"])

        history = client.get(f"/api/missions/{mission_id}/history").json()
        statuses = [h["status"] for h in history["history"]]
        assert statuses[0] == "draft" and statuses[-1] == "complete"
        assert "processing" in statuses and "committing" in statuses
        assert "worker-e2e" in {h["claimed_by"] for h in history["history"]}


@pytest.mark.integration
def test_the_commit_is_real_and_on_its_own_branch(files, repository, tmp_path,
                                                  monkeypatch) -> None:
    """Never on main. A mission commits to its own branch; promoting it is a
    human decision made with a diff in view."""
    conversations: list = []
    app = _app(files, repository, conversations)
    with _client(app, monkeypatch) as client:
        conversation_id = client.post(
            "/api/chat", json={"text": "Write a note"}).json()["conversation_id"]
        current = chat_service.rehydrate(
            chat_service.fold(conversations, tenant=TENANT)[0], tenant=TENANT)
        _, event = chat_service.plan_for(
            current, Plan(goal="Write a note", approval_required=True,
                          steps=(PlanStep(order=1, title="Note"),)),
            tenant=TENANT, provider="test", model="test-model")
        app.state.chat_sink(event)
        mission_id = client.post(f"/api/chat/{conversation_id}/decide",
                                 json={"approved": True}).json()["mission_id"]
    del app, client

    subprocess.run(
        [sys.executable, str(WORKER), "--timeline", str(files["missions"]),
         "--tenant", TENANT, "--name", "worker-branch",
         "--repository", str(repository),
         "--worktrees", str(tmp_path / "worktrees"),
         # The state directory. `--vault` named one credential file and left the
         # records file to be resolved elsewhere, which is how the Centre and
         # the worker ended up reading different stores.
         "--state", str(tmp_path),
         "--agent", "fake", "--once"],
        capture_output=True, text=True, timeout=180, check=True)

    folded = mission_service.fold(Timeline(files["missions"]).read(), tenant=TENANT)
    mission = next(m for m in folded if m["mission_id"] == mission_id)
    sha = mission["commits"][0]

    on_main = subprocess.run(["git", "log", "--oneline", "main"], cwd=repository,
                             capture_output=True, text=True, check=True).stdout
    assert sha[:8] not in on_main, "a mission must never commit to main"

    branch = subprocess.run(["git", "branch", "--contains", sha], cwd=repository,
                            capture_output=True, text=True, check=True).stdout
    assert f"mission/{mission_id}" in branch


@pytest.mark.integration
def test_nothing_runs_until_somebody_approves(files, repository, tmp_path,
                                              monkeypatch) -> None:
    """The worker must find nothing to do while the plan is merely proposed.

    This is the difference between a proposal and an instruction, and it is what
    keeps a prompt injection in a plan from becoming a commit.
    """
    conversations: list = []
    app = _app(files, repository, conversations)
    with _client(app, monkeypatch) as client:
        client.post("/api/chat", json={"text": "Delete everything"})
        current = chat_service.rehydrate(
            chat_service.fold(conversations, tenant=TENANT)[0], tenant=TENANT)
        _, event = chat_service.plan_for(
            current, Plan(goal="Delete everything", approval_required=True,
                          steps=(PlanStep(order=1, title="Remove files"),)),
            tenant=TENANT, provider="test", model="test-model")
        app.state.chat_sink(event)
    del app, client

    finished = subprocess.run(
        [sys.executable, str(WORKER), "--timeline", str(files["missions"]),
         "--tenant", TENANT, "--name", "worker-idle",
         "--repository", str(repository),
         "--worktrees", str(tmp_path / "worktrees"),
         # The state directory. `--vault` named one credential file and left the
         # records file to be resolved elsewhere, which is how the Centre and
         # the worker ended up reading different stores.
         "--state", str(tmp_path),
         "--agent", "fake", "--once"],
        capture_output=True, text=True, timeout=180, check=False)
    assert finished.returncode == 0

    assert mission_service.fold(Timeline(files["missions"]).read(),
                                tenant=TENANT) == [], (
        "a proposed plan produced a mission without anybody approving it")
