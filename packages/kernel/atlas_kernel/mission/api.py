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

import logging
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
from . import origins, service
from .models import Mission, MissionStatus

log = logging.getLogger(__name__)

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


def _tools_for(recipe_id: str) -> tuple[str, ...]:
    """What the mission's declared recipe was permitted to use.

    From the declaration, not from what ran: a reviewer asking "could this have
    contacted anybody" is asking what it was allowed to do.
    """
    if not recipe_id:
        return ()
    from ..fabric import recipes

    try:
        return recipes.get(recipe_id).tools
    except recipes.UnknownRecipe:
        return ()


def _opportunities(request: Request):
    """The business memory this control plane reads opportunities from.

    Cached on the app the same way the discovery surface caches it, so an
    approval and the list it was made from are looking at one database.
    """
    from ..opportunity.repository import OpportunityRepository

    found = getattr(request.app.state, "opportunity_repository", None)
    if found is None:
        found = OpportunityRepository()
        request.app.state.opportunity_repository = found
    return found


def origin_registry(request: Request) -> origins.Registry:
    """The origins this deployment declares.

    Built from `QEVIK_ORIGINS` — the **same** input the worker reads, rather
    than a second list kept here. Two registries built from different sources
    are two answers to "which origins exist", and they disagree on the day
    somebody adds one to a single process.

    A malformed entry yields the built-ins alone rather than an error page: the
    console must still work, and `qevik` and `none` are derived rather than
    configured. The mistake is logged, and the worker refuses to start on it,
    which is where an operator will see it.
    """
    cached = getattr(request.app.state, "origins", None)
    if cached is not None:
        return cached
    try:
        built = origins.Registry.build(origins.from_environment())
    except origins.OriginRefused as refusal:
        log.error("QEVIK_ORIGINS is not usable, falling back to the built-in "
                  "origins only: %s", refusal)
        built = origins.Registry.build()
    request.app.state.origins = built
    return built


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


class OutreachApproval(BaseModel):
    """Authorising one exact message to one exact recipient.

    The recipient is **not** a field. It comes from the business record, and a
    request that could name one could name any address — which is precisely how
    a message reaches somebody nobody decided to contact.
    """

    fingerprint: str = Field(min_length=8, max_length=128)
    note: str = Field(default="", max_length=2000)


class PublishRequest(BaseModel):
    """Authorising one exact bundle to go to one exact address.

    `commit` is required and is what the operator was looking at. The address is
    **not** a field: it is derived from the business, because a request that
    could name a destination could name a directory.
    """

    commit: str = Field(min_length=7, max_length=64,
                        pattern="^[0-9a-f]+$")
    note: str = Field(default="", max_length=2000)


class Review(BaseModel):
    """A person's decision about a delivered artefact.

    `commit` is what they were looking at. Sent by the client from the same
    response that showed them the files, so a decision made about one artefact
    cannot be recorded against a branch that has since been rebuilt.
    """

    decision: str = Field(pattern="^(accepted|rejected)$")
    note: str = Field(default="", max_length=2000)
    commit: str = Field(default="", max_length=64)


class Delivery(BaseModel):
    """Which opportunity a person is approving. Nothing else.

    One field on purpose. A body that also carried a recipe, an origin or a
    scope would be a caller deciding what the approval means — and the whole
    point of this path is that the opportunity's own evidence decided that
    before anybody was asked.
    """

    signal_id: str = Field(min_length=1, max_length=120)


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

    @router.get("/origins")
    def origin_list(request: Request,
                    _: User = Depends(requires(Scope.READ))) -> dict:
        """Which repositories a mission may be pointed at.

        Names and kinds only — **no filesystem paths**. A path is not something
        an operator picks from, and putting one in an HTTP response makes it
        something anybody reaching the console can read.

        Declared above `/{mission_id}` so `origins` is never read as a mission
        id. FastAPI matches in declaration order, and this route was first
        written *below* it — where every request for it was answered by the
        detail handler looking for a mission called "origins". The comment
        claiming otherwise was written at the same time as the bug, which is
        the useful lesson: a note about ordering is not ordering.
        """
        registry = origin_registry(request)
        return {"origins": registry.public(), "default": origins.DEFAULT_NAME}

    @router.get("/awaiting-publication")
    def awaiting_publication(request: Request, limit: int = 50,
                             tenant: TenantId = Depends(current_tenant),
                             _: User = Depends(requires(Scope.READ))) -> dict:
        """Artefacts a person accepted, that nothing has taken anywhere.

        **Declared here, above `/{mission_id}`.** A path parameter matches a
        literal segment happily, so this route registered after it would be
        served as a mission whose id is the string `awaiting-publication` — a
        404 that looks like an empty queue. This repository has shipped that
        bug once already.

        Read-only, and deliberately carries **no filesystem path**. Where an
        artefact happens to sit on a host is not a fact this queue is about, and
        an operator who is deciding what should go out next does not need one.
        The mission id is the handle; the mission's own artefact endpoint is
        where the files are.
        """
        return {"awaiting": _opportunities(request).awaiting_publication(
            limit=limit, tenant=tenant)}

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
        # Validated here as well as in the worker. The worker's check is the
        # one that protects execution; this one means a typo is answered
        # immediately, by the surface that made it, instead of becoming a
        # mission that sits blocked until somebody reads its note.
        registry = origin_registry(request)
        if body.origin and not registry.known(body.origin):
            raise HTTPException(
                status_code=400,
                detail=f"no origin named {body.origin!r}. Known: "
                       f"{', '.join(registry.names())}")
        try:
            mission, event = service.create(
                tenant=tenant, title=body.title, description=body.description,
                requested_by=user.username, priority=body.priority,
                origin_name=body.origin)
        except service.NotPermitted as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        _append(request, event)
        return mission.summary()

    @router.get("/{mission_id}/artefact")
    def artefact_of(mission_id: str, request: Request,
                    tenant: TenantId = Depends(current_tenant),
                    _: User = Depends(requires(Scope.READ))) -> dict:
        """What this mission delivered, read out of its commit.

        The whole point of the surface: a reviewer needs the files, what they
        answer, what authorised them and what has already been decided — and
        needs them without a terminal. Everything here is read-only.
        """
        from ..opportunity.repository import NotApprovable  # noqa: F401
        from . import artefact as reader

        summary = _one(request, mission_id, tenant)
        workspace = summary.get("workspace") or ""
        scratch = getattr(request.app.state, "scratch_root", None)
        scratch = Path(str(scratch)) if scratch else None

        memory = _opportunities(request)
        reviews = memory.reviews_for(mission_id, tenant=tenant)
        # Where this artefact has actually got to, read from the timeline. A
        # surface that worked it out from the presence of a directory would
        # report a site as live because a disk had it.
        published = memory.publications_for(mission_id, tenant=tenant)
        authorised = memory.publication_approvals_for(mission_id, tenant=tenant)
        chain = {
            "signal_id": summary.get("signal_id") or "",
            "approved_scope": summary.get("approved_scope") or "",
            "approved_by": summary.get("requested_by") or "",
            "evidence_fingerprints": summary.get("evidence_fingerprints") or [],
            "origin_name": summary.get("origin_name") or "",
            "origin": summary.get("origin") or "",
            "origin_kind": summary.get("origin_kind") or "",
            "recipe": summary.get("recipe") or "",
            "agent_id": summary.get("agent_id") or "",
            "tools": list(_tools_for(summary.get("recipe") or "")),
            "workspace": workspace,
            "branch": reader.branch_of(mission_id),
            "report_path": summary.get("report_path") or "",
            "status": summary.get("status") or "",
            # Three states, told apart: reviewed and waiting, authorised and not
            # yet out, or live. Never inferred from a machine.
            "publication_state": ("PUBLISHED" if published
                                  else "AUTHORISED" if authorised
                                  else "ACCEPTED"
                                  if reviews and reviews[-1]["decision"] == "accepted"
                                  else "NOT_REVIEWED"),
            "published": published,
            "authorised": authorised,
        }
        try:
            found = reader.files(mission_id, workspace, scratch=scratch)
        except reader.Unreadable as refused:
            # Reported, not raised. A mission with no artefact is an ordinary
            # state — most missions have none — and a 500 here would make the
            # review page unusable for every one of them.
            return {"mission_id": mission_id, **chain, "files": [],
                    "provenance": {}, "commit": "", "reviews": reviews,
                    "unreadable": str(refused)}
        return {
            "mission_id": mission_id, **chain,
            "files": [entry.summary() for entry in found],
            "provenance": reader.provenance(mission_id, workspace,
                                            scratch=scratch),
            "commit": reader.commit_of(mission_id, workspace, scratch=scratch),
            "reviews": reviews,
        }

    @router.get("/{mission_id}/artefact/file")
    def artefact_file(mission_id: str, path: str, request: Request,
                      tenant: TenantId = Depends(current_tenant),
                      _: User = Depends(requires(Scope.READ))) -> dict:
        """One delivered file, in full or not at all.

        As text, and never rendered by this API. The console shows it as source
        with an opt-in preview, because a control plane that executed a
        customer's generated HTML in the operator's session would be running
        somebody else's markup with the operator's token in the page.
        """
        from . import artefact as reader

        summary = _one(request, mission_id, tenant)
        scratch = getattr(request.app.state, "scratch_root", None)
        try:
            body = reader.read(mission_id, summary.get("workspace") or "", path,
                               scratch=Path(str(scratch)) if scratch else None)
        except reader.Unreadable as refused:
            raise HTTPException(status_code=404, detail=str(refused)) from refused
        return {"mission_id": mission_id, "path": path, "text": body,
                "bytes": len(body.encode("utf-8"))}

    @router.post("/{mission_id}/review", status_code=201)
    def review(mission_id: str, body: Review, request: Request,
               tenant: TenantId = Depends(current_tenant),
               user: User = Depends(requires(Scope.EXECUTE))) -> dict:
        """Record what a person decided about the artefact. Publishes nothing.

        Requires EXECUTE rather than READ: a review is a decision, and the next
        milestone reads it to decide whether anything may leave the building.
        Someone who may only read must not be able to leave one.

        Accepting does **not** publish, send, promote or merge. It records that
        a person looked and said yes, which is a different act from doing
        anything about it — and keeping them different is what lets the
        publishing boundary exist at all.
        """
        from ..opportunity.repository import NotApprovable

        summary = _one(request, mission_id, tenant)
        if not summary.get("signal_id"):
            raise HTTPException(
                status_code=422,
                detail=("this mission delivered nothing an opportunity asked "
                        "for, so there is no delivery to review."))
        memory = _opportunities(request)
        signal = memory.get_signal(summary["signal_id"], tenant=tenant)
        try:
            recorded = memory.record_review(
                mission_id=mission_id,
                business_id=(signal or {}).get("business_id", ""),
                signal_id=summary["signal_id"], decision=body.decision,
                actor=user.username, note=body.note, commit=body.commit,
                tenant=tenant)
        except NotApprovable as refused:
            raise HTTPException(status_code=400, detail=str(refused)) from refused
        return recorded

    @router.get("/{mission_id}/outreach")
    def outreach(mission_id: str, request: Request,
                 tenant: TenantId = Depends(current_tenant),
                 _: User = Depends(requires(Scope.READ))) -> dict:
        """What Qevik would say to this business, and what stops it saying it.

        A read. Preparing a message reaches nothing, dispatches nothing and
        sends nothing — there is no agent, tool or recipe on this path, so
        there is no network capability to withhold.
        """
        from ..opportunity.tenancy import ALL_TENANTS
        from ..outreach import preparation

        summary = _one(request, mission_id, tenant)
        memory = _opportunities(request)
        signal_id = summary.get("signal_id") or ""
        signal = memory.get_signal(signal_id, tenant=tenant) if signal_id else None
        if signal is None:
            raise HTTPException(status_code=422,
                                detail="this mission has no opportunity to "
                                       "write about")
        business = memory.get_business(signal["business_id"], tenant=ALL_TENANTS)
        if business is None:
            raise HTTPException(status_code=422, detail="no business")

        published = memory.publications_for(mission_id, tenant=tenant)
        approvals = memory.outreach_approvals_for(mission_id, tenant=tenant)
        if not published:
            return {"mission_id": mission_id, "state": "NOT_PUBLISHED",
                    "prepared": None, "approvals": approvals,
                    "detail": ("nothing has been published for this business. "
                               "The message is about a published site.")}

        # What the build said it answered, read from the artefact it published.
        from . import artefact as reader

        scratch = getattr(request.app.state, "scratch_root", None)
        answers: tuple[str, ...] = ()
        try:
            provenance = reader.provenance(
                mission_id, summary.get("workspace") or "",
                scratch=Path(str(scratch)) if scratch else None)
            answers = tuple(provenance.get("addresses") or ())
        except Exception:                          # noqa: BLE001 - reported
            answers = ()

        try:
            prepared = preparation.prepare(
                business=business, signal=signal, publication=published[-1],
                approved_scope=summary.get("approved_scope") or "",
                answers=answers)
        except preparation.NotPreparable as refused:
            return {"mission_id": mission_id, "state": "NOT_PREPARABLE",
                    "prepared": None, "approvals": approvals,
                    "detail": str(refused)}

        return {"mission_id": mission_id,
                "state": "APPROVED_TO_SEND" if approvals else prepared.state,
                "prepared": prepared.summary(), "approvals": approvals}

    @router.post("/{mission_id}/outreach/approve", status_code=201)
    def approve_outreach(mission_id: str, body: OutreachApproval,
                         request: Request,
                         tenant: TenantId = Depends(current_tenant),
                         user: User = Depends(requires(Scope.COMMUNICATE))
                         ) -> dict:
        """Authorise contacting this business. Sends nothing, because nothing can.

        `Scope.COMMUNICATE`, and not PUBLISH. Putting a page on the internet and
        writing to a person are different acts: the first is found by whoever
        goes looking, the second arrives. An operator trusted with one is not
        thereby trusted with the other, and reusing the scope would mean the
        publication approval had quietly carried this one.
        """
        from ..opportunity.repository import NotApprovable
        from ..opportunity.tenancy import ALL_TENANTS
        from ..outreach import preparation

        summary = _one(request, mission_id, tenant)
        memory = _opportunities(request)
        signal = memory.get_signal(summary.get("signal_id") or "", tenant=tenant)
        if signal is None:
            raise HTTPException(status_code=422, detail="no opportunity")
        business = memory.get_business(signal["business_id"], tenant=ALL_TENANTS)
        published = memory.publications_for(mission_id, tenant=tenant)
        if business is None or not published:
            raise HTTPException(
                status_code=422,
                detail="nothing published for this business to write about")

        recipient, channel = preparation.verified_recipient(business)
        if not recipient:
            # The state the first real business is actually in. Reported as a
            # refusal rather than filled in: an address derived from a website
            # is a guess that lands in a stranger's inbox.
            raise HTTPException(
                status_code=409,
                detail=("no verified way to reach this business. Qevik does not "
                        "derive an address from a domain, and a landline is not "
                        "a WhatsApp number."))
        try:
            recorded = memory.approve_outreach(
                mission_id=mission_id, business_id=business.id,
                signal_id=signal["id"], commit=published[-1]["commit"],
                recipient=recipient, channel=channel,
                fingerprint=body.fingerprint, actor=user.username,
                note=body.note, tenant=tenant)
        except NotApprovable as refused:
            raise HTTPException(status_code=409, detail=str(refused)) from refused
        return {**recorded, "state": "APPROVED_TO_SEND",
                "sent": False,
                "why_not_sent": ("no channel has a provider configured. "
                                 "Approval records permission; it does not "
                                 "create the ability.")}

    @router.post("/{mission_id}/publish", status_code=201)
    def publish(mission_id: str, body: PublishRequest, request: Request,
                tenant: TenantId = Depends(current_tenant),
                user: User = Depends(requires(Scope.PUBLISH))) -> dict:
        """Authorise publishing this artefact, and create the mission that does.

        `Scope.PUBLISH`, not EXECUTE. Reviewing says the work is good; this puts
        it in front of strangers, and the two are answerable differently by the
        same person — which is the whole reason there are two decisions.

        Nothing here publishes. It records an authorisation and creates a
        mission, and the mission goes through `policy.decide` like every other:
        the agent's blast radius is IRREVERSIBLE, so policy has the last word on
        whether a person is asked again before it runs.
        """
        from ..opportunity.repository import NotApprovable
        from . import publication as bridge

        summary = _one(request, mission_id, tenant)
        if not summary.get("signal_id"):
            raise HTTPException(
                status_code=422,
                detail="this mission delivered nothing, so there is nothing "
                       "to publish.")
        memory = _opportunities(request)
        signal = memory.get_signal(summary["signal_id"], tenant=tenant)
        if signal is None:
            raise HTTPException(status_code=404,
                                detail="the opportunity is not there")

        from ..opportunity.tenancy import ALL_TENANTS

        business = memory.get_business(signal["business_id"],
                                       tenant=ALL_TENANTS)
        if business is None:
            raise HTTPException(status_code=422,
                                detail="no business to publish for")
        try:
            site_id = bridge.site_for(business.id)
        except bridge.NotPublishable as refused:
            raise HTTPException(status_code=422, detail=str(refused)) from refused

        try:
            approval = memory.approve_publication(
                mission_id=mission_id, business_id=business.id,
                signal_id=signal["id"], commit=body.commit, site_id=site_id,
                actor=user.username, note=body.note, tenant=tenant)
        except NotApprovable as refused:
            raise HTTPException(status_code=409, detail=str(refused)) from refused

        registry = origin_registry(request)
        origin = registry.resolve(origins.EMPTY_NAME)
        try:
            mission, events = bridge.enqueue(
                approval, signal, tenant=tenant, origin=origin,
                actor=user.username, business_id=business.id)
        except bridge.NotPublishable as refused:
            raise HTTPException(status_code=422, detail=str(refused)) from refused

        for event in events:
            _append(request, event)
        # The site id is an address, not a path. What is returned is the
        # publication mission and what it was authorised to do — never where
        # anything sits on a disk.
        return {**mission.summary(), "publishes": mission_id,
                "commit": approval["commit"], "site_id": site_id}

    @router.post("/deliver", status_code=201)
    def deliver(body: Delivery, request: Request,
                tenant: TenantId = Depends(current_tenant),
                user: User = Depends(requires(Scope.EXECUTE))) -> dict:
        """Approve one opportunity, and create the mission that delivers it.

        One action because it is one decision. The person is not approving "a
        mission" — they are approving *this opportunity*, and the mission is
        what carrying it out looks like. Splitting them would leave an approved
        opportunity that does nothing, which is the state this milestone
        existed to end.

        The recipe is **not** a parameter. It comes from the capability the
        opportunity's own suggested action named, through `OFFER_RECIPES`, so
        there is no request that can ask for a different one.

        The mission then goes through `service.attach_plan` like every other,
        so `policy.decide` still gets the last word on whether a person is
        needed again before it runs.
        """
        from ..opportunity.repository import NotApprovable, UnknownSignal
        from . import delivery as bridge

        memory = _opportunities(request)
        registry = origin_registry(request)
        # A delivery writes into its own scratch workspace and reads Qevik's
        # memory. It does not have a repository, and naming one would give a
        # customer's build a checkout it has no reason to touch.
        origin = registry.resolve(origins.EMPTY_NAME)

        try:
            approved = memory.approve_signal(body.signal_id,
                                             actor=user.username, tenant=tenant)
        except UnknownSignal as unknown:
            raise HTTPException(status_code=404, detail=str(unknown)) from unknown
        except NotApprovable as refused:
            raise HTTPException(status_code=409, detail=str(refused)) from refused

        try:
            mission, events = bridge.enqueue(approved, tenant=tenant,
                                             origin=origin,
                                             actor=user.username)
        except bridge.NotDeliverable as refused:
            # The approval stands and is recorded; what cannot be built is the
            # mission. Reported as such rather than rolled back, because a
            # person did decide, and erasing that would lose the decision.
            raise HTTPException(status_code=422, detail=str(refused)) from refused

        for event in events:
            _append(request, event)
        return {**mission.summary(), "signal_id": approved["id"],
                "approved_scope": mission.approved_scope}

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
