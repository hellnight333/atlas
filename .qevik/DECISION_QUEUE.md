# QEVIK DECISION QUEUE

Only decisions that genuinely require the owner. A decision already resolved in
`QEVIK_HISTORICAL_DECISIONS.md` is not a question.

| ID | Decision | Options | Recommendation | Owner decision | Source | Date | Status |
|---|---|---|---|---|---|---|---|
| DQ-001 | YouMind | Define it, or drop it | None. The definition is not recoverable from any surviving document and inventing one would be inventing product | — | HISTORICAL_DECISIONS §24 | — | UNKNOWN |
| DQ-002 | Computer-use lineage | Which substrate carries it | None yet. Grok Bot is DROPPED and must not return as the answer | — | ROADMAP §02 unknown list | — | OPEN |
| DQ-003 | Dormant Atlas surfaces | Revive / retire / leave parked | Leave parked. `apps/desktop`, `apps/web`, `apps/prototype` have no Qevik wiring and no deploy path; parked is recorded in `apps/STATUS.md`, and retiring would be inventing a decision nobody made | — | ROADMAP §02; `apps/STATUS.md` | 2026-08-30 | OPEN |
| DQ-004 | Media provider / local-vs-cloud policy | Provider choice, and whether media runs local or cloud | None yet. It gates C-30 and, through it, the GPU machines' first genuine workload | — | ROADMAP §02 unknown list | — | OPEN |
| DQ-006 | What allowance does Qevik's own operating tenant have? | Put `tenant-qevik` on a customer plan / define an internal tenant kind that is metered differently / leave it unmetered and accept that metered work refuses | Do **not** put it on a customer plan. LIST/PRO/ADVANCED/ENTERPRISE are commercial plans with included units and an essential floor; assigning one to Qevik's own operating tenant would record Qevik as a customer of itself and make its own consumption look like a customer's. An internal tenant kind is the honest shape, and what it is allowed is a decision nobody has made | — | `credits/models.py`; production shows no tenant on a plan | 2026-08-31 | OPEN |
| DQ-007 | Where do email addresses come from? | Read `mailto:` from the audited homepage / buy a data source / stay on WhatsApp only / do not do email outreach | None. 412 businesses carry 0 email addresses and no source collects one, so the email channel has no recipients at all. Reading contacts off a business's own website is technically deterministic — the audit already has the HTML — but it is collecting contact details for unsolicited outreach, which is the substance of DQ-005 and not mine to decide | — | Measured 2026-08-31 | 2026-08-31 | OPEN |
| DQ-005 | Outreach policy for businesses that did not request contact | How Qevik approaches strangers | Partly answered in practice: the health check is now the first action, it asserts only what was observed, and it claims no prior relationship. The remaining question is cadence and scale, not truthfulness | — | ROADMAP §02 unknown list | — | OPEN |

## Resolved, recorded here so they are not asked again

| Decision | Outcome | Source | Date |
|---|---|---|---|
| Creative Blueprint, Grok Bot, Shopify, Facebook | DROPPED | HISTORICAL_DECISIONS §24 | — |
| Audiobook, Character Sheet, TikTok, Steam | DEFERRED | HISTORICAL_DECISIONS §24 | — |
| Atlas vs Qevik orchestration | Reuse the Atlas substrate; no second orchestrator or registry | HISTORICAL_DECISIONS §25 | — |
| Health check as the first action for an evidenced weak web presence | Approved. A first action, not a replacement for the website offer | Owner, this session | 2026-08-30 |
| Publication records carry the offer; missing stays unknown | Approved | Owner, this session | 2026-08-31 |
| Health-check outreach copy | Approved in principle, with the prohibitions held by tests | Owner, this session | 2026-08-31 |
| Contact cooldown | 14 days, an initial commercial decision rather than a technical default | Owner | 2026-08-30 |
