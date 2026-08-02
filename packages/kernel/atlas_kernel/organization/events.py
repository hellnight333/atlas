from __future__ import annotations

from dataclasses import dataclass

from ..event_types import AtlasEvent


@dataclass(frozen=True)
class OrganizationCreated(AtlasEvent):
    organization_id: str = ""
    name: str = ""
    tenant_id: str = ""


@dataclass(frozen=True)
class OrganizationUpdated(AtlasEvent):
    organization_id: str = ""


@dataclass(frozen=True)
class OrganizationArchived(AtlasEvent):
    organization_id: str = ""


@dataclass(frozen=True)
class TeamCreated(AtlasEvent):
    team_id: str = ""
    organization_id: str = ""
    name: str = ""


@dataclass(frozen=True)
class TeamUpdated(AtlasEvent):
    team_id: str = ""
    organization_id: str = ""


@dataclass(frozen=True)
class MemberAdded(AtlasEvent):
    membership_id: str = ""
    organization_id: str = ""
    identity_id: str = ""


@dataclass(frozen=True)
class MemberRemoved(AtlasEvent):
    membership_id: str = ""
    organization_id: str = ""
    identity_id: str = ""


@dataclass(frozen=True)
class MembershipChanged(AtlasEvent):
    membership_id: str = ""
    organization_id: str = ""
    identity_id: str = ""
    reason: str = ""


@dataclass(frozen=True)
class RoleCreated(AtlasEvent):
    role_id: str = ""
    name: str = ""
    organization_id: str | None = None


@dataclass(frozen=True)
class RoleUpdated(AtlasEvent):
    role_id: str = ""
    name: str = ""


@dataclass(frozen=True)
class PermissionsChanged(AtlasEvent):
    identity_id: str = ""
    organization_id: str = ""
    reason: str = ""


@dataclass(frozen=True)
class PolicySetUpdated(AtlasEvent):
    policy_set_id: str = ""
    organization_id: str = ""
    domain: str = ""
    scope: str = ""


@dataclass(frozen=True)
class PolicyViolationDetected(AtlasEvent):
    organization_id: str = ""
    domain: str = ""
    detail: str = ""


@dataclass(frozen=True)
class WorkerTransferred(AtlasEvent):
    worker_id: str = ""
    from_organization_id: str | None = None
    to_organization_id: str | None = None


@dataclass(frozen=True)
class AuditRecorded(AtlasEvent):
    audit_id: str = ""
    organization_id: str | None = None
    action: str = ""
    actor_id: str = ""


@dataclass(frozen=True)
class IdentityAuthenticated(AtlasEvent):
    identity_id: str = ""
    provider: str = ""
