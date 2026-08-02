from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .cost_estimator import PlannerCostEstimator
from .plan_models import ExecutionPlan, PlanStep, PlannerContext


@dataclass
class PlannerRequest:
    goal: str
    agent_id: str
    project_id: str | None = None
    workspace_id: str | None = None
    workspace_intelligence: dict[str, Any] | None = None
    capabilities: list[str] | None = None


class AgentPlanner:
    """Goal -> plan translator. Never executes workflows or providers."""

    def __init__(self, estimator: PlannerCostEstimator | None = None) -> None:
        self.estimator = estimator or PlannerCostEstimator()

    def generate_plan(self, context: PlannerContext) -> ExecutionPlan:
        steps = self._build_steps(context)

        dependencies: list[dict[str, str]] = []
        for step in steps:
            for dep in step.dependencies:
                dependencies.append({"from": dep, "to": step.id})

        for idx, step in enumerate(steps):
            estimate = self.estimator.estimate_step(step)
            steps[idx] = step.model_copy(
                update={
                    "estimate": estimate,
                    "estimated_cost_usd": estimate.overall_cost_usd,
                    "estimated_time_seconds": estimate.latency_seconds,
                }
            )

        duration = sum(step.estimated_time_seconds for step in steps)
        cost = round(sum(step.estimated_cost_usd for step in steps), 4)
        capabilities_required = sorted(set(step.capability for step in steps))
        assets_required = [str(asset.get("id", "")) for asset in context.assets[:8] if asset.get("id")]
        expected_outputs = [step.expected_output for step in steps]
        review_required = any(step.review_required for step in steps)

        confidence = self._calculate_confidence(context, steps)

        return ExecutionPlan(
            goal=context.goal,
            confidence=confidence,
            estimated_duration_seconds=duration,
            estimated_cost_usd=cost,
            steps=steps,
            dependencies=dependencies,
            capabilities_required=capabilities_required,
            assets_required=assets_required,
            expected_outputs=expected_outputs,
            review_required=review_required,
            context_snapshot={
                "project_summary": context.project_summary,
                "running_jobs": len(context.running_jobs),
                "open_workflows": len(context.open_workflows),
                "research_items": len(context.research),
                "reviews": len(context.reviews),
                "chats": len(context.chats),
            },
        )

    def _build_steps(self, context: PlannerContext) -> list[PlanStep]:
        cap_order = context.capabilities or ["research", "workflow", "review"]

        base_steps: list[PlanStep] = []
        previous_id: str | None = None
        for idx, capability in enumerate(cap_order[:5]):
            normalized = capability.strip() or f"capability-{idx + 1}"
            review_required = "review" in normalized.lower() or idx == len(cap_order[:5]) - 1
            action = self._action_for_capability(normalized)
            step = PlanStep(
                description=f"{normalized}: advance goal '{context.goal}'",
                capability=normalized,
                action=action,
                payload=self._payload_for_action(action, context.goal, normalized),
                expected_output=f"{normalized}-output-{idx + 1}",
                dependencies=[previous_id] if previous_id else [],
                estimated_time_seconds=30 + (idx * 20),
                review_required=review_required,
            )
            base_steps.append(step)
            previous_id = step.id

        if not base_steps:
            base_steps.append(
                PlanStep(
                    description=f"Draft execution strategy for goal '{context.goal}'",
                    capability="planning",
                    action="text.generate",
                    payload=self._payload_for_action("text.generate", context.goal, "planning"),
                    expected_output="execution-strategy",
                    estimated_time_seconds=45,
                    review_required=True,
                )
            )

        return base_steps

    def _action_for_capability(self, capability: str) -> str:
        normalized = capability.lower()
        if "image" in normalized or "media" in normalized:
            return "image.generate"
        if "code" in normalized or "build" in normalized:
            return "code.generate"
        return "text.generate"

    def _payload_for_action(self, action: str, goal: str, capability: str) -> dict[str, Any]:
        prompt = f"{capability}: advance goal '{goal}'"
        if action == "code.generate":
            return {"prompt": prompt, "language": "python"}
        return {"prompt": prompt}

    def _calculate_confidence(self, context: PlannerContext, steps: list[PlanStep]) -> float:
        score = 0.45
        if context.assets:
            score += 0.1
        if context.research:
            score += 0.1
        if context.reviews:
            score += 0.05
        if context.chats:
            score += 0.05
        if context.open_workflows:
            score += 0.05
        if len(context.capabilities) >= 2:
            score += 0.1
        if len(steps) >= 3:
            score += 0.05
        return max(0.0, min(0.99, round(score, 3)))
