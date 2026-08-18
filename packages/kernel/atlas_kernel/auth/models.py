"""Who may ask Qevik to do what.

The control plane can deploy websites, send email and spend money. It has run on
loopback until now for exactly that reason, and this module is what makes
exposing it defensible rather than reckless.

Three decisions shape everything here.

**Scopes live on the user record, never in the request.** A caller says what it
wants to do; it never says what it is allowed to do. This is the property that
makes the rule "a model must never grant itself permission" true structurally
rather than by convention — a plan, a prompt-injected page and a compromised
client are all just requests, and none of them can widen a scope.

**Tokens are stored hashed.** A stolen database of session tokens is a stolen
set of live sessions, and the fix is the same one used for passwords: keep a
verifier, not the secret.

**Approval outranks scope.** Having `PUBLISH` means a publish may be *proposed*.
Irreversible and outward-facing actions still route through the approval queue,
because a scope is a standing grant and an approval is a decision about one
specific thing.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Scope(StrEnum):
    """What a principal may do. Ordered roughly by blast radius."""

    #: See jobs, plans, artifacts, health. Changes nothing.
    READ = "read"
    #: Run plans that build and test inside a workspace. No outward effect.
    EXECUTE = "execute"
    #: Put something where the public can reach it.
    PUBLISH = "publish"
    #: Send email or messages to people outside the system.
    COMMUNICATE = "communicate"
    #: Spend money, or commit to spending it.
    FINANCIAL = "financial"
    #: Delete, overwrite or take down. Separate from publish because undoing a
    #: publication and destroying the thing published are different mistakes.
    DESTRUCTIVE = "destructive"
    #: Manage users and scopes. Held by people, never by automation.
    ADMIN = "admin"


#: What a new operator gets unless told otherwise. Deliberately not PUBLISH:
#: the safe default for an account that can reach the internet on your behalf is
#: that it cannot.
DEFAULT_SCOPES = frozenset({Scope.READ, Scope.EXECUTE})

#: Scopes that always require a human approval per action, no matter who holds
#: them. A standing grant says "you may propose this"; it never says "do it
#: without asking".
ALWAYS_APPROVED = frozenset({Scope.PUBLISH, Scope.COMMUNICATE, Scope.FINANCIAL, Scope.DESTRUCTIVE})

SESSION_LIFETIME = timedelta(hours=12)
#: scrypt parameters. n=2**15, r=8 costs about 32MB and ~100ms per verification:
#: slow enough that guessing is expensive, fast enough for a login, and small
#: enough that a handful of concurrent logins fit inside the API's 1.5GB cgroup.
#:
#: `maxmem` is explicit because OpenSSL's default ceiling is *below* what these
#: parameters need, so omitting it fails at the first login with "memory limit
#: exceeded" — a runtime error rather than a configuration one, and confusing
#: precisely because the parameters themselves are unremarkable.
_SCRYPT = {"n": 2**15, "r": 8, "p": 1, "dklen": 32, "maxmem": 64 * 1024 * 1024}
MIN_PASSWORD_LENGTH = 12


class AuthError(RuntimeError):
    """Authentication or authorisation failed."""


class NotAuthenticated(AuthError):
    """No valid credential. Distinct from having one that is insufficient."""


class NotAuthorised(AuthError):
    """A valid principal without the scope required.

    Separate from NotAuthenticated because the remedies differ: log in versus
    ask someone to widen your access, and conflating them sends people to the
    wrong place.
    """


def _now() -> datetime:
    return datetime.now(UTC)


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    """Derive a verifier. The password itself is never stored or logged."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(
            f"password must be at least {MIN_PASSWORD_LENGTH} characters; "
            "this account can deploy websites and send email"
        )
    salt = salt or secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${derived.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time comparison against the stored verifier."""
    try:
        scheme, salt_hex, expected = stored.split("$", 2)
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    try:
        derived = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex), **_SCRYPT)
    except ValueError:
        return False
    # compare_digest, not ==: an early-exit comparison leaks how much of the
    # verifier matched, one byte at a time.
    return hmac.compare_digest(derived.hex(), expected)


def new_token() -> tuple[str, str]:
    """A session token and the verifier to store for it.

    The token is returned once, to the client. Only its hash is kept, so a
    stolen store is not a stolen set of live sessions. SHA-256 rather than
    scrypt here on purpose: a 256-bit random token has no guessable structure,
    so slowing verification buys nothing and would cost a KDF on every request.
    """
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class User(BaseModel):
    """A person who may operate Qevik."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: f"usr_{secrets.token_hex(6)}")
    username: str
    password_hash: str
    scopes: frozenset[Scope] = DEFAULT_SCOPES
    created_at: datetime = Field(default_factory=_now)
    disabled: bool = False

    def has(self, scope: Scope) -> bool:
        return Scope.ADMIN in self.scopes or scope in self.scopes

    def require(self, scope: Scope) -> None:
        if self.disabled:
            raise NotAuthorised(f"{self.username} is disabled")
        if not self.has(scope):
            raise NotAuthorised(
                f"{self.username} does not hold the {scope} scope. "
                "Scopes are granted by an administrator, never requested."
            )

    def redacted(self) -> dict:
        """Safe to log or return. The verifier never leaves this object."""
        return {
            "id": self.id,
            "username": self.username,
            "scopes": sorted(str(s) for s in self.scopes),
            "disabled": self.disabled,
        }


class Session(BaseModel):
    """A logged-in session. Identified by a token only its holder has."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: f"ses_{secrets.token_hex(6)}")
    user_id: str
    token_hash: str
    created_at: datetime = Field(default_factory=_now)
    expires_at: datetime = Field(default_factory=lambda: _now() + SESSION_LIFETIME)
    revoked: bool = False
    #: Recorded for the audit trail, not for authorisation — an address is
    #: trivially spoofed and must never be part of a decision.
    user_agent: str = ""

    @property
    def alive(self) -> bool:
        return not self.revoked and _now() < self.expires_at


def bootstrap_password() -> str | None:
    """The initial admin password, from the environment.

    Read once at first start and never stored in the repository. Absent means no
    account is created, which is the correct default: a control plane that
    invents its own credentials has a known password.
    """
    for prefix in ("QEVIK_", "ATLAS_", ""):
        value = os.environ.get(f"{prefix}ADMIN_PASSWORD", "")
        if value.strip():
            return value.strip()
    return None
