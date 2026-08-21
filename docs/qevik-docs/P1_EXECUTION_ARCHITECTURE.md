# P1 — execution and growth architecture

Required by §43, before any implementation. No code, no migration, no provider
connection, no production change was made to produce it.

---

## 1. Executive architecture

**P1 is mostly assembly, not construction.** The inspection below found that
roughly two-thirds of what this brief describes as new already exists in the
kernel: an approval engine with policy modes, a quota ledger that reserves
before acting, an asset model carrying full provenance, a provider router that
scores on cost, quality, locality and VRAM, a multi-tenant organization layer
with roles and per-tenant branding, and an append-only audit service with no
update or delete.

What genuinely does not exist is the connective tissue: a **Recommendation**
(the human-readable bridge between an opportunity and a job), a **Capability
registry** (what Qevik can actually execute, and under what conditions), and
**Measurement** (what changed afterwards). Those three are the P1 work. Almost
everything else in §4's twenty-four families is a capability plugged into a loop
that would then already exist.

The one-sentence answer to §42's "why is this one platform":

> Qevik researches a business continuously, derives evidence-backed
> opportunities, recommends actions, executes the approved ones, measures what
> changed, and re-researches. Every product family is a capability inside that
> loop, and none of them is reachable except through it.

That is also the structural defence against becoming a tool collection: a
capability with no opportunity that justifies it has no route to a job.

---

## 2. Existing-system assessment (§3 — mandatory)

| # | Component | Where | Reuse / extend / do not duplicate |
|---|---|---|---|
| 1 | **Business** | `opportunity/models.py` | **Reuse unchanged.** Immutable id, deliberately not called Prospect, enforced by `test_one_customer_entity.py`. Every P1 factory references this id. |
| 2 | **BusinessEvent** | `opportunity/models.py` | **Reuse and extend by `kind`.** `kind` is a plain string under a `factory` namespace precisely so a new factory adds kinds without editing the module. Jobs, assets, approvals and measurements all become events here. |
| 3 | **Evidence** | `opportunity/website_audit.py` (`Status`, `Category`, `Finding`) | **Reuse unchanged.** Three states plus REFUTED. Every P1 stage emits `Finding`. |
| 4 | **Research engine** | `research/` — 11 stages, `pipeline.research()` | **Reuse and extend by stage.** Adding AI-visibility research is one more stage, not a second engine. |
| 5 | **Opportunity engine** | `outreach/opportunity.py` — 14 rules, 49 products, 8 families | **Extend by rule only.** The dataclass, `derive()` and ranking stay. New evidence produces new rules. |
| 6 | **Demo system** | `outreach/demos.py` — one registry, 6 classes, overclaim gate | **Reuse.** `CAPABILITY_DEMO` already covers §33's 3D work. |
| 7 | **Job queue** | `models.JobStatus`, `queue.py`, `jobs/`, `orchestrator.py`, `state_machine.py`, `workflow_engine.py` | **Reuse the kernel's.** See the conflict in §3.1 — there are now five job-state vocabularies and P1 must not add a sixth. |
| 8 | **Media permission** | `control/sales.py` — 5 states, event-sourced, `MEDIA_ALLOWS_ORIGINALS` | **Reuse as the hard gate.** Every image and video capability reads it. |
| 9 | **QA** | `infra/differentiation.py`, browser harnesses, `verify()` in the AHS generator | **Extend into layers.** The pattern exists; §24's twelve layers formalise it. |
| 10 | **Dashboard** | `control/sales.py` + `apps/control/index.html` | **Reuse. This is the ADMIN layer** of §28. The customer portal is a separate surface, not a fork of this one. |
| 11 | **Auth / scopes** | `auth/` — 7 scopes, sessions, `requires()`; `organization/` — 14+ permissions, 7 roles, memberships, branding | **Two vocabularies. See §3.2.** |
| 12 | **Provider abstraction** | `providers.py` (`ProviderAdapter`, `ProviderManager`), `router.py` (`ProviderRouter`), `models.ProviderSpec` (cost, quality, VRAM, `is_local`), `media/providers/base.py` (`LongRunningProvider`) | **Reuse. Do not write a second provider layer.** §36's twelve interfaces are `kind` values on the existing spec. |
| 13 | **Scoring / ranking** | `outreach/scoring.py` (100-point commercial score), `opportunity.rank` | **Reuse.** Plan and credit logic must not re-rank. |
| 14 | **Production constraints** | append-only events, no second customer entity, no outbound clients in `sales.py`, no auto-send | **Binding on everything below.** |
| — | **Approval engine** | `approval/` — `ApprovalScope`, `ApprovalState`, `ApprovalPolicy`, `ApprovalPolicyMode`, `gate.py` | **Reuse — this is §21 and §23 already built.** |
| — | **Quota ledger** | `quota/` — `LimitKind`, `QuotaWindow`, `QuotaLedger` reserve-before-act | **Extend for credits. See §3.3.** |
| — | **Asset + provenance** | `models.Asset` (`parent_asset_id`, `version`, `content_hash`, `run_id`, `job_id`), `asset_system.py` | **Reuse — this is §10's provenance requirement, already met.** |
| — | **Audit service** | `organization/audit.py` — append-only, no update, no delete | **Reuse for §22's audit trail.** |
| — | **Tenancy + white-label** | `organization/` — `Membership`, `PolicySet`, `Branding` | **Reuse — §34 is largely present.** |

### 3.1 Conflict: five job-state vocabularies

| Vocabulary | Where | Subject |
|---|---|---|
| `JobStatus` (queued/running/paused/failed/completed/cancelled) | `models.py` | Kernel execution jobs |
| `JobState` (running/succeeded/failed/lost) | `jobs/models.py` | Local OS processes, derived from disk |
| `JobState` (provider states) | `media/providers/base.py` | One provider's long-running render |
| `JobState` (QUEUED/RESEARCHING/READY/PARTIAL/FAILED/CANCELLED) | `research/job.py` | A research run |
| `JOB_STATES` (10, uppercase) | `control/sales.py` | The customer-visible build queue |

**Recommendation.** These are not duplicates — they describe different subjects
at different layers, and collapsing them would be worse than keeping them. Make
that explicit rather than accidental:

- `models.JobStatus` stays **authoritative for kernel execution**. P1's Job is a
  kernel job.
- `control/sales.JOB_STATES` stays **authoritative for what a customer sees**,
  because it is the only one whose stages a customer understands (`DESIGNING`,
  `MEDIA`, `REVIEW`) and it already holds a live record in `CANCELLED`.
- The other three stay scoped to their subject and are never rendered to a
  customer.
- **P1 adds no sixth vocabulary.** A build job is a kernel job whose
  customer-facing projection is one of the ten.

The mapping is one function, tested both ways, and it is the only place the two
vocabularies meet.

### 3.2 Conflict: two permission vocabularies

`auth.Scope` — 7 coarse scopes (`read`, `execute`, `publish`, `communicate`,
`financial`, `destructive`, `admin`) — guards the control API today.
`organization.Permission` — 14+ resource-action pairs (`Asset.Publish`,
`Approval.Override`, `Policy.Manage`…) with 7 `BuiltinRole`s and `Membership`
scoping — is the richer model and already multi-tenant.

**Recommendation: `organization` becomes authoritative for the customer portal
and agency layers; `auth.Scope` remains authoritative for the operator console.**
They answer different questions — "what may this operator do to Qevik" versus
"what may this member do within this tenant" — and merging them would put
customer roles into the same enum that guards `admin`. The seam is a resolver
that maps a `Membership` to the `Scope` set a request carries. One direction
only: a customer role can never widen an operator scope.

### 3.3 Conflict: quota vs credits

`quota/` measures **platform limits** — a provider's daily unit allowance, a
spend ceiling — and reserves before acting. §25 wants **customer credits**:
included quota, consumed, remaining, overage, purchases, refunds, admin grants.

These are the same mechanism at two levels: what a provider will allow us, and
what a customer has bought. **Recommendation: extend `QuotaLedger` with a
customer-scoped `LimitKind.CREDIT` rather than building a parallel ledger.**
Reserve-before-act is exactly the property a credit system needs — it is what
stops a job consuming credits it cannot pay for halfway through — and
reimplementing it would produce two ledgers that disagree.

Billing stays out. Credits are a usage abstraction; money is a separate concern
that reads the ledger.

---

## 4. Domain model (§2)

```
Business ──1:N── BusinessEvent          (append-only, the whole memory)
   │
   ├── Research run ──► Finding[]        (evidence: PRESENT/ABSENT/UNVERIFIED/REFUTED)
   │                        │
   │                        ▼
   │                   Opportunity       (evidence-gated; no evidence, no opportunity)
   │                        │
   │                        ▼
   │                  Recommendation     ◄── NEW. Opportunity + Capability + cost
   │                        │                 + what it needs from the customer
   │                        ▼
   │                    Approval          (existing engine: policy → auto or human)
   │                        │
   │                        ▼
   │                      Job             (kernel job; customer-facing 10-state projection)
   │                        │
   │              ┌─────────┼─────────┐
   │              ▼         ▼         ▼
   │          Provider   Provider  Provider   (existing router: cost/quality/local)
   │              └─────────┼─────────┘
   │                        ▼
   │                     Asset[]          (existing model; provenance already built in)
   │                        │
   │                        ▼
   │                    QA layers         (§24; a job is READY only after these)
   │                        │
   │                        ▼
   │                  Publication         (or READY_TO_PUBLISH where we cannot publish)
   │                        │
   │                        ▼
   └──────────────────► Measurement       ◄── NEW. Baseline, window, observed change
                            │
                            ▼
                      Re-evaluation ──► back to Research
```

**Capability** is the missing noun that makes the graph work: an opportunity says
*something could be better*, a capability says *we can do this, using these
providers, at this cost, requiring this connection and this approval*. A
recommendation is the join of the two. Without it, opportunities have no route
to execution and capabilities have no justification for running.

---

## 5. Execution lifecycle

Recommendation → Approval → Job → steps → providers → assets → QA → publication
→ measurement. Each arrow is a `BusinessEvent`; nothing is a mutable status
column, so the whole history is reconstructable and a funnel is derived rather
than stored.

## 6. Job architecture (§22)

Reuse the kernel's `Job`, `queue.py`, `state_machine.py`, `orchestrator.py`.
What P1 adds is per-job requirements, not a new engine: **idempotency key**
(business + capability + input hash, so a retried job does not publish twice),
**child jobs** (a website job spawning image jobs), **compensating action** for
irreversible steps, and **an audit event per transition**.

`CANCELLED` remains terminal and no historical event is rewritten.

## 7. Approval architecture (§23)

`ApprovalPolicyMode` already has `always` / `never` / `scoped`, which is exactly
§21's MANUAL / AUTOPILOT / ASSISTED under different names. **Recommendation:
keep the existing names** — they are in the kernel and in tests — and present
the three plan-facing labels in the portal only.

Always requiring approval: publishing anywhere public, sending marketing email,
spending advertising budget, marketplace listing changes, using customer media,
brand changes. Auto-approvable: research, internal reports, drafts, crops,
internal QA. Autopilot is a bounded pre-authorisation — scope, budget, daily
limit, kill switch, audit trail — never unrestricted execution.

## 8. QA architecture (§24)

Twelve layers, each a gate rather than a report. **A job may not reach READY
because generation succeeded** — that is the existing rule ("done" is not a job
state) applied to assets. Layers: schema · content · brand · visual · browser ·
link · accessibility · SEO · marketplace · policy · publication · post-publication.

Existing harnesses already implement several: `differentiation.py` (brand/visual
distinctness), the browser QA harness, the generator's `verify()`. P1 formalises
them behind one `QAResult` so a gate cannot be skipped silently.

## 9. Asset architecture (§10, §11)

Reuse `models.Asset`. It already carries `parent_asset_id`, `version`,
`content_hash`, `job_id`, `run_id` — an original → edited → generated chain is
expressible today. P1 adds the fields the content graph needs (`topic`,
`brand`, `campaign`, `approval_state`, `publication_state`) and one hard rule:
**an asset derived from customer media inherits its permission**, so a crop of a
photograph we may not publish is itself unpublishable.

## 10. Provider architecture (§36)

Reuse `ProviderAdapter` / `ProviderManager` / `ProviderRouter`. §36's twelve
interfaces become `kind` values, not twelve new abstractions. `ProviderSpec`
already scores cost, quality, VRAM and locality, which is what "support future
local providers without redesigning" requires.

Marketplace and advertising providers additionally declare availability, since
we cannot assume access:

`CAPABILITY_AVAILABLE` · `REQUIRES_CONNECTION` · `REQUIRES_APPROVAL` ·
`UNAVAILABLE`

**No external API is assumed to exist anywhere in this document.** Amazon SP-API,
Noon, Google Ads, Meta and every social publishing API are modelled as
`REQUIRES_CONNECTION` until a credential is present and verified.

---

## 11. Customer portal (§5, §27)

A separate surface from the operator console, reading the same events. It shows
only what that tenant may see, and every capability carries a state so nothing
is a dead control: **Available · Requires upgrade · Requires connection ·
Requires approval · Coming soon**.

Sections: Research · Opportunities · Recommendations (approve/reject) · Jobs ·
Assets (review/approve/publish) · Reports · Credits · Waiting for you.

"Waiting for you" is the one that earns the portal. A customer's real question
is not *what can this do* but *what is stuck on me*.

## 12. Public audit (§6)

`qevik.ai` → enter a URL → the research engine runs bounded → evidence,
opportunities, and what Qevik could do → plans → sign-up.

The engine already produces this in ~30 seconds within budget. Constraints:
never expose credentials, competitor confidential data, invented rankings or
unverified opportunities; show `NOT_VERIFIED` honestly. A public audit that
overclaims is worse than none, because the first thing a prospect does is check.

Abuse bounds: one research run per domain per day, cached, rate-limited per IP,
and the same robots/politeness rules — a public form must not become a way to
point our crawler at someone.

## 13. AI search / LLM visibility (§7, §8)

A first-class **research** category — a new stage in the existing pipeline, not
a new engine.

Every measurement records: query · engine · timestamp · mentioned · position
**only if the provider actually exposes one** · citation · competitors ·
confidence · methodology · limitations.

**The hard rule: never convert "mentioned" into a rank.** An assistant naming a
business is not a position. The record is:

```
query: "best catering company Dubai"
chatgpt:  mentioned=true  position=UNAVAILABLE  cited=<url>  competitors=[A,B,C]
google:   organic_position=7
```

Two different measurements about two different systems, neither converted into
the other.

Optimisation (§8) is kept separate from SEO because they diverge: structured
data, entity consistency, organisation/product/service entities, authorship,
citations, internal linking, topical coverage, machine-readable product data,
knowledge-graph relationships. Some SEO wins do nothing for LLM visibility and
vice versa; merging the categories would hide that.

Works for companies *and* products — the subject of a query is a parameter.

## 14. Website factory (§9)

Research → sitemap → IA → design system → copy → assets → build → automated QA →
browser QA → approval → deploy → analytics → re-evaluate.

The AHS generator is the proof this works: 102 routes, two languages, generated,
QA'd and deployed. The lesson to carry is the one that produced
`differentiation.py` — **one generator across sites converges; a generator per
site does not.** So the factory supplies shared *systems* (tokens, components,
QA, deploy) and per-business *structure*, and the differentiation gate fails the
build when two sites converge. Recolouring does not pass.

## 15. Content, image, character and video factories (§10–§13)

One content graph: a research topic yields article, images, shorts, social
posts, carousel, email, landing page, ad creative — each an `Asset` with a
`parent_asset_id` back to the topic, so provenance is the existing mechanism.

**Character** is a reusable definition (identity, appearance, clothing, voice,
personality, language, accent, camera language, shot types, lighting,
environment, continuity, negative constraints) referenced by many videos, never
re-described per video.

**Social (§13):** accounts have an owner, a character, pillars, a schedule and
approval rules. Where autonomous publishing is unavailable a job ends at
`READY_TO_PUBLISH` — the architecture never pretends a post went out. No
undisclosed or deceptive behaviour is designed; every account has declared
ownership and must satisfy its platform's rules.

## 16. Ecommerce, Amazon, Noon (§14, §15)

Full lifecycle with marketplace QA and policy checks as gates. All marketplace
capabilities start `REQUIRES_CONNECTION`; none assumes seller permissions, API
access or advertising access. Marketplace rules are verified at implementation
time, not encoded from memory.

## 17. Advertising (§16)

**Preparation and execution are different capabilities with different approval
requirements.** Preparation — audience, keywords, creative, landing page — is
auto-approvable. Execution spends money and requires a credential, an explicit
approval, and a budget bound. Never promise ROAS; report measured performance.

## 18. Leads and CRM (§17, §18)

ICP → accounts → contacts → enrichment → qualification → scoring → outreach →
CRM → measurement. **Provenance per lead**, and inferred or scraped personal data
is never recorded as verified fact — it carries its source and confidence, the
same three-state discipline as website evidence.

Qevik's CRM stays deliberately small: lead, company, contact, opportunity,
stage, owner, activity, source, campaign, score, next action. It references the
same `Business` id. Beyond pipeline hygiene, integrate rather than rebuild
Salesforce.

## 19. Email (§19) and affiliate (§20)

Transactional and marketing are separate capabilities with separate approval and
separate sending paths. No uncontrolled bulk sending: segmentation, approval,
unsubscribe and rate bounds are gates, not settings. Affiliate relationships are
explicit internally and disclosed in the publishing context; no fabricated
reviews or personal use.

## 20. Credits (§25) and plans (§26)

Credits extend `QuotaLedger` (see §3.3). Usage measurement is separate from
billing. Costs are declared per capability, never hard-coded into execution.

| | LIST | PRO | ADVANCED | ENTERPRISE |
|---|---|---|---|---|
| Research depth | homepage + basic crawl | full crawl + CMS | + AI visibility, competitors | + continuous re-evaluation |
| Opportunities | view | view + recommend | + capability matching | + custom rules |
| Execution | — | website, content | + media, ecommerce, ads prep | + autopilot, ads execution |
| Approval mode | manual | manual | assisted | configurable policies |
| Businesses | 1 | 3 | 15 | unlimited |
| Users | 1 | 3 | 10 | SSO + teams |
| Social accounts | — | 1 | 7 | unlimited |
| Marketplace | — | — | Amazon | Amazon + Noon |
| CRM / leads | — | — | leads | leads + CRM + enrichment |
| Credits | small | monthly | monthly + purchase | pooled + grants |
| API / white-label | — | — | API | API + white-label |

Plans differ by **capability and depth**, not by arbitrary limit inflation.

## 21. Analytics, ROI and re-evaluation (§29, §30)

Baseline → intervention → window → observed result → comparison → confidence →
limitations.

**Language is part of the architecture.** The system may say *"observed change
after intervention"* and may not say *"Qevik caused a 43% increase"* unless
causality is actually established. This is enforceable the same way the outreach
overclaim gate is enforced — a phrase list checked before anything reaches a
customer — and it should be, because a fabricated causal claim is the single
most damaging sentence this platform could produce.

Re-evaluation closes the loop: publication → 30-day measurement → re-research →
compare → new opportunities. That loop is the product.

## 22. Case studies (§32)

Recommendations differ because the evidence differs. Abbreviated:

**AHS — premium catering, strong brand.** Research grades it STRONG with a FAST
site. Opportunities are *additive*: portfolio discovery (34 orphaned pages, 32
picture-only, 170 photographs), AI visibility for "catering Dubai", quote-journey
structure, Arabic, a dormant blog. **Not** "your website is bad". This is the
case that proves the system can sell to a strong company.

**Coffee shop — local B2C.** Local visibility, menu/order journey, loyalty,
lifestyle media, hours and map. Not a case-study system; nobody chooses a café
from a portfolio.

**Ecommerce seller — Amazon/Noon.** Listing quality, image sets, A+ where
applicable, keyword research, ads preparation. Marketplace capabilities start
`REQUIRES_CONNECTION`.

**B2B company.** Capability, proof, RFQ journey, lead generation, CRM. Content
that answers buying questions.

**Logistics.** Quote and tracking journeys, document portal, multilingual, B2B
lead generation.

**CRM / lead-gen business.** ICP, enrichment, outreach systems, their own funnel
measurement.

**Small service business.** Reachability, local visibility, a working enquiry.
Deliberately the shortest list — recommending a CRM to a two-person business is
how a platform proves it is not listening.

## 23. 3D and advanced (§33)

`CAPABILITY_DEMO`, already in the demo vocabulary with the strictest overclaim
gate. Commercially real where the buyer's decision is spatial — event layouts,
showrooms, configurators. A technology demonstration everywhere else, and
labelled as one.

## 24. Agency and white-label (§34)

`organization/` already has `Membership`, `Team`, `PolicySet`, `Role` and
`Branding`. Sub-accounts, per-tenant branding and agency-level usage are
configuration of an existing model rather than a new one.

## 25. Security and privacy (§35)

Tenant isolation at the query layer, not the view layer. **No provider
credential is ever readable by a customer or another tenant** — credentials live
in the vault, are referenced by name, and never enter an asset, a job payload or
a log. Customer media, generated assets and lead data are tenant-scoped;
retention, deletion and consent are per-tenant policy. The append-only audit
service records who did what.

## 26. Dependency graph (§37)

```
Research ──► Evidence ──► Opportunity ──► Recommendation ──► Capability
                                                │
                                          Approval ──► Job ──► Provider
                                                              │
                                                          Asset ──► QA
                                                                     │
                                                            Publication ──► Measurement
                                                                                 │
                                                                          Re-evaluation
```

P0 built Research → Evidence → Opportunity. **P1's critical path is
Recommendation → Capability → Job → Asset → QA**, because nothing downstream
exists without it. Measurement depends on publication; publication depends on
QA; QA depends on assets. Everything in §4 that is not on that path is a
capability that plugs in afterwards.

## 27. Implementation phases (§38, adjusted to this codebase)

| Phase | Contents | Why here |
|---|---|---|
| **P1** | Recommendation · Capability registry · Job wiring to the kernel queue · QA gate framework · Asset provenance extension · portal skeleton (read-only) | The connective tissue. Nothing else is reachable without it. |
| **P2** | Website factory execution · content factory · image factory | Reuses the AHS generator and the differentiation gate; highest proven value. |
| **P3** | AI visibility research + optimisation · SEO execution | A research stage plus rules; cheap once P1 exists. |
| **P4** | Credits on the quota ledger · plans · customer portal (write) · public audit | Commercial surface. Needs P1's job states to show anything true. |
| **P5** | Ecommerce · Amazon · Noon | All gated on connections we do not have. |
| **P6** | Leads · CRM · email | Personal data; wants the tenancy and audit work settled first. |
| **P7** | Social · video · character factory · autopilot | Highest risk, most approval surface. |
| **P8** | Agency / white-label | Mostly configuration of `organization/`. |

## 28. Testing strategy (§39)

Unit · integration · **provider mocks and recorded fixtures** (the research
engine already does this with `MockTransport`) · browser at both viewports ·
permissions · **tenant isolation** · job idempotency · retry · cancellation · QA
gates · approval · publication · credit consumption · credit failure and refund ·
measurement · audit trail.

**Negative control on every gate**, which the codebase already treats as
mandatory: a guard nobody has seen fail is a guard nobody knows works. Specific
ones worth naming: a job cannot reach READY with a failing QA layer; a customer
cannot read another tenant's anything; a retried job does not double-publish; a
refunded credit reconciles to zero; a strong business does not produce
manufactured weaknesses.

## 29. Rollback (§40)

Per execution class. Reversible: website deploys (versioned already), asset
versions, CRM edits. Irreversible: sent email, published social post,
marketplace change, ad spend — these require approval, record a warning, and
have a compensating action where one exists (delete the post, pause the
campaign, revert the listing).

**A job never becomes successful because generation succeeded.** If publication
failed, the job failed, and the asset stays `READY_TO_PUBLISH`.

## 30. Risks and open decisions

**Risks.**
1. *Scope.* Twenty-four families is a decade of work. The mitigation is the loop:
   ship the tissue, then capabilities one at a time, each earning its place.
2. *Assumed API access.* Amazon, Noon, Google Ads, social publishing — none is
   verified. Everything modelled as `REQUIRES_CONNECTION`.
3. *Causal overclaim.* The most damaging failure available to this platform.
   Needs the same gate as outreach overclaiming.
4. *Personal data in lead generation.* Legal exposure; wants tenancy, retention
   and consent settled before P6.
5. *Provider cost.* Credits must reserve before acting or a job spends money it
   does not have.

**Open decisions — yours, not mine.**
1. **Customer portal: extend the console or a new app?** I recommend new — the
   console is an operator tool and its density is wrong for a customer — but it
   is a real fork in the road.
2. **Does a customer see raw evidence?** It is honest and it is also a lot of
   `NOT_VERIFIED`. My inclination is yes, summarised, with detail on demand.
3. **Credits: per-tenant or per-business?** Per-tenant is simpler; agencies will
   want per-business.
4. **Public audit depth.** Enough to be useful, not enough to be the product.
   Where exactly is a commercial call.
5. **Autopilot ceiling.** What may a bounded workflow do without asking? I would
   start with nothing public and nothing that spends.
6. **Do we build a CRM at all**, or integrate from the start? Building is
   tempting and rarely correct.
