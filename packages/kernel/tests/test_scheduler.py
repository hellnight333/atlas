from __future__ import annotations

from fastapi.testclient import TestClient

from atlas_kernel.api import app, repository


client = TestClient(app)


def _create_project() -> str:
    workspace = client.post("/workspaces", json={"name": "scheduler-ws", "description": "scheduler"})
    assert workspace.status_code == 200
    project = client.post(
        "/projects",
        json={
            "workspace_id": workspace.json()["workspace_id"],
            "name": "scheduler-project",
            "description": "scheduler",
        },
    )
    assert project.status_code == 200
    return project.json()["project_id"]


def _create_agent(project_id: str) -> str:
    agent = client.post(
        "/agents",
        json={
            "name": "Scheduler Agent",
            "description": "scheduler",
            "role": "planner",
            "project_id": project_id,
            "capabilities": ["research", "workflow"],
            "permission_set": ["read_assets"],
        },
    )
    assert agent.status_code == 200
    return agent.json()["id"]


def test_scheduler_create_queue_pause_resume_cancel_without_execution_side_effects() -> None:
    project_id = _create_project()
    agent_id = _create_agent(project_id)

    jobs_before = len(repository.list_jobs())
    runs_before = len(repository.list_runs())

    created = client.post(
        "/scheduler/schedule",
        json={
            "agent_id": agent_id,
            "goal": "Create a deterministic execution schedule",
            "priority": "normal",
            "available_executors": ["local"],
            "execution_policy": {},
        },
    )
    assert created.status_code == 200
    schedule = created.json()
    schedule_id = schedule["schedule_id"]

    queue = client.get(f"/scheduler/{schedule_id}/queue")
    assert queue.status_code == 200
    assert len(queue.json()) >= 1

    paused = client.post(f"/scheduler/{schedule_id}/pause", json={})
    assert paused.status_code == 200
    assert paused.json()["status"] == "ok"

    resumed = client.post(f"/scheduler/{schedule_id}/resume", json={})
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "ok"

    cancelled = client.post(f"/scheduler/{schedule_id}/cancel", json={})
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "ok"

    queue_after = client.get(f"/scheduler/{schedule_id}/queue")
    assert queue_after.status_code == 200
    assert all(entry["status"] in {"cancelled", "completed"} for entry in queue_after.json())

    jobs_after = len(repository.list_jobs())
    runs_after = len(repository.list_runs())
    assert jobs_after == jobs_before
    assert runs_after == runs_before
