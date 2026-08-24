"""What changed, cheaply enough to ask every few seconds.

Mission Control shows state on load and then stops moving. A person watching a
mission run has to reload to find out whether it did, which is the difference
between a report and a control panel.

**Polling with a version token, not server-sent events**, and that is a decision
rather than a shortcut. `app.qevik.ai` sits behind Cloudflare, which buffers
streaming responses by default; an SSE channel would work locally, appear to work
in review, and deliver nothing through the CDN. Polling also holds no connection
open, so a hundred idle tabs cost nothing on a single-worker deployment.

The shape that makes it cheap: `version()` folds the timelines once and returns a
digest. The console sends the digest it last saw; when it is unchanged the
response is a few bytes and the console does nothing. Only a changed digest
causes a re-render.

Tenant-scoped like everything else — the digest is computed over one tenant's
events, so a change in another tenant's work cannot even signal.
"""

from __future__ import annotations

import hashlib
from typing import Any

from ..chat import service as chat_service
from ..mission import service as mission_service
from ..mission.models import TERMINAL, MissionStatus
from ..opportunity.tenancy import TenantId
from ..opportunity.tenancy import require as _require_tenant

#: Statuses that mean something is happening right now. A person watching wants
#: to know the difference between "running" and "waiting for me".
RUNNING: frozenset[str] = frozenset({
    MissionStatus.PROCESSING.value, MissionStatus.TESTING.value,
    MissionStatus.REVIEWING.value, MissionStatus.COMMITTING.value,
})


def snapshot(mission_events: Any, chat_events: Any, *,
             tenant: TenantId | None) -> dict:
    """Everything the home screen needs, in one fold of each timeline.

    Deliberately a summary rather than the missions themselves: the console
    asks this every few seconds, and shipping the full list each time would
    make a live view more expensive than the page it lives on.
    """
    tenant = _require_tenant(tenant, method="live.snapshot")
    missions = mission_service.fold(list(mission_events or []), tenant=tenant)
    conversations = chat_service.fold(list(chat_events or []), tenant=tenant)

    running = [m for m in missions if m.get("status") in RUNNING]
    awaiting = [m for m in missions
                if m.get("status") == MissionStatus.AWAITING_APPROVAL.value]
    blocked = [m for m in missions
               if m.get("status") == MissionStatus.BLOCKED.value]
    failed = [m for m in missions
              if m.get("status") == MissionStatus.FAILED.value]
    proposed = [c for c in conversations if c.get("status") == "plan_proposed"]

    # "What needs me" is the question the home screen exists to answer, so it is
    # computed here rather than left for a caller to assemble from three lists
    # and get subtly different on each surface.
    needs_me = len(awaiting) + len(proposed)

    return {
        "version": _digest(missions, conversations),
        "counts": {
            "missions": len(missions),
            "running": len(running),
            "awaiting_approval": len(awaiting),
            "blocked": len(blocked),
            "failed": len(failed),
            "plans_proposed": len(proposed),
            "needs_me": needs_me,
            "complete": sum(1 for m in missions
                            if m.get("status") == MissionStatus.COMPLETE.value),
        },
        # A few rows, not the list. Enough to show movement without becoming a
        # second copy of `/api/missions` that can disagree with it.
        "running": [_row(m) for m in running[:5]],
        "needs_attention": [_row(m) for m in awaiting[:5]]
                           + [_conversation(c) for c in proposed[:5]],
        "recent": [_row(m) for m in missions[:5]],
        "note": ("A summary, refreshed by polling. The authoritative lists are "
                 "/api/missions and /api/chat; this never disagrees with them "
                 "because it is folded from the same events."),
    }


def _row(mission: dict) -> dict:
    return {"kind": "mission", "id": mission.get("mission_id", ""),
            "title": mission.get("title", ""),
            "status": mission.get("status", ""),
            "claimed_by": mission.get("claimed_by", ""),
            "at": mission.get("updated_at", ""),
            "terminal": mission.get("status") in {s.value for s in TERMINAL}}


def _conversation(entry: dict) -> dict:
    return {"kind": "conversation", "id": entry.get("conversation_id", ""),
            "title": entry.get("title", ""), "status": entry.get("status", ""),
            "at": entry.get("at", "")}


def _digest(missions: list[dict], conversations: list[dict]) -> str:
    """A token that changes exactly when something a viewer would notice does.

    Built from each item's id and its last-updated time rather than from the
    whole payload: a digest over everything changes when a field nobody displays
    changes, and then the console re-renders on every poll for no reason.
    """
    parts = [f"{m.get('mission_id')}@{m.get('updated_at')}:{m.get('status')}"
             for m in missions]
    parts += [f"{c.get('conversation_id')}@{c.get('at')}:{c.get('status')}"
              for c in conversations]
    # Sorted, because two workers appending concurrently produce the same set in
    # a different order and that is not a change.
    joined = "|".join(sorted(parts))
    return hashlib.blake2b(joined.encode("utf-8"), digest_size=12).hexdigest()
