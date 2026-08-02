from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class Permission(StrEnum):
    """Every capability the platform can grant. Roles are collections of these;
    the engine never branches on a role name."""

    PROJECT_READ = "Project.Read"
    PROJECT_WRITE = "Project.Write"
    PROJECT_DELETE = "Project.Delete"
    ASSET_PUBLISH = "Asset.Publish"
    WORKFLOW_EXECUTE = "Workflow.Execute"
    AUTOMATION_MANAGE = "Automation.Manage"
    WORKER_MANAGE = "Worker.Manage"
    APPROVAL_OVERRIDE = "Approval.Override"
    PLUGIN_INSTALL = "Plugin.Install"
    STUDIO_CONFIGURE = "Studio.Configure"
    GRAPH_VIEW = "Graph.View"
    ORGANIZATION_ADMIN = "Organization.Admin"
    AUDIT_VIEW = "Audit.View"
    POLICY_MANAGE = "Policy.Manage"
    MEMBER_MANAGE = "Member.Manage"


class BuiltinRole(StrEnum):
    OWNER = "owner"
    ADMINISTRATOR = "administrator"
    MANAGER = "manager"
    OPERATOR = "operator"
    CONTRIBUTOR = "contributor"
    REVIEWER = "reviewer"
    VIEWER = "viewer"


#: Built-in roles are seed *data*, not behaviour. They land in the same table as
#: custom roles and are resolved by exactly the same code path.
BUILTIN_ROLE_PERMISSIONS: dict[BuiltinRole, tuple[Permission, ...]] = {
    BuiltinRole.OWNER: tuple(Permission),
    BuiltinRole.ADMINISTRATOR: (
        Permission.PROJECT_READ,
        Permission.PROJECT_WRITE,
        Permission.PROJECT_DELETE,
        Permission.ASSET_PUBLISH,
        Permission.WORKFLOW_EXECUTE,
        Permission.AUTOMATION_MANAGE,
        Permission.WORKER_MANAGE,
        Permission.APPROVAL_OVERRIDE,
        Permission.PLUGIN_INSTALL,
        Permission.STUDIO_CONFIGURE,
        Permission.GRAPH_VIEW,
        Permission.AUDIT_VIEW,
        Permission.POLICY_MANAGE,
        Permission.MEMBER_MANAGE,
    ),
    BuiltinRole.MANAGER: (
        Permission.PROJECT_READ,
        Permission.PROJECT_WRITE,
        Permission.ASSET_PUBLISH,
        Permission.WORKFLOW_EXECUTE,
        Permission.AUTOMATION_MANAGE,
        Permission.GRAPH_VIEW,
        Permission.AUDIT_VIEW,
        Permission.MEMBER_MANAGE,
    ),
    BuiltinRole.OPERATOR: (
        Permission.PROJECT_READ,
        Permission.PROJECT_WRITE,
        Permission.WORKFLOW_EXECUTE,
        Permission.WORKER_MANAGE,
        Permission.GRAPH_VIEW,
    ),
    BuiltinRole.CONTRIBUTOR: (
        Permission.PROJECT_READ,
        Permission.PROJECT_WRITE,
        Permission.WORKFLOW_EXECUTE,
        Permission.GRAPH_VIEW,
    ),
    BuiltinRole.REVIEWER: (
        Permission.PROJECT_READ,
        Permission.ASSET_PUBLISH,
        Permission.GRAPH_VIEW,
    ),
    BuiltinRole.VIEWER: (
        Permission.PROJECT_READ,
        Permission.GRAPH_VIEW,
    ),
}


class Role(BaseModel):
    id: str = Field(default_factory=lambda: f"role-{uuid4().hex[:12]}")
    name: str
    description: str = ""
    permissions: list[Permission] = Field(default_factory=list)
    organization_id: str | None = None
    builtin: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TeamKind(StrEnum):
    ENGINEERING = "engineering"
    RESEARCH = "research"
    CREATIVE = "creative"
    OPERATIONS = "operations"
    MANAGEMENT = "management"
    CUSTOM = "custom"


class Team(BaseModel):
    id: str = Field(default_factory=lambda: f"team-{uuid4().hex[:12]}")
    organization_id: str
    name: str
    kind: TeamKind = TeamKind.CUSTOM
    description: str = ""
    project_ids: list[str] = Field(default_factory=list)
    studio_ids: list[str] = Field(default_factory=list)
    worker_ids: list[str] = Field(default_factory=list)
    automation_rule_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class IdentityProviderKind(StrEnum):
    """Interfaces only. Milestone 010 implements no external identity flow."""

    LOCAL = "local"
    OIDC = "oidc"
    LDAP = "ldap"
    SAML = "saml"
    GITHUB = "github"
    GOOGLE = "google"
    MICROSOFT = "microsoft"


class Identity(BaseModel):
    id: str = Field(default_factory=lambda: f"identity-{uuid4().hex[:12]}")
    subject: str
    display_name: str
    email: str | None = None
    provider: IdentityProviderKind = IdentityProviderKind.LOCAL
    provider_subject: str | None = None
    active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_login_at: datetime | None = None


class MembershipScope(StrEnum):
    ORGANIZATION = "organization"
    TEAM = "team"
    PROJECT = "project"


class Membership(BaseModel):
    id: str = Field(default_factory=lambda: f"membership-{uuid4().hex[:12]}")
    identity_id: str
    organization_id: str
    scope: MembershipScope = MembershipScope.ORGANIZATION
    scope_id: str | None = None
    role_ids: list[str] = Field(default_factory=list)
    team_ids: list[str] = Field(default_factory=list)
    active: bool = True
    expires_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def is_current(self, now: datetime | None = None) -> bool:
        if not self.active:
            return False
        if self.expires_at is None:
            return True
        return (now or datetime.now(UTC)) < self.expires_at


class PolicyScopeKind(StrEnum):
    ORGANIZATION = "organization"
    WORKSPACE = "workspace"
    PROJECT = "project"
    OBJECT = "object"


#: Narrowest scope last: inheritance walks this order and later wins.
POLICY_SCOPE_ORDER: tuple[PolicyScopeKind, ...] = (
    PolicyScopeKind.ORGANIZATION,
    PolicyScopeKind.WORKSPACE,
    PolicyScopeKind.PROJECT,
    PolicyScopeKind.OBJECT,
)


class PolicyDomain(StrEnum):
    APPROVAL = "approval"
    AUTOMATION = "automation"
    WORKERS = "workers"
    PLUGINS = "plugins"
    PROVIDERS = "providers"
    STORAGE = "storage"
    RETENTION = "retention"
    SHARING = "sharing"
    PUBLISHING = "publishing"
    SECURITY = "security"


class PolicySet(BaseModel):
    id: str = Field(default_factory=lambda: f"policyset-{uuid4().hex[:12]}")
    organization_id: str
    scope: PolicyScopeKind = PolicyScopeKind.ORGANIZATION
    scope_id: str | None = None
    domain: PolicyDomain
    settings: dict[str, Any] = Field(default_factory=dict)
    #: Settings named here may not be overridden by a narrower scope.
    locked_keys: list[str] = Field(default_factory=list)
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ResolvedPolicy(BaseModel):
    domain: PolicyDomain
    organization_id: str
    settings: dict[str, Any] = Field(default_factory=dict)
    #: Which policy set each setting came from, so the UI can show its source.
    sources: dict[str, str] = Field(default_factory=dict)
    locked_keys: list[str] = Field(default_factory=list)
    chain: list[str] = Field(default_factory=list)


class Branding(BaseModel):
    display_name: str | None = None
    logo_uri: str | None = None
    accent_color: str | None = None
    theme: str | None = None


class LicenseTier(StrEnum):
    INDIVIDUAL = "individual"
    TEAM = "team"
    COMPANY = "company"
    LAB = "lab"


class License(BaseModel):
    """Records entitlement only. Milestone 010 implements no billing."""

    tier: LicenseTier = LicenseTier.INDIVIDUAL
    seats: int = 1
    max_workers: int = 0
    features: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None


class Organization(BaseModel):
    id: str = Field(default_factory=lambda: f"org-{uuid4().hex[:12]}")
    name: str
    slug: str
    description: str = ""
    tenant_id: str = Field(default_factory=lambda: f"tenant-{uuid4().hex[:12]}")
    workspace_ids: list[str] = Field(default_factory=list)
    branding: Branding = Field(default_factory=Branding)
    license: License = Field(default_factory=License)
    #: Workers from other organizations may execute this org's work only when
    #: a policy explicitly allows it.
    allow_shared_pool: bool = True
    active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AuditAction(StrEnum):
    LOGIN = "login"
    PERMISSION_CHANGED = "permission_changed"
    POLICY_CHANGED = "policy_changed"
    AUTOMATION = "automation"
    APPROVAL = "approval"
    EXECUTION = "execution"
    WORKER_ASSIGNMENT = "worker_assignment"
    PUBLISHING = "publishing"
    DELETION = "deletion"
    EXPORT = "export"
    ORGANIZATION_CHANGED = "organization_changed"
    MEMBERSHIP_CHANGED = "membership_changed"
    ROLE_CHANGED = "role_changed"


class AuditRecord(BaseModel):
    """Append-only. The repository exposes no update or delete for these."""

    id: str = Field(default_factory=lambda: f"audit-{uuid4().hex[:16]}")
    organization_id: str | None = None
    actor_id: str = "system"
    actor_display: str = "system"
    action: AuditAction
    target_type: str = ""
    target_id: str | None = None
    summary: str = ""
    before: dict[str, Any] = Field(default_factory=dict)
    after: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PermissionGrant(BaseModel):
    """Why an identity holds a permission — the Inspector renders this."""

    permission: Permission
    granted: bool
    role_id: str | None = None
    role_name: str | None = None
    membership_id: str | None = None
    reason: str = ""


class PermissionSetResolution(BaseModel):
    identity_id: str
    organization_id: str
    permissions: list[Permission] = Field(default_factory=list)
    grants: list[PermissionGrant] = Field(default_factory=list)
    role_ids: list[str] = Field(default_factory=list)
    team_ids: list[str] = Field(default_factory=list)

    def allows(self, permission: Permission) -> bool:
        return permission in self.permissions
