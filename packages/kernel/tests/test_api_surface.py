from __future__ import annotations

from fastapi.testclient import TestClient

from atlas_kernel.api import app

client = TestClient(app)


def test_health_and_catalog_endpoints():
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    providers = client.get("/providers")
    assert providers.status_code == 200
    assert any(item["name"] == "local-flux" for item in providers.json())

    actions = client.get("/actions")
    assert actions.status_code == 200
    assert any(item["name"] == "image.generate" for item in actions.json())

    capabilities = client.get("/capabilities")
    assert capabilities.status_code == 200
    assert any(item["id"] == "cap-image-generation" for item in capabilities.json())


def test_workspace_project_run_job_and_asset_endpoints_roundtrip():
    workspace = client.post("/workspaces", json={"name": "ws-a", "description": "workspace"})
    assert workspace.status_code == 200
    workspace_id = workspace.json()["workspace_id"]

    project = client.post(
        "/projects",
        json={"workspace_id": workspace_id, "name": "proj-a", "description": "project"},
    )
    assert project.status_code == 200
    project_id = project.json()["project_id"]

    workflow = client.post(
        "/workflows",
        json={
            "project_id": project_id,
            "name": "workflow-a",
            "description": "workflow",
            "studio": "image",
            "default_action": "image.generate",
            "capability_req": {
                "capability_id": "cap-image-generation",
                "requirements": {"required_vram_gb": 24},
            },
        },
    )
    assert workflow.status_code == 200
    workflow_id = workflow.json()["workflow_id"]

    run = client.post(
        "/runs",
        json={
            "title": "run-a",
            "description": "run",
            "studio": "image",
            "workspace_id": workspace_id,
            "project_id": project_id,
            "workflow_id": workflow_id,
        },
    )
    assert run.status_code == 200
    run_id = run.json()["run_id"]

    run_details = client.get(f"/runs/{run_id}")
    assert run_details.status_code == 200
    assert run_details.json()["id"] == run_id
    assert run_details.json()["job_count"] >= 1

    jobs = client.get(f"/runs/{run_id}/jobs")
    assert jobs.status_code == 200
    assert len(jobs.json()) >= 1

    created_asset = client.post(
        "/assets",
        json={
            "type": "image",
            "project_id": project_id,
            "workflow_id": workflow_id,
            "run_id": run_id,
            "uri": "atlas://manual/asset",
            "metadata": {"source": "test"},
        },
    )
    assert created_asset.status_code == 200
    asset_id = created_asset.json()["id"]

    assets_by_project = client.get(f"/assets?project_id={project_id}")
    assert assets_by_project.status_code == 200
    assert any(item["id"] == asset_id for item in assets_by_project.json())

    assets_by_run = client.get(f"/assets?run_id={run_id}")
    assert assets_by_run.status_code == 200
    assert any(item["id"] == asset_id for item in assets_by_run.json())

    fetched_asset = client.get(f"/assets/{asset_id}")
    assert fetched_asset.status_code == 200
    assert fetched_asset.json()["id"] == asset_id

    project_assets = client.get(f"/projects/{project_id}/assets")
    assert project_assets.status_code == 200
    assert any(item["id"] == asset_id for item in project_assets.json())


def test_asset_import_and_delete_roundtrip():
    workspace = client.post("/workspaces", json={"name": "ws-import", "description": "workspace"})
    project = client.post(
        "/projects",
        json={
            "workspace_id": workspace.json()["workspace_id"],
            "name": "proj-import",
            "description": "project",
        },
    )
    project_id = project.json()["project_id"]

    imported = client.post(
        "/assets/import",
        data={"project_id": project_id, "tags": '["desktop-import"]'},
        files={"file": ("notes.txt", b"hello atlas", "text/plain")},
    )
    assert imported.status_code == 200
    imported_asset = imported.json()
    assert imported_asset["project_id"] == project_id
    assert imported_asset["version"] == 1
    assert imported_asset["metadata"]["original_filename"] == "notes.txt"

    fetched = client.get(f"/assets/{imported_asset['id']}")
    assert fetched.status_code == 200

    delete_response = client.delete(f"/assets/{imported_asset['id']}")
    assert delete_response.status_code == 200
    assert delete_response.json()["status"] == "deleted"

    missing = client.get(f"/assets/{imported_asset['id']}")
    assert missing.status_code == 404


def test_capability_and_recipe_error_branches_and_selection_endpoint():
    missing_capability = client.get("/capabilities/does-not-exist")
    assert missing_capability.status_code == 404

    missing_recipes = client.get("/capabilities/does-not-exist/recipes")
    assert missing_recipes.status_code == 404

    missing_providers = client.get("/capabilities/does-not-exist/providers")
    assert missing_providers.status_code == 404

    missing_executors = client.get("/capabilities/does-not-exist/executors")
    assert missing_executors.status_code == 404

    missing_recipe_capability = client.post(
        "/recipes",
        json={
            "id": "recipe-missing-cap",
            "capability_id": "cap-missing",
            "name": "missing",
        },
    )
    assert missing_recipe_capability.status_code == 404

    recipe = client.post(
        "/recipes",
        json={
            "id": "recipe-reasoning-low-latency",
            "capability_id": "cap-reasoning",
            "name": "Low Latency",
            "profile": "fast",
            "metadata": {"supported_executor_kinds": ["local"]},
        },
    )
    assert recipe.status_code == 200

    selected = client.post(
        "/capabilities/cap-reasoning/recipes/recipe-reasoning-low-latency/select",
        json={"run_id": "run-select"},
    )
    assert selected.status_code == 200
    assert selected.json()["status"] == "selected"

    missing_recipe = client.post(
        "/capabilities/cap-reasoning/recipes/recipe-does-not-exist/select",
        json={"run_id": "run-select"},
    )
    assert missing_recipe.status_code == 404


def test_workflow_engine_endpoints_and_error_branches():
    definition = {
        "id": "wf-api-surface",
        "name": "wf api surface",
        "project_id": "project-unassigned",
        "nodes": [
            {
                "id": "A",
                "action": "text.generate",
                "payload": {"prompt": "hello"},
                "capability_req": {
                    "capability_id": "cap-reasoning",
                    "requirements": {"required_vram_gb": 0},
                },
            }
        ],
    }

    created = client.post("/workflow-engine/workflows", json=definition)
    assert created.status_code == 200

    validated = client.post("/workflow-engine/workflows/validate", json=definition)
    assert validated.status_code == 200
    assert validated.json()["valid"] is True

    run = client.post("/runs", json={"title": "wf-run", "description": "wf", "studio": "text"})
    assert run.status_code == 200
    run_id = run.json()["run_id"]

    execution = client.post(
        "/workflow-engine/workflows/wf-api-surface/execute",
        json={"run_id": run_id},
    )
    assert execution.status_code == 200
    execution_id = execution.json()["id"]

    plan = client.get(f"/workflow-engine/executions/{execution_id}/plan")
    assert plan.status_code == 200

    paused = client.post(f"/workflow-engine/executions/{execution_id}/pause")
    assert paused.status_code == 200

    resumed = client.post(f"/workflow-engine/executions/{execution_id}/resume")
    assert resumed.status_code == 200

    cancelled = client.post(f"/workflow-engine/executions/{execution_id}/cancel")
    assert cancelled.status_code == 200

    missing_pause = client.post("/workflow-engine/executions/does-not-exist/pause")
    assert missing_pause.status_code == 404

    missing_resume = client.post("/workflow-engine/executions/does-not-exist/resume")
    assert missing_resume.status_code == 404

    missing_cancel = client.post("/workflow-engine/executions/does-not-exist/cancel")
    assert missing_cancel.status_code == 404

    missing_plan = client.get("/workflow-engine/executions/does-not-exist/plan")
    assert missing_plan.status_code == 404

    unsafe_client = TestClient(app, raise_server_exceptions=False)
    missing_execution = unsafe_client.post(
        "/workflow-engine/workflows/does-not-exist/execute",
        json={"run_id": run_id},
    )
    assert missing_execution.status_code == 500


def test_chat_conversation_and_message_roundtrip():
    workspace = client.post("/workspaces", json={"name": "ws-chat", "description": "workspace"})
    project = client.post(
        "/projects",
        json={
            "workspace_id": workspace.json()["workspace_id"],
            "name": "proj-chat",
            "description": "project",
        },
    )
    project_id = project.json()["project_id"]

    conversation = client.post(
        "/chat/conversations",
        json={
            "project_id": project_id,
            "title": "Alpha chat",
            "metadata": {"surface": "chat-studio"},
        },
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]

    sent = client.post(
        "/chat/message",
        json={
            "conversation_id": conversation_id,
            "role": "user",
            "content": "Summarize the project state",
            "tokens": 24,
            "metadata": {"source": "test"},
        },
    )
    assert sent.status_code == 200
    sent_message = sent.json()
    assert sent_message["prompt_asset_id"] is not None
    assert sent_message["response_asset_id"] is not None

    fetched = client.get(f"/chat/conversation/{conversation_id}")
    assert fetched.status_code == 200
    payload = fetched.json()
    assert payload["id"] == conversation_id
    assert len(payload["messages"]) == 2
    assert payload["messages"][0]["role"] == "user"
    assert payload["messages"][1]["role"] == "assistant"
    assert payload["prompt_asset_id"] is not None
    assert payload["response_asset_id"] is not None

    listed = client.get(f"/chat/conversations?project_id={project_id}")
    assert listed.status_code == 200
    assert any(item["id"] == conversation_id for item in listed.json())

    deleted = client.delete(f"/chat/conversation/{conversation_id}")
    assert deleted.status_code == 200

    missing = client.get(f"/chat/conversation/{conversation_id}")
    assert missing.status_code == 404


def test_research_session_search_summary_report_and_graph_roundtrip():
    workspace = client.post("/workspaces", json={"name": "ws-research", "description": "workspace"})
    project = client.post(
        "/projects",
        json={
            "workspace_id": workspace.json()["workspace_id"],
            "name": "proj-research",
            "description": "project",
        },
    )
    project_id = project.json()["project_id"]

    session_record = client.post(
        "/research/session",
        json={
            "project_id": project_id,
            "title": "Research Alpha",
            "question": "What are the main risks?",
        },
    )
    assert session_record.status_code == 200
    session_id = session_record.json()["id"]

    listed = client.get(f"/research/session?project_id={project_id}")
    assert listed.status_code == 200
    assert any(item["id"] == session_id for item in listed.json())

    searched = client.post(
        "/research/search",
        json={"session_id": session_id, "query": "atlas risks", "provider": "mock-search"},
    )
    assert searched.status_code == 200
    sources = searched.json()["sources"]
    assert len(sources) == 3

    summarized = client.post(
        "/research/summarize",
        json={
            "session_id": session_id,
            "source_asset_ids": [item["id"] for item in sources],
            "prompt": "Summarize the source set",
        },
    )
    assert summarized.status_code == 200
    finding_asset = summarized.json()["asset"]
    assert finding_asset["metadata"]["kind"] == "finding"

    reported = client.post(
        "/research/report",
        json={"session_id": session_id, "format": "markdown"},
    )
    assert reported.status_code == 200
    assert reported.json()["metadata"]["kind"] == "report"

    graph = client.get(f"/research/graph/{project_id}")
    assert graph.status_code == 200
    assert len(graph.json()["nodes"]) >= 4


def test_review_lifecycle_roundtrip():
    workspace = client.post("/workspaces", json={"name": "ws-review", "description": "workspace"})
    project = client.post(
        "/projects",
        json={
            "workspace_id": workspace.json()["workspace_id"],
            "name": "proj-review",
            "description": "project",
        },
    )
    project_id = project.json()["project_id"]

    base_asset = client.post(
        "/assets",
        json={
            "type": "document",
            "project_id": project_id,
            "uri": "atlas://review/source",
            "metadata": {"kind": "draft", "title": "Draft Document"},
        },
    )
    assert base_asset.status_code == 200
    source_asset_id = base_asset.json()["id"]

    created = client.post(
        "/reviews",
        json={
            "project_id": project_id,
            "title": "Review Alpha",
            "asset_id": source_asset_id,
            "metadata": {"surface": "review-studio"},
        },
    )
    assert created.status_code == 200
    review = created.json()
    review_id = review["id"]
    assert review["status"] == "pending"

    listed = client.get(f"/reviews?project_id={project_id}")
    assert listed.status_code == 200
    assert any(item["id"] == review_id for item in listed.json())

    commented = client.post(
        f"/reviews/{review_id}/comment",
        json={"content": "Looks good overall. Please verify citations."},
    )
    assert commented.status_code == 200
    assert commented.json()["review_id"] == review_id

    approved = client.post(
        f"/reviews/{review_id}/approve",
        json={"asset_id": source_asset_id, "comment": "Approved for publication"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    published = client.post(
        f"/reviews/{review_id}/publish",
        json={"asset_id": source_asset_id, "metadata": {"channel": "docs"}},
    )
    assert published.status_code == 200
    payload = published.json()
    assert payload["status"] == "published"
    assert payload["published_asset_id"] is not None
    assert payload["published_asset"]["parent_asset_id"] == source_asset_id
    assert payload["published_asset"]["version"] == 2

    history = client.get(f"/reviews/{review_id}/history")
    assert history.status_code == 200
    event_types = [item["event_type"] for item in history.json()]
    assert "created" in event_types
    assert "approved" in event_types
    assert "published" in event_types

    def test_workspace_intelligence_endpoints_reflect_project_state():
        workspace = client.post(
            "/workspaces", json={"name": "ws-intel", "description": "workspace"}
        )
        assert workspace.status_code == 200
        workspace_id = workspace.json()["workspace_id"]

        project = client.post(
            "/projects",
            json={"workspace_id": workspace_id, "name": "proj-intel", "description": "project"},
        )
        assert project.status_code == 200
        project_id = project.json()["project_id"]

        conversation = client.post(
            "/chat/conversations",
            json={"project_id": project_id, "title": "Workspace intelligence chat"},
        )
        assert conversation.status_code == 200
        conversation_id = conversation.json()["id"]

        message = client.post(
            "/chat/message",
            json={
                "conversation_id": conversation_id,
                "role": "user",
                "content": "Summarize current plan",
            },
        )
        assert message.status_code == 200

        research_session = client.post(
            "/research/session",
            json={
                "project_id": project_id,
                "title": "Research wave",
                "question": "What should we prioritize?",
            },
        )
        assert research_session.status_code == 200
        session_id = research_session.json()["id"]

        source_search = client.post(
            "/research/search",
            json={
                "session_id": session_id,
                "query": "priority framework",
                "provider": "mock-search",
            },
        )
        assert source_search.status_code == 200

        image = client.post(
            "/images/generate",
            json={
                "project_id": project_id,
                "prompt": "Workspace intelligence visual concept",
                "styles": ["editorial"],
                "resolution": "1024x1024",
            },
        )
        assert image.status_code == 200
        image_id = image.json()["image"]["id"]

        reviews = client.get(f"/reviews?project_id={project_id}")
        assert reviews.status_code == 200
        review_id = reviews.json()[0]["id"]

        approved = client.post(
            f"/reviews/{review_id}/approve",
            json={"asset_id": image_id, "comment": "Approved for publish"},
        )
        assert approved.status_code == 200

        published = client.post(
            f"/reviews/{review_id}/publish",
            json={"asset_id": image_id, "metadata": {"channel": "workspace-dashboard"}},
        )
        assert published.status_code == 200

        context_payload = client.get(f"/workspace/context/{project_id}")
        assert context_payload.status_code == 200
        workspace_context = context_payload.json()["workspace_context"]
        assert workspace_context["project"]["id"] == project_id
        assert len(workspace_context["recent_assets"]) >= 1
        assert isinstance(workspace_context["recommendations"], list)
        assert "open_reviews" in workspace_context["project_summary"]

        recommendations_payload = client.get(f"/workspace/recommendations/{project_id}")
        assert recommendations_payload.status_code == 200
        recommendation_titles = {
            item["title"] for item in recommendations_payload.json()["recommendations"]
        }
        assert "Generate Variant" in recommendation_titles

        recent_payload = client.get(f"/workspace/recent/{project_id}")
        assert recent_payload.status_code == 200
        recent = recent_payload.json()
        assert len(recent["recent_assets"]) >= 1
        assert len(recent["recent_activity"]) >= 1
        assert len(recent["recent_images"]) >= 1

        dashboard_payload = client.get(f"/workspace/dashboard/{project_id}")
        assert dashboard_payload.status_code == 200
        dashboard = dashboard_payload.json()
        assert dashboard["project_summary"]["project"]["id"] == project_id
        assert "project_health" in dashboard
        assert isinstance(dashboard["recent_timeline"], list)
        assert isinstance(dashboard["review_queue"], list)


def test_packaged_desktop_origin_is_allowed_by_cors():
    """The installed app must be able to call its own kernel.

    Tauri serves the frontend from its own scheme, so a packaged Atlas has
    origin ``tauri://localhost`` (``http://tauri.localhost`` on Windows) rather
    than the Vite dev server's ``http://localhost:5173``. RC1 allowed only the
    dev origins, so every request from an installed Atlas was blocked and the
    app opened into an empty workspace with no first-run wizard.

    A browser reports that as "Load failed" with no detail, and the onboarding
    store reads any failure as "setup already done", so nothing anywhere said
    what was wrong. Hence this test.
    """
    for origin in ("tauri://localhost", "http://tauri.localhost"):
        preflight = client.options(
            "/api/onboarding",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        assert preflight.status_code == 200, origin
        assert preflight.headers.get("access-control-allow-origin") == origin

        response = client.get("/api/onboarding", headers={"Origin": origin})
        assert response.headers.get("access-control-allow-origin") == origin, origin
