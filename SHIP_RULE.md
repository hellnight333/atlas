# SHIP-1

**Atlas exists to build businesses, not software.**

Software is only valuable when it creates, deploys, operates, grows or automates a
business.

Whenever there is a choice between:

- another abstraction
- another architectural improvement
- another framework
- another internal refactor
- another generic capability

versus

- shipping a product
- deploying a website
- generating content
- acquiring customers
- discovering opportunities
- reducing manual work
- increasing revenue

**always prefer shipping.**

---

## Priority order

Every proposed milestone is evaluated in this order:

1. Revenue generated
2. Hours of manual work eliminated
3. Products shipped
4. Customers acquired
5. Reach increased
6. Architecture improved

Architecture exists to enable shipping. **Architecture is never the product.**

---

## Decision rule

When choosing between two implementations, ask:

> Which implementation gets something into the real world sooner **while preserving
> the long-term architecture?**

Choose that one.

Never build the general solution simply because it might be useful someday. Build the
smallest solution that naturally evolves into the larger architecture.

---

## What counts as shipping

Publishing videos · deploying websites · launching SaaS products · generating Amazon
listings · publishing podcasts · deploying APIs · finding leads · preparing proposals
· sending approved outreach · deploying customer solutions.

Internal work counts as shipping **only if it removes a blocker preventing one of the
above.**

| | |
|---|---|
| ✓ | Fixing a crash preventing Atlas from opening |
| ✓ | Fixing deployment so websites can actually be published |
| ✓ | Repairing a database corruption bug |
| ✗ | Rewriting a module because it "looks cleaner" |
| ✗ | Generalising an abstraction with no immediate user |

---

## Long-term objective

Atlas should eventually become an autonomous AI operating system capable of building,
deploying, operating and growing digital businesses.

Long-term factories: Media · Website · Amazon · AI SaaS · Opportunity · Browser Agent
· Computer Agent · Deployment · SSH Infrastructure Manager · Business Automation ·
Multi-model AI Orchestrator.

**These are destinations. They are NOT today's backlog.** The existence of these
destinations must never justify premature architecture.

The invariants that keep them reachable — content independent from rendering,
providers disposable, capabilities never vendor-bound, workers stateless, everything
reproducible, irreversible actions gated by approval — are in `PROJECT_MEMORY.md` →
Long-term vision. They cost a design choice, not a milestone. The moment one becomes a
project of its own, SHIP-1 wins and it waits until something real needs it.

---

## Revenue-first roadmap

**Whenever current work is blocked** — hardware, credentials, APIs — Atlas identifies
the highest-ROI work that can continue immediately, in this preference order:

1. Something that can make money
2. Something that removes hours of manual work
3. Something that publishes products automatically
4. Something that improves internal architecture

A blocked milestone is never a reason to fall through to (4) by default.

---

## Permanent rule

Atlas is **not** measured by lines of code, abstractions, design patterns or
architectural elegance.

Atlas is measured by **businesses created, products shipped, customers acquired,
recurring revenue generated, and manual work eliminated.**

**This rule overrides all roadmap decisions whenever priorities conflict.**

One caveat worth stating, because it is the only way this rule gets misused: it bites
hardest exactly when the architecture work feels obviously correct. That is the signal
to check it against the priority order, not the exemption from it.
