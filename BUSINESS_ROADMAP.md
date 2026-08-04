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

**Leverage.** Highest on the list. Its output **compounds** — it runs continuously and
never exhausts its market — where a catalogue or a client site is finite. And every
other factory's *commercial* path runs through it: selling Amazon optimisation to other
sellers, or websites to SMBs, both begin with finding and reaching them.

**Risk.** Cold outreach is a reputation and compliance surface. Ayoub's standing rule
is *no spam*, and the approval gate is load-bearing, not decorative. Second: leads
without delivery capacity are a pipeline you cannot service — survivable while delivery
is manual, which is why Website Factory follows immediately. Third and largest: **close
rate is unproven.** If it is near zero the factory produces nothing, so the MVP exists
to measure it cheaply.

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

### The correction that produced this ranking

The first version of this document ranked Amazon first. It got there by scoring
*strategic value* at ×1 — the **lowest** weight of five — and strategic value is
precisely where leverage lives. The relationship matrix showed Opportunity feeding four
other factories, that fact was written down, and then a ×1 weight buried it.

That is a scoring error, not a judgement call. Atlas is meant to become an operating
system that builds businesses, not a tool that improves one. A ranking that optimises
for the next dirham will always select the factory serving the customer who already
exists, and will therefore never build the engine that finds new ones.

**Leverage is now a first-class criterion, weighted highest, and it replaces
"strategic value" rather than sitting beside it** — the two measure the same thing, and
counting both would double-count it.

**Method.** Scored 1–5. *Freedom from dependency*: 5 = nothing in the way, 1 = blocked
today. *Platform leverage*: how many other factories this one multiplies, and whether
its output **compounds** or is **capped**.

| Criterion | Weight | Rationale |
|---|---|---|
| Platform leverage | ×3 | Does this multiply other factories, and does it compound? |
| Revenue potential | ×2.5 | SHIP-1 priority 1 |
| Manual work eliminated | ×2 | SHIP-1 priority 2 |
| Time to MVP | ×1.5 | Sooner into the real world |
| Freedom from dependency | ×1.5 | Blocked work cannot ship |

| # | Factory | Lev ×3 | Rev ×2.5 | Manual ×2 | Time ×1.5 | Deps ×1.5 | **Total** |
|---|---|---|---|---|---|---|---|
| **1** | **Opportunity** | 5 | 4 | 2 | 5 | 5 | **44.0** |
| **2** | **Amazon** | 2 | 5 | 5 | 4 | 4 | **40.5** |
| **3** | **Website** | 5 | 4 | 3 | 3 | 3 | **40.0** |
| 4 | Browser / Computer | 5 | 2 | 5 | 2 | 4 | 39.0 |
| 5 | Deployment | 4 | 1 | 3 | 4 | 5 | 34.0 |
| 6 | Business automation | 3 | 2 | 4 | 3 | 4 | 32.5 |
| 7 | SSH infrastructure | 3 | 1 | 3 | 4 | 5 | 31.0 |
| 8 | Multi-model orchestrator | 4 | 1 | 1 | 4 | 5 | 30.0 |
| 9 | Media | 3 | 2 | 4 | 3 | 1 | 28.0 |
| 10 | AI SaaS | 2 | 5 | 1 | 1 | 2 | 25.0 |

### What the ranking says

**Opportunity Factory is now clearly first, and the margin is real** — 3.5 points clear
of second, where the rest of the table is separated by fractions. Three properties do
that work:

*It compounds; the others are capped.* Amazon Factory optimises a catalogue, and a
catalogue is finite — once the listings are good, the marginal value falls away. A
demand engine has no such ceiling. It runs continuously and its output grows.

*Every other factory's commercial path runs through it.* This is the argument I missed
entirely. Amazon Factory's second revenue mechanism — selling listing optimisation to
other GCC sellers — **requires finding and reaching those sellers**, which is
Opportunity Factory. The same is true of Website and AI SaaS. Ranking Amazon first put
the delivery arm before the demand engine, and then relied on the demand engine to make
it a business.

*It has no blockers at all.* No GPU, no marketplace API approval, no new credentials.

**Amazon and Website are a statistical tie** — 40.5 against 40.0, which is inside the
noise of any 1–5 scoring exercise. **The numbers do not choose between them, so
something else must.** The tiebreaker is which one closes a loop:

Website Factory is the delivery arm for Opportunity Factory. Together they are a
**complete self-contained business** — find businesses with a fixable web problem,
propose, deliver, charge — that needs no other factory to function. Website also
carries Deployment, and Deployment is the hard blocker on AI SaaS, so building Website
buys most of the infrastructure the highest-ceiling factory will eventually need.

Amazon Factory closes no loop with anything. It serves a *different* business (Oskar),
and its value as a product depends on Opportunity existing first.

**So Website takes second on leverage, despite trailing by half a point on score.**

**Amazon Factory keeps a real and specific role at third.** It is still the fastest
measurable revenue on the list and the least blocked — and more importantly, it
produces the thing that makes Opportunity Factory's outreach actually convert: **a
proven, owned case study.** "We increased conversion on our own catalogue by X" is a
materially stronger opening than a generic pitch. It is a strong candidate to run
alongside or immediately after Opportunity rather than being deferred indefinitely.

**AI SaaS falls to last under this lens, from 8th.** It scores maximum on revenue and
minimum on nearly everything else: it consumes leverage rather than creating it, is
blocked behind Deployment, and its true dependency — distribution — cannot be built at
all. It remains the highest-ceiling destination and the worst possible starting point.

**Media falls to 9th.** Blocked externally, capped leverage, indirect revenue. Sunk
effort is still not a criterion.

**Enablers stay enablers.** Deployment, SSH and Multi-model score well on leverage and
near-zero on revenue — which is exactly the signature of infrastructure. Each gets
built *thinly, inside the first factory that needs it*: Deployment inside Website, SSH
when the GPU worker arrives. Never as a milestone of its own. Multi-model's 4 on
leverage next to 1 on revenue is precisely the trap SHIP-1 exists to prevent.

### The honest cost of going Opportunity-first

Worth stating plainly rather than leaving for later:

**Opportunity Factory adds manual work before it removes any.** It scores 2 on manual
work eliminated — the second-lowest on the table — because every lead it produces
consumes Ayoub's time in closing, and initially in delivery too. That is in direct
tension with SHIP-1 priority 2, and it is the strongest argument for the Amazon-first
ranking I originally gave.

It is a real cost, not a fatal one. Building a demand engine always costs time before
it returns any, and Ayoub has an operating team that can service early leads by hand
while Website Factory is built. But it constrains the MVP: **automate the research and
the proposal — where the hours actually go — and leave only the close to a human.** A
version that generates leads without generating the proposal would make the problem
worse rather than better.

**And the number that decides everything is unproven.** Close rate on cold,
evidence-backed outreach is an assumption. If it is near zero, the factory produces
nothing regardless of how well it is built. That is not a reason to defer it — it is
the reason to build the smallest version that measures it honestly and early.

---

## Proposed sequence

*(Numbering note: the frozen media continuation is deferred, not renumbered. These are
the next milestones Atlas works on, not the next media milestones.)*

### M014 — Opportunity Factory MVP  ← **proposed next**

**Outcome.** A repeatable engine that finds real businesses with a specific, provable
commercial defect and produces a personalised proposal Ayoub can approve and send —
with the **close rate measured**.

**Scope.**
- One niche, one geography. Narrow enough that the proposals are genuinely specific.
- Discovery: find businesses and detect concrete defects — no website, broken or
  insecure site, unusable on mobile, weak SEO, unclaimed or unoptimised listings
- **Evidence per prospect** — a screenshot, a score, a named finding. A proposal that
  cannot point at the problem is a cold email.
- Proposal generation: personalised, evidence-backed, priced
- **Approval gate** — Ayoub approves per prospect or per batch. Nothing sends
  unapproved. This is the product, not a safety wrapper.
- One channel (email), with suppression and a full audit trail
- Track replies through to conversations

**Explicitly out of scope.** WhatsApp and CRM channels. Multi-channel orchestration.
Any auto-send path that bypasses approval. A generic crawling framework. Automated
delivery of the work sold — early delivery is manual and that is correct.

**Effort.** 6–9 build-days.

**Success is a number, not a demo:** *N* prospects found with named defects, *M*
proposals approved and sent, and a measured reply and conversation rate. If the close
rate is near zero, that is the single most valuable thing to learn, and learning it in
nine days is the point.

**Why this first.** It compounds where the others are capped, it is the commercial path
for every other factory including Amazon's, and nothing blocks it.

### M015 — Website Factory MVP (carrying Deployment)  ← **[defined in M015.md](M015.md)**

The delivery arm that closes the loop with M014, and the milestone that buys the
deployment spine AI SaaS will need. One vertical, one template family, real domain,
live URL, verified uptime, rollback. **10–15 build-days plus 6–10 for Deployment** —
the most expensive milestone in the sequence, and the reason it follows a milestone
that proves demand exists first.

### M016 — Amazon Factory MVP

Unchanged in scope from the previous draft: real ASINs, keyword and competitor
analysis, generated listing content with reasoning attached, approval, apply, and a
measured before/after. **8–12 build-days**, nothing blocking.

Worth running **earlier than its slot if M014's build is ever waiting on something
external** — it is the least blocked factory on the list, and its output is the case
study that makes M014's outreach convert. Under the revenue-first rule, that is exactly
what a blocked stretch should be filled with.

---

## Open questions for Ayoub

These change the plan, so they are worth answering before M014 starts:

1. **Which niche and geography** should the first Opportunity run target? This is the
   single highest-impact input — it decides whether the proposals are specific enough
   to convert, and your read on the market beats any scoring model here.
2. **Who delivers the first sold engagement?** Confirming that early delivery is manual
   (your team) sets the MVP scope correctly and keeps Website Factory out of M014.
3. **What is the offer?** A fixed-price website, an audit, a retainer? The proposal
   generator needs something concrete to propose.
4. **Outreach identity and channel** — which domain and sending address, given the
   reputation exposure and your standing *no spam* rule.
5. **Run M016 in parallel?** If Oskar's catalogue is available now, the Amazon case
   study is the strongest single input to M014's conversion rate.
