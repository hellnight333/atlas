# Atlas Administrator Guide

For the person who runs Atlas for other people. Assumes `DEPLOYMENT.md` for
installation and `CONFIGURATION.md` for settings.

## Daily posture

Two endpoints tell you everything:

```bash
curl localhost:8000/health/report      # is anything degraded, and why
curl localhost:8000/recovery/report    # is any work stranded
```

If both are clean, Atlas is healthy. Neither performs repairs.

## Organizations and access

Atlas is multi-tenant. An organization owns projects, assets, workers,
automation, policies and its own knowledge graph.

```bash
curl -X POST localhost:8000/organizations -d '{"name":"Eminent Tech","actor_id":"you"}'
```

Creating an organization seeds seven built-in roles (owner → viewer). Built-in
roles cannot be edited — create a custom role instead. Both kinds resolve
through identical code, so a custom role is not second-class.

### Granting access

```bash
curl -X POST localhost:8000/identities -d '{"subject":"mani","display_name":"Mani"}'
curl -X POST localhost:8000/organizations/{org}/members \
  -d '{"identity_id":"...","role_ids":["role-{org}-manager"],"actor_id":"you"}'
```

Temporary access: pass `expires_at`. An expired membership grants **nothing** —
there is no grace period.

### Answering "why can this person do that?"

```bash
curl localhost:8000/organizations/{org}/permissions/{identity}
```

Every permission comes back with the role and membership that granted it. This
is the same data the Inspector shows, so support answers match the UI.

## Policies

Policies inherit `Organization → Workspace → Project → Object`. A narrower scope
overrides a broader one key by key.

To enforce something a project **cannot** opt out of, lock the key:

```bash
curl -X PUT localhost:8000/policies -d '{
  "organization_id":"...", "domain":"security", "scope":"organization",
  "settings":{"require_mfa":true}, "locked_keys":["require_mfa"], "actor_id":"you"}'
```

Verify what actually applies:

```bash
curl "localhost:8000/policies/resolve?organization_id=...&domain=security&project_id=..."
```

`sources` names the policy set behind each key.

## Approvals

Nothing in Atlas is autonomous. A declarative approval policy pauses execution
before any work is created.

```bash
curl -X PUT localhost:8000/approval-policies -d '{
  "name":"delete-guard","mode":"scoped","scopes":["delete"],
  "required_approvers":["you"],"priority":10}'
```

With no policy configured, nothing requires approval. Guards that always hold:

- A requester can never approve their own request (`403`).
- Only designated approvers can decide (`409`).
- The same person cannot approve twice toward a quorum.
- Decided requests cannot be re-decided.

Pending queue: `GET /approvals?pending_only=true`.

## The cluster

A single machine is a cluster of one; the in-process worker registers itself and
needs no configuration. Add capacity:

```bash
curl -X POST localhost:8000/workers/register -d '{
  "hostname":"office-a6000","capabilities":["image","video"],
  "max_concurrency":2,"tags":["office","gpu"]}'
```

Remote workers must heartbeat (default every ≤90s) or they are marked offline.
The in-process worker is exempt — its liveness is the process itself.

Take a machine out of service without losing running work:

```bash
curl -X POST localhost:8000/workers/{id}/drain    # finishes current work, takes no new
curl -X POST localhost:8000/workers/{id}/pause    # takes no new work
curl -X POST localhost:8000/workers/{id}/resume
```

Workers belong to one organization or the shared pool. Cross-organization
execution is refused unless the organization allows the shared pool.

## Backups

Back up before upgrades and before bulk deletions:

```bash
curl -X POST localhost:8000/backups/export -d '{"scope":"organization","scope_id":"..."}' > org.json
```

Always `validate` before `restore`, and prefer `dry_run: true` first. Restore is
additive: it never overwrites an existing row. Audit records are exported for
the record but never restored.

Archives contain **asset metadata, not asset bytes**. Backing up Atlas is not a
substitute for backing up the asset store and the database.

## Audit

Every governance change is recorded immutably: logins, permission and policy
changes, worker assignment, publishing, deletion, exports.

```bash
curl "localhost:8000/audit?organization_id=...&action=permission_changed"
```

There is no update or delete path for audit records anywhere in the kernel, and
re-inserting a modified record is a no-op. If you need to explain an incident,
the trail is intact by construction.

## When something is stuck

See `TROUBLESHOOTING.md`. The short version:

1. `GET /health/report` — is a component degraded?
2. `GET /approvals/waiting-executions` — waiting on a human?
3. `GET /cluster/waiting-placement` — waiting on a machine? Read
   `placement_reason`.
4. `POST /recovery/sweep {"dry_run": true}` — then run it for real.

## Collecting a bug report

```bash
curl localhost:8000/diagnostics > diagnostics.json
```

Safe to share: it contains the profile, host, dependency versions and component
health, and deliberately excludes the database URL and any credentials.
