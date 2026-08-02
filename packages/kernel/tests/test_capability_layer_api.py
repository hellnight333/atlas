from fastapi.testclient import TestClient

from atlas_kernel.api import app, event_bus
from atlas_kernel.event_bus import CapabilityRegistered, CapabilityUpdated, RecipeRegistered

client = TestClient(app)


def test_capability_registration_and_lookup_endpoints():
    registered: list[CapabilityRegistered] = []
    updated: list[CapabilityUpdated] = []
    event_bus.subscribe(CapabilityRegistered, lambda event: registered.append(event))
    event_bus.subscribe(CapabilityUpdated, lambda event: updated.append(event))

    response = client.post(
        "/capabilities",
        json={
            "id": "cap-image-editing",
            "name": "Image Editing",
            "description": "Edit existing images.",
            "version": "1.0.0",
            "supported_provider_kinds": ["image"],
            "supported_executor_kinds": ["local", "cloud"],
            "metadata": {"domain": "image"},
        },
    )
    assert response.status_code == 200
    assert response.json()["id"] == "cap-image-editing"

    response_update = client.post(
        "/capabilities",
        json={
            "id": "cap-image-editing",
            "name": "Image Editing",
            "description": "Edit and refine existing images.",
            "version": "1.0.1",
            "supported_provider_kinds": ["image"],
            "supported_executor_kinds": ["local", "cloud"],
            "metadata": {"domain": "image"},
        },
    )
    assert response_update.status_code == 200

    lookup = client.get("/capabilities/cap-image-editing")
    assert lookup.status_code == 200
    assert lookup.json()["version"] == "1.0.1"

    listing = client.get("/capabilities")
    assert listing.status_code == 200
    assert any(item["id"] == "cap-image-editing" for item in listing.json())

    assert any(event.capability_id == "cap-image-editing" for event in registered)
    assert any(event.capability_id == "cap-image-editing" for event in updated)


def test_recipe_registration_and_compatibility_endpoints():
    recipe_events: list[RecipeRegistered] = []
    event_bus.subscribe(RecipeRegistered, lambda event: recipe_events.append(event))

    capability_id = "cap-video-generation"
    create_capability = client.post(
        "/capabilities",
        json={
            "id": capability_id,
            "name": "Video Generation",
            "description": "Generate short video clips.",
            "version": "1.0.0",
            "supported_provider_kinds": ["image"],
            "supported_executor_kinds": ["local", "cloud", "remote"],
            "metadata": {"domain": "video"},
        },
    )
    assert create_capability.status_code == 200

    response = client.post(
        "/recipes",
        json={
            "id": "recipe-video-storyboard",
            "capability_id": capability_id,
            "name": "Storyboard",
            "description": "Fast storyboard sequence.",
            "version": "1.0.0",
            "profile": "fast",
            "parameters": {"fps": 12},
            "metadata": {"supported_executor_kinds": ["local", "remote"]},
        },
    )
    assert response.status_code == 200
    assert response.json()["capability_id"] == capability_id

    recipes = client.get(f"/capabilities/{capability_id}/recipes")
    assert recipes.status_code == 200
    assert any(item["id"] == "recipe-video-storyboard" for item in recipes.json())

    providers = client.get(f"/capabilities/{capability_id}/providers")
    assert providers.status_code == 200
    assert all(item["kind"] == "image" for item in providers.json())

    executors = client.get(f"/capabilities/{capability_id}/executors")
    assert executors.status_code == 200
    assert executors.json() == ["local", "cloud", "remote"]

    assert any(event.recipe_id == "recipe-video-storyboard" for event in recipe_events)


def test_workflow_provider_agnostic_and_backward_compatible_runs_endpoint():
    response = client.post(
        "/workflows",
        json={
            "name": "provider-agnostic-workflow",
            "description": "Capability based workflow.",
            "studio": "image",
            "default_action": "image.generate",
            "capability_req": {
                "capability_id": "cap-image-generation",
                "requirements": {
                    "max_cost": 2.5,
                    "preferred_quality": "high",
                },
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["capability_req"]["capability_id"] == "cap-image-generation"
    assert "provider_name" not in body
    assert "model" not in body
    assert "executor" not in body

    runs_response = client.get("/runs")
    assert runs_response.status_code == 200
    assert isinstance(runs_response.json(), list)


def test_workflow_creation_rejects_unknown_capability_identifier():
    response = client.post(
        "/workflows",
        json={
            "name": "invalid-capability-workflow",
            "description": "Should fail capability validation.",
            "studio": "image",
            "default_action": "image.generate",
            "capability_req": {
                "capability_id": "cap-does-not-exist",
                "requirements": {"required_vram_gb": 4},
            },
        },
    )
    assert response.status_code == 400
    assert "Unknown capability_id" in response.json()["detail"]


def test_execution_policy_endpoints_evaluate_and_fetch_decision():
    response = client.post(
        "/execution-policy/evaluate",
        json={
            "capability_req": {
                "capability_id": "cap-reasoning",
                "requirements": {
                    "offline_only": True,
                    "required_vram_gb": 0,
                },
            },
            "runtime_context": {
                "available_gpu_vram_gb": 8,
                "provider_availability": {"local-text": True},
                "executor_health": {"local": "healthy"},
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["capability_id"] == "cap-reasoning"
    assert body["provider_id"] == "local-text"
    assert body["executor_id"] == "local"

    fetch = client.get(f"/execution-policy/decision/{body['decision_id']}")
    assert fetch.status_code == 200
    assert fetch.json()["decision_id"] == body["decision_id"]
