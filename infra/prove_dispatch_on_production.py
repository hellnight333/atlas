#!/usr/bin/env python3
"""Production evidence for capability-matched dispatch. Read-only.

Runs **on qevik-core-01**, against the real `atlas_workers` rows and the real
recipe registry. It creates no mission, claims nothing, dispatches nothing and
writes nothing: selection is a pure function of a demand and the node snapshots,
so it can be exercised in full without touching a queue.

Real business work is never started to manufacture evidence. Where a case does
not exist in production -- two eligible workers, a placement other than EITHER,
a busy worker -- the control is synthetic and says so.

Run on the host, with the environment read by systemd rather than by a shell
(a database password may contain any byte, and a shell would not survive it):
    systemd-run --wait --collect --pipe --quiet \\
      --property=EnvironmentFile=/opt/qevik/atlas.env \\
      --property=User=qevik --property=WorkingDirectory=/opt/qevik/atlas \\
      --setenv=PYTHONPATH=/opt/qevik/atlas/packages/kernel \\
      /opt/qevik/atlas/.venv/bin/python infra/prove_dispatch_on_production.py
"""
from __future__ import annotations

import sys

import atlas_kernel.agents  # noqa: F401  (import order; breaks a cycle)
from atlas_kernel.cluster.worker_registry import WorkerRegistry
from atlas_kernel.event_bus import EventBus
from atlas_kernel.fabric import recipes as recipe_registry
from atlas_kernel.fabric.agents import Placement
from atlas_kernel.fabric.scheduler import (
    Demand,
    NodeSnapshot,
    Queue,
    _tools_for,
    decide,
    eligible,
)
from atlas_kernel.mission.nodes import snapshots
from atlas_kernel.repository import AtlasRepository

PASSED: list[str] = []
FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    (PASSED if ok else FAILED).append(label)
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}" + (f"  — {detail}" if detail else ""))


def demand(**over) -> Demand:
    base = {"mission_id": "evidence", "tenant_id": "qevik", "title": "evidence"}
    return Demand(**{**base, **over})


NODES = snapshots()
REGISTRY = WorkerRegistry(AtlasRepository(), EventBus())
ALL_ROWS = REGISTRY.list_workers()

# ==================================================== the real cluster, as it is
print("\n-- the production cluster ----------------------------------------------")
check("the cluster was read", NODES is not None,
      f"{len(NODES or ())} mission worker(s) of {len(ALL_ROWS)} rows")
check("all four Qevik workers are present and reporting",
      len([n for n in NODES if n.fresh]) == 4,
      ", ".join(sorted(n.worker_name for n in NODES if n.fresh)))
check("each advertises the agent it serves",
      {n.worker_name: n.serves for n in NODES if n.fresh} ==
      {"worker-1": "self-check", "worker-research": "researcher",
       "worker-delivery": "website-builder", "worker-publish": "site-publisher"},
      str({n.worker_name: n.serves for n in NODES if n.fresh}))

# 11. non-participating / non-Qevik workers are excluded
print("\n-- workers that are not Qevik mission workers --------------------------")
tagged = {w.id for w in ALL_ROWS if "qevik-mission-worker" in w.tags}
untagged = [w for w in ALL_ROWS if w.id not in tagged]
check("the registry really does hold other workers",
      len(untagged) > 0, f"{len(untagged)}: {', '.join(sorted(w.id for w in untagged)[:4])}…")
check("...and none of them is a candidate for any mission",
      not ({n.worker_name for n in (NODES or ())} & {w.id for w in untagged}),
      "the allow-list admits only what declares itself")
check("...including the online test fixtures",
      all(w.id not in {n.node_id for n in (NODES or ())}
          for w in untagged if w.status.value == "online"),
      f"{len([w for w in untagged if w.status.value == 'online'])} online non-Qevik row(s)")

# 8 + 9. real recipes, real workers, and the tools that justify the choice
print("\n-- every production recipe, matched against the live cluster -----------")
for recipe_id in ("publish-website", "verify-recorded-websites",
                  "discover-dubai-dental-osm", "deliver-website",
                  "execution-canary"):
    recipe = recipe_registry.get(recipe_id)
    needs = _tools_for(recipe_id)
    verdict = decide(demand(agent_id=recipe.agent_id, required_tools=needs),
                     nodes=NODES)
    chosen = next((n for n in NODES if n.worker_name == verdict.worker), None)
    check(f"{recipe_id} is assigned to one worker",
          verdict.queue is Queue.NOW and chosen is not None,
          f"{verdict.worker or 'NOBODY'} — {verdict.why}")
    if chosen:
        check(f"...and {verdict.worker} declares every tool it needs",
              set(needs) <= chosen.capabilities,
              f"needs {list(needs)}, has {sorted(chosen.capabilities)}")
        check(f"...and serves the agent the approval named ({recipe.agent_id})",
              chosen.serves == recipe.agent_id)

# 13. unrouted work
print("\n-- an unrouted mission -------------------------------------------------")
orphan = decide(demand(agent_id=""), nodes=NODES)
check("a mission naming no agent is blocked", orphan.queue is Queue.BLOCKED)
check("...names nobody", orphan.worker == "")
check("...and says why", "no agent" in orphan.why, orphan.why)

# 10. stale workers, using the real rows with freshness flipped
print("\n-- a stale worker (real row, freshness flipped) ------------------------")
publisher = next(n for n in NODES if n.serves == "site-publisher")
stale = publisher.model_copy(update={"fresh": False})
pub_demand = demand(agent_id="site-publisher",
                    required_tools=_tools_for("publish-website"))
check("the real publisher, reporting, is chosen",
      decide(pub_demand, nodes=NODES).worker == publisher.worker_name)
check("...the same worker, stale, is not",
      decide(pub_demand, nodes=(stale,)).queue is Queue.BLOCKED)
check("...and the reason is that it stopped reporting, not that it is missing",
      "stopped reporting" in decide(pub_demand, nodes=(stale,)).why,
      decide(pub_demand, nodes=(stale,)).why)

# 5 + 6. the re-registration window
print("\n-- the window where workers have not re-registered yet -----------------")
none_yet = decide(pub_demand, nodes=())
check("with no worker registered, work is BLOCKED, not lost",
      none_yet.queue is Queue.BLOCKED, none_yet.why)
check("...and the reason names the agent nobody runs",
      "site-publisher" in none_yet.why)
check("...while 'nothing known' is still different from 'nothing there'",
      decide(pub_demand, nodes=None).queue is Queue.NOW,
      "a surface that cannot see the cluster does not block every mission")

# 12. the scheduler and the worker cannot disagree
print("\n-- one definition of who may run what ----------------------------------")
import inspect  # noqa: E402

import atlas_kernel.mission.nodes as nodes_module  # noqa: E402

worker_src = open("/opt/qevik/atlas/infra/mission_worker.py",
                  encoding="utf-8").read()
check("the worker does not compute eligibility itself",
      "from atlas_kernel.mission.nodes import snapshots" in worker_src
      and "def eligible" not in worker_src,
      "it reads the assignment the scheduler published")
check("...and reads its own name from `assigned`",
      'assigned.get(mission_id' in worker_src)
import atlas_kernel.mission.api as mission_api  # noqa: E402

check("the schedule view uses that same definition",
      "from .nodes import snapshots" in inspect.getsource(mission_api),
      "so the view cannot describe a dispatch that would not happen")
check("...and passes them into the same plan() dispatch uses",
      "nodes=_worker_nodes(request)" in inspect.getsource(mission_api),
      "one decision, read by both")
check("there is exactly one snapshot builder",
      inspect.getsource(nodes_module).count("def snapshots") == 1)

# 14. claims are untouched
print("\n-- existing mission claims ---------------------------------------------")
from sqlalchemy import text  # noqa: E402

from atlas_kernel.db import SessionLocal  # noqa: E402

with SessionLocal() as session:
    held = session.execute(text(
        "SELECT mission_id, claimed_by, claimed_at FROM qevik_mission_claim "
        "WHERE coalesce(claimed_by,'') <> ''")).fetchall()
    total = session.execute(text("SELECT count(*) FROM qevik_mission_claim")).scalar()
check("the claim table is intact", total is not None and total > 0, f"{total} row(s)")
check("...and the claim held before this deploy is still held",
      any(r[1] == "worker-1" for r in held),
      "; ".join(f"{r[0]} by {r[1]} since {r[2]}" for r in held) or "none held")
check("...selection never wrote to it",
      all(str(r[2]) < "2026-08-28" for r in held),
      "claimed_at predates today's deploy")

# ============================================ synthetic: what production lacks
print("\n-- synthetic controls (production does not exercise these) -------------")
a = NodeSnapshot(worker_name="w-broad", serves="researcher",
                 capabilities=frozenset({"dns", "http-fetch", "shell"}),
                 placements=frozenset({"either"}), node_id="synthetic:aaa")
b = NodeSnapshot(worker_name="w-narrow", serves="researcher",
                 capabilities=frozenset({"dns", "http-fetch"}),
                 placements=frozenset({"either"}), node_id="synthetic:zzz")
research = demand(agent_id="researcher", required_tools=("http-fetch",))
order = eligible(research, (a, b))
check("MULTIPLE ELIGIBLE: both qualify", len(order) == 2)
check("SPECIFICITY: the narrower worker wins",
      order[0].worker_name == "w-narrow",
      "and it sorts later by id, so id was not the reason")
busy = b.model_copy(update={"worker_name": "w-busy", "load": 1, "free": False})
check("BUSY: a worker with no free slot is not chosen",
      [n.worker_name for n in eligible(research, (busy, a))] == ["w-broad"])
loaded = b.model_copy(update={"worker_name": "w-loaded", "load": 1,
                              "node_id": "synthetic:aaa"})
check("LOAD: equally specific, the least loaded wins",
      eligible(research, (loaded, b))[0].worker_name == "w-narrow")
cloud_only = NodeSnapshot(worker_name="w-cloud", serves="site-publisher",
                          capabilities=frozenset({"site-publish"}),
                          placements=frozenset({"cloud"}), node_id="synthetic:c")
check("PLACEMENT: local work does not go to a cloud-only machine",
      not eligible(demand(agent_id="site-publisher",
                          required_tools=("site-publish",),
                          placement=Placement.LOCAL), (cloud_only,)))
check("...but cloud work does",
      eligible(demand(agent_id="site-publisher",
                      required_tools=("site-publish",),
                      placement=Placement.CLOUD), (cloud_only,))[0].worker_name
      == "w-cloud")
check("STRICT SUBSET: one missing tool is not a match",
      not eligible(demand(agent_id="researcher",
                          required_tools=("http-fetch", "site-publish")), (b,)))

print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
for name in FAILED:
    print(f"  FAILED  {name}")
sys.exit(1 if FAILED else 0)
