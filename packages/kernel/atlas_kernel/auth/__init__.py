"""Authentication and authorisation for the Qevik control plane.

Scopes live on the user record and are never read from a request, which is what
makes "a model must never grant itself permission" structural rather than
aspirational: a plan, a prompt-injected page and a compromised client are all
just requests, and none of them can widen a scope.
"""

from .api import SESSION_COOKIE, current_user, install, requires
from .models import (
    ALWAYS_APPROVED,
    DEFAULT_SCOPES,
    AuthError,
    NotAuthenticated,
    NotAuthorised,
    Scope,
    Session,
    User,
    hash_password,
    verify_password,
)
from .store import AuthStore, bootstrap_admin, init_auth

__all__ = [
    "ALWAYS_APPROVED",
    "DEFAULT_SCOPES",
    "SESSION_COOKIE",
    "AuthError",
    "AuthStore",
    "NotAuthenticated",
    "NotAuthorised",
    "Scope",
    "Session",
    "User",
    "bootstrap_admin",
    "current_user",
    "hash_password",
    "init_auth",
    "install",
    "requires",
    "verify_password",
]
