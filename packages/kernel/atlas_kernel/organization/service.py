from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from .audit import AuditService
from .events import (
    MemberAdded,
    MemberRemoved,
    MembershipChanged,
    OrganizationArchived,
    OrganizationCreated,
    OrganizationUpdated,
    PermissionsChanged,
    PolicySetUpdated,
    RoleCreated,
    RoleUpdated,
    TeamCreated,
    TeamUpdated,
    WorkerTransferred,
)
from .models import (
    BUILTIN_ROLE_PERMISSIONS,
    AuditAction,
    Branding,
    BuiltinRole,
    License,
    Membership,
    MembershipScope,
    Organization,
    Permission,
    PermissionSetResolution,
    PolicyDomain,
    PolicyScopeKind,
    PolicySet,
    ResolvedPolicy,
    Role,
    Team,
    TeamKind,
)
from .permissions import PermissionEngine
from .policy_resolver import PolicyResolver

if TYPE_CHECKING:
    from ..event_bus import EventBus
    from ..repository import AtlasRepository


class OrganizationError(RuntimeError):
    pass


class PermissionDeniedError(OrganizationError):
    pass


class CrossOrganizationError(OrganizationError):
    """Raised when work would execute on another organization's worker."""


class OrganizationService:
    """Owns organizations, teams, roles, memberships and policy sets.

    Authorisation decisions are delegated to PermissionEngine and policy
    resolution to PolicyResolver, so this class never branches on a role name.
    """

    def __init__(
        self,
        repository: AtlasRepository,
        event_bus: EventBus,
        audit: AuditService,
        permission_engine: PermissionEngine | None = None,
        policy_resolver: PolicyResolver | None = None,
    ) -> None:
        self.repository = repository
        self.event_bus = event_bus
        self.audit = audit
        self.permissions = permission_engine or PermissionEngine()
        self.policies = policy_resolver or PolicyResolver()

    # ------------------------------------------------------------------
    # Organizations
    # ------------------------------------------------------------------

    def create_organization(
        self,
        *,
        name: str,
        slug: str | None = None,
        description: str = "",
        branding: Branding | None = None,
        license: License | None = None,
        actor_id: str = "system",
        seed_builtin_roles: bool = True,
    ) -> Organization:
        normalized = _slugify(slug or name)
        if self.repository.get_organization_by_slug(normalized) is not None:
            raise OrganizationError(f"Organization slug already in use: {normalized}")

        organization = Organization(
            name=name,
            slug=normalized,
            description=description,
            branding=branding or Branding(),
            license=license or License(),
        )
        self.repository.upsert_organization(organization)

        if seed_builtin_roles:
            self.seed_builtin_roles(organization.id)

        self.event_bus.publish(
            OrganizationCreated(
                organization_id=organization.id,
                name=organization.name,
                tenant_id=organization.tenant_id,
            )
        )
        self.audit.record(
            action=AuditAction.ORGANIZATION_CHANGED,
            actor_id=actor_id,
            organization_id=organization.id,
            target_type="organization",
            target_id=organization.id,
            summary=f"Organization '{name}' created",
            after={"name": name, "slug": normalized},
        )
        return organization

    def get_organization(self, organization_id: str) -> Organization | None:
        return self.repository.get_organization(organization_id)

    def list_organizations(self, identity_id: str | None = None) -> list[Organization]:
        organizations = self.repository.list_organizations()
        if identity_id is None:
            return organizations
        member_of = {
            membership.organization_id
            for membership in self.repository.list_memberships(identity_id=identity_id)
            if membership.is_current()
        }
        return [org for org in organizations if org.id in member_of]

    def update_organization(
        self, organization_id: str, changes: dict[str, Any], actor_id: str = "system"
    ) -> Organization:
        organization = self._require_organization(organization_id)
        before = organization.model_dump(mode="json")
        updated = organization.model_copy(update={**changes, "updated_at": datetime.now(UTC)})
        self.repository.upsert_organization(updated)
        self.event_bus.publish(OrganizationUpdated(organization_id=organization_id))
        self.audit.record(
            action=AuditAction.ORGANIZATION_CHANGED,
            actor_id=actor_id,
            organization_id=organization_id,
            target_type="organization",
            target_id=organization_id,
            summary="Organization updated",
            before=before,
            after=updated.model_dump(mode="json"),
        )
        return updated

    def archive_organization(self, organization_id: str, actor_id: str = "system") -> Organization:
        updated = self.update_organization(organization_id, {"active": False}, actor_id=actor_id)
        self.event_bus.publish(OrganizationArchived(organization_id=organization_id))
        return updated

    # ------------------------------------------------------------------
    # Roles
    # ------------------------------------------------------------------

    def seed_builtin_roles(self, organization_id: str) -> list[Role]:
        """Built-in roles are seed data in the same table as custom roles, so
        both resolve through exactly the same code path."""
        created: list[Role] = []
        for builtin, permissions in BUILTIN_ROLE_PERMISSIONS.items():
            role = Role(
                id=f"role-{organization_id}-{builtin.value}",
                name=builtin.value,
                description=f"Built-in {builtin.value} role",
                permissions=list(permissions),
                organization_id=organization_id,
                builtin=True,
            )
            self.repository.upsert_role(role)
            created.append(role)
        return created

    def create_role(
        self,
        *,
        name: str,
        permissions: list[Permission],
        organization_id: str | None = None,
        description: str = "",
        actor_id: str = "system",
    ) -> Role:
        role = Role(
            name=name,
            description=description,
            permissions=list(permissions),
            organization_id=organization_id,
            builtin=False,
        )
        self.repository.upsert_role(role)
        self.event_bus.publish(
            RoleCreated(role_id=role.id, name=role.name, organization_id=organization_id)
        )
        self.audit.record(
            action=AuditAction.ROLE_CHANGED,
            actor_id=actor_id,
            organization_id=organization_id,
            target_type="role",
            target_id=role.id,
            summary=f"Role '{name}' created",
            after={"permissions": [p.value for p in permissions]},
        )
        return role

    def update_role(
        self, role_id: str, permissions: list[Permission], actor_id: str = "system"
    ) -> Role:
        role = self._require_role(role_id)
        if role.builtin:
            raise OrganizationError(
                f"Built-in role '{role.name}' cannot be modified; create a custom role instead"
            )
        before = [p.value for p in role.permissions]
        updated = role.model_copy(
            update={"permissions": list(permissions), "updated_at": datetime.now(UTC)}
        )
        self.repository.upsert_role(updated)
        self.event_bus.publish(RoleUpdated(role_id=role_id, name=updated.name))
        self.audit.record(
            action=AuditAction.ROLE_CHANGED,
            actor_id=actor_id,
            organization_id=role.organization_id,
            target_type="role",
            target_id=role_id,
            summary=f"Role '{role.name}' permissions changed",
            before={"permissions": before},
            after={"permissions": [p.value for p in permissions]},
        )
        return updated

    def list_roles(self, organization_id: str | None = None) -> list[Role]:
        roles = self.repository.list_roles()
        if organization_id is None:
            return roles
        return [r for r in roles if r.organization_id in (None, organization_id)]

    def list_permissions(self) -> list[dict[str, str]]:
        return [
            {"permission": permission.value, "name": permission.name} for permission in Permission
        ]

    # ------------------------------------------------------------------
    # Teams
    # ------------------------------------------------------------------

    def create_team(
        self,
        *,
        organization_id: str,
        name: str,
        kind: TeamKind = TeamKind.CUSTOM,
        description: str = "",
        actor_id: str = "system",
    ) -> Team:
        self._require_organization(organization_id)
        team = Team(organization_id=organization_id, name=name, kind=kind, description=description)
        self.repository.upsert_team(team)
        self.event_bus.publish(
            TeamCreated(team_id=team.id, organization_id=organization_id, name=name)
        )
        self.audit.record(
            action=AuditAction.ORGANIZATION_CHANGED,
            actor_id=actor_id,
            organization_id=organization_id,
            target_type="team",
            target_id=team.id,
            summary=f"Team '{name}' created",
        )
        return team

    def update_team(self, team_id: str, changes: dict[str, Any], actor_id: str = "system") -> Team:
        team = self._require_team(team_id)
        updated = team.model_copy(update={**changes, "updated_at": datetime.now(UTC)})
        self.repository.upsert_team(updated)
        self.event_bus.publish(TeamUpdated(team_id=team_id, organization_id=team.organization_id))
        return updated

    def list_teams(self, organization_id: str | None = None) -> list[Team]:
        return self.repository.list_teams(organization_id=organization_id)

    # ------------------------------------------------------------------
    # Membership
    # ------------------------------------------------------------------

    def add_member(
        self,
        *,
        organization_id: str,
        identity_id: str,
        role_ids: list[str] | None = None,
        team_ids: list[str] | None = None,
        scope: MembershipScope = MembershipScope.ORGANIZATION,
        scope_id: str | None = None,
        expires_at: datetime | None = None,
        actor_id: str = "system",
    ) -> Membership:
        self._require_organization(organization_id)
        membership = Membership(
            identity_id=identity_id,
            organization_id=organization_id,
            scope=scope,
            scope_id=scope_id,
            role_ids=list(role_ids or []),
            team_ids=list(team_ids or []),
            expires_at=expires_at,
        )
        self.repository.upsert_membership(membership)
        self.event_bus.publish(
            MemberAdded(
                membership_id=membership.id,
                organization_id=organization_id,
                identity_id=identity_id,
            )
        )
        self.audit.record(
            action=AuditAction.MEMBERSHIP_CHANGED,
            actor_id=actor_id,
            organization_id=organization_id,
            target_type="membership",
            target_id=membership.id,
            summary=f"Identity {identity_id} added to organization",
            after={"role_ids": membership.role_ids, "scope": scope.value},
        )
        return membership

    def update_membership(
        self, membership_id: str, changes: dict[str, Any], actor_id: str = "system"
    ) -> Membership:
        membership = self._require_membership(membership_id)
        before = membership.model_dump(mode="json")
        updated = membership.model_copy(update={**changes, "updated_at": datetime.now(UTC)})
        self.repository.upsert_membership(updated)
        self.event_bus.publish(
            MembershipChanged(
                membership_id=membership_id,
                organization_id=membership.organization_id,
                identity_id=membership.identity_id,
                reason="membership updated",
            )
        )
        if "role_ids" in changes:
            self.event_bus.publish(
                PermissionsChanged(
                    identity_id=membership.identity_id,
                    organization_id=membership.organization_id,
                    reason="roles changed",
                )
            )
            self.audit.record(
                action=AuditAction.PERMISSION_CHANGED,
                actor_id=actor_id,
                organization_id=membership.organization_id,
                target_type="membership",
                target_id=membership_id,
                summary="Membership roles changed",
                before={"role_ids": before.get("role_ids", [])},
                after={"role_ids": updated.role_ids},
            )
        return updated

    def remove_member(
        self, organization_id: str, membership_id: str, actor_id: str = "system"
    ) -> None:
        membership = self._require_membership(membership_id)
        if membership.organization_id != organization_id:
            raise OrganizationError("Membership does not belong to this organization")
        self.repository.delete_membership(membership_id)
        self.event_bus.publish(
            MemberRemoved(
                membership_id=membership_id,
                organization_id=organization_id,
                identity_id=membership.identity_id,
            )
        )
        self.audit.record(
            action=AuditAction.MEMBERSHIP_CHANGED,
            actor_id=actor_id,
            organization_id=organization_id,
            target_type="membership",
            target_id=membership_id,
            summary=f"Identity {membership.identity_id} removed from organization",
            before=membership.model_dump(mode="json"),
        )

    def list_members(self, organization_id: str) -> list[Membership]:
        return self.repository.list_memberships(organization_id=organization_id)

    def list_memberships_for_identity(self, identity_id: str) -> list[Membership]:
        return self.repository.list_memberships(identity_id=identity_id)

    # ------------------------------------------------------------------
    # Permissions
    # ------------------------------------------------------------------

    def resolve_permissions(
        self,
        identity_id: str,
        organization_id: str,
        scope: MembershipScope | None = None,
        scope_id: str | None = None,
    ) -> PermissionSetResolution:
        return self.permissions.resolve(
            identity_id=identity_id,
            organization_id=organization_id,
            memberships=self.repository.list_memberships(organization_id=organization_id),
            roles=self.list_roles(organization_id),
            scope=scope,
            scope_id=scope_id,
        )

    def require_permission(
        self,
        permission: Permission,
        *,
        identity_id: str,
        organization_id: str,
        scope: MembershipScope | None = None,
        scope_id: str | None = None,
    ) -> None:
        resolution = self.resolve_permissions(
            identity_id, organization_id, scope=scope, scope_id=scope_id
        )
        if not resolution.allows(permission):
            raise PermissionDeniedError(
                f"{identity_id} lacks {permission.value} in {organization_id}"
            )

    # ------------------------------------------------------------------
    # Policies
    # ------------------------------------------------------------------

    def upsert_policy_set(self, policy_set: PolicySet, actor_id: str = "system") -> PolicySet:
        existing = self.repository.get_policy_set(policy_set.id)
        stored = policy_set.model_copy(update={"updated_at": datetime.now(UTC)})
        self.repository.upsert_policy_set(stored)
        self.event_bus.publish(
            PolicySetUpdated(
                policy_set_id=stored.id,
                organization_id=stored.organization_id,
                domain=stored.domain.value,
                scope=stored.scope.value,
            )
        )
        self.audit.record(
            action=AuditAction.POLICY_CHANGED,
            actor_id=actor_id,
            organization_id=stored.organization_id,
            target_type="policy_set",
            target_id=stored.id,
            summary=f"{stored.domain.value} policy updated at {stored.scope.value} scope",
            before=existing.model_dump(mode="json") if existing else {},
            after=stored.model_dump(mode="json"),
        )
        return stored

    def list_policy_sets(
        self, organization_id: str | None = None, domain: PolicyDomain | None = None
    ) -> list[PolicySet]:
        return self.repository.list_policy_sets(organization_id=organization_id, domain=domain)

    def resolve_policy(
        self,
        *,
        domain: PolicyDomain,
        organization_id: str,
        workspace_id: str | None = None,
        project_id: str | None = None,
        object_id: str | None = None,
    ) -> ResolvedPolicy:
        return self.policies.resolve(
            domain=domain,
            organization_id=organization_id,
            policy_sets=self.repository.list_policy_sets(organization_id=organization_id),
            workspace_id=workspace_id,
            project_id=project_id,
            object_id=object_id,
        )

    # ------------------------------------------------------------------
    # Worker ownership
    # ------------------------------------------------------------------

    def assign_worker(
        self,
        worker_id: str,
        organization_id: str | None,
        actor_id: str = "system",
    ) -> None:
        """A worker belongs to one organization, or to the shared pool when
        organization_id is None."""
        worker = self.repository.get_worker(worker_id)
        if worker is None:
            raise OrganizationError(f"Worker not found: {worker_id}")

        previous = worker.metadata.get("organization_id")
        metadata = {**worker.metadata, "organization_id": organization_id}
        self.repository.upsert_worker(worker.model_copy(update={"metadata": metadata}))

        self.event_bus.publish(
            WorkerTransferred(
                worker_id=worker_id,
                from_organization_id=previous if isinstance(previous, str) else None,
                to_organization_id=organization_id,
            )
        )
        self.audit.record(
            action=AuditAction.WORKER_ASSIGNMENT,
            actor_id=actor_id,
            organization_id=organization_id,
            target_type="worker",
            target_id=worker_id,
            summary=(
                f"Worker assigned to {organization_id}"
                if organization_id
                else "Worker moved to shared pool"
            ),
            before={"organization_id": previous},
            after={"organization_id": organization_id},
        )

    def worker_organization(self, worker_id: str) -> str | None:
        worker = self.repository.get_worker(worker_id)
        if worker is None:
            return None
        owner = worker.metadata.get("organization_id")
        return owner if isinstance(owner, str) else None

    def may_execute_on_worker(self, organization_id: str | None, worker_id: str) -> bool:
        """Cross-organization execution is forbidden unless the requesting
        organization permits the shared pool."""
        owner = self.worker_organization(worker_id)
        if owner is None:
            if organization_id is None:
                return True
            organization = self.repository.get_organization(organization_id)
            return organization.allow_shared_pool if organization else True
        return owner == organization_id

    def require_worker_access(self, organization_id: str | None, worker_id: str) -> None:
        if not self.may_execute_on_worker(organization_id, worker_id):
            raise CrossOrganizationError(
                f"Organization {organization_id} may not execute on worker {worker_id}"
            )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _require_organization(self, organization_id: str) -> Organization:
        organization = self.repository.get_organization(organization_id)
        if organization is None:
            raise OrganizationError(f"Organization not found: {organization_id}")
        return organization

    def _require_role(self, role_id: str) -> Role:
        role = self.repository.get_role(role_id)
        if role is None:
            raise OrganizationError(f"Role not found: {role_id}")
        return role

    def _require_team(self, team_id: str) -> Team:
        team = self.repository.get_team(team_id)
        if team is None:
            raise OrganizationError(f"Team not found: {team_id}")
        return team

    def _require_membership(self, membership_id: str) -> Membership:
        membership = self.repository.get_membership(membership_id)
        if membership is None:
            raise OrganizationError(f"Membership not found: {membership_id}")
        return membership

    def builtin_role_id(self, organization_id: str, role: BuiltinRole) -> str:
        return f"role-{organization_id}-{role.value}"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    if not slug:
        raise OrganizationError("Organization name must contain alphanumeric characters")
    return slug


__all__ = [
    "CrossOrganizationError",
    "OrganizationError",
    "OrganizationService",
    "PermissionDeniedError",
    "PolicyScopeKind",
]
