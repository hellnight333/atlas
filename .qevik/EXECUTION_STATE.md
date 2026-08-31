# QEVIK EXECUTION STATE

Last updated: 2026-08-31
Repository revision: ec55f67 (main)
Gate result: 3806 passed, 33 skipped, 0 failed

## Overall position

Qevik discovers real businesses, gathers evidence about their websites, raises
evidenced opportunities, produces a reviewable artefact, publishes it to a live
HTTPS address, and composes a truthful outreach message about what it published.

It has never sent a message. Nothing has been delivered to a business, no
business has responded, and there is no customer and no payment. The commercial
chain is complete up to delivery and unproven beyond it.

## Current formal milestones

- **P1 — core autonomous commercial loop.** PRODUCTION-PROVEN through outreach
  preparation. Sending is separately gated and remains unproven.
- **P2 — distributed execution fabric.** Its stated "Next" — deploy and prove
  capability-matched dispatch in production — is **done**: five workers run,
  each serving one agent, and a health-check mission was matched to
  `worker-healthcheck` by agent and capability and executed. The roadmap still
  says IN PROGRESS. See `SESSION_LOG.md` for the proposed correction.
- **P3–P8** — future, per the roadmap. Not started.
- **M1 — working email identity.** DEPLOYMENT-VERIFIED. Blocked on DNS + SMTP.

## Active vertical slice

None in progress. The health-check slice closed at its external boundary.

## Ready tracks

Ranked by the selection rules in the execution controller (§17 of the memory
spec). See `CAPABILITY_LEDGER.md` for evidence behind each.

The last batch's reading — that nothing was both ready and worth doing — was
wrong, and the way it was wrong is worth remembering: it was reached by asking
which *tracks* were open rather than by looking at what the running system was
actually producing. Reading production data found a defect that had dropped 16%
of the audited population from the funnel.

**Look at the data before concluding there is nothing to do.**

The candidates, with why each is not obviously next:

1. **CRM pipeline (C-26)** — capture landed; qualification and stages have not.
   Zero real inbound rows exist, so a pipeline would be a shape with nothing in
   it.
2. **Customer-facing surface (C-27)** — `/api/customer/*` has seven reads no
   client consumes. They are for customers, and there are none.
3. **Digital Product expansion** — a second product type multiplies something
   no business has yet received.
4. **Publishing the eight remaining health checks** — deterministic and
   valuable inventory for the moment sending works, but each one is a
   commercial decision to approach that business. Now doable from the console.
5. **Measure the re-audit recovery** — 36 businesses still carry a
   `reachable=False` our browser wrote. They re-audit in nightly rotation, and
   how many recover into opportunities is worth counting once they have. Ready
   now, but the answer arrives on its own schedule.

The honest reading: the next genuinely valuable step is **not** more capability.
It is the first real send, and that is HA-001 and HA-002.

## Blocked tracks

Every one of these is prepared to its human boundary. None blocks the others.

- Outbound email — DNS + SMTP (see `HUMAN_ACTIONS.md` HA-001, HA-002).
- HP / Lenovo workers — physical access, and a ledger no second machine can
  reach (HA-003, HA-004, HA-005).
- Commerce, media, app and game factories — provider and account credentials.

## Human actions required

5 open. See `HUMAN_ACTIONS.md`. Two block the commercial chain; three block the
fabric and nothing else.

## Product decisions required

5 open, and one of them now blocks a track. **DQ-006** — what allowance does
Qevik's own operating tenant have — holds C-27 and C-28. The rest do not block
the candidates above.

## Last production evidence

2026-08-31, on qevik-core-01:

- Two health checks live and serving: `site-98cf44bff7fa44dc` (11,485b),
  `site-22fd58442af840e3` (11,281b), both HTTPS 200.
- Outreach composed from a real published URL: state PREPARED, blocked only on
  `NO_SENDING_IDENTITY`.
- Five workers registered and fresh.
- `qevik.ai` MX, SPF, DMARC and DKIM all CONFIRMED_ABSENT, resolver readable.

## Next execution batch

Productization was selected and **found already built**: `credits/`, `quota/`
and `fabric/budgets.py` are complete and wired, and the ledger is durable. What
was missing was operator visibility, which this batch supplied, and a decision
(DQ-006) about what Qevik's own tenant is allowed.

If a batch must be chosen without the owner: **publish health checks for the
eight remaining approved-able opportunities**, building inventory for the moment
sending works. Each is a commercial decision to approach that business, so it
wants the owner's word, and it is now doable from the console rather than a
script.

## Stop condition

Not stopped. This file is written at the start of a batch and updated at its
end; a session finding it stale should reconcile before trusting it.
