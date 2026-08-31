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

### Next
No track is both ready and clearly worth doing. The next genuinely valuable step
is the first real send — HA-001 and HA-002.
