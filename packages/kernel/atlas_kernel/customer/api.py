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

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import controlplane
from ..auth.api import current_user, requires
from ..auth.models import Scope, User
from ..credits.models import ESSENTIAL_FLOOR, INCLUDED, NoPlan
from ..customer import public
from ..customer import strategy as strategy_service
from ..customer import tasks as task_service
from ..integrations import registry as integration_registry
from ..measurement import service as measurement_service
from ..opportunity.tenancy import TenantId
from ..publication import service as publication_service
from ..publication import staging as staging_service
from ..roadmap.lifecycle import facts_for
from ..roadmap.presentation import capabilities, view

#: The single message for every miss. Deliberately identical whether the thing
#: does not exist or belongs to somebody else.
NOT_FOUND = "no such resource"


def current_tenant(user: User = Depends(current_user)) -> TenantId:
    """The tenant this request acts for, or a refusal.

    Raises rather than returning a default. An implicit fallback here would make
    every downstream `owns()` check pass for whichever tenant the fallback named,
    and every one of them would look correct in review.
    """
    tenant = (user.tenant_id or "").strip()
    if not tenant:
        raise HTTPException(
            status_code=403,
            detail="this account is not attached to a customer. Operator "
                   "accounts use the internal surfaces, which name a tenant "
                   "explicitly.")
    return tenant


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

    return router


def install(app: Any) -> None:
    app.include_router(build_router())
    app.include_router(build_public_router())
