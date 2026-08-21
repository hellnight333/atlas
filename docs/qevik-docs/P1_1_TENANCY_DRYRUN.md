# Phase 1 — tenancy dry run

**Nothing was written.** Every query below was read-only against production on
2026-08-22. No migration was created or executed.

**The migration cannot proceed as specified, and should not.** The reason is in
§2: the production tables are heavily contaminated with test-suite residue, and
back-filling ownership across them would assign customer ownership to rows that
are not customers — and cement them as real.

---

## 1. Ownership relationships as they actually are

| Table | Rows | Ownership column | Reaches a tenant? |
|---|---|---|---|
| `atlas_organizations` | 1431 | `tenant_id` (1431 distinct), `workspace_ids` | — is the root |
| `atlas_projects` | 2475 | `workspace_id` | **no** — 0 of 2443 workspaces are claimed by any organization |
| `atlas_assets` | 4947 | `project_id` | **no** — and 3376 reference a project that does not exist |
| `atlas_jobs` | 1679 | none | **no** — has `run_id`, `action`, `provider_name`, nothing else |
| `atlas_businesses` | 1100 | none | **no** |
| `atlas_business_events` | 1886 | `business_id` | inherits |
| `atlas_outreach_messages` | 16 | `business_id` | inherits |

`tenant_id` is 1:1 with organization across all 1,431 rows, so it is an alias
rather than a grouping. An agency owning several client organizations has no
representation today.

## 2. The blocking finding: the tables are test residue

All 1,431 organizations match a test-fixture naming pattern — `Acme Labs-77f0679c`,
`Duplicate-45eec278`, `Org-690fb779`, `Backup Org-bf987d42` — created 583/424/424
across 17–19 August. None has a workspace. Projects are `planner-project`,
`proj-a`, `proj-chat`. Assets are `atlas://chat/conversation-…`,
`atlas://planner/research-note`. Jobs are `text.generate` (945) and
`image.generate` (734).

This is almost certainly accumulated pollution from before the test-isolation
fix — `conftest.py` still records that "the suite had no isolation at all: it
wrote to whatever `ATLAS_DATABASE_URL` was set to".

**`atlas_businesses` is a mixture**, which is the hard part.

### Classifying it: three heuristics failed, one holds

| Signal | Verdict |
|---|---|
| Name patterns | **Failed** — "Al Noor Dental Clinic" is a test fixture with a plausible name |
| Reserved TLDs (RFC 2606) | Catches 315, misses fixtures on `.ae` |
| Discovery source (`google-places`, `seed-list`) | **Failed** — fixtures set those sources too ("Resolve Test Clinic") |
| **DNS resolution of the website host** | **Holds.** A fixture cannot fake a domain that resolves |

```
1100 businesses
  353  host resolves in DNS          → real prospects
  432  host does not resolve         → fixtures (tower-a-954183290f.ae, look-one-00ca9486df.ae)
  315  reserved TLD or no website    → fixtures / unusable
```

Corroboration: **all 1,301 audit events and all 16 outreach messages belong to
the resolving set.** The commercial history attaches to the real businesses,
which is what one would expect if the classification is right. AHS resolves.

Sample of the resolving set — unmistakably real Dubai businesses:
`dmrentalcar.ae` · `petalbox.com` · `homeappliancesrepairsuae.com` ·
`americanmdcenter.com` · `draminaalamiri.com` · `aaconsultancy.ae`.

## 3. Every repository method that can cross a tenant

`organization_id` and `tenant_id` appear **zero times** in
`opportunity/repository.py` and **zero times** in `control/sales.py`.

| Method | Exposure | After Phase 1 |
|---|---|---|
| `list_businesses()` | all 1100, every tenant | must take a tenant |
| `get_business(id)` | any business by id | must verify ownership |
| `resolve_business()` | writes without an owner | must take a tenant |
| `find_possible_duplicates()` | scans every business | **cross-tenant identity leak** |
| `save_business()` | writes without an owner | must take a tenant |
| `list_findings(business_id)` | no ownership check | inherits from business |
| `timeline(business_id)` | any business's memory | inherits |
| `list_events(niche)` | all tenants | must take a tenant |
| `list_proposals()` / `get_proposal()` | no ownership check | inherits |
| `delete_unsent_drafts()` | **write**, no ownership check | must verify |
| `record_event()` | **write**, no ownership check | inherits from business |
| `load_suppression()` | global | see §4 |
| `load_contact_history()` | global | see §4 |
| `sales._rows()` | the whole console read model | operator scope, explicit |

Thirteen read paths and three write paths. This is a missing parameter in the
data layer, not a set of call sites to patch — which is exactly why the
instruction forbids solving it in the UI.

## 4. `load_suppression()` and `load_contact_history()` — decision required

Both are global today and I am **not** proposing to change them silently.

**Recommendation: suppression stays house-level; contact history becomes
tenant-scoped.**

A do-not-contact request is made to *us*, by a person who does not know or care
which tenant holds their record, and honouring it in one tenant while another
mails them would be indefensible — and in several jurisdictions unlawful. Contact
history is different: it is a record of *a tenant's* outreach, and one tenant
should not be able to infer another's activity from it.

This needs your explicit agreement because it means a global table survives the
isolation work by design, and a future auditor will ask why.

## 5. Ambiguous records — the stop condition

The instruction says: *never guess ownership; if any row cannot be mapped
safely, stop and report it.*

- **353 businesses** — unambiguous. One house organization. Safe to map.
- **747 businesses** — fixtures. **Mapping them is the ambiguity.** Assigning
  them to the house tenant makes 747 fake companies permanent customer records
  and inflates every count in the product.
- **1,431 organizations / 2,475 projects / 4,947 assets / 1,679 jobs** — no real
  ownership exists to preserve. Back-filling would be inventing it.

**So I have stopped**, as instructed.

## 6. Proposed plan

### Phase 1a — cleanup, before any tenancy change

Quarantine rather than delete, extending the existing
`infra/quarantine_fixtures.py`, which already implements the right shape: copy
the whole original row into `atlas_quarantined_fixtures` with its source table
and the reason, then remove it — reversible with a `SELECT`.

| Step | Rows | Method |
|---|---|---|
| Quarantine non-resolving businesses | 432 | DNS verdict, list reviewed by you first |
| Quarantine reserved-TLD / no-site businesses | 315 | RFC 2606, unambiguous |
| Quarantine their events | 585 | follows `business_id` |
| Quarantine test organizations | 1431 | 100% fixture-patterned, none has a workspace |
| Quarantine test projects / assets / jobs | 2475 / 4947 / 1679 | no real ownership exists |

Guards: re-run the DNS check inside the transaction; count the 353 real
businesses and their 1,301 events before and after and roll back if either
moves; `--apply` required, dry run is the default.

**You review the 747-row list before anything moves.**

### Phase 1b — tenancy, on clean data

| Change | Table | Rows after cleanup |
|---|---|---|
| `+ organization_id`, `+ tenant_id` (nullable) | `atlas_businesses` | **353** |
| `+ business_id`, `+ tenant_id` (nullable) | `atlas_projects` | 0 |
| `+ project_id`, `+ tenant_id` (nullable) | `atlas_jobs` | 0 |
| Create one house organization | `atlas_organizations` | 1 |
| Backfill | — | one `UPDATE`, 353 rows |
| `NOT NULL` | all three | second migration, after verification |
| Tenant predicate | 16 repository methods | code |

After cleanup the backfill is **353 rows and a single statement**, against 5,254
rows before it. The cleanup is what makes the migration safe *and* trivial.

### Rollback

Cleanup: `INSERT … SELECT` back from `atlas_quarantined_fixtures`. Migration:
columns are additive and nullable in the first step, so rollback is `DROP
COLUMN`. No historical `BusinessEvent` is rewritten at any point.

## 7. What I need from you before Phase 1a

1. **Agreement that the 747 are fixtures**, having reviewed the list.
2. **The suppression / contact-history decision** in §4.
3. **Confirmation of the house organization's name and slug** — I will not
   invent the identity of the tenant that ends up owning all real commercial
   history.
4. **A database snapshot** taken by you, or authorisation for me to take one,
   before the first write.

Nothing further will touch production until these are answered.
