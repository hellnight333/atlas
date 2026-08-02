# Atlas Enterprise Platform & Multi-Tenant Governance

## Objective

Atlas serves individuals, teams, companies, research labs and multiple organizations without
changing Runtime, Scheduler, Providers or the Worker Cluster.

```
Organization  ── owns ──► Projects · Assets · Workers · Automation · Policies · Graph · Studios
     │
     ├── Teams        (engineering · research · creative · operations · management · custom)
     ├── Roles        (permission collections, built-in and custom)
     ├── Memberships  (identity × organization × scope, optionally time-limited)
     └── Policy Sets  Organization → Workspace → Project → Object
```

## Responsibilities

- organization, team, role and membership lifecycle
- declarative permission resolution
- policy inheritance with locking
- append-only audit trail
- worker ownership and cross-organization isolation
- identity seams for enterprise providers

## Non-Responsibilities

- no billing, payments or subscriptions
- no cloud licensing or deployment tooling
- no external identity implementation — interfaces only

`test_no_billing_or_subscription_code` asserts the first point against the source.

## Permissions are data, never a role-name branch

`PermissionEngine` never asks "is this user an admin". It unions the permissions of whatever
roles an identity's live memberships reference. Built-in roles are **seed data in the same
table as custom roles** and resolve through exactly the same code path, so a custom role behaves
identically to a built-in one.

`test_permission_engine_has_no_hardcoded_role_names` greps the engine for every built-in role
name and fails if one appears.

| Role | Grants |
|---|---|
| Owner | every permission |
| Administrator | everything except tenant ownership |
| Manager | project read/write, publish, automation, members, audit |
| Operator | project read/write, execute, worker management |
| Contributor | project read/write, execute |
| Reviewer | read, publish |
| Viewer | read, graph |

Permissions: `Project.Read/Write/Delete`, `Asset.Publish`, `Workflow.Execute`,
`Automation.Manage`, `Worker.Manage`, `Approval.Override`, `Plugin.Install`,
`Studio.Configure`, `Graph.View`, `Organization.Admin`, `Audit.View`, `Policy.Manage`,
`Member.Manage`.

### Membership rules

- An organization-wide membership applies everywhere; a project- or team-scoped membership
  applies only inside its own scope.
- Roles never leak across organizations: a role belonging to org B grants nothing in org A.
- An expired or deactivated membership grants **nothing** — temporary access really expires.
- Every resolved permission carries a `PermissionGrant` explaining which role and membership
  produced it. The Inspector renders that verbatim.

## Policy inheritance

```
Organization → Workspace → Project → Object
```

A narrower scope overrides a broader one **key by key**. Keys listed in a broader scope's
`locked_keys` cannot be overridden below — that is how an organization enforces something a
project cannot opt out of. Resolution records the source policy set for every key, so the UI
can show where a setting came from.

Domains: `approval`, `automation`, `workers`, `plugins`, `providers`, `storage`, `retention`,
`sharing`, `publishing`, `security`.

## Audit is append-only

`AuditService` exposes `record`, `get` and `list_records` — no update, no delete. The
repository exposes no mutating SQL for `atlas_audit_records` either, and the insert uses
`ON CONFLICT DO NOTHING`, so replaying a record with altered fields is a no-op rather than an
overwrite. Four tests enforce this, including one that tampers with a stored record and asserts
the original survives.

Audited actions: login, permission changes, policy changes, automation, approval, execution,
worker assignment, publishing, deletion, exports, organization/membership/role changes. Records
capture `before` and `after`.

## Worker ownership

A worker belongs to one organization or to the shared pool. Cross-organization execution is
forbidden unless the requesting organization permits the shared pool
(`Organization.allow_shared_pool`).

Enforcement reaches the dispatcher through an injected `OwnershipFilter` Protocol, so the
**cluster layer never imports the organization domain** — `test_cluster_does_not_import_the_organization_domain`
enforces that. Without a filter the dispatcher behaves exactly as it did in Milestone 009.

## Identity: interfaces only

`AuthenticationProvider` is the seam. `LocalAuthenticationProvider` trusts a caller-supplied
subject and is suitable for a single-operator desktop install — it is not a login system.

OIDC, LDAP, SAML, GitHub, Google and Microsoft are registered as
`UnimplementedAuthenticationProvider`, which **raises rather than silently authenticating
anyone**. `GET /identity-providers` reports `implemented: false` for each, so the UI can say so
honestly instead of offering a button that does nothing.

## Persistence

Additive tables: `atlas_organizations`, `atlas_teams`, `atlas_roles`, `atlas_identities`,
`atlas_memberships`, `atlas_policy_sets`, `atlas_audit_records`. Worker ownership is recorded in
the existing `atlas_workers.metadata`, so the cluster schema is untouched.

## API

| Method | Path |
|---|---|
| GET / POST | `/organizations` |
| GET / PUT | `/organizations/{id}` |
| GET / POST | `/organizations/{id}/members` |
| PUT / DELETE | `/organizations/{id}/members/{membership_id}` |
| GET | `/organizations/{id}/permissions/{identity_id}` |
| POST | `/organizations/{id}/workers/{worker_id}` |
| GET / POST | `/roles` · PUT `/roles/{id}` |
| GET | `/permissions` |
| GET / POST | `/teams` |
| GET / PUT | `/policies` · GET `/policies/resolve` |
| GET | `/audit` · `/audit/{id}` |
| GET / POST | `/identities` · GET `/identity-providers` |

## Events

`OrganizationCreated/Updated/Archived`, `TeamCreated/Updated`, `MemberAdded/Removed`,
`MembershipChanged`, `RoleCreated/Updated`, `PermissionsChanged`, `PolicySetUpdated`,
`PolicyViolationDetected`, `WorkerTransferred`, `AuditRecorded`, `IdentityAuthenticated`.

## Desktop

**Organization Studio** (`/organizations`) — organizations, members with live permission
resolution, teams, roles with a permission picker, policy editor with locked-key support,
branding and licence, identity provider status, and the audit trail.

**Organization switcher** in the top bar, replacing the hardcoded tenant label.

**Mission Control** — organization health, seat-limit violations, shared-pool posture, audit
alerts.

**Inspector** — owner, organization, tenant, team, role, permission source, policy source and
audit history.

**Activity Center** — permission, role, policy and worker-transfer events as first-class
activities linking into Organization Studio.

## Import constraint

`event_bus` imports `organization.events`, so `organization/__init__.py` performs **no eager
imports** — the same rule as `approval` and `cluster`. Import submodules directly.

## Tests

`packages/kernel/tests/test_organization.py` — 65 tests across organization CRUD, teams,
membership and expiry, role resolution, permission evaluation, policy inheritance and locking,
audit immutability, identity seams, worker ownership, the API surface, and the architecture
contracts.
