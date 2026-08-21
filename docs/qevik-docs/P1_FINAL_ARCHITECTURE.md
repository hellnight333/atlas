# P1 — final architecture and implementation directive

Architecture only. No production code, schema, migration, provider connection,
publishing, billing, autopilot, CRM or account was created to produce this.

Two corrections to the brief come first, because both would create a parallel
vocabulary if implemented as written, and §50 forbids exactly that.

---

## 0. Two conflicts with shipped production vocabulary

### 0.1 Job states (§10)

| | |
|---|---|
| **Shipped** (`control/sales.JOB_STATES`, live, one record in `CANCELLED`) | QUEUED · RESEARCHING · DESIGNING · BUILDING · MEDIA · QA · REVIEW · READY · FAILED · CANCELLED |
| **§10 proposes** | QUEUED · RUNNING · WAITING_APPROVAL · QA · READY · PUBLISHED · MEASURING · COMPLETED · FAILED · CANCELLED |

These are the same axis with different resolution. The shipped set describes
**what the job is doing**; the proposed set describes **where it is in the
lifecycle**. Adopting the second wholesale would be a second registry for one
subject — the thing §10 itself prohibits.

**Recommendation: extend the shipped set with the four genuinely new states and
keep the five that describe work.**

```
QUEUED → RESEARCHING → DESIGNING → BUILDING → MEDIA → QA → REVIEW
       → WAITING_APPROVAL → READY → PUBLISHED → MEASURING → COMPLETED
                                                  FAILED · CANCELLED
```

`RUNNING` is deliberately not adopted: it is what `RESEARCHING`/`DESIGNING`/
`BUILDING`/`MEDIA` already say, more usefully. An operator reading "running" for
forty minutes learns nothing; "MEDIA" tells them what it is waiting on. Nothing
is renamed and no historical event moves.

### 0.2 Media permission names (§12)

Shipped: `none` · `permission_pending` · `use_originals` · **`edit_enhance`** ·
**`generate_matching`**. The brief writes the last two as `use_enhanced` and
`generate_replacements`.

**Recommendation: keep the shipped keys, adopt the brief's wording as UI
labels.** The keys are in production event history; the labels are free. The
brief's phrasing is better English and should appear on the buttons:

> `edit_enhance` → "Allow enhancement / cropping"
> `generate_matching` → "Allow AI-generated replacement"

`permission_pending` never grants anything — enforced by `MEDIA_ALLOWS_ORIGINALS`.

---

## 1. Updated architecture

The loop is the product. Everything else is a capability inside it.

```
Public audit ─► Research ─► Evidence ─► Opportunity ─► Recommendation
                   ▲                                        │
                   │                                        ▼
             Re-evaluation                            CapabilityOffer
                   ▲                                        │
                   │                                        ▼
             Measurement ◄─ Publish ◄─ Approval ◄─ QA ◄─ Asset ◄─ Job ◄─ Approval
```

The addition this brief makes, and it is the important one: **the loop does not
end at an answer, it ends at a roadmap.** §2's requirement — answer *"what
should I do next"*, not *"what is wrong"* — is what turns an audit tool into an
operating system, and it is satisfied by one new object (§10 below) rather than
by a new subsystem.

## 2. Entity relationships

**The ownership chain already exists.** `Organization` carries `tenant_id` *and*
`workspace_ids`; `Project.workspace_id`; `Asset.project_id`. What sits outside
it is `Business`.

```
Tenant
  └── Organization            (tenant_id, workspace_ids, branding, license)
        ├── Identity ── Membership (organization_id, scope, scope_id, role_ids)
        ├── Workspace
        │     └── Project     (workspace_id)              ── existing
        │           ├── Job   (project scoped)
        │           │     └── Asset (project_id, job_id, run_id, parent_asset_id)
        │           └── Measurement                        ── NEW
        └── Business ◄──────── THE MISSING EDGE
              ├── BusinessEvent (append-only memory)
              ├── Research run → Finding[]
              ├── Opportunity (derived, never stored)
              └── Recommendation                           ── NEW
```

**Business is the subject; Organization is the owner; Project is the unit of
work.** One organization owns many businesses. One business has many projects
(a website project, an SEO project, a social project). Many identities reach one
business through `Membership`. An agency is an organization whose memberships
span client organizations — already expressible.

**The one edge to add: `Business.organization_id`.**

I withdraw the `Asset.business_id` recommendation from the previous review.
Assets already reach a tenant through project → workspace → organization. Adding
a second path would be two sources of truth for one question.

**But the join direction is wrong for filtering.** `Organization.workspace_ids`
is a list *on the organization*, so "every asset for this tenant" is a three-hop
query ending in list containment. The fix is a denormalised `tenant_id` on
`Project` (and therefore reachable from `Asset` in one hop), maintained on
creation. That is a small, additive change and it is what makes §45's isolation
enforceable in the repository rather than the view.

## 3. Capability lifecycle

```
CapabilitySpec (exists)  ──┐
                           ├──► CapabilityOffer (NEW, commercial half)
ProviderSpec (exists)    ──┘         │
                                     ├─ availability: AVAILABLE | REQUIRES_CONNECTION
                                     │                | REQUIRES_APPROVAL | UNAVAILABLE
                                     ├─ plans, credit_cost, approval mode
                                     ├─ qa_layers, publication_targets
                                     ├─ business_models (from research.classify)
                                     └─ measurement metrics
```

**Capability ≠ publication target**, adopted from §8. One capability, many
targets:

```
Capability: product_listing.optimise
Targets:    amazon · noon · shopify · woocommerce · website
```

The target owns the credential, the platform rules and the publication QA. This
is why `amazon.listing.create` is not a capability: modelling it as one gives
every marketplace its own copy of approval, credential and QA logic, and they
will drift.

A capability whose availability is `REQUIRES_CONNECTION` **still produces
recommendations** — it just cannot produce jobs. That is what lets Qevik
recommend Amazon work honestly before Amazon access exists.

## 4. Recommendation lifecycle

```
Opportunity ──► Recommendation ──► CapabilityOffer ──► Approval ──► Job
   (derived)      (persisted)         (matched)
```

```
Recommendation
  id · business_id · project_id · opportunity_key · capability_id
  title · rationale · evidence_refs[]        ← empty raises; no evidence, no rec
  expected_benefit · priority · confidence · risk
  estimated_cost · estimated_credits · dependencies[]
  approval_required · status · created_at
```

States: `PROPOSED → ACCEPTED → SCHEDULED → EXECUTING → DONE`, plus `DECLINED`
(permanently — a business that says "not for us" must not be asked every cycle)
and `BLOCKED` (dependency or connection missing).

**A recommendation with no available capability is still valid** — it becomes
"upgrade your plan" or "connect your account", not a dead end. That is the
commercial bridge working correctly.

## 5. Approval lifecycle

Both mechanisms, layered, exactly as §9 directs.

```
Policy  (approval/ ApprovalPolicy: always | never | scoped)
   │      "does this class of act need a human?"
   ▼
Gate    (actions/approval_gate.py: ApprovalProposal, Risk, GateDecision)
          "here is the actual artefact — approve this act"
```

Policy decides; the gate obtains. The gate pauses the run at the point of
decision and records what was consented to, which is why category consent at
submission is the failure mode its own docstring describes.

Approval appears **twice** in the lifecycle on purpose: once on the
recommendation (approve the plan) and once on the asset (approve this artefact
for publication). They are different consents.

## 6. Job lifecycle

Kernel execution (`models.JobStatus`) stays separate from the customer-facing
projection (`sales.JOB_STATES`, extended per 0.1). One mapping function, tested
both directions, is the only place they meet.

```
QUEUED → RESEARCHING → DESIGNING → BUILDING → MEDIA → QA → REVIEW
   → WAITING_APPROVAL → READY → PUBLISHED → MEASURING → COMPLETED
                                    FAILED · CANCELLED  (terminal)
```

Requirements: idempotency key (business + capability + input hash), child jobs,
retry within the original credit reservation, cancellation from any non-terminal
state, and an audit event per transition. **A job never becomes successful
because generation succeeded** — if publication fails, the job fails and the
asset stays `READY`.

## 7. Asset and provenance lifecycle

Reuse the existing graph — `parent_asset_id`, `source_asset_ids`,
`derived_asset_ids`, `content_hash`, `version`, `job_id`, `run_id`, `embeddings`,
`transcript`, `ocr_text` are all present. **Do not build a second asset system.**

Add rights, which is the actual gap:

```
+ owner            customer | qevik | licensed | generated_original
+ permission_ref   → media permission state at time of use
+ copyright_status
+ provider · model · prompt_ref
+ transformations[]
+ approval_state · publication_state · publication_history[]
```

**Permission is inherited through derivation.** A crop of a photograph we may
not publish is itself unpublishable, enforced in the model rather than
remembered. This is the single most important rule in the asset layer.

## 8. Measurement lifecycle

New, and first-class.

```
Metric ─► Baseline ─► Intervention ─► Window ─► Observed ─► Attribution ─► Evidence
```

Attribution is a scale the system may not skip:

`OBSERVED` → `ASSOCIATED` → `ATTRIBUTED` → `EXPERIMENTALLY_SUPPORTED` → `UNKNOWN`

Most results are `OBSERVED`. `UNKNOWN` is legitimate and reportable, exactly as
`NOT_VERIFIED` is in research. The permitted sentence is *"organic leads
increased from 34 to 61 during the 30-day window following the intervention"*;
*"Qevik increased leads 79%"* is refused by a phrase gate, the same mechanism
that already stops outreach overclaiming.

Metrics: traffic · leads · qualified leads · conversion · revenue · CTR · CPA ·
ROAS · organic visibility · **AI visibility** · content views · engagement ·
marketplace CTR · listing conversion · video views · affiliate commission.

## 9. The 0→100 framework (§3)

A `Readiness` object: dimensions, each scored **only from confirmed evidence**,
each carrying the findings that produced it and the count of what could not be
measured.

```
Readiness(business, project)
  dimensions:
    technical_health  81   from 14 findings,  0 unverified
    social_presence   68   from  6 findings,  2 unverified
    ux                51   from 11 findings,  1 unverified
    seo               37   from 19 findings,  3 unverified
    conversion        29   from  9 findings,  0 unverified
    content           22   from  7 findings,  0 unverified
    ai_visibility     18   from  4 findings,  8 unverified   ← low confidence
  overall             42   weighted by business model
```

Three rules that keep it honest:

1. **A dimension with mostly unverified inputs reports low confidence, not a low
   score.** Not measuring AI visibility is not the same as being invisible.
2. **Weighting is by business model.** Conversion matters more for a caterer
   than content depth; the inverse for a publisher. A single global weighting
   would rank every business the same way and produce the same priorities.
3. **A high score produces no priority.** AHS scores 81 on technical health and
   the framework must therefore recommend nothing there. This is the mechanical
   form of "do not manufacture weaknesses".

Priorities fall out as `(100 − score) × model_weight × capability_availability`,
so a low score with no capability to fix it does not become a priority we cannot
act on.

## 10. Roadmap architecture (§4, §41)

A `Roadmap` is generated, never templated: horizon (7/14/30/60/90), tasks
ordered by dependency, each task one of two kinds.

```
Task
  kind: QEVIK_TASK | CUSTOMER_TASK        ← the distinction that makes it usable
  title · why · evidence_refs[] · expected_benefit
  capability_id (Qevik) | customer_action (customer)
  dependencies[] · effort · approval_required · owner
  status · metric · target · deadline
```

**`CUSTOMER_TASK` is the part that makes this a product rather than a work
queue** (§5). "Connect a payment gateway", "create the Instagram account",
"approve the first ten articles", "grant media permission" — Qevik cannot do
these, and a roadmap that silently omits them is a roadmap that stalls without
explaining why.

Generation inputs, per §4: research · opportunities · business model ·
capability availability · customer goals · dependencies · budget · available
assets · approvals · previous measurements. **The same inputs for two different
businesses produce different roadmaps** because every one of those inputs
differs — there is no default plan to fall back to, by construction: a roadmap
with no evidence has no tasks.

§14's twenty post-launch items are the *website* project's roadmap template
seeded by capability, not a global checklist. A business with no ecommerce never
sees "configure payment gateway".

## 11. Customer portal (§27)

**A new application** sharing the kernel and API — not a role-gated console. The
console is an operator tool over 1,100 businesses; role-gating it means every
future change carries a "does a customer see this" question, and the first time
someone forgets, a customer sees another tenant's row. A separate app makes the
boundary a deployment boundary.

Sections: Dashboard · Research · Opportunities · **Recommendations** ·
**Roadmap** · **Tasks** · Jobs · Assets · Approvals · Publications · Analytics ·
Credits · Reports · Connections · Settings.

Every capability shows one of: **Available · Requires upgrade · Requires
connection · Requires approval · Coming soon** — never hidden, because a
customer who cannot see a capability cannot buy it.

The section that earns the portal is **"Waiting for you"**: approvals, assets to
review, customer tasks, connections to authorise. The customer's real question
is not what the platform does; it is what is stuck on them.

## 12. Capability matrix (§29)

Derived from capability economics, not arbitrary limits. Cost class drives it:
research is cheap and repeatable; video is expensive per unit; leads cost per
record; publishing costs nothing but risks everything.

| Capability | LIST | PRO | ADVANCED | ENTERPRISE |
|---|---|---|---|---|
| Website audit | ✓ | ✓ | ✓ | ✓ |
| Deep research (crawl + CMS) | limited | ✓ | ✓ | ✓ |
| Readiness score + roadmap | 30-day | 30/60 | 30/60/90 | continuous |
| Opportunities | view | + recommend | + capability match | + custom rules |
| SEO | audit | audit + optimise | advanced | custom |
| AI visibility | — | audit | audit + optimise | + monitoring |
| Content / blog | — | ✓ | ✓ | pooled |
| Image generation | limited | ✓ | ✓ | custom |
| Video | — | limited | ✓ | custom |
| Social accounts | — | 1 | 7 | negotiated |
| Ecommerce / marketplace | — | — | Amazon | Amazon + Noon |
| Advertising | — | — | preparation | preparation + execution |
| Leads | — | ✓ | ✓ | + enrichment |
| CRM integration | — | — | ✓ | ✓ |
| Autopilot | — | — | limited | custom |
| Businesses | 1 | 3 | 15 | unlimited |
| API / white-label | — | — | API | both |

**Commercial logic.** LIST converts the public audit — one business, real
findings, nothing executed. PRO is the first plan that *does* something. ADVANCED
is where a business stops being a website and becomes an operation, which is why
marketplace, leads and assisted autopilot arrive together. ENTERPRISE
differentiates by **pooling and delegation**, not bigger numbers. The predictable
lever is **businesses**, and agencies self-select on it.

## 13. Tenancy model (§6)

Answering §6 directly:

| Question | Answer |
|---|---|
| Who owns the business? | An `Organization`, via the new `Business.organization_id` |
| Which org can access it? | Exactly one owner; others only through an explicit share |
| Which assets belong to it? | Assets reach the tenant through `project → workspace → organization` |
| Which jobs? | Jobs are project-scoped; the project is business-scoped |
| Which measurements? | Business-scoped, since a measurement is about the business |
| Multiple businesses per org? | Yes — the plan's `businesses` limit |
| Multiple users per business? | Yes — `Membership` with `scope`/`scope_id` |
| Agency across orgs? | Yes — memberships spanning client organizations |
| Multiple projects per business? | Yes — website, SEO, social are separate projects |

**Isolation is at the repository, never the view.** Every query filters on
tenant. The denormalised `tenant_id` on `Project` (§2) is what makes that a
one-hop filter instead of a list-containment join.

The test that decides whether it holds: **a customer requesting another tenant's
business id receives 404, not 403** — a 403 confirms the record exists.

## 14. Security model (§45)

Tenant isolation as above. Provider credentials live in the vault, referenced by
name, and never enter a job payload, an asset, a log or an API response — no
customer or tenant can read one. Customer media, generated assets, leads,
prompts and reports are tenant-scoped. The existing append-only `AuditService`
records who did what. Deletion, retention and export are per-tenant policy.
Agency isolation is organization isolation; a white-label portal is branding on
the same boundary, never a second customer model.

## 15. Case studies (§32–§37)

Materially different because the evidence is — these are from the live research
run, not invented.

**AHS.** Position STRONG · speed FAST (484ms) · 34 orphaned pages · 32
picture-only pages / 170 photographs · blog of four same-day posts against a
501-item library · no hreflang · journey breaks at `call`. Readiness would score
technical health high and content/AI visibility low. Recommendations: portfolio
discovery system, AI visibility, one-tap contact, Arabic, dormant-editorial
revival, quote-journey structure. **No website rebuild** — the site is fast and
the business is strong. `STRONG BUSINESS + LIMITED WEBSITE OPPORTUNITY` falls
out of the evidence; nobody writes it by hand.

**Coffee shop.** Local visibility, Google Business, menu and order journey,
hours, map, lifestyle media, loyalty. No portfolio system — nobody chooses a café
from a case study.

**Ecommerce seller.** Listing quality, image sets, comparison graphics,
keywords, A+ export, ads preparation. All marketplace work
`REQUIRES_CONNECTION`; the pipeline still runs to an export a seller can paste.

**B2B.** ICP research, case studies, LinkedIn content, landing pages, lead
generation, CRM integration, AI visibility.

**Logistics.** Quote journey, tracking UX, location and service pages, document
portal, multilingual, B2B prospecting.

**Lead-gen company.** ICP, enrichment, outreach systems, their own funnel
measurement — the one case where Qevik's own capability is the product being
improved.

**Small service business.** Reachability, local visibility, a working enquiry —
and deliberately nothing else. Recommending a CRM to a two-person business is
how a platform proves it is not listening.

## 16. Answers to the twenty questions (§49)

1. Business → `Organization` (new edge). 2. Asset → project → workspace →
organization. 3. Job → project → business. 4. Opportunity + CapabilityOffer,
evidence-gated. 5. Matched on business model, evidence type and availability.
6. Approval, then credit reservation, then a kernel job. 7. `approval/` for
policy, `actions/approval_gate.py` for the act. 8. On `Asset`, extended with
rights. 9. `QuotaLedger`, reserve-before-act, tenant-keyed. 10. `QAResult` gates
that cannot be skipped; READY is unreachable with a failing gate. 11. Publication
target + explicit approval + credential. 12. `Measurement`, business-scoped.
13. By schedule and by publication + window elapsed. 14. Repository-layer filter
on `tenant_id`. 15. Portal: roadmap, jobs, "waiting for you". 16. Readiness →
priorities → capability match → dependency-ordered tasks. 17–20. The same loop —
ecommerce, B2B, media and a game differ only in business model, capabilities and
metrics, which is why `Project` is typed and **"website" is not hard-coded**
(§42).

**No answer requires a second registry.**

## 17. P1 implementation sequence

| Step | Contents | Gate |
|---|---|---|
| **P1.1** | `Business.organization_id` · denormalised `tenant_id` on `Project` · repository-layer filters · isolation tests | 404-not-403 test passes |
| **P1.2** | `Recommendation` · `CapabilityOffer` extending `CapabilitySpec` | A recommendation cannot be built without evidence |
| **P1.3** | **AHS vertical slice**: research → opportunity → recommendation → approval → job → asset → QA → `READY`. No publish, no credits, no external providers | The slice runs end to end and stops at READY |
| **P1.4** | `Measurement` + attribution scale + phrase gate | "Qevik increased" is refused |
| **P1.5** | Readiness + roadmap engine (7/14/30/60/90, Qevik and customer tasks) | Two businesses produce materially different roadmaps |
| **P1.6** | Customer portal, read-only | No cross-tenant read is possible |
| **P1.7** | Credits on the tenant-keyed ledger | Reserve/release reconciles to zero |
| **P1.8+** | Media → website/content → SEO/AI visibility → ecommerce → leads → social → autopilot → white-label | Each gated on the one before |

**P1.1 blocks everything.** Every row written before it needs back-filling.

## 18. Unresolved decisions

1. **Does `Business` move under `Project`, or stay parallel?** I recommend
   parallel — a business outlives any project — but it decides whether research
   is project-scoped or business-scoped, and that is hard to reverse.
2. **Readiness weighting per business model** — who authors the weights, and are
   they visible to the customer? Visible is more honest and more arguable.
3. **Does a customer see raw evidence, including `NOT_VERIFIED`?** Honest, and a
   lot of "we could not tell". My inclination: summarised, detail on demand.
4. **Credits per tenant or per business?** Per tenant is simpler; agencies will
   want per business.
5. **Public audit depth** — enough to be useful, not enough to be the product.
   A commercial call, and easy to widen, very hard to narrow.
6. **Roadmap regeneration cadence** — every research run, or on request? Silent
   regeneration invalidates a plan a customer is working through.
7. **Who owns a generated character** when a customer leaves — Qevik, them, or
   licensed? Affects every asset it appears in and cannot be decided
   retroactively.
8. **Game/app project types (§42)** — the architecture supports them, but the
   capabilities do not exist. Confirm this is direction rather than backlog.
