# Qevik — strategic north star

Recorded 2026-09-01 as product direction. **Not a backlog.** Nothing here is
built speculatively; work is ranked by production evidence and real demand, and
the queue finishes first.

## What Qevik is becoming

Not "software that gives a business marketing tools" but

> an AI growth team that understands my business, tells me what matters, does
> the work it can do, brings in a human when necessary, and shows me the result.

The target is roughly **1,000 high-value customers**, not 10,000 low-value SaaS
seats. That changes what is worth building: depth of understanding per business
beats breadth of self-serve features.

## The customer journey

    onboarding / business discovery
    → connectors
    → business audit ("business brain")
    → growth plan — the five highest-value things, with evidence
    → plan tier
    → execution, AI or human
    → measurement
    → next opportunity

### Onboarding
Identity, industry, locations, website, Google ecosystem, Search Console,
Analytics, Meta, Instagram, LinkedIn, email systems, advertising accounts,
marketplaces, CRM, ecommerce, other supported connectors. Never assume the
customer has any of them.

### Connectors
For anything unconnected, say what it is, why it matters, what Qevik could do
with it, how to connect it, and what to do without it.

### Audit
Website, SEO, Google and AI visibility, reviews, social, advertising, email,
conversion, ecommerce, Amazon, content, competitors, analytics, acquisition,
retention — each labelled KNOWN / OBSERVED / VERIFIED / NOT VERIFIED /
NOT CONNECTED / REQUIRES CUSTOMER INPUT. **Never invented.**

### Growth plan
Five things, not fifty. Each with evidence, business purpose, dependencies,
what Qevik can do automatically, what needs approval, what needs a specialist,
what needs a connection, and effort where it can be supported.

### Plans
SILVER intelligence · GOLD AI execution · PLATINUM AI plus specialists ·
ENTERPRISE custom. **Pricing is a separate commercial decision and is not
invented here.**

### Factories
Website, web apps, mobile, video/UGC, image and content, SEO, Google Business,
advertising, email, social, marketplace, ecommerce, CRM, service and sales
automation, analytics. Qevik need not build every primitive — external
providers are execution infrastructure. What is Qevik's own is the loop:

    UNDERSTAND → DECIDE → APPROVE → ORCHESTRATE → EXECUTE → QA → DELIVER
    → MEASURE → IMPROVE

### Hybrid execution
Every task classified as deterministic, AI-executable, needs customer input,
needs approval, needs a Qevik specialist, blocked on a credential, or
externally irreversible. Humans take over what needs expertise.

### Assistant
Contextual, never generic. It answers from the customer's own audits,
connectors, opportunities, active work and results, and separates fact from
recommendation.

### Customer UX
Overview, business health, growth plan, opportunities, work in progress,
results, connectors, reports, content, website, ads, Amazon, email, social,
assistant, billing, help — revealed progressively. **The current dark operator
console is not the customer aesthetic.**

## The architectural rule this rests on

Extend the existing pattern; do not build a parallel one:

    discovery → evidence → opportunity → approval → mission → worker
    → artefact → QA → review → publication → outreach

And preserve, without exception: evidence discipline, append-only history,
explicit approval boundaries, human actions, credential boundaries, production
verification, objective gates, adversarial review, production-data-driven
prioritisation, no invented facts, and no autonomous irreversible external
action.

## How this becomes work

It does not, by itself. Slices are selected when production evidence or real
customer demand ranks them, and the ordering constraint is recorded in
`QEVIK_CUSTOMER_PLATFORM_RECONCILIATION.md`: Qevik has 412 audited businesses,
5 published artefacts, 16 drafts and **0 sent**, so the journey above has no
occupant until one message reaches one business. That is HA-001 and HA-002.
