from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class StepCostEstimate(BaseModel):
    tokens: int = 0
    gpu_seconds: int = 0
    provider_class: str = "planner-simulated"
    latency_seconds: int = 0
    overall_cost_usd: float = 0.0


class PlanStep(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    description: str
    capability: str
    action: str = "text.generate"
    payload: dict[str, Any] = Field(default_factory=dict)
    expected_output: str
    dependencies: list[str] = Field(default_factory=list)
    estimated_cost_usd: float = 0.0
    estimated_time_seconds: int = 0
    review_required: bool = False
    estimate: StepCostEstimate = Field(default_factory=StepCostEstimate)


class PlannerContext(BaseModel):
    goal: str
    workspace_id: str | None = None
    project_id: str | None = None
    agent_id: str
    workspace_intelligence: dict[str, Any] = Field(default_factory=dict)
    capabilities: list[str] = Field(default_factory=list)
    assets: list[dict[str, Any]] = Field(default_factory=list)
    research: list[dict[str, Any]] = Field(default_factory=list)
    chats: list[dict[str, Any]] = Field(default_factory=list)
    reviews: list[dict[str, Any]] = Field(default_factory=list)
    open_workflows: list[dict[str, Any]] = Field(default_factory=list)
    running_jobs: list[dict[str, Any]] = Field(default_factory=list)
    project_summary: dict[str, Any] = Field(default_factory=dict)
    recent_work: list[dict[str, Any]] = Field(default_factory=list)
    knowledge_graph: dict[str, Any] = Field(default_factory=dict)


class ExecutionPlan(BaseModel):
    plan_id: str = Field(default_factory=lambda: str(uuid4()))
    goal: str
    confidence: float = 0.0
    estimated_duration_seconds: int = 0
    estimated_cost_usd: float = 0.0
    steps: list[PlanStep] = Field(default_factory=list)
    dependencies: list[dict[str, str]] = Field(default_factory=list)
    capabilities_required: list[str] = Field(default_factory=list)
    assets_required: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    review_required: bool = True
    context_snapshot: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
