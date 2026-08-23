# Master execution state

Every known implementation item, from `01_QEVIK_PHASE_ROADMAP.md` (authoritative),
`QEVIK_PENDING_IMPLEMENTATION_DOCS/`, `QEVIK_MASTER_AUTONOMOUS_EXECUTION_V2.md`
and the repository itself. See `ROADMAP_RECONCILIATION.md` for why the numbering
differs between sources.

Statuses: COMPLETE · IN_PROGRESS · READY · PENDING_CREDENTIAL · PENDING_EXTERNAL
· BLOCKED · DEFERRED · NOT_STARTED

## Product A — the evidence engine (`01_QEVIK_PHASE_ROADMAP.md`)

| Item | Phase | Status | Files | Tests | Commit | Next action |
|---|---|---|---|---|---|---|
| Recommendation + CapabilityOffer | P1.2 | COMPLETE | `recommendation/` | `test_recommendation` | pre-run | — |
| AHS end-to-end slice | P1.3 | COMPLETE | `execution/` | `test_execution_slice` | pre-run | — |
| Measurement | P1.4 | COMPLETE | `measurement/` | `test_measurement` | pre-run | — |
| 0→100 roadmap | P1.5 | COMPLETE | `roadmap/` | `test_roadmap` | `b7b32cf` | — |
| Roadmap → execution | P1.6 | COMPLETE | `roadmap/{gate,crossing}` | `test_roadmap_execution` | `e03c20f` | — |
| Customer portal (reads) | P1.6/P2.4 | COMPLETE | `customer/` | `test_customer_workflow` | `44f975b` | — |
| Credits / plans / quota | P1.7 | COMPLETE | `credits/` | `test_credits` | `9953cc8` | — |
| Website capability | P2 | COMPLETE | `capabilities/website.py` | `test_website_capability` | `902600d` | — |
| Website vertical loop | P2 | COMPLETE | `publication/staging.py` | `test_website_vertical` | `1fc45ef` | — |
| Editorial/content capability | P2 | COMPLETE | `capabilities/editorial.py` | `test_editorial_capability` | `eea841e` | — |
| Multi-page website | P2 | READY | `capabilities/website.py` | — | — | Render a page per service; bundle machinery already supports it |
| Media capability | P2 | READY | `media/providers/mock.py` | — | — | Local vertical slice; no external provider needed |
| Arabic / localisation | P2 | NOT_STARTED | `offer-arabic-experience` | — | — | Offer exists, no executor |
| Enquiry flow | P2 | NOT_STARTED | `offer-enquiry-builder` | — | — | Offer exists, no executor |
| One-tap contact | P2 | NOT_STARTED | `offer-one-tap-contact` | — | — | Offer exists, no executor |
| Imagery | P2 | NOT_STARTED | `offer-imagery` | — | — | Offer exists, no executor |
| SEO detection + execution | P3 | COMPLETE | `research/seo.py`, `offer-website` | `test_research_pipeline` | pre-run | — |
| Sitemap / canonical / structured data | P3 | PARTIAL | `research/seo.py`, `themes/clean.py` | — | — | Detected and emitted; no dedicated executor |
| AI visibility | P3 | COMPLETE (live: PENDING_CREDENTIAL) | `aivisibility/` | `test_ai_visibility` | `46d618e` | Add `QEVIK_AI_VISIBILITY_TOKEN` |
| Public audit route | P4 | COMPLETE | `customer/{public,api}.py` | `test_customer_workflow` | `41f47b4` | — |
| Plan / usage surface | P4 | COMPLETE | `customer/api.py` | `test_control_plane` | `200190b` | — |
| Customer write routes | P4 | READY | `customer/api.py` | — | — | Complete a task, request an approval |
| Marketplaces (Amazon/Noon) | P5 | NOT_STARTED | — | — | — | Follow the `aivisibility` adapter pattern |
| Leads / CRM / email | P6 | NOT_STARTED | — | — | — | Same pattern; suppression list already exists in `outreach/` |
| Social / video / autopilot | P7 | NOT_STARTED | — | — | — | Same pattern |
| Agency / white label | P8 | COMPLETE | `organization/agency.py` | `test_agency` | this commit | Delegation = membership. No schema change |

## Cross-cutting (master directive)

| Item | Status | Files | Commit |
|---|---|---|---|
| Credential centre | COMPLETE | `integrations/registry.py` | `46d618e` |
| Blocker-first action centre | COMPLETE | `controlplane/actions.py` | `a945c4e` |
| Measurement scheduling query | COMPLETE | `measurement/schedule.py` | `44f975b` |
| Agent provider abstraction | NOT_STARTED | — | — |
| Chat → plan → execute | NOT_STARTED | — | — |
| Persistent task queue / worker | NOT_STARTED | — | — |
| app.qevik.ai UI | NOT_STARTED | — | — |

## Product B — execution platform (`QEVIK_PENDING_IMPLEMENTATION_DOCS/`)

| Item | Doc | Status | Blocker |
|---|---|---|---|
| Core infra, supervision, backup/restore | 08, 01/Ph2 | NOT_STARTED | Operational, outside the kernel |
| Execution engine: retries, cancel, resume | 01/Ph3 | NOT_STARTED | — |
| Coding-agent adapter | 02, 01/Ph4 | PENDING_EXTERNAL | Needs a sandboxed workspace host |
| Browser worker | 02, 01/Ph5 | PENDING_EXTERNAL | Needs a Chromium host |
| Publishing to a real host | 01/Ph6 | PENDING_CREDENTIAL | Cloudflare or SSH credential |
| Iran-origin worker | 03, 01/Ph7 | PENDING_EXTERNAL | Needs an Iran-resident host; must not be faked |
| Worker architecture | 01/Ph8 | NOT_STARTED | — |
| Control interface / mobile | 06, 01/Ph9 | PARTIAL | Action centre + reads; no UI |
| Qevik product website | 09, 01/Ph10 | NOT_STARTED | — |
| App / game factories | 05, 01/Ph11 | NOT_STARTED | — |
| Billing / subscriptions | 01/Ph12 | PENDING_CREDENTIAL | Stripe; abstraction not yet built |

## Product C — media/growth business (docs 11, 11A)

| Item | Status | Why |
|---|---|---|
| Whole programme | DEFERRED | A different business line, not a Qevik layer. Its own gap analysis lists legal entity, developer accounts, API quotas and IP rights as Tier 1 — commercial and legal decisions, not code |

## Credentials required

| Provider | Blocks | Action |
|---|---|---|
| AI visibility | `ai_mention_rate`, `ai_citation_rate` | Add `QEVIK_AI_VISIBILITY_TOKEN` |
| Google Search Console | `clicks`, `impressions` | OAuth connect |
| Analytics | `sessions`, `conversion_rate` | OAuth connect |
| Cloudflare | Publication to a real host | Add API token |
| Stripe | Billing | Not yet abstracted |
