from __future__ import annotations

from fastapi.testclient import TestClient

from atlas_kernel.agents.events import (
    AgentAssigned,
    AgentCompleted,
    AgentMessageReceived,
    AgentMessageSent,
    AgentStarted,
    AgentWaiting,
    TeamCompleted,
)
from atlas_kernel.api import app, event_bus

client = TestClient(app)


def _create_project() -> str:
    workspace = client.post("/workspaces", json={"name": "team-ws", "description": "team"})
    assert workspace.status_code == 200
    project = client.post(
        "/projects",
        json={
            "workspace_id": workspace.json()["workspace_id"],
            "name": "team-project",
            "description": "team",
        },
    )
    assert project.status_code == 200
    return project.json()["project_id"]


def _create_agent(project_id: str, name: str, role: str, capabilities: list[str]) -> str:
    response = client.post(
        "/agents",
        json={
            "name": name,
            "description": role,
            "role": role,
            "project_id": project_id,
            "capabilities": capabilities,
            "permission_set": ["read_assets"],
        },
    )
    assert response.status_code == 200
    return response.json()["id"]


def test_team_creation_and_assignment() -> None:
    project_id = _create_project()
    research_id = _create_agent(project_id, "Research Agent", "research", ["research"])
    writer_id = _create_agent(project_id, "Writer Agent", "writer", ["text"])

    created = client.post(
        "/agents/team",
        json={
            "name": "Launch Team",
            "project_id": project_id,
            "assignments": [
                {
                    "agent_id": research_id,
                    "role": "research",
                    "title": "Research brief",
                    "action": "text.generate",
                    "payload": {"prompt": "research brief"},
                    "dependencies": [],
                },
                {
                    "agent_id": writer_id,
                    "role": "writer",
                    "title": "Write summary",
                    "action": "text.generate",
                    "payload": {"prompt": "write summary"},
                    "dependencies": [],
                },
            ],
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["id"]
    assert len(payload["assignments"]) == 2


def test_mailbox_delivery_and_message_ordering() -> None:
    project_id = _create_project()
    research_id = _create_agent(project_id, "Research Agent", "research", ["research"])
    writer_id = _create_agent(project_id, "Writer Agent", "writer", ["text"])

    created = client.post(
        "/agents/team",
        json={
            "name": "Mailbox Team",
            "project_id": project_id,
            "assignments": [
                {
                    "agent_id": research_id,
                    "role": "research",
                    "title": "Research",
                    "action": "text.generate",
                    "payload": {"prompt": "research"},
                    "dependencies": [],
                },
                {
                    "agent_id": writer_id,
                    "role": "writer",
                    "title": "Write",
                    "action": "text.generate",
                    "payload": {"prompt": "write"},
                    "dependencies": [],
                },
            ],
        },
    )
    assert created.status_code == 200
    team_id = created.json()["id"]

    messages = client.get(f"/agents/team/{team_id}/messages")
    assert messages.status_code == 200
    payload = messages.json()
    assert len(payload) >= 2
    timestamps = [item["timestamp"] for item in payload]
    assert timestamps == sorted(timestamps)


def test_waiting_state_and_completion() -> None:
    project_id = _create_project()
    research_id = _create_agent(project_id, "Research Agent", "research", ["research"])
    reviewer_id = _create_agent(project_id, "Reviewer Agent", "reviewer", ["review"])

    created = client.post(
        "/agents/team",
        json={
            "name": "Dependency Team",
            "project_id": project_id,
            "assignments": [
                {
                    "agent_id": research_id,
                    "role": "research",
                    "title": "Research",
                    "action": "text.generate",
                    "payload": {"prompt": "research"},
                    "dependencies": [],
                },
                {
                    "agent_id": reviewer_id,
                    "role": "reviewer",
                    "title": "Review",
                    "action": "text.generate",
                    "payload": {"prompt": "review"},
                    "dependencies": ["missing-dependency"],
                },
            ],
        },
    )
    assert created.status_code == 200
    team_id = created.json()["id"]

    status = client.get(f"/agents/team/{team_id}/status")
    assert status.status_code == 200
    payload = status.json()
    assert isinstance(payload["waiting"], list)
    assert isinstance(payload["completed"], list)


def test_team_cancellation() -> None:
    project_id = _create_project()
    operator_id = _create_agent(project_id, "Operator Agent", "operator", ["workflow"])

    created = client.post(
        "/agents/team",
        json={
            "name": "Cancelable Team",
            "project_id": project_id,
            "assignments": [
                {
                    "agent_id": operator_id,
                    "role": "operator",
                    "title": "Operate",
                    "action": "text.generate",
                    "payload": {"prompt": "operate"},
                    "dependencies": [],
                }
            ],
        },
    )
    assert created.status_code == 200
    team_id = created.json()["id"]

    cancelled = client.post(f"/agents/team/{team_id}/cancel", json={})
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


def test_multi_agent_event_emission() -> None:
    captured: list[object] = []
    event_bus.subscribe(AgentAssigned, lambda event: captured.append(event))
    event_bus.subscribe(AgentStarted, lambda event: captured.append(event))
    event_bus.subscribe(AgentWaiting, lambda event: captured.append(event))
    event_bus.subscribe(AgentMessageSent, lambda event: captured.append(event))
    event_bus.subscribe(AgentMessageReceived, lambda event: captured.append(event))
    event_bus.subscribe(AgentCompleted, lambda event: captured.append(event))
    event_bus.subscribe(TeamCompleted, lambda event: captured.append(event))

    project_id = _create_project()
    research_id = _create_agent(project_id, "Research Agent", "research", ["research"])

    created = client.post(
        "/agents/team",
        json={
            "name": "Event Team",
            "project_id": project_id,
            "assignments": [
                {
                    "agent_id": research_id,
                    "role": "research",
                    "title": "Research",
                    "action": "text.generate",
                    "payload": {"prompt": "research"},
                    "dependencies": [],
                }
            ],
        },
    )
    assert created.status_code == 200
    assert any(isinstance(item, AgentAssigned) for item in captured)
    assert any(isinstance(item, AgentStarted) for item in captured)
    assert any(isinstance(item, AgentMessageSent) for item in captured)
    assert any(isinstance(item, AgentMessageReceived) for item in captured)
    assert any(isinstance(item, AgentCompleted) for item in captured)
    assert any(isinstance(item, TeamCompleted) for item in captured)
