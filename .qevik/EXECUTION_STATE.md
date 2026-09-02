# QEVIK EXECUTION STATE

Last updated: 2026-08-31
Repository revision: e47f2f9 (main)
Gate result: 3944 passed, 33 skipped, 0 failed

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
5. **Close the discovery-provenance gap (B-12)** — 353 of 412 businesses have
   no sighting, so no discovery state and no `claims_about_the_world`. The feed
   now says so; the gap is not closed. Deterministic, no external dependency,
   and it is what makes the discovery layer honest rather than merely quiet.
6. **Watch the recovery** — `GET /api/missions/coverage` reports 43 businesses
   blocked by our own failed checks. The nightly pass revisits them; the number
   falling is the measurement. Nothing to build, and re-auditing by hand would
   spend somebody else's bandwidth to produce a figure the schedule will give
   for free.

**The critical path moved twice on 2026-08-31, and is now back on DNS + SMTP.**

First: "412 businesses, 0 email addresses" was read as a fact about those
businesses. It was a fact about Qevik's canonical data. They publish addresses;
nothing was reading them.

Then contact discovery measured it on 100 real businesses: **69 of 96 pages read
are email-contactable — 72%.** Extrapolated over the 359 with a website, roughly
258 addressable. External discovery — LinkedIn, social, open search — is
**not necessary**.

So the path is now: nightly audit fills `Business.email` → HA-001 (DNS) →
HA-002 (SMTP) → one prepared message → explicit approval → first send.

**19 addresses are now in canonical data**, from one real nightly pass, each
with a `contact_observed` provenance event. `email_is_addressable` is true for
the first time. The rest fill as the pass works through the backlog at ~40
sites a night.

One caveat measured rather than assumed: the nightly pass uses plain
`http-fetch` and reached ~48% where the browser reached 72%. JavaScript-rendered
contact details are not seen by it. That is a known difference, not a defect,
and it is not worth a second fetching path until the backlog is exhausted.

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

## The rule this project now runs on

Before declaring a capability production-proven, or concluding there is nothing
valuable to do, **inspect what the running system is actually producing**. Both
of the last two batches found real defects that way and neither was visible from
the code:

- A shared browser page made Qevik record that 43 real businesses had dead
  websites. They were silently dropped from the funnel.
- Before that, six failed missions each reported that they ended because a
  "report was written".

An empty result usually means a measurement failed. Ask whose failure it was.

## Last production evidence

2026-08-31, on qevik-core-01:

- Two health checks live and serving: `site-98cf44bff7fa44dc` (11,485b),
  `site-22fd58442af840e3` (11,281b), both HTTPS 200.
- Outreach composed from a real published URL: state PREPARED, blocked only on
  `NO_SENDING_IDENTITY`.
- Five workers registered and fresh.
- `qevik.ai` MX, SPF, DMARC and DKIM all CONFIRMED_ABSENT, resolver readable.

## What the production data said to fix, in order found

Three batches, three defects, none visible from the code:

1. Six failed missions each reported ending because a "report was written".
2. A shared browser page made Qevik record that 43 real businesses had dead
   websites.
3. The contact cooldown could be stepped around by duplicate business records —
   four phone numbers across nine records, each with its own 14-day window.
4. 412 businesses and not one email address, while DNS and SMTP were being
   treated as the last blockers before a first send.

Every one was found by reading what the running system produced.

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

<!-- devloop:begin -->
## Development loop

_Written by `infra/devloop/driver.py` at 2026-09-02T00:57:47+00:00. The queue is the source of truth; this is its projection._

- **6 done** · 0 in flight · 6 queued
- **1 waiting on a person** · 4 contested · 3 blocked

### Waiting on you

- **Most observation records are more than a week old** — waits on `human-decision-what-the-cadence-verdict-may-claim-about-stale-observations`, resumes at `FIXING`

### Contested — the reviewer still objects

- **A mission that did its work is recorded as failed, with no cause** — 3 finding(s) after 3 round(s).
- **Wire approval decisions back to the message, without racing** — 8 finding(s) after 3 round(s).
- **Say why one outreach draft is unreviewed** — 6 finding(s) after 3 round(s).
- **Wire terminal approval decisions back to the persisted message** — 8 finding(s) after 3 round(s).

_Reviewer negative control: detected the planted defect (2026-08-31T21:29:57)._

<!-- devloop:end -->
