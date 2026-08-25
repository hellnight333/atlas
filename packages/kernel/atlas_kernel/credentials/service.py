"""The Credential Center: what is connected, what is not, and why.

Sits between three things that already exist and joins them without replacing
any of them. `Connection` (from `publication`) is still the reference; the
`integrations` registry is still the catalogue of providers; `Vault` holds the
value. This adds the part none of them had: a status per provider that reflects
whether the credential *works*, and a place to store one that outlives the
session that entered it.

**Status is derived, with one exception that is deliberately stored.** Whether a
credential exists is derived from the vault. Whether it *verified* cannot be —
verification is a network call with a moment in time attached, so the result and
its timestamp are recorded. A status that re-tested on every page load would
hammer a provider and still be stale by the time it rendered.

**Nothing here returns a secret.** `describe()` returns metadata; the only
method that yields a value is `resolve()`, which exists for the one caller about
to make a request with it. §17's tests read this module's output looking for
key material and must find none.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ..integrations.registry import BY_ID, INTEGRATIONS
from ..opportunity.models import BusinessEvent
from ..opportunity.tenancy import TenantId, owns
from ..opportunity.tenancy import require as _require_tenant
from ..publication.models import Connection, ConnectionKind
from .vault import Vault, VaultError, fingerprint, hint

log = logging.getLogger(__name__)

FACTORY = "credentials"
STORED = "credential_stored"
VERIFIED = "credential_verified"
ROTATED = "credential_rotated"
DISABLED = "credential_disabled"
#: A destroyed credential. Recorded rather than deleted, so a fold does not
#: resurrect what an operator deliberately removed.
FORGOTTEN = "credential_forgotten"


class Status(StrEnum):
    """The statuses §6 names. Each says something different to the operator."""

    CONNECTED = "CONNECTED"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    INVALID_CREDENTIAL = "INVALID_CREDENTIAL"
    INSUFFICIENT_PERMISSION = "INSUFFICIENT_PERMISSION"
    RATE_LIMITED = "RATE_LIMITED"
    NETWORK_ERROR = "NETWORK_ERROR"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    DISABLED = "DISABLED"
    PENDING_CREDENTIAL = "PENDING_CREDENTIAL"


#: Statuses meaning "do not attempt to use this". A caller that ignores these
#: gets a refusal from `resolve` rather than a confusing provider error.
UNUSABLE: frozenset[Status] = frozenset({
    Status.NOT_CONFIGURED, Status.PENDING_CREDENTIAL, Status.DISABLED,
    Status.INVALID_CREDENTIAL, Status.INSUFFICIENT_PERMISSION,
})


class CredentialDisabled(Exception):
    """The credential exists and may not be used."""


class CredentialMissing(Exception):
    """Nothing is stored for this provider and tenant.

    Never falls back to another tenant's credential — §17.14. The failure mode
    it prevents is one customer's work being billed to another's account.
    """


class Verification(BaseModel):
    """The result of actually asking the provider, and when."""

    model_config = ConfigDict(frozen=True)

    status: Status
    #: Human-readable, and never carrying the secret or a provider's echo of it.
    detail: str = ""
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CredentialRecord(BaseModel):
    """What is known about one provider's credential for one tenant.

    Holds no secret. `fingerprint` answers "is this the same key as before" and
    `hint` lets a person recognise their own; neither can reconstruct it.
    """

    model_config = ConfigDict(frozen=True)

    provider: str
    tenant_id: str
    reference: str
    kind: ConnectionKind = ConnectionKind.API_TOKEN
    enabled: bool = True
    fingerprint: str = ""
    hint: str = ""
    last_verification: Verification | None = None
    stored_at: datetime | None = None
    rotated_at: datetime | None = None

    @property
    def status(self) -> Status:
        """Derived, except the verified result, which cannot be."""
        if not self.enabled:
            return Status.DISABLED
        if not self.fingerprint:
            return Status.NOT_CONFIGURED
        if self.last_verification is None:
            # Stored but never tested. Not CONNECTED — that would claim
            # something nobody checked.
            return Status.PENDING_CREDENTIAL
        return self.last_verification.status

    def describe(self) -> dict:
        """Safe for an API response, a report, or a screen."""
        integration = BY_ID.get(self.provider)
        return {
            "provider": self.provider,
            "name": integration.name if integration else self.provider,
            "purpose": integration.purpose if integration else "",
            "status": self.status.value,
            "enabled": self.enabled,
            "configured": bool(self.fingerprint),
            "hint": self.hint,
            "fingerprint": self.fingerprint,
            "credential": integration.credential if integration else self.reference,
            "setup_url": integration.setup_url if integration else "",
            "blocks": list(integration.blocks) if integration else [],
            "last_checked": (self.last_verification.at.isoformat()
                             if self.last_verification else None),
            "detail": self.last_verification.detail if self.last_verification else "",
        }


def reference_for(provider: str, tenant: str) -> str:
    """The vault key. Tenant-scoped, so one tenant's key cannot address another's."""
    return f"{tenant}/{provider}"


class CredentialService:
    """Store, test, rotate and disable credentials. Never reveal them."""

    def __init__(self, vault: Vault, *, events: list | None = None,
                 sink: Callable[[BusinessEvent], None] | None = None) -> None:
        """The vault, and the timeline the records live on.

        Without `events` the records are in memory only — which is correct for a
        test and was quietly wrong for the deployment: the vault persisted the
        secret while the record vanished on restart, so a saved credential read
        back as NOT_CONFIGURED with its key still in the vault, unreachable and
        impossible to forget through the UI.
        """
        self._vault = vault
        self._sink = sink
        self._records: dict[str, CredentialRecord] = (
            restore(events) if events is not None else {})
        if self._records:
            log.info("credentials: restored %d record(s) from the timeline",
                     len(self._records))

    def _remember(self, record: CredentialRecord, kind: str, *,
                  actor: str = "operator") -> None:
        """Hold the record and append the event that will rebuild it.

        Both, always, in one place. Updating the dict without appending is how
        the state and its log disagree, and it is the shape of the bug this
        replaced.
        """
        self._records[record.reference] = record
        if self._sink is not None:
            self._sink(to_event(record, kind, actor=actor))

    # -- writing ----------------------------------------------------------

    def store(self, *, provider: str, tenant: TenantId | None, secret: str,
              kind: ConnectionKind = ConnectionKind.API_TOKEN
              ) -> CredentialRecord:
        """Put a credential in the vault and record that it exists.

        Deliberately does not mark it CONNECTED. Storing a key proves somebody
        typed one, not that it works; `verify` is a separate act.
        """
        tenant = _require_tenant(tenant, method="credentials.store")
        reference = reference_for(provider, str(tenant))
        self._vault.put(reference, secret)
        record = CredentialRecord(
            provider=provider, tenant_id=str(tenant), reference=reference,
            kind=kind, fingerprint=fingerprint(secret), hint=hint(secret),
            stored_at=datetime.now(UTC))
        self._remember(record, STORED)
        log.info("credential stored for %s/%s (%s)", tenant, provider,
                 record.fingerprint)
        return record

    def rotate(self, *, provider: str, tenant: TenantId | None, secret: str
               ) -> CredentialRecord:
        """Replace a credential. A rejected value never displaces a working one."""
        tenant = _require_tenant(tenant, method="credentials.rotate")
        reference = reference_for(provider, str(tenant))
        existing = self._records.get(reference)
        self._vault.rotate(reference, secret)
        record = CredentialRecord(
            provider=provider, tenant_id=str(tenant), reference=reference,
            kind=existing.kind if existing else ConnectionKind.API_TOKEN,
            enabled=existing.enabled if existing else True,
            fingerprint=fingerprint(secret), hint=hint(secret),
            stored_at=existing.stored_at if existing else datetime.now(UTC),
            # Verification does not survive a rotation: the old result was about
            # the old key, and carrying it forward would show a new, untested
            # credential as CONNECTED.
            last_verification=None,
            rotated_at=datetime.now(UTC))
        self._remember(record, ROTATED)
        return record

    def set_enabled(self, *, provider: str, tenant: TenantId | None,
                    enabled: bool) -> CredentialRecord:
        """Disable without deleting, so it can be turned back on."""
        record = self._require(provider, tenant)
        updated = record.model_copy(update={"enabled": enabled})
        self._remember(updated, DISABLED)
        return updated

    def forget(self, *, provider: str, tenant: TenantId | None) -> None:
        tenant = _require_tenant(tenant, method="credentials.forget")
        reference = reference_for(provider, str(tenant))
        gone = self._records.get(reference)
        self._vault.drop(reference)
        self._records.pop(reference, None)
        # Recorded, not merely deleted. A fold over a timeline that only ever
        # said "stored" would resurrect a credential the operator destroyed.
        if gone is not None and self._sink is not None:
            self._sink(to_event(gone, FORGOTTEN))

    # -- reading ----------------------------------------------------------

    def _require(self, provider: str, tenant: TenantId | None) -> CredentialRecord:
        tenant = _require_tenant(tenant, method="credentials.read")
        reference = reference_for(provider, str(tenant))
        record = self._records.get(reference)
        # Another tenant's record is absent, as everywhere else in the system.
        if record is None or not owns(record.tenant_id, tenant):
            raise CredentialMissing(f"no credential stored for {provider}")
        return record

    def record(self, *, provider: str, tenant: TenantId | None
               ) -> CredentialRecord | None:
        try:
            return self._require(provider, tenant)
        except CredentialMissing:
            return None

    def status(self, *, provider: str, tenant: TenantId | None) -> Status:
        record = self.record(provider=provider, tenant=tenant)
        return record.status if record else Status.NOT_CONFIGURED

    def resolve(self, *, provider: str, tenant: TenantId | None) -> str:
        """The secret, for one use. The only method that returns one.

        Refuses a disabled credential rather than letting a caller discover the
        state from a provider error, and never falls back to another tenant's.
        """
        record = self._require(provider, tenant)
        if not record.enabled:
            raise CredentialDisabled(
                f"the {provider} credential is disabled for this tenant")
        try:
            return self._vault.get(record.reference)
        except VaultError as failure:
            # The vault's message never carries key material; this does not add
            # any either.
            raise CredentialMissing(
                f"{provider}: the stored credential could not be read") from failure

    def connection(self, *, provider: str, tenant: TenantId | None) -> Connection:
        """The existing `Connection`, so publication and integrations are unchanged.

        This is the join: the rest of the system keeps using the reference model
        it already had, and the vault is simply what that reference now points
        at.
        """
        record = self._require(provider, tenant)
        return Connection(id=f"cred-{record.provider}", tenant_id=record.tenant_id,
                          target=record.provider, kind=record.kind,
                          reference=record.reference,
                          label=BY_ID[record.provider].name
                          if record.provider in BY_ID else record.provider)

    # -- verification -----------------------------------------------------

    def verify(self, *, provider: str, tenant: TenantId | None,
               probe: object) -> Verification:
        """Ask the provider whether the credential works, and record the answer.

        `probe` is supplied by the caller and returns `(Status, detail)`. Kept
        out of this module so testing verification does not require a network,
        and so a provider's own error text is translated to a status *before* it
        reaches here — a provider echoing a request could otherwise put the key
        into a detail string.
        """
        record = self._require(provider, tenant)
        if not record.enabled:
            result = Verification(status=Status.DISABLED,
                                  detail="the credential is disabled")
        else:
            try:
                secret = self.resolve(provider=provider, tenant=tenant)
                status, detail = probe(secret)            # type: ignore[operator]
                result = Verification(status=status, detail=_safe(detail, secret))
            except CredentialMissing:
                result = Verification(status=Status.NOT_CONFIGURED,
                                      detail="nothing is stored")
            except Exception as failure:          # noqa: BLE001 - reported
                result = Verification(status=Status.PROVIDER_ERROR,
                                      detail=type(failure).__name__)

        updated = record.model_copy(update={"last_verification": result})
        self._remember(updated, VERIFIED)
        return result

    # -- the centre -------------------------------------------------------

    def centre(self, *, tenant: TenantId | None) -> dict:
        """Every provider, whether configured or not, in one list.

        Includes providers with nothing stored, because "you have not connected
        Stripe" is the row a person needs and an empty list does not say it.
        """
        tenant = _require_tenant(tenant, method="credentials.centre")
        rows = []
        for integration in INTEGRATIONS:
            record = self.record(provider=integration.id, tenant=tenant)
            if record is not None:
                rows.append(record.describe())
                continue
            rows.append({
                "provider": integration.id, "name": integration.name,
                "purpose": integration.purpose,
                "status": Status.NOT_CONFIGURED.value,
                "enabled": True, "configured": False, "hint": "",
                "fingerprint": "", "credential": integration.credential,
                "setup_url": integration.setup_url,
                "blocks": list(integration.blocks),
                "last_checked": None, "detail": "",
            })
        return {
            "credentials": rows,
            "connected": [r for r in rows if r["status"] == Status.CONNECTED.value],
            "action_required": [r for r in rows
                                if r["status"] in {s.value for s in UNUSABLE}],
            "vault": {"sealed": self._vault.sealed,
                      "locked": self._vault.requires_pin and not self._vault.unlocked},
            "note": "No secret value appears in this response. A credential is "
                    "stored in the vault and referenced by name.",
        }


def _safe(detail: str, secret: str) -> str:
    """Never let a provider's echo of the request carry the key back out.

    Providers do echo. A 400 that quotes the offending header is a normal API
    response and an abnormal thing to store.
    """
    text = detail or ""
    if secret and secret in text:
        return text.replace(secret, "<redacted>")
    return text[:300]


def to_event(record: CredentialRecord, kind: str, *,
             actor: str = "operator") -> BusinessEvent:
    """A timeline entry for a credential change. Metadata only, by construction.

    There is no field on `CredentialRecord` holding a secret, so this cannot
    leak one — the same argument the publication record makes.

    **Lossless.** `restore()` folds these back into records, so anything the
    record needs has to be here. It was not, and the effect was that a saved
    credential reverted to NOT_CONFIGURED on the next restart while its secret
    sat in the vault, unreachable and unforgettable.
    """
    verified = record.last_verification
    return BusinessEvent(
        business_id="", factory=FACTORY, kind=kind, actor=actor,
        detail={"provider": record.provider, "tenant_id": record.tenant_id,
                "reference": record.reference, "kind": record.kind.value,
                "fingerprint": record.fingerprint, "hint": record.hint,
                "status": record.status.value, "enabled": record.enabled,
                "verified_status": verified.status.value if verified else "",
                "verified_detail": verified.detail if verified else "",
                "verified_at": verified.at.isoformat() if verified else "",
                "stored_at": (record.stored_at.isoformat()
                              if record.stored_at else ""),
                "rotated_at": (record.rotated_at.isoformat()
                               if record.rotated_at else ""),
                "at": datetime.now(UTC).isoformat()})


#: Kinds this module writes. A fold that matched on `factory` alone would also
#: swallow anything a later module namespaced the same way.
KINDS: frozenset[str] = frozenset({STORED, VERIFIED, ROTATED, DISABLED,
                                   FORGOTTEN})


def _moment(value: object) -> datetime | None:
    """An ISO string from a folded event back into a moment.

    The timeline is JSON, so every datetime arrives as text. Parsed in one place
    so a naive value cannot reach a comparison against an aware one.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def restore(events: list) -> dict[str, CredentialRecord]:
    """Every current credential record, folded from the timeline.

    Not tenant-scoped: this rebuilds one service's whole state at start-up, and
    the tenant check happens on every read afterwards in `_require`. Scoping
    here would silently give a restarted process one tenant's credentials.

    The **latest** event wins by its own timestamp rather than by position, for
    the same reason `mission.fold` does: a log that must be replayed in the
    order it was written is a log with a hidden ordering requirement.
    """
    latest: dict[str, dict] = {}
    for event in events:
        kind = getattr(event, "kind", None) or event.get("kind")
        if kind not in KINDS:
            continue
        detail = getattr(event, "detail", None) or event.get("detail") or {}
        reference = detail.get("reference") or ""
        if not reference:
            continue
        seen = latest.get(reference)
        if seen is None or detail.get("at", "") >= seen.get("at", ""):
            latest[reference] = {**dict(detail), "_kind": kind}

    records: dict[str, CredentialRecord] = {}
    for reference, detail in latest.items():
        if detail["_kind"] == FORGOTTEN:
            continue                      # destroyed; the timeline keeps why
        verified = None
        if detail.get("verified_status"):
            verified = Verification(
                status=Status(detail["verified_status"]),
                detail=detail.get("verified_detail", ""),
                at=_moment(detail.get("verified_at")) or datetime.now(UTC))
        records[reference] = CredentialRecord(
            provider=detail.get("provider", ""),
            tenant_id=detail.get("tenant_id", ""),
            reference=reference,
            kind=ConnectionKind(detail.get("kind")
                                or ConnectionKind.API_TOKEN.value),
            enabled=bool(detail.get("enabled", True)),
            fingerprint=detail.get("fingerprint", ""),
            hint=detail.get("hint", ""),
            last_verification=verified,
            stored_at=_moment(detail.get("stored_at")),
            rotated_at=_moment(detail.get("rotated_at")))
    return records


def read(events: list, *, tenant: TenantId | None = None) -> list[dict]:
    """TENANT_SCOPED. Credential history for one tenant, newest first.

    History, not state — `restore()` answers "what is configured now". This
    answers "what happened", which is the question an audit asks.
    """
    tenant = _require_tenant(tenant, method="credentials.read")
    found = []
    for event in events:
        kind = getattr(event, "kind", None) or event.get("kind")
        if kind not in KINDS:
            continue
        detail = getattr(event, "detail", None) or event.get("detail") or {}
        if not owns(detail.get("tenant_id"), tenant):
            continue
        found.append({**dict(detail), "kind": kind})
    return sorted(found, key=lambda d: d.get("at", ""), reverse=True)
