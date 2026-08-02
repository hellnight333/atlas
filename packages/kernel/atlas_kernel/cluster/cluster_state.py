from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from .heartbeat_service import HeartbeatService
from .lease_manager import LeaseManager
from .models import (
    ClusterHealth,
    ClusterLoad,
    ClusterSnapshot,
    WorkerState,
    WorkerSummary,
)
from .worker_registry import WorkerRegistry

if TYPE_CHECKING:
    from ..repository import AtlasRepository


class ClusterStateService:
    """Read-only aggregation over the registry, heartbeats and leases.
    Holds no state of its own and never mutates the cluster."""

    def __init__(
        self,
        repository: AtlasRepository,
        registry: WorkerRegistry,
        heartbeats: HeartbeatService,
        lease_manager: LeaseManager,
    ) -> None:
        self.repository = repository
        self.registry = registry
        self.heartbeats = heartbeats
        self.lease_manager = lease_manager

    def health(self, now: datetime | None = None) -> ClusterHealth:
        now = now or datetime.now(UTC)
        workers = self.registry.list_workers()
        stale = [w.id for w in self.heartbeats.stale_workers(now)]
        expired = [
            lease.id
            for lease in self.repository.list_leases()
            if lease.state.value == "active" and lease.expires_at <= now
        ]
        counts = {state: 0 for state in WorkerState}
        for worker in workers:
            counts[worker.status] += 1

        dispatchable = counts[WorkerState.ONLINE] + counts[WorkerState.BUSY]
        return ClusterHealth(
            healthy=bool(workers) and dispatchable > 0 and not stale and not expired,
            total_workers=len(workers),
            online=counts[WorkerState.ONLINE],
            offline=counts[WorkerState.OFFLINE],
            draining=counts[WorkerState.DRAINING],
            paused=counts[WorkerState.PAUSED],
            errored=counts[WorkerState.ERROR],
            stale_heartbeats=stale,
            expired_leases=expired,
        )

    def load(self, now: datetime | None = None) -> ClusterLoad:
        now = now or datetime.now(UTC)
        workers = self.registry.list_workers()
        stale = {w.id for w in self.heartbeats.stale_workers(now)}

        total_capacity = sum(w.max_concurrency for w in workers)
        used_capacity = sum(w.current_load for w in workers)
        return ClusterLoad(
            total_capacity=total_capacity,
            used_capacity=used_capacity,
            load_ratio=(used_capacity / total_capacity) if total_capacity else 0.0,
            active_reservations=len(self.lease_manager.list_active_reservations()),
            active_leases=len(self.lease_manager.list_active_leases()),
            per_worker=[
                WorkerSummary(
                    worker_id=w.id,
                    display_name=w.display_name,
                    status=w.status,
                    capabilities=list(w.capabilities),
                    current_load=w.current_load,
                    max_concurrency=w.max_concurrency,
                    load_ratio=w.load_ratio,
                    last_heartbeat_at=w.last_heartbeat_at,
                    healthy=w.id not in stale and w.status is not WorkerState.ERROR,
                )
                for w in workers
            ],
        )

    def snapshot(self, now: datetime | None = None) -> ClusterSnapshot:
        now = now or datetime.now(UTC)
        return ClusterSnapshot(
            health=self.health(now),
            load=self.load(now),
            workers=self.registry.list_workers(),
            captured_at=now,
        )
