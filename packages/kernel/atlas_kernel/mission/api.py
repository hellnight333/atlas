"""Mission control over HTTP. A window onto the work, never the thing doing it.

§12. The temptation in a control plane is to let the route that starts a mission
also run it — it is one function call, the response can carry the result, and the
UI gets a progress bar for free. That design makes the browser tab load-bearing:
close it, lose the network, restart the API to deploy, and a mission dies
half-committed with a worktree left behind.

So **no handler in this module runs anything.** Every write appends an event and
returns. A worker somewhere else folds the timeline, sees a queued mission, and
picks it up on its own schedule. That is what makes "closing the UI does not stop
a running mission" a property of the architecture rather than a hope, and
`test_the_http_surface_cannot_run_a_mission` reads this file to keep it true.

Two smaller rules, both borrowed from the customer surface because they were
right there:

**The tenant comes from the authenticated user, never from the request.** There
is no argument in which to ask for somebody else's missions.

**Another tenant's mission is absent, not forbidden.** 404 and the same body for
both, since 403-versus-404 tells a caller which mission ids exist.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..auth.api import current_user, requires
from ..auth.models import Scope, User
from ..fabric import scheduler
from ..fabric.scheduler import demands_from
from ..opportunity.tenancy import TenantId
from . import service
from .models import Mission, MissionStatus

#: The single message for every miss, whether the mission does not exist or
#: belongs to somebody else.
NOT_FOUND = "no such mission"

#: What `create()` produces. Collection routes are declared before the
#: parameterised one, but order-of-declaration is a fragile thing to rest a
#: routing decision on — this makes `/api/missions/costs` impossible to read as
#: a mission id rather than merely unlikely to be.
MISSION_ID = re.compile(r"^mission-[0-9a-f]{12}$")

#: Where reports are written, relative to the deployment root. A path that
#: escapes this is refused: `report_path` arrives from an event, and an event is
#: data, so treating it as a filesystem instruction is how a read model becomes
#: an arbitrary-file-read.
REPORTS = Path("docs/qevik-docs/autonomous/reports")


def usable_credentials(request: Request, tenant: TenantId) -> frozenset[str]:
    """Which providers `resolve()` would hand over a secret for.

    The rule itself lives in `credentials.service.usable_for`, because the
    worker asks the same question and two implementations of "usable" would
    disagree on the day one of them mattered.
    """
    from ..credentials.service import usable_for
    return usable_for(getattr(request.app.state, "credentials", None),
                      tenant=tenant)


def tenant_balance(request: Request, tenant: TenantId) -> float | None:
    """What this tenant may still spend, or `None` when nothing meters it.

    `CreditService.balance()` rather than the ledger directly, because it also
    subtracts units already reserved and not yet settled — scheduling against
    the raw remaining would dispatch work whose money is already promised to a
    mission still running.

    A tenant with no plan yields `None`, which the scheduler reads as "no
    allowance configured" and does not block on. That is deliberately *not* what
    `budgets.reserve()` does, and the asymmetry is the point: refusing to start
    every mission because billing was never set up would break a single-tenant
    self-hosted deployment, where refusing to *spend* against an allowance
    nobody set is still correct.
    """
    credits = getattr(request.app.state, "credits", None)
    if credits is None:
        return None
    try:
        return credits.balance(tenant)
    except Exception:  # noqa: BLE001 - no plan, or no policy. Both are "unmetered".
        return None


def current_tenant(user: User = Depends(current_user)) -> TenantId:
    """The tenant this request acts for, or a refusal."""
    tenant = (user.tenant_id or "").strip()
    if not tenant:
        raise HTTPException(
            status_code=403,
            detail="this account is not attached to a tenant, so it has no "
                   "missions. Attach it to one rather than defaulting.")
    return tenant


def _events(request: Request) -> list:
    """The timeline this deployment folds missions from.

    Injected rather than imported, so the same routes serve a file-backed
    timeline in development and a database-backed one in production without
    this module knowing which.
    """
    source = getattr(request.app.state, "mission_events", None)
    return list(source or [])


def _append(request: Request, event: Any) -> None:
    """Put one event on the timeline, or refuse.

    No silent no-op when a sink is missing. A write route that appears to
    succeed and persists nothing is the failure mode where an operator approves
    a mission, sees a 200, and nothing ever runs.
    """
    sink = getattr(request.app.state, "mission_sink", None)
    if sink is None:
        raise HTTPException(
            status_code=503,
            detail="no mission timeline is configured to write to, so this "
                   "would have been accepted and lost")
    sink(event)


def _folded(request: Request, tenant: TenantId) -> list[dict]:
    return service.fold(_events(request), tenant=tenant)


def _one(request: Request, mission_id: str, tenant: TenantId) -> dict:
    if not MISSION_ID.match(mission_id):
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    for summary in _folded(request, tenant):
        if summary.get("mission_id") == mission_id:
            return summary
    raise HTTPException(status_code=404, detail=NOT_FOUND)


def _rehydrate(summary: dict, tenant: TenantId) -> Mission:
    try:
        return service.rehydrate(summary, tenant=tenant)
    except service.NotPermitted as error:  # pragma: no cover - fold scopes first
        raise HTTPException(status_code=404, detail=NOT_FOUND) from error


# ============================================ what a cost summary may claim

def costs(missions: list[dict]) -> dict:
    """What the work cost, and how much of that is actually known.

    Summing the invocations that reported a cost gives a number that reads as
    the total and is really a floor. So the floor is labelled a floor, and the
    calls that reported nothing are counted beside it rather than folded in as
    zero — a missing cost is not a free call, and the one number in this system
    nobody can check is a fabricated exact one.
    """
    reported = estimated = 0.0
    unknown = priced = 0
    currencies: set[str] = set()
    for mission in missions:
        for call in mission.get("invocations") or []:
            status = call.get("cost_status", "UNKNOWN")
            cost = call.get("cost")
            if cost is None:
                unknown += 1
                continue
            priced += 1
            currencies.add(call.get("currency", "") or "")
            if status == "REPORTED":
                reported += float(cost)
            else:
                estimated += float(cost)

    known = reported + estimated
    return {
        "reported": round(reported, 6),
        "estimated": round(estimated, 6),
        "known_total": round(known, 6),
        "priced_calls": priced,
        "unpriced_calls": unknown,
        # Mixed currencies would make the sum meaningless, so say so rather than
        # adding dirhams to dollars behind a single figure.
        "currency": next(iter(currencies)) if len(currencies) == 1 else "",
        "mixed_currencies": len(currencies) > 1,
        "complete": unknown == 0 and priced > 0,
        "note": ("every call reported a cost" if unknown == 0 and priced
                 else f"{unknown} call(s) reported no cost. The total is a "
                      "floor, not the amount spent."),
    }


def blockers(missions: list[dict]) -> dict:
    """What is stopping work, grouped by class rather than listed as sentences.

    A credential blocker and an architecture blocker are both "blocked" and
    almost nothing else in common: one is a person's five minutes, the other is
    a design decision. Grouping by kind is what turns a stuck list into a list
    somebody can act on.
    """
    by_kind: dict[str, list[dict]] = {}
    for mission in missions:
        for blocker in mission.get("blockers") or []:
            entry = {**blocker, "mission_id": mission.get("mission_id"),
                     "title": mission.get("title", "")}
            by_kind.setdefault(blocker.get("kind", "UNKNOWN"), []).append(entry)

    stopped = [m for m in missions
               if m.get("status") == MissionStatus.BLOCKED.value]
    return {
        "by_kind": {kind: found for kind, found in sorted(by_kind.items())},
        "counts": {kind: len(found) for kind, found in sorted(by_kind.items())},
        "blocked_missions": [
            {"mission_id": m.get("mission_id"), "title": m.get("title", ""),
             "blockers": m.get("blockers") or []} for m in stopped],
        "total": sum(len(f) for f in by_kind.values()),
    }


class Submission(BaseModel):
    """A request for work. Qevik decides the steps; this is not a plan."""

    title: str = Field(min_length=3, max_length=300)
    description: str = Field(default="", max_length=8000)
    priority: int = 0
    #: Which repository this is about, **by name**. A key from the worker's
    #: allow-list, never a path — see `mission/origins.py`. Not validated here:
    #: the registry is built by the worker from deployment configuration this
    #: process does not have, and a name the worker cannot resolve blocks the
    #: mission there with the reason attached. Empty means Qevik's own source,
    #: which needs a person.
    origin: str = Field(default="", max_length=64)


class Decision(BaseModel):
    """An operator's answer about one mission.

    No `decided_by`. The decider is the authenticated session, and a field for
    it would be a field to lie in.
    """

    note: str = Field(default="", max_length=2000)


class Proposal(BaseModel):
    """Which registered agent should propose the plan.

    Named rather than defaulted: "whichever agent the system picked" is not
    something a person can approve, because they cannot tell what it was.
    """

    agent: str = Field(min_length=1, max_length=64)


class Deferral(BaseModel):
    """When a mission may start, and why it was held.

    `reason` is required rather than optional. A deferral without one is
    indistinguishable from a queue that is simply long, which is the exact
    confusion the SCHEDULED queue exists to remove.
    """

    until: datetime
    reason: str = Field(min_length=3, max_length=500)


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api/missions", tags=["missions"])

    # -------------------------------------------------- collection views
    # Declared before `/{mission_id}`, and made unambiguous by MISSION_ID.

    @router.get("")
    def listing(request: Request, status: str = "",
                tenant: TenantId = Depends(current_tenant),
                _: User = Depends(requires(Scope.READ))) -> dict:
        """Every mission this tenant has, newest first."""
        found = _folded(request, tenant)
        if status:
            wanted = {s.strip() for s in status.split(",") if s.strip()}
            unknown = wanted - {s.value for s in MissionStatus}
            if unknown:
                raise HTTPException(
                    status_code=400,
                    detail=f"unknown status: {', '.join(sorted(unknown))}")
            found = [m for m in found if m.get("status") in wanted]
        return {
            "missions": found,
            "counts": {
                "total": len(found),
                "running": sum(1 for m in found if m.get("claimed_by")),
                "awaiting_approval": sum(
                    1 for m in found
                    if m.get("status") == MissionStatus.AWAITING_APPROVAL.value),
                "blocked": sum(1 for m in found
                               if m.get("status") == MissionStatus.BLOCKED.value),
            },
        }

    @router.get("/costs")
    def cost_summary(request: Request, tenant: TenantId = Depends(current_tenant),
                     _: User = Depends(requires(Scope.READ))) -> dict:
        return costs(_folded(request, tenant))

    @router.get("/blockers")
    def blocker_summary(request: Request,
                        tenant: TenantId = Depends(current_tenant),
                        _: User = Depends(requires(Scope.READ))) -> dict:
        return blockers(_folded(request, tenant))

    @router.get("/actions")
    def actions(request: Request, tenant: TenantId = Depends(current_tenant),
                _: User = Depends(requires(Scope.READ))) -> dict:
        """What is waiting on a person.

        Delegated to the control plane rather than derived again here. Two
        places computing "what does the human still owe us" is two places to
        disagree, and the one that disagrees quietly is the one in the UI.
        """
        from .. import controlplane
        from ..publication import ConnectionStore

        store = getattr(request.app.state, "connections", None) or ConnectionStore()
        return controlplane.centre(store=store, tenant=tenant)

    @router.get("/schedule")
    def schedule(request: Request, concurrency: int = 1, local_worker: bool = False,
                 tenant: TenantId = Depends(current_tenant),
                 _: User = Depends(requires(Scope.READ))) -> dict:
        """What would run next, and why everything else would not.

        A view, not a command: nothing here claims, dispatches or transitions
        anything. `dispatchable` is the scheduler's advice, and the atomic claim
        remains the single place two workers can race — so a stale page cannot
        start work twice by being refreshed.
        """
        found = _folded(request, tenant)
        done = frozenset(m["mission_id"] for m in found
                         if m.get("status") == MissionStatus.COMPLETE.value)
        # Which agent each mission needs, recorded when its plan was attached.
        # Without it every demand looked like it required no credentials, so
        # this view showed a mission as dispatchable that the worker would hold.
        demands = demands_from(found,
                               agent_for={str(m.get("mission_id", "")):
                                          str(m.get("agent_id", "")) for m in found},
                               connected=usable_credentials(request, tenant),
                               remaining_units=tenant_balance(request, tenant))
        return scheduler.plan(demands, tenant=tenant, done=done,
                              local_worker=local_worker,
                              concurrency=max(1, min(concurrency, 32)))

    # -------------------------------------------------- one mission

    @router.get("/{mission_id}")
    def detail(mission_id: str, request: Request,
               tenant: TenantId = Depends(current_tenant),
               _: User = Depends(requires(Scope.READ))) -> dict:
        return _one(request, mission_id, tenant)

    @router.get("/{mission_id}/history")
    def transitions(mission_id: str, request: Request,
                    tenant: TenantId = Depends(current_tenant),
                    _: User = Depends(requires(Scope.READ))) -> dict:
        """Every transition, oldest first, never collapsed.

        Establishes the mission first. Reading history for an id that folds to
        nothing would return an empty list either way — and an empty list for
        "not yours" versus "no such mission" is the same leak in a quieter form.
        """
        _one(request, mission_id, tenant)
        return {"mission_id": mission_id,
                "history": service.history(_events(request), mission_id,
                                           tenant=tenant)}

    @router.get("/{mission_id}/report")
    def report(mission_id: str, request: Request,
               tenant: TenantId = Depends(current_tenant),
               _: User = Depends(requires(Scope.READ))) -> dict:
        """The written report, if the mission produced one.

        `report_path` comes off an event, which is data. It is resolved under
        the reports directory and refused if it escapes — a read model that
        opens whatever path an event names is an arbitrary-file-read with extra
        steps.
        """
        summary = _one(request, mission_id, tenant)
        raw = (summary.get("report_path") or "").strip()
        if not raw:
            raise HTTPException(
                status_code=404,
                detail="this mission has not produced a report")

        # The root the *worker* wrote under, not the repository root.
        #
        # These were the same expression and are not the same thing: a worker
        # started with `--reports <dir>` records a path relative to that
        # directory, while this resolved it against the repository. The report
        # existed, the mission pointed at it, and the console said "no report" —
        # found by running the whole path end to end rather than by reading it.
        configured = (getattr(request.app.state, "reports_root", None)
                      or getattr(request.app.state, "repository_root", None)
                      or ".")
        root = Path(str(configured)).resolve()
        reports = (root / REPORTS).resolve()
        candidate = (root / raw).resolve()
        if not candidate.is_relative_to(reports) or not candidate.is_file():
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        return {"mission_id": mission_id, "path": raw,
                "report": candidate.read_text(encoding="utf-8")}

    # -------------------------------------------------- writes append, only

    @router.post("", status_code=201)
    def submit(body: Submission, request: Request,
               tenant: TenantId = Depends(current_tenant),
               user: User = Depends(requires(Scope.EXECUTE))) -> dict:
        """Record a request. Nothing runs from this.

        The mission lands in DRAFT and stays there until something plans it and
        a person approves the plan. A submission that went straight to QUEUED
        would let anyone holding EXECUTE start unreviewed work by choosing a
        title carefully.
        """
        try:
            mission, event = service.create(
                tenant=tenant, title=body.title, description=body.description,
                requested_by=user.username, priority=body.priority,
                origin_name=body.origin)
        except service.NotPermitted as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        _append(request, event)
        return mission.summary()

    @router.post("/{mission_id}/plan")
    def propose(mission_id: str, body: Proposal, request: Request,
                tenant: TenantId = Depends(current_tenant),
                user: User = Depends(requires(Scope.EXECUTE))) -> dict:
        """Ask a registered agent to propose a plan. It does not queue anything.

        The missing link in the control plane: a mission could be submitted and
        approved here, but only *planned* through chat — so anything not driven
        by a conversation had no way to become executable.

        The agent **proposes**. This route attaches the proposal and moves the
        mission to AWAITING_APPROVAL, which is exactly where a person decides.
        Nothing here can queue work, and a mission that arrived already planned
        is refused rather than re-planned over.
        """
        from ..fabric import Registry, UnknownAgent
        from ..fabric.agents import Backend
        from .adapter import SELF_CHECK_STEPS, NotRunnable, build

        mission = _rehydrate(_one(request, mission_id, tenant), tenant)
        registry = getattr(request.app.state, "agents", None) or Registry()
        try:
            agent = registry.get(body.agent)
        except UnknownAgent as unknown:
            raise HTTPException(status_code=404, detail=str(unknown)) from unknown

        if agent.backend is not Backend.EXECUTOR:
            # Honest about the boundary rather than half-implementing it: a
            # model-backed proposal needs the vault and a provider call, which
            # is the worker's and chat's job, not this route's.
            raise HTTPException(
                status_code=501,
                detail=f"{agent.id} is {agent.backend.value}-backed. A model "
                       "proposal is made in chat, where the conversation that "
                       "justifies it is recorded alongside it.")
        if agent.id != "self-check":
            raise HTTPException(
                status_code=501,
                detail=f"{agent.id} declares no steps to propose. Only agents "
                       "with a declared procedure can be planned from here.")
        try:
            proposed = build(agent.id, SELF_CHECK_STEPS).plan(
                mission.title or "verify this deployment")
        except NotRunnable as refused:
            raise HTTPException(status_code=409, detail=str(refused)) from refused

        try:
            planning, first = service.transition(
                mission, MissionStatus.PLANNING, tenant=tenant,
                actor=user.username, note=f"planning with {agent.id}")
            planned, second = service.attach_plan(planning, proposed,
                                                  tenant=tenant)
        except service.NotPermitted as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        _append(request, first)
        _append(request, second)
        return {**planned.summary(),
                "proposed_by": agent.id,
                "note": "proposed, not authorised. Approve it to queue it."}

    @router.post("/{mission_id}/approve")
    def approve(mission_id: str, body: Decision, request: Request,
                tenant: TenantId = Depends(current_tenant),
                user: User = Depends(requires(Scope.EXECUTE))) -> dict:
        """Let an approved plan be picked up. Still does not run it.

        The transition goes through the same `ALLOWED` table the worker obeys,
        so a mission that is not actually awaiting approval is refused here for
        the same reason it would be refused anywhere else, rather than by a
        second rule written into this handler.
        """
        mission = _rehydrate(_one(request, mission_id, tenant), tenant)
        try:
            approved, event = service.transition(
                mission, MissionStatus.QUEUED, tenant=tenant,
                actor=user.username, note=body.note or "approved by operator")
        except service.NotPermitted as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        _append(request, event)
        return approved.summary()

    @router.post("/{mission_id}/cancel")
    def cancel(mission_id: str, body: Decision, request: Request,
               tenant: TenantId = Depends(current_tenant),
               user: User = Depends(requires(Scope.EXECUTE))) -> dict:
        """Stop a mission from being picked up. Only before something picks it.

        A claimed mission cannot be cancelled here, and the refusal says why
        rather than being a generic state error. Marking it cancelled while a
        worker is still writing to a worktree and about to commit would show
        the operator a cancelled mission that goes on producing commits — the
        button that appears to kill a process and does not. The worker's own
        claim expiry is what handles a worker that has actually died.
        """
        mission = _rehydrate(_one(request, mission_id, tenant), tenant)
        if mission.claimed_by:
            raise HTTPException(
                status_code=409,
                detail=f"{mission.id} is being worked on by "
                       f"{mission.claimed_by}. Cancelling it here would record "
                       "it as cancelled while the worker is still writing, so "
                       "it is refused: wait for the mission to finish, fail, or "
                       "for the claim to expire.")
        try:
            cancelled, event = service.transition(
                mission, MissionStatus.CANCELLED, tenant=tenant,
                actor=user.username, note=body.note or "cancelled by operator")
        except service.NotPermitted as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        _append(request, event)
        return cancelled.summary()

    @router.post("/{mission_id}/defer")
    def defer(mission_id: str, body: Deferral, request: Request,
              tenant: TenantId = Depends(current_tenant),
              user: User = Depends(requires(Scope.EXECUTE))) -> dict:
        """Hold a mission until a chosen moment, with the reason recorded.

        Not a cancellation and not a block: the mission stays queued, because it
        is still work somebody wants done. What changes is when it may start —
        and `claim()` enforces that, so the window is a decision rather than a
        note the worker is free to ignore.
        """
        mission = _rehydrate(_one(request, mission_id, tenant), tenant)
        try:
            held, event = service.defer(mission, until=body.until, tenant=tenant,
                                        reason=body.reason, actor=user.username)
        except service.NotPermitted as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        _append(request, event)
        return held.summary()

    return router


def install(app: Any) -> None:
    app.include_router(build_router())
