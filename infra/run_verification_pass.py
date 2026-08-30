"""Run the nightly website verification now, so fresh signals use current code.

Run on the control-plane host.

This enqueues exactly the occurrence `rec-nightly-website-verification` would
have enqueued, through `recurrence.enqueue` — not a second way a mission comes
into being. The recipe fetches websites Qevik has already recorded and audits
what each server returned; its own notes say it runs unattended and contacts
nobody, and its suggested actions are gated by `policy.decide` like any other.

Today's run happened at 05:00 UTC, before the detector change deployed, so
every signal on the ledger predates it. This is how the ledger catches up
without waiting a day.

Sends nothing. Publishes nothing.
"""
from __future__ import annotations

import time

from atlas_kernel.mission import origins, recurrence, service
from atlas_kernel.mission.timeline import Timeline

TENANT = "tenant-qevik"
RECURRENCE = "rec-nightly-website-verification"


def main() -> int:
    timeline = Timeline("/var/lib/qevik/control/missions.jsonl")
    wanted = next((r for r in recurrence.RECURRENCES if r.id == RECURRENCE), None)
    if wanted is None:
        print("no such recurrence: %s" % RECURRENCE)
        return 1

    registry = origins.Registry.build()
    origin = registry.resolve(wanted.origin_name)

    # The firing the ticker would have produced. Built from `latest_due` rather
    # than invented, so the occurrence key is the same deterministic one the
    # scheduled run would have used — a key made up here would let this and the
    # nightly run both fire for the same occurrence.
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    occurrence = recurrence.latest_due(wanted, at=now)
    if occurrence is None:
        print("nothing is due for %s" % RECURRENCE)
        return 1
    firing = recurrence.Firing(
        recurrence_id=wanted.id, occurrence=occurrence,
        key=recurrence.key_for(wanted.id, occurrence))

    mission, events = recurrence.enqueue(
        wanted, firing, tenant=TENANT, origin=origin)
    for event in events:
        timeline.append(event)

    print("mission : %s" % mission.id)
    print("recipe  : %s -> agent %s" % (mission.recipe, mission.agent_id))
    print("status  : %s" % mission.status.value)

    print("\nwaiting for worker-research...")
    deadline = time.time() + 600
    last = ""
    while time.time() < deadline:
        time.sleep(10)
        current = next((m for m in service.fold(timeline.read(), tenant=TENANT)
                        if m["mission_id"] == mission.id), None)
        if current is None:
            continue
        if current["status"] != last:
            last = current["status"]
            print("   %-14s %s" % (last, (current.get("because") or "")[:56]))
        if current["status"] in ("complete", "failed", "cancelled", "blocked"):
            print("\nfinal   : %s" % current["status"])
            print("because : %s" % (current.get("because") or ""))
            return 0 if current["status"] == "complete" else 1
    print("\nstill %s after 600s" % (last or "unclaimed"))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
