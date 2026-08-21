# P1 architecture review

A review of `P1_EXECUTION_ARCHITECTURE.md` against the code, written to find
what is wrong with it. No code was written or changed to produce this.

**Five things in that report are wrong or too glib.** They are listed first,
because the rest of the document depends on them.

---

## 0. Corrections to the previous report

### 0.1 The customer entity is not connected to tenancy at all

The report said "reuse `organization/`; §34 is largely present". The code says
otherwise:

```
Business fields: id, name, geography, website, email, phone, identity_keys,
                 sources, metadata, first_seen_at, last_seen_at
```

**There is no `organization_id`.** Nothing anywhere in `opportunity/`,
`outreach/` or `research/` references one. `Membership` carries
`organization_id` and `scope`/`scope_id`, so a tenancy model exists — but no
edge connects a customer's business to a tenant.

`Asset` is worse for this purpose: it is scoped to `project_id`, with no
`business_id`. So a customer's *business* and a customer's *assets* are not
merely un-isolated, they are keyed on two different things, neither of which is
a tenant.

This makes §18's requirement — a customer must never reach another customer's
assets or evidence — **not implementable today**, and it invalidates the
previous report's claim that isolation is "at the query layer, not the view
layer". There is no column to filter on.

This is the single most expensive thing on the list to defer. Every table
written before it is fixed has to be back-filled, and every query written
before it is fixed is wrong in the same way.

### 0.2 A Capability registry already exists

The report called Capability one of three "genuinely missing" concepts.
`models.py` has had `CapabilitySpec` all along — `id`, `name`, `description`,
`version`, `supported_provider_kinds`, `supported_executor_kinds`, `metadata` —
with `Registry.register_action`, `RecipeSpec.capability_id`, and
`ProviderRouter` already selecting providers by capability kind.

What is missing is not the registry. It is the **commercial half** of a
capability: credit cost, approval requirement, QA requirements, publication
target, plan availability, supported business types. That is a smaller and
better-shaped job than "build a capability registry", and it must extend
`CapabilitySpec` rather than sit beside it.

### 0.3 There are two approval mechanisms, and I recommended the wrong one

- `approval/` — `ApprovalService`, `ApprovalPolicy`, `ApprovalScope`,
  `RuntimeApprovalGate`. A policy engine.
- `actions/approval_gate.py` — `Risk`, `ApprovalProposal`, `ApprovalStore`,
  `GateDecision`, `ApprovalOutcome`. A run-pausing gate.

The second one's docstring is a direct argument against how the first is
typically used:

> "The previous boundary was a flag on submission: the operator said
> 'publishing is allowed' before any plan existed… At submission nobody knows
> what will be published, to where, or what it will say — so the consent was to
> a category, not to an act."

For a platform that publishes on a customer's behalf, **consent to a specific
act is the correct model** and consent to a category is the failure mode. The
previous report recommended `approval/` without noticing the gate existed. That
was wrong. See §7.

### 0.4 "Credits just extend QuotaLedger" understates the change

`QuotaPolicy` is keyed on `resource` — "a dotted and specific" *platform*
resource such as `youtube.videos.insert` — with `limit`, `window`, `kind`,
`floor`. **There is no customer, tenant or business dimension anywhere in the
policy or the spend record.**

Adding `LimitKind.CREDIT` gives you a customer-credit *kind* with no customer to
attach it to. Per-customer credits need a tenant key on both the policy and the
spend, which is a change to a live model — related to 0.1 and blocked behind
the same decision.

The reuse recommendation stands; the estimate does not.

### 0.5 The asset graph is more complete than reported

`Asset` also carries `source_asset_ids`, `derived_asset_ids`, `embeddings`,
`transcript`, `ocr_text`, `ai_summary`, `search_index`, `thumbnail_uri`. §11's
content graph is mostly built. What it lacks is **rights**: no copyright status,
no permission link, no provider or prompt record. That is the gap, not the graph.

---

## 1. Canonical lifecycle (§1)

One path. A product family that needs a second one is a product family that has
not been modelled properly.

| # | Transition | Input | Output | Authoritative structure | Event | Permission | Customer approval | Credits | Failure | Rollback |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Public audit → Research | URL | bounded run | `research.Budget` | — (pre-tenant) | none (rate-limited) | no | free, capped | show partial | n/a |
| 2 | Research → Evidence | routes, CMS | `Finding[]` | `website_audit.Finding` | `researched` | `Scope.READ` | no | research units | stage fails alone → `UNVERIFIED` | n/a |
| 3 | Evidence → Opportunity | confirmed findings | `Opportunity[]` | `outreach.opportunity` | derived, not stored | `Scope.READ` | no | none | no evidence → no opportunity | n/a |
| 4 | Opportunity → Recommendation | opportunity + capability | `Recommendation` | **NEW** | `recommended` | `Scope.READ` | no | none | no capability → recommendation withheld | n/a |
| 5 | Recommendation → Approval | recommendation | decision | `actions.ApprovalProposal` | `approval_requested/decided` | member role | **yes, per act** | none | expires → no job | n/a |
| 6 | Approval → Credit reserve | approved rec | reservation | `QuotaLedger` (+tenant) | `credits_reserved` | member role | no | **reserve** | insufficient → job never starts | release |
| 7 | Reserve → Job | reservation | job | `models.Job` | `job_created` | `Scope.EXECUTE` | no | held | — | cancel + release |
| 8 | Job → Execution | job | provider calls | `ProviderRouter` | `job_progressed` | provider creds | no | consumed on success | retry, then FAILED | release unconsumed |
| 9 | Execution → Asset | provider output | `Asset` | `models.Asset` | `asset_created` | — | no | — | partial assets kept, job FAILED | version supersede |
| 10 | Asset → QA | asset | `QAResult` | **NEW** | `qa_completed` | — | no | none | any gate fails → not READY | n/a |
| 11 | QA → Approval (publish) | passed asset | decision | `actions.ApprovalProposal` | `publish_approved` | `Asset.Publish` | **yes** | none | no decision → `READY_TO_PUBLISH` | n/a |
| 12 | Approval → Publish | approved asset | live artefact | `website/targets`, provider | `published` | `Scope.PUBLISH` + creds | already given | consumed | **job FAILS; asset stays READY_TO_PUBLISH** | per class, §29 |
| 13 | Publish → Measurement | published + baseline | `Measurement` | **NEW** | `measured` | `Scope.READ` | no | measurement units | no baseline → `UNKNOWN` attribution | n/a |
| 14 | Measurement → Re-evaluation | measurement | new run | `research.pipeline` | `researched` | `Scope.READ` | no | research units | as row 2 | n/a |

Three properties this table is designed to hold:

- **Credits are reserved at 6 and consumed at 8/12, never at 7.** A job that
  never ran must not have cost anything.
- **Approval appears twice on purpose** (5 and 11), because approving *the plan*
  and approving *the artefact* are different consents. 0.3 is why.
- **Row 12 cannot silently succeed.** If publication fails the job fails, and
  the asset remains `READY_TO_PUBLISH` rather than becoming published-in-name.

---

## 2. Duplicate registry sweep (§2)

Searched across `packages/kernel/atlas_kernel/` for every concept listed.

| Concept | Existing implementations | Authoritative | Duplicate? | Action |
|---|---|---|---|---|
| Job states | `models.JobStatus`; `jobs.JobState`; `media.providers.JobState`; `research.JobState`; `control.sales.JOB_STATES` | `models.JobStatus` (execution) + `sales.JOB_STATES` (customer view) | **No** — five subjects | Document the mapping; forbid a sixth |
| Asset states | `Asset` has no state field; approval/publication implied | none yet | No | Add `approval_state`/`publication_state` to `Asset` |
| Approval states | `approval.ApprovalState`; `actions.ApprovalOutcome` | **`actions/approval_gate.py`** for acts; `approval/` for policy | **Yes, overlapping** | Layer them — see §7 |
| Permissions | `auth.Scope` (7); `organization.Permission` (14+) + `BuiltinRole` | `organization` for tenants; `auth.Scope` for operators | **No** — different subjects | One-way resolver |
| Quotas | `quota.QuotaLedger` | `quota` | No | Extend with a tenant key |
| Credits | — | — | No | New `LimitKind`, same ledger |
| Plans | `agents.Plan`; `quota.Plan` (both = *a plan of work*) | neither | **Name collision only** | Commercial plans must not be called `Plan` |
| Capabilities | `models.CapabilitySpec` + `Registry` + `RecipeSpec` | **`CapabilitySpec`** | No | Extend with commercial fields (0.2) |
| Providers | `providers.ProviderAdapter/Manager`; `router.ProviderRouter`; `media.providers.LongRunningProvider` | `ProviderSpec` + `ProviderRouter` | **No** — sync vs long-running | Keep both; one spec |
| Organizations | `organization/` | `organization` | No | **Wire `Business` to it (0.1)** |
| Users | `auth.User`; `organization.Identity` + `Membership` | `Identity` for customers; `auth.User` for operators | **No** | Resolver, one direction |
| Customer accounts | — (`Business` is not an account) | — | No | An account is an Organization; a Business is a subject |
| Businesses | `opportunity.Business` | `Business` | No — enforced by test | Never a second one |
| Recommendations | — | — | No | **New** |
| Opportunities | `outreach.opportunity`; `opportunity.models.Opportunity` (pipeline stage) | **Two meanings** | **Yes, semantic** | Rename in prose; do not merge the code |
| Events | `BusinessEvent`; `AtlasEvent`/`event_bus`; `approval.events`; `organization.events` | `BusinessEvent` for business memory; `AtlasEvent` for runtime | No | Business-facing facts go to `BusinessEvent` |
| Audit records | `organization.audit.AuditService` (append-only) | `AuditService` | No | Reuse for job/approval trail |
| Media jobs | `media/providers` + `media/publishing.py` | `media` | No | Wrap in a kernel Job |
| Publishing | `website/targets/base.py`; `actions/handlers.py`; `media/publishing.py` | **Three paths** | **Yes, functional** | One `PublicationTarget` protocol over all three |
| Analytics / measurement | `observability.py`, `telemetry.py` (system); `cluster.WorkerMetrics` | none for business outcomes | No | **New** — must not live in telemetry |
| "demos" | `atlas_kernel/demos.py` (demo projects); `outreach/demos.py` (sample sites) | both, different things | **Name collision** | Rename one before either is public |

**Genuinely absent:** Recommendation · Measurement · Credit · Tenant link ·
Campaign · Lead. Everything else exists in some form.

---

## 3. Capability architecture (§3)

Extend `CapabilitySpec`; do not replace it. The existing fields carry the
technical half. The commercial half is added as a sibling record so the kernel
spec stays free of pricing:

```
CapabilityOffer
  capability_id      -> CapabilitySpec.id      (existing)
  version                                       (existing on the spec)
  requires_providers  [kind]                    (existing: supported_provider_kinds)
  requires_integration  none | connection_id
  availability        AVAILABLE | REQUIRES_CONNECTION | REQUIRES_APPROVAL | UNAVAILABLE
  requires_permission  organization.Permission
  approval            never | act | policy
  inputs / outputs     schema refs
  estimated_cost       provider units
  credit_cost          declared, never computed in execution
  qa_layers            [layer]
  publication_target   none | website | marketplace | social | email | ads
  measurement          [metric]
  business_types       [model] from research.classify
  plans                [LIST|PRO|ADVANCED|ENTERPRISE]
```

**On the proposed vocabulary: it is roughly right but wrongly shaped in two
places.**

`social.publish` and `amazon.listing.create` are not capabilities in the same
sense as `image.generate` — they are *publication targets* reached by a
capability. Modelling them as capabilities means every one carries its own
approval, credential and QA logic, and they will drift. Better:
`content.generate` → asset → `publish(target=social)`, where the target owns the
credential and the platform rules.

`crm.manage` is not a capability at all — it is a surface. Capabilities are
things a job can *do*; a CRM is a place records live.

Otherwise the list is sound. Note that a capability whose `availability` is
`REQUIRES_CONNECTION` still produces recommendations — it just cannot produce
jobs. That distinction is what lets Qevik sell Amazon work before Amazon access
exists, honestly.

## 4. Recommendation architecture (§4)

```
Opportunity ──► Recommendation ──► Capability ──► Job
```

A `Recommendation` is the join, and it carries: the evidence ids it rests on,
what was found, why it matters, the capability that would execute it, expected
inputs and outputs, estimated and credit cost, expected measurement, approval
requirement, risk, and confidence.

**Evidence cannot be bypassed** because the constructor takes evidence ids and
an empty list raises — the same guard `Opportunity` already uses, for the same
reason. A recommendation without evidence is a sales pitch.

Two rules the previous report did not state:

- **A recommendation may exist with no available capability.** It is then a
  recommendation to buy an upgrade or connect an account, not a dead end.
- **A recommendation may be declined permanently.** "Not for us" is a fact about
  the business worth remembering; re-recommending it every cycle is how an
  automated system becomes noise.

## 5. Customer portal (§5)

**A new application, sharing the kernel and the API, not the console.**

The console is an operator tool: 1,100 businesses, evidence tables, refuted
findings, raw scores. Role-gating it would mean every future console change
carrying a "does a customer see this" question, and the first time somebody
forgets, a customer sees another customer's row. A separate app makes the
isolation boundary a deployment boundary.

Sections gated by plan, each capability showing **Available · Requires upgrade ·
Requires connection · Requires approval · Coming soon** — never hidden, because
a customer who cannot see what exists cannot buy it.

The section that earns the portal is **"Waiting for you"**: approvals, assets to
review, connections to authorise, credits to top up. A customer's real question
is not what the platform does; it is what is stuck on them.

## 6. Plans (§6) — with the commercial logic

| | LIST | PRO | ADVANCED | ENTERPRISE |
|---|---|---|---|---|
| Research | homepage + shallow crawl | full crawl + CMS | + AI visibility, competitors | + scheduled re-evaluation |
| Businesses | 1 | 3 | 15 | unlimited |
| Opportunities | view | view + recommend | + capability matching | + custom rules |
| Website | — | 1 build | rebuilds + optimisation | multi-site |
| SEO / AI visibility | audit | audit + recommend | optimise | optimise + monitor |
| Content / image | — | small monthly | monthly + purchase | pooled |
| Video / social | — | — | 1 account | up to 7, then negotiated |
| Ecommerce / marketplace | — | — | Amazon | Amazon + Noon |
| Ads | — | — | preparation | preparation + execution |
| Leads / CRM | — | — | leads | leads + CRM + enrichment |
| Autopilot | — | — | assisted | configurable |
| API / white-label | — | — | API | API + white-label |

**Logic, not arbitrary numbers.** LIST exists to make the public audit
convertible — one business, real findings, nothing executed. PRO is the first
plan that *does* something, so it gets one website and content. ADVANCED is
where a business stops being a website and starts being an operation, which is
why marketplace, leads and assisted autopilot appear together. ENTERPRISE is
distinguished by *pooling and delegation* — multiple brands, teams, API,
white-label — not by bigger numbers.

The number that matters commercially is **businesses**, not credits: it is the
one a customer can predict, and agencies self-select into ENTERPRISE on it.

## 7. Approval and autopilot, corrected (§17)

Layer the two mechanisms rather than choosing one:

- `approval/` (`ApprovalPolicy`, modes `always`/`never`/`scoped`) decides
  **whether this class of act needs a human** — the policy.
- `actions/approval_gate.py` (`ApprovalProposal`, `Risk`, `GateDecision`)
  handles **this specific act, with its actual content, pausing the run** — the
  consent.

Policy chooses; the gate obtains. Neither is redundant, and using only the
policy is exactly the failure its own docstring describes.

Autopilot defaults, deliberately conservative:

| | LIST | PRO | ADVANCED | ENTERPRISE |
|---|---|---|---|---|
| Research, drafts, internal QA | auto | auto | auto | auto |
| Generate assets (unpublished) | — | auto | auto | auto |
| Consume credits | per job | per job | pre-authorised per workflow | pooled |
| Publish website | — | approve | approve | policy |
| Publish social / send email | — | — | approve | policy + daily cap |
| Marketplace changes | — | — | approve | approve |
| Spend ad budget | — | — | approve | approve + cap + kill switch |

**Nothing public and nothing that spends is ever auto-approved below
ENTERPRISE**, and even there it is bounded and reversible. Autopilot is a
bounded pre-authorisation, never an absence of consent.

## 8. Credits (§7)

`reserve → execute → consume`, and `reserve → fail → release`. The existing
ledger already reserves before acting; what it needs is the tenant key (0.4).

- **Partial jobs** consume for completed steps, release the rest.
- **Retries** are covered by the original reservation — a retry that re-reserves
  charges twice for one outcome.
- **Cancellation** releases everything unconsumed.
- **Provider failure** releases; the customer does not pay for our outage.
- **Provider price change** is absorbed by the declared `credit_cost` — the
  customer's price is fixed at reservation, and margin is our problem.
- **Concurrency** is handled by reservation, which is the whole point of
  reserving.
- **Rollover and expiry** are policy on the allowance, not on execution.

Usage measurement stays separate from billing. Every credit movement is an event,
so a balance is reconcilable from history rather than trusted as a column.

## 9. Public audit (§8)

Free: one bounded research run per domain per day, cached, rate-limited per IP,
robots-obeying. Findings, opportunities, and what Qevik could do about them.

Credit-consuming after sign-up: AI-visibility queries (each costs a provider
call), competitor comparison, deep crawls, and anything that executes.

Never exposed: internal prompts, scoring weights, raw competitor research,
credentials, other customers' anything, and any claim the evidence does not
support. `NOT_VERIFIED` is shown as `NOT_VERIFIED`. The prospect's first act is
to check, and the audit's value is entirely that it survives checking.

## 10. AI visibility (§9)

A research stage, not a second engine. Per measurement: query · engine ·
timestamp · mentioned · **position only where the engine actually provides one**
· citation · competitors · sentiment · entity recognised · confidence ·
methodology · limitations.

Distinguish `mention` / `citation` / `recommendation` / `position` as different
observations. An assistant naming a business is a mention; linking it is a
citation; ranking it is a position only where a rank exists. **Never convert one
into another.** Google gives positions; assistants generally do not; the record
says so.

Loop: measure → diagnose → recommend → optimise → re-measure. This is the
clearest re-evaluation case in the platform because the measurement is cheap and
repeatable, which is a good reason to build it early.

## 11. Entity graph (§10)

**Yes, but as a kernel primitive and not a graph database.** Business → brand →
website → profiles → services → products → locations is a small, shallow,
mostly-tree structure. `BusinessEvent` plus a typed `EntityLink` table answers
every query in the brief. A graph database earns its place at multi-hop queries
over millions of edges, and nothing here is that.

Shared, not owned by SEO or AI visibility — both read it, research writes it,
and the website factory uses it to emit consistent structured data. That
consistency *is* the entity optimisation.

## 12–14. Media, character, social factories (§11–§13)

The asset graph is largely built (0.5). Add to `Asset`: `copyright_status`,
`permission_ref` (into media permission), `provider`, `prompt_ref`,
`approval_state`, `publication_state`. **Permission is inherited by derivation** —
a crop of a photograph we may not publish is unpublishable, and that has to be
enforced in the model rather than remembered.

A `Character` is a reusable definition (identity, appearance, wardrobe, voice,
accent, camera language, shot types, movement, lighting, environment,
continuity, negative constraints) with explicit rights: **customer-owned ·
Qevik-owned · licensed · generated-original**. Rights travel to every asset the
character appears in; a licensed character whose licence lapses must be
traceable to every video it is in.

Social: accounts have declared ownership, a character, pillars, a calendar,
approval rules. Where a platform's API cannot publish, the job ends at
`READY_TO_PUBLISH`. Nothing undisclosed or deceptive is designed.

## 15. Ecommerce, Amazon, Noon (§14)

Full lifecycle with marketplace QA and policy gates. **What happens with no API
access** is the important part, because that is today's state: the pipeline runs
to `READY_TO_PUBLISH` and produces an export — the listing, images, keywords,
A+ blocks — that a seller can paste in. That is genuinely valuable and it is
honest, and it means the ecommerce factory is buildable before any marketplace
relationship exists.

## 16. Leads and CRM (§15)

**Integrate, do not build.** The recommendation is not made from convenience:
Qevik's CRM would need pipelines, activities, permissions, imports, dedup,
reporting and a mobile view before it matched what a customer already has, and
none of that is differentiating. Qevik keeps the *lead* — with provenance,
enrichment, confidence and source — and pushes to whatever CRM the customer
uses. Where they have none, the existing prospect workspace is already a
serviceable pipeline view.

Inferred or scraped personal data is never recorded as verified fact; it carries
source and confidence like every other observation.

## 17. Measurement (§16)

A first-class object, and genuinely new. `Metric · Baseline · Intervention ·
Window · Observed · AttributionConfidence · Evidence`.

Attribution is a five-value scale, and the system may never skip a level:

`OBSERVED` → `ASSOCIATED` → `ATTRIBUTED` → `EXPERIMENTALLY_SUPPORTED` → `UNKNOWN`

Most results are `OBSERVED`. `ATTRIBUTED` requires a plausible mechanism and no
competing explanation. `EXPERIMENTALLY_SUPPORTED` requires a control, which
almost nothing will have. **`UNKNOWN` is a legitimate outcome** and must be
reportable without embarrassment, exactly as `NOT_VERIFIED` is in research.

Enforce the language the way outreach overclaiming is enforced: a phrase gate
that refuses "Qevik caused" or "increased by X because" unless the attribution
level supports it.

## 18. Security and tenant isolation (§18)

At 100, 1,000 and 10,000 customers the answer is the same and it starts with
0.1: **`Business` gets an `organization_id`; `Asset` gets a `business_id`.**
Until then isolation is aspirational.

Then: every query filters on tenant at the repository, not the view; provider
credentials live in the vault, referenced by name, never in a job payload, an
asset, a log or an API response; generated media, leads, prompts and reports are
tenant-scoped; the append-only audit records who did what; deletion and
retention are per-tenant policy.

One test decides whether this holds: a customer session requesting another
tenant's business id gets a 404, not a 403 — because a 403 confirms the record
exists.

## 19. Case studies (§19)

Materially different because the evidence is:

**AHS.** Position `STRONG`, speed `FAST`, journey breaks at `call`, 34 orphaned
pages, 32 picture-only pages, 170 photographs, a blog of four same-day posts
against a 501-item library, no hreflang. Recommendations: portfolio system, AI
visibility, one-tap contact, Arabic, dormant-editorial revival. **No website
rebuild is recommended, because the site is fast and the business is strong.**
That is `STRONG BUSINESS + LIMITED WEBSITE OPPORTUNITY` falling out of the
evidence rather than being written by hand.

**Coffee shop.** Local visibility, menu and order journey, hours, map, lifestyle
media, loyalty. No case-study system — nobody picks a café from a portfolio.

**Ecommerce seller.** Listing quality, image sets, keywords, A+ export, ads
preparation. Everything marketplace-side `REQUIRES_CONNECTION`.

**B2B.** Capability, proof, RFQ journey, lead generation, content answering
buying questions.

**Logistics.** Quote and tracking journeys, document portal, multilingual.

**Lead-gen company.** ICP, enrichment, outreach systems, their own funnel.

**Small service business.** Reachability, local visibility, a working enquiry —
and deliberately nothing else. Recommending a CRM to a two-person business is
how a platform proves it is not listening.

## 20. Commercial architecture (§20)

The sentence a customer should be able to say: *"Qevik researches my business
continuously, tells me what is worth doing and why, does the work I approve,
and shows me what changed."* Capabilities are discoverable inside that, never
presented as a menu of tools.

---

## 21. Final architectural challenge

### A. Build first
1. `Business.organization_id` and `Asset.business_id` (0.1) — everything else
   is built wrong without them.
2. `Recommendation` — evidence-gated, joining opportunity to capability.
3. `CapabilityOffer` extending `CapabilitySpec` (0.2).
4. The QA gate framework — one `QAResult`, gates that cannot be skipped.
5. Job wiring: recommendation → approval → reserve → kernel job → asset → QA.

### B. Explicitly do not build yet
Credits and billing (needs A1) · the customer portal beyond read-only ·
marketplace integrations · social publishing · a CRM · autopilot beyond
"generate but do not publish" · anything 3D · white-label.

### C. Reuse
`Business` · `BusinessEvent` · `Finding` · the research pipeline · the
opportunity engine · `CapabilitySpec`/`Registry`/`RecipeSpec` ·
`ProviderSpec`/`ProviderRouter` · `models.Job`/`queue`/`state_machine` ·
`Asset`/`asset_system` · `approval/` **and** `actions/approval_gate.py` ·
`QuotaLedger` · `organization/` · `AuditService` · `differentiation.py` · the
media-permission gate.

### D. Refactor before P1
1. Wire tenancy (A1) — a change to two live models, done once, early.
2. Unify the three publish paths behind one `PublicationTarget` protocol.
3. Rename one of the two `demos` modules.
4. Document the five job-state vocabularies and the mapping; add the test that
   forbids a sixth.
5. Decide `Opportunity`'s two meanings in prose before the portal exposes either.

### E. Expensive to change later
1. **Tenancy keys.** Every row written before them needs back-filling.
2. **Credit reservation semantics.** Changing when a credit is consumed after
   customers have balances means reconciling real money.
3. **Approval granularity.** Moving from category consent to act consent later
   means re-obtaining every consent.
4. **Asset provenance and rights.** Unrecordable retroactively — an asset whose
   origin was never captured never gets one.
5. **Attribution vocabulary.** Once a customer has seen "Qevik increased your
   leads 43%", walking back to "observed" reads as a retraction.
6. **Public-audit depth.** Easy to widen, very hard to narrow.

### F. Minimum viable P1
One business, one capability, end to end: **AHS → "Work nobody can find" →
`website.portfolio_upgrade` → recommendation → approval → job → assets → QA →
`READY_TO_PUBLISH`.** No credits, no portal, no publishing. If that path is
clean, every other capability is a plug-in. If it is not, nothing downstream is
worth building.

### G. Twelve-month architecture
The loop running unattended for a set of customers: continuous research,
recommendations that arrive without being asked for, approved work executing
against real providers, measurement closing back into research, and a portal
where a customer approves and watches. Websites, content, images, SEO and AI
visibility as working capabilities; marketplaces, ads, social and leads as
capabilities gated on connections. Agency and white-label as configuration.

### H. How this fails
**Technically:** deferring tenancy; provider costs outrunning credit pricing;
one runaway crawl damaging a prospect's server and the reputation with it; a
publishing bug that posts to a customer's real accounts; QA gates that become
advisory under delivery pressure.

**Commercially:** the trap this whole design exists to avoid — becoming a menu of
tools, where a customer buys "video" and Qevik becomes a worse Fiverr. Also:
selling execution to businesses that needed advice; one fabricated causal claim
destroying the credibility of every honest measurement; and a platform whose
recommendations are all the same because the research is shallow.

### I. Three things that would be genuinely hard to copy
1. **The honesty machinery.** Three-state evidence, the refuted state, overclaim
   gates, `NOT_VERIFIED` surviving all the way to a customer, and a research
   engine that can conclude *"strong business, limited opportunity"*. Competitors
   optimise for finding fault because it sells; the discipline not to is
   architectural here and cannot be retrofitted onto a system that has been
   manufacturing weaknesses.
2. **The closed loop.** Research → recommend → execute → measure → re-research,
   on one immutable business id with an append-only memory. Most competitors
   have an audit tool *or* an agency. Neither can answer "what changed after we
   did it", because neither holds the baseline.
3. **Evidence-to-execution provenance.** Every asset traces to a job, to an
   approval, to a recommendation, to an opportunity, to a finding, to the page
   it was observed on. That answers "why did you do this and what did it change"
   in one query, which is the question agencies cannot answer and the reason
   they get fired.
