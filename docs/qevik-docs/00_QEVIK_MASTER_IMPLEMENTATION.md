# QEVIK — MASTER IMPLEMENTATION INSTRUCTIONS

## Current state

- P0 Research Engine: COMPLETE
- P1.1 Tenancy / production safety: COMPLETE
- P1.2 onward: NOT YET IMPLEMENTED

This is the master execution contract. Inspect the repository and verify actual implementation before changing code.

## 1. Product thesis

Qevik is a closed-loop digital growth and execution platform:

**Research → Evidence → Opportunity → Recommendation → Approval → Job → Execution → QA → Publish → Measurement → Re-evaluation**

Every capability must plug into this loop.

The platform must answer:
1. What is the current state?
2. What evidence supports it?
3. What could improve?
4. What does Qevik recommend?
5. What can Qevik execute?
6. What requires approval?
7. What job ran?
8. What assets were produced?
9. Did QA pass?
10. Was anything published?
11. What happened afterward?
12. What should happen next?

## 2. Non-negotiable rules

### Inspect before implementing
- Inspect existing repository, models, services, registries and vocabularies.
- Reuse existing abstractions.
- Do not create duplicate registries.
- Existing production vocabulary and immutable history win over document terminology.

### Production safety
Never:
- modify production data without explicit authorization;
- connect an external provider without explicit authorization;
- publish without the required approval;
- charge credits without an auditable metering event;
- delete/rewrite historical evidence.

Tests must never connect to production.

### Evidence honesty
A failure to measure is not proof of absence.

Failed research stages emit `UNVERIFIED`, never `NOT_FOUND`.

A strong company may legitimately produce:

**STRONG BUSINESS + LIMITED WEBSITE OPPORTUNITY**

### Causality
Record baseline, intervention, measurement window, observed change and attribution confidence. Do not claim Qevik caused an outcome unless evidence supports it.

## 3. Execution behavior

For each phase:
1. Inspect the implementation.
2. Read the relevant phase document.
3. Reconcile it against actual code.
4. Produce a short implementation plan.
5. Identify genuine blockers.
6. If there is no blocker, implement.
7. Run focused tests and negative controls.
8. Run the full suite where appropriate.
9. Perform browser QA for UI changes.
10. Report exact changes and verification.
11. Continue to the next sub-phase.

Do not stop merely because an architecture report has been completed.

Stop only for:
- an actual user decision;
- an irreversible production action requiring approval;
- missing credentials/permissions;
- safety/security ambiguity;
- destructive migration uncertainty;
- an architectural conflict that cannot be resolved from existing rules.

## 4. Customer Task vs Qevik Task

### CUSTOMER_TASK
Things the customer must do because Qevik cannot legitimately do them:
- create an Instagram account;
- connect a payment gateway;
- grant ad/analytics access;
- provide brand assets;
- approve publication;
- verify an account.

### QEVIK_TASK
Things Qevik can execute:
- audit;
- generate pages;
- generate assets;
- optimize SEO;
- research AI visibility;
- generate ads;
- enrich leads;
- prepare marketplace listings;
- run QA;
- measure outcomes.

The 0→100 roadmap must contain both.

## 5. 0→100 roadmap

The roadmap derives from:
- research/evidence;
- business model;
- opportunities;
- capabilities;
- goals;
- dependencies;
- customer tasks;
- Qevik tasks;
- measurement.

Potential dimensions:
website, UX, technical health, SEO, AI visibility, entity presence, content, image, video, social, ecommerce, marketplaces, advertising, leads, CRM, email, analytics, conversion, automation.

Unmeasured does not mean bad. Low confidence is different from a low score.

## 6. Public audit

Eventually support:

**qevik.ai → enter website → audit → evidence → opportunities → capabilities → plans**

It must demonstrate value without exposing sensitive data or unsupported claims.

## 7. Customer portal

Eventually support:
- audit/evidence;
- opportunities/recommendations;
- roadmap;
- customer/Qevik tasks;
- jobs;
- assets;
- approvals;
- publication;
- usage/credits;
- reports;
- measurement/ROI.

## 8. Capability architecture

A capability is something Qevik can execute.

Publication destinations are not automatically separate capabilities. For example, social platforms and Amazon/Noon are targets/integrations.

Reuse the existing CapabilitySpec/Registry. Commercial `CapabilityOffer` may define:
- capability;
- plan availability;
- credit cost;
- required inputs;
- approval;
- QA;
- publication targets;
- provider requirements;
- measurement.

Do not create a second capability registry.

## 9. Assets

Reuse the existing asset graph and provenance:
- source/derived relationships;
- versions;
- content hashes;
- run/job linkage;
- provider information.

Add rights/provenance controls where required.

## 10. Approval

Use two layers:
1. Policy: whether automation is allowed.
2. Act-level gate: consent for the specific action when required.

## 11. QA

Every capability needs an appropriate QA contract. Publication must be blocked when required QA fails.

## 12. Providers

Reuse the existing provider abstraction. Never hard-code a provider into the core capability model. Do not assume an external API or permission exists until verified.

## 13. Credits/plans

Reuse QuotaLedger and reserve-before-act. Do not create a parallel credit ledger.

Eventually support:
- List;
- Pro;
- Advanced;
- Enterprise.

Do not connect billing providers until explicitly authorized.

## 14. Multi-account content factory

Support owned/authorized channels and characters with explicit:
- owner;
- platform/account;
- character;
- policy;
- visual identity;
- schedule;
- approval;
- publication target;
- analytics.

No deceptive identity, fake endorsements, undisclosed impersonation or platform-rule evasion.

## 15. Characters

Reusable character profiles may contain:
identity, appearance, voice, tone, visual style, camera language, shot types, movement, scene templates, continuity and asset references.

## 16. Ecommerce

Support the architecture:

**Research → Product Opportunity → Listing → Images → Video → SEO → QA → Approval → Publish → Ads → Measurement → Optimization**

Never assume Amazon/Noon API access.

## 17. Media Factory

**Research → article → image → short videos → social → carousel → email → landing page → affiliate content → ad creatives**

Outputs must remain linked to source research/opportunity/job.

## 18. AI Search / LLM visibility

First-class measurement category. Record:
- query;
- system/engine;
- timestamp;
- result;
- mention;
- citation/source where available;
- competitor presence;
- recommendation;
- confidence.

Keep systems separate. Never convert an AI mention into a Google-style ranking.

Support businesses, brands, products, services, locations and category queries.

Examples:
- best iPhone charger in Dubai;
- best camping brand UAE;
- best catering company Dubai.

## 19. Leads / CRM / Email

Support prospect discovery, enrichment, qualification, B2B research, provenance, lead scoring, CRM integration and email workflows.

Prefer integration with an existing CRM over building an entire CRM unless explicitly approved.

## 20. Website execution

Support:
- information architecture;
- multi-page generation;
- content;
- design system;
- responsive design;
- SEO/schema;
- forms;
- analytics;
- conversion journeys;
- QA;
- deployment abstraction.

A website project should generate a next-step roadmap.

## 21. Roadmap engine

A roadmap is a product feature, not a generic checklist. It uses evidence, goals, opportunities, capabilities and dependencies.

Roadmap regeneration must not silently invalidate an active customer plan.

## 22. Case studies

Test architecture against:
1. AHS — premium catering / strong brand.
2. Coffee shop — local B2C.
3. Ecommerce seller — Amazon/Noon.
4. B2B company.
5. Logistics company.
6. Lead-generation/CRM business.
7. Small service business.

Recommendations must differ based on evidence/business model.

## 23. Security

Enforce tenancy at repository/data layer, not UI filtering.

Keep house-level suppression separate from tenant-scoped contact history.

Protect external credentials and never expose them in customer reports.

## 24. Definition of done

A phase is complete only when implementation, focused tests, negative controls, relevant integration/browser QA, tenancy checks, evidence semantics and rollback are verified.
