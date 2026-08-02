from __future__ import annotations

from fastapi.testclient import TestClient

from atlas_kernel.agents.events import (
    RuntimeCancelled,
    RuntimeCompleted,
    RuntimeFailed,
    RuntimePreparing,
    RuntimeProgress,
    RuntimeRunning,
    RuntimeStarted,
    RuntimeTimedOut,
)
from atlas_kernel.agents.schedule_models import RuntimeExecutionStatus
from atlas_kernel.api import agent_foundation, app, event_bus, repository

client = TestClient(app)


def _create_project() -> str:
    workspace = client.post("/workspaces", json={"name": "runtime-ws", "description": "runtime"})
    assert workspace.status_code == 200
    project = client.post(
        "/projects",
        json={
            "workspace_id": workspace.json()["workspace_id"],
            "name": "runtime-project",
            "description": "runtime",
        },
    )
    assert project.status_code == 200
    return project.json()["project_id"]


def _create_agent(project_id: str, capabilities: list[str] | None = None) -> str:
    response = client.post(
        "/agents",
        json={
            "name": "Runtime Agent",
            "description": "runtime",
            "role": "operator",
            "project_id": project_id,
            "capabilities": capabilities or ["research", "workflow"],
            "permission_set": ["read_assets"],
        },
    )
    assert response.status_code == 200
    return response.json()["id"]


def _create_schedule(agent_id: str, goal: str = "Execute scheduled work") -> str:
    created = client.post(
        "/scheduler/schedule",
        json={
            "agent_id": agent_id,
            "goal": goal,
            "priority": "normal",
            "available_executors": ["local"],
            "execution_policy": {},
        },
    )
    assert created.status_code == 200
    return created.json()["schedule_id"]


def test_runtime_execute_success() -> None:
    project_id = _create_project()
    agent_id = _create_agent(project_id)
    schedule_id = _create_schedule(agent_id)

    started = client.post(f"/runtime/schedule/{schedule_id}/start", json={})
    assert started.status_code == 200
    payload = started.json()
    assert payload
    assert any(item["status"] == "completed" for item in payload)
    assert any(item["asset_id"] is not None for item in payload if item["status"] == "completed")


def test_runtime_provider_failure() -> None:
    project_id = _create_project()
    agent_id = _create_agent(project_id, capabilities=["unknown-capability"])
    schedule_id = _create_schedule(agent_id, goal="Force provider failure")

    started = client.post(f"/runtime/schedule/{schedule_id}/start", json={})
    assert started.status_code == 200
    payload = started.json()
    assert any(item["status"] == "failed" for item in payload)


def test_runtime_timeout() -> None:
    project_id = _create_project()
    agent_id = _create_agent(project_id)
    schedule_id = _create_schedule(agent_id, goal="Timeout path")

    schedule = agent_foundation.get_schedule(schedule_id)
    assert schedule is not None
    entry = next(item for item in schedule.queue_entries if item.status.value == "ready")
    runtime_execution = agent_foundation._runtime.execute_entry(  # type: ignore[attr-defined]
        schedule,
        entry,
        retry_policy=(
            agent_foundation._runtime.list_runtime_executions()[0].retry_policy
            if agent_foundation._runtime.list_runtime_executions()
            else (
                repository.get_runtime_execution(
                    repository.list_runtime_executions()[0].execution_id
                ).retry_policy
                if repository.list_runtime_executions()
                else __import__(
                    "atlas_kernel.agents.schedule_models", fromlist=["RuntimeRetryPolicy"]
                ).RuntimeRetryPolicy(max_attempts=1, retry_delay=0.0, backoff=1.0)
            )
        ),
        timeout_seconds=0.0,
        heartbeat_interval_seconds=0.0,
    )
    assert runtime_execution.status == RuntimeExecutionStatus.TIMED_OUT


def test_runtime_retry() -> None:
    project_id = _create_project()
    agent_id = _create_agent(project_id, capabilities=["unknown-capability"])
    schedule_id = _create_schedule(agent_id, goal="Retry path")

    started = client.post(f"/runtime/schedule/{schedule_id}/start", json={})
    assert started.status_code == 200
    failed = next(item for item in started.json() if item["status"] == "failed")

    retried = client.post(f"/runtime/{failed['execution_id']}/retry", json={})
    assert retried.status_code == 200
    assert retried.json()["attempts"] >= 1


def test_runtime_cancel() -> None:
    project_id = _create_project()
    agent_id = _create_agent(project_id)
    schedule_id = _create_schedule(agent_id, goal="Cancel path")

    started = client.post(f"/runtime/schedule/{schedule_id}/start", json={})
    assert started.status_code == 200
    execution_id = started.json()[0]["execution_id"]

    cancelled = client.post(f"/runtime/{execution_id}/cancel", json={})
    assert cancelled.status_code == 200
    assert cancelled.json()["cancellation_requested"] is True


def test_runtime_heartbeat_and_event_emission() -> None:
    captured: list[object] = []

    event_bus.subscribe(RuntimeStarted, lambda event: captured.append(event))
    event_bus.subscribe(RuntimePreparing, lambda event: captured.append(event))
    event_bus.subscribe(RuntimeRunning, lambda event: captured.append(event))
    event_bus.subscribe(RuntimeProgress, lambda event: captured.append(event))
    event_bus.subscribe(RuntimeCompleted, lambda event: captured.append(event))
    event_bus.subscribe(RuntimeFailed, lambda event: captured.append(event))
    event_bus.subscribe(RuntimeCancelled, lambda event: captured.append(event))
    event_bus.subscribe(RuntimeTimedOut, lambda event: captured.append(event))

    project_id = _create_project()
    agent_id = _create_agent(project_id)
    schedule_id = _create_schedule(agent_id, goal="Emit runtime events")

    response = client.post(f"/runtime/schedule/{schedule_id}/start", json={})
    assert response.status_code == 200
    assert any(isinstance(item, RuntimeStarted) for item in captured)
    assert any(isinstance(item, RuntimePreparing) for item in captured)
    assert any(isinstance(item, RuntimeRunning) for item in captured)
    assert any(isinstance(item, RuntimeProgress) for item in captured)
    assert any(isinstance(item, RuntimeCompleted) for item in captured)


def test_runtime_history_and_running_endpoints() -> None:
    project_id = _create_project()
    agent_id = _create_agent(project_id)
    schedule_id = _create_schedule(agent_id, goal="History endpoints")

    started = client.post(f"/runtime/schedule/{schedule_id}/start", json={})
    assert started.status_code == 200

    listing = client.get("/runtime")
    running = client.get("/runtime/running")
    history = client.get("/runtime/history")
    assert listing.status_code == 200
    assert running.status_code == 200
    assert history.status_code == 200
    assert isinstance(listing.json(), list)
    assert isinstance(running.json(), list)
    assert isinstance(history.json(), list)
