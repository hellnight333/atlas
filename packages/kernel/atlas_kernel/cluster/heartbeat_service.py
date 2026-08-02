from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from .events import WorkerHeartbeatReceived
from .models import HeartbeatReport, WorkerHeartbeat, WorkerNode, WorkerState
from .worker_registry import WorkerRegistry, WorkerRegistryError

if TYPE_CHECKING:
    from ..event_bus import EventBus
    from ..repository import AtlasRepository


DEFAULT_HEARTBEAT_TIMEOUT_SECONDS = 90


class HeartbeatService:
    """Tracks worker liveness. A worker that stops reporting is marked OFFLINE
    so the dispatcher stops considering it; it is never deleted."""

    def __init__(
        self,
        repository: AtlasRepository,
        event_bus: EventBus,
        registry: WorkerRegistry,
        timeout_seconds: int = DEFAULT_HEARTBEAT_TIMEOUT_SECONDS,
    ) -> None:
        self.repository = repository
        self.event_bus = event_bus
        self.registry = registry
        self.timeout_seconds = timeout_seconds

    def record(self, report: HeartbeatReport) -> WorkerNode:
        worker = self.registry.get(report.worker_id)
        if worker is None:
            raise WorkerRegistryError(f"Worker not found: {report.worker_id}")

        now = datetime.now(UTC)
        status = report.status or self._recovered_status(worker)
        updated = worker.model_copy(
            update={
                "status": status,
                "current_load": (
                    report.current_load if report.current_load is not None else worker.current_load
                ),
                "metrics": report.metrics or worker.metrics,
                "metadata": {**worker.metadata, **report.metadata},
                "last_heartbeat_at": now,
                "updated_at": now,
            }
        )
        self.repository.upsert_worker(updated)
        self.repository.create_worker_heartbeat(
            WorkerHeartbeat(
                worker_id=updated.id,
                status=updated.status,
                current_load=updated.current_load,
                metrics=updated.metrics,
                created_at=now,
            )
        )
        self.event_bus.publish(
            WorkerHeartbeatReceived(
                worker_id=updated.id,
                status=updated.status.value,
                current_load=updated.current_load,
            )
        )
        return updated

    def _recovered_status(self, worker: WorkerNode) -> WorkerState:
        """A heartbeat from a worker we had given up on brings it back, but it
        must not override a deliberate operator state."""
        if worker.status in {WorkerState.PAUSED, WorkerState.DRAINING, WorkerState.UPDATING}:
            return worker.status
        if worker.status in {WorkerState.OFFLINE, WorkerState.ERROR}:
            return WorkerState.ONLINE
        return worker.status

    def stale_workers(self, now: datetime | None = None) -> list[WorkerNode]:
        now = now or datetime.now(UTC)
        cutoff = now - timedelta(seconds=self.timeout_seconds)
        stale: list[WorkerNode] = []
        for worker in self.repository.list_workers():
            if worker.status in {WorkerState.OFFLINE, WorkerState.PAUSED}:
                continue
            if worker.last_heartbeat_at is None or worker.last_heartbeat_at < cutoff:
                stale.append(worker)
        return stale

    def detect_timeouts(self, now: datetime | None = None) -> list[WorkerNode]:
        """Marks every worker past its heartbeat deadline OFFLINE."""
        return [
            self.registry.mark_offline(worker.id, reason="heartbeat timeout")
            for worker in self.stale_workers(now)
        ]

    def history(self, worker_id: str, limit: int = 50) -> list[WorkerHeartbeat]:
        return self.repository.list_worker_heartbeats(worker_id=worker_id, limit=limit)
