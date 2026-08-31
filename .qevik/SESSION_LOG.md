# QEVIK SESSION LOG

Durable facts only. Not a copy of the final report.

## 2026-08-31 — Session 1 (execution memory established)

### Completed
- Created `.qevik/` per `QEVIK_EXECUTION_MEMORY_SPEC.md`, reconciled against the
  repository at 1a46afa and against live production, not against chat.
- Copied `QEVIK_MASTER_ROADMAP.md` and `QEVIK_HISTORICAL_DECISIONS.md` into
  `docs/qevik-docs/`. They existed only in `~/Downloads` and were therefore not
  repository truth; authorities #1 and #2 of the spec were unreadable by any
  session that did not have the chat.

### Discovered
- **The dropped/deferred decisions are not in `docs/qevik-docs/90_DECISIONS.md`.**
  They live in `QEVIK_HISTORICAL_DECISIONS.md` §24 only. `90_DECISIONS.md` has
  no record of Creative Blueprint, Grok Bot, Shopify, Facebook, Audiobook,
  Character Sheet, TikTok, Steam or YouMind.
- **`docs/qevik-docs/91_OPEN_QUESTIONS.md` is stale.** It still asks "First
  niche? Geography? Offer? Price?" — all answered in practice by production
  (Dubai, evidenced weak web presence, health check as first action).

### Corrected
Two stale roadmap claims, reported rather than edited:
- **P2 says IN PROGRESS with "Next: deploy and prove capability-matched dispatch
  in production".** That is done: five workers, one agent each, and a
  health-check mission matched to `worker-healthcheck` by agent and capability
  and executed. Evidence E-05, E-09.
- **Digital Product Factory says "DESIGNED / EARLY WORKFLOW".** The health check
  is production-verified end to end with two live URLs. Evidence E-03, E-05,
  E-06.

### Human boundary
Five open actions, HA-001 to HA-005. Two hold the commercial chain at delivery;
three hold the fabric. None blocks CRM, control plane or productization.

### Decisions
No new owner decisions required to continue. Four remain open (DQ-002 to
DQ-005) and one unknown (DQ-001); none blocks the ready tracks.

### Also completed
- **Inbound capture (C-25).** `POST /api/public/audit` recorded nothing about
  who asked. It now writes to the shared timeline, `GET /api/missions/inbound`
  reads it, and the console shows who came to us at the top of Opportunities.
  Production-verified end to end; the synthetic probe row was removed.
- `test_one_customer_entity` refused the first version, named `Lead`. It was
  right — that is the head noun of a second customer entity. What is modelled
  is a request at a moment, and the company stays `atlas_businesses.id`.
- The repository imported `.leads` from inside `opportunity/`, a module that
  does not exist. Nothing exercised it, so the whole gate passed. There is now
  a test that imports it.

## 2026-08-31 — Session 2 (productization)

### Discovered
- **Productization is built, not designed.** The ledger said C-28 DESIGNED.
  `credits/` (Plan, Reservation, CreditService), `quota/` (QuotaLedger with
  windows and replay) and `fabric/budgets.py` (TENANT ⊃ MISSION ⊃ AGENT ⊃
  CONVERSATION) are complete and wired into the app.
- **Nothing is metered.** No tenant is on a plan, so `/api/customer/plan` 409s
  for everyone and any metered work would refuse.
- A suspicion checked and **found wrong**: the quota ledger looked in-memory in
  production because no `quota.jsonl` exists. `QEVIK_STATE` is set for
  `qevik-control`, so the path resolves; the file is absent because nothing has
  ever been spent. No fix was shipped for a defect that did not exist.

### Completed
- The console draws all three allowance states. It previously collapsed "not on
  a plan" into "nothing to show" and omitted the card entirely.
- **An operator can approve an opportunity.** `POST /api/missions/deliver`
  existed and nothing called it — every approval this session was made from a
  script. Behind a confirm, carrying only the signal id.

### Human boundary
DQ-006 recorded: LIST/PRO/ADVANCED/ENTERPRISE are commercial plans, and putting
Qevik's own operating tenant on one would record Qevik as a customer of itself.
An internal tenant kind is the honest shape and nobody has decided what it is
allowed. B-11 raised.

### Also completed — the audit was lying about 64 businesses
- One `PlaywrightSession` is started once and the audit loops over businesses
  calling `open()` on the same page. `wait_until="domcontentloaded"` returns
  while a page may still be navigating, so the next business's `goto` cancelled
  the previous one — and Playwright raised against the **previous** call, whose
  business got the blame.
- 64 of 396 audits were recorded `reachable=False`; 43 carry "interrupted by
  another navigation". Among them Crate and Barrel and Interiors, whose sites
  plainly work. Each was dropped from the funnel: no observations, no findings,
  no opportunity, no health check.
- `open()` now starts each navigation on a fresh page. `browser/failures.py`
  separates failures that can only be ours from a site that did not answer, and
  the first records `reachable=None` — not established, which is not down. The
  classifier is conservative: DNS failures, refused connections, bad
  certificates and timeouts stay findings about the site.
- Proven on production: 7 of 7 previously-unreachable sites answered 200 with
  20 observations each.

### Corrected
The previous session concluded that nothing was both ready and worth doing.
That was reached by asking which tracks were open rather than by looking at what
the running system was producing. **Read the data before concluding there is
nothing to do.**

## 2026-08-31 — Session 3 (production-data integrity)

### Traced
The browser defect's consequences, through real production data rather than
code:
- 352 businesses audited; 61 have a latest audit saying unreachable; **43 carry
  "interrupted by another navigation"**, which only our own browser produces.
- Those businesses carry a signal **6.6%** of the time against **22.4%** for
  reachable ones — roughly ten opportunities that were never created.
- **3** stored signals belong to businesses that ever had an interrupted audit;
  their evidence rests on later successful audits, not on the failures.
- The rotation recovers them unaided: **34 of 43 have never been marked
  `website_verified`**, so they sort to the front of a queue holding ~119
  unaudited sites at 40 a night.

### Completed
`opportunity/coverage.py` + `GET /api/missions/coverage` + a Discovery panel.
Four states kept apart: answered, never-audited (a queue position, not a loss),
their site did not answer, and **our check did not complete**. Baseline in
production: 359 with a website, 352 audited, 290 answered, 19 theirs, 43 ours,
7 queued.

Two history problems it reads correctly: 43 rows predate
`check_failed_because` and carry only the error text, and 60 rows from an
earlier producer never wrote `reachable` at all but carry 20 observations each.

### Checked and clean
`audit_prospects.py` writes no ledger events, so `audit_discovered.py` was the
only producer putting a false negative into production state.
`research/net.py`, `outreach/deliverability.py`, `publication/published.py` and
`credentials/probes.py` already separate a producer failure from a fact about
the subject.

### Next
Watch `we_failed` fall. Beyond that the valuable step remains the first real
send — HA-001 and HA-002.
