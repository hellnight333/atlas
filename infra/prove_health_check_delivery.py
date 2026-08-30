"""Prove the health check reaches an artefact through the real chain.

Run on the control-plane host. Creates one real mission and lets the real
worker run it: Mission -> Recipe -> Agent -> Tool -> Worker -> Artefact.

**Publishes nothing and contacts nobody.** The recipe's agent declares one
tool, `website-generator`, which is not a network tool, so this cannot reach
the internet even if it tried. Publication remains the separate outward act it
already is, with its own approval.

Mirrors `delivery.enqueue` exactly — create, transition, attach_plan — rather
than inventing a second way a mission comes into being. The one difference is
that the recipe is named here instead of derived from the opportunity's
suggested action, because no detector suggests a health check yet; that routing
is a product decision and is deliberately not made in this script.
"""
from __future__ import annotations

import sys
import time

from atlas_kernel.fabric import recipes
from atlas_kernel.mission import origins, service
from atlas_kernel.mission.models import MissionStatus
from atlas_kernel.opportunity.repository import OpportunityRepository
from atlas_kernel.opportunity.tenancy import ALL_TENANTS

TENANT = "tenant-qevik"
RECIPE = "deliver-health-check"
ACTOR = "verification"


def _timeline():
    """The same ledger the workers read."""
    from atlas_kernel.mission.timeline import Timeline

    return Timeline("/var/lib/qevik/control/missions.jsonl")


def main() -> int:
    memory = OpportunityRepository()
    recipe = recipes.get(RECIPE)

    # A real opportunity, about a business with a real audit behind it.
    chosen = None
    for signal in memory.open_signals(limit=60, tenant=TENANT):
        business = memory.get_business(signal["business_id"], tenant=ALL_TENANTS)
        if business is None:
            continue
        chosen = (signal, business)
        break
    if chosen is None:
        print("no open opportunity with a business behind it")
        return 1
    signal, business = chosen
    print("opportunity : %s" % signal["id"])
    print("business    : %s" % business.name)

    timeline = _timeline()
    origin = origins.Registry.build().resolve("qevik")

    mission, created = service.create(
        tenant=TENANT,
        title=f"Health check for {business.name}",
        description=(f"{recipe.does}\n\nCreated by {ACTOR} to prove the "
                     "delivery chain end to end."),
        requested_by=ACTOR,
        origin_name=origin.name,
        recipe=recipe.id,
        signal_id=signal["id"],
        approved_scope="a health check built from this business's own audit",
        evidence_fingerprints=tuple(signal.get("evidence_fingerprints") or ()))
    mission, planning = service.transition(
        mission, MissionStatus.PLANNING, tenant=TENANT, actor=ACTOR,
        note=f"health check for {signal['id']}")
    # `plan_for` is delivery's own, so the plan a policy decision is made about
    # is the same object the real path builds. Nothing is generated: the steps
    # were approved when the recipe was merged.
    from atlas_kernel.mission.delivery import plan_for

    mission, attached = service.attach_plan(
        mission, plan_for(recipe, signal), tenant=TENANT, actor=ACTOR,
        agent_id=recipe.agent_id,
        modifies_qevik_itself=origin.modifies_qevik_itself)

    for event in (created, planning, attached):
        timeline.append(event)
    print("mission     : %s" % mission.id)
    print("status      : %s" % mission.status.value)
    print("recipe      : %s -> agent %s" % (mission.recipe, mission.agent_id))

    if mission.status is MissionStatus.AWAITING_APPROVAL:
        approved, event = service.transition(
            mission, MissionStatus.QUEUED, tenant=TENANT, actor=ACTOR,
            note="approved for the delivery proof")
        timeline.append(event)
        mission = approved
        print("approved    : queued")

    print("\nwaiting for worker-healthcheck to claim it...")
    deadline = time.time() + 180
    last = ""
    while time.time() < deadline:
        time.sleep(6)
        current = next((m for m in service.fold(timeline.read(), tenant=TENANT)
                        if m["mission_id"] == mission.id), None)
        if current is None:
            continue
        if current["status"] != last:
            last = current["status"]
            print("   %-18s %s" % (last, (current.get("because") or "")[:52]))
        if current["status"] in ("complete", "failed", "cancelled", "blocked"):
            print("\nfinal       : %s" % current["status"])
            print("claimed by  : %s" % (current.get("claimed_by") or "nobody"))
            print("because     : %s" % (current.get("because") or ""))
            return 0 if current["status"] == "complete" else 1
    print("\nstill %s after 180s" % (last or "unclaimed"))
    return 1


if __name__ == "__main__":
    sys.exit(main())
