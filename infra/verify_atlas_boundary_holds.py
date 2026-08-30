#!/usr/bin/env python3
"""Guards a CLOSED finding. It used to demonstrate an open one.

CLOSED on 2026-08-28 by `WorkerNode.accepts_execution_dispatch`, declared False
by Qevik mission workers at registration. Until then this file passed, and its
passing was the finding. It now asserts the opposite, so a regression brings it
back rather than leaving the hazard to be rediscovered.

Registering Qevik mission workers as `atlas_kernel.cluster` nodes -- the
milestone that adopted the existing lineage instead of building a second one --
also makes them eligible targets for Atlas *execution* dispatch, which they will
never collect. They poll the Qevik mission queue, not the Atlas execution queue.

The route is not capability matching, which correctly excludes them:

    Dispatcher._required_capability   any capability outside `WorkerCapability`
                                      resolves to ""
    Dispatcher.select_candidates      `if capability and not self._serves(...)`
                                      -- "" is read as *no constraint*

That rule is deliberate (its docstring: unroutable work should fail at the
provider rather than stall forever waiting for a machine that cannot exist).
Its consequence, once non-Atlas nodes share the registry, is that unconstrained
work can be leased to a machine that never runs it.

`max_concurrency=0` does not express "no Atlas slots": `WorkerRegistry.register`
floors it with `max(1, registration.max_concurrency)`.

`max_concurrency=0` is still not expressible -- `WorkerRegistry.register` floors
it with `max(1, ...)` -- which is why the fix is a declared property rather than
a capacity of zero. That floor is asserted below, so the day it changes, the
reasoning behind the property is not quietly invalidated.

Run:  python3 infra/verify_atlas_boundary_holds.py
"""
from __future__ import annotations

import sys

sys.path.insert(0, "packages/kernel")
sys.path.insert(0, "infra")

import atlas_kernel.agents  # noqa: F401  (import order; breaks a cycle)
from sqlalchemy import text

import mission_worker as mw
from atlas_kernel.cluster.dispatcher import Dispatcher
from atlas_kernel.cluster.lease_manager import LeaseManager
from atlas_kernel.db import SessionLocal
from atlas_kernel.event_bus import EventBus
from atlas_kernel.repository import AtlasRepository

PASSED: list[str] = []
FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    (PASSED if ok else FAILED).append(label)
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}" + (f"  — {detail}" if detail else ""))


from atlas_kernel.agents.plan_models import PlanStep
from atlas_kernel.agents.schedule_models import ScheduleQueueEntry


def _entry_with_capability(capability: str) -> ScheduleQueueEntry:
    """A real queue entry, so the resolution below is the production path."""
    return ScheduleQueueEntry(
        capability=capability,
        plan_step=PlanStep(description=f"step needing {capability}",
                           capability=capability,
                           expected_output="an artefact"))


registry, _ = mw._node_services()
repo, bus = AtlasRepository(), EventBus()
dispatcher = Dispatcher(registry, LeaseManager(repo, bus, registry), bus)

identity = mw._register_node("worker-hazard-repro", "publish")
try:
    node = registry.get(identity)

    print("\n-- the worker, as registered ------------------------------------------")
    check("it advertises only Qevik tools", node.capabilities == ["site-publish"],
          str(node.capabilities))
    check("...and it offers an Atlas slot", node.max_concurrency == 1)

    # Zero slots is the obvious way to say "runs no Atlas work". It is not
    # expressible: registration floors it. Shown rather than asserted from
    # reading the source.
    from atlas_kernel.cluster.models import WorkerRegistration

    floored = registry.register(WorkerRegistration(
        worker_id="worker-hazard-floor", hostname="worker-hazard-floor",
        display_name="floor probe", max_concurrency=0))
    check("registering 0 slots is silently floored to 1", floored.max_concurrency == 1,
          "`max(1, registration.max_concurrency)` in WorkerRegistry.register")

    def candidates(capability: str) -> set[str]:
        return {c.worker.id for c in dispatcher.select_candidates(capability)}

    print("\n-- capability matching excludes it, correctly --------------------------")
    check("not a candidate for 'image'", identity not in candidates("image"))
    check("not a candidate for 'video'", identity not in candidates("video"))

    print("\n-- and unconstrained work no longer reaches it -------------------------")
    unconstrained = candidates("")
    check("CLOSED: not a candidate for work with no capability constraint",
          identity not in unconstrained,
          "the route capability matching could never have closed")
    check("...because it declares that it does not take executions",
          registry.get(identity).accepts_execution_dispatch is False)
    check("NEGATIVE CONTROL: an ordinary worker still is a candidate",
          "worker-hazard-floor" in unconstrained,
          "so the exclusion is the declaration, not an empty cluster")
    # Why "" is the realistic case and not a contrived one: the resolution runs
    # on a real queue entry carrying a capability Atlas does not know.
    entry = _entry_with_capability("site-publish")
    resolved = dispatcher._required_capability(entry)
    check("...and a real entry naming an unknown capability resolves to ''",
          resolved == "", f"'site-publish' -> {resolved!r}")
    check("NEGATIVE CONTROL: a known capability does not",
          dispatcher._required_capability(_entry_with_capability("image")) == "image")
finally:
    with SessionLocal() as session:
        session.execute(text("DELETE FROM atlas_worker_heartbeats WHERE worker_id = :i"),
                        {"i": identity})
        session.execute(text("DELETE FROM atlas_workers WHERE id = ANY(:ids)"),
                        {"ids": [identity, "worker-hazard-floor"]})
        session.commit()

print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
print("\nPASSING means the boundary still holds." if not FAILED else
      "\nFAILING means a Qevik worker can be handed Atlas work again.")
