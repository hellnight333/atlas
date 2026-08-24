"""Authentication for the control plane.

**Deny by default, allow-list the exceptions.** The API is roughly four thousand
lines of routes that were written when the only way to reach them was a loopback
socket. Adding a dependency to each one would protect every route somebody
remembered, and the routes people forget are exactly the ones worth protecting.
Middleware inverts that: a new endpoint is protected the moment it exists, and
making one public takes a deliberate edit to a short list.

The allow-list is short on purpose and every entry has a reason.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .models import AuthError, NotAuthenticated, NotAuthorised, Scope, User
from .store import AuthStore

#: Reachable without a session. Nothing here changes state or reveals anything
#: an unauthenticated caller should not see.
PUBLIC_PATHS = frozenset(
    {
        "/health",  # liveness, checked by systemd and by the operator
        "/auth/login",  # the way in
        "/openapi.json",
        "/docs",
        "/redoc",
        # The acquisition entry point: a visitor audits a site before they have
        # an account. It returns only what `customer.public.audit` assembles,
        # which is an allow-list of fields rather than a redaction of a private
        # payload — see customer/public.py.
        "/api/public/audit",
    }
)

#: The console's own routes: the shell, and the client-side paths it owns.
#:
#: Deliberately a *separate* set from `PUBLIC_PATHS`, which is pinned exactly by
#: a test so that an unauthenticated API route is a conscious decision. These
#: serve one static HTML file that carries no data — every number on screen is
#: fetched from an API that authenticates separately — and the login form has to
#: be reachable before anybody has a session.
#:
#: `/api/health` is **not** here, and was briefly. It reports whether the vault
#: is sealed, which components are absent and what claiming guarantees — that is
#: deployment posture, and it belongs behind a session. `/health` stays public
#: for liveness and returns nothing but `{"status": "ok"}`.
CONSOLE_PATHS = frozenset({
    "/", "/dashboard", "/roadmap", "/missions", "/chat", "/actions",
    "/credentials", "/models", "/businesses", "/publications", "/measurements",
    "/reports", "/history", "/settings",
})

#: Cookie rather than a header for the browser UI, so the token is not reachable
#: from JavaScript and therefore not stealable by injected script.
SESSION_COOKIE = "qevik_session"

#: Login attempts per address per window. Slow enough to make guessing
#: impractical, generous enough that a person mistyping twice is unaffected.
LOGIN_ATTEMPTS = 10
LOGIN_WINDOW_SECONDS = 300.0

_attempts: dict[str, list[float]] = defaultdict(list)


log = logging.getLogger(__name__)


def _rate_limited(key: str) -> bool:
    now = time.monotonic()
    recent = [t for t in _attempts[key] if now - t < LOGIN_WINDOW_SECONDS]
    _attempts[key] = recent
    if len(recent) >= LOGIN_ATTEMPTS:
        return True
    recent.append(now)
    return False


def token_from(request: Request) -> str:
    """The session token, from a cookie or a bearer header.

    Both are supported: the browser UI uses the cookie, and scripts use the
    header. The cookie is checked first because that is the interactive path.
    """
    cookie = request.cookies.get(SESSION_COOKIE, "")
    if cookie:
        return cookie
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return ""


def current_user(request: Request) -> User:
    """The authenticated user, or a 401.

    Resolved by the middleware and stashed on the request, so a route that
    declares this dependency does not re-verify the token on every call.
    """
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return user


def requires(scope: Scope):
    """Dependency factory for a route that needs a specific scope.

    The scope is named by the *route*, never by the caller. A request cannot ask
    for a wider one, which is what makes "a model may not grant itself
    permission" a property of the design rather than a promise.
    """

    def dependency(user: User = Depends(current_user)) -> User:
        try:
            user.require(scope)
        except NotAuthorised as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        return user

    return dependency


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    user: dict
    #: Scopes that still require a per-action approval even though the user
    #: holds them, so a UI can say so before someone clicks.
    approval_required_for: list[str] = Field(default_factory=list)


class ScopeChange(BaseModel):
    """Which scopes an administrator is granting to whom.

    Module level, not nested inside the route factory — the same trap
    `control/api.py` records. A model declared inside a function is invisible to
    the schema generator, and here it did more than break one route's
    validation: generating the OpenAPI document for the *whole application*
    raised `PydanticUserError`, so `/docs` and `/openapi.json` returned 500 on
    every deployment that mounted this router.
    """

    username: str
    scopes: list[str]


def build_router(store: AuthStore | None = None, audit=None) -> APIRouter:
    store = store or AuthStore()
    router = APIRouter(prefix="/auth", tags=["auth"])

    @router.post("/login", response_model=LoginResponse)
    def login(body: LoginRequest, request: Request, response: Response) -> LoginResponse:
        client = request.client.host if request.client else "unknown"
        if _rate_limited(client):
            raise HTTPException(
                status_code=429,
                detail=(f"too many login attempts; wait {LOGIN_WINDOW_SECONDS / 60:.0f} minutes"),
            )
        try:
            token, user = store.login(
                body.username, body.password, user_agent=request.headers.get("user-agent", "")
            )
        except NotAuthenticated as error:
            # Deliberately unspecific. Saying which half was wrong confirms
            # which usernames exist.
            raise HTTPException(status_code=401, detail=str(error)) from error

        response.set_cookie(
            SESSION_COOKIE,
            token,
            httponly=True,  # unreachable from JavaScript
            samesite="strict",  # not sent on cross-site requests
            secure=request.url.scheme == "https",
            max_age=12 * 3600,
            path="/",
        )
        from .models import ALWAYS_APPROVED

        return LoginResponse(
            token=token,
            user=user.redacted(),
            approval_required_for=sorted(str(s) for s in ALWAYS_APPROVED if user.has(s)),
        )

    @router.post("/logout")
    def logout(request: Request, response: Response) -> dict:
        token = token_from(request)
        if token:
            store.logout(token)
        response.delete_cookie(SESSION_COOKIE, path="/")
        return {"ok": True}

    @router.get("/me")
    def me(user: User = Depends(current_user)) -> dict:
        from .models import ALWAYS_APPROVED

        return {
            **user.redacted(),
            "approval_required_for": sorted(str(s) for s in ALWAYS_APPROVED if user.has(s)),
            "active_sessions": store.active_sessions(user.id),
        }

    @router.get("/users", dependencies=[Depends(requires(Scope.ADMIN))])
    def list_users() -> list[dict]:
        return [u.redacted() for u in store.list_users()]

    @router.post("/users/scopes", dependencies=[Depends(requires(Scope.ADMIN))])
    def set_scopes(body: ScopeChange) -> dict:
        """Only an administrator reaches this, which is the whole point: scopes
        are granted, never requested."""
        try:
            scopes = frozenset(Scope(s) for s in body.scopes)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=f"unknown scope: {error}") from error
        return store.set_scopes(body.username, scopes).redacted()

    @router.delete("/users/{username}", dependencies=[Depends(requires(Scope.ADMIN))])
    def delete_user(username: str, user: User = Depends(current_user)) -> dict:
        """Remove an account. Administrator only, and it cannot be undone.

        Named for exactly one thing. There is no bulk endpoint and no query
        filter, because the safety of a destructive route comes from what it is
        unable to express, not from how carefully it is called.

        The removal is recorded before it is returned. An account disappearing
        with no trace of who removed it, or of the scopes it held, is the part
        that matters months later.
        """
        try:
            removed = store.delete_user(username, requested_by=user.username)
        except AuthError as error:
            # "no such user" is a 404; a refusal to lock the system out is a 409.
            missing = "no user" in str(error)
            raise HTTPException(status_code=404 if missing else 409,
                                detail=str(error)) from error
        # The store already records the removal; this adds who asked for it.
        log.info("auth: deletion of %s requested by %s", removed["username"], user.username)
        if audit is not None:
            audit(actor=user.username, removed=removed)
        return {"deleted": True, **removed, "deleted_by": user.username}

    return router


def install(app, store: AuthStore | None = None) -> None:
    """Protect every route, then add the login routes.

    Order matters: the middleware is registered first so it sees every request,
    including ones for routes added afterwards.
    """
    store = store or AuthStore()

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        path = request.url.path
        if (path in PUBLIC_PATHS or path in CONSOLE_PATHS
                or request.method == "OPTIONS"):
            return await call_next(request)
        try:
            request.state.user = store.authenticate(token_from(request))
        except NotAuthenticated as error:
            from fastapi.responses import JSONResponse

            return JSONResponse(status_code=401, content={"detail": str(error)})
        return await call_next(request)

    app.include_router(build_router(store))
