from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class WorkerState(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"
    PAUSED = "paused"
    DRAINING = "draining"
    ERROR = "error"
    UPDATING = "updating"


#: States that may receive new work. DRAINING finishes what it has but takes nothing new.
DISPATCHABLE_WORKER_STATES: frozenset[WorkerState] = frozenset(
    {WorkerState.ONLINE, WorkerState.BUSY}
)


class WorkerCapability(StrEnum):
    """Known capabilities. Workers may advertise custom strings beyond these."""

    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    TRAINING = "training"
    EMBEDDING = "embedding"
    RENDER = "render"
    PYTHON = "python"
    FILESYSTEM = "filesystem"
    DOCKER = "docker"


class WorkerResources(BaseModel):
    cpu_cores: int = 0
    ram_gb: int = 0
    gpu: str | None = None
    vram_gb: int = 0
    storage_gb: int = 0


class WorkerMetrics(BaseModel):
    """Point-in-time utilisation reported by a heartbeat."""

    cpu_percent: float = 0.0
    ram_percent: float = 0.0
    gpu_percent: float = 0.0
    vram_used_gb: float = 0.0
    storage_used_gb: float = 0.0


class WorkerNode(BaseModel):
    id: str = Field(default_factory=lambda: f"worker-{uuid4().hex[:12]}")
    hostname: str
    display_name: str
    platform: str = "unknown"
    resources: WorkerResources = Field(default_factory=WorkerResources)
    capabilities: list[str] = Field(default_factory=list)
    current_load: int = 0
    max_concurrency: int = 1
    status: WorkerState = WorkerState.ONLINE
    version: str = "0.0.0"
    tags: list[str] = Field(default_factory=list)
    metrics: WorkerMetrics = Field(default_factory=WorkerMetrics)
    metadata: dict[str, Any] = Field(default_factory=dict)
    last_heartbeat_at: datetime | None = None
    registered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def has_free_slot(self) -> bool:
        return self.current_load < self.max_concurrency

    @property
    def load_ratio(self) -> float:
        if self.max_concurrency <= 0:
            return 1.0
        return self.current_load / self.max_concurrency


class WorkerRegistration(BaseModel):
    hostname: str
    display_name: str | None = None
    platform: str = "unknown"
    resources: WorkerResources = Field(default_factory=WorkerResources)
    capabilities: list[str] = Field(default_factory=list)
    max_concurrency: int = 1
    version: str = "0.0.0"
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    worker_id: str | None = None


class HeartbeatReport(BaseModel):
    worker_id: str
    status: WorkerState | None = None
    current_load: int | None = None
    metrics: WorkerMetrics | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkerHeartbeat(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    worker_id: str
    status: WorkerState
    current_load: int = 0
    metrics: WorkerMetrics = Field(default_factory=WorkerMetrics)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReservationState(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    RELEASED = "released"
    CANCELLED = "cancelled"


class ExecutionReservation(BaseModel):
    id: str = Field(default_factory=lambda: f"reservation-{uuid4().hex[:12]}")
    worker_id: str
    schedule_id: str
    entry_id: str
    execution_id: str | None = None
    capability: str = ""
    priority: int = 0
    state: ReservationState = ReservationState.PENDING
    reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    released_at: datetime | None = None


class LeaseState(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    RELEASED = "released"


class ExecutionLease(BaseModel):
    id: str = Field(default_factory=lambda: f"lease-{uuid4().hex[:12]}")
    reservation_id: str
    worker_id: str
    execution_id: str
    state: LeaseState = LeaseState.ACTIVE
    lease_seconds: int = 120
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    renewed_at: datetime | None = None
    expires_at: datetime
    released_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        return self.state is LeaseState.ACTIVE


class WorkerSummary(BaseModel):
    worker_id: str
    display_name: str
    status: WorkerState
    capabilities: list[str] = Field(default_factory=list)
    current_load: int = 0
    max_concurrency: int = 1
    load_ratio: float = 0.0
    last_heartbeat_at: datetime | None = None
    healthy: bool = True


class ClusterHealth(BaseModel):
    healthy: bool = True
    total_workers: int = 0
    online: int = 0
    offline: int = 0
    draining: int = 0
    paused: int = 0
    errored: int = 0
    stale_heartbeats: list[str] = Field(default_factory=list)
    expired_leases: list[str] = Field(default_factory=list)


class ClusterLoad(BaseModel):
    total_capacity: int = 0
    used_capacity: int = 0
    load_ratio: float = 0.0
    active_reservations: int = 0
    active_leases: int = 0
    per_worker: list[WorkerSummary] = Field(default_factory=list)


class ClusterSnapshot(BaseModel):
    health: ClusterHealth = Field(default_factory=ClusterHealth)
    load: ClusterLoad = Field(default_factory=ClusterLoad)
    workers: list[WorkerNode] = Field(default_factory=list)
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

