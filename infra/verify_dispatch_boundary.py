#!/usr/bin/env python3
"""Proves the dispatch boundary: a Qevik mission worker is not an Atlas target.

The milestone this proves is *not* capability-matched dispatch. It is the
boundary that has to exist before dispatch is safe, in both directions:

  Atlas execution -> Qevik worker   `accepts_execution_dispatch`, declared
  unrouted mission -> every worker  removed from `mission_worker.queued`

Capability alone could not do the first. `Dispatcher._required_capability`
resolves anything outside `WorkerCapability` to `""`, `select_candidates` reads
`""` as *no constraint*, and the self-check role genuinely holds `filesystem`,
which is a real Atlas capability. So the candidate list for unconstrained work
was the Qevik workers and nothing else, and `filesystem` put a mission worker
ahead of `worker-local`.

No production row is mutated. Every worker this creates is synthetic and is
removed on the way out, including on failure.

Run:  python3 infra/verify_dispatch_boundary.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, "packages/kernel")
sys.path.insert(0, "infra")

import atlas_kernel.agents  # noqa: F401  (import order; breaks a cycle)
from sqlalchemy import text

import mission_worker as mw
from atlas_kernel.cluster.dispatcher import Dispatcher
from atlas_kernel.cluster.lease_manager import LeaseManager
from atlas_kernel.cluster.models import WorkerRegistration, WorkerState
from atlas_kernel.db import SessionLocal
from atlas_kernel.event_bus import EventBus
from atlas_kernel.repository import AtlasRepository

PASSED: list[str] = []
FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    (PASSED if ok else FAILED).append(label)
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}" + (f"  — {detail}" if detail else ""))


registry, heartbeats = mw._node_services()
repo, bus = AtlasRepository(), EventBus()
dispatcher = Dispatcher(registry, LeaseManager(repo, bus, registry), bus)

#: Everything this harness creates. Nothing else is ever written or removed.
MINE: list[str] = []


def candidates(capability: str) -> set[str]:
    return {c.worker.id for c in dispatcher.select_candidates(capability)}


def cleanup() -> None:
    if not MINE:
        return
    with SessionLocal() as session:
        session.execute(text("DELETE FROM atlas_worker_heartbeats "
                             "WHERE worker_id = ANY(:ids)"), {"ids": MINE})
        session.execute(text("DELETE FROM atlas_workers WHERE id = ANY(:ids)"),
                        {"ids": MINE})
        session.commit()


try:
    # ---------------------------------------------------------------- default
    print("\n-- an ordinary Atlas worker is unaffected -----------------------------")
    ordinary = registry.register(WorkerRegistration(
        worker_id="worker-boundary-ordinary", hostname="worker-boundary-ordinary",
        display_name="ordinary", capabilities=["image"], max_concurrency=1))
    MINE.append(ordinary.id)
    check("a registration that says nothing accepts dispatch",
          ordinary.accepts_execution_dispatch is True,
          "the default is True, so nothing that predates the field changes")
    check("...and it is offered work it advertises",
          ordinary.id in candidates("image"))
    check("...and unconstrained work too",
          ordinary.id in candidates(""),
          "this is the behaviour Atlas workers keep")

    # ------------------------------------------------------------- the worker
    print("\n-- a Qevik mission worker is not an execution target ------------------")
    identity = mw._register_node("worker-boundary-qevik", "publish")
    MINE.append(identity)
    node = registry.get(identity)
    check("it registered as a non-participant",
          node.accepts_execution_dispatch is False, identity)
    check("...while online, capable and heartbeating",
          node.status is WorkerState.ONLINE
          and node.capabilities == ["site-publish"]
          and node.last_heartbeat_at is not None,
          "excluded from placement is not absent, idle or unhealthy")
    check("...reporting the fingerprint of its own source",
          node.version == mw._source_fingerprint() and len(node.version) == 12,
          node.version)

    check("THE BOUNDARY: not a candidate for unconstrained work",
          identity not in candidates(""),
          "the route capability could not close")
    check("...nor for a capability it advertises",
          identity not in candidates("site-publish"))
    check("...nor for 'filesystem', the real collision",
          identity not in candidates("filesystem"),
          "self-check holds `filesystem`, which is a genuine Atlas capability")

    # The checks above pass trivially if selection returns nothing at all.
    check("NEGATIVE CONTROL: the ordinary worker is still offered that work",
          ordinary.id in candidates(""),
          "so the exclusion is the flag, not an empty cluster")

    # ------------------------------------------------- the idempotent branch
    print("\n-- re-registration keeps it, which is where this would rot ------------")
    again = mw._register_node("worker-boundary-qevik", "publish")
    check("a restart returns the same identity", again == identity, again)
    check("RE-REGISTRATION: still a non-participant",
          registry.get(identity).accepts_execution_dispatch is False,
          "`register` takes the model_copy branch for a row it has seen before")
    check("...and still not a candidate", identity not in candidates(""))

    # And the reverse, so the check above is not just reading a stuck value.
    flipped = registry.register(WorkerRegistration(
        worker_id=identity, hostname=identity, display_name="flip probe",
        capabilities=["site-publish"], max_concurrency=1,
        accepts_execution_dispatch=True))
    check("NEGATIVE CONTROL: re-registering as True does change it",
          flipped.accepts_execution_dispatch is True
          and identity in candidates(""),
          "so False was carried, not merely never written")
    mw._register_node("worker-boundary-qevik", "publish")
    check("...and registering as a worker again puts it back",
          registry.get(identity).accepts_execution_dispatch is False)

    # ------------------------------------------------------------ persistence
    print("\n-- it survives the database round trip --------------------------------")
    with SessionLocal() as session:
        stored = session.execute(
            text("SELECT accepts_execution_dispatch FROM atlas_workers WHERE id = :i"),
            {"i": identity}).scalar()
    check("the column holds False, not just the object in memory",
          stored is False, f"stored={stored!r}")
    check("...and reading it back gives False",
          repo.get_worker(identity).accepts_execution_dispatch is False,
          "positional row mapping, so a column in the wrong place shows here")

    # ------------------------------------------------- unrouted mission work
    #
    # Through the real `queued()`, not a copy of its filter. A harness that
    # re-implements the rule it is testing proves only that it can write the
    # rule twice.
    print("\n-- an unrouted mission is offered to nobody ----------------------------")
    from datetime import UTC, datetime

    from atlas_kernel.mission import service as msvc
    from atlas_kernel.mission.models import Mission, MissionStatus

    TENANT = "boundary-probe"

    def _event(mission: Mission) -> dict:
        return {"kind": msvc.KIND, "detail": mission.summary()}

    def _mission(mission_id: str, agent_id: str) -> Mission:
        return Mission(id=mission_id, tenant_id=TENANT, title=mission_id,
                       agent_id=agent_id, recipe="publish-website",
                       status=MissionStatus.QUEUED,
                       updated_at=datetime.now(UTC))

    class _Timeline:
        """Only what `queued` uses: a read() of events."""

        def __init__(self, events: list[dict]) -> None:
            self._events = events

        def read(self) -> list[dict]:
            return list(self._events)

    routed = _mission("m-routed", "site-publisher")
    unrouted = _mission("m-unrouted", "")
    timeline = _Timeline([_event(routed), _event(unrouted)])

    offered = {m.id for m in mw.queued(timeline, tenant=TENANT,
                                       agent_id="site-publisher")}
    check("the routed mission is offered to the worker it names",
          "m-routed" in offered, str(sorted(offered)))
    check("THE UNROUTED MISSION IS OFFERED TO NOBODY",
          "m-unrouted" not in offered,
          "absence of a requirement is not permission to run anywhere")

    for other in ("researcher", "website-builder", "self-check", "implementer"):
        got = {m.id for m in mw.queued(timeline, tenant=TENANT, agent_id=other)}
        check(f"...not to {other} either", "m-unrouted" not in got,
              str(sorted(got)) if got else "nothing offered")

    # If `queued` returned nothing at all the checks above would pass for the
    # wrong reason. It does not: the routed mission came back.
    check("NEGATIVE CONTROL: routing it makes it eligible again",
          "m-unrouted" in {m.id for m in mw.queued(
              _Timeline([_event(routed), _event(_mission("m-unrouted", "researcher"))]),
              tenant=TENANT, agent_id="researcher")},
          "so the exclusion is the missing agent, not a broken fold")

    # ---------------------------------------- the worker filter is a subset
    #
    # The worker keeps filtering by agent id, deliberately: removing it revived
    # two workers each claiming the other's mission. It is a redundant narrowing
    # and must never be a second authority, so what it offers has to be a subset
    # of what the scheduler already called dispatchable.
    print("\n-- the worker narrows the scheduler, it does not widen it --------------")
    from atlas_kernel.fabric import scheduler as sched
    from atlas_kernel.fabric.agents import Registry as AgentRegistry

    every = [_mission("m-pub", "site-publisher"), _mission("m-res", "researcher"),
             _mission("m-none", "")]
    full = _Timeline([_event(m) for m in every])
    folded = msvc.fold(full.read(), tenant=TENANT)
    routes = {str(m.get("mission_id")): str(m.get("agent_id")) for m in folded
              if m.get("agent_id")}
    plan = sched.plan(sched.demands_from(folded, agents=AgentRegistry(),
                                         agent_for=routes),
                      tenant=TENANT, concurrency=len(every))
    eligible = set(plan["dispatchable"])

    union: set[str] = set()
    for role in ("site-publisher", "researcher", "website-builder", "self-check",
                 "implementer"):
        union |= {m.id for m in mw.queued(full, tenant=TENANT, agent_id=role)}

    check("SUPERSET: scheduler candidates ⊇ worker candidates",
          union <= eligible,
          f"offered {sorted(union)} ⊆ dispatchable {sorted(eligible)}")
    check("...and the worker is a narrowing, not an equal authority",
          union <= eligible,
          "a worker may decline what the scheduler allowed; never the reverse")
    check("no worker is offered the unrouted mission", "m-none" not in union)

    # This was the gap: the scheduler called an unrouted mission dispatchable
    # while the worker declined it, so the worker's filter was the authority and
    # anything reading `dispatchable` -- the console among them -- was told work
    # would run that never could. Now closed at the scheduler.
    check("CLOSED: the scheduler no longer calls it dispatchable",
          "m-none" not in eligible,
          "eligibility decided once, where every caller reads it")
    blocked = {d["mission_id"] for d in plan["queues"]["BLOCKED"]}
    check("...it is blocked, and says why",
          "m-none" in blocked,
          next((d["why"] for d in plan["queues"]["BLOCKED"]
                if d["mission_id"] == "m-none"), ""))
    check("...while the routed missions stayed dispatchable",
          {"m-pub", "m-res"} <= eligible,
          "explicitly routed work is untouched")
    check("NEGATIVE CONTROL: the scheduler did name something dispatchable",
          bool(eligible), "so the subset above is not vacuous")

    # --------------------------------------------- production rows untouched
    print("\n-- production/fixture rows are left exactly as they were ---------------")
    # The property that matters is not "only this harness wrote False" -- other
    # harnesses run the real worker binary and legitimately register Qevik
    # workers. It is that **no Atlas worker** was changed. A row is a Qevik
    # mission worker iff it says so in its tags, which only `_register_node`
    # writes.
    with SessionLocal() as session:
        strays = session.execute(text(
            "SELECT id FROM atlas_workers WHERE NOT accepts_execution_dispatch "
            "AND NOT (tags @> '[\"qevik-mission-worker\"]'::jsonb)")).scalars().all()
        atlas_rows = session.execute(text(
            "SELECT count(*) FROM atlas_workers "
            "WHERE NOT (tags @> '[\"qevik-mission-worker\"]'::jsonb)")).scalar()
    check("no Atlas worker was set to non-participating",
          not strays, str(list(strays)) if strays else f"{atlas_rows} Atlas row(s), all still True")
    check("NEGATIVE CONTROL: there were Atlas rows to get this wrong on",
          atlas_rows > 0, f"{atlas_rows} row(s) without the Qevik tag")
finally:
    cleanup()

print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
