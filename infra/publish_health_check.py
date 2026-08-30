"""Review an artefact, authorise publication, and let the publisher run.

Run on the control-plane host, as the `qevik` user (the scratch is theirs).

Mirrors the two existing routes rather than inventing a path: `POST
/{id}/review` records the decision, `POST /{id}/publish` records the
authorisation and creates the publication mission. The publishing itself is
done by `worker-publish` through `publish-website`, which is the mechanism
already proven by every site on sites.qevik.ai.

Two decisions, kept two. Accepting the work says it is good; authorising
publication puts it in front of strangers, and the same person answers for them
differently.
"""
from __future__ import annotations

import sys
import time

from atlas_kernel.mission import origins, publication as bridge, service
from atlas_kernel.mission.timeline import Timeline
from atlas_kernel.opportunity.repository import OpportunityRepository
from atlas_kernel.opportunity.tenancy import ALL_TENANTS

TENANT = "tenant-qevik"
ACTOR = "verification"


def main(mission_id: str) -> int:
    memory = OpportunityRepository()
    timeline = Timeline("/var/lib/qevik/control/missions.jsonl")

    summary = next((m for m in service.fold(timeline.read(), tenant=TENANT)
                    if m["mission_id"] == mission_id), None)
    if summary is None:
        print("no such mission")
        return 1
    commit = (summary.get("commits") or [""])[-1]
    signal = memory.get_signal(summary["signal_id"], tenant=TENANT)
    business = memory.get_business(signal["business_id"], tenant=ALL_TENANTS)
    print("mission  : %s" % mission_id)
    print("business : %s" % business.name[:56])
    print("commit   : %s" % commit[:12])

    # 1. The review. Accepting the artefact, on the commit that was read.
    review = memory.record_review(
        mission_id=mission_id, business_id=business.id,
        signal_id=signal["id"], commit=commit, decision="accepted",
        actor=ACTOR, note="health check: every claim carries its evidence",
        tenant=TENANT)
    print("reviewed : %s" % review.get("decision"))

    # 2. The authorisation, and the mission that carries it out.
    site_id = bridge.site_for(business.id)
    approval = memory.approve_publication(
        mission_id=mission_id, business_id=business.id,
        signal_id=signal["id"], commit=commit, site_id=site_id,
        actor=ACTOR, note="publishing the health check", tenant=TENANT)
    print("site     : %s" % site_id)

    origin = origins.Registry.build().resolve(origins.EMPTY_NAME)
    publisher, events = bridge.enqueue(approval, signal, tenant=TENANT,
                                       origin=origin, actor=ACTOR,
                                       business_id=business.id)
    for event in events:
        timeline.append(event)
    print("publisher: %s (%s)" % (publisher.id, publisher.status.value))

    if publisher.status.value == "awaiting_approval":
        from atlas_kernel.mission.models import MissionStatus

        queued, event = service.transition(
            publisher, MissionStatus.QUEUED, tenant=TENANT, actor=ACTOR,
            note="authorised to publish")
        timeline.append(event)
        publisher = queued
        print("           queued")

    print("\nwaiting for worker-publish...")
    deadline = time.time() + 300
    last = ""
    while time.time() < deadline:
        time.sleep(8)
        current = next((m for m in service.fold(timeline.read(), tenant=TENANT)
                        if m["mission_id"] == publisher.id), None)
        if current is None:
            continue
        if current["status"] != last:
            last = current["status"]
            print("   %-14s %s" % (last, (current.get("because") or "")[:56]))
        if current["status"] in ("complete", "failed", "cancelled", "blocked"):
            print("\nfinal    : %s" % current["status"])
            print("because  : %s" % (current.get("because") or ""))
            for record in memory.publications_for(mission_id, tenant=TENANT):
                print("published: %s" % record.get("url"))
            return 0 if current["status"] == "complete" else 1
    print("\nstill %s after 300s" % (last or "unclaimed"))
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
