from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from ..agents.runtime import PlacementResult
from ..agents.schedule_models import ExecutionSchedule, ScheduleQueueEntry
from .events import ExecutionAssigned
from .lease_manager import LeaseManager
from .models import (
    DISPATCHABLE_WORKER_STATES,
    WorkerCapability,
    WorkerNode,
)
from .worker_registry import WorkerRegistry

if TYPE_CHECKING:
    from ..event_bus import EventBus


class OwnershipFilter(Protocol):
    """Implemented by the organization layer. The dispatcher knows only this
    shape, so worker ownership can be enforced without the cluster depending on
    organizations."""

    def may_execute_on_worker(self, organization_id: str | None, worker_id: str) -> bool: ...


@dataclass(frozen=True)
class WorkerCandidate:
    worker: WorkerNode
    score: float
    reason: str


class Dispatcher:
    """Chooses which worker runs an entry.

    Selection inputs, in order of authority: worker health, advertised
    capability, declared affinity, current load, and entry priority. The UI
    never selects a worker, and providers never learn which machine they ran on.
    """

    def __init__(
        self,
        registry: WorkerRegistry,
        lease_manager: LeaseManager,
        event_bus: EventBus,
        ownership_filter: OwnershipFilter | None = None,
    ) -> None:
        self.registry = registry
        self.lease_manager = lease_manager
        self.event_bus = event_bus
        # Injected by the composition root so the cluster layer never imports
        # the organization domain. Absent, every worker is eligible.
        self.ownership_filter = ownership_filter

    def place(
        self,
        schedule: ExecutionSchedule,
        entry: ScheduleQueueEntry,
        execution_id: str,
    ) -> PlacementResult:
        """Reserves a worker slot and issues a lease, or reports why it could not."""
        capability = self._required_capability(entry)
        affinity = self._affinity(schedule, entry)
        organization_id = self._organization_id(schedule)

        candidates = self.select_candidates(capability, affinity, organization_id)
        if not candidates:
            return PlacementResult(
                placed=False,
                reason=self._unplaceable_reason(capability, affinity, organization_id),
            )

        chosen = candidates[0]
        reservation = self.lease_manager.reserve(
            worker_id=chosen.worker.id,
            schedule_id=schedule.schedule_id,
            entry_id=entry.id,
            execution_id=execution_id,
            capability=capability,
            priority=self._priority(entry),
            reason=chosen.reason,
        )
        lease = self.lease_manager.acquire(
            reservation_id=reservation.id,
            worker_id=chosen.worker.id,
            execution_id=execution_id,
        )
        self.registry.adjust_load(chosen.worker.id, +1)

        self.event_bus.publish(
            ExecutionAssigned(
                execution_id=execution_id,
                worker_id=chosen.worker.id,
                reservation_id=reservation.id,
                lease_id=lease.id,
            )
        )
        return PlacementResult(
            placed=True,
            worker_id=chosen.worker.id,
            reservation_id=reservation.id,
            lease_id=lease.id,
            reason=chosen.reason,
        )

    def release(
        self,
        *,
        worker_id: str | None,
        reservation_id: str | None,
        lease_id: str | None,
        reason: str = "completed",
        expired: bool = False,
    ) -> None:
        """Always safe to call: releasing an already-released claim is a no-op."""
        if lease_id:
            if expired:
                self.lease_manager.expire(lease_id)
            else:
                self.lease_manager.release(lease_id)
        if reservation_id:
            self.lease_manager.release_reservation(reservation_id, reason=reason)
        if worker_id:
            self.registry.adjust_load(worker_id, -1)

    def select_candidates(
        self,
        capability: str,
        affinity: list[str] | None = None,
        organization_id: str | None = None,
    ) -> list[WorkerCandidate]:
        affinity = affinity or []
        candidates: list[WorkerCandidate] = []

        for worker in self.registry.list_workers():
            if worker.status not in DISPATCHABLE_WORKER_STATES:
                continue
            if not worker.has_free_slot:
                continue
            if not self._owns(organization_id, worker.id):
                continue
            if capability and not self._serves(worker, capability):
                continue
            if affinity and not set(affinity) & set(worker.tags):
                continue
            candidates.append(
                WorkerCandidate(
                    worker=worker,
                    score=self._score(worker, affinity),
                    reason=self._reason(worker, capability, affinity),
                )
            )

        # Highest score first; ties broken deterministically by id so the same
        # cluster state always produces the same placement.
        return sorted(candidates, key=lambda c: (-c.score, c.worker.id))

    def _serves(self, worker: WorkerNode, capability: str) -> bool:
        return capability in worker.capabilities

    def _score(self, worker: WorkerNode, affinity: list[str]) -> float:
        score = 100.0 * (1.0 - worker.load_ratio)
        if affinity and set(affinity) & set(worker.tags):
            score += 50.0
        if worker.resources.vram_gb:
            score += min(worker.resources.vram_gb, 96) / 10.0
        return score

    def _reason(self, worker: WorkerNode, capability: str, affinity: list[str]) -> str:
        parts = [f"serves '{capability}'"] if capability else ["no capability required"]
        parts.append(f"load {worker.current_load}/{worker.max_concurrency}")
        if affinity and set(affinity) & set(worker.tags):
            parts.append(f"affinity {sorted(set(affinity) & set(worker.tags))}")
        return ", ".join(parts)

    def _owns(self, organization_id: str | None, worker_id: str) -> bool:
        """Cross-organization execution is forbidden unless policy allows it."""
        if self.ownership_filter is None:
            return True
        return self.ownership_filter.may_execute_on_worker(organization_id, worker_id)

    def _organization_id(self, schedule: ExecutionSchedule) -> str | None:
        value = schedule.queue_metadata.get("organization_id")
        return str(value) if isinstance(value, str) and value else None

    def _unplaceable_reason(
        self, capability: str, affinity: list[str], organization_id: str | None = None
    ) -> str:
        workers = self.registry.list_workers()
        if not workers:
            return "no workers registered"
        healthy = [w for w in workers if w.status in DISPATCHABLE_WORKER_STATES]
        if not healthy:
            return "no worker is online"
        owned = [w for w in healthy if self._owns(organization_id, w.id)]
        if not owned:
            return f"no worker is available to organization {organization_id}"
        capable = [w for w in owned if not capability or self._serves(w, capability)]
        if not capable:
            return f"no online worker advertises '{capability}'"
        if affinity:
            matched = [w for w in capable if set(affinity) & set(w.tags)]
            if not matched:
                return f"no online worker matches affinity {affinity}"
        return "every capable worker is at capacity"

    def _required_capability(self, entry: ScheduleQueueEntry) -> str:
        """Capability comes from the plan step, never from the provider: the
        provider layer must stay unaware of machines.

        Routing is a hint, not a feasibility verdict. A capability outside the
        known worker vocabulary imposes no constraint, so work that the provider
        layer would reject still reaches the provider layer and fails there
        rather than stalling forever waiting for a machine that cannot exist.
        """
        declared = entry.plan_step.payload.get("worker_capability")
        if isinstance(declared, str) and declared:
            return declared

        resolved = _CAPABILITY_ALIASES.get(entry.capability.lower(), entry.capability.lower())
        return resolved if resolved in _KNOWN_WORKER_CAPABILITIES else ""

    def _affinity(self, schedule: ExecutionSchedule, entry: ScheduleQueueEntry) -> list[str]:
        declared: Any = entry.plan_step.payload.get("worker_affinity")
        if isinstance(declared, list):
            return [str(tag) for tag in declared]
        project_rule = schedule.queue_metadata.get("worker_affinity")
        if isinstance(project_rule, list):
            return [str(tag) for tag in project_rule]
        return []

    def _priority(self, entry: ScheduleQueueEntry) -> int:
        return {"immediate": 100, "high": 50, "normal": 0, "low": -10, "background": -50}.get(
            entry.priority.value, 0
        )


_KNOWN_WORKER_CAPABILITIES: frozenset[str] = frozenset(c.value for c in WorkerCapability)


#: Plan-step capabilities are workflow vocabulary; worker capabilities are
#: machine vocabulary. This table is the only place the two meet.
_CAPABILITY_ALIASES: dict[str, str] = {
    "reasoning": "text",
    "planning": "text",
    "research": "text",
    "workflow": "text",
    "review": "text",
    "code": "python",
    "code_generation": "python",
    "media": "video",
    "image_generation": "image",
}
