from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from .events import IdentityAuthenticated
from .models import Identity, IdentityProviderKind

if TYPE_CHECKING:
    from ..event_bus import EventBus
    from ..repository import AtlasRepository


class IdentityError(RuntimeError):
    pass


class AuthenticationProvider(ABC):
    """Abstract authentication seam.

    Milestone 010 deliberately implements **no** external identity flow. This
    interface exists so OIDC, LDAP, SAML, GitHub, Google and Microsoft can be
    added later without touching the organization, permission or audit layers.
    A provider's only job is to turn provider-specific credentials into a stable
    subject; everything downstream keys off that subject.
    """

    kind: IdentityProviderKind = IdentityProviderKind.LOCAL

    @abstractmethod
    def authenticate(self, credentials: dict[str, Any]) -> str:
        """Returns the provider subject, or raises IdentityError."""

    def describe(self) -> dict[str, Any]:
        return {"kind": self.kind.value, "implemented": True}


class LocalAuthenticationProvider(AuthenticationProvider):
    """Trusts a caller-supplied subject. Suitable for a single-operator desktop
    install; it performs no credential verification and is not a login system."""

    kind = IdentityProviderKind.LOCAL

    def authenticate(self, credentials: dict[str, Any]) -> str:
        subject = credentials.get("subject")
        if not isinstance(subject, str) or not subject.strip():
            raise IdentityError("Local authentication requires a subject")
        return subject.strip()


class UnimplementedAuthenticationProvider(AuthenticationProvider):
    """Registered placeholder for an enterprise provider.

    It is a declared seam, not a stub pretending to work: calling it raises
    rather than silently authenticating anyone.
    """

    def __init__(self, kind: IdentityProviderKind) -> None:
        self.kind = kind

    def authenticate(self, credentials: dict[str, Any]) -> str:
        raise IdentityError(f"{self.kind.value} authentication is not implemented in this build")

    def describe(self) -> dict[str, Any]:
        return {"kind": self.kind.value, "implemented": False}


class IdentityService:
    """Owns identities and the provider registry. Performs no authorisation —
    that is the PermissionEngine's job."""

    def __init__(self, repository: AtlasRepository, event_bus: EventBus) -> None:
        self.repository = repository
        self.event_bus = event_bus
        self._providers: dict[IdentityProviderKind, AuthenticationProvider] = {
            IdentityProviderKind.LOCAL: LocalAuthenticationProvider(),
        }
        for kind in IdentityProviderKind:
            if kind is not IdentityProviderKind.LOCAL:
                self._providers[kind] = UnimplementedAuthenticationProvider(kind)

    def register_provider(self, provider: AuthenticationProvider) -> None:
        self._providers[provider.kind] = provider

    def providers(self) -> list[dict[str, Any]]:
        return [self._providers[kind].describe() for kind in IdentityProviderKind]

    def create_identity(
        self,
        *,
        subject: str,
        display_name: str,
        email: str | None = None,
        provider: IdentityProviderKind = IdentityProviderKind.LOCAL,
        metadata: dict[str, Any] | None = None,
    ) -> Identity:
        existing = self.repository.get_identity_by_subject(subject)
        if existing is not None:
            return existing
        identity = Identity(
            subject=subject,
            display_name=display_name,
            email=email,
            provider=provider,
            metadata=metadata or {},
        )
        self.repository.upsert_identity(identity)
        return identity

    def get(self, identity_id: str) -> Identity | None:
        return self.repository.get_identity(identity_id)

    def list_identities(self) -> list[Identity]:
        return self.repository.list_identities()

    def authenticate(
        self, provider_kind: IdentityProviderKind, credentials: dict[str, Any]
    ) -> Identity:
        provider = self._providers.get(provider_kind)
        if provider is None:
            raise IdentityError(f"Unknown identity provider: {provider_kind}")

        subject = provider.authenticate(credentials)
        identity = self.repository.get_identity_by_subject(subject)
        if identity is None:
            raise IdentityError(f"No identity registered for subject: {subject}")
        if not identity.active:
            raise IdentityError(f"Identity is deactivated: {identity.id}")

        updated = identity.model_copy(update={"last_login_at": datetime.now(UTC)})
        self.repository.upsert_identity(updated)
        self.event_bus.publish(
            IdentityAuthenticated(identity_id=updated.id, provider=provider_kind.value)
        )
        return updated

    def deactivate(self, identity_id: str) -> Identity:
        identity = self.repository.get_identity(identity_id)
        if identity is None:
            raise IdentityError(f"Identity not found: {identity_id}")
        updated = identity.model_copy(update={"active": False})
        self.repository.upsert_identity(updated)
        return updated
