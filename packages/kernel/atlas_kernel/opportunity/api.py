"""What discovery found, in the shape a phone can act on.

Deliberately small. The brief was explicit that this is not the moment for a
dashboard: what a person needs on a phone is *what turned up, why it might
matter, what it rests on, and what to do* — and the ability to say yes, no, or
not yet.

## The four parts arrive as four parts

`Signal.summary()` keeps observation, evidence, inference and action separate,
and this hands that through unchanged. Flattening them into a sentence here is
the one thing the surface must not do: the flattened form is the one that reads
as though somebody had observed the inference.

Each inference carries `is_an_inference: true` in the payload itself, so a
renderer cannot forget. A client that ignores it will show a hedge as a
headline, which is exactly what the label exists to prevent — but at least the
data said so.

## Nothing here executes anything

`/watch` and `/ignore` record a decision about *attention*. Approving the work
a signal suggests is a mission, and missions are created through the mission
API behind `policy.decide` — a discovery surface that could start work would be
a scanner with authority, which is the thing the whole design refuses.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth.api import current_user, requires
from ..auth.models import Scope, User
from .discovery import DiscoveryState
from .discovery import describe as describe_states
from .repository import OpportunityRepository
from .tenancy import TenantId


def current_tenant(user: User = Depends(current_user)) -> TenantId:
    return user.tenant_id


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api/discovery", tags=["discovery"])

    def repository(request: Request) -> OpportunityRepository:
        found = getattr(request.app.state, "opportunity_repository", None)
        if found is None:
            found = OpportunityRepository()
            request.app.state.opportunity_repository = found
        return found

    @router.get("/states")
    def states(_: User = Depends(requires(Scope.READ))) -> dict:
        """What each discovery state may be read as claiming.

        Served rather than hardcoded in the client, because the one thing a
        surface must not do is invent a friendlier meaning for
        `DISCOVERED_BY_QEVIK` than the one the kernel gives it.
        """
        return {"states": describe_states()}

    @router.get("")
    def recent(request: Request, limit: int = 25,
               tenant: TenantId = Depends(current_tenant),
               _: User = Depends(requires(Scope.READ))) -> dict:
        """The newest sightings that were not already known.

        `claims_about_the_world` travels with every row. A phone showing "new
        business" for something that is merely new to Qevik would be making the
        claim this system exists to avoid, and the row says which it is.
        """
        try:
            found = repository(request).recent_discoveries(
                limit=limit, tenant=tenant)
        except Exception as unavailable:          # noqa: BLE001 - reported, not 500
            raise HTTPException(
                status_code=503,
                detail="the discovery memory could not be read. This is not "
                       "the same as nothing having been discovered.",
            ) from unavailable
        # Why the list is the length it is. An empty feed reads as "the scan
        # ran and found nothing", and in production it means something else:
        # most businesses arrived through a path that records no sighting.
        try:
            coverage = repository(request).sighting_coverage()
        except Exception:                          # noqa: BLE001 - reported
            coverage = {}

        return {
            "discoveries": found,
            "coverage": coverage,
            "counts": {
                "total": len(found),
                "claiming_about_the_world": sum(
                    1 for row in found if row.get("claims_about_the_world")),
            },
            # Said in the payload so a client cannot round it up.
            "note": ("A discovery is new to Qevik. Only rows with "
                     "claims_about_the_world are evidenced as new to their "
                     "source, and new to a source is not new to the world."),
        }

    @router.get("/opportunities")
    def opportunities(request: Request, limit: int = 25,
                      tenant: TenantId = Depends(current_tenant),
                      _: User = Depends(requires(Scope.READ))) -> dict:
        """What was detected, best first. **No demo rows.**

        Everything here came out of a real scan against a real source, and an
        empty list means nothing was detected — not that the feature is
        unfinished. The four parts arrive as four parts, so a client cannot
        render an inference as an observation without ignoring the labels.

        Declared above `/{business_id}/sightings` so `opportunities` is never
        read as a business id: FastAPI matches in declaration order, and a
        route losing that race is how `/api/missions/origins` was once served
        by the mission-detail handler.
        """
        try:
            found = repository(request).open_signals(limit=limit, tenant=tenant)
        except Exception as unavailable:          # noqa: BLE001 - reported
            raise HTTPException(
                status_code=503,
                detail="the opportunity memory could not be read. This is not "
                       "the same as there being no opportunities.",
            ) from unavailable
        return {
            "opportunities": found,
            "counts": {
                "total": len(found),
                "needing_approval": sum(1 for row in found
                                        if row.get("needs_approval")),
                "valued": sum(1 for row in found
                              if row["value"]["status"] != "UNKNOWN"),
            },
            "note": ("Every opportunity carries the evidence it rests on. An "
                     "inference is labelled as one. A value of UNKNOWN means "
                     "nobody measured it, and is not zero."),
        }

    @router.get("/opportunities/{signal_id}")
    def opportunity(signal_id: str, request: Request,
                    tenant: TenantId = Depends(current_tenant),
                    _: User = Depends(requires(Scope.READ))) -> dict:
        """One opportunity, with its observation, evidence, inference and
        suggested action kept apart."""
        found = repository(request).get_signal(signal_id, tenant=tenant)
        if found is None:
            # Absent, not forbidden: a 403 would confirm it exists.
            raise HTTPException(status_code=404, detail="no such opportunity")
        return found

    @router.get("/{business_id}/dossier")
    def dossier(business_id: str, request: Request,
                tenant: TenantId = Depends(current_tenant),
                _: User = Depends(requires(Scope.READ))) -> dict:
        """Everything known about one prospect, from the models that own it.

        Thirteen questions a person asks before deciding whether to write to a
        stranger. It assembles and stores nothing: a second copy of "was this
        sent" would be a second answer to a question that has one.

        A missing fact is reported as missing. A dossier that filled gaps would
        be most confident exactly where it knows least.
        """
        from .dossier import assemble

        return assemble(business_id, memory=repository(request), tenant=tenant)

    @router.get("/{business_id}/sightings")
    def sightings(business_id: str, request: Request,
                  tenant: TenantId = Depends(current_tenant),
                  _: User = Depends(requires(Scope.READ))) -> dict:
        """Every observation of one entity, oldest first — the evidence trail."""
        history = repository(request).sightings_for(business_id, tenant=tenant)
        if not history:
            # Absent, not forbidden: a 403 would confirm the record exists.
            raise HTTPException(status_code=404,
                                detail="no sightings for that id")
        return {"business_id": business_id, "sightings": history,
                "first_seen_at": history[0]["observed_at"],
                "last_seen_at": history[-1]["observed_at"]}

    return router


def install(app) -> None:
    app.include_router(build_router())


__all__ = ["DiscoveryState", "build_router", "install"]
