# Business roadmap

How Atlas turns into a revenue-generating operating system.

**This is not an implementation document.** No schemas, no interfaces, no file
layouts. It answers a different question: *which factory earns first, and why that
one.* Implementation plans are written per milestone, after a factory is chosen.

Ranked under [`SHIP_RULE.md`](SHIP_RULE.md). Where this roadmap and a technical
preference disagree, SHIP-1 wins.

---

## Position today (2026-08-04)

Honest starting point, because the ranking depends on it.

**What exists.** Atlas desktop runs and is stable. The kernel has an orchestrator,
job queue, provider router, action registry, recipe registry and event bus. M013 built
the media layer — source model, capability-based recipes, dependency graph, partial
regeneration, approval gate, YouTube publisher — and is **frozen, blocked on a GPU
worker and YouTube credentials**.

**What Ayoub already has** that most of these factories would otherwise have to
acquire: live Amazon seller accounts in UAE and KSA, a real marketplace business
(Naml), a Meta ads account, Hetzner infrastructure, two GPU machines, Cloudflare, and
sixteen years of operating experience in exactly the businesses these factories serve.

**The asset that dominates the ranking:** Ayoub is a customer with revenue today.
Every factory that serves him first skips the entire sales cycle — no acquisition
cost, no close rate, no trust problem, and a feedback loop measured in hours.

**The boundary that must hold.** The Naml ops dashboard already runs marketing, blog,
inbox, scheduler, UGC and CopyLab in production. **Atlas does not rebuild Naml.**
Where a factory overlaps it, the roadmap says so and the factory either serves a
different business (Oskar) or absorbs the function later. Rebuilding working software
is the purest possible SHIP-1 violation.

**Estimates.** Effort is in *focused build-days* — one day of uninterrupted work at
the pace M012/M013 actually ran, not calendar days. Revenue figures are **assumptions
to validate, not researched market data**, and are marked as such.

---

## 1. Opportunity Factory

**Objective.** Continuously find businesses with a fixable commercial problem — no
website, weak SEO, poor UX, unoptimised Amazon or Airbnb listings — and turn each into
a personalised, evidence-backed proposal. Human approves. Atlas sends.

**Customer.** Ayoub, acting as an agency. The end buyer is a UAE/GCC SMB or
marketplace seller.

**Revenue model.** Services revenue per closed deal. *Assumption to validate:* a
one-off engagement in this market is meaningful (thousands of AED), and close rate on
warm, evidence-backed outreach is the single number that decides whether this factory
works at all.

**Dependencies.** Web search and crawling, an LLM, a proposal renderer, and an
approval-gated outreach channel (email, later WhatsApp/CRM). **All available now.** No
GPU. No new credentials. No marketplace API approval.

**Effort.** 6–9 build-days to a usable MVP.

**Earliest MVP.** A ranked list of prospects, each with named specific defects, a
generated proposal, and a one-click approve→send step with full suppression and
audit trail.

**What can be sold after MVP.** Nothing directly — it sells *someone else's* delivery
capacity. Its output is qualified leads, which are only worth money if a delivery
factory exists to service them.

**Why it exists.** It is the only factory that produces demand rather than assets.
Every other factory makes something; this one finds who will pay for it.

**Relationships.** Feeds Website, Amazon, AI SaaS and Media (all are delivery for the
leads it finds). Depends on Browser Agent later, for outreach into channels with no
API. Constrains nothing.

**Risk.** Cold outreach is a reputation and compliance surface. Ayoub's standing rule
is *no spam*, and the approval gate is load-bearing, not decorative. Also: leads
without delivery capacity are a pipeline you cannot service — which is why this ranks
below the factory that already has a customer.

---

## 2. Website Factory

**Objective.** Given a goal, design, implement, deploy, monitor, improve and redeploy
a website without the operator choosing a framework, host or stack.

**Customer.** SMBs sourced by the Opportunity Factory. Also Naml and Oskar internally.

**Revenue model.** Per-site build fee, plus optional recurring hosting/maintenance —
the recurring half is what makes it more than freelancing.

**Dependencies.** Deployment Factory (hard blocker — a site that cannot deploy is not
a product), domain and DNS automation, LLM codegen, an asset/image source.

**Effort.** 10–15 build-days, most of it in deploy/verify rather than generation.

**Earliest MVP.** One vertical, one template family, real domain, live URL, measurable
uptime. Narrow and shipped beats general and unshipped.

**What can be sold after MVP.** Complete websites, immediately. This is the most
directly saleable output of any factory here.

**Why it exists.** It converts Opportunity leads into revenue, and it is the delivery
arm that makes lead generation worth doing.

**Relationships.** Consumes Opportunity leads. **Hard-depends on Deployment.** Shares
codegen with AI SaaS — the same generate→deploy→verify spine, at different scale.
Consumes Media for imagery and copy. Monitored by Business Automation.

---

## 3. Amazon Factory

**Objective.** Create and optimise marketplace listings end to end: keyword research,
imagery, listing copy, A+ content, competitor analysis, inventory analytics, daily
monitoring.

**Customer.** **Oskar Phones and Teqtronix — Ayoub's own businesses, selling on Amazon
UAE and KSA today.** Later, other GCC sellers.

**Revenue model.** Two distinct mechanisms, and they behave differently:
1. **Lift on existing revenue.** Better listings convert traffic Ayoub already pays
   for. No new customer required; the effect is measurable against current baseline.
2. **Sold as a service** to other sellers once proven on his own catalogue — with a
   case study he owns rather than a pitch.

**Dependencies.** Catalogue data (**already available** via existing systems and
exports), image generation (available), LLM (available). Amazon SP-API is *desirable,
not required* for MVP — approval takes time, and the first version can run on exports
plus public marketplace data. Being able to start without it is exactly why this ranks
where it does.

**Effort.** 8–12 build-days for MVP.

**Earliest MVP.** Pick N live ASINs, generate optimised titles/bullets/keywords/imagery
with reasoning, human approves, apply, and **measure the before/after**. The
measurement is the deliverable, not the copy.

**What can be sold after MVP.** Listing optimisation as a service to GCC sellers —
a market Ayoub is already inside and credible in.

**Why it exists.** It is the shortest path from Atlas to money, because it improves
revenue that already exists rather than revenue that must first be won.

**Relationships.** Consumes Media (product imagery, A+ visuals). Feeds Opportunity
(unoptimised competitor listings are themselves leads). Uses Browser Agent for
anything Seller Central exposes only through its UI. Feeds Business Automation with
monitoring.

---

## 4. AI SaaS Factory

**Objective.** Build, deploy and operate complete subscription products — image tools,
PDF tools, SEO tools, marketing tools, automation tools.

**Customer.** Self-serve internet buyers. **The only factory here with no warm
audience** — which is its defining problem.

**Revenue model.** Recurring MRR. The highest ceiling on this list and the only
compounding one.

**Dependencies.** Deployment, payments, auth, billing, support, abuse handling, and
distribution. Distribution is the real dependency and the one that cannot be built —
a deployed SaaS with no traffic earns nothing.

**Effort.** 15–25 build-days for the first product, and that number understates it:
the build is not the hard part, the customers are.

**Earliest MVP.** One narrow tool, one payment path, one acquisition channel.

**What can be sold after MVP.** Subscriptions.

**Why it exists.** Recurring revenue is the only kind that grows while Ayoub sleeps.
Strategically the most valuable destination on the list, and simultaneously the worst
thing to build first.

**Relationships.** Shares the codegen/deploy spine with Website. Depends on Deployment.
Fed by Media and Opportunity for acquisition. Operated by Business Automation.

---

## 5. Media Factory

**Objective.** One source content model, many rendered outputs: video, shorts,
podcasts, music, blogs, presentations, images, thumbnails.

**Customer.** Naml and Oskar marketing, first. Later, content-as-a-service.

**Revenue model.** **Indirect** — content drives reach, reach drives sales. The
weakest direct revenue link of any factory here, which is worth stating plainly given
it is also the one already half-built.

**Dependencies.** **GPU worker (blocked)** and YouTube credentials (blocked). Both
external to the code.

**Effort.** Already ~70% built (M013 steps 1–7). Perhaps 4–6 build-days after the
blockers clear.

**Earliest MVP.** Blocked. Not schedulable.

**What can be sold after MVP.** Content production for sellers and SMBs; supports every
other factory's marketing.

**Why it exists.** Every other factory needs assets, and Ayoub's businesses need
content continuously.

**Relationships.** Supplies Amazon (imagery), Website (visuals), AI SaaS and
Opportunity (marketing). Depends on SSH Infrastructure for the GPU worker. Overlaps
Naml's existing UGC/CopyLab — **do not rebuild those; Atlas serves Oskar and new
work.**

**Note.** Under SHIP-1's revenue-first rule, being blocked is precisely why it does not
get worked around. A blocked milestone is not a reason to keep polishing it.

---

## 6. Browser / Computer Agent

**Objective.** Operate authenticated software the way a person does — Seller Central,
Meta Ads, Merchant Center, Cloudflare, Stripe, Shopify, WordPress, Hostinger —
eventually configuring services itself once given credentials.

**Customer.** Ayoub, immediately. Every factory, structurally.

**Revenue model.** Indirect, but the largest *manual-work* elimination on the list. Its
value is hours returned, not invoices sent.

**Dependencies.** Browser automation, a credential vault with strict scoping, an
approval gate for irreversible actions, and durable session handling.

**Effort.** 12–18 build-days to be trustworthy. Reliability is the whole cost — a
browser agent that works 80% of the time is worse than none, because it fails silently
inside someone's live ad account.

**Earliest MVP.** One site, one workflow, read-mostly, approval-gated on every write.

**What can be sold after MVP.** Nothing directly. It multiplies everything else.

**Why it exists.** It is the universal fallback for every service with no API, and
that set is large and permanent.

**Relationships.** Serves Amazon (Seller Central UI), Opportunity (outreach and
research), Deployment (dashboards without APIs), Business Automation. Depends on the
approval gate built in M013.

**Risk.** Account suspension, TOS exposure, and silent partial failure in systems that
spend money. The highest-risk factory on the list.

---

## 7. SSH Infrastructure Manager

**Objective.** Manage a fleet — workstation, GPU workers, Hetzner, cloud — and decide
where each job runs.

**Customer.** Atlas itself.

**Revenue model.** **None.** It is an enabler.

**Dependencies.** SSH orchestration, provisioning, health and secrets.

**Effort.** 5–8 build-days for the useful subset; the *specific* subset that brings up
one GPU worker is far smaller.

**Earliest MVP.** One GPU worker provisioned, long-polling the queue, running a real
job.

**What can be sold after MVP.** Nothing.

**Why it exists.** It is the thing standing between M013 and shipped video.

**Relationships.** Unblocks Media. Underpins Deployment. Feeds Business Automation.

**Note.** Bringing up **one** worker is shipping work — it removes a blocker. Building
multi-worker scheduling, placement and leases is not, and is explicitly frozen until
the first worker runs.

---

## 8. Deployment Factory

**Objective.** Take a generated artifact — website, API, SaaS — and put it live, with
rollback, monitoring and redeploy.

**Customer.** Atlas itself; indirectly every website and SaaS customer.

**Revenue model.** None directly. It is the gate every saleable digital product passes
through.

**Dependencies.** Hosting targets, DNS, TLS, CI, health checks.

**Effort.** 6–10 build-days.

**Earliest MVP.** One artifact type, one target, one rollback path, verified live.

**What can be sold after MVP.** Nothing alone — but **Website Factory cannot sell
anything without it.**

**Why it exists.** Generation without deployment produces demos. Demos do not
generate revenue.

**Relationships.** Hard dependency of Website and AI SaaS. Depends on SSH
Infrastructure. Used by Business Automation for redeploys.

---

## 9. Business Automation Platform

**Objective.** Run the recurring operational work of a business — monitoring,
reporting, reconciliation, alerting, scheduled actions.

**Customer.** Ayoub's businesses first; later, customers as a retainer service.

**Revenue model.** Indirect via hours saved; potentially recurring retainers later.

**Dependencies.** Event bus and scheduler (**both already exist in the kernel**),
plus connectors per system.

**Effort.** 8–12 build-days, mostly connectors.

**Earliest MVP.** One business, one recurring workflow, running unattended with alerts.

**What can be sold after MVP.** Automation retainers.

**Why it exists.** It is where every other factory's output goes to be *operated*
rather than shipped once.

**Relationships.** Operates the output of Website, Amazon, SaaS and Media. Uses Browser
Agent for systems without APIs. **Overlaps the Naml dashboard most heavily of any
factory — the boundary must be explicit before any work starts.**

---

## 10. Multi-model Orchestrator

**Objective.** Select planner, reasoner, coder, vision, search, image, video and speech
models by capability, never by vendor.

**Customer.** Atlas itself.

**Revenue model.** **None.** Cost reduction and resilience.

**Dependencies.** None blocking. A provider router and capability routing already
exist from M013.

**Effort.** 4–6 build-days to extend properly.

**Earliest MVP.** Partially present today.

**What can be sold after MVP.** Nothing.

**Why it exists.** It prevents dependence on any single vendor, and it is an invariant
of the long-term vision.

**Relationships.** Serves every factory. Depended on by none of them to ship.

**Note.** This is pure architecture. Under SHIP-1 it is item 6 of 6 and should be
extended *when a factory needs a capability it lacks* — never as a milestone of its
own.

---

## Relationship matrix

Rows depend on / consume columns. **H** = hard dependency (cannot ship without),
**s** = soft (benefits, degrades gracefully), **↑** = row feeds the column.

| ↓ depends on → | Opp | Web | Amz | SaaS | Media | Brw | SSH | Depl | BizAu | Multi |
|---|---|---|---|---|---|---|---|---|---|---|
| **Opportunity** | — | ↑ | ↑ | ↑ | s | s | | | ↑ | s |
| **Website** | ↑ | — | | s | s | s | | **H** | ↑ | s |
| **Amazon** | ↑ | | — | | s | s | | | ↑ | s |
| **AI SaaS** | ↑ | s | | — | s | s | | **H** | ↑ | s |
| **Media** | ↑ | ↑ | ↑ | ↑ | — | | **H** | s | | s |
| **Browser agent** | ↑ | ↑ | ↑ | ↑ | | — | | ↑ | ↑ | s |
| **SSH infra** | | | | | ↑ | | — | ↑ | ↑ | |
| **Deployment** | | ↑ | | ↑ | | | **H** | — | ↑ | |
| **Business automation** | ↑ | s | s | s | s | s | s | s | — | s |
| **Multi-model** | ↑ | ↑ | ↑ | ↑ | ↑ | ↑ | | | ↑ | — |

Three structural facts fall out of this table:

- **Deployment is the only hard blocker of a saleable product** (Website, AI SaaS).
- **SSH Infrastructure is the only hard blocker of Media**, which is why M013 sits
  frozen.
- **Amazon Factory has no hard dependency on anything.** It is the only revenue
  factory that can start today.

---

## Objective ranking

**Method.** Each factory scored 1–5 on Ayoub's five criteria, weighted in the order
SHIP-1 states them. *Technical dependency* is scored as **freedom from blockers** —
5 means nothing stands in the way, 1 means blocked today.

| Criterion | Weight | Rationale |
|---|---|---|
| Revenue potential | ×3 | SHIP-1 priority 1 |
| Manual work eliminated | ×2.5 | SHIP-1 priority 2 |
| Time to MVP | ×2 | Sooner into the real world |
| Freedom from dependency | ×1.5 | Blocked work cannot ship |
| Strategic value | ×1 | Real, but last — this is the architecture slot |

| # | Factory | Rev ×3 | Manual ×2.5 | Time ×2 | Deps ×1.5 | Strat ×1 | **Total** |
|---|---|---|---|---|---|---|---|
| **1** | **Amazon** | 5 | 5 | 4 | 4 | 4 | **45.5** |
| **2** | **Opportunity** | 4 | 2 | 5 | 5 | 5 | **39.5** |
| 3 | Website | 4 | 3 | 3 | 3 | 4 | 34.0 |
| 4 | Browser / Computer | 2 | 5 | 2 | 4 | 5 | 33.5 |
| 5 | Deployment | 1 | 3 | 4 | 5 | 5 | 31.0 |
| 5 | Business automation | 2 | 4 | 3 | 4 | 3 | 31.0 |
| 7 | SSH infrastructure | 1 | 3 | 4 | 5 | 4 | 30.0 |
| 8 | AI SaaS | 5 | 1 | 1 | 2 | 5 | 27.5 |
| 9 | Media | 2 | 4 | 3 | 1 | 3 | 26.5 |
| 10 | Multi-model orchestrator | 1 | 1 | 4 | 5 | 3 | 24.0 |

### What the ranking says

**Amazon Factory wins on the criterion that decides everything: it has a paying
customer today.** Ayoub sells on Amazon UAE and KSA right now. Improving those
listings lifts revenue that already exists — no acquisition, no close rate, no trust
gap, and a result measurable against a live baseline within weeks. Every other revenue
factory must first find someone willing to pay.

**AI SaaS scores maximum on revenue and still lands 8th.** That is the ranking working
correctly rather than a flaw in it: the highest ceiling on the list is also the
longest path to the first dirham, and SHIP-1 ranks time-to-real-world above ambition.
It stays a destination.

**Media lands 9th despite being 70% built.** Sunk effort is not a criterion. It is
blocked externally, and SHIP-1's revenue-first rule exists precisely to stop blocked
work from absorbing attention it no longer earns.

**Deployment, SSH and Multi-model are enablers, not milestones.** They score
respectably on strategic value and near-zero on revenue. Each should be built *thinly,
inside the factory that first needs it* — Deployment when Website ships, SSH when the
GPU worker arrives — never as a project of its own. This is the exact failure mode
SHIP-1 was written to prevent.

**A correction to what I said an hour ago.** I recommended Opportunity Factory first.
Working the numbers changes the answer: Opportunity generates leads, and leads are
worth nothing without delivery capacity, whereas Amazon Factory serves a business that
already exists and already earns. Amazon first, Opportunity second — and Opportunity
becomes far stronger once there is a proven result to sell.

---

## Proposed next milestone

### M014 — Amazon Factory MVP

*(Numbering note: the frozen media continuation is deferred, not renumbered. This is
the next milestone Atlas works on, not the next media milestone.)*

**Outcome.** Measurably better performance on a real subset of Oskar's live Amazon
catalogue, produced by Atlas and approved by Ayoub.

**Scope.**
- Ingest a real catalogue subset (exports plus public marketplace data — **no SP-API
  approval on the critical path**)
- Keyword research and competitor analysis per ASIN
- Generate optimised title, bullets, description, backend keywords, with the reasoning
  attached
- Product imagery via the existing media layer where it does not need the blocked GPU
- Approval gate — Ayoub approves the *outcome*, Atlas executes the plan
- Apply changes, then **measure before/after against a live baseline**

**Explicitly out of scope.** A generic marketplace abstraction. Noon/eBay/Shopify
connectors. Full SP-API integration. Inventory forecasting. Building any of these
before one ASIN improves would be a SHIP-1 violation.

**Effort.** 8–12 build-days.

**Success is a number, not a demo:** N listings updated, measured lift or honest
absence of it. If the lift is not there, that is a finding worth having early and
cheaply.

**Why this and not the alternatives.** Website needs Deployment first and a customer
second. Opportunity produces leads with nothing yet to deliver. Media is blocked.
Amazon needs nothing that does not already exist, and its customer is already paying.

**What it sets up.** A proven, owned case study — which is the single strongest input
to Opportunity Factory, the proposed milestone after it.

---

## Open questions for Ayoub

These change the plan, so they are worth answering before M014 starts:

1. **Which catalogue?** Oskar Phones or Teqtronix, UAE or KSA — and roughly how many
   ASINs are worth touching first?
2. **Is SP-API worth starting in parallel?** Approval is slow but not on the critical
   path. Beginning the application now costs nothing and may unblock the version after.
3. **What does "better" mean to you** — sessions, conversion rate, units, or revenue
   per ASIN? The measurement decides what gets built.
4. **Naml boundary:** confirm Atlas serves **Oskar** here, and does not touch Naml's
   existing marketing stack.
