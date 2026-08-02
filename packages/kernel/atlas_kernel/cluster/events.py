from __future__ import annotations

from dataclasses import dataclass

from ..event_types import AtlasEvent


@dataclass(frozen=True)
class WorkerRegistered(AtlasEvent):
    worker_id: str = ""
    hostname: str = ""
    capabilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkerDisconnected(AtlasEvent):
    worker_id: str = ""
    reason: str = ""


@dataclass(frozen=True)
class WorkerHeartbeatReceived(AtlasEvent):
    worker_id: str = ""
    status: str = ""
    current_load: int = 0


@dataclass(frozen=True)
class WorkerPaused(AtlasEvent):
    worker_id: str = ""
    actor: str = "system"


@dataclass(frozen=True)
class WorkerResumed(AtlasEvent):
    worker_id: str = ""
    actor: str = "system"


@dataclass(frozen=True)
class WorkerDraining(AtlasEvent):
    worker_id: str = ""
    actor: str = "system"


@dataclass(frozen=True)
class ExecutionAssigned(AtlasEvent):
    execution_id: str = ""
    worker_id: str = ""
    reservation_id: str = ""
    lease_id: str = ""


@dataclass(frozen=True)
class ExecutionMoved(AtlasEvent):
    execution_id: str = ""
    from_worker_id: str = ""
    to_worker_id: str = ""
    reason: str = ""


@dataclass(frozen=True)
class ExecutionRecovered(AtlasEvent):
    execution_id: str = ""
    worker_id: str = ""
    reason: str = ""


@dataclass(frozen=True)
class LeaseExpired(AtlasEvent):
    lease_id: str = ""
    worker_id: str = ""
    execution_id: str = ""


@dataclass(frozen=True)
class ReservationCreated(AtlasEvent):
    reservation_id: str = ""
    worker_id: str = ""
    schedule_id: str = ""
    entry_id: str = ""


@dataclass(frozen=True)
class ReservationReleased(AtlasEvent):
    reservation_id: str = ""
    worker_id: str = ""
    reason: str = ""
