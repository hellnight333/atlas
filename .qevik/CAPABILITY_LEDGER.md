# QEVIK CAPABILITY LEDGER

The unit of progress is a capability, not a file.

Levels are never collapsed: CODE → TEST → INTEGRATION → DEPLOYMENT → PRODUCTION
→ COMMERCIAL. A test cannot become production evidence and a live URL cannot
become a customer.

Reconciled against the repository at 1a46afa and against qevik-core-01 on
2026-08-31. Where a cell says `—` the layer does not apply to that capability.

| ID | Capability | Track | Code | Tests | Integration | UI | Deploy | Production | Commercial | Status | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|
| C-01 | Business discovery | Commercial | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | PRODUCTION-VERIFIED | 329 `business_discovered` |
| C-02 | Website evidence audit | Commercial | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | PRODUCTION-VERIFIED | 396 `website_audited`, 240 `website_verified`, 352 screenshots. **64 were recorded unreachable, 43 of them by our own browser** — fixed 2026-08-31, proven on 7 of 7; the rest re-audit in nightly rotation |
| C-03 | Opportunity detection | Commercial | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | PRODUCTION-VERIFIED | 45 `prospect_scored`; 108 open signals |
| C-04 | Website generation | Website | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | PRODUCTION-VERIFIED | 20 `website_demo_published`, all live |
| C-05 | Artefact review | Commercial | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | PRODUCTION-VERIFIED | 6 `artefact_reviewed` |
| C-06 | Publication | Commercial | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | PRODUCTION-VERIFIED | 5 `publication_completed`, 5 approved |
| C-07 | Publication liveness | Control plane | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | PRODUCTION-VERIFIED | 21/21 addresses live when checked |
| C-08 | Health-check generation | Digital Product | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | PRODUCTION-VERIFIED | 33 built from 40 real audits, 7 refused |
| C-09 | Health-check publication | Digital Product | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | PRODUCTION-VERIFIED | 2 live: `site-98cf44bff7fa44dc`, `site-22fd58442af840e3` |
| C-10 | Health-check recommendation | Commercial | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | PRODUCTION-VERIFIED | 28 of 40 real audits recommend it; 10 stored signals |
| C-11 | Outreach preparation | Commercial | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | PRODUCTION-VERIFIED | Composed from a real published URL; state PREPARED |
| C-12 | Outreach approval | Commercial | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | PRODUCTION-VERIFIED | Fingerprint-bound; 409 on mismatch |
| C-13 | **SMTP delivery** | Commercial | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ | **BLOCKED** | HA-001, HA-002 — **and B-13: 0 of 412 businesses carry an email address, so clearing those two sends to nobody**. Zero messages sent, ever |
| C-39 | Places extractor | Commercial | ✓ | ✓ | ✓ | — | ✓ | ✓ | — | PRODUCTION-VERIFIED | Replayed a real production `place_id`; no novelty claim, no city, no country, no phone |
| C-45 | Cross-method reconciliation | Commercial | ✓ | ✓ | ✓ | — | ✓ | ✓ | — | PRODUCTION-VERIFIED | 6 false absences withdrawn across 2 businesses, both with an open opportunity |
| C-44 | Observation freshness | Control plane | ✓ | ✓ | ✓ | — | ✓ | ✓ | — | PRODUCTION-VERIFIED | The nightly pass writes the three-state record; 7 on the first run, cadence ~9 nights for 359 sites |
| C-43 | Publication offer recovery | Commercial | ✓ | ✓ | ✓ | — | ✓ | ✓ | — | PRODUCTION-VERIFIED | 4 of 5 publications recovered what they published from the mission's recipe; 3 of 3 businesses now compose, against 1 of 3 before |
| C-42 | Prospect dossier | Control plane | ✓ | ✓ | ✓ | — | ✓ | ✓ | — | PRODUCTION-VERIFIED | Thirteen facts, each read from its owner. Verified on four real prospects |
| C-41 | Contact discovery | Commercial | ✓ | ✓ | ✓ | — | ✓ | ✓ | — | PRODUCTION-VERIFIED | 96 pages read, 69 email-contactable (72%) by browser. **Wired into the nightly pass and proven: one run populated 19 addresses with 19 provenance events**, `email_is_addressable` true for the first time |
| C-40 | Outreach reachability | Control plane | ✓ | ✓ | ✓ | — | ✓ | ✓ | — | PRODUCTION-VERIFIED | 412 businesses, 0 by email, 349 by phone, 63 by neither |
| C-14 | Enquiry delivery evidence | Commercial | ✓ | ✓ | — | — | — | ✗ | ✗ | BLOCKED | Depends on C-13 |
| C-15 | Worker registration | Fabric | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | PRODUCTION-VERIFIED | 5 workers, one agent each, fresh |
| C-16 | Heartbeat / liveness | Fabric | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | PRODUCTION-VERIFIED | 90s heartbeat, distinct from 7200s claim staleness |
| C-17 | Capability-matched dispatch | Fabric | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | PRODUCTION-VERIFIED | Health-check mission matched to `worker-healthcheck` and run |
| C-18 | Multi-GPU resource probe | Fabric | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | — | DEPLOYMENT-VERIFIED | No GPU exists to probe. Deployed, unexercised |
| C-19 | HP Z8 worker | Fabric | ✓ | ✓ | — | ✓ | ✓ | ✗ | — | BLOCKED | HA-003, HA-005 |
| C-20 | Lenovo worker | Fabric | ✓ | ✓ | — | ✓ | ✓ | ✗ | — | BLOCKED | HA-004, HA-005 |
| C-21 | Mission control UI | Control plane | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | PRODUCTION-VERIFIED | Grouped by whose move it is |
| C-22 | Human Action Centre | Control plane | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | PRODUCTION-VERIFIED | 12 actions served, 9 blocking |
| C-23 | Credential centre | Control plane | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | PRODUCTION-VERIFIED | 17 providers, each with a verification method |
| C-24 | Sending-identity check | Commercial | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | PRODUCTION-VERIFIED | MX/SPF/DMARC/DKIM all CONFIRMED_ABSENT |
| C-25 | Inbound capture | Commercial | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | PRODUCTION-VERIFIED | A public audit records who asked; route and console verified on the host. **Zero real rows** — nobody has used the public audit yet |
| C-26 | CRM pipeline | Commercial | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | DESIGNED | Qualification, stages, follow-up. Nothing implemented; C-25 is the capture, not the pipeline |
| C-27 | Customer control plane | Productization | ✓ | ✓ | ✓ | ~ | ✓ | ~ | ✗ | **BLOCKED (DQ-006)** | Substrate complete: `credits/` (Plan, Reservation, CreditService), `quota/` ledger durable via `$QEVIK_STATE/quota.jsonl`, `fabric/budgets.py` scopes. `/api/customer/plan` is rich and the console now draws its three states. **No tenant is on a plan**, so it 409s for everyone |
| C-27a | Operator approves an opportunity | Control plane | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | PRODUCTION-VERIFIED | `POST /api/missions/deliver` reachable from the console; route and markup live on the host |
| C-28 | Usage / credits / quotas | Productization | ✓ | ✓ | ✓ | ✓ | ✓ | ~ | ✗ | **BLOCKED (DQ-006)** | Built, not DESIGNED as the ledger previously said. Nothing has ever been spent, so there is nothing to meter yet |
| C-29 | Stripe payment handoff | Productization | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | DESIGNED | Payment Links sufficient; adapter deliberately unbuilt |
| C-30 | Media generation | Creative | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | BLOCKED | Provider decision + credentials |
| C-31 | App factory | App | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | BLOCKED | Apple / Google Play accounts |
| C-32 | Game factory | Game | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | DESIGNED | Roadmap P7 |
| C-33 | Commerce / marketplace | Commerce | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | BLOCKED | Amazon / Noon credentials |
| C-34 | Computer use | Computer use | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | DECISION | DQ-002 |
| C-37 | Contact cooldown | Commercial | ✓ | ✓ | ✓ | — | ✓ | ✓ | — | PRODUCTION-VERIFIED | Keyed on the recipient as well as the business. Proven on a real shared number: old rule left the 2nd record unblocked, new rule blocks all 3 |
| C-38 | Discovery provenance | Commercial | ~ | ✓ | ✓ | ✓ | ✓ | ✓ | — | **PARTIAL** | 353 of 412 businesses have **no sighting**, so no discovery state and no `claims_about_the_world`. The feed now says so instead of implying a clean scan; the gap itself is not closed |
| C-36 | Funnel coverage | Control plane | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | PRODUCTION-VERIFIED | 359 with a website, 352 audited, 290 answered, 19 theirs, **43 ours**, 7 queued. `we_failed` should reach zero as the nightly pass revisits |
| C-35 | Desktop surfaces | Desktop | ~ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | PARKED | `apps/STATUS.md`; DQ-003 |

## Notes on the two that look complete and are not

**C-13 SMTP delivery** carries every layer except the last two, and those two
are the whole point. The transport exists, the approval binds to exact words,
suppression and cooldown are loaded from the database, and zero messages have
ever left. Do not read the ticks as readiness.

**C-08/C-09 health check** is production-verified as a *capability*. No business
has seen one. That is C-13's job and C-13 is blocked.
