from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from atlas_kernel.api import app, repository, runtime
from atlas_kernel.organization.events import (
    AuditRecorded,
    MemberAdded,
    OrganizationCreated,
    PermissionsChanged,
    WorkerTransferred,
)
from atlas_kernel.organization.identity import (
    IdentityError,
    LocalAuthenticationProvider,
    UnimplementedAuthenticationProvider,
)
from atlas_kernel.organization.models import (
    AuditAction,
    BuiltinRole,
    IdentityProviderKind,
    Membership,
    MembershipScope,
    Permission,
    PolicyDomain,
    PolicyScopeKind,
    PolicySet,
    Role,
)
from atlas_kernel.organization.permissions import PermissionEngine
from atlas_kernel.organization.policy_resolver import PolicyResolver
from atlas_kernel.organization.service import (
    CrossOrganizationError,
    OrganizationError,
    PermissionDeniedError,
)

client = TestClient(app)

KERNEL_ROOT = Path(__file__).resolve().parents[1] / "atlas_kernel"

orgs = runtime.organization_service
identities = runtime.identity_service
audit = runtime.audit_service


def _unique(prefix: str) -> str:
    """The test database persists across runs, so ids must never be fixed."""
    return f"{prefix}-{uuid4().hex[:8]}"


def _org(name: str | None = None):
    return orgs.create_organization(name=name or _unique("Org"))


def _identity(subject: str | None = None):
    subject = subject or _unique("subject")
    return identities.create_identity(subject=subject, display_name=subject)


def _role_id(organization_id: str, builtin: BuiltinRole) -> str:
    return orgs.builtin_role_id(organization_id, builtin)


# ---------------------------------------------------------------------------
# Organization CRUD
# ---------------------------------------------------------------------------


def test_create_organization_seeds_builtin_roles() -> None:
    # Name must be unique: the slug is unique-constrained and the test database
    # persists across runs.
    organization = _org(_unique("Acme Labs"))

    assert organization.slug == organization.slug.lower()
    assert organization.tenant_id
    assert organization.active is True

    roles = orgs.list_roles(organization.id)
    names = {r.name for r in roles if r.builtin}
    assert names == {r.value for r in BuiltinRole}


def test_organization_slug_is_unique() -> None:
    name = _unique("Duplicate")
    orgs.create_organization(name=name)
    with pytest.raises(OrganizationError, match="slug already in use"):
        orgs.create_organization(name=name)


def test_organization_name_must_be_meaningful() -> None:
    with pytest.raises(OrganizationError, match="alphanumeric"):
        orgs.create_organization(name="   ---   ")


def test_update_and_archive_organization() -> None:
    organization = _org()
    updated = orgs.update_organization(organization.id, {"description": "changed"})
    assert updated.description == "changed"

    archived = orgs.archive_organization(organization.id)
    assert archived.active is False


def test_organizations_are_listed_per_identity() -> None:
    identity = _identity()
    mine = _org()
    other = _org()
    orgs.add_member(organization_id=mine.id, identity_id=identity.id)

    visible = {o.id for o in orgs.list_organizations(identity_id=identity.id)}
    assert mine.id in visible
    assert other.id not in visible


def test_organization_creation_emits_event() -> None:
    from atlas_kernel.api import event_bus

    seen: list[OrganizationCreated] = []
    event_bus.subscribe(OrganizationCreated, seen.append)
    organization = _org()
    assert organization.id in {e.organization_id for e in seen}


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------


def test_create_team_and_list() -> None:
    from atlas_kernel.organization.models import TeamKind

    organization = _org()
    team = orgs.create_team(
        organization_id=organization.id, name="Engineering", kind=TeamKind.ENGINEERING
    )

    assert team.organization_id == organization.id
    assert team.kind is TeamKind.ENGINEERING
    assert team.id in {t.id for t in orgs.list_teams(organization.id)}


def test_team_requires_existing_organization() -> None:
    with pytest.raises(OrganizationError, match="Organization not found"):
        orgs.create_team(organization_id="org-nope", name="Ghost")


def test_team_can_own_projects_and_workers() -> None:
    organization = _org()
    team = orgs.create_team(organization_id=organization.id, name="Ops")
    updated = orgs.update_team(
        team.id, {"project_ids": ["p1"], "worker_ids": ["w1"], "studio_ids": ["s1"]}
    )
    assert updated.project_ids == ["p1"]
    assert updated.worker_ids == ["w1"]
    assert updated.studio_ids == ["s1"]


# ---------------------------------------------------------------------------
# Membership
# ---------------------------------------------------------------------------


def test_add_and_remove_member() -> None:
    organization = _org()
    identity = _identity()

    membership = orgs.add_member(
        organization_id=organization.id,
        identity_id=identity.id,
        role_ids=[_role_id(organization.id, BuiltinRole.VIEWER)],
    )
    assert membership.id in {m.id for m in orgs.list_members(organization.id)}

    orgs.remove_member(organization.id, membership.id)
    assert membership.id not in {m.id for m in orgs.list_members(organization.id)}


def test_membership_cannot_be_removed_from_another_organization() -> None:
    first = _org()
    second = _org()
    identity = _identity()
    membership = orgs.add_member(organization_id=first.id, identity_id=identity.id)

    with pytest.raises(OrganizationError, match="does not belong"):
        orgs.remove_member(second.id, membership.id)


def test_identity_may_belong_to_multiple_organizations() -> None:
    identity = _identity()
    first = _org()
    second = _org()
    orgs.add_member(organization_id=first.id, identity_id=identity.id)
    orgs.add_member(organization_id=second.id, identity_id=identity.id)

    org_ids = {m.organization_id for m in orgs.list_memberships_for_identity(identity.id)}
    assert {first.id, second.id} <= org_ids


def test_temporary_access_expires() -> None:
    organization = _org()
    identity = _identity()
    orgs.add_member(
        organization_id=organization.id,
        identity_id=identity.id,
        role_ids=[_role_id(organization.id, BuiltinRole.ADMINISTRATOR)],
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    resolution = orgs.resolve_permissions(identity.id, organization.id)
    assert resolution.permissions == [], "expired membership must grant nothing"


def test_inactive_membership_grants_nothing() -> None:
    organization = _org()
    identity = _identity()
    membership = orgs.add_member(
        organization_id=organization.id,
        identity_id=identity.id,
        role_ids=[_role_id(organization.id, BuiltinRole.OWNER)],
    )
    orgs.update_membership(membership.id, {"active": False})

    assert orgs.resolve_permissions(identity.id, organization.id).permissions == []


def test_member_added_emits_event() -> None:
    from atlas_kernel.api import event_bus

    seen: list[MemberAdded] = []
    event_bus.subscribe(MemberAdded, seen.append)

    organization = _org()
    identity = _identity()
    membership = orgs.add_member(organization_id=organization.id, identity_id=identity.id)
    assert membership.id in {e.membership_id for e in seen}


# ---------------------------------------------------------------------------
# Roles and permission resolution
# ---------------------------------------------------------------------------


def test_builtin_role_permissions_resolve() -> None:
    organization = _org()
    identity = _identity()
    orgs.add_member(
        organization_id=organization.id,
        identity_id=identity.id,
        role_ids=[_role_id(organization.id, BuiltinRole.VIEWER)],
    )

    resolution = orgs.resolve_permissions(identity.id, organization.id)
    assert resolution.allows(Permission.PROJECT_READ)
    assert resolution.allows(Permission.GRAPH_VIEW)
    assert not resolution.allows(Permission.PROJECT_DELETE)
    assert not resolution.allows(Permission.ORGANIZATION_ADMIN)


def test_owner_holds_every_permission() -> None:
    organization = _org()
    identity = _identity()
    orgs.add_member(
        organization_id=organization.id,
        identity_id=identity.id,
        role_ids=[_role_id(organization.id, BuiltinRole.OWNER)],
    )

    resolution = orgs.resolve_permissions(identity.id, organization.id)
    assert set(resolution.permissions) == set(Permission)


def test_multiple_roles_union_their_permissions() -> None:
    organization = _org()
    identity = _identity()
    orgs.add_member(
        organization_id=organization.id,
        identity_id=identity.id,
        role_ids=[
            _role_id(organization.id, BuiltinRole.VIEWER),
            _role_id(organization.id, BuiltinRole.REVIEWER),
        ],
    )

    resolution = orgs.resolve_permissions(identity.id, organization.id)
    assert resolution.allows(Permission.PROJECT_READ)
    assert resolution.allows(Permission.ASSET_PUBLISH)


def test_custom_role_resolves_identically_to_builtin() -> None:
    organization = _org()
    identity = _identity()
    custom = orgs.create_role(
        name="Publisher",
        permissions=[Permission.ASSET_PUBLISH, Permission.PROJECT_READ],
        organization_id=organization.id,
    )
    orgs.add_member(
        organization_id=organization.id, identity_id=identity.id, role_ids=[custom.id]
    )

    resolution = orgs.resolve_permissions(identity.id, organization.id)
    assert resolution.allows(Permission.ASSET_PUBLISH)
    assert not resolution.allows(Permission.WORKER_MANAGE)


def test_roles_do_not_leak_across_organizations() -> None:
    first = _org()
    second = _org()
    identity = _identity()
    foreign_role = orgs.create_role(
        name="Foreign", permissions=[Permission.ORGANIZATION_ADMIN], organization_id=second.id
    )
    orgs.add_member(
        organization_id=first.id, identity_id=identity.id, role_ids=[foreign_role.id]
    )

    resolution = orgs.resolve_permissions(identity.id, first.id)
    assert not resolution.allows(Permission.ORGANIZATION_ADMIN)


def test_builtin_roles_cannot_be_modified() -> None:
    organization = _org()
    with pytest.raises(OrganizationError, match="cannot be modified"):
        orgs.update_role(
            _role_id(organization.id, BuiltinRole.VIEWER), [Permission.ORGANIZATION_ADMIN]
        )


def test_custom_role_update_changes_resolution() -> None:
    organization = _org()
    identity = _identity()
    custom = orgs.create_role(
        name="Grower", permissions=[Permission.PROJECT_READ], organization_id=organization.id
    )
    orgs.add_member(
        organization_id=organization.id, identity_id=identity.id, role_ids=[custom.id]
    )
    assert not orgs.resolve_permissions(identity.id, organization.id).allows(
        Permission.PROJECT_WRITE
    )

    orgs.update_role(custom.id, [Permission.PROJECT_READ, Permission.PROJECT_WRITE])
    assert orgs.resolve_permissions(identity.id, organization.id).allows(
        Permission.PROJECT_WRITE
    )


def test_require_permission_raises_when_denied() -> None:
    organization = _org()
    identity = _identity()
    orgs.add_member(
        organization_id=organization.id,
        identity_id=identity.id,
        role_ids=[_role_id(organization.id, BuiltinRole.VIEWER)],
    )

    orgs.require_permission(
        Permission.PROJECT_READ, identity_id=identity.id, organization_id=organization.id
    )
    with pytest.raises(PermissionDeniedError):
        orgs.require_permission(
            Permission.PROJECT_DELETE,
            identity_id=identity.id,
            organization_id=organization.id,
        )


def test_permission_grant_explains_its_source() -> None:
    organization = _org()
    identity = _identity()
    orgs.add_member(
        organization_id=organization.id,
        identity_id=identity.id,
        role_ids=[_role_id(organization.id, BuiltinRole.REVIEWER)],
    )
    resolution = orgs.resolve_permissions(identity.id, organization.id)

    engine = PermissionEngine()
    granted = engine.explain(Permission.ASSET_PUBLISH, resolution)
    assert granted.granted is True
    assert granted.role_name == "reviewer"

    denied = engine.explain(Permission.ORGANIZATION_ADMIN, resolution)
    assert denied.granted is False
    assert "no role" in denied.reason


def test_project_scoped_membership_only_applies_in_scope() -> None:
    engine = PermissionEngine()
    role = Role(id="r1", name="writer", permissions=[Permission.PROJECT_WRITE])
    membership = Membership(
        id="m1",
        identity_id="i1",
        organization_id="o1",
        scope=MembershipScope.PROJECT,
        scope_id="project-a",
        role_ids=["r1"],
    )

    in_scope = engine.resolve(
        identity_id="i1",
        organization_id="o1",
        memberships=[membership],
        roles=[role],
        scope=MembershipScope.PROJECT,
        scope_id="project-a",
    )
    out_of_scope = engine.resolve(
        identity_id="i1",
        organization_id="o1",
        memberships=[membership],
        roles=[role],
        scope=MembershipScope.PROJECT,
        scope_id="project-b",
    )

    assert in_scope.allows(Permission.PROJECT_WRITE)
    assert not out_of_scope.allows(Permission.PROJECT_WRITE)


def test_permission_engine_has_no_hardcoded_role_names() -> None:
    """Permissions must come from role data, never from a role-name branch."""
    source = (KERNEL_ROOT / "organization" / "permissions.py").read_text(encoding="utf-8")
    for builtin in BuiltinRole:
        assert f'"{builtin.value}"' not in source
        assert f"'{builtin.value}'" not in source


def test_role_change_emits_permissions_changed() -> None:
    from atlas_kernel.api import event_bus

    seen: list[PermissionsChanged] = []
    event_bus.subscribe(PermissionsChanged, seen.append)

    organization = _org()
    identity = _identity()
    membership = orgs.add_member(organization_id=organization.id, identity_id=identity.id)
    orgs.update_membership(
        membership.id, {"role_ids": [_role_id(organization.id, BuiltinRole.MANAGER)]}
    )

    assert identity.id in {e.identity_id for e in seen}


# ---------------------------------------------------------------------------
# Policy inheritance
# ---------------------------------------------------------------------------


def test_policy_inherits_from_organization_down_to_project() -> None:
    organization = _org()
    orgs.upsert_policy_set(
        PolicySet(
            organization_id=organization.id,
            scope=PolicyScopeKind.ORGANIZATION,
            domain=PolicyDomain.PUBLISHING,
            settings={"require_review": True, "watermark": True},
        )
    )
    orgs.upsert_policy_set(
        PolicySet(
            organization_id=organization.id,
            scope=PolicyScopeKind.PROJECT,
            scope_id="project-x",
            domain=PolicyDomain.PUBLISHING,
            settings={"watermark": False},
        )
    )

    resolved = orgs.resolve_policy(
        domain=PolicyDomain.PUBLISHING,
        organization_id=organization.id,
        project_id="project-x",
    )
    assert resolved.settings["require_review"] is True, "inherited from organization"
    assert resolved.settings["watermark"] is False, "overridden at project scope"


def test_locked_keys_cannot_be_overridden_downward() -> None:
    organization = _org()
    orgs.upsert_policy_set(
        PolicySet(
            organization_id=organization.id,
            scope=PolicyScopeKind.ORGANIZATION,
            domain=PolicyDomain.SECURITY,
            settings={"require_mfa": True},
            locked_keys=["require_mfa"],
        )
    )
    orgs.upsert_policy_set(
        PolicySet(
            organization_id=organization.id,
            scope=PolicyScopeKind.PROJECT,
            scope_id="project-y",
            domain=PolicyDomain.SECURITY,
            settings={"require_mfa": False},
        )
    )

    resolved = orgs.resolve_policy(
        domain=PolicyDomain.SECURITY,
        organization_id=organization.id,
        project_id="project-y",
    )
    assert resolved.settings["require_mfa"] is True, "a locked key must survive a narrower scope"
    assert "require_mfa" in resolved.locked_keys


def test_policy_resolution_records_its_source() -> None:
    organization = _org()
    org_policy = orgs.upsert_policy_set(
        PolicySet(
            organization_id=organization.id,
            scope=PolicyScopeKind.ORGANIZATION,
            domain=PolicyDomain.RETENTION,
            settings={"days": 30},
        )
    )
    resolved = orgs.resolve_policy(
        domain=PolicyDomain.RETENTION, organization_id=organization.id
    )
    assert resolved.sources["days"] == org_policy.id
    assert org_policy.id in resolved.chain


def test_workspace_scope_sits_between_organization_and_project() -> None:
    resolver = PolicyResolver()
    org_id = "org-1"
    sets = [
        PolicySet(
            id="ps-org",
            organization_id=org_id,
            scope=PolicyScopeKind.ORGANIZATION,
            domain=PolicyDomain.STORAGE,
            settings={"tier": "cold", "quota": 10},
        ),
        PolicySet(
            id="ps-ws",
            organization_id=org_id,
            scope=PolicyScopeKind.WORKSPACE,
            scope_id="ws-1",
            domain=PolicyDomain.STORAGE,
            settings={"tier": "warm"},
        ),
        PolicySet(
            id="ps-obj",
            organization_id=org_id,
            scope=PolicyScopeKind.OBJECT,
            scope_id="asset-1",
            domain=PolicyDomain.STORAGE,
            settings={"tier": "hot"},
        ),
    ]

    at_workspace = resolver.resolve(
        domain=PolicyDomain.STORAGE, organization_id=org_id, policy_sets=sets, workspace_id="ws-1"
    )
    assert at_workspace.settings["tier"] == "warm"
    assert at_workspace.settings["quota"] == 10

    at_object = resolver.resolve(
        domain=PolicyDomain.STORAGE,
        organization_id=org_id,
        policy_sets=sets,
        workspace_id="ws-1",
        object_id="asset-1",
    )
    assert at_object.settings["tier"] == "hot", "narrowest scope wins"


def test_disabled_policy_set_is_ignored() -> None:
    organization = _org()
    orgs.upsert_policy_set(
        PolicySet(
            organization_id=organization.id,
            scope=PolicyScopeKind.ORGANIZATION,
            domain=PolicyDomain.SHARING,
            settings={"external": True},
            enabled=False,
        )
    )
    resolved = orgs.resolve_policy(
        domain=PolicyDomain.SHARING, organization_id=organization.id
    )
    assert resolved.settings == {}


def test_policies_do_not_leak_across_organizations() -> None:
    first = _org()
    second = _org()
    orgs.upsert_policy_set(
        PolicySet(
            organization_id=second.id,
            scope=PolicyScopeKind.ORGANIZATION,
            domain=PolicyDomain.PROVIDERS,
            settings={"allow_cloud": True},
        )
    )
    resolved = orgs.resolve_policy(
        domain=PolicyDomain.PROVIDERS, organization_id=first.id
    )
    assert resolved.settings == {}


# ---------------------------------------------------------------------------
# Audit immutability
# ---------------------------------------------------------------------------


def test_audit_records_are_written_for_governance_changes() -> None:
    organization = _org()
    identity = _identity()
    orgs.add_member(organization_id=organization.id, identity_id=identity.id, actor_id="ayoub")

    records = audit.list_records(organization_id=organization.id)
    actions = {r.action for r in records}
    assert AuditAction.ORGANIZATION_CHANGED in actions
    assert AuditAction.MEMBERSHIP_CHANGED in actions
    assert any(r.actor_id == "ayoub" for r in records)


def test_audit_has_no_update_or_delete_path() -> None:
    assert not hasattr(repository, "update_audit_record")
    assert not hasattr(repository, "delete_audit_record")
    assert not hasattr(repository, "delete_audit_records")
    assert not hasattr(audit, "update")
    assert not hasattr(audit, "delete")


def test_audit_service_source_contains_no_mutation() -> None:
    source = (KERNEL_ROOT / "organization" / "audit.py").read_text(encoding="utf-8")
    assert "UPDATE atlas_audit" not in source
    assert "DELETE FROM atlas_audit" not in source

    repo_source = (KERNEL_ROOT / "repository.py").read_text(encoding="utf-8")
    assert "UPDATE atlas_audit_records" not in repo_source
    assert "DELETE FROM atlas_audit_records" not in repo_source


def test_rewriting_an_audit_record_is_a_no_op() -> None:
    """create uses ON CONFLICT DO NOTHING, so a replay cannot overwrite history."""
    organization = _org()
    record = audit.record(
        action=AuditAction.EXPORT,
        organization_id=organization.id,
        actor_id="ayoub",
        summary="original",
    )
    tampered = record.model_copy(update={"summary": "rewritten"})
    repository.create_audit_record(tampered)

    stored = audit.get(record.id)
    assert stored is not None
    assert stored.summary == "original"


def test_audit_captures_before_and_after() -> None:
    organization = _org()
    custom = orgs.create_role(
        name="Auditable", permissions=[Permission.PROJECT_READ], organization_id=organization.id
    )
    orgs.update_role(custom.id, [Permission.PROJECT_READ, Permission.PROJECT_WRITE])

    records = audit.list_records(organization_id=organization.id, action=AuditAction.ROLE_CHANGED)
    changed = next(r for r in records if r.target_id == custom.id and r.before)
    assert changed.before["permissions"] == ["Project.Read"]
    assert "Project.Write" in changed.after["permissions"]


def test_audit_record_emits_event() -> None:
    from atlas_kernel.api import event_bus

    seen: list[AuditRecorded] = []
    event_bus.subscribe(AuditRecorded, seen.append)
    record = audit.record(action=AuditAction.LOGIN, actor_id="ayoub", summary="login")
    assert record.id in {e.audit_id for e in seen}


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def test_local_provider_authenticates_a_known_subject() -> None:
    identity = _identity()
    authenticated = identities.authenticate(
        IdentityProviderKind.LOCAL, {"subject": identity.subject}
    )
    assert authenticated.id == identity.id
    assert authenticated.last_login_at is not None


def test_local_provider_requires_a_subject() -> None:
    with pytest.raises(IdentityError, match="requires a subject"):
        LocalAuthenticationProvider().authenticate({})


def test_enterprise_providers_are_declared_but_not_implemented() -> None:
    """Interfaces only: a placeholder must refuse rather than silently pass."""
    for kind in (
        IdentityProviderKind.OIDC,
        IdentityProviderKind.LDAP,
        IdentityProviderKind.SAML,
        IdentityProviderKind.GITHUB,
        IdentityProviderKind.GOOGLE,
        IdentityProviderKind.MICROSOFT,
    ):
        with pytest.raises(IdentityError, match="not implemented"):
            UnimplementedAuthenticationProvider(kind).authenticate({"subject": "x"})

    described = {p["kind"]: p["implemented"] for p in identities.providers()}
    assert described["local"] is True
    assert described["oidc"] is False


def test_deactivated_identity_cannot_authenticate() -> None:
    identity = _identity()
    identities.deactivate(identity.id)
    with pytest.raises(IdentityError, match="deactivated"):
        identities.authenticate(IdentityProviderKind.LOCAL, {"subject": identity.subject})


def test_unknown_subject_is_rejected() -> None:
    with pytest.raises(IdentityError, match="No identity registered"):
        identities.authenticate(IdentityProviderKind.LOCAL, {"subject": _unique("ghost")})


# ---------------------------------------------------------------------------
# Worker ownership
# ---------------------------------------------------------------------------


def _register_worker(name: str) -> str:
    from atlas_kernel.cluster.models import WorkerRegistration

    worker = runtime.worker_registry.register(
        WorkerRegistration(hostname=name, display_name=name, capabilities=["image"])
    )
    return worker.id


def test_worker_assignment_and_ownership() -> None:
    organization = _org()
    worker_id = _register_worker(_unique("owned"))

    orgs.assign_worker(worker_id, organization.id)
    assert orgs.worker_organization(worker_id) == organization.id
    assert orgs.may_execute_on_worker(organization.id, worker_id) is True


def test_cross_organization_execution_is_forbidden() -> None:
    owner = _org()
    intruder = _org()
    worker_id = _register_worker(_unique("private"))
    orgs.assign_worker(worker_id, owner.id)

    assert orgs.may_execute_on_worker(intruder.id, worker_id) is False
    with pytest.raises(CrossOrganizationError):
        orgs.require_worker_access(intruder.id, worker_id)


def test_shared_pool_worker_is_usable_when_policy_allows() -> None:
    organization = _org()
    worker_id = _register_worker(_unique("shared"))
    orgs.assign_worker(worker_id, None)

    assert orgs.worker_organization(worker_id) is None
    assert orgs.may_execute_on_worker(organization.id, worker_id) is True


def test_shared_pool_can_be_refused_by_organization() -> None:
    organization = _org()
    orgs.update_organization(organization.id, {"allow_shared_pool": False})
    worker_id = _register_worker(_unique("shared-denied"))
    orgs.assign_worker(worker_id, None)

    assert orgs.may_execute_on_worker(organization.id, worker_id) is False


def test_dispatcher_skips_workers_owned_by_another_organization() -> None:
    owner = _org()
    intruder = _org()
    orgs.update_organization(intruder.id, {"allow_shared_pool": False})

    worker_id = _register_worker(_unique("dispatch-owned"))
    orgs.assign_worker(worker_id, owner.id)

    owner_candidates = {
        c.worker.id
        for c in runtime.dispatcher.select_candidates("image", organization_id=owner.id)
    }
    intruder_candidates = {
        c.worker.id
        for c in runtime.dispatcher.select_candidates("image", organization_id=intruder.id)
    }

    assert worker_id in owner_candidates
    assert worker_id not in intruder_candidates


def test_worker_transfer_emits_event_and_audits() -> None:
    from atlas_kernel.api import event_bus

    seen: list[WorkerTransferred] = []
    event_bus.subscribe(WorkerTransferred, seen.append)

    organization = _org()
    worker_id = _register_worker(_unique("transferred"))
    orgs.assign_worker(worker_id, organization.id, actor_id="ayoub")

    assert worker_id in {e.worker_id for e in seen}
    records = audit.list_records(
        organization_id=organization.id, action=AuditAction.WORKER_ASSIGNMENT
    )
    assert any(r.target_id == worker_id for r in records)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_api_organization_lifecycle() -> None:
    created = client.post("/organizations", json={"name": _unique("API Org")})
    assert created.status_code == 200
    organization_id = created.json()["id"]

    fetched = client.get(f"/organizations/{organization_id}")
    assert fetched.status_code == 200
    body = fetched.json()
    assert "teams" in body and "members" in body and "roles" in body

    updated = client.put(
        f"/organizations/{organization_id}", json={"description": "via api"}
    )
    assert updated.json()["description"] == "via api"


def test_api_duplicate_slug_is_400() -> None:
    name = _unique("Dup API")
    assert client.post("/organizations", json={"name": name}).status_code == 200
    assert client.post("/organizations", json={"name": name}).status_code == 400


def test_api_member_lifecycle_and_permission_resolution() -> None:
    organization_id = client.post("/organizations", json={"name": _unique("Members")}).json()["id"]
    identity = client.post(
        "/identities", json={"subject": _unique("api-subject"), "display_name": "API User"}
    ).json()

    added = client.post(
        f"/organizations/{organization_id}/members",
        json={
            "identity_id": identity["id"],
            "role_ids": [f"role-{organization_id}-manager"],
        },
    )
    assert added.status_code == 200
    membership_id = added.json()["id"]

    permissions = client.get(
        f"/organizations/{organization_id}/permissions/{identity['id']}"
    ).json()
    assert "Project.Write" in permissions["permissions"]
    assert "Organization.Admin" not in permissions["permissions"]

    removed = client.delete(f"/organizations/{organization_id}/members/{membership_id}")
    assert removed.status_code == 200
    assert client.get(f"/organizations/{organization_id}/members").json() == []


def test_api_roles_and_permissions() -> None:
    all_permissions = client.get("/permissions").json()
    assert {p["permission"] for p in all_permissions} == {p.value for p in Permission}

    organization_id = client.post("/organizations", json={"name": _unique("Roles")}).json()["id"]
    created = client.post(
        "/roles",
        json={
            "name": "Custom Publisher",
            "permissions": ["Asset.Publish"],
            "organization_id": organization_id,
        },
    )
    assert created.status_code == 200
    role_id = created.json()["id"]

    updated = client.put(
        f"/roles/{role_id}", json={"permissions": ["Asset.Publish", "Project.Read"]}
    )
    assert updated.status_code == 200
    assert len(updated.json()["permissions"]) == 2


def test_api_builtin_role_update_conflicts() -> None:
    organization_id = client.post("/organizations", json={"name": _unique("Builtin")}).json()["id"]
    response = client.put(
        f"/roles/role-{organization_id}-viewer", json={"permissions": ["Organization.Admin"]}
    )
    assert response.status_code == 409


def test_api_teams() -> None:
    organization_id = client.post("/organizations", json={"name": _unique("Teams")}).json()["id"]
    created = client.post(
        "/teams",
        json={"organization_id": organization_id, "name": "Research", "kind": "research"},
    )
    assert created.status_code == 200
    assert created.json()["kind"] == "research"
    assert created.json()["id"] in {
        t["id"] for t in client.get("/teams", params={"organization_id": organization_id}).json()
    }


def test_api_policies_and_resolution() -> None:
    organization_id = client.post("/organizations", json={"name": _unique("Policies")}).json()["id"]

    client.put(
        "/policies",
        json={
            "organization_id": organization_id,
            "domain": "automation",
            "scope": "organization",
            "settings": {"max_concurrent": 5, "allow_cron": True},
            "locked_keys": ["allow_cron"],
        },
    )
    client.put(
        "/policies",
        json={
            "organization_id": organization_id,
            "domain": "automation",
            "scope": "project",
            "scope_id": "project-api",
            "settings": {"max_concurrent": 1, "allow_cron": False},
        },
    )

    resolved = client.get(
        "/policies/resolve",
        params={
            "organization_id": organization_id,
            "domain": "automation",
            "project_id": "project-api",
        },
    ).json()

    assert resolved["settings"]["max_concurrent"] == 1, "narrower scope overrides"
    assert resolved["settings"]["allow_cron"] is True, "locked key survives"


def test_api_audit_listing_and_fetch() -> None:
    organization_id = client.post("/organizations", json={"name": _unique("Audit")}).json()["id"]

    records = client.get("/audit", params={"organization_id": organization_id}).json()
    assert records
    record_id = records[0]["id"]

    fetched = client.get(f"/audit/{record_id}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == record_id
    assert client.get("/audit/audit-missing").status_code == 404


def test_api_identity_providers_report_implementation_status() -> None:
    providers = client.get("/identity-providers").json()
    by_kind = {p["kind"]: p["implemented"] for p in providers}
    assert by_kind["local"] is True
    assert all(not by_kind[k] for k in ("oidc", "ldap", "saml", "github", "google", "microsoft"))


def test_api_missing_organization_is_404() -> None:
    assert client.get("/organizations/org-missing").status_code == 404
    assert (
        client.post("/organizations/org-missing/members", json={"identity_id": "i"}).status_code
        == 404
    )


# ---------------------------------------------------------------------------
# Architecture contracts
# ---------------------------------------------------------------------------


def test_organization_layer_never_touches_providers_or_runtime() -> None:
    for name in ("service.py", "permissions.py", "policy_resolver.py", "audit.py", "identity.py"):
        source = (KERNEL_ROOT / "organization" / name).read_text(encoding="utf-8")
        assert "ProviderManager" not in source
        assert "ProviderRouter" not in source
        assert "from ..providers" not in source
        assert "AgentRuntime" not in source


def test_cluster_does_not_import_the_organization_domain() -> None:
    """Ownership reaches the dispatcher through an injected Protocol, so the
    cluster layer stays independent of organizations."""
    for path in (KERNEL_ROOT / "cluster").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "from ..organization" not in source
        assert "import organization" not in source


def test_no_billing_or_subscription_code() -> None:
    forbidden = ("stripe", "invoice", "subscription", "payment", "checkout")
    for path in (KERNEL_ROOT / "organization").glob("*.py"):
        source = path.read_text(encoding="utf-8").lower()
        for token in forbidden:
            assert token not in source, f"{path.name} references {token}"


def test_organization_services_constructed_only_in_composition_root() -> None:
    constructed = {"OrganizationService", "AuditService", "IdentityService", "PermissionEngine"}
    for path in KERNEL_ROOT.glob("*.py"):
        if path.name in {"composition_root.py", "api.py"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in constructed
            ):
                raise AssertionError(
                    f"{path.name} constructs {node.func.id} outside composition root"
                )


def test_dispatcher_ownership_filter_is_optional() -> None:
    """A dispatcher built without an ownership filter behaves as before M010."""
    from atlas_kernel.cluster.dispatcher import Dispatcher

    assert "ownership_filter" in Dispatcher.__init__.__code__.co_varnames
    assert runtime.dispatcher.ownership_filter is runtime.organization_service
