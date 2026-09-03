"""`/api/fabric` — the floor, read once.

One route, because the office is one question. The console asks it every few
seconds and draws desks; nothing here writes, dispatches or approves.

The fleet comes from the scheduler's own snapshot rather than a query of our
own, so the office and the dispatcher cannot disagree about which machines
exist. When that snapshot cannot be read the route says so — `known: false` —
instead of returning an empty fleet, because an unreachable database drawn as an
empty office is how somebody concludes their cluster died.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..auth.api import Scope, User, requires
from . import office


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api/fabric", tags=["fabric"])

    @router.get("/office")
    def office_floor(_: User = Depends(requires(Scope.READ))) -> dict[str, Any]:
        """Every agent as a desk, in a room, with the state it is actually in.

        Blocked agents are included on purpose: a seat with
        `PENDING_CREDENTIAL` attached is the most actionable thing on the floor,
        and hiding it would make the picture prettier and the company slower.
        """
        try:
            from ..mission.nodes import snapshots

            fleet_nodes = snapshots()
        except Exception:  # pragma: no cover - the DB is not reachable in unit tests
            fleet_nodes = None

        if fleet_nodes is None:
            fleet: dict[str, Any] = {
                "known": False,
                "workers": [],
                "detail": ("the cluster could not be read, which is not the "
                           "same as there being no workers"),
            }
        else:
            workers = [{
                "name": node.worker_name,
                "capabilities": sorted(node.capabilities),
                "healthy": node.fresh,
                "available": node.free,
                "load": node.load,
            } for node in fleet_nodes]
            fleet = {
                "known": True,
                "workers": workers,
                "counts": {
                    "total": len(workers),
                    "ready": sum(1 for w in workers if w["healthy"] and w["available"]),
                    "busy": sum(1 for w in workers if w["healthy"] and not w["available"]),
                    "stale": sum(1 for w in workers if not w["healthy"]),
                },
            }

        return office.floor(fleet)

    return router


def install(app) -> None:
    app.include_router(build_router())


__all__ = ["build_router", "install"]
