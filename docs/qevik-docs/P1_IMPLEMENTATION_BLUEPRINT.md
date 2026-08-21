# P1 implementation blueprint

No production code, migration, provider connection, billing or publishing was
created. Everything below was measured against the live database read-only on
2026-08-22.

Design that has not changed since `P1_FINAL_ARCHITECTURE.md` is referenced
rather than repeated. What follows is what the gate asked for: the ownership
graph as it **actually is**, every query that can cross a tenant, the minimum
change, the backfill, and the sequence.

---

## 0. The finding that changes the estimate

My previous document said the ownership chain already existed and only
`Business` sat outside it. **That was true of the model and false of the data.**

```
atlas_organizations   1431 rows   tenant_id present, 1431 distinct
                                  workspace_ids present — EMPTY ON ALL 1431
atlas_projects        2475 rows   workspace_id → no organization references it
atlas_assets          4947 rows   project_id → project → dead end
atlas_jobs            1679 rows   NO ownership column of any kind
atlas_businesses      1100 rows   NO ownership column of any kind
atlas_business_events 1886 rows   business_id only
```

Three consequences:

1. **No asset can reach a tenant today.** `Organization.workspace_ids` is empty
   on every row, so `asset → project → workspace → organization` terminates at
   the workspace. The chain is declared, not populated.
2. **`atlas_jobs` is scoped to nothing** — it has `run_id`, `action`, `payload`,
   `provider_name`, but no project, business, organization or tenant. §1's
   question *"which jobs belong to this organization?"* is currently
   unanswerable, and I had not checked this before.
3. **`tenant_id` is a 1:1 alias for organization id** — 1,431 organizations,
   1,431 distinct tenants. It is not a grouping today, so an agency owning
   several client organizations has no expressible representation yet.

So P1.1 is not "add one edge". It is **establishing the ownership chain for the
first time**, across four tables. It remains the right first step and it is a
bigger one than I said.

## 1. Every query that can cross a tenant

`organization_id` and `tenant_id` appear **zero times** in
`opportunity/repository.py` and **zero times** in `control/sales.py`.

| Location | Query | Exposure |
|---|---|---|
| `repository.list_businesses()` | `SELECT * FROM atlas_businesses` | **all 1100, every tenant** |
| `repository.get_business(id)` | by id, no owner check | any business by id |
| `repository.list_events(niche)` | events by niche | all tenants |
| `repository.timeline(business_id)` | by id, no owner check | any business's memory |
| `repository.find_possible_duplicates()` | scans all businesses | cross-tenant identity leak |
| `repository.load_suppression()` / `load_contact_history()` | global | global by design — revisit |
| `sales._rows()` | `SELECT … FROM atlas_businesses` | the entire console read model |
| `infra/research_prospects.py` | least-recently-researched across all | operator tool, but unscoped |

**Thirteen repository methods take no tenant parameter.** This is not a leak to
be patched at the call sites; it is the absence of a parameter in the data layer,
which is exactly why §1 insists isolation cannot be UI filtering.

## 2. Ownership graph — target

```
Tenant  (grouping; today 1:1 with Organization, must become 1:N)
  └── Organization
        ├── Membership → Identity            (exists, unchanged)
        ├── Business            ← NEW EDGE   Business.organization_id
        │     ├── BusinessEvent (business_id, exists)
        │     ├── Research run  (business-scoped — §2 of the gate)
        │     ├── Recommendation (NEW, business_id + project_id)
        │     ├── Measurement    (NEW, business_id)
        │     └── Project        ← NEW EDGE   Project.business_id
        │           ├── Job      ← NEW EDGE   Job.project_id
        │           │     └── Asset (project_id + job_id, exists)
        │           └── Roadmap  (NEW, project-scoped)
        └── Workspace (existing, execution context — not the ownership path)
```

**Decision taken, per gate §2:** `Business` is parallel to and above `Project`,
not under it. A business outlives any initiative. Research is **business-scoped**;
execution is **project-scoped**. A project belongs to exactly one business.

**Decision taken:** `Project` gains `business_id`, and **`tenant_id` is
denormalised onto `Project`, `Job` and `Business`** so every isolation filter is
one hop. The alternative — resolving through workspaces — needs a populated
chain that does not exist and a list-containment join that will not scale.

**Decision held:** no `Asset.business_id`. Assets reach the tenant through
`project_id`, which becomes a real path once `Project` carries `tenant_id`.

## 3. Minimum required change

| Change | Table | Nullable first? | Backfill |
|---|---|---|---|
| `organization_id` + `tenant_id` | `atlas_businesses` | yes | **1100 rows** |
| `business_id` + `tenant_id` | `atlas_projects` | yes | **2475 rows** |
| `project_id` + `tenant_id` | `atlas_jobs` | yes | **1679 rows** |
| tenant filter parameter | 13 repository methods | n/a | none |
| `Tenant` becomes 1:N over organizations | `atlas_organizations` | — | 1431 rows re-pointed |

Assets (4947), events (1886) and messages (16) need **no change** — they inherit
through `project_id` and `business_id` respectively.

### Backfill strategy

There is one operator and no customers, so every existing row belongs to the
house tenant. The backfill is therefore a single `UPDATE … SET tenant_id =
<qevik-internal>` per table, run once, with the columns added nullable, filled,
then made `NOT NULL` in a second migration after verification.

**This is the cheapest this change will ever be.** At 1,100 businesses and one
tenant it is an afternoon. After the first paying customer it is a data-integrity
problem with a legal edge.

## 4. Models (summary; full definitions in `P1_FINAL_ARCHITECTURE.md`)

- **Recommendation** — `business_id`, `project_id`, `opportunity_key`,
  `capability_id`, `evidence_refs[]` (empty raises), rationale, priority,
  confidence, cost, credits, dependencies, approval, status.
  States: `PROPOSED → ACCEPTED → SCHEDULED → EXECUTING → DONE`, plus `DECLINED`
  (permanent), `DEFERRED`, `BLOCKED`, `CANCELLED`.
- **CapabilityOffer** — extends the existing `CapabilitySpec`; adds availability,
  plans, credit cost, approval mode, QA layers, publication targets, business
  models, metrics. **Capability ≠ publication target** (gate §9).
- **Job** — kernel `models.Job` gains `project_id`; the customer-facing
  projection is the extended `sales.JOB_STATES`. No sixth registry.
- **Asset** — existing graph, plus rights: owner, permission_ref,
  copyright_status, provider, model, prompt_ref, transformations,
  approval_state, publication_state, publication_history.
  **Permission inherits through derivation.**
- **Measurement** — metric, baseline, intervention, window, observed,
  attribution (`OBSERVED → ASSOCIATED → ATTRIBUTED → EXPERIMENTALLY_SUPPORTED →
  UNKNOWN`), evidence.
- **Roadmap / Task** — horizon, dependency-ordered tasks, each
  `QEVIK_TASK | CUSTOMER_TASK`, with why, evidence, metric, target, owner.
- **Readiness** — dimensions scored from confirmed evidence only; unverified
  inputs lower *confidence*, never the score; a high score yields no priority.
- **Character** — identity, visuals, voice, wardrobe, camera language,
  continuity, constraints, plus `owner ∈ {customer, qevik, licensed,
  generated_original}`.

## 5. Character ownership (gate §3)

Technical model only; the legal terms are flagged, not written.

| | Customer-owned | Qevik-owned |
|---|---|---|
| Reuse across customers | **never** | yes |
| May incorporate customer identity/assets | yes, theirs | **never** |
| Derivative assets | inherit the customer's rights boundary | Qevik boundary |
| On customer departure | retained, not deleted | unaffected |

**On departure, nothing is deleted.** Provenance and ownership are preserved:
the character definition, source references, generated assets, published assets,
derivatives, embeddings, prompts and voice profiles all keep their owner and
their history. Published assets in particular cannot be un-published by deleting
our record of them, and destroying the provenance would leave assets in the
world whose origin we can no longer explain.

**Requires a legal policy, not an engineering decision:** retention period,
whether a departed customer may demand deletion of derivatives, licence
survival, and whether a Qevik-owned character trained on customer references is
contaminated. Flagged for counsel.

## 6. QA, publication, provider, security, portal, public audit, AI visibility, ecommerce, leads, media, video, social, affiliate

Unchanged from `P1_FINAL_ARCHITECTURE.md` §§3–15 and
`P1_ARCHITECTURE_REVIEW.md` §§9–18. Summarised:

- **QA** — layered gates, not reports; `READY` unreachable with a failing gate.
- **Publication** — one `PublicationTarget` protocol over the three existing
  publish paths (`website/targets`, `actions/handlers`, `media/publishing`).
- **Providers** — reuse `ProviderSpec`/`ProviderRouter`; no vendor in the domain
  model; availability is explicit and nothing assumes an API exists.
- **Security** — repository-layer filters, vault-only credentials, per-tenant
  retention; 404-not-403 on foreign ids.
- **Approval** — policy (`approval/`) decides, gate (`actions/approval_gate.py`)
  obtains; both retained per gate §10.
- **Credits** — extend `QuotaLedger`, tenant-keyed; reserve → execute → settle,
  release on failure. No second ledger.
- **AI visibility** — mention ≠ citation ≠ position; never converted.
- **CRM** — integration-first; do not build.

## 7. Case studies

Ten cases in `P1_FINAL_ARCHITECTURE.md` §15, drawn from the live research run.
The two the gate adds:

**New website from zero.** No research subject exists, so the loop starts at
customer goals rather than evidence. The roadmap is dominated by `CUSTOMER_TASK`
— domain, hosting, brand assets, payment, analytics — and Qevik's first
`QEVIK_TASK` cannot run until several of them complete. This is the case that
proves the customer-task distinction is load-bearing rather than cosmetic.

**New product or game from zero.** Same shape, different capabilities and
metrics. `Project` is typed; "website" is not hard-coded. The capabilities do
not exist yet, which is why this is direction and not backlog.

**AHS remains the strong-business test.** Evidence: STRONG, FAST, 34 orphans, 32
picture-only pages, 170 photographs, four same-day posts, no hreflang, journey
breaking at `call`. Readiness scores technical health high and therefore
recommends **nothing** there. Output: `STRONG BUSINESS + LIMITED WEBSITE
OPPORTUNITY`, produced mechanically.

---

# FINAL GATE — the eight answers

## 1. Blueprint
This document, with `P1_FINAL_ARCHITECTURE.md` for the model definitions.

## 2. Unresolved decisions

1. **Does `Tenant` become 1:N over organizations?** Today it is 1:1 across all
   1,431 rows. Agencies need 1:N. Changing it later re-points every row.
2. **`load_suppression()` and `load_contact_history()` are global by design.**
   Do-not-contact is arguably a house-level fact, not a tenant one — but it
   means one tenant's suppression suppresses another's. Needs a decision.
3. **Readiness weights per business model** — who authors them, are they shown?
4. **Does the customer see raw evidence including `NOT_VERIFIED`?**
5. **Credits per tenant or per business?**
6. **Roadmap regeneration cadence** — silent regeneration invalidates a plan a
   customer is working through.
7. **Character contamination** — legal, not technical (§5).
8. **Public audit depth** — easy to widen, very hard to narrow.

## 3. Production risks

| Risk | Severity | Mitigation |
|---|---|---|
| Backfill mis-assigns ownership | **high** | One tenant today; verify counts before `NOT NULL` |
| `NOT NULL` before backfill completes | high | Two migrations, nullable then constrained |
| A tenant filter missed on one method | **high** | Filter in the repository base, not per method; negative-control test per method |
| 1,679 jobs re-pointed wrongly | medium | Jobs are historical; assign to house tenant, do not infer |
| Console breaks when filters land | medium | Operator scope reads all tenants explicitly |
| Research writes before ownership exists | low | Only 1 business has a `researched` event |

## 4. Migration requirements

**Requires migration:** `atlas_businesses` (+2 cols, 1100 rows) ·
`atlas_projects` (+2, 2475) · `atlas_jobs` (+2, 1679) · later
`atlas_recommendations`, `atlas_measurements`, `atlas_roadmaps`,
`atlas_capability_offers` (new tables) · `Asset` rights columns ·
credit ledger tenant key.

**No migration:** everything expressible as `BusinessEvent` detail — research
runs, approvals, job transitions, media permission, roadmap *state*. This is why
P0 shipped without one.

## 5. Implementation order

P1.1 tenancy → P1.2 Recommendation + CapabilityOffer → **P1.3 AHS slice to
`READY`, no publish** → P1.4 Measurement → P1.5 Roadmap → P1.6 portal read-only
→ P1.7 credits → P1.8+ media, website/content, AI visibility, ecommerce, leads,
video/social, autopilot, agency. Each gated on the one before.

## 6. Complexity per phase

| Phase | Complexity | Driver |
|---|---|---|
| P1.1 tenancy | **high** | 3 migrations, 5,254 rows, 13 methods, isolation tests |
| P1.2 recommendation | medium | 2 new models, evidence gating, matching |
| P1.3 AHS slice | medium | Wiring, not building; the generator exists |
| P1.4 measurement | medium | Model is simple; the attribution gate is the work |
| P1.5 roadmap | **high** | Generation quality is the product; easy to make generic |
| P1.6 portal | high | New application, tenant-safe from line one |
| P1.7 credits | medium | Ledger exists; tenant key and settlement semantics |
| P1.8+ | varies | Each capability is small once the loop exists |

## 7. Safe without migration

`CapabilityOffer` as a code-level registry · the QA gate framework · the
`PublicationTarget` protocol · attribution vocabulary and the phrase gate ·
readiness scoring (derived from existing findings) · roadmap **generation**
(rendered, not stored) · portal read-only against existing endpoints · renaming
one `demos` module · documenting the job-state mapping · every negative-control
test.

**A useful amount of P1 is reachable with no schema change at all** — enough to
prove the loop before touching the database.

## 8. Absolutely requires migration

Tenant isolation (P1.1) · persisted `Recommendation` · persisted `Measurement` ·
persisted `Roadmap` state · `Asset` rights columns · customer-scoped credits ·
`Job.project_id`.

**Nothing customer-facing may ship before P1.1.** Every row written before it
needs back-filling, and the moment a second tenant exists the backfill stops
being an afternoon and becomes a data-integrity problem with a legal edge.
