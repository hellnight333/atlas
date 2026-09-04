"""The customer-facing boundary. Thin on purpose.

Every handler does three things: establish the tenant, call a kernel service,
return what it returned. There is no logic here worth reading, and that is the
design — a rule enforced in a handler is a rule that applies to callers who
arrive through this door and not to anybody else, which is how a system ends up
with a safe API and an unsafe worker.

**The tenant is resolved from the authenticated user and never from the
request.** No path parameter, no header, no query string names a tenant. A
customer cannot ask for another customer's data because there is no argument in
which to ask.

**A resource belonging to another tenant is absent, not forbidden.** 404 for
both, and the same body — the difference between "no such business" and "not
yours" tells an attacker which ids exist, and enumerating ids is the cheapest
attack there is.

**A user with no tenant reaches none of this.** Empty means not established,
and the routes refuse rather than defaulting: an operator account exists to run
Qevik, not to read one customer's file.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import controlplane
from ..approval.models import ApprovalState
from ..approval.service import ApprovalError
from ..auth.api import current_user, requires
from ..auth.models import Scope, User
from ..credits.models import ESSENTIAL_FLOOR, INCLUDED, NoPlan
from ..customer import public
from ..customer import strategy as strategy_service
from ..customer import tasks as task_service
from ..integrations import registry as integration_registry
from ..measurement import service as measurement_service
from ..opportunity.tenancy import TenantId, owns
from ..publication import service as publication_service
from ..publication import staging as staging_service
from ..roadmap.lifecycle import facts_for
from ..roadmap.presentation import capabilities, view

#: The single message for every miss. Deliberately identical whether the thing
#: does not exist or belongs to somebody else.
NOT_FOUND = "no such resource"


def current_tenant(user: User = Depends(current_user)) -> TenantId:
    """The tenant this request acts for. Decided in `tenancy.of_user`, once.

    This was the sixth copy of that decision, and it survived a consolidation
    of the other five because its refusal is worded differently — which is the
    argument for one function in its most literal form.

    Its wording was also the most defensible of the six: the customer surface is
    for customers, and an operator is not one. But refusing here left the
    console's Settings page unable to read the plan route at all, and that page
    already distinguishes three answers — on a plan, no plan, unreadable. With
    the operator acting for the house tenant it gets 409 (no plan), which is
    true and is the state the page was written for.
    """
    from ..opportunity.tenancy import TenantRequired, of_user

    try:
        return of_user(user, method="the customer surface")
    except TenantRequired as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


def _events(request: Request) -> list:
    """The business timeline this deployment reads from.

    Injected rather than imported so a surface can be served from a repository,
    a cache or a test list without this module knowing which.
    """
    source = getattr(request.app.state, "business_events", None)
    return list(source or [])


def _research(request: Request, business_id: str, tenant: TenantId) -> dict:
    reader = getattr(request.app.state, "research_reader", None)
    if reader is None:
        raise HTTPException(status_code=503,
                            detail="no research source is configured")
    found = reader(business_id=business_id, tenant=tenant)
    if found is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return found


def _plan(request: Request, business_id: str, tenant: TenantId) -> Any:
    """Research → readiness → roadmap, through the existing services."""
    reader = getattr(request.app.state, "plan_reader", None)
    if reader is None:
        raise HTTPException(status_code=503, detail="no plan source is configured")
    found = reader(business_id=business_id, tenant=tenant)
    if found is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return found


@runtime_checkable
class Approvals(Protocol):
    """The three things this surface needs of an approval service.

    Declared as a protocol rather than importing `ApprovalService` directly,
    because the real one needs a repository and an event bus and this surface
    needs none of that. Naming the narrow dependency means a test can supply a
    double without the double being a shortcut — and
    `test_the_real_approval_service_satisfies_the_protocol` checks the real one
    still fits, so the double cannot drift away from it silently.
    """

    def get(self, approval_id: str) -> Any: ...

    def approve(self, approval_id: str, actor: str,
                comment: str | None = None) -> Any: ...

    def reject(self, approval_id: str, actor: str,
               comment: str | None = None) -> Any: ...


class TaskCompletion(BaseModel):
    """The customer's claim that they did their part, and what backs it.

    `kind` is what sort of evidence this is; `reference` is the thing itself — a
    hostname, an approval id. There is deliberately no `verified_by_system`
    field: that is derived from the kind, and a field for it would let a caller
    assert that Qevik checked something Qevik never looked at.
    """

    kind: task_service.ProofKind
    reference: str = Field(min_length=1, max_length=500)
    detail: str = Field(default="", max_length=2000)
    #: Required for an attestation, ignored otherwise — the attester is the
    #: authenticated session, and this exists only to record a third party who
    #: is not the person logged in.
    attested_by: str = Field(default="", max_length=200)


class Decision(BaseModel):
    """A customer's answer about one artefact.

    No `decided_by`: the decider is the authenticated session, and a field for
    it would be a field to lie in.
    """

    approved: bool
    comment: str = Field(default="", max_length=2000)


def _append(request: Request, event: Any) -> None:
    """Put one event on the business timeline, or refuse.

    Never a silent no-op. A write route that returns 200 and persists nothing is
    how a customer marks a task done, sees it accepted, and finds it outstanding
    again tomorrow.
    """
    sink = getattr(request.app.state, "business_sink", None)
    if sink is None:
        raise HTTPException(
            status_code=503,
            detail="no timeline is configured to write to, so this would have "
                   "been accepted and lost")
    sink(event)


def _establish(body: TaskCompletion, request: Request,
               tenant: TenantId) -> task_service.Proof:
    """Turn a claim into evidence, or refuse it.

    The three kinds are not interchangeable. An `observed` proof is checked
    here and now; an `approval` proof is read from the approval service rather
    than taken from the request, because an approval id a customer typed is a
    claim and the approval's own state is the fact; an `attestation` is
    somebody's word and is recorded as such.
    """
    try:
        if body.kind is task_service.ProofKind.OBSERVED:
            # A DNS lookup, not a fetch: tri-state resolution, no ports, no
            # response body. Authenticated and scoped to a task, so it is not
            # the open amplifier the public audit route refuses to be.
            return task_service.verify_domain(body.reference)
        if body.kind is task_service.ProofKind.APPROVAL:
            service = getattr(request.app.state, "approvals", None)
            if service is None:
                raise HTTPException(
                    status_code=503,
                    detail="no approval service is configured")
            found = service.get(body.reference)
            if found is None or not owns(found.metadata.get("tenant_id"), tenant):
                raise HTTPException(status_code=404, detail=NOT_FOUND)
            return task_service.verify_approval(found)
        return task_service.Proof(kind=body.kind, reference=body.reference,
                                  detail=body.detail,
                                  attested_by=body.attested_by)
    except task_service.ProofRejected as rejected:
        raise HTTPException(status_code=422, detail=str(rejected)) from rejected


log = logging.getLogger(__name__)


def _remember_lead(request: Request, *, website: str, found: dict | None) -> None:
    """Record that a business asked about itself. Never raises.

    On the ordinary timeline, through the ordinary sink. There is no lead table
    and no second store: a lead is something that happened, and the timeline
    already holds things that happened.
    """
    from . import inbound as leads

    lead = leads.capture(
        website=website,
        observations=len((found or {}).get("observations") or []),
        business_id=(found or {}).get("business_id", ""))
    if lead is None:
        return

    memory = getattr(request.app.state, "opportunity_repository", None)
    if memory is None:
        from ..opportunity.repository import OpportunityRepository

        memory = OpportunityRepository()
        request.app.state.opportunity_repository = memory
    try:
        memory.record_lead(website=lead.website, host=lead.host,
                           source=lead.source, observations=lead.observations,
                           business_id=lead.business_id)
    except Exception:                             # noqa: BLE001 - reported
        log.exception("a business asked about %s and it was not recorded",
                      lead.host)


def build_public_router() -> APIRouter:
    """Unauthenticated. Separate router so the boundary is visible in the code.

    One route, and everything it can return goes through `public.audit`, whose
    guard refuses any field nobody put on the allow-list. Keeping it in its own
    router rather than as an exception inside the customer one means a route
    added to the wrong file is a route with the wrong authentication, which is
    noticeable, rather than a decorator argument nobody reads.
    """
    router = APIRouter(prefix="/api/public", tags=["public"])

    @router.post("/audit")
    def audit(body: dict, request: Request) -> dict:
        """Audit a website for somebody who has no account yet.

        Research is not run here. A route that crawled an arbitrary URL on
        request is a request-triggered outbound fetch, which is a denial-of-
        service amplifier and a way to make Qevik's address appear in a
        stranger's logs. Instead it reads what research already holds, and
        says plainly when it holds nothing.
        """
        website = (body or {}).get("website", "")
        if not isinstance(website, str) or not website.strip():
            raise HTTPException(status_code=400, detail="a website is required")

        reader = getattr(request.app.state, "public_audit_reader", None)
        if reader is None:
            raise HTTPException(status_code=503,
                                detail="no audit source is configured")
        found = reader(website=website.strip())

        # They came to us. Recorded before the answer is composed, because the
        # commercially interesting fact is that somebody asked — not what the
        # answer happened to be, and not whether research already knew them.
        #
        # A failure to record must not fail the request: the visitor is owed
        # their answer, and losing a lead is worse than losing it silently only
        # if nobody is told, so it is logged.
        _remember_lead(request, website=website.strip(), found=found)

        if found is None:
            # Not 404-as-absence here: there is no tenant boundary to protect,
            # and telling a visitor "we have not looked at this yet" is the
            # honest answer and the one that converts.
            return public.audit(website=website.strip(), observations=[])
        return public.audit(website=website.strip(),
                            observations=found.get("observations") or [],
                            opportunities=found.get("opportunities") or ())

    return router


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api/customer", tags=["customer"])

    @router.get("/me")
    def me(user: User = Depends(current_user),
           tenant: TenantId = Depends(current_tenant)) -> dict:
        return {"username": user.username, "tenant_id": tenant,
                "scopes": sorted(str(s) for s in user.scopes)}

    @router.get("/capabilities", dependencies=[Depends(requires(Scope.READ))])
    def catalogue(_tenant: TenantId = Depends(current_tenant)) -> dict:
        """What Qevik offers, and what Qevik can actually run."""
        return capabilities()

    @router.get("/businesses/{business_id}/research",
                dependencies=[Depends(requires(Scope.READ))])
    def research(business_id: str, request: Request,
                 tenant: TenantId = Depends(current_tenant)) -> dict:
        """What was confirmed, and what was not looked at.

        Both halves, always. A summary listing only findings reads as a complete
        picture of the business rather than of our checking.
        """
        found = _research(request, business_id, tenant)
        observations = found.get("observations") or []
        return {
            "business_id": business_id,
            "website": found.get("website", ""),
            "confirmed_present": sorted(o["feature"] for o in observations
                                        if o.get("status") == "present"),
            "confirmed_absent": sorted(o["feature"] for o in observations
                                       if o.get("status") == "not_found"),
            "not_verified": sorted(o["feature"] for o in observations
                                   if o.get("status") == "unverified"),
            "note": "Anything under 'not verified' was not checked. It is not a "
                    "finding either way.",
        }

    @router.get("/businesses/{business_id}/roadmap",
                dependencies=[Depends(requires(Scope.READ))])
    def roadmap(business_id: str, request: Request,
                tenant: TenantId = Depends(current_tenant)) -> dict:
        plan = _plan(request, business_id, tenant)
        done = task_service.completed_ids(_events(request), tenant=tenant)
        return view(plan.roadmap, facts=facts_for(plan.roadmap,
                                                  completed_task_ids=done))

    @router.get("/businesses/{business_id}/strategy",
                dependencies=[Depends(requires(Scope.READ))])
    def strategy(business_id: str, request: Request,
                 tenant: TenantId = Depends(current_tenant)) -> dict:
        plan = _plan(request, business_id, tenant)
        return strategy_service.summarise(roadmap=plan.roadmap,
                                          readiness=plan.readiness,
                                          measurements=plan.measurements)

    @router.get("/businesses/{business_id}/tasks",
                dependencies=[Depends(requires(Scope.READ))])
    def my_tasks(business_id: str, request: Request,
                 tenant: TenantId = Depends(current_tenant)) -> dict:
        """"What does Qevik need from me?" """
        plan = _plan(request, business_id, tenant)
        done = task_service.completed_ids(_events(request), tenant=tenant)
        facts = facts_for(plan.roadmap, completed_task_ids=done)
        return {"business_id": business_id,
                "outstanding": list(task_service.outstanding(plan.roadmap, facts)),
                "completed": sorted(done)}

    @router.get("/businesses/{business_id}/previews",
                dependencies=[Depends(requires(Scope.READ))])
    def previews(business_id: str, request: Request,
                 tenant: TenantId = Depends(current_tenant)) -> dict:
        """Staged versions. Tenant-scoped because a preview URL is a working
        link to work nobody has agreed may be seen.

        Establishes the business first. Filtering a tenant-scoped event list by
        business id looks equivalent and is not: for a business belonging to
        somebody else it returns an empty list and a 200, which answers "does
        this id exist and is it mine" differently from every other route here.
        """
        _plan(request, business_id, tenant)
        staged = staging_service.read(_events(request), tenant=tenant)
        return {"business_id": business_id,
                "previews": [s for s in staged
                             if s.get("business_id") == business_id]}

    @router.get("/businesses/{business_id}/publications",
                dependencies=[Depends(requires(Scope.READ))])
    def publications(business_id: str, request: Request,
                     tenant: TenantId = Depends(current_tenant)) -> dict:
        _plan(request, business_id, tenant)
        records = publication_service.read(_events(request), tenant=tenant)
        return {"business_id": business_id,
                "publications": [r for r in records
                                 if r.get("business_id") == business_id]}

    @router.get("/plan", dependencies=[Depends(requires(Scope.READ))])
    def plan(request: Request, tenant: TenantId = Depends(current_tenant)) -> dict:
        """The plan, what it includes, and what is left of it.

        Units, never money. There is no pricing in the credit layer, so there is
        none to show — a figure here would be the only place in the system that
        claimed to know what something costs in currency.
        """
        service = getattr(request.app.state, "credits", None)
        if service is None:
            raise HTTPException(status_code=503,
                                detail="no credit service is configured")
        try:
            current = service.plan_of(tenant)
            status = service.status(tenant)
        except NoPlan as absent:
            # A provisioning gap, reported as one. Not an empty balance.
            raise HTTPException(status_code=409, detail=str(absent)) from absent

        return {
            "plan": current.value,
            "included_units": INCLUDED[current],
            "used": status.used,
            # Two numbers, because there are two. `remaining` is what ordinary
            # work may draw on; the reserve is held back so an approved
            # publication is never blocked by a month of generation. Showing
            # only the larger figure would let a customer plan against units
            # ordinary work cannot reach.
            "remaining": service.balance(tenant),
            "reserved_for_essential": ESSENTIAL_FLOOR[current],
            "remaining_including_reserve": service.balance(tenant, essential=True),
            "held": service.held(tenant),
            "resets_at": status.resets_at.isoformat() if status.resets_at else None,
            "history": [r.model_dump(mode="json") for r in service.history(tenant)],
            "note": "Units, not money. A unit is what a capability declares it "
                    "costs; nothing here prices or charges anything.",
        }

    @router.get("/actions", dependencies=[Depends(requires(Scope.READ))])
    def actions(request: Request,
                tenant: TenantId = Depends(current_tenant)) -> dict:
        """Everything waiting on a person, for this tenant.

        Derived from integrations, approvals and outstanding customer tasks
        rather than stored, so an action that has been satisfied stops being
        produced instead of needing to be closed by hand.
        """
        store = getattr(request.app.state, "connections", None)
        if store is None:
            raise HTTPException(status_code=503,
                                detail="no connection store is configured")
        approvals = getattr(request.app.state, "pending_approvals", None)
        pending = list(approvals(tenant=tenant)) if approvals else []
        return controlplane.centre(store=store, tenant=tenant,
                                   pending_approvals=pending)

    @router.get("/integrations", dependencies=[Depends(requires(Scope.READ))])
    def integrations(request: Request,
                     tenant: TenantId = Depends(current_tenant)) -> dict:
        """What is connected, what is waiting on a credential, what is not built."""
        store = getattr(request.app.state, "connections", None)
        if store is None:
            raise HTTPException(status_code=503,
                                detail="no connection store is configured")
        return integration_registry.catalogue(store, tenant=tenant)

    @router.get("/businesses/{business_id}/measurements",
                dependencies=[Depends(requires(Scope.READ))])
    def measurements(business_id: str, request: Request,
                     tenant: TenantId = Depends(current_tenant)) -> dict:
        plan = _plan(request, business_id, tenant)
        return {"business_id": business_id,
                "pending_sources": list(
                    measurement_service.awaiting_source(plan.roadmap)),
                "measurements": list(plan.measurements)}

    # ---------------------------------------------------------------- writes
    #
    # Two, and only two, things a customer may change: they can tell us they
    # have done their part, and they can decide an approval. Everything else on
    # this surface is a read, because everything else is work Qevik owes them
    # and a customer marking our work done is the conversion the whole
    # CUSTOMER_TASK boundary exists to prevent.

    @router.post("/businesses/{business_id}/tasks/{task_id}/complete",
                 dependencies=[Depends(requires(Scope.EXECUTE))])
    def complete_task(business_id: str, task_id: str, body: TaskCompletion,
                      request: Request,
                      tenant: TenantId = Depends(current_tenant),
                      user: User = Depends(current_user)) -> dict:
        """Record that the customer did their part, with the evidence.

        The proof is *established*, never accepted. An `observed` proof runs the
        check; an `approval` proof reads the approval's real state; an
        `attestation` records whose word it is. `verified_by_system` is derived
        from the kind and can therefore not be claimed by the caller — a field a
        customer could set would make "we checked this" mean "somebody said so".
        """
        plan = _plan(request, business_id, tenant)
        task = next((t for t in plan.roadmap.tasks if t.id == task_id), None)
        if task is None:
            raise HTTPException(status_code=404, detail=NOT_FOUND)

        proof = _establish(body, request, tenant)
        try:
            event = task_service.complete(task, proof, tenant=tenant,
                                          actor=user.username)
        except task_service.ProofRejected as rejected:
            raise HTTPException(status_code=422, detail=str(rejected)) from rejected
        except PermissionError as denied:      # pragma: no cover - plan scopes
            raise HTTPException(status_code=404, detail=NOT_FOUND) from denied

        _append(request, event)
        return {"task_id": task_id, "completed": True,
                "proof": proof.model_dump(mode="json"),
                "verified_by_system": event.detail["verified_by_system"]}

    @router.post("/approvals/{approval_id}/decide",
                 dependencies=[Depends(requires(Scope.EXECUTE))])
    def decide(approval_id: str, body: Decision, request: Request,
               tenant: TenantId = Depends(current_tenant),
               user: User = Depends(current_user)) -> dict:
        """Approve or reject one specific thing.

        This is the artefact boundary, not the execution one: it answers "may
        this exact output go live", and holding EXECUTE is what lets a customer
        answer it rather than what answers it for them.

        Another tenant's approval is absent. An approval names an artefact and
        usually a domain, so 403-versus-404 here would tell a caller which
        customers exist and what is pending for them.
        """
        service = getattr(request.app.state, "approvals", None)
        if service is None:
            raise HTTPException(status_code=503,
                                detail="no approval service is configured")
        found = service.get(approval_id)
        if found is None or not owns(found.metadata.get("tenant_id"), tenant):
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        if found.state is not ApprovalState.PENDING:
            raise HTTPException(
                status_code=409,
                detail=f"this was already {found.state.value}. Deciding it "
                       "again would overwrite a decision somebody made.")

        try:
            decided = (service.approve(approval_id, user.username, body.comment)
                       if body.approved
                       else service.reject(approval_id, user.username, body.comment))
        except ApprovalError as refused:
            raise HTTPException(status_code=409, detail=str(refused)) from refused
        return {"approval_id": approval_id, "state": decided.state.value,
                "decided_by": user.username,
                # Approving is permission to publish, not publication. Saying so
                # here stops "approved" being read as "live" by whoever builds
                # the screen that shows this.
                "note": "recorded. Approval permits the publication; it does "
                        "not perform it."}

    return router


def install(app: Any) -> None:
    app.include_router(build_router())
    app.include_router(build_public_router())
