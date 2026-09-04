"""`/api/crm` — the pipeline, derived on read.

Two routes, because there are two questions: what does the whole pipeline look
like, and what is going on with this one company. Both are reads; nothing here
sends, approves or writes a stage, because there is no stage to write.

Deriving on every request rather than caching is a deliberate choice at this
size. A cached pipeline is a second answer that goes stale the moment a message
is sent, and the derivation is a loop over rows that already had to be read.
When it stops being cheap, the fix is a materialised view of the same function —
not a stored stage field, which is the thing this design exists to avoid.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth.api import Scope, User, requires
from ..opportunity.api import current_tenant
from ..opportunity.tenancy import TenantId
from . import pipeline


def _repository(request: Request):
    from ..opportunity.repository import OpportunityRepository

    found = getattr(request.app.state, "opportunity_repository", None)
    if found is None:
        found = OpportunityRepository()
        request.app.state.opportunity_repository = found
    return found


def _channels_ready(request: Request) -> frozenset[str]:
    """Which outreach channels this deployment can actually use.

    Read from the app rather than from the environment inside the derivation, so
    the pipeline behaves the same in a test as in production and the deployment
    fact lives in one place.
    """
    ready = getattr(request.app.state, "outreach_channels_ready", None)
    return frozenset(ready) if ready else frozenset()


def _relationship_for(repository, business, *, channels: frozenset[str]):
    """Assemble one company's evidence and derive from it.

    Each read is defensive: a repository that cannot answer one question must
    not blank the whole pipeline. An empty list here means "nothing recorded",
    which is what the derivation already treats as the earliest stage — the same
    answer it would give for a company nobody has touched.
    """
    def safely(call, default):
        try:
            return call()
        except Exception:  # pragma: no cover - a partial store is not a crash
            return default

    findings = safely(lambda: list(repository.list_findings(business.id)), [])
    messages = safely(lambda: list(repository.messages_for(business.id)), [])
    events = safely(lambda: list(repository.timeline(business.id)), [])
    # There is no opportunity-by-business read on the repository, and adding one
    # is not this module's call to make. The derivation already treats a missing
    # opportunity as "not scored yet", which is the truthful reading of a store
    # that cannot answer the question.
    opportunity = safely(lambda: repository.opportunity_for(business.id), None) \
        if hasattr(repository, "opportunity_for") else None

    return pipeline.relationship(business, findings=findings, opportunity=opportunity,
                                 messages=messages, events=events,
                                 channels_ready=channels)


def _as_dict(r: pipeline.Relationship) -> dict[str, Any]:
    return {
        "business_id": r.business_id,
        "name": r.name,
        "stage": r.stage.value,
        "because": r.because,
        "findings": r.findings,
        "severity": r.severity,
        "score": r.score,
        "contactable": r.contactable,
        "events": r.events,
        "last_activity": r.last_activity.isoformat() if r.last_activity else None,
        "next_action": {
            "kind": r.next_action.kind.value,
            "summary": r.next_action.summary,
            "because": r.next_action.because,
            "blocked_by": r.next_action.blocked_by,
            "blocked": r.next_action.blocked,
        },
    }


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api/crm", tags=["crm"])

    @router.get("/pipeline")
    def whole_pipeline(request: Request, limit: int = 200,
                       tenant: TenantId = Depends(current_tenant),
                       _: User = Depends(requires(Scope.READ))) -> dict[str, Any]:
        """Every relationship, with the board over it.

        `limit` is a page size, not a filter: the board counts what it was given,
        and a truncated list with a total that disagreed with it would be a
        dashboard that lies quietly.
        """
        repository = _repository(request)
        channels = _channels_ready(request)
        try:
            businesses = list(repository.list_businesses(tenant=tenant))
        except Exception:
            # The store could not be read. Not an empty pipeline — the two are
            # different facts and only one of them means "there is no work".
            return {"known": False, "relationships": [], "board": {},
                    "detail": ("the opportunity store could not be read, which is "
                               "not the same as having no companies")}

        relationships = [_relationship_for(repository, b, channels=channels)
                         for b in businesses[:limit]]
        return {
            "known": True,
            "relationships": [_as_dict(r) for r in relationships],
            "board": pipeline.board(relationships),
            "truncated": len(businesses) > limit,
            "total_known": len(businesses),
        }

    @router.get("/{business_id}")
    def one_relationship(business_id: str, request: Request,
                         tenant: TenantId = Depends(current_tenant),
                         _: User = Depends(requires(Scope.READ))) -> dict[str, Any]:
        repository = _repository(request)
        try:
            business = repository.get_business(business_id, tenant=tenant)
        except Exception:
            business = None
        if business is None:
            raise HTTPException(status_code=404, detail=f"no business {business_id!r}")
        return _as_dict(_relationship_for(repository, business,
                                          channels=_channels_ready(request)))

    return router


def install(app) -> None:
    app.include_router(build_router())


__all__ = ["build_router", "install"]
