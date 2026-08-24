"""What Mission Control shows, computed here rather than in a UI.

§12 asks for enough backend data for a polished interface, and the trap it is
avoiding is a UI that derives status itself. Two clients then disagree about
what a mission is doing, and the one a person happens to be looking at becomes
the truth. So the shaping lives here and the client renders what it is given.

Everything is folded from the event log. There is no mission table to query and
no cached view to invalidate — a restarted process reads the same file and
reaches the same answer, which is the property the whole mission layer was
arranged to have.
"""

from __future__ import annotations

from ..mission import service as mission_service
from ..mission.models import TERMINAL, MissionStatus
from ..opportunity.tenancy import TenantId
from ..opportunity.tenancy import require as _require_tenant

#: The order a person reads a mission list in: what needs them, then what is
#: running, then what is waiting, then what is finished. Sorting by timestamp
#: alone buries a blocked mission under a week of completed ones.
ATTENTION: tuple[MissionStatus, ...] = (
    MissionStatus.BLOCKED,
    MissionStatus.AWAITING_APPROVAL,
    MissionStatus.FAILED,
    MissionStatus.PROCESSING,
    MissionStatus.TESTING,
    MissionStatus.REVIEWING,
    MissionStatus.COMMITTING,
    MissionStatus.QUEUED,
    MissionStatus.PLANNING,
    MissionStatus.DRAFT,
    MissionStatus.COMPLETE,
    MissionStatus.CANCELLED,
)

_RANK = {status.value: position for position, status in enumerate(ATTENTION)}


def _needs_human(row: dict) -> bool:
    """Whether this mission is waiting on a person rather than on the system."""
    return row.get("status") in (MissionStatus.AWAITING_APPROVAL.value,
                                 MissionStatus.BLOCKED.value)


def summarise(row: dict) -> dict:
    """One mission, in the shape a list renders.

    Deliberately includes `needs_human` and `blockers` rather than leaving a
    client to infer them from the status string — an inference two clients
    would eventually make differently.
    """
    plan = row.get("plan") or {}
    return {
        "mission_id": row.get("mission_id"),
        "title": row.get("title", ""),
        "status": row.get("status"),
        "needs_human": _needs_human(row),
        "requested_by": row.get("requested_by", ""),
        "claimed_by": row.get("claimed_by", ""),
        "goal": plan.get("goal", ""),
        "steps": len(plan.get("steps") or ()),
        "blockers": row.get("blockers") or [],
        "commits": row.get("commits") or [],
        "invocations": len(row.get("invocations") or ()),
        # None when no provider reported one. Never rendered as zero, because a
        # free-looking mission and an unmeasured one are different facts.
        "cost": row.get("total_cost"),
        "report": row.get("report_path", ""),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def board(events: list, *, tenant: TenantId | None = None) -> dict:
    """The mission board: everything, grouped and ordered by what needs doing.

    TENANT_SCOPED — `mission_service.fold` refuses without a tenant, so there is
    no path here that reads another customer's missions.
    """
    tenant = _require_tenant(tenant, method="controlplane.board")
    rows = [summarise(row) for row in mission_service.fold(events, tenant=tenant)]
    ordered = sorted(rows, key=lambda r: (_RANK.get(r["status"], 99),
                                          r.get("updated_at") or ""))

    by_status: dict[str, list[str]] = {}
    for row in ordered:
        by_status.setdefault(row["status"], []).append(row["mission_id"])

    running = {MissionStatus.PROCESSING.value, MissionStatus.TESTING.value,
               MissionStatus.REVIEWING.value, MissionStatus.COMMITTING.value}
    return {
        "missions": ordered,
        "needs_human": [r for r in ordered if r["needs_human"]],
        "running": [r for r in ordered if r["status"] in running],
        "by_status": by_status,
        "counts": {
            "total": len(ordered),
            "needs_human": sum(1 for r in ordered if r["needs_human"]),
            "running": sum(1 for r in ordered if r["status"] in running),
            "finished": sum(1 for r in ordered
                            if r["status"] in {s.value for s in TERMINAL}),
        },
        "note": "Ordered by what needs attention, not by time. A blocked "
                "mission sorted by timestamp disappears under finished ones.",
    }


def detail(events: list, mission_id: str, *, tenant: TenantId | None = None
           ) -> dict | None:
    """One mission with its whole timeline. `None` when it is not this tenant's.

    Absent rather than forbidden, as everywhere else — the difference tells a
    caller which mission ids exist.
    """
    tenant = _require_tenant(tenant, method="controlplane.detail")
    current = [row for row in mission_service.fold(events, tenant=tenant)
               if row.get("mission_id") == mission_id]
    if not current:
        return None

    timeline = mission_service.history(events, mission_id, tenant=tenant)
    row = current[0]
    return {
        **summarise(row),
        "plan": row.get("plan"),
        "timeline": [
            {"status": entry.get("status"), "note": entry.get("note", ""),
             "at": entry.get("updated_at")}
            for entry in timeline
        ],
        # The full invocation records, not just a count: cost provenance is the
        # thing a person checks when a number looks wrong.
        "agent_calls": row.get("invocations") or [],
    }


def attention(events: list, *, tenant: TenantId | None = None) -> list[dict]:
    """Only what is waiting on a person. The list a mobile client opens to."""
    return board(events, tenant=tenant)["needs_human"]
