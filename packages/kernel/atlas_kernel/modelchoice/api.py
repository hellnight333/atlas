"""Choosing which model does which job.

Four routes, and the interesting one is the read: `GET /api/models` returns the
models this tenant can run **and the ones it cannot, with the reason**. A list
of only the usable models cannot answer "why isn't Claude here", and that is the
question that brings somebody to this screen in the first place.

Choosing needs ADMIN. A model choice is a spending decision — implementation
work on Opus costs many times the same work on a cheap model — and it changes
what every subsequent mission runs on. That is not the same authority as being
able to start a mission.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..auth.api import current_user, requires
from ..auth.models import Scope, User
from ..credentials.models import PROVIDER_MODELS, Role
from ..credentials.service import CredentialService
from ..opportunity.tenancy import TenantId
from .store import SelectionStore, available, chosen


def current_tenant(user: User = Depends(current_user)) -> TenantId:
    """Whose rows this request touches. Decided in `tenancy.of_user`, once.

    This was eight lines of its own here, and the same eight lines in four other
    modules with four different wordings. An operator with no customer tenant
    got a 403 from every one of them, which is a console that refuses its own
    administrator on every page it has.
    """
    from ..opportunity.tenancy import TenantRequired, of_user

    try:
        return of_user(user, method="model selection")
    except TenantRequired as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


def _credentials(request: Request) -> CredentialService:
    found = getattr(request.app.state, "credentials", None)
    if found is None:
        raise HTTPException(
            status_code=503,
            detail="no credential vault is configured, so no model registry "
                   "can be built")
    return found


def _selections(request: Request) -> SelectionStore:
    store = getattr(request.app.state, "model_selections", None)
    if store is None:
        raise HTTPException(status_code=503,
                            detail="no model selection store is configured")
    return store


class RoleChoice(BaseModel):
    """A model for a role. An empty model clears the choice."""

    model: str = Field(default="", max_length=200)


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api/models", tags=["models"])

    @router.get("")
    def listing(request: Request, tenant: TenantId = Depends(current_tenant),
                _: User = Depends(requires(Scope.READ))) -> dict:
        """Every model, usable or not, with the reason it is not."""
        credentials = _credentials(request)
        models = available(credentials, tenant=tenant)
        return {
            "models": models,
            "usable": [m for m in models if m["usable"]],
            "blocked": [m for m in models if not m["usable"]],
            "roles": [r.value for r in Role],
            "providers": sorted(PROVIDER_MODELS),
        }

    @router.get("/selection")
    def selection(request: Request, tenant: TenantId = Depends(current_tenant),
                  _: User = Depends(requires(Scope.READ))) -> dict:
        """What runs each role now, and whether that was chosen or defaulted."""
        credentials = _credentials(request)
        current = _selections(request).get(tenant=tenant)
        choices = chosen(credentials, current, tenant=tenant)
        return {
            "selection": current.by_role,
            "roles": [c.model_dump(mode="json") for c in choices],
            "unavailable": [c.role for c in choices if not c.available],
            "note": ("A role whose chosen model is unavailable is reported, "
                     "never silently reassigned: running the work on a model "
                     "nobody picked and recording it as chosen is worse than "
                     "refusing."),
        }

    @router.put("/selection/{role}")
    def choose(role: str, body: RoleChoice, request: Request,
               tenant: TenantId = Depends(current_tenant),
               _: User = Depends(requires(Scope.ADMIN))) -> dict:
        """Pick a model for one role.

        ADMIN, because this is a spending decision as much as a technical one
        and it changes what every later mission runs on.
        """
        try:
            wanted = Role(role)
        except ValueError as unknown:
            raise HTTPException(
                status_code=404,
                detail=f"no such role. Roles: "
                       f"{', '.join(r.value for r in Role)}") from unknown

        credentials = _credentials(request)
        if body.model:
            known = {m["model"] for m in available(credentials, tenant=tenant)}
            if body.model not in known:
                raise HTTPException(
                    status_code=422,
                    detail=f"{body.model} is not a model Qevik knows. Choosing "
                           "an unknown one would fail at the first invocation, "
                           "far from here.")

        updated = _selections(request).set_role(tenant=tenant, role=wanted,
                                                model=body.model)
        choices = chosen(credentials, updated, tenant=tenant)
        picked = next(c for c in choices if c.role == wanted.value)
        return {
            "role": wanted.value, "selection": updated.by_role,
            "resolved": picked.model_dump(mode="json"),
            # Choosing a model whose credential is missing is allowed and
            # reported. Refusing would make it impossible to configure Qevik
            # before entering keys, which is the order most people work in.
            "note": "" if picked.available else
                    "chosen, but not currently runnable — enter the credential "
                    "in the Credential Centre and this becomes active with no "
                    "further change here",
        }

    @router.delete("/selection")
    def reset(request: Request, tenant: TenantId = Depends(current_tenant),
              _: User = Depends(requires(Scope.ADMIN))) -> dict:
        """Back to the registry's own preference for every role."""
        _selections(request).clear(tenant=tenant)
        return {"selection": {}, "note": "every role falls back to the "
                                         "registry's cheapest capable model"}

    return router


def install(app: Any) -> None:
    app.include_router(build_router())
    if getattr(app.state, "model_selections", None) is None:
        app.state.model_selections = SelectionStore()
