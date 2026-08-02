from __future__ import annotations

from .plan_models import PlanStep, StepCostEstimate


class PlannerCostEstimator:
    """Predict-only planner estimator. Never executes providers or workflows."""

    def estimate_step(self, step: PlanStep) -> StepCostEstimate:
        base_tokens = max(200, len(step.description) * 12)
        capability_factor = 1.0
        provider_class = "planner-simulated-llm"
        gpu_seconds = 0

        normalized = step.capability.lower()
        if "image" in normalized or "video" in normalized:
            capability_factor = 1.8
            provider_class = "planner-simulated-gpu"
            gpu_seconds = max(30, int(step.estimated_time_seconds * 0.7))
        elif "research" in normalized:
            capability_factor = 1.2
            provider_class = "planner-simulated-search"
        elif "review" in normalized:
            capability_factor = 0.9
            provider_class = "planner-simulated-review"

        tokens = int(base_tokens * capability_factor)
        latency_seconds = max(5, step.estimated_time_seconds)
        overall_cost_usd = round((tokens / 1000.0) * 0.004 + (gpu_seconds * 0.0025), 4)

        return StepCostEstimate(
            tokens=tokens,
            gpu_seconds=gpu_seconds,
            provider_class=provider_class,
            latency_seconds=latency_seconds,
            overall_cost_usd=overall_cost_usd,
        )
