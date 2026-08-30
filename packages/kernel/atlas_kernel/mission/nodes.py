"""Mission workers, as the scheduler needs to hear about them.

The composition point between two lineages that stay separate: `cluster` owns
the registry rows, `fabric` decides over stated facts and imports nothing from
`cluster`. This reads the one and speaks the other.

It exists so there is exactly one answer to "which workers are there". The
worker process and `GET /schedule` both call it, and a view that computed the
answer differently from the dispatch it describes is the whole defect this
milestone set out to remove.

No storage of its own, and no second registry: every fact comes from the
`atlas_workers` rows that already exist.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from ..fabric.scheduler import MISSION_WORKER_TAG, NodeSnapshot

log = logging.getLogger(__name__)


def snapshots() -> tuple[NodeSnapshot, ...] | None:
    """Every Qevik mission worker. `None` when the cluster cannot be read.

    `None` and `()` are deliberately different answers, and the scheduler treats
    them differently: `None` means nothing is known about workers, so queues are
    decided as they were before nodes existed; `()` means somebody looked and
    there are none, which blocks. Returning `()` on a failed read would turn a
    database hiccup into "every mission is unrunnable".

    Only nodes carrying the mission-worker tag. The registry also holds Atlas
    workers and, in production, five online test fixtures -- an allow-list keeps
    every one of them out by default rather than by having anticipated them.
    """
    try:
        import atlas_kernel.agents  # noqa: F401  (import order; breaks a cycle)

        from ..cluster.heartbeat_service import DEFAULT_HEARTBEAT_TIMEOUT_SECONDS
        from ..cluster.models import DISPATCHABLE_WORKER_STATES
        from ..cluster.worker_registry import WorkerRegistry
        from ..event_bus import EventBus
        from ..repository import AtlasRepository

        registry = WorkerRegistry(AtlasRepository(), EventBus())
        cutoff = (datetime.now(UTC)
                  - timedelta(seconds=DEFAULT_HEARTBEAT_TIMEOUT_SECONDS))
        out = []
        for worker in registry.list_workers():
            if MISSION_WORKER_TAG not in worker.tags:
                continue
            beat = worker.last_heartbeat_at
            out.append(NodeSnapshot(
                worker_name=str(worker.metadata.get("worker_name", "")),
                serves=str(worker.metadata.get("serves", "")),
                capabilities=frozenset(worker.capabilities),
                placements=frozenset(
                    tag.split(":", 1)[1] for tag in worker.tags
                    if tag.startswith("placement:")),
                # Liveness, never ownership. A stale node keeps any claim it
                # holds and is simply not given anything new.
                fresh=bool(beat and beat >= cutoff
                           and worker.status in DISPATCHABLE_WORKER_STATES),
                free=worker.has_free_slot,
                load=worker.current_load,
                node_id=worker.id))
        return tuple(out)
    except Exception:                            # noqa: BLE001 - reported, not swallowed
        log.exception("could not read the cluster; scheduling without it")
        return None
