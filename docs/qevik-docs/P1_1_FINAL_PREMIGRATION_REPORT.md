# P1.1 — final pre-migration report

**No migration has been performed.** No schema changed, no ownership assigned.
Two things were done under explicit instruction and are reported below: the test
isolation boundary (item 4, a prerequisite) and the Qevik house organization
(item 2, one reversible row).

---

## 0. Done since the last report

### The production-database boundary (item 4)

`conftest.py` redirected `ATLAS_DATABASE_URL` to a `_test` database. That worked,
and it protected only code loading that conftest — a script in `infra/`, a test
in another directory, a doctest, or a future conftest that stops importing first
all bypassed it. The evidence it was insufficient is the 10,532 fixture rows
still sitting in production.

Enforcement now lives at the engine, in `atlas_kernel/db_safety.py`, called from
`db.py` **before `create_engine`** — the one place every caller passes through.
It **refuses** rather than redirects, because a redirect that computes the wrong
name silently uses production while a refusal cannot.

- **Test process detected** by two independent signals: `PYTEST_CURRENT_TEST`,
  and `pytest` in `sys.modules` (which covers collection and import, before any
  test runs).
- **Fails closed.** A database whose name does not clearly say "test" is treated
  as production — including an empty name.
- **Escape hatch** is `QEVIK_ALLOW_PRODUCTION_DB_IN_TESTS=1`, exact-match only.
  `true`, `yes`, `TRUE` and `0` all still refuse.
- **Credentials never appear** in the refusal message.

**28 tests**, including a regression that launches a real interpreter, imports
`atlas_kernel.db` with a production URL and asserts it raises. Negative-controlled:
removing the guard fails both the regression and the wiring assertion.

This does not rely on developer discipline or on an environment variable being
set correctly — the variable being wrong is the case it catches.

### The Qevik house organization (item 2)

Created through `OrganizationService`, not a raw insert.

```
id        org-a393025bd19e
name      Qevik
slug      qevik
tenant_id tenant-b9d7bfaa4fd8
active    true
created   2026-08-21T23:59:21Z
```

Organizations 1,431 → 1,432. **No organization named Asia Link exists**, and
none was created; it stays available as a separate real customer organization.

## 1. Exact rows to be changed

| Table | Rows | Change |
|---|---|---|
| `atlas_businesses` | **352** | `organization_id` = `org-a393025bd19e`, `tenant_id` = `tenant-b9d7bfaa4fd8` |
| `atlas_projects` | **0** | columns added, no rows to fill |
| `atlas_jobs` | **0** | columns added, no rows to fill |

**352 rows change. That is the entire backfill.**

Projects and jobs get their columns now so the shape is right, but every
existing row in both is legacy test residue and is deliberately left `NULL` —
see §2.

## 2. Exact rows excluded

| Excluded | Rows | Why |
|---|---|---|
| **Confidence Clinic** (`conf.ae`) | 1 | AMBIGUOUS. Unresolved by instruction. No owner, no tenant, untouched |
| `atlas_organizations` residue | 1,431 | Legacy test residue, left inert |
| `atlas_projects` | 2,475 | Legacy test residue — `tenant_id` stays `NULL` |
| `atlas_assets` | 4,947 | Legacy test residue, reached only through projects |
| `atlas_jobs` | 1,679 | Legacy test residue — `tenant_id` stays `NULL` |
| `atlas_sites` / builds / deployments | 1,215 | Already orphaned before Phase 1a |
| Dependent rows across ~20 tables | ~24,000 | Not touched |

**Legacy test residue is documented and explicitly excluded from tenancy
ownership.** It was written by the suite on 17–19 August 2026, has no
`business_id` column, references no surviving business, and is read by no live
request path. It is left inert on purpose, not overlooked. A `NULL` tenant on
those rows is the correct and honest record: they have no owner.

## 3. Exact ownership assignments

```
tenant-b9d7bfaa4fd8  (Qevik)
  └── org-a393025bd19e  Qevik
        └── 352 businesses          ← the verified real prospect set
              ├── 1,301 business events   (inherit through business_id)
              └── 16 outreach messages    (inherit through business_id)

unassigned
  └── 1 business — Confidence Clinic
  └── all legacy residue — tenant_id NULL, permanently
```

Events and outreach are **not** given their own tenant column. They already
carry `business_id`, and a second path would be a second source of truth.

## 4. Repository methods requiring tenant enforcement

Sixteen. Currently `organization_id` and `tenant_id` appear **zero times** in
`opportunity/repository.py` and **zero times** in `control/sales.py`.

| Method | Class | Enforcement |
|---|---|---|
| `list_businesses()` | TENANT_SCOPED | require tenant; no default |
| `get_business(id)` | TENANT_SCOPED | verify ownership, 404 on mismatch |
| `resolve_business()` | TENANT_SCOPED | **write** — tenant required |
| `save_business()` | TENANT_SCOPED | **write** — tenant required |
| `find_possible_duplicates()` | TENANT_SCOPED | scans all today — cross-tenant identity leak |
| `list_findings(business_id)` | BUSINESS_SCOPED | inherits |
| `timeline(business_id)` | BUSINESS_SCOPED | inherits |
| `list_events(niche)` | TENANT_SCOPED | filters all tenants today |
| `record_event()` | BUSINESS_SCOPED | **write** — inherits |
| `list_proposals()` / `get_proposal()` | BUSINESS_SCOPED | inherits |
| `delete_unsent_drafts()` | BUSINESS_SCOPED | **write** — verify first |
| `load_suppression()` | **HOUSE_LEVEL** | stays global, deliberately (§7) |
| `load_contact_history()` | **TENANT_SCOPED** | becomes scoped (§7) |
| `sales._rows()` | HOUSE_LEVEL | operator console, explicitly all tenants |
| `research_prospects.targets()` | TENANT_SCOPED | operator tool, currently unscoped |

Enforcement goes in the repository, with the tenant taken as a parameter rather
than read from a global — a global is a thing a background job forgets to set.

## 5. Foreign keys and indexes

**Foreign keys.** `atlas_businesses.organization_id` →
`atlas_organizations(id)`. Deliberately **not** `ON DELETE CASCADE`: deleting an
organization must not silently delete a customer's businesses. `RESTRICT` is
correct — removing a tenant should require dealing with its data first.

`tenant_id` is denormalised and carries **no** foreign key. There is no tenants
table; it is a grouping key on organizations, and adding one is the separate
1:1→1:N decision still open.

**Indexes.**

```sql
CREATE INDEX CONCURRENTLY atlas_businesses_tenant  ON atlas_businesses (tenant_id);
CREATE INDEX CONCURRENTLY atlas_businesses_org     ON atlas_businesses (organization_id);
CREATE INDEX CONCURRENTLY atlas_projects_tenant    ON atlas_projects (tenant_id);
CREATE INDEX CONCURRENTLY atlas_jobs_tenant        ON atlas_jobs (tenant_id);
```

`CONCURRENTLY` because every read path will filter on `tenant_id`, and it must
be an index scan from the first query rather than a sequential scan over a
growing table. At 353 rows it makes no measurable difference today; the point is
that it is never added later under load.

`NOT NULL` is **not** applied. Legacy residue keeps `NULL`, and that is the
correct record.

## 6. Migration order

| # | Step | Reversible |
|---|---|---|
| 1 | Fresh verified `pg_dump` | — |
| 2 | Add nullable columns to the three tables | `DROP COLUMN` |
| 3 | Create the indexes concurrently | `DROP INDEX` |
| 4 | Backfill 352 businesses in one `UPDATE` | `SET NULL` on those ids |
| 5 | Verify: 352 owned, 1 NULL, residue NULL, counts unmoved | — |
| 6 | Add the FK to `atlas_organizations` | `DROP CONSTRAINT` |
| 7 | Ship repository enforcement + isolation tests | revert |

Steps 2–6 are one transaction except the concurrent indexes, which cannot run
inside one. Step 7 is a separate deployment: **schema first, enforcement second**,
so a failed deploy leaves a database with unused columns rather than a product
that cannot read its own data.

## 7. Suppression and contact history

Unchanged from your decision. **Suppression stays house-level** — a
do-not-contact request is made to us, by someone who neither knows nor cares
which tenant holds their record, and honouring it in one tenant while another
mails them would be indefensible. **Contact history becomes tenant-scoped** —
it describes one tenant's activity and must not leak. The two are not merged.

## 8. Rollback

```sql
-- step 4
UPDATE atlas_businesses SET organization_id = NULL, tenant_id = NULL
WHERE organization_id = 'org-a393025bd19e';
-- steps 2, 3, 6
ALTER TABLE atlas_businesses DROP CONSTRAINT atlas_businesses_org_fk;
DROP INDEX CONCURRENTLY atlas_businesses_tenant;   -- and the others
ALTER TABLE atlas_businesses DROP COLUMN organization_id, DROP COLUMN tenant_id;
```

Or restore the whole database from the step-1 dump. The house organization is
one row and reverses with a single `DELETE`.

## 9. Negative controls proving cross-tenant access is impossible

Each fails if the tenant predicate is removed:

1. Two tenants, one business each — A's `list_businesses()` never returns B's.
2. `get_business()` on B's id from A's context → **404, not 403**; a 403 confirms
   the record exists.
3. `find_possible_duplicates()` from A never matches B's business — the leak that
   would otherwise expose a competitor's customer list.
4. `record_event()` and `save_business()` from A cannot write against B's id.
5. `list_events()` never crosses tenants.
6. **Aggregates** — counts, summaries and the ready list are computed per tenant;
   a total that includes another tenant's rows leaks their volume.
7. `load_contact_history()` from A never returns B's activity.
8. `load_suppression()` **does** return house-level entries — the deliberate
   exception, tested so it stays deliberate.
9. Removing the predicate from any repository method fails at least one test.
10. A business with a `NULL` tenant (residue, Confidence Clinic) is returned to
    **no** tenant.

## 10. Test isolation verification

- 28 tests in `test_production_database_boundary.py`, all passing.
- The regression launches a real interpreter and proves the import raises.
- Negative-controlled: removing the guard fails two tests.
- `test_this_very_suite_is_pointed_at_a_test_database` asserts the running
  suite's own URL is a test database, whatever the harness did.
- CI inherits this automatically: any runner without an explicit test database
  fails at import rather than writing to production.

---

## STOP

No migration performed. Awaiting review of this report before step 1.

**Two decisions still open, neither blocking this migration:**

1. `Confidence Clinic` — stays unassigned until you resolve it.
2. Whether `tenant_id` becomes 1:N over organizations. It is 1:1 today. Agencies
   need 1:N, and changing it later re-points every row.
