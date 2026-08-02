from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from .plan_models import PlanStep


class SchedulerPriority(StrEnum):
    IMMEDIATE = "immediate"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"
    BACKGROUND = "background"


class QueueEntryStatus(StrEnum):
    QUEUED = "queued"
    READY = "ready"
    BLOCKED = "blocked"
    WAITING_APPROVAL = "waiting_approval"
    PREPARING = "preparing"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class ScheduleQueueEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    plan_step: PlanStep
    status: QueueEntryStatus = QueueEntryStatus.QUEUED
    priority: SchedulerPriority = SchedulerPriority.NORMAL
    dependencies: list[str] = Field(default_factory=list)
    executor_hint: str | None = None
    capability: str
    retry_count: int = 0
    scheduled_time: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_time: datetime | None = None
    completed_time: datetime | None = None


class ResumeToken(BaseModel):
    token: str = Field(default_factory=lambda: str(uuid4()))
    entry_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionSchedule(BaseModel):
    schedule_id: str = Field(default_factory=lambda: str(uuid4()))
    plan_id: str
    agent_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    priority: SchedulerPriority = SchedulerPriority.NORMAL
    estimated_finish_time: datetime | None = None
    queue_entries: list[ScheduleQueueEntry] = Field(default_factory=list)
    blocked_entries: list[str] = Field(default_factory=list)
    parallel_groups: list[list[str]] = Field(default_factory=list)
    resume_tokens: list[ResumeToken] = Field(default_factory=list)
    queue_metadata: dict[str, Any] = Field(default_factory=dict)


class SchedulerRequest(BaseModel):
    plan_id: str
    agent_id: str
    steps: list[PlanStep]
    priority: SchedulerPriority = SchedulerPriority.NORMAL
    workspace_state: dict[str, Any] = Field(default_factory=dict)
    current_jobs: list[dict[str, Any]] = Field(default_factory=list)
    running_workflows: list[dict[str, Any]] = Field(default_factory=list)
    available_executors: list[str] = Field(default_factory=list)
    execution_policy: dict[str, Any] = Field(default_factory=dict)


class QueueUpdateResult(BaseModel):
    schedule_id: str
    updated_entries: list[str] = Field(default_factory=list)
    status: str = "ok"


class RuntimeExecutionStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    WAITING_APPROVAL = "waiting_approval"
    APPROVAL_REJECTED = "approval_rejected"
    PREPARING = "preparing"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class RuntimeRetryPolicy(BaseModel):
    max_attempts: int = 1
    retry_delay: float = 0.0
    backoff: float = 1.0


class RuntimeExecutionRecord(BaseModel):
    execution_id: str = Field(default_factory=lambda: str(uuid4()))
    schedule_id: str
    entry_id: str
    agent_id: str
    plan_id: str
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)
    status: RuntimeExecutionStatus = RuntimeExecutionStatus.PENDING
    attempts: int = 0
    retry_policy: RuntimeRetryPolicy = Field(default_factory=RuntimeRetryPolicy)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    heartbeat_at: datetime | None = None
    deadline_at: datetime | None = None
    completed_at: datetime | None = None
    timeout_reason: str | None = None
    error: str | None = None
    provider_name: str | None = None
    run_id: str | None = None
    job_id: str | None = None
    asset_id: str | None = None
    approval_id: str | None = None
    output: dict[str, Any] = Field(default_factory=dict)
    cancellation_requested: bool = False
    timeline: list[dict[str, Any]] = Field(default_factory=list)
