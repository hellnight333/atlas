# Phase 1a — quarantine report

Completed. **Phase 1b was not started.**

---

## 1. Classification

| Bucket | Count | Basis |
|---|---|---|
| **REAL** | **352** | Host resolves **and** carries commercial history |
| **FIXTURE** | **747** | RFC-reserved TLD or generated hostname, **and zero commercial history** |
| **AMBIGUOUS** | **1** | `Confidence Clinic` / `conf.ae` — resolves, no history |

Re-derived from live data immediately before mutation, inside the same
transaction, rather than read from the earlier list. DNS was re-resolved at that
moment. The run aborts if the counts differ from the approved 352/747/1.

## 2. Quarantine

`quarantine-20260821-233715` — **1,683 rows**, all copied whole before removal:

| Table | Copied | Removed |
|---|---|---|
| `atlas_findings` | 216 | 216 |
| `atlas_opportunities` | 81 | 81 |
| `atlas_proposals` | 54 | 54 |
| `atlas_outreach_messages` | 0 | 0 |
| `atlas_business_events` | 585 | 585 |
| `atlas_businesses` | 747 | 747 |
| **Total** | **1,683** | **1,683** |

Copied and removed counts are compared per table inside the transaction; a
mismatch rolls the whole thing back.

Each archived row carries the complete original row as `jsonb`, its original
primary key, source table, `business_id`, the per-row reason, the classification
evidence (website, host, resolves, reserved_tld, generated_host,
commercial_records) and the run id. **Evidence recorded on all 1,683.**

## 3. Commercial history

| | Before | After |
|---|---|---|
| Businesses | 1,100 | **353** |
| Business events | 1,886 | **1,301** |
| Outreach messages | 16 | **16** |
| Findings | 400 | 184 |
| Opportunities | 141 | 60 |
| Proposals | 54 | 0 |

**Commercial history on the real set: 1,301 → 1,301, unchanged.** Verified
inside the transaction before commit; the run rolls back if it moves by one.

The fixture set was proven to carry **0 commercial events and 0 outreach
messages** before anything was touched, and the check was repeated at apply time.

## 4. Integrity

| Check | After |
|---|---|
| Events with no business | **0** |
| Outreach with no business | **0** |
| Findings with no business | **0** |
| Opportunities with no business | **0** |
| Proposals with no business | **0** |

Children were removed before parents, so no orphan was created at any point.

## 5. AHS

Intact. `466e86e8-01cd-4dbd-a401-2543d0123994` — "AHS Catering And Events In
Dubai", **19 events**, including the `researched` event from the research engine,
plus `website_audited`, `claims_verified`, `screenshot_captured`,
`media_permission_recorded`, `product_build_requested/progressed`,
`prospect_scored`, `experiment_prepared`.

The live prospect page still returns the full research block: state `READY`,
model `CATERING`, position `STRONG`, speed `FAST`, 60 pages, 501 media, 34
orphans.

## 6. House organization

**Still none, and none was created.** Per your instruction the 352 real
businesses remain **unassigned to any tenant**. No `organization_id` column was
added and no backfill was attempted.

## 7. Snapshot

Taken and verified **before** any mutation.

```
path      /var/backups/qevik-20260821-233035.dump
size      4,208,242 bytes
sha256    77f5b3eceda26f827dd66c108653e4773be6dc80680b9cb99567b6e816357055
taken     2026-08-21T23:30:35Z
database  qevik   (PostgreSQL 18.4)
verified  284 TOC entries, 69 table-data entries, all 7 critical tables present
```

The first verification reported "not readable" — that was `pg_restore` running
as `postgres` against a root-owned `0600` file, not a bad dump. Re-verified as
root before proceeding.

## 8. Production changes

1. `atlas_quarantined_fixtures` gained three additive columns — `business_id`,
   `evidence`, `run_id`. The table already existed with 189 rows from an earlier
   quarantine and `id` already held the original primary key, so it was extended
   rather than duplicated. **No existing archived row was modified.**
2. 1,683 rows copied into that archive and removed from five production tables.

**Nothing else.** No schema change to any business table, no tenancy column, no
ownership assignment, no historical `BusinessEvent` rewritten, no customer data
deleted.

## 9. Rollback

Per table, from the archive:

```sql
INSERT INTO atlas_businesses
SELECT (jsonb_populate_record(NULL::atlas_businesses, row)).*
FROM atlas_quarantined_fixtures
WHERE run_id = 'quarantine-20260821-233715'
  AND source_table = 'atlas_businesses';
```

Repeat for `atlas_business_events`, `atlas_findings`, `atlas_opportunities`,
`atlas_proposals` — **parents first**, then children, the reverse of removal.

Or restore the whole database:

```bash
sudo -u postgres pg_restore -d qevik --clean --if-exists \
  /var/backups/qevik-20260821-233035.dump
```

## 10. Tests

**Full suite: 1,928 passed, 4 skipped, 91.38% coverage.** Unchanged from before
the quarantine — the suite runs against `<db>_test` and was unaffected, which is
itself the confirmation that the isolation fix works.

Live application after the change: `app.qevik.ai` 200; the prospect endpoint
returns 401 unauthenticated, so authorisation is still enforced; the AHS
prospect payload renders in full.

The guards in the tool are negative controls in the operational sense — each one
aborts the run rather than reporting: counts differing from 352/747/1, any
commercial history on a fixture, copied ≠ removed per table, business count
wrong after removal, real history changed, or any orphan created.

## 11. STOP

Phase 1b has not started. No tenancy column exists. The house organization is
still unresolved and remains the blocker.

---

## What I need for Phase 1b

1. **The house organization's name and slug.** 352 businesses and 1,301
   commercial records are waiting for an owner and I will not choose it.
2. **A verdict on `Confidence Clinic`** (`conf.ae`) — real prospect or fixture.
   Untouched, and it is why the business count is 353 rather than 352.

## One thing worth noting

`atlas_organizations` still holds **1,431 rows, all of them test residue** — as
do `atlas_projects` (2,475), `atlas_assets` (4,947) and `atlas_jobs` (1,679).
They were outside the approved scope of this phase, which covered business
fixtures only. They will need the same treatment before tenancy, since assigning
ownership through a chain of fixture projects would be meaningless. That is a
separate approval.
