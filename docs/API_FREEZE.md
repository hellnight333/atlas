# Public API freeze — Alpha RC1

Frozen at **0.12.0-alpha.1**: 208 HTTP routes across 53 resource groups.

## What "frozen" means for an alpha

Within the `0.12.x` line the contracts below will not break: no route is
removed, no required field is added, no response field is removed, no status
code changes meaning. Additive change — new routes, new optional fields, new
enum members — remains allowed, so a client must ignore fields it does not
recognise.

**Alpha is not a compatibility promise past 0.12.x.** Version 0.13 may break
anything here, with the change recorded in `CHANGELOG.md`. Building something
long-lived against this API is premature; building a script or an integration
experiment is exactly what it is for.

## Addressing

Every route answers at the root and under `/api`:

```
GET /version        ==  GET /api/version
```

The kernel defines routes at the root; the desktop client addresses them under
`/api`. Both forms are frozen — the prefix is not a deprecated alias.

**No authentication exists.** The API binds to localhost and assumes one
trusted operator. Do not expose it. Adding auth in a later version will be a
breaking change and is expected to be one.

## Frozen surfaces

| Group | Routes | Stability |
|---|---|---|
| Orchestration — workspaces, projects, runs, steps, jobs | 20 | Frozen |
| Automation — rules, runs, logs, dry-run, enable/disable | 14 | Frozen |
| Agents, teams, assignments, mailboxes | 14 | Frozen |
| Approvals — requests, decisions, policies | 12 | Frozen |
| Organizations, teams, roles, identities, memberships | 10 | Frozen |
| Cluster — workers, placement, load, health | 9 | Frozen |
| Diagnostics, health, configuration | 8 | Frozen |
| Workflow engine | 7 | Frozen |
| Runtime, scheduler | 13 | Frozen |
| Knowledge graph | 7 | Frozen |
| Research, review, chat | 21 | Frozen |
| Assets, capabilities, images | 14 | Frozen |
| Backups, recovery | 7 | Frozen |
| Release surface — version, license, telemetry, updates | 6 | Frozen |
| Onboarding, demos | 7 | Frozen |
| Remaining single-purpose routes | 19 | Frozen |

Enumerate the live surface yourself — this is the authority, not the table:

```bash
curl localhost:8000/openapi.json | python3 -m json.tool | grep '"/'
```

## Not frozen

| Surface | Why |
|---|---|
| `ProviderAdapter` | No real adapter exists. Freezing an interface with no implementation would freeze a guess |
| Recipes | Not implemented |
| `/studios` response body | Returns fixed sample data, not a registry. Will change when studios become real |
| Internal Python modules | `atlas_kernel.*` is not a public library. Only HTTP is a contract |
| Database schema | Use the HTTP API or `/backups/export`. Reading tables directly is unsupported |

## Deprecation policy

Within `0.12.x`, nothing is removed. If something must change, the new form
ships alongside the old, the old is marked deprecated in `CHANGELOG.md`, and
removal waits for a minor version bump.
