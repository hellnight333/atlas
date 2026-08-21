# Gap analysis — master digital-product workflow vs. what exists

Written against `QEVIK_MASTER_DIGITAL_PRODUCT_WORKFLOW.md` §36.7, before any
implementation. Every row was checked in the repository or against the live
system on 2026-08-22; nothing here is assumed from a previous report.

The headline: **P0 is roughly two-thirds built.** What is missing is not the
opportunity engine or the demo layer — those ship and are tested. It is the
research layer underneath them.

---

## 1. The single most important gap

`packages/kernel/atlas_kernel/opportunity/website_audit.py` says so itself:

> "Nothing here crawls a site, follows a sitemap or touches anything a
> `robots.txt` would speak to."

It audits **one page of HTML**. Nineteen features, all derived from a single
document.

Everything that made the AHS work valuable came from somewhere else: their
WordPress REST API returned sixty pages and four posts, which is how the 32
event pages, 170 photographs, 501-item media library, the buried client list and
the thin blog were found. **A person ran that in a shell.** It is not a product
capability, so it does not happen for prospect 2 through 1,100.

That is the gap that makes §2 real. Until it closes, every other research
category is reasoning from a homepage.

---

## 2. P0 status (§33)

| P0 item | State | Evidence |
|---|---|---|
| Stabilize dashboard | **DONE** | 500 fixed, `_safe` degradation, 100/100 prospects 200, 38 browser assertions |
| Missing Digital Opportunity | **DONE** | `outreach/opportunity.py` — 8 rules, 49 products, 8 families, evidence-gated |
| Multi-page demos | **PROVEN ONCE** | AHS: 102 routes, 2 languages, own generator. 13 other samples are single files |
| Media permission | **DONE** | 4 states, event-sourced, hard gate |
| QA | **DONE** | 86 browser assertions on AHS, 38 static, differentiation 0.55 vs 0.62 |
| Prospect-specific demos | **DONE** | one registry, classification gates outreach language |
| Truthful outreach | **DONE** | `consistency.check`, three-state evidence, overclaim gate |
| **Deep research architecture** | **MISSING** | single-page audit only; no crawl, no CMS API |
| **Website intelligence** | **PARTIAL** | 19 HTML features; no speed class, console errors, broken links, redirects, TLS |
| **SEO checks** | **PARTIAL** | title/meta/h1/alt/structured-data exist as flags; no SEO category, no content or visibility analysis |
| **UX checks** | **MISSING** | no journey model per business type (§4) |
| **Market-position checks** | **MISSING** | `opportunity/market.py` grades *niches for market selection*, not competitors per prospect |

### What already exists and must not be rebuilt (§36.5)

- `research/` — `web.search` capability via Brave, vendor-neutral
- `opportunity/market.py` — niche/geography viability, measured not argued
- `opportunity/website_audit.py` — the single-page checks, three-state semantics
- `Business` / `BusinessEvent` — one customer entity, append-only timeline
- `outreach/demos.py` — the one demo registry
- `infra/differentiation.py` — structural fingerprinting

---

## 3. Vocabulary conflicts — decisions, not gaps

The document proposes vocabularies that differ from ones already shipped,
tested, and in production event history. §36.5 forbids duplicate registries, so
these must be reconciled deliberately rather than by adding a second set.

| Concept | Shipped | Document | Overlap |
|---|---|---|---|
| Demo classes | `GENERIC_SAMPLE` · `INDUSTRY_CONCEPT` · `PROSPECT_INSPIRED` · `PROSPECT_REBUILD` · `CLIENT_APPROVED_REBUILD` | §10: `REBUILD` · `PROSPECT_INSPIRED` · `PRODUCT_CONCEPT` · `CAPABILITY_DEMO` · `INTERNAL_DEMO` | 1 of 5 |
| Job states | `DRAFT` · `QUEUED` · `RUNNING` · `QA` · `READY` · `FAILED` · `CANCELLED` | §24: `QUEUED` · `RESEARCHING` · `DESIGNING` · `BUILDING` · `MEDIA` · `QA` · `REVIEW` · `READY` · `FAILED` | 4 of 9 |
| Media permission | `none` · `use_originals` · `edit_enhance` · `generate_matching` | §13: `NO_PERMISSION` · `PERMISSION_PENDING` · `ORIGINALS_ALLOWED` · `ENHANCEMENT_ALLOWED` · `GENERATED_SUPPORT_MEDIA_ALLOWED` | 0 of 5 by name |

**Recommendation.** Adopt the document's *job states* — its extra stages
(`RESEARCHING`, `DESIGNING`, `MEDIA`, `REVIEW`) carry real information an
operator wants, and no job has run yet, so nothing migrates. Adopt
`PERMISSION_PENDING` as a fifth media state for the same reason it was proposed:
"asked, no answer yet" is not "no permission", and the distinction matters when
somebody is chasing a reply. Keep the shipped names for the other media states
and for demo classes — those are written into production event history and into
the outreach gate, and renaming them buys a vocabulary match at the cost of a
migration and a re-test of the only thing standing between a concept and an
accidental claim of a client relationship.

`CAPABILITY_DEMO` from §10 is genuinely missing and worth adding — §23's 3D
concept is exactly that, and none of the five shipped classes describes it.

---

## 4. Later phases, noted and not started

P1 media/video/blog generation, P2 ecommerce/Amazon/Noon/advertising/CRM, P3
3D/AR/autonomous orchestration. §33 is explicit that these must not destabilize
P0, and §35 that capability is not a reason to build. Recorded here so the
sequence is visible, not to schedule them.

### §26 canonical artifacts

1 of 13 exists (`AHS_SOURCE_AUDIT.md`, one prospect). The rest are unwritten.
Worth noting that thirteen markdown files per prospect is not obviously the
right shape at 1,100 prospects — the dashboard already folds most of this from
events, and a document per prospect per category would be a second registry in
prose. Recommend treating the artifact list as *the required content*, rendered
from the existing event timeline, rather than as thirteen files to author.

---

## 5. Proposed P0 order

1. **Crawler + CMS reader.** Multi-page fetch, sitemap and `robots.txt`, and a
   WordPress/CMS API reader. Turns the AHS shell session into a capability.
   Everything below depends on it.
2. **Technical health.** Speed class (`FAST`/`NORMAL`/`SLOW`/`UNAVAILABLE`/
   `NOT_VERIFIED`), redirects, TLS, broken assets, console errors. Measured,
   never guessed — §3.
3. **SEO as an audit category.** Promote the existing flags into a category and
   add what a crawl makes possible: canonicals, hreflang, orphan pages,
   duplicate titles, internal linking, content depth.
4. **UX journey model.** The §4 journeys as data, so friction is reported at a
   named step rather than as "UX could improve".
5. **Market position.** Per-prospect competitor grading, `NOT_VERIFIED` where
   unmeasured, and never framing a strong company as weak to make a sale.

Steps 3–5 produce new evidence, which the opportunity engine already consumes —
so each one widens the opportunity map without touching it.
