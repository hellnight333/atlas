# Phase 1b — pre-migration gate report

**READ-ONLY.** No production data was modified, no migration created, no
organization created, no quarantine performed, nothing deleted. The Qevik house
organization has **not** been created.

---

## 1. Proposed classification

Same conservative standard as Phase 1a: multiple independent signals, plus
commercial-history corroboration, and `UNKNOWN ≠ FIXTURE`.

| Table | Rows | Proposed | Basis |
|---|---|---|---|
| `atlas_organizations` | 1,431 | **FIXTURE** | 4 independent signals, below |
| `atlas_projects` | 2,475 | **FIXTURE** | same |
| `atlas_assets` | 4,947 | **FIXTURE** | same |
| `atlas_jobs` | 1,679 | **FIXTURE** | same |
| `atlas_sites` | 459 | **FIXTURE** | already orphaned before Phase 1a |
| `atlas_site_builds` | 351 | **FIXTURE** | same |
| `atlas_site_deployments` | 405 | **FIXTURE** | same |
| **AMBIGUOUS** | **0** | — | no row failed to classify |

### The four signals, each independent

1. **Creation window.** Every one of the 10,532 rows in the four tables was
   created on **2026-08-17, 18 or 19** — the three days the suite ran against
   production before the isolation fix. **Zero rows exist outside that window**,
   including anything created since. Real work would have continued.
2. **Reserved and local addresses only.** All 4,947 assets resolve to
   `atlas://` (1,135), `file:///tmp/` (3,077) or `example.com` (708). **Zero
   assets have any other address** — and `example.com` is RFC 2606 reserved, so
   the 708 "http" assets cannot be real published artefacts.
3. **No commercial linkage exists structurally.** None of `atlas_organizations`,
   `atlas_projects`, `atlas_assets` or `atlas_jobs` has a `business_id` column.
   There is no path by which a real prospect's work could be recorded in them.
4. **Naming and shape.** 1,431 of 1,431 organizations match `Name-xxxxxxxx`
   (`Acme Labs-77f0679c`, `Duplicate-45eec278`, `Backup Org-bf987d42`); jobs are
   `text.generate` (945) and `image.generate` (734); projects are
   `planner-project`, `proj-chat`, `proj-import`. **This signal alone would not
   be sufficient** — it is the one that misled me in Phase 1a — and is listed
   last for that reason.

Signals 1–3 are each conclusive on their own. All four agree.

## 2. Rows with real commercial history

**None.** There is no structural path for it: the four tables have no
`business_id`, and the three site tables that *do* have one point at **zero**
surviving businesses.

## 3. Does anything real reference them?

| Question | Answer |
|---|---|
| Does a surviving business reference a project, asset, job or organization? | **No** — no such column exists |
| Do sites/builds/deployments reference the 353 surviving businesses? | **No — 0 of 1,215** |
| Do sites/builds/deployments reference projects, assets or jobs? | **No** — `business_id` only |
| Did Phase 1a orphan them? | **No — 0 of 459 / 324 / 216.** All were already orphaned |
| Do they reference the 747 I quarantined? | **No.** They use a `biz-xxxxxxxxx` id format that never matched any row in `atlas_businesses` |

**This corrects a gap in my Phase 1a verification.** I checked five tables for
orphans and did not check `atlas_sites`, `atlas_site_builds` or
`atlas_site_deployments`. Having now checked: **Phase 1a created none of these
orphans.** All 1,215 rows were already orphaned, referencing ids that were never
in the businesses table. My integrity claim stands, but it was narrower than I
stated and I should have said so.

## 4. Dependency graph

The four tables are not four tables. They are the root of a web:

```
atlas_organizations (1431)
  ├── atlas_roles              10152     ├── atlas_memberships   459
  ├── atlas_audit_records       2835     ├── atlas_policy_sets   243
  └── atlas_teams                 81

atlas_projects (2475)
  ├── atlas_agents             1632      ├── atlas_agent_teams          162
  ├── atlas_assets             4947      ├── atlas_runs                1166
  ├── atlas_graph_nodes        1008      ├── atlas_automation_rules     497
  ├── atlas_approval_requests   308      ├── atlas_review_sessions      135
  ├── atlas_chat_conversations   54      ├── atlas_research_sessions     54
  ├── atlas_research_graphs      54      └── atlas_workflows             27

atlas_assets (4947)
  ├── atlas_runtime_executions  841      ├── atlas_renditions           300
  ├── atlas_chat_messages       108      ├── atlas_review_history       108
  ├── atlas_review_sessions     135      ├── atlas_review_items          27
  └── atlas_agent_memory_references 27

atlas_jobs (1679)
  ├── atlas_runtime_executions  922      ├── atlas_assets              1249
  └── qevik_approvals            212

atlas_sites (459) ─ atlas_site_builds (351) ─ atlas_site_deployments (405)
  └── all orphaned: 0 of 1,215 reach a surviving business
```

**Removing the four tables cascades into roughly twenty more.** That is the
central difference from Phase 1a, where the blast radius was five tables and
1,683 rows.

## 5. Rows that cannot be safely classified

**Zero.** Every row in scope satisfies at least three independent conclusive
signals. Nothing landed in AMBIGUOUS.

This is a stronger result than Phase 1a and I want to be explicit about why it
is trustworthy rather than convenient: the businesses table was hard because it
genuinely mixed real prospects with fixtures. These tables are not mixed —
nothing real was ever written to them, because **no code path exists that could
have written a real prospect's work there.**

## 6. Production features depending on these rows

| Table | Modules referencing it |
|---|---|
| `atlas_organizations` | `db.py`, `repository.py` |
| `atlas_projects` | `db.py`, `repository.py` |
| `atlas_assets` | `db.py`, `repository.py` |
| `atlas_jobs` | `db.py`, `repository.py` |
| `atlas_sites` | `db.py`, `website/repository.py` |

`db.py` is schema definition; the repositories are generic accessors. **Nothing
in the sales console or the research engine touches any of them** — the two live
request paths are unaffected.

The features that *would* read them — the asset library, the run graph, the
approval queue, the agent system — are real code with no real data. Emptying the
tables removes fixtures from those views; it does not remove capability.

---

## Expected quarantine count

| Scope | Rows |
|---|---|
| The four tables | **10,532** |
| The three site tables | **1,215** |
| Their dependent rows (~20 tables) | **~24,000** (needs exact enumeration before apply) |
| **AMBIGUOUS, untouched** | **0** |

The dependent count is an estimate from the graph above and **must be enumerated
exactly in a dry run before any apply** — that number is the one I would want
confirmed, not estimated, and it is the reason this should not be one operation.

## Commercial-history impact

**None.** Businesses 353, events 1,301, outreach 16 — all unchanged by anything
proposed here. `Confidence Clinic` remains untouched and unclassified.

## Proposed rollback

Identical to Phase 1a and proven by it: whole rows into
`atlas_quarantined_fixtures` with source table, primary key, reason, evidence
and run id; restore with `jsonb_populate_record` filtered on the run id, parents
before children. Plus a fresh verified `pg_dump` immediately before.

## Exact production changes that would be required

1. A new snapshot, verified before anything.
2. Rows copied to `atlas_quarantined_fixtures` (no schema change — the three
   columns Phase 1a added are already there).
3. Deletes in dependency order, leaves first, in one transaction.
4. **No schema change to any table. No tenancy column. No ownership assignment.**

## Approval gates for the next step

1. **Enumerate the dependent rows exactly** — a read-only dry run producing the
   real number per table, replacing my ~24,000 estimate.
2. **Confirm the blast radius is acceptable**, given it reaches ~20 tables
   including `atlas_roles` (10,152) and `atlas_audit_records` (2,835).
3. **Decide on the audit records specifically.** 2,835 audit rows reference
   fixture organizations. They are an append-only audit trail, and quarantining
   audit history — even fixture audit history — deserves a deliberate decision
   rather than being swept along.
4. **Then** the Qevik house organization, and only then the tenancy backfill.

## A recommendation you did not ask for

The cleanest option may be neither quarantine nor migration. Every row in these
tables was written in a three-day window by a test suite that no longer writes
to production, and none of it has commercial value. **Consider whether the
correct move is to leave them entirely alone** — create the Qevik organization
alongside them, add `Business.organization_id`, and let the fixture rows sit
inert in tables the product does not read.

They cost 50 MB and cross no tenant boundary, because they carry no business
reference at all. Quarantining twenty-four thousand rows across twenty tables to
tidy up data that nothing queries is a large, irreversible-in-practice operation
in exchange for neatness. Tenancy does not require it. The businesses table
needed cleaning because tenancy would have assigned ownership to fake companies;
these tables cannot receive ownership at all.

I would rather raise this now than perform the work and have you ask afterwards
why it was necessary.

---

## STOP

Phase 1b is not started. No Qevik organization exists. No tenancy column exists.
Awaiting review.
