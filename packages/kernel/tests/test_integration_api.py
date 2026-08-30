"""End-to-end integration coverage of the public API surface.

Milestone 011 asks for integration tests. These walk complete operator journeys
through the HTTP layer rather than calling services directly, so a regression in
wiring — not just in a service — is caught.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from atlas_kernel.api import app

client = TestClient(app)


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


def _project() -> str:
    workspace = client.post(
        "/workspaces", json={"name": _unique("int-ws"), "description": "integration"}
    )
    assert workspace.status_code == 200
    project = client.post(
        "/projects",
        json={
            "workspace_id": workspace.json()["workspace_id"],
            "name": _unique("int-project"),
            "description": "integration",
        },
    )
    assert project.status_code == 200
    return project.json()["project_id"]


def _agent(project_id: str, capabilities: list[str] | None = None) -> str:
    agent = client.post(
        "/agents",
        json={
            "name": _unique("Agent"),
            "description": "integration",
            "role": "operator",
            "project_id": project_id,
            "capabilities": capabilities or ["image", "research"],
            "permission_set": ["read_assets", "execute_workflow"],
        },
    )
    assert agent.status_code == 200
    return agent.json()["id"]


# ---------------------------------------------------------------------------
# Agent lifecycle
# ---------------------------------------------------------------------------


def test_agent_full_lifecycle() -> None:
    project_id = _project()
    agent_id = _agent(project_id)

    assert agent_id in {a["id"] for a in client.get("/agents").json()}
    assert agent_id in {
        a["id"] for a in client.get("/agents", params={"project_id": project_id}).json()
    }

    fetched = client.get(f"/agents/{agent_id}")
    assert fetched.status_code == 200
    assert fetched.json()["project_id"] == project_id

    patched = client.patch(f"/agents/{agent_id}", json={"description": "updated"})
    assert patched.status_code == 200
    assert patched.json()["description"] == "updated"

    permissions = client.get(f"/agents/{agent_id}/permissions")
    assert permissions.status_code == 200
    assert "read_assets" in permissions.json()

    deleted = client.delete(f"/agents/{agent_id}")
    assert deleted.status_code == 200
    assert client.get(f"/agents/{agent_id}").status_code == 404


def test_partial_patch_preserves_unmentioned_fields() -> None:
    """Regression: PATCH used to write None over every field the caller omitted."""
    project_id = _project()
    agent_id = _agent(project_id, capabilities=["image", "research"])
    before = client.get(f"/agents/{agent_id}").json()

    patched = client.patch(f"/agents/{agent_id}", json={"description": "only this"})
    assert patched.status_code == 200

    after = patched.json()
    assert after["description"] == "only this"
    assert after["name"] == before["name"]
    assert after["role"] == before["role"]
    assert after["status"] == before["status"]
    assert after["capabilities"] == before["capabilities"]
    assert after["project_id"] == project_id


def test_agent_endpoints_404_on_missing_agent() -> None:
    missing = _unique("agent-missing")
    assert client.get(f"/agents/{missing}").status_code == 404
    assert client.patch(f"/agents/{missing}", json={"description": "x"}).status_code == 404
    assert client.get(f"/agents/{missing}/memory").status_code == 404


def test_agent_memory_attachment() -> None:
    project_id = _project()
    agent_id = _agent(project_id)

    assert client.get(f"/agents/{agent_id}/memory").json() == []

    generated = client.post(
        "/images/generate", json={"project_id": project_id, "prompt": _unique("memory asset")}
    )
    assert generated.status_code == 200
    asset_id = generated.json()["image"]["id"]

    attached = client.post(
        f"/agents/{agent_id}/memory", json={"kind": "image", "asset_id": asset_id}
    )
    assert attached.status_code == 200
    assert attached.json()["asset_id"] == asset_id
    assert len(client.get(f"/agents/{agent_id}/memory").json()) == 1


def test_agent_memory_rejects_unknown_asset() -> None:
    agent_id = _agent(_project())
    response = client.post(
        f"/agents/{agent_id}/memory", json={"kind": "image", "asset_id": "asset-missing"}
    )
    assert response.status_code == 404


def test_agent_plan_generation() -> None:
    agent_id = _agent(_project())
    plan = client.post(f"/agents/{agent_id}/plan", json={"goal": "Draft a launch narrative"})
    assert plan.status_code == 200

    body = plan.json()
    assert body["goal"] == "Draft a launch narrative"
    assert body["steps"], "a plan must contain at least one step"


def test_agent_plan_requires_a_goal() -> None:
    agent_id = _agent(_project())
    assert client.post(f"/agents/{agent_id}/plan", json={"goal": "   "}).status_code == 400


# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------


def _schedule(agent_id: str) -> str:
    created = client.post(
        "/scheduler/schedule",
        json={
            "agent_id": agent_id,
            "goal": _unique("Integration goal"),
            "priority": "normal",
            "available_executors": ["local"],
            "execution_policy": {},
        },
    )
    assert created.status_code == 200
    return created.json()["schedule_id"]


def test_scheduler_lifecycle_through_the_api() -> None:
    agent_id = _agent(_project())
    schedule_id = _schedule(agent_id)

    fetched = client.get(f"/scheduler/{schedule_id}")
    assert fetched.status_code == 200
    assert fetched.json()["agent_id"] == agent_id

    queue = client.get(f"/scheduler/{schedule_id}/queue")
    assert queue.status_code == 200
    assert len(queue.json()) >= 1

    assert client.post(f"/scheduler/{schedule_id}/pause", json={}).json()["status"] == "ok"
    assert client.post(f"/scheduler/{schedule_id}/resume", json={}).json()["status"] == "ok"
    assert client.post(f"/scheduler/{schedule_id}/cancel", json={}).json()["status"] == "ok"


def test_scheduler_404s_on_missing_schedule() -> None:
    missing = _unique("schedule-missing")
    assert client.get(f"/scheduler/{missing}").status_code == 404
    assert client.post(f"/scheduler/{missing}/pause", json={}).status_code == 404
    assert client.post(f"/runtime/schedule/{missing}/start").status_code == 404


def test_scheduler_rejects_unknown_agent() -> None:
    response = client.post(
        "/scheduler/schedule",
        json={"agent_id": "agent-missing", "goal": "x", "priority": "normal"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Runtime lifecycle
# ---------------------------------------------------------------------------


def test_runtime_listing_endpoints() -> None:
    for path in ("/runtime", "/runtime/running", "/runtime/history"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert isinstance(response.json(), list)


def test_runtime_execution_detail_and_cancel() -> None:
    agent_id = _agent(_project(), capabilities=["image"])
    schedule_id = _schedule(agent_id)

    started = client.post(f"/runtime/schedule/{schedule_id}/start")
    assert started.status_code == 200
    executions = started.json()
    assert executions

    execution_id = executions[0]["execution_id"]
    detail = client.get(f"/runtime/{execution_id}")
    assert detail.status_code == 200
    assert detail.json()["execution_id"] == execution_id

    cancelled = client.post(f"/runtime/{execution_id}/cancel")
    assert cancelled.status_code == 200


def test_runtime_404s_on_missing_execution() -> None:
    missing = _unique("execution-missing")
    assert client.get(f"/runtime/{missing}").status_code == 404
    assert client.post(f"/runtime/{missing}/cancel").status_code == 404
    assert client.post(f"/runtime/{missing}/retry").status_code == 404


# ---------------------------------------------------------------------------
# Multi-agent teams
# ---------------------------------------------------------------------------


def test_agent_team_lifecycle() -> None:
    project_id = _project()
    first = _agent(project_id)
    second = _agent(project_id)

    created = client.post(
        "/agents/team",
        json={
            "name": _unique("Team"),
            "project_id": project_id,
            "assignments": [
                {
                    "agent_id": first,
                    "role": "research",
                    "title": "Gather sources",
                    "action": "text.generate",
                    "payload": {"prompt": "research"},
                },
                {
                    "agent_id": second,
                    "role": "writer",
                    "title": "Draft copy",
                    "action": "text.generate",
                    "payload": {"prompt": "draft"},
                },
            ],
        },
    )
    assert created.status_code == 200
    team_id = created.json()["id"]

    assert client.get(f"/agents/team/{team_id}").status_code == 200
    assert isinstance(client.get(f"/agents/team/{team_id}/messages").json(), list)

    status = client.get(f"/agents/team/{team_id}/status")
    assert status.status_code == 200

    assert client.post(f"/agents/team/{team_id}/cancel").status_code == 200


def test_agent_team_404s() -> None:
    missing = _unique("team-missing")
    assert client.get(f"/agents/team/{missing}").status_code == 404
    assert client.get(f"/agents/team/{missing}/status").status_code == 404
    assert client.post(f"/agents/team/{missing}/cancel").status_code == 404


# ---------------------------------------------------------------------------
# Knowledge graph
# ---------------------------------------------------------------------------


def test_graph_endpoints_for_a_project() -> None:
    project_id = _project()
    client.post("/images/generate", json={"project_id": project_id, "prompt": _unique("graph")})

    graph = client.get(f"/graph/project/{project_id}")
    assert graph.status_code == 200
    assert "graph" in graph.json()
    assert "snapshot" in graph.json()

    context = client.get(f"/graph/context/{project_id}")
    assert context.status_code == 200
    assert "graph" in context.json()

    nodes = graph.json()["graph"]["nodes"]
    if nodes:
        node_id = nodes[0]["id"]
        assert client.get(f"/graph/node/{node_id}").status_code == 200
        assert isinstance(client.get(f"/graph/node/{node_id}/neighbors").json(), list)
        assert isinstance(client.get(f"/graph/history/{node_id}").json(), list)


def test_graph_path_between_unrelated_nodes_is_empty() -> None:
    response = client.get("/graph/path", params={"start": "node-a", "end": "node-b"})
    assert response.status_code == 200
    assert response.json()["path"] == []


def test_graph_node_404() -> None:
    assert client.get(f"/graph/node/{_unique('node-missing')}").status_code == 404


def test_graph_lineage_for_an_asset() -> None:
    project_id = _project()
    generated = client.post(
        "/images/generate", json={"project_id": project_id, "prompt": _unique("lineage")}
    )
    asset_id = generated.json()["image"]["id"]

    lineage = client.get(f"/graph/lineage/{asset_id}")
    assert lineage.status_code == 200
    assert "nodes" in lineage.json()


# ---------------------------------------------------------------------------
# Chat and research
# ---------------------------------------------------------------------------


def test_chat_conversation_and_message_flow() -> None:
    project_id = _project()
    conversation = client.post(
        "/chat/conversations", json={"project_id": project_id, "title": _unique("Chat")}
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    message = client.post(
        "/chat/message",
        json={
            "conversation_id": conversation_id,
            "role": "user",
            "content": "Summarise the launch plan",
        },
    )
    assert message.status_code == 200

    listed = client.get("/chat/conversations", params={"project_id": project_id})
    assert conversation_id in {c["id"] for c in listed.json()}

    fetched = client.get(f"/chat/conversation/{conversation_id}")
    assert fetched.status_code == 200

    assert client.delete(f"/chat/conversation/{conversation_id}").status_code == 200


def test_chat_404s() -> None:
    missing = _unique("conversation-missing")
    assert client.get(f"/chat/conversation/{missing}").status_code == 404
    assert (
        client.post(
            "/chat/message",
            json={"conversation_id": missing, "role": "user", "content": "x"},
        ).status_code
        == 404
    )


def test_research_session_lifecycle() -> None:
    project_id = _project()
    session = client.post(
        "/research/session",
        json={
            "project_id": project_id,
            "title": _unique("Research"),
            "question": "What changed this quarter?",
        },
    )
    assert session.status_code == 200
    session_id = session.json()["id"]

    assert client.get(f"/research/session/{session_id}").status_code == 200
    assert session_id in {
        s["id"] for s in client.get("/research/session", params={"project_id": project_id}).json()
    }

    searched = client.post(
        "/research/search", json={"session_id": session_id, "query": "quarterly change"}
    )
    assert searched.status_code == 200
    assert "sources" in searched.json()

    summarised = client.post(
        "/research/summarize", json={"session_id": session_id, "prompt": "summarise"}
    )
    assert summarised.status_code == 200
    assert "asset" in summarised.json()

    graph = client.get(f"/research/graph/{project_id}")
    assert graph.status_code == 200


def test_research_404s() -> None:
    missing = _unique("session-missing")
    assert client.get(f"/research/session/{missing}").status_code == 404
    assert (
        client.post("/research/search", json={"session_id": missing, "query": "x"}).status_code
        == 404
    )


# ---------------------------------------------------------------------------
# Capability, registry and platform surfaces
# ---------------------------------------------------------------------------


def test_platform_listing_endpoints_are_available() -> None:
    for path in (
        "/health",
        "/projects",
        "/assets",
        "/runs",
        "/activities",
        "/notifications",
        "/capabilities",
        "/studios",
        "/commands",
        "/workflows",
    ):
        response = client.get(path)
        assert response.status_code == 200, path


def test_created_project_is_listed() -> None:
    project_id = _project()
    assert any(p["id"] == project_id for p in client.get("/projects").json())


def test_memory_kind_must_be_recognised() -> None:
    """An unrecognised memory kind is a client error, not a silent accept.

    A real asset is used so the 400 comes from kind validation rather than from
    the asset lookup 404ing first.
    """
    project_id = _project()
    agent_id = _agent(project_id)
    asset_id = client.post(
        "/images/generate", json={"project_id": project_id, "prompt": _unique("kind")}
    ).json()["image"]["id"]

    response = client.post(
        f"/agents/{agent_id}/memory", json={"kind": "not-a-kind", "asset_id": asset_id}
    )
    assert response.status_code == 400


class TestTheCatalogueMatchesReality:
    """Two defects the production action centre made visible.

    An action list is only read while every item on it is true. One wrong entry
    teaches people to skim it, and the next real blocker is skimmed too.
    """

    def test_a_deployment_configured_root_is_connected_not_pending(
            self, monkeypatch, tmp_path) -> None:
        """`local` asked to be connected on a deployment that had been
        publishing to that directory for weeks.

        A filesystem root is how a deployment was installed, not a per-tenant
        secret somebody stores through the Credential Centre.
        """
        from atlas_kernel.integrations.registry import BY_ID, IntegrationStatus
        from atlas_kernel.publication.connections import ConnectionStore

        store = ConnectionStore()
        monkeypatch.setenv("QEVIK_SITES_ROOT", str(tmp_path))
        assert BY_ID["local"].status(store, tenant="qevik") is (
            IntegrationStatus.CONNECTED)

        # Not vacuous: a root that does not exist is genuinely pending.
        monkeypatch.setenv("QEVIK_SITES_ROOT", str(tmp_path / "absent"))
        assert BY_ID["local"].status(store, tenant="qevik") is (
            IntegrationStatus.PENDING_CREDENTIAL)

    def test_the_default_root_counts_when_no_variable_is_set(
            self, monkeypatch, tmp_path) -> None:
        """Production has never set `QEVIK_SITES_ROOT`. It publishes to the
        documented default, and the catalogue must agree with the publisher
        rather than with whether somebody typed a setting."""
        from atlas_kernel.integrations.registry import BY_ID, IntegrationStatus
        from atlas_kernel.mission import toolrunner
        from atlas_kernel.publication.connections import ConnectionStore

        monkeypatch.delenv("QEVIK_SITES_ROOT", raising=False)
        monkeypatch.setattr(toolrunner, "DEFAULT_SITES_ROOT", str(tmp_path))
        assert BY_ID["local"].status(ConnectionStore(), tenant="qevik") is (
            IntegrationStatus.CONNECTED)

    def test_google_places_is_in_the_catalogue(self) -> None:
        """It has working, cost-capped code and was absent from this list, so
        the action centre could not ask for the one key that turns discovery
        into a workable prospect list."""
        from atlas_kernel.integrations.registry import BY_ID

        places = BY_ID["google-places"]
        assert places.credential == "QEVIK_GOOGLE_PLACES_API_KEY"
        assert places.adapter_ready is True
        assert places.blocks, "an integration that blocks nothing cannot be justified"
        assert places.setup_url, "a request with no route to satisfying it"

    def test_the_credential_name_matches_what_the_code_reads(self) -> None:
        """A catalogue entry naming a variable nothing reads is a request that
        cannot be satisfied."""
        from pathlib import Path

        import atlas_kernel.opportunity.sources.google_places as source
        from atlas_kernel.integrations.registry import BY_ID

        text = Path(source.__file__).read_text(encoding="utf-8")
        assert BY_ID["google-places"].credential in text

    def test_every_ready_integration_names_something_it_blocks(self) -> None:
        """The catalogue's own rule, asserted rather than trusted."""
        from atlas_kernel.integrations.registry import INTEGRATIONS

        for integration in INTEGRATIONS:
            if integration.adapter_ready:
                assert integration.blocks, integration.id
