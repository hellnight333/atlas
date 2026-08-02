from atlas_kernel.composition_root import create_runtime
from atlas_kernel.event_bus import EventBus, ExecutionDecisionCreated, ExecutionPolicyEvaluated
from atlas_kernel.models import CapabilityRequest, RuntimeContext


def test_execution_policy_is_deterministic_for_identical_inputs():
    runtime = create_runtime()
    policy = runtime.execution_policy
    request = CapabilityRequest(
        capability_id="cap-image-generation",
        requirements={"required_vram_gb": 24, "offline_only": True},
    )
    context = RuntimeContext(
        available_gpu_vram_gb=48,
        provider_availability={"local-flux": True, "local-text": True},
        executor_health={"local": "healthy", "cloud": "healthy"},
    )

    first = policy.evaluate(request, runtime_context=context)
    second = policy.evaluate(request, runtime_context=context)

    assert first.capability_id == second.capability_id
    assert first.recipe_id == second.recipe_id
    assert first.executor_id == second.executor_id
    assert first.provider_id == second.provider_id
    assert first.model_id == second.model_id
    assert first.reason == second.reason
    assert first.confidence == second.confidence


def test_execution_policy_filters_by_offline_requirement_and_selects_local_executor():
    runtime = create_runtime()
    decision = runtime.execution_policy.evaluate(
        CapabilityRequest(
            capability_id="cap-reasoning",
            requirements={"offline_only": True, "required_vram_gb": 0},
        ),
        runtime_context=RuntimeContext(
            available_gpu_vram_gb=48,
            provider_availability={"local-text": True},
            executor_health={"local": "healthy", "cloud": "healthy"},
            cloud_available=True,
        ),
    )

    assert decision.executor_id == "local"
    assert decision.provider_id == "local-text"
    assert decision.model_id == "qwen-local"


def test_execution_policy_honors_requested_recipe_when_compatible():
    runtime = create_runtime()
    decision = runtime.execution_policy.evaluate(
        CapabilityRequest(
            capability_id="cap-image-generation",
            recipe_id="recipe-image-product-photo",
            requirements={"required_vram_gb": 24},
        ),
        runtime_context=RuntimeContext(
            available_gpu_vram_gb=48,
            provider_availability={"local-flux": True},
            executor_health={"local": "healthy"},
        ),
    )

    assert decision.recipe_id == "recipe-image-product-photo"
    assert decision.provider_id == "local-flux"
    assert decision.model_id == "flux-dev"


def test_execution_policy_prefers_project_executor_preference_in_tie():
    runtime = create_runtime()
    decision = runtime.execution_policy.evaluate(
        CapabilityRequest(
            capability_id="cap-image-generation",
            requirements={"required_vram_gb": 24},
        ),
        runtime_context=RuntimeContext(
            available_gpu_vram_gb=48,
            provider_availability={"local-flux": True},
            executor_health={"local": "healthy", "cloud": "healthy"},
        ),
        project_preferences={"preferred_executor_id": "local"},
    )

    assert decision.executor_id == "local"
    assert "score_breakdown" in decision.reason


def test_execution_policy_generates_machine_readable_explanation_and_events():
    bus = EventBus()
    runtime = create_runtime(event_bus=bus)
    evaluated: list[ExecutionPolicyEvaluated] = []
    created: list[ExecutionDecisionCreated] = []
    bus.subscribe(ExecutionPolicyEvaluated, lambda event: evaluated.append(event))
    bus.subscribe(ExecutionDecisionCreated, lambda event: created.append(event))

    decision = runtime.execution_policy.evaluate(
        CapabilityRequest(
            capability_id="cap-code-generation",
            requirements={"streaming_required": True, "required_vram_gb": 0},
        ),
        runtime_context=RuntimeContext(
            available_gpu_vram_gb=8,
            provider_availability={"local-text": True},
            executor_health={"local": "healthy"},
        ),
    )

    assert "score_breakdown" in decision.reason
    assert "considerations" in decision.reason
    assert any(item.startswith("provider:") for item in decision.reason["considerations"])
    assert len(evaluated) == 1
    assert len(created) == 1
    assert evaluated[0].decision_id == decision.decision_id


def test_execution_policy_decision_roundtrip_api_and_repository():
    runtime = create_runtime()
    decision = runtime.execution_policy.evaluate(
        CapabilityRequest(capability_id="cap-reasoning", requirements={"required_vram_gb": 0}),
        runtime_context=RuntimeContext(
            available_gpu_vram_gb=0,
            provider_availability={"local-text": True},
            executor_health={"local": "healthy"},
        ),
    )

    stored = runtime.repository.get_execution_decision(decision.decision_id)
    assert stored is not None
    assert stored.decision_id == decision.decision_id
    assert stored.provider_id == decision.provider_id
