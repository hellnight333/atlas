from __future__ import annotations

from fastapi.testclient import TestClient

from atlas_kernel.api import app, repository


client = TestClient(app)


def _create_project() -> str:
    workspace = client.post("/workspaces", json={"name": "planner-ws", "description": "planner"})
    assert workspace.status_code == 200
    project = client.post(
        "/projects",
        json={
            "workspace_id": workspace.json()["workspace_id"],
            "name": "planner-project",
            "description": "planner",
        },
    )
    assert project.status_code == 200
    return project.json()["project_id"]


def test_agent_planner_generates_plan_and_dependency_graph_without_execution_side_effects() -> None:
    project_id = _create_project()

    agent = client.post(
        "/agents",
        json={
            "name": "Planner Agent",
            "description": "planner",
            "role": "planner",
            "project_id": project_id,
            "capabilities": ["research", "workflow", "review"],
            "permission_set": ["read_assets"],
        },
    )
    assert agent.status_code == 200
    agent_id = agent.json()["id"]

    jobs_before = len(repository.list_jobs())
    runs_before = len(repository.list_runs())

    response = client.post(
        f"/agents/{agent_id}/plan",
        json={"goal": "Create a launch-ready execution plan for campaign assets"},
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["plan_id"]
    assert payload["goal"].startswith("Create a launch-ready")
    assert payload["confidence"] > 0
    assert payload["estimated_duration_seconds"] > 0
    assert payload["estimated_cost_usd"] >= 0
    assert len(payload["steps"]) >= 2
    assert all("id" in step for step in payload["steps"])
    assert all("estimate" in step for step in payload["steps"])
    assert isinstance(payload["dependencies"], list)

    jobs_after = len(repository.list_jobs())
    runs_after = len(repository.list_runs())
    assert jobs_after == jobs_before
    assert runs_after == runs_before


def test_agent_planner_cost_and_confidence_fields_are_populated() -> None:
    project_id = _create_project()
    agent = client.post(
        "/agents",
        json={
            "name": "Estimator Agent",
            "description": "planner",
            "role": "planner",
            "project_id": project_id,
            "capabilities": ["image", "review"],
            "permission_set": ["read_assets"],
        },
    )
    assert agent.status_code == 200
    agent_id = agent.json()["id"]

    plan = client.post(
        f"/agents/{agent_id}/plan",
        json={"goal": "Design and review hero image variants"},
    )
    assert plan.status_code == 200
    payload = plan.json()

    assert 0.0 <= payload["confidence"] <= 0.99
    assert payload["estimated_cost_usd"] >= 0
    assert all(step["estimate"]["tokens"] >= 0 for step in payload["steps"])
    assert any(step["review_required"] for step in payload["steps"])


def test_agent_planner_uses_workspace_context_gathering() -> None:
    project_id = _create_project()
    agent = client.post(
        "/agents",
        json={
            "name": "Context Agent",
            "description": "planner",
            "role": "planner",
            "project_id": project_id,
            "capabilities": ["research", "workflow"],
            "permission_set": ["read_assets"],
        },
    )
    assert agent.status_code == 200
    agent_id = agent.json()["id"]

    _ = client.post(
        "/assets",
        json={
            "type": "research",
            "project_id": project_id,
            "uri": "atlas://planner/research-note",
            "metadata": {"title": "research note"},
        },
    )

    plan = client.post(f"/agents/{agent_id}/plan", json={"goal": "Synthesize context"})
    assert plan.status_code == 200
    payload = plan.json()
    snapshot = payload["context_snapshot"]
    assert "project_summary" in snapshot
    assert "running_jobs" in snapshot
    assert "open_workflows" in snapshot
