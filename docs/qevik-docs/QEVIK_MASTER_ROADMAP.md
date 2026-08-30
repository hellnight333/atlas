# QEVIK MASTER ROADMAP

**Status:** AUTHORITATIVE  
**Last reconstructed:** 2026-08-30  
**Repository:** `hellnight333/atlas`

> This is the single human-readable roadmap for Qevik. It consolidates the established architecture, implementation evidence, roadmap, blockers, deferred work, dropped decisions, and unresolved product decisions. It does not invent capabilities that are not evidenced.

> Historical source documents use **Phase / P numbering**. Earlier conversation sometimes used M0/M1 informally. This document retains the authoritative Phase/P numbering rather than inventing a competing M-number system.

---

# 01 — QEVIK NORTH STAR

Qevik is an **autonomous, evidence-driven business-production and digital-execution system**.

It is not merely a website generator, chatbot, coding assistant, or automation tool. It is intended to take a business, product, or authorized job through research, evidence, planning, production, review, approval, publication/external action, measurement, and re-evaluation.

The universal execution model is:

```text
Research
  ↓
Evidence
  ↓
Opportunity / Requirement
  ↓
Recommendation / Plan
  ↓
Approval where required
  ↓
Mission
  ↓
Recipe
  ↓
Agent
  ↓
Tool
  ↓
Worker
  ↓
Artefact / Result
  ↓
Review / QA
  ↓
Approval where required
  ↓
Publication / External Action
  ↓
Measurement
  ↓
Re-evaluation
```

Not every operation requires every stage. External side effects require explicit authorization boundaries.

The commercial ladder established in the project is:

1. Website improvement
2. Website + SEO/content
3. Website + lead generation
4. Website + CRM
5. Digital product / portal
6. Mobile app
7. Ecommerce / marketplace
8. Media + advertising factory
9. Ongoing digital growth platform

Do not force the highest package. The strongest opportunity determines the appropriate product.

---

# 02 — CURRENT STATE

## Production-proven

### Business intelligence

- OSM business discovery.
- Real business records and opportunity signals.
- Evidence-backed verification.
- Three-state source absence semantics:
  - `OBSERVED`
  - `ABSENT_IN_SOURCE`
  - `NOT_CONSULTED`
- Evidence fingerprints.
- Bounded evidence bodies.
- Deterministic opportunity extraction/detection/ranking.
- Evidence-backed website verification.
- Weak web presence detection.

### Commercial website workflow

The proven chain is:

```text
Discovery
→ Verification
→ Evidence-backed audit
→ Opportunity
→ Ranking
→ Approval
→ Delivery
→ Artefact
→ Review
→ Accepted
→ Publication approval
→ Policy
→ Publication
→ Live URL
→ Publication recorded
→ Outreach preparation
```

A real business website was generated, reviewed against an exact Git commit, published through the existing hosting architecture, verified externally, and recorded as published.

### Artefact review

Production-proven:

- read-only artefact reader;
- exact commit-addressed inspection;
- Git read operations only;
- repository containment;
- `artefact/` containment;
- traversal rejection;
- hidden scratch-path rejection;
- review bound to exact inspected commit;
- append-only review decisions;
- derived accepted-but-not-published queue.

### Publication

Production-proven:

- accepted artefact publication;
- publication approval;
- policy check;
- existing `sites.qevik.ai` host;
- promotion;
- public URL verification;
- `publication_completed`;
- published state distinct from publication approval.

### Mission persistence

Production-proven:

- durable missions;
- agent binding;
- recipes;
- claims;
- isolated scratch workspaces;
- budgets;
- reports;
- append-only history;
- PostgreSQL mission ledger;
- deterministic fold.

Ledger migration evidence included 158 original events, 160 rows after later test events, and byte-for-byte equivalence across 13 original missions including timestamp-tie cases.

### Mission reports

Production-proven:

- PostgreSQL report store;
- insert-only semantics;
- 11 reports migrated;
- 6,436,720 bytes;
- SHA-256 equality for all 11;
- cross-process reading without shared filesystem;
- successful approximately 6.5 MB report round-trip.

### Worker/Fabric foundation

Built and exercised:

- Atlas worker registry adopted for identity;
- Qevik per-process worker identities;
- heartbeat;
- resource probing;
- capability derivation from declared agent tools;
- execution-dispatch participation boundary;
- worker stand-down;
- scheduler-side capability matching implementation.

Current Qevik worker identities:

```text
qevik-core-01:worker-1
qevik-core-01:worker-research
qevik-core-01:worker-delivery
qevik-core-01:worker-publish
```

Current role capabilities:

```text
worker-1        → filesystem, shell
worker-research → dns, http-fetch
worker-delivery → website-generator
worker-publish  → site-publish
```

Current measured host resources:

```text
4 CPU cores
7 GB RAM
GPU: none
```

Resources are physical-host observations and must not be summed across worker processes.

## Implemented but production proof pending

### Capability-matched dispatch

Implemented and locally gated.

Core rule:

```text
recipe.required_tools ⊆ worker.capabilities
```

The scheduler now owns assignment/eligibility rather than relying on a worker-side decision as the primary authority.

Latest supplied implementation gate:

```text
3494 passed
33 skipped
0 failed
```

Production deployment/proof is still required before marking this production-proven.

## Built but not fully integrated

- Atlas cluster dispatcher.
- Atlas leases/reservations.
- Browser sessions.
- FFmpeg/media assembly.
- Agent-to-agent protocol scaffolding.
- External integration declarations.
- Dormant/test-oriented Atlas worker data.

## Designed / specified

- Image generation.
- Video generation.
- Music generation.
- Storyboard.
- Voice input/output/control.
- App Factory.
- Game Factory.
- Ecommerce / marketplace workflows.
- Amazon / Noon workflows.
- Google Search Console / analytics / advertising workflows.
- CRM / B2B lead-generation workflows.
- Customer accounts.
- Credits.
- Billing.
- Usage/cost accounting.
- Plans / quotas / limits.
- Customer dashboard.
- Mission Control.
- Self-use/self-improvement.
- Browser/computer-use.
- Distributed HP / Lenovo / GPU workers.

## Not implemented as production capabilities

- Real image-generation backend.
- Real video-generation backend.
- Real music-generation backend.
- Complete storyboard implementation.
- STT.
- TTS.
- Voice control.
- App Factory.
- Android build/release.
- iOS build/release.
- Google Play publishing.
- Apple App Store publishing.
- Game Factory.
- Game build/release.
- Marketplace execution.
- Full advertising execution.
- Full analytics/attribution/revenue loop.
- Full customer billing platform.

## Externally blocked

- SMTP/email sending identity and credentials.
- WhatsApp Business identity/credentials.
- Amazon credentials.
- Noon credentials.
- YouTube credentials.
- Instagram credentials.
- Advertising credentials.
- App-store developer accounts and signing identities.
- Additional hosting where required.
- Image/video/music providers.
- STT/TTS providers.

## Unknown / requires product decision

- YouMind.
- Computer-use lineage.
- Treatment of dormant Atlas runtime surfaces.
- Media provider/backend selection.
- Local vs cloud media/AI policy.
- Outreach policy for businesses that did not request contact.
- Exact audiobook source/transformation/voice policy.
- App/Game shared factory architecture.
- Final customer pricing/economics.

---

# 03 — ARCHITECTURE

## Control plane

Qevik owns:

- mission semantics;
- mission claims;
- recipes;
- agents;
- tools;
- scheduler;
- capability matching;
- budgets;
- policy;
- approvals;
- provenance;
- artefacts;
- reports;
- commercial workflow state.

Workers execute bounded work.

## Atlas and Qevik

### Atlas lineage

Existing:

- worker registry;
- worker identity;
- heartbeat;
- leases;
- reservations;
- dispatcher;
- cluster state;
- runtime/orchestrator infrastructure;
- worker resource model.

### Qevik lineage

Active commercial workflow:

- missions;
- claims;
- recipes;
- agents;
- tools;
- scheduler;
- budgets;
- scratch isolation;
- reports;
- approvals;
- publication;
- outreach preparation.

### Rule

**NO SECOND ORCHESTRATOR.**

Reuse the Atlas worker identity/heartbeat substrate while Qevik remains authoritative for Qevik mission ownership, scheduling, capability matching, approvals, and execution semantics.

Atlas leases/reservations remain distinct from Qevik mission claims.

## Mission execution

```text
Mission
  ↓
Recorded Agent
  ↓
Recipe
  ↓
Required Tools
  ↓
Scheduler
  ↓
Worker Capability Match
  ↓
Eligible Worker
  ↓
Atomic Mission Claim
  ↓
Isolated Workspace
  ↓
Execution
  ↓
Artefact / Evidence
  ↓
Report
```

A mission without a recorded route must not silently become executable.

A mission may have an agent without a recipe; an empty tool set does not mean "no agent".

## Worker identity

Qevik uses one worker identity per worker process because one physical host may run multiple differently capable workers.

Identity:

```text
hostname:worker-name
```

Heartbeat and mission claim staleness remain separate:

```text
worker heartbeat ≈ 90 seconds
mission claim staleness ≈ 900 seconds
```

## Capability matching

A worker can receive work only when its advertised capabilities satisfy every tool required by the recipe.

Recipe requirements derive from recipe steps.

Worker capabilities derive from declared agent tools.

No second hand-maintained capability list.

## Durable execution

The UI is a control/observation surface, not the runtime.

Execution must survive browser close, refresh, network interruption, UI failure, API timeout, worker restart, and server restart.

## Artefacts

Important artefacts should preserve:

```text
artifact_id
type
created_by_task
created_at
source
version
storage_location
checksum
related_commit
related_deployment
```

Reviews must point to the exact output/version inspected.

## Outreach

Canonical path:

```text
Opportunity
→ Preparation
→ OutreachMessage
→ Operator Approval
→ Explicit Send Action
→ OutreachService.send()
→ Guards
→ Channel Adapter
→ Transport
→ Delivery Evidence
```

Policy/guards, channel adapter, and transport remain separate.

Preparation never implies sending.

Qevik never invents a contact destination.

---

# 04 — PRODUCT FACTORIES

## Business Intelligence / Discovery
**IMPLEMENTED / PRODUCTION-PROVEN**

Business discovery, evidence, verification, opportunity detection, ranking, and evidence-backed audits.

## Google Business Data / Places
**DESIGNED / INTEGRATION-DEPENDENT**

Intended for business identity, Places identifiers, map URL, public business attributes, and authorized business intelligence.

Google data must be obtained through an authorized connector and current API/terms must be checked at implementation time.

## Website Factory
**IMPLEMENTED / PRODUCTION-PROVEN for current controlled slice**

Must produce genuinely functional sites, not only generated HTML.

Production completion should verify:

- HTTP response;
- page load;
- runtime/console errors;
- major routes;
- responsive rendering;
- screenshots;
- links;
- forms;
- API connectivity where applicable;
- authentication where applicable;
- performance;
- deployment;
- smoke test.

## SEO / UX / Market Audit
**PARTIALLY IMPLEMENTED / CONTINUING**

Existing SEO analysis and evidence-backed findings.

Future scope includes broader website intelligence, search/AI visibility, conversion analysis, competitor/market analysis, and measurement.

## Digital Product Factory
**DESIGNED / EARLY WORKFLOW**

Potential outputs:

- guides;
- checklists;
- templates;
- calculators;
- interactive tools;
- portals;
- mini-courses;
- lead magnets;
- business-specific tools.

A digital product must be genuinely usable.

## CRM / Lead Generation
**DESIGNED**

Potential:

- lead database;
- qualification;
- CRM;
- pipeline;
- RFQ/enquiry;
- follow-up;
- email/WhatsApp workflows;
- sales dashboard;
- reporting.

Handle personal data lawfully and conservatively.

## Ecommerce / Marketplace
**DESIGNED**

B2C:

- catalogue;
- PDP;
- search/filter;
- cart;
- checkout;
- reviews;
- bundles;
- subscriptions;
- SEO;
- email;
- advertising.

B2B:

- account pricing;
- RFQ;
- bulk ordering;
- customer-specific catalogue;
- approvals;
- invoices;
- reorder;
- CRM/sales integration.

## Affiliate
**DESIGNED / NOT PRODUCTION-IMPLEMENTED**

```text
Product research
→ Affiliate eligibility
→ Offer understanding
→ Creative
→ UGC/content
→ Distribution
→ Tracking
→ Conversion
→ Revenue
```

No affiliate revenue is claimed without measured conversions.

## UGC
**DESIGNED / MEDIA-DEPENDENT**

Intended:

- hooks;
- scripts;
- product understanding;
- demonstrations;
- CTA;
- captions;
- variants;
- platform adaptation;
- disclosure;
- measurement.

## Media Factory
**PARTIAL FOUNDATION**

Existing:

- media assembly;
- FFmpeg.

Missing:

- real image/video/music generation backends;
- complete storyboard;
- voice;
- production QA;
- full distribution/measurement.

## Image generation
**PLANNED / GREENFIELD BACKEND**

## Video generation
**PLANNED / GREENFIELD BACKEND**

## Music generation
**PLANNED / GREENFIELD BACKEND**

## Storyboard
**PLANNED / SPECIFICATION INCOMPLETE**

```text
Brief
→ Concept
→ Visual definitions
→ Storyboard
→ Assets
→ Generation
→ Assembly
→ QA
→ Delivery
```

## Character Sheet
**DEFERRED / NOT CURRENTLY EVIDENCED**

## Creative Blueprint
**DROPPED**

## Visual Bible
**NOT CURRENTLY EVIDENCED**

## Asset Bible
**NOT CURRENTLY EVIDENCED**

## Voice
**PLANNED / GREENFIELD**

```text
Voice Input
→ STT
→ Intent / Control Request
→ Policy
→ Execution
→ Result
→ TTS
```

Also intended: voice-controlled Qevik and audio briefings.

## Audiobook / Book Factory
**DEFERRED**

```text
Book / authorized source
→ Acquire / ingest
→ Extract / understand
→ Summary / detailed / full authorized transformation
→ Structured content
→ Voice
→ Audio assembly
→ QA
→ Output
```

Before implementation, define source/copyright rules, transformation modes, providers, and formats.

## Browser / Computer Use
**PARTIAL FOUNDATION / DECISION REQUIRED**

Existing browser-session implementation.

Potential uses:

- research;
- web interaction;
- QA;
- CRM;
- Google Console;
- advertising dashboards;
- marketplace dashboards;
- browser administration.

Must remain:

```text
Mission → Recipe → Agent → Tool → Worker
```

## Cowork
**UNKNOWN / EVALUATION CONCEPT**

Computer-use style workflow may be evaluated as a bounded capability, not as Qevik's orchestrator.

## OpenClaw
**DOCUMENTED / OPTIONAL INTEGRATION**

OpenClaw is not the Qevik orchestration foundation.

## App Factory
**NOT IMPLEMENTED**

```text
Requirement
→ Architecture
→ Code
→ Tests
→ Build
→ Package
→ Review
→ Release
```

## Game Factory
**NOT IMPLEMENTED**

```text
Idea
→ Game design
→ Assets
→ Scenes
→ Code
→ Build
→ Test
→ Package
→ Store submission
```

## Analytics / Attribution / Revenue
**DESIGNED / NOT PRODUCTION COMPLETE**

```text
Content / Product
→ Distribution
→ Impressions
→ Clicks
→ Leads
→ Conversions
→ Revenue
→ ROI / Attribution
→ Next decision
```

Never fabricate performance.

## Customer accounts
**FUTURE PRODUCTIZATION**

Reuse existing tenancy/authentication.

## Billing
**FUTURE**

The first payment does not require a complex billing system. The established decision is that Stripe Payment Links are sufficient for the first payment.

## Credits / Usage / Plans
**FUTURE / PARTIAL INFRASTRUCTURE**

Reuse existing quota concepts.

Customer layer eventually includes:

- plans;
- credits;
- usage;
- reserve-before-act;
- actual vs estimated usage;
- quotas;
- limits;
- cost visibility.

## Customer dashboard / Mission Control
**PARTIAL FOUNDATION / FUTURE PRODUCT SURFACE**

Eventually:

- roadmap;
- conversations;
- plans;
- tasks;
- execution;
- blockers;
- approvals;
- reports;
- artefacts;
- commits;
- workers;
- usage;
- cost;
- deployments;
- account state.

---

# 05 — DISTRIBUTION / INTEGRATIONS

| Integration | Status | Intended use |
|---|---|---|
| Google Places | DESIGNED / API dependent | Business intelligence |
| Google Search Console | DECLARED / NOT WIRED | Search visibility |
| Google Analytics | DESIGNED | Measurement |
| Google Ads | DESIGNED / credential dependent | Advertising |
| Email / SMTP | ADAPTER/PATH BUILT; PRODUCTION CREDENTIAL BLOCKED | Outreach |
| WhatsApp | DECLARED / CREDENTIAL BLOCKED | Outreach |
| Amazon | DECLARED / CREDENTIAL BLOCKED | Marketplace |
| Noon | DECLARED / CREDENTIAL BLOCKED | Marketplace |
| Shopify | DROPPED | No implementation without new decision |
| YouTube | DECLARED / CREDENTIAL BLOCKED | Distribution |
| Instagram | DECLARED / CREDENTIAL BLOCKED | Distribution |
| TikTok | DEFERRED | Do not prioritize without reopening decision |
| Facebook | DROPPED | No implementation without new decision |
| Stripe | PAYMENT PATH / CUSTOMER BILLING FUTURE | Payment Links sufficient for first payment |
| Google Play | NOT IMPLEMENTED / account + signing required | App distribution |
| Apple App Store | NOT IMPLEMENTED / account + signing required | App distribution |
| Cloudflare | EXISTING DEPLOYMENT CONTEXT | Hosting/DNS where required |
| Additional hosting | EXTERNAL DEPENDENCY | Customer-specific hosting where needed |

An integration declaration is not a working integration.

---

# 06 — COMPLETE MILESTONE ROADMAP

## Roadmap numbering

The authoritative historical sequence is Phase 1–8. A separate detailed capability sequence is retained below. The phases are not necessarily strictly sequential; independent branches may proceed when unblocked.

---

## P1 — CORE AUTONOMOUS COMMERCIAL LOOP
**STATUS: MOSTLY COMPLETE / PRODUCTION-PROVEN**

### Objective
Prove a controlled commercial loop from real business discovery through evidence, production, review, publication, and outreach preparation.

### Business outcome
Qevik can produce a real, reviewable digital improvement for a real business.

### Product capabilities
- discovery;
- evidence;
- verification;
- opportunity detection/ranking;
- website production;
- artefact review;
- publication;
- outreach preparation.

### Existing infrastructure reused
Missions, claims, recipes, agents, tools, scheduler, budgets, scratch isolation, Git, append-only events, existing hosting.

### Acceptance
Real data, exact artefact review, exact commit binding, explicit approval, real publication verification, no fabricated contact data, no unauthorized external action.

### Production evidence
Real business, real artefact, real public URL, recorded publication.

### Deferred
Outbound communication remains separately gated.

---

## P2 — DISTRIBUTED EXECUTION FABRIC
**STATUS: IN PROGRESS**

### Objective
Move from one controlled production machine to a controlled multi-worker system.

### Completed
- mission ledger → PostgreSQL;
- mission reports → PostgreSQL;
- worker identity;
- heartbeat;
- resource probe;
- capability derivation;
- execution-dispatch boundary;
- explicit agent routing;
- unrouted-mission scheduler block;
- local capability-matched dispatch implementation.

### Next
Deploy and prove capability-matched dispatch in production.

### Future
```text
Capability dispatch
→ Production proof
→ Real remote worker
→ Resource-aware scheduling
→ GPU worker
→ Distributed media/AI workloads
```

### Business outcome
A mission can be routed to the correct worker without manually selecting a computer.

### Acceptance
Capability subset, placement, stale/busy handling, specificity/load/id ordering, scheduler/worker agreement, no silent fallback, no cross-lineage dispatch.

---

## P3 — CREATIVE / MEDIA FACTORY
**STATUS: FUTURE**

### Objective
Produce usable creative/media assets and UGC.

### Capabilities
- image;
- video;
- music;
- storyboard;
- creative production;
- media assembly;
- QA;
- UGC;
- platform variants;
- measurement.

### Dependencies
GPU/worker capabilities and real generation providers/backends.

### Deferred
Character Sheet remains deferred. Creative Blueprint is dropped.

---

## P4 — VOICE
**STATUS: FUTURE / INDEPENDENT BRANCH**

### Objective
Add voice as a production capability and Qevik control-plane interface.

### Capabilities
- STT;
- TTS;
- voice commands;
- voice briefings;
- audio output.

### Dependency
STT/TTS provider or local backend.

---

## P5 — COMPUTER USE
**STATUS: FUTURE / DECISION REQUIRED**

### Objective
Operate web applications where APIs are insufficient.

### Capabilities
- browser research;
- browser QA;
- CRM;
- Google Console;
- advertising dashboards;
- marketplace dashboards;
- administration.

### Dependency
Decision on computer-use lineage.

---

## P6 — COMMERCE / MARKETPLACE / DISTRIBUTION
**STATUS: FUTURE / EXTERNAL DEPENDENCIES**

### Objective
Operate authorized commercial distribution channels.

### Capabilities
- ecommerce;
- Amazon;
- Noon;
- affiliate;
- YouTube;
- Instagram;
- advertising;
- marketplace listing production;
- attribution.

### Acceptance
Separate approval for publication, spend, price changes, and external commitments.

---

## P7 — APP / GAME FACTORIES
**STATUS: FUTURE**

### Objective
Expand from websites to applications and games.

### App
Requirement → architecture → code → tests → build → package → review → release.

### Game
Idea → design → assets → scenes → code → build → test → package → store.

### Distribution
Google Play and Apple App Store require developer accounts and signing identities.

### Decision
Shared App/Game factory architecture is **UNKNOWN / REQUIRES PRODUCT DECISION**.

---

## P8 — PRODUCTIZATION
**STATUS: FUTURE**

### Objective
Turn Qevik capabilities into a customer-facing product.

### Capabilities
- accounts;
- dashboard;
- projects;
- missions;
- approvals;
- artefacts;
- deployments;
- usage;
- credits;
- billing;
- plans;
- quotas;
- limits;
- attribution.

### Commercial website
Public Qevik website becomes the commercial front door, architecturally separate from the internal control plane.

---

## Detailed capability sequence retained from the established roadmap

1. Capability-matched dispatch.
2. Verify dispatch against production.
3. Deploy real remote worker.
4. Capability/resource-aware scheduling.
5. GPU worker.
6. Image generation.
7. Character/visual identity — DEFERRED.
8. Storyboard.
9. Video generation.
10. Music generation.
11. Media assembly and QA.
12. STT.
13. TTS.
14. Voice control.
15. App Factory.
16. Game Factory.
17. App build/release pipeline.
18. Google Play.
19. Apple App Store.
20. Email.
21. WhatsApp.
22. Outreach policy.
23. Amazon.
24. Noon.
25. YouTube.
26. Instagram.
27. Google Search Console.
28. Advertising.
29. Book research.
30. Book summarisation.
31. Audiobook generation — DEFERRED.
32. Content transformation pipeline.
33. Customer accounts.
34. Credits.
35. Billing.
36. Usage/cost accounting.
37. Quotas and limits.
38. Customer-facing dashboards.
39. YouMind — definition first.
40. OpenClaw/operator integration — optional evaluation.
41. Broader agent-to-agent protocol.
42. Larger distributed compute Fabric.

---

# 07 — M1 DEEP STATUS

## Scope

M1 represents the immediate outbound-email/commercial-proof stage supplied in the current roadmap request.

### Implemented

- EmailChannel transport.
- SMTP configuration model.
- Message-ID domain correction.
- Email adapter.
- canonical OutreachService path.
- explicit send action.
- approval boundary.
- suppression.
- cooldown.
- duplicate protection.
- enquiry capability.
- dental/business vertical integration.
- booking/appointment disclaimers.
- test/harness coverage.

### Canonical path

```text
Opportunity
→ Outreach Preparation
→ OutreachMessage
→ Approval
→ Explicit Send Action
→ OutreachService.send()
→ Guards
→ EmailChannel
→ SMTP Transport
→ Delivery Evidence
```

### Latest supplied M1 gate

```text
3503 passed
33 skipped
0 failed
```

This is preserved as the latest M1-specific gate supplied for this roadmap. It is distinct from later Fabric gates.

### Status

- **CODE COMPLETE:** Yes for supplied M1 slice.
- **AUTOMATED VERIFIED:** Yes, according to supplied gate.
- **PRODUCTION VERIFIED:** No; real outbound delivery evidence remains.
- **COMMERCIAL VERIFIED:** No; customer response/payment evidence remains.

---

# 08 — M1 REMAINING WORK

## Technical

- mailbox;
- SMTP credentials;
- SPF;
- DKIM;
- DMARC;
- required Cloudflare DNS;
- production configuration;
- deployment;
- real outbound email;
- received-header SPF/DKIM/DMARC verification;
- approval trail evidence;
- real published-site enquiry;
- enquiry delivery evidence.

## Commercial

```text
Real send
→ Real delivery
→ Real business interaction
→ First customer conversation
→ First customer
→ First payment
```

Technical delivery is not commercial success.

---

# 09 — REVENUE ROADMAP

Shortest credible path:

```text
Strong opportunity
→ Evidence-backed recommendation
→ Working demo / website / digital product
→ Review
→ Approval
→ Publish / demonstrate
→ Truthful outreach
→ Business conversation
→ Proposal
→ FIRST CUSTOMER
→ FIRST PAYMENT
→ Repeatable delivery
→ Repeatable sales
→ Scalable revenue
```

First payment:

**Stripe Payment Links are sufficient.**

Do not build complex billing before the business requires it.

---

# 10 — CUSTOMER / COMMERCIALISATION

## Future

### Customer accounts
Reuse existing tenancy/authentication.

### Dashboard
Projects, missions, roadmap, artefacts, deployments, workers, approvals, usage, cost, billing, settings.

### Billing
Future; do not prematurely build complexity.

### Credits
Customer-facing usage abstraction over existing quota concepts.

### Usage accounting
Estimated, reserved, actual, provider cost, worker cost where applicable.

### Plans / quotas / limits
Future customer product; do not create a second quota ledger.

### Attribution
Source → content → distribution → click → conversion → revenue.

---

# 11 — DISTRIBUTED FABRIC

## Purpose

Enable execution across:

- current Qevik host;
- HP workstation;
- Lenovo workstation;
- GPU systems;
- cloud workers;
- geographically specialized workers.

## Worker model

Workers advertise:

- identity;
- capabilities;
- physical resources;
- placement;
- heartbeat;
- execution participation.

Qevik scheduler decides eligibility and assignment.

## Future examples

```text
Website build
→ coding-capable worker

Research
→ research/browser worker

Image generation
→ GPU worker

Video rendering
→ GPU/render worker

Local model inference
→ local-model GPU worker

Iran-origin verification
→ geographic worker
```

HP/Lenovo are future workers, not separate manual systems.

---

# 12 — MEDIA / UGC / CREATIVE SYSTEM

## Intended production pipeline

```text
Business / Product
→ Research
→ Creative Brief
→ Concept
→ Storyboard
→ Assets
→ Image / Video / Voice / Music
→ Media Assembly
→ QA
→ Platform variants
→ Review / Approval
→ Publication
→ Measurement
```

## UGC

For affiliate, ecommerce, business promotion, and ads:

- hook;
- problem;
- demonstration;
- benefit;
- evidence where applicable;
- CTA;
- captions;
- variants;
- disclosure;
- measurement.

## Current truth

- Media assembly: partial foundation.
- FFmpeg: available.
- Image backend: not implemented.
- Video backend: not implemented.
- Music backend: not implemented.
- Voice: not implemented.
- Storyboard: planned.
- Character Sheet: deferred.
- Creative Blueprint: dropped.
- Visual Bible: not evidenced.
- Asset Bible: not evidenced.

---

# 13 — DECISIONS / DROPPED / DEFERRED

## KEEP

- Pricing.

## DEFER

- Audiobook.
- Character Sheet.
- TikTok.
- Steam.

## DROP

- Creative Blueprint.
- Grok Bot.
- Shopify.
- Facebook.

## ASK / UNRESOLVED

- YouMind.

## Architectural decisions still open

- Computer-use lineage.
- Dormant Atlas surfaces.

Do not silently resolve these.

---

# 14 — ARCHITECTURAL GUARDRAILS

1. **No second orchestrator.**
2. Approval is not execution.
3. No arbitrary external side effects.
4. SMTP transport is not unrestricted dispatch.
5. Preserve the canonical outreach path.
6. Do not duplicate policy/guards inside transports.
7. Exact approved message/version must be bound to send.
8. Prevent duplicate sends.
9. Credentials never enter source code.
10. Probes do not equal production capability.
11. Local tests do not equal production evidence.
12. Documentation/declarations do not equal functionality.
13. Dormant code must not be revived accidentally.
14. Do not refactor unrelated systems for cleanliness.
15. Do not expand scope without a product decision.
16. Evidence must remain traceable.
17. Unknown remains unknown.
18. Never guess external identities or destinations.
19. Read-only paths must actually be read-only.
20. Important business history remains append-only.
21. Worker capabilities are derived, not manually duplicated.
22. Mission routing must be explicit.
23. UI/session must not own the execution lifecycle.
24. Deployment must ship every changed runtime file or fail.
25. Never manufacture customer, payment, conversion, revenue, ROI, or engagement evidence.
26. External actions require stronger approval boundaries.
27. A registered worker is not automatically eligible for Qevik mission execution.
28. Capability is not permission.
29. Worker failure must not corrupt mission state.
30. Blocked external work must not block unrelated unblocked work.

---

# 15 — CURRENT EXECUTION POSITION

**CURRENT MILESTONE:**  
P2 — Distributed Execution Fabric / Capability-Matched Dispatch

**CURRENT OBJECTIVE:**  
Deploy the implemented capability-matched dispatch boundary and prove it against real production workers/missions.

**COMPLETED:**  
Mission ledger, mission reports, worker identity, heartbeat, resources, capability derivation, execution-dispatch boundary, explicit routing, unrouted-mission blocking, local capability-matched dispatch.

**IN PROGRESS:**  
Production deployment/proof of capability-matched dispatch.

**BLOCKED BY:**  
No architectural blocker. Deployment integrity must be verified before production status is claimed.

**NEXT IMPLEMENTATION:**  
Deploy the capability-matched dispatch slice and run the production verification gate.

**NEXT EXTERNAL ACTION:**  
No new external credential is required for this proof. HP/Lenovo can be attached after the production dispatch boundary is proven.

**PRODUCTION EVIDENCE REQUIRED:**  
Changed runtime files shipped; worker registration correct; fingerprint correct; capability advertisement correct; placement correct; stale/busy behavior correct; capability subset matching correct; scheduler/worker agreement; unrouted mission blocked; claims untouched; no fallback; no cross-lineage dispatch; services healthy.

**DO NOT START YET:**  
Real HP/Lenovo deployment before dispatch proof; GPU media generation; image/video/music providers; app/game factories; marketplace execution; complex billing; YouMind; dropped integrations; speculative computer-use adoption.

**OWNER DECISIONS REQUIRED:**  
Computer-use lineage; dormant Atlas surfaces; media providers; local/cloud media policy; outreach policy; audiobook policy when reopened; YouMind; final pricing/economics; App/Game factory architecture.

---

# 16 — MASTER CHANGELOG

## Foundation

- Qevik established as an evidence-driven autonomous business-production system.
- Business discovery and opportunity engine established.
- Evidence/verification model established.
- Mission/recipe/agent/tool execution model established.

## Website commercial loop

- Website generation implemented.
- Real business website generated.
- Read-only artefact review implemented.
- Exact commit-bound review implemented.
- Accepted-artifact queue implemented.
- Website publication implemented.
- Publication completion recording implemented.
- Outreach preparation implemented without sending.

## Mission persistence

- Mission ledger moved from local JSONL to PostgreSQL.
- Timestamp tie defect discovered and corrected through real-data equivalence testing.
- Mission reports moved to an insert-only PostgreSQL store.
- Cross-process report access proven.

## Fabric discovery and integration

- Audit discovered the existing Atlas worker registry/heartbeat/lease/dispatcher lineage.
- Earlier "not started" assessment was corrected.
- Decision made to reuse Atlas worker identity/heartbeat rather than create a second registry.
- Qevik workers registered per process.
- Worker resources and capabilities added.
- Heartbeat separated from mission claim staleness.
- Execution-dispatch boundary introduced.
- Deployment fingerprinting introduced.
- Explicit agent routing introduced.
- Scheduler made authoritative for unrouted missions.
- Capability-matched dispatch implemented and locally gated.

## Product scope consolidation

Retained:

- business intelligence;
- Google business data;
- websites;
- SEO;
- digital products;
- CRM/lead generation;
- ecommerce;
- affiliate;
- UGC;
- media;
- voice;
- books/audiobooks;
- browser/computer use;
- apps;
- games;
- Amazon;
- Noon;
- YouTube;
- Instagram;
- advertising;
- billing;
- credits;
- usage;
- customer platform;
- distributed workers.

Decisions:

- Audiobook: DEFERRED.
- Character Sheet: DEFERRED.
- TikTok: DEFERRED.
- Steam: DEFERRED.
- Creative Blueprint: DROPPED.
- Grok Bot: DROPPED.
- Shopify: DROPPED.
- Facebook: DROPPED.
- YouMind: UNKNOWN / REQUIRES PRODUCT DECISION.

## Operating principle

The project repeatedly established:

> Build the smallest capability that establishes one real boundary, prove it against production data, and only then open the next boundary.

And:

> Optimize for commercial usefulness, not technical novelty.

---

# AUTHORITATIVE STATUS RULE

Future implementation sessions must:

1. Read this file first.
2. Inspect the actual repository state.
3. Reconcile roadmap status with real implementation evidence.
4. Never create a competing roadmap.
5. Update this roadmap when milestone status changes.
6. Preserve historical decisions, dropped items, deferred items, blockers, and unresolved decisions.
7. Distinguish:
   - CONFIRMED
   - EVIDENCED
   - IMPLEMENTED
   - PRODUCTION-PROVEN
   - DESIGNED
   - DEFERRED
   - DROPPED
   - UNKNOWN
   - REQUIRES PRODUCT DECISION
8. Never treat a test, declaration, prototype, credential probe, or document as production capability without corresponding evidence.
9. Keep independent blockers isolated from unrelated work.
10. Preserve the Qevik control-plane architecture and **NO SECOND ORCHESTRATOR** rule.

The roadmap is complete only when it remains synchronized with the actual system.
