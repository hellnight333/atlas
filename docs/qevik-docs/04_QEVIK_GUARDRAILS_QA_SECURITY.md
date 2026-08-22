# QEVIK — GUARDRAILS, QA, SECURITY & MEASUREMENT

## Evidence
Use:
- PRESENT
- NOT_FOUND
- UNVERIFIED
- REFUTED where existing verification supports it.

Timeout/failure is not proof of absence.

## Tenancy
Enforce at repository/data layer, not UI.
Tenant must be explicit where required.
Cross-tenant reads should behave as absence where appropriate.
Aggregates must not leak other tenant volume.
Suppression remains house-level.
Contact history remains tenant-scoped.

## Approval
Two layers:
1. Policy: may this class of action be automated?
2. Act-level gate: customer consent for the specific act when required.

## Credits
Use reserve-before-act.
Failed/cancelled actions must not silently consume permanent credits.
Every credit event is auditable.

## Website QA
Where applicable:
status, redirects, TLS, broken links/assets, responsive layout, console errors, metadata, canonical, hreflang, structured data, forms, tracking, accessibility, performance.

## Content QA
Factual consistency, brand consistency, duplicate content, unsupported claims, links, formatting, disclosures.

## Image QA
Dimensions, aspect ratio, quality, artifacts, brand/product correctness, rights/provenance, duplicates.

## Video QA
Duration, resolution, aspect ratio, audio, captions, continuity, character consistency, policy/platform requirements.

## Marketplace QA
Title, bullets, description, keywords, category, images, variants, required attributes and marketplace-specific rules.

## Ad QA
Destination, creative dimensions, copy, tracking, campaign fields, budget, policy-sensitive claims.

## Social QA
Target account/platform, content, caption, media dimensions, schedule, approval, disclosure.

No fake engagement, fake endorsements, deceptive identity or platform-rule evasion.

## Measurement
Every intervention defines:
- baseline;
- intervention;
- measurement window;
- observed result;
- attribution confidence.

Example:
"AI visibility mention rate increased from 22% to 47% during the measurement window."

Do not automatically say:
"Qevik increased AI visibility by 25%."

## Negative controls
Test that removing a guard would fail:
- production DB access from tests;
- cross-tenant reads;
- cross-tenant aggregates;
- unauthorized publication;
- credit spend without reservation;
- failed research becoming NOT_FOUND;
- unsupported AI ranking claims;
- unsupported causal claims.

## Rollback
Every production phase must document:
- exact changes;
- reversal;
- historical-data impact;
- append-only event behavior;
- deployment rollback;
- external publication reversal where relevant.

Git revert alone is not a sufficient rollback plan when data/external systems changed.

## Definition of done
Implementation + focused tests + negative controls + integration/browser QA + tenancy checks + evidence semantics + rollback understanding.
