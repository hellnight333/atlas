from __future__ import annotations

import platform as platform_module
import socket
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from .events import (
    WorkerDisconnected,
    WorkerDraining,
    WorkerPaused,
    WorkerRegistered,
    WorkerResumed,
)
from .models import (
    WorkerCapability,
    WorkerNode,
    WorkerRegistration,
    WorkerResources,
    WorkerState,
)

if TYPE_CHECKING:
    from ..event_bus import EventBus
    from ..repository import AtlasRepository


LOCAL_WORKER_ID = "worker-local"

#: The in-process worker advertises everything the local kernel can serve, so a
#: single-machine Atlas behaves exactly as it did before the cluster existed.
LOCAL_WORKER_CAPABILITIES: tuple[str, ...] = tuple(c.value for c in WorkerCapability)


class WorkerRegistryError(RuntimeError):
    pass


class WorkerRegistry:
    """Owns worker identity and lifecycle. Holds no scheduling logic."""

    def __init__(self, repository: AtlasRepository, event_bus: EventBus) -> None:
        self.repository = repository
        self.event_bus = event_bus

    def register(self, registration: WorkerRegistration) -> WorkerNode:
        """Registration is idempotent per hostname: a worker that reconnects
        keeps its id and history rather than accumulating duplicates."""
        existing = None
        if registration.worker_id:
            existing = self.repository.get_worker(registration.worker_id)
        if existing is None:
            existing = self.repository.get_worker_by_hostname(registration.hostname)

        now = datetime.now(UTC)
        if existing is not None:
            worker = existing.model_copy(
                update={
                    "display_name": registration.display_name or existing.display_name,
                    "platform": registration.platform,
                    "resources": registration.resources,
                    "capabilities": list(registration.capabilities),
                    "max_concurrency": max(1, registration.max_concurrency),
                    "version": registration.version,
                    "tags": list(registration.tags),
                    "metadata": dict(registration.metadata),
                    "status": WorkerState.ONLINE,
                    "last_heartbeat_at": now,
                    "updated_at": now,
                }
            )
        else:
            worker = WorkerNode(
                id=registration.worker_id or f"worker-{registration.hostname}",
                hostname=registration.hostname,
                display_name=registration.display_name or registration.hostname,
                platform=registration.platform,
                resources=registration.resources,
                capabilities=list(registration.capabilities),
                max_concurrency=max(1, registration.max_concurrency),
                version=registration.version,
                tags=list(registration.tags),
                metadata=dict(registration.metadata),
                status=WorkerState.ONLINE,
                last_heartbeat_at=now,
                registered_at=now,
                updated_at=now,
            )

        self.repository.upsert_worker(worker)
        self.event_bus.publish(
            WorkerRegistered(
                worker_id=worker.id,
                hostname=worker.hostname,
                capabilities=tuple(worker.capabilities),
            )
        )
        return worker

    def get(self, worker_id: str) -> WorkerNode | None:
        return self.repository.get_worker(worker_id)

    def list_workers(self, status: WorkerState | None = None) -> list[WorkerNode]:
        workers = self.repository.list_workers()
        if status is not None:
            workers = [w for w in workers if w.status is status]
        return sorted(workers, key=lambda w: (w.display_name, w.id))

    def pause(self, worker_id: str, actor: str = "system") -> WorkerNode:
        worker = self._transition(worker_id, WorkerState.PAUSED)
        self.event_bus.publish(WorkerPaused(worker_id=worker_id, actor=actor))
        return worker

    def resume(self, worker_id: str, actor: str = "system") -> WorkerNode:
        worker = self._transition(worker_id, WorkerState.ONLINE)
        self.event_bus.publish(WorkerResumed(worker_id=worker_id, actor=actor))
        return worker

    def drain(self, worker_id: str, actor: str = "system") -> WorkerNode:
        """Draining keeps running work but accepts nothing new."""
        worker = self._transition(worker_id, WorkerState.DRAINING)
        self.event_bus.publish(WorkerDraining(worker_id=worker_id, actor=actor))
        return worker

    def mark_offline(self, worker_id: str, reason: str = "disconnected") -> WorkerNode:
        worker = self._transition(worker_id, WorkerState.OFFLINE)
        self.event_bus.publish(WorkerDisconnected(worker_id=worker_id, reason=reason))
        return worker

    def mark_error(self, worker_id: str, reason: str) -> WorkerNode:
        worker = self._transition(worker_id, WorkerState.ERROR)
        self.event_bus.publish(WorkerDisconnected(worker_id=worker_id, reason=reason))
        return worker

    def adjust_load(self, worker_id: str, delta: int) -> WorkerNode:
        worker = self._require(worker_id)
        load = max(0, worker.current_load + delta)
        status = worker.status
        if status in {WorkerState.ONLINE, WorkerState.BUSY}:
            status = WorkerState.BUSY if load >= worker.max_concurrency else WorkerState.ONLINE
        updated = worker.model_copy(
            update={"current_load": load, "status": status, "updated_at": datetime.now(UTC)}
        )
        self.repository.upsert_worker(updated)
        return updated

    def ensure_local_worker(self) -> WorkerNode:
        """Registers the in-process worker so a single-machine install has a
        cluster of one and nothing needs configuring to keep working."""
        existing = self.repository.get_worker(LOCAL_WORKER_ID)
        if existing is not None:
            return existing
        return self.register(
            WorkerRegistration(
                worker_id=LOCAL_WORKER_ID,
                hostname=_safe_hostname(),
                display_name="Local Machine",
                platform=platform_module.platform(),
                resources=WorkerResources(),
                capabilities=list(LOCAL_WORKER_CAPABILITIES),
                max_concurrency=4,
                version="0.9.0",
                tags=["local"],
            )
        )

    def _transition(self, worker_id: str, state: WorkerState) -> WorkerNode:
        worker = self._require(worker_id)
        updated = worker.model_copy(update={"status": state, "updated_at": datetime.now(UTC)})
        self.repository.upsert_worker(updated)
        return updated

    def _require(self, worker_id: str) -> WorkerNode:
        worker = self.repository.get_worker(worker_id)
        if worker is None:
            raise WorkerRegistryError(f"Worker not found: {worker_id}")
        return worker


def _safe_hostname() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "localhost"
