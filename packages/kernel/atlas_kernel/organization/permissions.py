from __future__ import annotations

from datetime import UTC, datetime

from .models import (
    Membership,
    MembershipScope,
    Permission,
    PermissionGrant,
    PermissionSetResolution,
    Role,
)


class PermissionEngine:
    """Resolves what an identity may do.

    The engine holds no rule of its own. It never asks "is this user an admin";
    it unions the permissions of whatever roles the identity's live memberships
    reference. Adding a role, or changing what a role grants, never means
    editing this class.
    """

    def resolve(
        self,
        *,
        identity_id: str,
        organization_id: str,
        memberships: list[Membership],
        roles: list[Role],
        scope: MembershipScope | None = None,
        scope_id: str | None = None,
        now: datetime | None = None,
    ) -> PermissionSetResolution:
        now = now or datetime.now(UTC)
        roles_by_id = {role.id: role for role in roles}

        applicable = [
            membership
            for membership in memberships
            if membership.identity_id == identity_id
            and membership.organization_id == organization_id
            and membership.is_current(now)
            and self._scope_applies(membership, scope, scope_id)
        ]

        granted: dict[Permission, PermissionGrant] = {}
        role_ids: list[str] = []
        team_ids: list[str] = []

        for membership in applicable:
            for team_id in membership.team_ids:
                if team_id not in team_ids:
                    team_ids.append(team_id)

            for role_id in membership.role_ids:
                role = roles_by_id.get(role_id)
                if role is None:
                    continue
                if role.organization_id not in (None, organization_id):
                    continue
                if role_id not in role_ids:
                    role_ids.append(role_id)

                for permission in role.permissions:
                    if permission in granted:
                        continue
                    granted[permission] = PermissionGrant(
                        permission=permission,
                        granted=True,
                        role_id=role.id,
                        role_name=role.name,
                        membership_id=membership.id,
                        reason=f"granted by role '{role.name}'",
                    )

        ordered = [p for p in Permission if p in granted]
        return PermissionSetResolution(
            identity_id=identity_id,
            organization_id=organization_id,
            permissions=ordered,
            grants=[granted[p] for p in ordered],
            role_ids=role_ids,
            team_ids=team_ids,
        )

    def allows(
        self,
        permission: Permission,
        *,
        identity_id: str,
        organization_id: str,
        memberships: list[Membership],
        roles: list[Role],
        scope: MembershipScope | None = None,
        scope_id: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        return self.resolve(
            identity_id=identity_id,
            organization_id=organization_id,
            memberships=memberships,
            roles=roles,
            scope=scope,
            scope_id=scope_id,
            now=now,
        ).allows(permission)

    def explain(
        self,
        permission: Permission,
        resolution: PermissionSetResolution,
    ) -> PermissionGrant:
        """Why the answer is what it is — the Inspector renders this verbatim."""
        for grant in resolution.grants:
            if grant.permission is permission:
                return grant
        return PermissionGrant(
            permission=permission,
            granted=False,
            reason="no role held by this identity grants this permission",
        )

    def _scope_applies(
        self,
        membership: Membership,
        scope: MembershipScope | None,
        scope_id: str | None,
    ) -> bool:
        """Organization-wide membership applies everywhere; a narrower
        membership applies only within its own scope."""
        if membership.scope is MembershipScope.ORGANIZATION:
            return True
        if scope is None:
            return True
        if membership.scope is not scope:
            return False
        return scope_id is None or membership.scope_id == scope_id
