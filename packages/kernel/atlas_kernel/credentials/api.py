"""The credential centre. The one door a secret comes in through, and no door out.

Everything here exists to make one asymmetry structural: a credential can be
written, tested, replaced and forgotten, and there is **no route that returns
one**. Not for an admin, not for debugging, not behind a flag. The moment such a
route exists it becomes the target, and every argument for adding it ("only
admins", "only the last four", "only in development") has been made before by
somebody whose keys later appeared in a log.

What a caller can learn about a stored credential is a fingerprint — enough to
answer "is this the same key I set last week" — and a hint of the last four
characters, suppressed entirely for a secret short enough that four characters
would be most of it.

**Storing is not connecting.** A stored-but-untested credential is
PENDING_CREDENTIAL, never CONNECTED. Reporting a key as working because somebody
pasted one is how an integration sits broken for a month behind a green tick.

**Writes require ADMIN.** A credential is the authority to act as the customer
somewhere else; handing that boundary to EXECUTE would make every automation
able to widen its own reach.

**The vault seals rather than degrading.** With no master key configured, this
surface refuses to store anything instead of falling back to plaintext, and says
so in the response.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..auth.api import current_user, requires
from ..auth.models import Scope, User
from ..integrations import BY_ID
from ..opportunity.tenancy import TenantId
from .service import CredentialMissing, CredentialService, Status
from .vault import VaultLocked, VaultSealed

#: A provider nobody has heard of is absent, not a bad request. The list of
#: providers Qevik supports is not secret, but answering differently for
#: "unknown provider" and "known provider you have not configured" is a small
#: enumeration oracle for no benefit.
NOT_FOUND = "no such provider"


def current_tenant(user: User = Depends(current_user)) -> TenantId:
    """Whose rows this request touches. Decided in `tenancy.of_user`, once.

    This was eight lines of its own here, and the same eight lines in four other
    modules with four different wordings. An operator with no customer tenant
    got a 403 from every one of them, which is a console that refuses its own
    administrator on every page it has.
    """
    from ..opportunity.tenancy import TenantRequired, of_user

    try:
        return of_user(user, method="credentials")
    except TenantRequired as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


def _service(request: Request) -> CredentialService:
    found = getattr(request.app.state, "credentials", None)
    if found is None:
        raise HTTPException(
            status_code=503,
            detail="no credential vault is configured on this deployment")
    return found


def _known(provider: str) -> str:
    if provider not in BY_ID:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return provider


class Secret(BaseModel):
    """A credential on its way in. This model never travels outward.

    `repr` is suppressed so the value cannot reach a traceback, a log line or an
    exception message by accident — the three places a secret ends up when
    nobody meant it to.
    """

    secret: str = Field(min_length=1, max_length=8192, repr=False)

    def __str__(self) -> str:                    # pragma: no cover - defensive
        return "Secret(<redacted>)"


class Toggle(BaseModel):
    enabled: bool


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api/credentials", tags=["credentials"])

    @router.get("")
    def centre(request: Request, tenant: TenantId = Depends(current_tenant),
               _: User = Depends(requires(Scope.READ))) -> dict:
        """Every provider, configured or not, with no secret in the response."""
        return _service(request).centre(tenant=tenant)

    @router.get("/{provider}")
    def one(provider: str, request: Request,
            tenant: TenantId = Depends(current_tenant),
            _: User = Depends(requires(Scope.READ))) -> dict:
        record = _service(request).record(provider=_known(provider), tenant=tenant)
        if record is None:
            integration = BY_ID[provider]
            return {"provider": provider, "name": integration.name,
                    "status": Status.NOT_CONFIGURED.value, "configured": False,
                    "credential": integration.credential,
                    "setup_url": integration.setup_url}
        return record.describe()

    @router.put("/{provider}", status_code=201)
    def store(provider: str, body: Secret, request: Request,
              tenant: TenantId = Depends(current_tenant),
              _: User = Depends(requires(Scope.ADMIN))) -> dict:
        """Put a credential in the vault.

        Returns the record, which carries a fingerprint and a hint and no
        secret. The response is deliberately the same shape as a read: there is
        no "here it is, just this once".
        """
        service = _service(request)
        try:
            record = service.store(provider=_known(provider), tenant=tenant,
                                   secret=body.secret)
        except VaultSealed as sealed:
            raise HTTPException(status_code=503, detail=str(sealed)) from sealed
        except VaultLocked as locked:
            raise HTTPException(status_code=423, detail=str(locked)) from locked
        return {**record.describe(),
                "note": "stored but not yet tested, so the status is "
                        "PENDING_CREDENTIAL rather than CONNECTED. Test it to "
                        "find out whether it works."}

    @router.post("/{provider}/rotate")
    def rotate(provider: str, body: Secret, request: Request,
               tenant: TenantId = Depends(current_tenant),
               _: User = Depends(requires(Scope.ADMIN))) -> dict:
        """Replace a credential, keeping the record and its history.

        Rotation clears the previous verification: the old key worked, and that
        says nothing about the new one. Carrying the CONNECTED status across a
        rotation is how a bad paste stays green until something fails at 3am.
        """
        service = _service(request)
        # Checked here rather than in the service, which is permissive on
        # purpose for internal callers. The distinction matters at this boundary
        # because a button labelled "Rotate" that quietly performs a first write
        # tells the operator they replaced something they never had.
        if service.record(provider=_known(provider), tenant=tenant) is None:
            raise HTTPException(
                status_code=409,
                detail=f"nothing is stored for {provider} to rotate. Store one "
                       "first — rotating into an empty slot would read as a "
                       "replacement and be a first write.")
        try:
            record = service.rotate(provider=provider, tenant=tenant,
                                    secret=body.secret)
        except VaultSealed as sealed:
            raise HTTPException(status_code=503, detail=str(sealed)) from sealed
        except VaultLocked as locked:
            raise HTTPException(status_code=423, detail=str(locked)) from locked
        return record.describe()

    @router.post("/{provider}/test")
    def test(provider: str, request: Request,
             tenant: TenantId = Depends(current_tenant),
             _: User = Depends(requires(Scope.EXECUTE))) -> dict:
        """Ask the provider whether the credential actually works.

        EXECUTE rather than ADMIN: testing changes nothing and is exactly what
        an operator should be able to do while diagnosing. The probe comes from
        the deployment, not from the request — a caller-supplied probe would be
        a caller-supplied outbound request carrying the tenant's key.
        """
        service = _service(request)
        probes = getattr(request.app.state, "credential_probes", None) or {}
        probe = probes.get(_known(provider))
        if probe is None:
            raise HTTPException(
                status_code=501,
                detail=f"no probe is implemented for {provider}, so its "
                       "credential cannot be tested here. Storing one is still "
                       "possible; it stays PENDING_CREDENTIAL until something "
                       "uses it.")
        try:
            result = service.verify(provider=provider, tenant=tenant, probe=probe)
        except CredentialMissing as missing:
            raise HTTPException(
                status_code=409, detail=f"nothing is stored for {provider}"
            ) from missing
        except VaultLocked as locked:
            raise HTTPException(status_code=423, detail=str(locked)) from locked
        return {"provider": provider, "status": result.status.value,
                "detail": result.detail, "at": result.at.isoformat(),
                "works": result.status is Status.CONNECTED}

    @router.post("/{provider}/enabled")
    def set_enabled(provider: str, body: Toggle, request: Request,
                    tenant: TenantId = Depends(current_tenant),
                    _: User = Depends(requires(Scope.ADMIN))) -> dict:
        """Turn a credential off without destroying it.

        The reason this is separate from forgetting: switching a provider off
        during an incident and switching it back on afterwards should not need
        the key to be found and pasted again.
        """
        service = _service(request)
        try:
            record = service.set_enabled(provider=_known(provider), tenant=tenant,
                                         enabled=body.enabled)
        except CredentialMissing as missing:
            raise HTTPException(status_code=404, detail=NOT_FOUND) from missing
        return record.describe()

    @router.delete("/{provider}", status_code=200)
    def forget(provider: str, request: Request,
               tenant: TenantId = Depends(current_tenant),
               _: User = Depends(requires(Scope.ADMIN))) -> dict:
        """Destroy the stored secret and the record of it.

        Irreversible on purpose, and it does not tell the caller whether
        anything was there — a delete that answers differently for "removed" and
        "there was nothing" is a way to ask which providers a tenant uses.
        """
        _service(request).forget(provider=_known(provider), tenant=tenant)
        return {"provider": provider, "forgotten": True,
                "note": "the secret is gone from the vault. Nothing here says "
                        "whether one was present."}

    return router


def install(app: Any) -> None:
    app.include_router(build_router())
