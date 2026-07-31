from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ActionSpec(BaseModel):
    name: str
    description: str
    schema: dict[str, Any] = Field(default_factory=dict)


class ProviderSpec(BaseModel):
    name: str
    kind: str
    is_local: bool = False
    cost_per_unit: float = 0.0
    p50_latency_ms: int = 0
    quality_score: float = 0.0
    vram_gb: int = 0


class RunCreate(BaseModel):
    title: str
    description: str = ""
    studio: str = "core"


class Run(BaseModel):
    id: str
    title: str
    description: str
    studio: str
    status: JobStatus = JobStatus.QUEUED
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Step(BaseModel):
    id: str
    run_id: str
    action: str
    status: StepStatus = StepStatus.PENDING
    payload: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Job(BaseModel):
    id: str
    run_id: str
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)
    status: JobStatus = JobStatus.QUEUED
    attempts: int = 0
    priority: int = 0
    capability_req: dict[str, Any] = Field(default_factory=dict)
    provider_name: str | None = None
    output: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
