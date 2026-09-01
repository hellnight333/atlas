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
| ~~DQ-007~~ | ~~Where do email addresses come from?~~ **RESOLVED 2026-08-31** — read them from the pages the audit already fetches. Contact discovery, not permission to send | — | — | Owner | Owner, this session | 2026-08-31 | RESOLVED |
| DQ-007-old | Where do email addresses come from? | Read `mailto:` from the audited homepage / buy a data source / stay on WhatsApp only / do not do email outreach | None. 412 businesses carry 0 email addresses and no source collects one, so the email channel has no recipients at all. Reading contacts off a business's own website is technically deterministic — the audit already has the HTML — but it is collecting contact details for unsolicited outreach, which is the substance of DQ-005 and not mine to decide | — | Measured 2026-08-31 | 2026-08-31 | OPEN |
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

## DQ-008 — approvals that predate the opportunity model, and one that predates its own evidence

**Open. Nothing has been changed, withdrawn or re-approved.**

Two outreach messages carry `approved_fingerprint` and have never been sent.
Both were approved by hand on 2026-08-19, before missions, signals and
publications existed as records:

* **Malabar Dental Clinic** — 20 observations, 17 findings, HTTP 200. The
  evidence is sound; there is simply no `Signal` naming the business, so the
  dossier says "no opportunity names this business" beside an approved message.
* **Kings — Dental Center Karama Dubai** — latest audit **0 observations, HTTP
  status 0**. The fetch never completed. `73_FIRST_COMMERCIAL_TEST.md` recorded
  on the day that the approved message claims the site "did not finish loading
  within 30 seconds" and that a live check found it loads in 15.8 seconds.

So one approved message contains a claim already known to be inaccurate, and
neither is reachable through the model the rest of the system reasons in.

**Why this is not being decided here.** An approval is a person's act. The
standing instruction is not to reinterpret these five manual approvals, and
withdrawing one, re-approving it against fresh evidence, or attaching it to a
manufactured `Signal` would each be a decision about what somebody meant.

**What is needed:** whether these two are (a) withdrawn, (b) re-approved after
a fresh audit, or (c) left exactly as they are and excluded from any future
automated send. Until then they sit approved and unsent, which is where they
have been since 2026-08-19 and is the safe direction.

<!-- devloop:contested:t-9c7566206741 -->
## Contested — Most observation records are more than a week old

The reviewer raised findings the builder did not settle in three rounds. The work is committed and **not deployed**.

  - `packages/kernel/atlas_kernel/opportunity/repository.py:1004-1006` [blocking] Base sweep claims on completed verification passes
  - `packages/kernel/atlas_kernel/opportunity/repository.py:121-129` [major] Share the nightly limit with the actual runner
  - `packages/kernel/atlas_kernel/opportunity/coverage.py:338-341` [major] Stop explaining ages when the pass is below its promised rate
  - `packages/kernel/atlas_kernel/opportunity/repository.py:989-996` [major] Discard observations for a business's previous website
  - `packages/kernel/atlas_kernel/opportunity/repository.py:1018-1021` [major] Measure throughput only for sites in the current queue
  - `/private/var/folders/k4/1yd9slj94ts6fnsn8l1h8p2r0000gn/T/devloop-review-sbp4lv_u/wt/infra/devloop/agents.py:344-347` [blocking] Normalize findings against the review worktree
  - `/private/var/folders/k4/1yd9slj94ts6fnsn8l1h8p2r0000gn/T/devloop-review-sbp4lv_u/wt/packages/kernel/atlas_kernel/mission/api.py:775-777` [major] Read freshness and backlog in the same transaction
  - `/private/var/folders/k4/1yd9slj94ts6fnsn8l1h8p2r0000gn/T/devloop-review-3p4ne2hh/wt/packages/kernel/atlas_kernel/opportunity/coverage.py:368-369` [major] Bound the stale count the cadence can explain
  - `/private/var/folders/k4/1yd9slj94ts6fnsn8l1h8p2r0000gn/T/devloop-review-3p4ne2hh/wt/apps/control/src/index.html:1618-1619` [major] Render unreachable records when the rotation is empty

- **Driver task:** `t-9c7566206741`
- **Review unit:** `a42cd63f8e1e..fb1b2ac25ca2`

<!-- human-decision:cadence-verdict -->
## DQ-009 — what the cadence verdict may claim about stale observations

**Open, and answerable in app.qevik.ai** — Human Actions →
"When should Qevik say the audit schedule explains a stale record?"
This file is the projection; the request is the record, and it carries the
four options with their consequences.

346 of 353 businesses carry observations more than a week old, and the coverage
screen says the schedule explains it. A reviewer showed the test is
magnitude-blind: it says the same thing whether 39 records are stale or 358.

Two things make this a person's call rather than an engineer's.

The docstring's arithmetic is provably false — 359 sites at 40 a night leaves
**39** of 359 past the eight-night line, not "the majority" — but that falsehood
has two repairs producing opposite code, and which is right turns on whether
`per_night` means the declared limit (40) or measured throughput (**7**, on the
one real pass). The repository has visited that question three times and
settled it none.

And no available input distinguishes "the pass is running and not reaching
these sites" from "the pass is draining a backlog after a gap". Qevik's only
production population is the second, so a bound would turn it red.

Blocks devloop task `t-9c7566206741`, which is parked and resumes on the
answer. The loop continues with independent work meanwhile.

<!-- devloop:contested:t-0f8d6a74729c -->
## Contested — A mission that did its work is recorded as failed, with no cause

The reviewer raised findings the builder did not settle in three rounds. The work is committed and **not deployed**.

  - `packages/kernel/atlas_kernel/mission/toolrunner.py:1213-1213` [major] Count only sightings actually stored
  - `packages/kernel/atlas_kernel/mission/toolrunner.py:1479-1481` [major] Honor the contactability write result
  - `packages/kernel/atlas_kernel/mission/worker.py:303-303` [major] Preserve live-output data when implementation crashes

- **Driver task:** `t-0f8d6a74729c`
- **Review unit:** `..`
