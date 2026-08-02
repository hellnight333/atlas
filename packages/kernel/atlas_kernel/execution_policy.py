from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .event_bus import EventBus, ExecutionDecisionCreated, ExecutionPolicyEvaluated
from .models import CapabilityRequest, ExecutionDecision, RuntimeContext
from .registry import Registry
from .repository import AtlasRepository


class PolicyScorer(ABC):
    @abstractmethod
    def score(
        self,
        capability_request: CapabilityRequest,
        recipe: dict[str, Any],
        executor: dict[str, Any],
        provider: dict[str, Any],
        model: dict[str, Any],
        runtime_context: RuntimeContext,
        workspace_preferences: dict[str, Any],
        project_preferences: dict[str, Any],
    ) -> tuple[int, dict[str, Any]]:
        pass


class WeightedPolicyScorer(PolicyScorer):
    def score(
        self,
        capability_request: CapabilityRequest,
        recipe: dict[str, Any],
        executor: dict[str, Any],
        provider: dict[str, Any],
        model: dict[str, Any],
        runtime_context: RuntimeContext,
        workspace_preferences: dict[str, Any],
        project_preferences: dict[str, Any],
    ) -> tuple[int, dict[str, Any]]:
        requirements = capability_request.requirements
        score = 0
        breakdown: dict[str, Any] = {}

        offline_only = bool(requirements.get("offline_only", False))
        cloud_allowed = bool(requirements.get("cloud_allowed", True))
        preferred_quality = str(requirements.get("preferred_quality", "")).lower()
        preferred_speed = str(requirements.get("preferred_speed", "")).lower()
        minimum_vram = int(requirements.get("required_vram_gb", 0))
        max_cost = requirements.get("max_cost")
        private_required = bool(requirements.get("private_execution_required", False))
        commercial_required = bool(requirements.get("commercial_use_required", False))
        streaming_required = bool(requirements.get("streaming_required", False))
        latency_target = requirements.get("latency_target_ms")

        executor_is_local = bool(executor.get("is_local", True))
        provider_is_local = bool(provider.get("is_local", False))
        provider_cost = float(provider.get("cost_per_unit", 0.0))
        provider_latency = int(provider.get("p50_latency_ms", 0))
        provider_quality = float(provider.get("quality_score", 0.0))
        provider_vram = int(provider.get("vram_gb", 0))
        model_latency = int(model.get("latency_ms", 0))
        model_cost = float(model.get("cost_per_unit", 0.0))
        model_quality = float(model.get("quality_score", 0.0))

        if offline_only:
            local_bonus = 100 if executor_is_local and provider_is_local else -10_000
            score += local_bonus
            breakdown["offline_only"] = local_bonus

        if not cloud_allowed and not provider_is_local:
            score -= 10_000
            breakdown["cloud_allowed"] = -10_000

        if runtime_context.offline_mode and not provider_is_local:
            score -= 10_000
            breakdown["runtime_offline_mode"] = -10_000

        if minimum_vram:
            vram_delta = min(provider_vram, runtime_context.available_gpu_vram_gb) - minimum_vram
            vram_score = vram_delta * 5 if vram_delta >= 0 else -10_000
            score += vram_score
            breakdown["vram"] = vram_score

        if max_cost is not None:
            total_cost = provider_cost + model_cost
            cost_score = 50 if total_cost <= float(max_cost) else -10_000
            score += cost_score
            breakdown["max_cost"] = cost_score
        else:
            cost_score = int(max(0.0, 100.0 - ((provider_cost + model_cost) * 100)))
            score += cost_score
            breakdown["cost"] = cost_score

        latency_value = provider_latency + model_latency
        if latency_target is not None:
            latency_score = 75 if latency_value <= int(latency_target) else -500
        else:
            latency_score = max(0, 200 - latency_value)
        score += latency_score
        breakdown["latency"] = latency_score

        quality_score = int((provider_quality + model_quality) * 50)
        if preferred_quality in {"high", "photorealistic", "best"}:
            quality_score += 50
        score += quality_score
        breakdown["quality"] = quality_score

        speed_score = 0
        if preferred_speed in {"fast", "draft", "low-latency"}:
            speed_score = max(0, 150 - latency_value)
        score += speed_score
        breakdown["speed"] = speed_score

        if commercial_required:
            commercial_score = 25 if bool(model.get("commercial_use", True)) else -10_000
            score += commercial_score
            breakdown["commercial_use"] = commercial_score

        if private_required:
            private_score = (
                25 if bool(model.get("private_execution", True)) and provider_is_local else -10_000
            )
            score += private_score
            breakdown["private_execution"] = private_score

        if streaming_required:
            streaming_score = 20 if bool(model.get("supports_streaming", False)) else -100
            score += streaming_score
            breakdown["streaming"] = streaming_score

        workspace_executor = workspace_preferences.get("preferred_executor_id")
        project_executor = project_preferences.get("preferred_executor_id")
        if workspace_executor and workspace_executor == executor.get("id"):
            score += 15
            breakdown["workspace_preference"] = 15
        if project_executor and project_executor == executor.get("id"):
            score += 15
            breakdown["project_preference"] = 15

        recipe_priority = int(recipe.get("metadata", {}).get("priority", 0))
        score += recipe_priority
        breakdown["recipe_priority"] = recipe_priority

        return score, breakdown


class ExecutionPolicyEngine:
    def __init__(
        self,
        registry: Registry,
        repository: AtlasRepository,
        event_bus: EventBus,
        scorer: PolicyScorer | None = None,
    ) -> None:
        self.registry = registry
        self.repository = repository
        self.event_bus = event_bus
        self.scorer = scorer or WeightedPolicyScorer()

    def evaluate(
        self,
        capability_request: CapabilityRequest,
        runtime_context: RuntimeContext | None = None,
        workspace_preferences: dict[str, Any] | None = None,
        project_preferences: dict[str, Any] | None = None,
    ) -> ExecutionDecision:
        runtime_context = runtime_context or RuntimeContext()
        workspace_preferences = workspace_preferences or {}
        project_preferences = project_preferences or {}

        capability = self.registry.get_capability(capability_request.capability_id)
        if capability is None:
            raise ValueError(f"Unknown capability_id: {capability_request.capability_id}")

        recipes = self.registry.list_capability_recipes(capability_request.capability_id)
        if capability_request.recipe_id is not None:
            recipes = [recipe for recipe in recipes if recipe.id == capability_request.recipe_id]
        if not recipes:
            recipes = [
                type(
                    "RecipeFallback",
                    (),
                    {
                        "id": None,
                        "capability_id": capability.id,
                        "name": "default",
                        "metadata": {},
                        "parameters": {},
                    },
                )()
            ]

        executor_specs = self.registry.list_compatible_executor_specs(capability.id)
        provider_specs = self.registry.list_compatible_providers(capability.id)

        candidates: list[tuple[int, tuple[str, str, str, str, str], ExecutionDecision]] = []
        for recipe in sorted(recipes, key=lambda item: (item.id or "", item.name)):
            recipe_supported = (
                recipe.metadata.get("supported_executor_kinds", [])
                if hasattr(recipe, "metadata")
                else []
            )
            for executor in sorted(executor_specs, key=lambda item: item.id):
                if (
                    recipe_supported
                    and executor.id not in recipe_supported
                    and executor.kind not in recipe_supported
                ):
                    continue
                executor_health = runtime_context.executor_health.get(executor.id, executor.health)
                if executor_health != "healthy":
                    continue
                for provider in sorted(provider_specs, key=lambda item: item.name):
                    provider_available = runtime_context.provider_availability.get(
                        provider.name, True
                    )
                    if not provider_available:
                        continue
                    models = self.registry.list_compatible_models(
                        capability.id, provider_id=provider.name
                    )
                    if not models:
                        models = [
                            type(
                                "ModelFallback",
                                (),
                                {
                                    "id": None,
                                    "provider_id": provider.name,
                                    "quality_score": provider.quality_score,
                                    "latency_ms": 0,
                                    "cost_per_unit": 0.0,
                                    "supports_streaming": False,
                                    "commercial_use": True,
                                    "private_execution": provider.is_local,
                                    "metadata": {},
                                },
                            )()
                        ]
                    for model in sorted(models, key=lambda item: item.id or ""):
                        score, breakdown = self.scorer.score(
                            capability_request=capability_request,
                            recipe={
                                "id": getattr(recipe, "id", None),
                                "metadata": getattr(recipe, "metadata", {}),
                            },
                            executor=executor.model_dump(),
                            provider=provider.model_dump(),
                            model={
                                "id": getattr(model, "id", None),
                                "quality_score": getattr(model, "quality_score", 0.0),
                                "latency_ms": getattr(model, "latency_ms", 0),
                                "cost_per_unit": getattr(model, "cost_per_unit", 0.0),
                                "supports_streaming": getattr(model, "supports_streaming", False),
                                "commercial_use": getattr(model, "commercial_use", True),
                                "private_execution": getattr(model, "private_execution", True),
                            },
                            runtime_context=runtime_context,
                            workspace_preferences=workspace_preferences,
                            project_preferences=project_preferences,
                        )
                        if score <= -10_000:
                            continue
                        reason = {
                            "score_breakdown": breakdown,
                            "considerations": [
                                f"capability:{capability.id}",
                                f"executor:{executor.id}",
                                f"provider:{provider.name}",
                                f"model:{getattr(model, 'id', None) or 'none'}",
                                f"recipe:{getattr(recipe, 'id', None) or 'default'}",
                            ],
                        }
                        confidence = max(0.0, min(1.0, score / 300.0))
                        decision = ExecutionDecision(
                            capability_id=capability.id,
                            recipe_id=getattr(recipe, "id", None),
                            executor_id=executor.id,
                            provider_id=provider.name,
                            model_id=getattr(model, "id", None),
                            reason=reason,
                            confidence=confidence,
                        )
                        tie_break = (
                            capability.id,
                            getattr(recipe, "id", None) or "",
                            executor.id,
                            provider.name,
                            getattr(model, "id", None) or "",
                        )
                        candidates.append((score, tie_break, decision))

        if not candidates:
            raise ValueError(f"No execution decision available for capability_id: {capability.id}")

        candidates.sort(key=lambda item: (-item[0], item[1]))
        decision = candidates[0][2]
        self.repository.create_execution_decision(decision)
        self.event_bus.publish(
            ExecutionPolicyEvaluated(
                decision_id=decision.decision_id,
                capability_id=decision.capability_id,
                executor_id=decision.executor_id,
                provider_id=decision.provider_id,
            )
        )
        self.event_bus.publish(
            ExecutionDecisionCreated(
                decision_id=decision.decision_id,
                capability_id=decision.capability_id,
                executor_id=decision.executor_id,
                provider_id=decision.provider_id,
            )
        )
        return decision

    def get_decision(self, decision_id: str) -> ExecutionDecision | None:
        return self.repository.get_execution_decision(decision_id)
