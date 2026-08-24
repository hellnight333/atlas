# P1 Architecture Review — Resolve Before Implementation

## Status

**Architecture review only.**

Do **not** implement anything yet.

Do not modify production code, database schema, migrations, provider connections, customer accounts, jobs, or production data.

Review `P1_EXECUTION_ARCHITECTURE.md` against the existing Qevik codebase and produce:

`P1_ARCHITECTURE_REVIEW.md`

The purpose is to find architectural gaps, contradictions, missing capabilities, and decisions that would become expensive to change after implementation.

Do not merely agree with the existing architecture. Challenge it.

---

# 1. Complete Qevik Lifecycle

Show the canonical lifecycle:

```text
Public Audit
    ↓
Research
    ↓
Evidence
    ↓
Opportunity
    ↓
Recommendation
    ↓
Capability
    ↓
Customer Approval
    ↓
Credit / Quota Check
    ↓
Job
    ↓
Execution
    ↓
Asset
    ↓
QA
    ↓
Approval
    ↓
Publish
    ↓
Measurement
    ↓
Re-evaluation
    ↓
New Opportunity
```

For every transition, specify:

- input
- output
- authoritative data structure
- event recorded
- permission required
- whether customer approval is required
- whether credits are consumed
- failure behaviour
- rollback behaviour

There must be **one canonical path**, not separate workflows invented by individual product families.

---

# 2. Find Every Existing Duplicate Registry

Search the entire repository for:

- job states
- asset states
- approval states
- permission systems
- quotas
- credits
- plans
- capabilities
- providers
- organizations
- users
- customer accounts
- businesses
- recommendations
- opportunities
- events
- audit records
- media jobs
- publishing jobs
- analytics
- measurements

Produce:

| Concept | Existing implementations | Authoritative implementation | Duplicate? | Action |
|---|---|---|---|---|

Do not create another registry merely because an existing one is inconvenient.

---

# 3. Capability Architecture

Define exactly what a Qevik `Capability` is.

Examples to investigate:

```text
website.build
website.optimize
seo.audit
seo.optimize
ai_visibility.audit
ai_visibility.optimize
blog.generate
image.generate
image.enhance
image.crop
video.generate
video.ugc
social.publish
amazon.listing.create
amazon.listing.optimize
amazon.image.generate
amazon.ads.prepare
lead.find
lead.enrich
crm.manage
email.generate
email.send
affiliate.content.generate
```

Do not assume this vocabulary is correct.

Determine:

- capability ID
- version
- required providers
- required integrations
- required permissions
- required inputs
- outputs
- estimated cost
- credit cost
- human approval requirement
- QA requirements
- publication targets
- measurement requirements
- supported business types
- availability by plan

A capability must describe **what Qevik can actually do**, not what Qevik merely recommends.

---

# 4. Recommendation Architecture

Define:

```text
Opportunity → Recommendation → Capability → Job
```

A recommendation must answer:

- What did we discover?
- Why does it matter?
- What can Qevik do about it?
- Which capability would execute it?
- Expected inputs
- Expected outputs
- Estimated cost
- Credit requirement
- Expected measurement
- Approval requirement
- Risk
- Confidence
- Evidence

Example:

```text
Opportunity:
AHS has 32 portfolio/event pages that are difficult to discover.

Recommendation:
Create a structured portfolio system with category filters,
case-study metadata and stronger internal linking.

Capability:
website.portfolio_upgrade

Evidence:
research:event-portfolio-001

Approval:
required

Expected measurement:
portfolio engagement / enquiry conversion / organic landing traffic
```

Ensure recommendations cannot bypass evidence.

---

# 5. Customer Portal

Do a full architecture for:

```text
qevik.ai/customer
```

Determine whether it should be:

- a new application
- an extension of the existing control application
- or a shared application with role-based views.

Design:

- Overview
- Audit
- Opportunities
- Recommendations
- Jobs
- Assets
- Approvals
- Website
- SEO
- AI Visibility
- Content
- Social
- Ecommerce
- Leads
- CRM
- Email
- Advertising
- Analytics
- Credits
- Billing
- Integrations
- Settings

Do **not** automatically expose every module to every customer.

Define feature visibility by plan.

---

# 6. Plans

Design the capability matrix for:

- LIST
- PRO
- ADVANCED
- ENTERPRISE

For each plan define:

- research limits
- audit depth
- opportunities
- SEO
- AI visibility
- blog generation
- image generation
- video generation
- social accounts
- ecommerce products
- Amazon
- Noon
- advertising
- leads
- CRM
- email
- analytics
- automation
- API
- white-label
- support
- credits

Do not choose arbitrary limits merely to fill a table.

Explain the commercial logic behind each limitation.

---

# 7. Credit Architecture

We already have `QuotaLedger`.

Determine whether it can safely support:

```text
research credits
image credits
video credits
AI generation credits
lead credits
enrichment credits
SEO credits
content credits
marketplace credits
```

without creating another ledger.

Define:

```text
reserve
→ execute
→ consume
```

and:

```text
reserve
→ fail
→ release
```

Also handle:

- partial jobs
- retries
- cancellations
- refunds
- failed provider calls
- provider cost changes
- concurrent jobs
- customer purchasing additional credits
- monthly plan allowance
- rollover
- expiration

No implementation yet.

---

# 8. Public Qevik Audit

Design:

```text
qevik.ai
↓
Enter URL / business / brand / product
↓
Quick Audit
↓
Score / Findings
↓
Opportunities
↓
"What Qevik can do"
↓
Potential value
↓
Create account
↓
Full report
↓
Plans
```

The public audit must provide enough value to demonstrate Qevik without exposing:

- sensitive data
- competitor private information
- internal prompts
- private research
- credentials
- proprietary scoring details
- unsupported claims

Also determine what is free versus credit-consuming.

---

# 9. AI Search / LLM Visibility

Treat AI/search visibility as a first-class research and optimization category.

Support queries such as:

```text
best catering company Dubai
best coffee shop Dubai
best logistics company UAE
best camping brand UAE
best charger brand UAE
best iPhone charger Dubai
best power bank UAE
best corporate catering Dubai
best B2B logistics UAE
best catering in Dubai Marina
```

Record separately for supported systems:

- Google
- Bing
- ChatGPT
- Claude
- Gemini
- other supported systems

Do not call something a "ranking" unless the system actually provides a ranking.

Define:

- mention
- citation
- recommendation
- position
- source
- competitor
- sentiment
- entity recognition
- confidence
- timestamp
- query
- engine

Also design:

```text
measure
→ diagnose
→ recommend
→ optimize
→ re-measure
```

---

# 10. Entity / Knowledge Graph Strategy

Determine whether Qevik should maintain structured representations of:

```text
Business
Brand
Product
Service
Person
Location
Organization
Website
Social profile
Marketplace listing
```

and their relationships.

Example:

```text
AHS
 ├── Brand
 ├── Website
 ├── Instagram
 ├── LinkedIn
 ├── Catering Services
 ├── EATLUX
 ├── Dubai
 ├── Portfolio
 └── Products/Services
```

Explain whether this belongs in:

- Research
- SEO
- AI Visibility
- or a shared kernel primitive

Do not introduce a graph database unless the existing architecture actually requires one.

---

# 11. Media Factory

Design:

```text
Research Topic
       ↓
      Brief
       ↓
 ┌─────┼────────┐
 ↓     ↓        ↓
Article Image  Video
 ↓     ↓        ↓
Email Social Carousel
 ↓
Landing Page
 ↓
Affiliate Content
 ↓
Ad Creative
```

Every asset needs:

- owner
- source
- provenance
- parent asset
- version
- provider
- prompt/brief where appropriate
- copyright status
- permission
- QA status
- approval status
- publication status

---

# 12. Character / Video Factory

Design reusable:

- character
- voice
- visual identity
- wardrobe
- environment
- camera language
- shot types
- camera movement
- scene templates
- continuity
- audio
- subtitles
- aspect ratios
- platform variants

A character must be reproducible across hundreds of videos.

Distinguish:

```text
customer-owned character
Qevik-owned character
licensed character
generated original character
```

and define rights/provenance.

---

# 13. Multi-Account Social Factory

Design the architecture for:

```text
7 Instagram accounts
7 characters
7 content identities
7 publishing calendars
7 analytics streams
```

with:

```text
research
→ script
→ generate
→ QA
→ approval/autopilot
→ schedule
→ publish
→ analytics
→ re-evaluate
```

Do not design this around undisclosed ownership or deceptive behaviour.

Define platform integration requirements and what can/cannot be automated.

---

# 14. Ecommerce Factory

Design:

```text
Product Research
↓
Opportunity
↓
Product Selection
↓
Listing Creation
↓
Title
↓
Bullets
↓
Description
↓
Keywords
↓
Images
↓
Lifestyle Images
↓
Comparison Graphics
↓
Video
↓
A+ / Enhanced Content
↓
Listing QA
↓
Publish
↓
Ads
↓
Measurement
↓
Optimization
```

Support Amazon and Noon architecturally without assuming API access.

Define what happens when API access is unavailable.

---

# 15. Lead Generation / CRM

Design:

```text
Research
→ ICP
→ Prospect discovery
→ Enrichment
→ Qualification
→ Lead
→ CRM
→ Outreach
→ Response
→ Opportunity
→ Customer
```

Include:

- B2B
- B2C
- local businesses
- ecommerce
- logistics
- agencies
- service companies

Determine whether Qevik should build its own CRM or integrate with external CRMs.

Do not decide merely from convenience.

---

# 16. Measurement

Measurement must be a first-class object.

Define:

```text
Metric
Baseline
Intervention
Measurement Window
Observed Result
Attribution Confidence
Evidence
```

Examples:

```text
AI mentions: 22 → 47
organic leads: 34 → 61
CTR: 2.1% → 3.4%
CPA: $18 → $13
portfolio engagement: +32%
qualified leads: +21%
```

Never automatically say:

> Qevik caused this increase.

Instead distinguish:

```text
Observed
Associated
Attributed
Experimentally supported
Unknown
```

---

# 17. Autopilot

Define exactly what can happen without approval at:

- List
- Pro
- Advanced
- Enterprise

Especially:

- spending money
- publishing
- sending emails
- posting social content
- changing websites
- changing marketplace listings
- launching ads
- generating assets
- consuming credits

Use conservative defaults and justify the architecture.

---

# 18. Security and Tenant Isolation

Assume Qevik eventually has:

```text
100 customers
1,000 customers
10,000 customers
```

Define isolation for:

- businesses
- assets
- prompts
- generated media
- credentials
- integrations
- jobs
- credits
- reports
- analytics
- CRM records

A customer must never be able to access another customer's assets or evidence.

---

# 19. Case Studies

Run the architecture conceptually against:

1. AHS — premium catering / strong company
2. Coffee shop
3. Ecommerce seller
4. B2B company
5. Logistics company
6. CRM/lead-generation company
7. Small service business

For each, show:

```text
Research
→ Opportunities
→ Recommendations
→ Capabilities
→ Jobs
→ Assets
→ Measurement
```

The outputs must be materially different.

Especially show how AHS can produce:

> STRONG BUSINESS + LIMITED WEBSITE OPPORTUNITY

without inventing weaknesses.

---

# 20. Commercial Product Architecture

Explain how Qevik eventually becomes more than a website agency.

The customer should understand:

> Qevik continuously researches my business, identifies opportunities, recommends actions, executes approved work, measures the result, and finds the next opportunity.

Design the product around this concept rather than around individual tools.

---

# 21. Final Architectural Challenge

At the end, provide:

### A. What should be built first?

### B. What should explicitly NOT be built yet?

### C. What existing Qevik code should be reused?

### D. What existing code should be refactored before P1?

### E. What architectural decisions would become expensive to change later?

### F. What is the minimum viable P1?

### G. What is the 12-month architecture?

### H. What could make Qevik fail technically or commercially?

### I. What three things would make Qevik genuinely difficult for competitors to copy?

---

# Strict Constraints

Do not:

- write production code
- modify production code
- modify the database
- create migrations
- connect providers
- create customer accounts
- run production jobs
- change production data
- change existing registries
- rename historical states
- create parallel vocabularies

Only produce:

`P1_ARCHITECTURE_REVIEW.md`

The report must reference the actual existing Qevik architecture and code rather than inventing a greenfield system.

The goal is one coherent execution architecture supporting:

- websites
- SEO
- AI/LLM visibility
- content
- images
- video
- social
- ecommerce
- Amazon
- Noon
- advertising
- leads
- CRM
- email
- affiliate content
- customer portals
- credits
- analytics
- autopilot
- agency/white-label

without turning Qevik into a collection of unrelated tools.

**Stop after producing the report and wait for review.**
