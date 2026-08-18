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

import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .models import NotAuthenticated, NotAuthorised, Scope, User
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
    }
)

#: Cookie rather than a header for the browser UI, so the token is not reachable
#: from JavaScript and therefore not stealable by injected script.
SESSION_COOKIE = "qevik_session"

#: Login attempts per address per window. Slow enough to make guessing
#: impractical, generous enough that a person mistyping twice is unaffected.
LOGIN_ATTEMPTS = 10
LOGIN_WINDOW_SECONDS = 300.0

_attempts: dict[str, list[float]] = defaultdict(list)


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


def build_router(store: AuthStore | None = None) -> APIRouter:
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

    class ScopeChange(BaseModel):
        username: str
        scopes: list[str]

    @router.post("/users/scopes", dependencies=[Depends(requires(Scope.ADMIN))])
    def set_scopes(body: ScopeChange) -> dict:
        """Only an administrator reaches this, which is the whole point: scopes
        are granted, never requested."""
        try:
            scopes = frozenset(Scope(s) for s in body.scopes)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=f"unknown scope: {error}") from error
        return store.set_scopes(body.username, scopes).redacted()

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
        if path in PUBLIC_PATHS or request.method == "OPTIONS":
            return await call_next(request)
        try:
            request.state.user = store.authenticate(token_from(request))
        except NotAuthenticated as error:
            from fastapi.responses import JSONResponse

            return JSONResponse(status_code=401, content={"detail": str(error)})
        return await call_next(request)

    app.include_router(build_router(store))
