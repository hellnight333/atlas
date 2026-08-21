# P1.1 — gate report

**No production data was changed. No quarantine was applied. No snapshot was
taken.** Everything below is read-only inspection.

**Two gates are blocking. Phase 1a has not started.**

---

## Gate 1 — classification

Multi-signal, with under-evidenced rows sent to AMBIGUOUS by construction.

Four signals: DNS resolution of the host · RFC 2606/6761 reserved TLD ·
generated hostname pattern (`tl-c2a8712423.ae`) · presence of commercial history
(`website_audited`, `screenshot_captured`, `researched`, `claims_verified`,
`experiment_sent`, `experiment_response`, outreach rows).

| Bucket | Count | Basis |
|---|---|---|
| **REAL** | **352** | Host resolves **and** carries commercial history |
| **FIXTURE** | **747** | Reserved TLD or generated hostname, **and zero commercial history** |
| **AMBIGUOUS** | **1** | Resolves, but has no history either way |
| Total | 1100 | |

**The corroboration that matters: the FIXTURE set carries 0 audit events and 0
outreach messages.** Quarantining all 747 cannot lose commercial history,
because there is none attached to any of them. The REAL set holds all 826.

### On your instruction not to assume

You were right to warn me. My first pass used DNS alone and mis-classified
"Al Noor Dental Clinic" (`https://clinic.test`) as real — it is the test suite's
own fixture. Three heuristics failed before one held:

- **names** — a fixture is called "Al Noor Dental Clinic";
- **`.ae` means real** — false, 432 fixtures use `.ae`;
- **`google-places` means real** — false, fixtures set that source too
  ("Resolve Test Clinic").

The classifier now treats a **reserved TLD as conclusive**, which is a fact
rather than a heuristic: `.test`, `.example`, `.invalid` and `.localhost` are
reserved by RFC and can never be a real business address. Everything else needs
two independent signals plus an absence of history.

### The one AMBIGUOUS record — not quarantined

```
Confidence Clinic    https://conf.ae    resolves, but no commercial history
```

It resolves, so it is not obviously a fixture; it has no history, so nothing
corroborates it. **Per your rule I have not classified it and will not move
it.** It stays exactly where it is. Your earlier figure of 353 real is this row
plus my 352 — the difference is precisely this record.

## Gate 2 — suppression and contact history

Decision recorded, **not yet implemented** (implementation belongs to Phase 1b):

- **Suppression stays house-level.** A do-not-contact request is globally
  effective across tenants.
- **Contact history becomes tenant-scoped.**
- The two are not merged.
- Four tests to be added, all at the repository layer: suppression remains
  globally effective · A cannot read B's contact history · A cannot modify B's ·
  no leak through aggregate or list endpoints.

## Gate 3 — house organization: **BLOCKING, no candidate exists**

| Search | Result |
|---|---|
| Name or slug matching qevik/atlas/house/operator/internal | **none** |
| Organizations not matching the fixture pattern `Name-xxxxxxxx` | **0 of 1431** |
| Organizations referenced by audit records | only fixtures (`Org-a532a011`, 4 records each) |
| `QEVIK_ORGANIZATION_ID`, `ATLAS_ORGANIZATION_ID`, `QEVIK_TENANT_ID`, … | all unset |
| Any reference in `atlas.env` | none |

**There is no house organization, and there is no evidence from which to infer
one.** All 1,431 organizations are test residue.

You instructed: *do not create a new organization just to satisfy the
migration*; *if there is no candidate, stop and ask*. **So I am asking.**

The tenancy backfill cannot proceed until you tell me the name and slug of the
organization that will own 352 real businesses and 826 commercial records. I
will not choose that identity.

## Gate 4 — snapshot: procedure prepared, **not executed**

| | |
|---|---|
| Database type | PostgreSQL **18.4** (Ubuntu 18.4-0ubuntu0.26.04.1) |
| Database | `qevik` on `127.0.0.1:5432` |
| Size | **50 MB** |
| Tables | 69 |
| Largest | `atlas_assets` 4,949 rows / 4.3 MB · `atlas_roles` 10,152 / 3.4 MB · `atlas_business_events` 1,886 / 2.2 MB |
| Tables affected by Phase 1a | `atlas_businesses` · `atlas_business_events` · `atlas_organizations` · `atlas_projects` · `atlas_assets` · `atlas_jobs` · plus the new `atlas_quarantined_fixtures` |
| `pg_dump` | present at `/usr/bin/pg_dump` |
| Disk headroom | 134 GB free on `/` — a 50 MB database is not a constraint |

**Snapshot command, for the operator to run:**

```bash
sudo -u postgres pg_dump -Fc -d qevik \
  -f /var/backups/qevik-$(date +%Y%m%d-%H%M%S).dump
```

**Restore:**

```bash
sudo -u postgres pg_restore -d qevik --clean --if-exists \
  /var/backups/qevik-<timestamp>.dump
```

A custom-format dump of 50 MB takes seconds and restores the whole database.
**I have not run it.** Say the word and I will, or run it yourself — it is a
production write in the sense that it creates a file, and you asked to authorise
that explicitly.

---

## What happens once the gates clear

Phase 1a, in this order, in one transaction with `--apply` required:

1. Snapshot verified present.
2. Re-run DNS inside the transaction.
3. Copy all 747 fixture rows into `atlas_quarantined_fixtures` with the complete
   original row, original table, original primary key, timestamp, reason and the
   signals that classified it.
4. Verify the REAL set: **352 businesses, 826 commercial records, AHS present**.
5. Remove the quarantined rows.
6. Re-count. **Roll back if any REAL count moved.**
7. Check orphans before and after.
8. Report and stop.

The 1 AMBIGUOUS record is excluded from every step.

## Answers to the required report, as far as the gates allow

1. **Classification** — 352 REAL / 747 FIXTURE / 1 AMBIGUOUS.
2. **Quarantine** — not performed.
3. **Commercial history** — unchanged: 1,886 events, 16 outreach, 1,100 businesses.
4. **Integrity** — unchanged; 3,376 orphaned assets pre-exist and are in the
   fixture set.
5. **AHS** — classified REAL, `466e86e8-01cd-4dbd-a401-2543d0123994`, history and
   its `researched` event intact and untouched.
6. **House organization** — **none exists.** Blocking.
7. **Snapshot** — not taken; procedure above; awaiting authorisation.
8. **Production changes** — **none.**
9. **Rollback** — nothing to roll back.
10. **Tests** — no code was written this phase.
11. **STOP** — stopped.

## What I need from you

1. **The house organization's name and slug.** No candidate exists and I will
   not invent one.
2. **Authorisation to run the snapshot**, or confirmation you have taken one.
3. **A decision on "Confidence Clinic"** (`https://conf.ae`) — real prospect or
   fixture? It stays untouched either way until you say.
4. **Confirmation** that 747 is the number you expect to be quarantined, given
   my 352/747/1 split differs by one row from your 353/747.
