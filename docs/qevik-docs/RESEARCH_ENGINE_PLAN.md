# Research engine — architecture report

Required by §27 before any production code. Nothing below is implemented.

The shape of it: **research discovers, opportunity interprets, outreach speaks.**
Research never decides what to sell, and the opportunity engine is not touched
apart from being given more evidence to read.

---

## 1. Files and modules that will change

### New — one package, one pipeline

All under `packages/kernel/atlas_kernel/research/`, which already exists and
already holds the vendor-neutral `web.search` capability.

| Module | Does |
|---|---|
| `pipeline.py` | The ResearchJob: runs the stages, folds results, degrades each independently |
| `discovery.py` | Canonical URL, redirect chain, TLS, DNS, `robots.txt`, `sitemap.xml`, sitemap indexes |
| `crawler.py` | Bounded internal crawl; records reached, unreachable, and *why it stopped* |
| `cms/base.py` | `CMSReader` protocol — `detect()` / `read()`. Vendor-neutral by construction |
| `cms/wordpress.py` | First implementation: pages, posts, categories, media, dates, URLs |
| `technical.py` | Status, timing, resource failures, broken links/images, speed class |
| `seo.py` | Technical SEO, indexability, duplicates, orphans, internal linking |
| `content.py` | Blog existence, volume, freshness, depth, images, service links |
| `journeys.py` | The §10 journeys as data; friction reported at a named step |
| `presence.py` | Official channels: found / not found / not verified, and how confident |
| `position.py` | Prospect-level market position. **Does not touch `market.py`** |
| `classify.py` | Business-model classification from evidence, never from the name |
| `evidence.py` | Normalises every stage into the observation shape the audit already emits |

### Existing — changed, additively

| File | Change |
|---|---|
| `outreach/demos.py` | Add `CAPABILITY_DEMO` to `CLASSES`, `CLAIM`, `FORBIDDEN_ABOVE` |
| `outreach/opportunity.py` | **New rules only.** No change to `Opportunity`, `derive`, or ranking |
| `control/sales.py` | `JOB_STATES` 7 → 9; `MEDIA_PERMISSION` + `permission_pending`; research block in the payload |
| `apps/control/index.html` | Research section; pending-permission option |

### Untouched on purpose

`opportunity/market.py` (niche selection, a different question), `website_audit.py`
(its single-page checks stay and become one stage among many), `Business`,
`BusinessEvent`, the demo registry, `differentiation.py`.

## 2. Existing functions reused

- `website_audit.Status` / `Category` / `Finding` — the evidence vocabulary, unchanged
- `website_audit.audit_html()` — becomes the homepage stage rather than the whole audit
- `audit_import.audit_event()` — the existing business-event writer
- `OpportunityRepository.record_event()` / `save_business()`
- `research.brave` — `web.search`, for presence and position
- `scoring.score()` and `opportunity.derive()` — consume the normalised output unchanged
- `control.sales._safe()` — the degradation wrapper written during the P0 fix

## 3. New functions

`pipeline.research(business, *, budget)` → `ResearchResult`. Each stage is
`stage(context) -> list[Finding]` with the same signature, so the pipeline is a
loop rather than thirteen bespoke calls. `evidence.normalise(findings)` →
`{"observations": [...]}`, the shape `website_audited` already carries.
`evidence.merge(existing, fresh)` folds with `setdefault().update()` semantics, so
a later partial run cannot resurrect a refuted finding — the bug that once
brought back AHS's "no HTTPS".

## 4. New data structures

`ResearchJob` (id, business_id, stages, budget, started, finished),
`StageResult` (stage, state, findings, evidence, error, duration),
`CrawlBudget`, `Route` (url, status, depth, discovered_from, content_type,
bytes), `CMSFacts`, `SpeedClass`, `JourneyStep`, `PositionGrade`.

All pydantic, all frozen where they are results rather than accumulators. None of
them is a customer entity.

## 5. Database schema

**No changes.** No new table, no migration.

A research job is `BusinessEvent` rows under `factory="research"`, kinds
`research_started` / `research_stage_recorded` / `research_completed` /
`research_failed`. State is folded per request, exactly as every other prospect
fact already is. `atlas_business_events.detail` is JSON and already carries the
audit observation shape.

This is also why there is no second prospect registry: research attaches to the
same immutable `Business` id everything else uses.

## 6. Production data

Research **reads** prospect websites and **writes** append-only events about what
it found — the same thing `website_audited` does today. Nothing existing is
mutated, nothing is deleted, no customer record changes.

Two notes:
- §25 says research should be read-only. Read-only against *their site* — no
  forms submitted, no auth, no private content, no state changed on any prospect
  system. Recording findings is the point of running it.
- If you would rather the first run write nothing, `pipeline.research()` takes
  `record=False` and returns the result without emitting events. Say so and that
  becomes the default for the first pass.

## 7. Crawl limits

Concrete, and enforced in `CrawlBudget` rather than by convention:

| Limit | Value | Why |
|---|---|---|
| Pages per prospect | 40 | AHS needed ~12 to find the pattern; the CMS API supplies the rest for one request |
| Depth | 3 | Beyond this is pagination and tag archives |
| Concurrency per host | 1 | One prospect is never worth loading their server |
| Delay between requests | ≥1.5s, or `Crawl-delay` if larger | |
| Per-request timeout | 10s | |
| Total budget per prospect | 120s | Bounds the worst case at 1,100 prospects |
| Response cap | 2MB, HTML only | |
| Cache | 7 days by URL + ETag | A re-run must not re-crawl |

Refusals are absolute: `robots.txt` `Disallow` is obeyed, off-host links are
never followed, query strings that look like search or filter are skipped, no
authentication is attempted, no private content is fetched, and the User-Agent
identifies Qevik with a contact URL. A cycle is caught by a visited set keyed on
the normalised URL.

## 8. Research job lifecycle

`QUEUED → RESEARCHING → READY | PARTIAL | FAILED`

Deliberately *not* the nine build states. A research job does not design, build
or produce media, and reusing that lifecycle would mean every research job sat
permanently in states it can never reach. The nine states are for the build
queue, which §21 asks me to establish but not implement.

Each of the twelve stages independently records `ok` / `skipped` / `failed`, so
`PARTIAL` is a real, common, honest outcome: crawl succeeded, position not
verified.

## 9. Evidence model

Unchanged, and reused rather than restated. `Status.PRESENT` /
`Status.NOT_FOUND` / `Status.UNVERIFIED`, plus `REFUTED` from the existing
verification path.

The rule that matters holds at the boundary: a stage that fails emits
`UNVERIFIED`, never `NOT_FOUND`. A crawler that times out has not established
that a booking page is absent. `evidence.normalise()` is the only place findings
become observations, so this cannot be got wrong in twelve places.

## 10. How each stage degrades

Every stage runs through the `_safe` pattern already proven on the prospect page:
log the traceback with the business id, record the stage as `failed`, continue.

- Discovery fails → no crawl, everything downstream `NOT_VERIFIED`, job `FAILED`
- Crawl partial → later stages see the routes that were reached, and the record
  says how many were not and why
- CMS absent → not an error; `cms.detected = False` and nothing is inferred
- Any single stage fails → that category is `NOT_VERIFIED`, the rest stand
- Whole job fails → the prospect page still renders; the research block shows the
  failure

The dashboard shows `Research complete` / `partial` / `failed` / `not verified`.
A failure never becomes "no opportunity found" — that is the sentence this whole
design exists to prevent.

## 11. Test plan

Every §24 case, against recorded fixtures rather than live sites, so the suite
never depends on somebody's server:

- **Crawler** — sitemap, sitemap index, robots `Disallow` obeyed, `Crawl-delay`
  honoured, redirect chain, redirect loop, broken link, timeout, pagination,
  duplicate URLs, cyclic links, off-host link refused, budget exhaustion recorded
- **CMS** — WordPress present, WordPress absent, API present but empty, malformed
  JSON, a non-WordPress CMS not misread as WordPress
- **SEO** — canonical, hreflang reciprocity, duplicate titles, duplicate
  descriptions, missing metadata, structured data, orphan page, thin page
- **UX** — one fixture per journey: restaurant, ecommerce, B2B, recruitment,
  logistics, clinic; plus that a missing step the model does not require produces
  no finding
- **Position** — strong business, weak presence, unknown presence, and a
  misleading social result that must not be attached
- **Evidence** — the negative control on every guard: a failing stage produces
  `UNVERIFIED` and never `NOT_FOUND`; a refuted finding never becomes a weakness;
  a partial re-run cannot resurrect a refuted one

Plus the one that matters commercially: **a strong business produces few or no
opportunities**, and the AHS fixture concludes "strong company, limited website
opportunity" rather than manufacturing a weakness.

## 12. Browser QA plan

1280×900 and 390×844 against the live dashboard: research block renders for a
researched prospect, for an unresearched one, and for a failed one; each state
visibly distinct; opportunities still render; A→B→C→A with no stale research
carried between prospects; hard refresh; no horizontal overflow; no dead
controls. Same harness as the P0 fix, which is already written.

## 13. Rollback

Everything new is one package plus additive fields. Rollback is
`git revert` and `systemctl restart qevik-api`.

- Research events are append-only, so reverting the code leaves harmless rows no
  fold reads
- The payload additions sit behind `_safe`, so a partial revert degrades rather
  than 500s
- `CAPABILITY_DEMO` and `permission_pending` are additive; nothing renames

**One thing that does not roll back cleanly, flagged now.** Replacing the 7 job
states with the 9 removes `CANCELLED`, and exactly one historical job carries it
— `466e86e8-001`, the verification job I queued and cancelled while testing. The
9-state vocabulary has no cancelled state. I will not rewrite that event. The
fold will display an unrecognised legacy state as-is and new jobs will only use
the nine; alternatively, tell me to keep `CANCELLED` as a tenth terminal state
and the problem disappears. I would rather ask than quietly rewrite history or
quietly drop a state a real job is in.
