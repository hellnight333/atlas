#!/usr/bin/env python3
"""Proves the scheduler alone answers "can this be dispatched, and to whom?".

Selection is a pure function of stated facts -- a demand and a tuple of node
snapshots -- so most of this needs no database at all. Where production has
real evidence it is used; where production has never exercised a case, the
control is synthetic and **says so** rather than implying the world proved it.

What production does not exercise today, and therefore cannot prove:
  * two workers eligible for one mission (each recipe matches exactly one node)
  * any placement other than EITHER (every registered agent declares EITHER)
  * a capability subset that is a strict subset (each recipe needs what one
    node advertises, no more)

Run:  python3 infra/verify_capability_dispatch.py
"""
from __future__ import annotations

import sys

sys.path.insert(0, "packages/kernel")
sys.path.insert(0, "infra")

import atlas_kernel.agents  # noqa: F401  (import order; breaks a cycle)
from atlas_kernel.fabric import recipes as recipe_registry
from atlas_kernel.fabric.agents import Placement
from atlas_kernel.fabric.agents import Registry as AgentRegistry
from atlas_kernel.fabric.scheduler import (
    Demand,
    NodeSnapshot,
    Queue,
    _tools_for,
    decide,
    eligible,
    plan,
)
from atlas_kernel.fabric.tools import for_agent

PASSED: list[str] = []
FAILED: list[str] = []
TENANT = "capability-probe"


def check(label: str, ok: bool, detail: str = "") -> None:
    (PASSED if ok else FAILED).append(label)
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}" + (f"  — {detail}" if detail else ""))


def node(name: str, serves: str, caps: set[str], **over) -> NodeSnapshot:
    return NodeSnapshot(worker_name=name, serves=serves,
                        capabilities=frozenset(caps),
                        placements=frozenset(over.pop("placements", {"either"})),
                        node_id=over.pop("node_id", f"host:{name}"), **over)


def demand(**over) -> Demand:
    base = {"mission_id": "m1", "tenant_id": TENANT, "title": "work",
            "agent_id": "site-publisher", "required_tools": ("site-publish",)}
    return Demand(**{**base, **over})


# ============================================================ production shape
print("\n-- the four production workers, as they really are ---------------------")
# Capabilities exactly as the production rows report them.
PROD = (
    node("worker-1", "self-check", {"filesystem", "shell"}),
    node("worker-research", "researcher", {"dns", "http-fetch"}),
    node("worker-delivery", "website-builder", {"website-generator"}),
    node("worker-publish", "site-publisher", {"site-publish"}),
)
PROD_RECIPES = ("publish-website", "verify-recorded-websites",
                "discover-dubai-dental-osm", "deliver-website",
                "execution-canary")

for rid in PROD_RECIPES:
    recipe = recipe_registry.get(rid)
    fit = eligible(demand(agent_id=recipe.agent_id,
                          required_tools=_tools_for(rid)), PROD)
    check(f"{rid} goes to exactly one worker", len(fit) == 1,
          f"{fit[0].worker_name if fit else 'NOBODY'} for {list(_tools_for(rid))}")

check("...and every recipe's tools are a subset of its agent's",
      all(set(recipe_registry.get(r).tools)
          <= {t.id for t in for_agent(AgentRegistry().get(
              recipe_registry.get(r).agent_id))}
          for r in PROD_RECIPES),
      "so dispatch never has to widen what an agent declared")

# ================================================== capability subset matching
print("\n-- capability subset matching ------------------------------------------")
generalist = node("worker-many", "researcher",
                  {"dns", "http-fetch", "site-publish", "website-generator"})
specialist = node("worker-few", "researcher", {"dns", "http-fetch"})

check("a worker advertising a superset is eligible",
      generalist in eligible(demand(agent_id="researcher",
                                    required_tools=("http-fetch",)),
                             (generalist,)))
check("NEGATIVE CONTROL: one missing tool makes it ineligible",
      not eligible(demand(agent_id="researcher",
                          required_tools=("http-fetch", "site-publish")),
                   (specialist,)),
      "subset, not overlap -- one match out of two is not a match")
check("a mission requiring nothing still binds to its agent",
      [n.worker_name for n in eligible(
          demand(agent_id="researcher", required_tools=()),
          (specialist, node("worker-pub", "site-publisher", {"site-publish"})))]
      == ["worker-few"],
      "empty is not a wildcard: a plan-based mission is not open to everyone")

# ============================================== specificity / load / id order
print("\n-- ordering: specificity, then load, then id ---------------------------")
print("     SYNTHETIC: no production recipe matches two workers, so production")
print("     has never exercised any of this.")
order = eligible(demand(agent_id="researcher", required_tools=("http-fetch",)),
                 (generalist, specialist))
check("the most specific worker wins", order[0].worker_name == "worker-few",
      " < ".join(n.worker_name for n in order))
check("...leaving the generalist free for work only it can take",
      order[1].worker_name == "worker-many")

busy = node("worker-a", "researcher", {"dns", "http-fetch"}, load=1,
            node_id="host:a")
idle = node("worker-b", "researcher", {"dns", "http-fetch"}, load=0,
            node_id="host:b")
tie = eligible(demand(agent_id="researcher", required_tools=("http-fetch",)),
               (busy, idle))
check("equally specific: the least loaded wins",
      tie[0].worker_name == "worker-b", f"load {tie[0].load} before {tie[1].load}")

same_a = node("worker-x", "researcher", {"dns", "http-fetch"}, node_id="host:z")
same_b = node("worker-y", "researcher", {"dns", "http-fetch"}, node_id="host:a")
last = eligible(demand(agent_id="researcher", required_tools=("http-fetch",)),
                (same_a, same_b))
check("identical otherwise: node id breaks the tie, deterministically",
      last[0].node_id == "host:a", " < ".join(n.node_id for n in last))
check("NEGATIVE CONTROL: id is the last word, never the first",
      eligible(demand(agent_id="researcher", required_tools=("http-fetch",)),
               (node("worker-broad", "researcher",
                     {"dns", "http-fetch", "shell"}, node_id="host:aaa"),
                node("worker-narrow", "researcher",
                     {"dns", "http-fetch"}, node_id="host:zzz"))
               )[0].worker_name == "worker-narrow",
      "the alphabetically later node wins because it is more specific")

# ====================================================== stale and busy workers
print("\n-- a stale worker is not chosen, and keeps what it holds ---------------")
stale = node("worker-gone", "site-publisher", {"site-publish"}, fresh=False)
check("a stale worker is not eligible", not eligible(demand(), (stale,)))
check("...and the reason says so, not 'no such worker'",
      "stopped reporting" in decide(demand(), nodes=(stale,)).why,
      decide(demand(), nodes=(stale,)).why)
check("NEGATIVE CONTROL: the same worker, fresh, is chosen",
      decide(demand(), nodes=(node("worker-gone", "site-publisher",
                                   {"site-publish"}),)).worker == "worker-gone")

full = node("worker-busy", "site-publisher", {"site-publish"}, free=False)
check("a worker with no free slot is not chosen", not eligible(demand(), (full,)))
check("...and that reads as busy, not as missing",
      "busy" in decide(demand(), nodes=(full,)).why,
      decide(demand(), nodes=(full,)).why)

# =================================================== placement and the tag
print("\n-- placement -----------------------------------------------------------")
print("     SYNTHETIC: every registered agent declares EITHER, so production")
print("     has never dispatched LOCAL or CLOUD work.")
cloud = node("worker-cloud", "site-publisher", {"site-publish"},
             placements={"cloud"})
local = node("worker-local-machine", "site-publisher", {"site-publish"},
             placements={"local"})
check("LOCAL work does not go to a cloud machine",
      not eligible(demand(placement=Placement.LOCAL), (cloud,)))
check("...but does go to a local one",
      eligible(demand(placement=Placement.LOCAL), (local,))[0].worker_name
      == "worker-local-machine")
check("CLOUD work does not go to the operator's machine",
      not eligible(demand(placement=Placement.CLOUD), (local,)))
check("EITHER work goes to either", len(eligible(
    demand(placement=Placement.EITHER), (cloud, local))) == 2)
check("...and the mismatch is reported as a placement problem",
      "cloud" in decide(demand(placement=Placement.CLOUD), nodes=(local,)).why,
      decide(demand(placement=Placement.CLOUD), nodes=(local,)).why)

# ========================================================= unrouted missions
print("\n-- unrouted work -------------------------------------------------------")
check("a mission naming no agent is blocked before selection",
      decide(demand(agent_id=""), nodes=PROD).queue is Queue.BLOCKED)
check("...and names nobody", decide(demand(agent_id=""), nodes=PROD).worker == "")
check("NEGATIVE CONTROL: the same mission, routed, is chosen",
      decide(demand(), nodes=PROD).worker == "worker-publish")

# ============================================ nothing supplied vs nothing there
print("\n-- 'no information' is not 'no workers' --------------------------------")
check("no nodes supplied: the queue is decided as before, nobody named",
      decide(demand(), nodes=None).queue is Queue.NOW
      and decide(demand(), nodes=None).worker == "")
check("an empty tuple means there really are none, and blocks",
      decide(demand(), nodes=()).queue is Queue.BLOCKED,
      decide(demand(), nodes=()).why)
check("...which is the distinction a caller that forgot to pass nodes needs",
      decide(demand(), nodes=None).queue
      is not decide(demand(), nodes=()).queue)

# ================================================================ through plan
print("\n-- through plan(), which is what every caller reads --------------------")
out = plan((demand(mission_id="m-pub"),
            demand(mission_id="m-res", agent_id="researcher",
                   required_tools=("http-fetch",)),
            demand(mission_id="m-orphan", agent_id="")),
           tenant=TENANT, concurrency=5, nodes=PROD)
check("each dispatchable mission is assigned a worker",
      out["assigned"] == {"m-pub": "worker-publish", "m-res": "worker-research"},
      str(out["assigned"]))
check("...the unrouted one is dispatchable to nobody",
      "m-orphan" not in out["dispatchable"]
      and "m-orphan" not in out["assigned"])
check("...and appears as BLOCKED with a reason",
      [d["mission_id"] for d in out["queues"]["BLOCKED"]] == ["m-orphan"])
check("every assignment names a worker that was actually eligible",
      all(w in {n.worker_name for n in PROD} for w in out["assigned"].values()),
      "no name is invented")

print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
