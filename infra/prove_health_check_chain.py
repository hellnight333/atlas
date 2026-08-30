"""Approve one health-check opportunity and carry it to an artefact.

Run on the control-plane host. Mirrors `POST /api/missions/deliver` exactly —
`approve_signal` then `delivery.enqueue` — rather than inventing a second way an
opportunity is approved or a mission is created.

**Contacts nobody and publishes nothing.** The recipe's agent declares one tool,
`website-generator`, which is not a network tool, so this cannot reach anyone
even if it tried. Publication stays the separate outward act it already is, with
its own approval.

Takes a signal id so the business being approved is chosen deliberately rather
than by whatever sorted first.
"""
from __future__ import annotations

import sys
import time

from atlas_kernel.mission import delivery, origins, service
from atlas_kernel.mission.timeline import Timeline
from atlas_kernel.opportunity.repository import OpportunityRepository

TENANT = "tenant-qevik"
ACTOR = "verification"


def main(signal_id: str) -> int:
    memory = OpportunityRepository()
    timeline = Timeline("/var/lib/qevik/control/missions.jsonl")
    origin = origins.Registry.build().resolve(origins.EMPTY_NAME)

    approved = memory.approve_signal(signal_id, actor=ACTOR, tenant=TENANT)
    print("opportunity : %s -> %s" % (signal_id, approved.get("status")))
    action = (approved.get("detail") or {}).get("actions", [{}])[0]
    print("action      : %s" % action.get("capability"))

    mission, events = delivery.enqueue(approved, tenant=TENANT, origin=origin,
                                       actor=ACTOR)
    for event in events:
        timeline.append(event)
    print("mission     : %s" % mission.id)
    print("recipe      : %s -> agent %s" % (mission.recipe, mission.agent_id))
    print("status      : %s" % mission.status.value)

    if mission.status.value == "awaiting_approval":
        from atlas_kernel.mission.models import MissionStatus

        queued, event = service.transition(
            mission, MissionStatus.QUEUED, tenant=TENANT, actor=ACTOR,
            note="approved to run")
        timeline.append(event)
        mission = queued
        print("approved    : queued")

    print("\nwaiting for worker-healthcheck...")
    deadline = time.time() + 300
    last = ""
    while time.time() < deadline:
        time.sleep(8)
        current = next((m for m in service.fold(timeline.read(), tenant=TENANT)
                        if m["mission_id"] == mission.id), None)
        if current is None:
            continue
        if current["status"] != last:
            last = current["status"]
            print("   %-14s %s" % (last, (current.get("because") or "")[:56]))
        if current["status"] in ("complete", "failed", "cancelled", "blocked"):
            print("\nfinal       : %s" % current["status"])
            print("workspace   : %s" % (current.get("workspace") or "none"))
            print("commits     : %s" % (current.get("commits") or []))
            print("because     : %s" % (current.get("because") or ""))
            return 0 if current["status"] == "complete" else 1
    print("\nstill %s after 300s" % (last or "unclaimed"))
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
