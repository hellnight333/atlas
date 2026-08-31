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

## 2026-08-31 — Session 4 (discovery audit)

### Traced
The discovery stage against production: 412 businesses, 359 with a website, 349
with a phone, 53 with neither. Sources: google-places 352 (100% with a site),
openstreetmap 59 (10%). Funnel: 412 discovered → 352 audited → 126 with a
signal → 4 approved → 3 published.

### Found and fixed
- **The contact cooldown could be stepped around.** Keyed on `business_id`
  alone, and four phone numbers in production are held by nine business
  records. One phone could have received three messages inside the fourteen-day
  window, each passing the guard. Now keyed on the recipient as well, with
  addresses normalised so punctuation cannot defeat it. Proven on a real shared
  number.
- **The discovery feed could not be empty honestly.** 353 of 412 businesses
  have no sighting at all and every sighting is `KNOWN`, which the feed
  excludes — so it is permanently empty and said "the scan ran and found
  nothing". Same shape as the browser defect. It now says which kind of empty
  it is.

### Not a defect
`roasterscoffee.ae` holds six business records with six different phones. Those
are six branches of a chain sharing one website, not duplicates. Merging them
would be wrong.

### Corrected
A gate reported one failure that passed in isolation — two gates were running
at once against the same database. My error; the clean run is the result.

### Human boundary
HA-001 and HA-002 cannot be executed by Claude: the Cloudflare zone and the
mailbox password are Ayoub's, and the first send is an irreversible external act
needing his authorisation.

## 2026-08-31 — Session 5 (B-12, then the critical path)

### B-12 closed at its real boundary
`EXTRACTORS` was a one-tuple holding OpenStreetMap, so no recipe could name
Places as its extractor and no Places response could become a sighting — the
source adapter existed the whole time and nothing could read what it fetched.
`GOOGLE_PLACES` is declared with the existing model: no novelty claim, no city
or country (the model refused a version that filled them from
`formattedAddress`), no phone (not a Sighting field).

**Nothing was backfilled.** The `business_discovered` events do preserve real
evidence — `place_id`, `query`, listed phone and website — but a sighting
carries a discovery state, and that state depends on whether the business was
known to Qevik at the moment it was seen. All 352 are known today.
Reconstructing 2026-08-19 would be inference presented as observation in the one
field this system is most careful about.

### Then production said something that changes the plan
**412 businesses. Zero email addresses.** No source collects one: OSM's
extractor reads name/source_url/city/country, the Places field mask has no email
field because the API does not return one, and nothing reads contacts out of the
audited homepages. 0 outreach rows have ever been addressed to an email.

So **HA-001 and HA-002 are necessary and not sufficient.** Completing both
enables email to nobody. Nothing in the system said this — outreach reports
`NO_SENDING_IDENTITY`, which reads as "the sender is missing" rather than "there
is no recipient either". The DNS action now says so in its own reason.

HA-008 and DQ-007 raised: where do addresses come from? Reading `mailto:` off an
audited homepage is technically deterministic, and it is collecting contact
details for unsolicited outreach — the substance of DQ-005, not mine to decide.

## 2026-08-31 — Session 6 (contact discovery, DQ-007)

### The framing that was wrong
"412 businesses, 0 email addresses" described Qevik's canonical data, not what
those businesses publish. They publish addresses; nothing was reading them.

### Measured on 100 real businesses
96 pages read, 0 our own failure, 4 sites did not answer:
- **61** publish a business channel
- **8** present a named individual as the contact
- **8** carry only addresses that cannot be tied to the business
- **19** publish none
- **69 email-contactable — 72%**, all 69 also reachable by phone
- 88 distinct addresses; **5 shared across businesses**; 12 businesses with
  several; **65 from `mailto`, 30 from page text** — a mailto-only reader would
  have missed a third

**External discovery is unnecessary.** No LinkedIn, no social, no open search.

### Built
Four contact types decided from page *context*, never the domain:
BUSINESS_EMAIL, INDIVIDUAL_BUSINESS_CONTACT, PERSONAL_OR_AMBIGUOUS, UNKNOWN.
An owner-operated business whose contact is a Gmail address is inventory; a
testimonial address on the business's own domain is not.

Full provenance per address: page, exact string, type, displayed name, displayed
role, association, extraction method, timestamp.

### Bugs found in my own work, by measuring
- `mailto:` addresses live in attributes, so stripping tags before reading
  context lost them entirely — the owner example classified as UNKNOWN.
- The name extractor returned "Owner" instead of "Ahmed Hassan".
- `you@company.com`, a shipped theme placeholder, was counted as two
  businesses' contact.

### Boundaries held
Discovery is not authorisation — a structural test refuses any reference to
sending, approval, suppression or cooldown from the module. Shared addresses
already participate in the cooldown fixed earlier, which is keyed on the
normalised recipient. Nothing sent.

### Then production contradicted me
I had said the field would fill through the nightly audit. It would not have.
`infra/audit_discovered.py`, where contact discovery was wired, ran **once** on
2026-08-19 and is scheduled by nothing — `website_audited` events stop there
while `website_verified` ran at 05:00 this morning. The capability was deployed
into code nobody executes.

The nightly recurrence runs `verify-recorded-websites` through the toolrunner,
whose audit step already holds every response body. Contact discovery moved
there: no second fetch, one pass over a string already in memory.

**Proven on a real run: 19 addresses written, 19 provenance events,
`email_is_addressable` true for the first time, 18 of 19 also phone-reachable.**

~48% against the browser's 72%, because the nightly pass uses plain
`http-fetch` and does not see JavaScript-rendered contacts. Measured, not
assumed; not worth a second fetching path yet.

### Next
The backlog fills at ~40 sites a night. HA-001 and HA-002 are the real blockers
again, and both are Ayoub's.

## The prospect dossier, and what it found on first contact with real data

Thirteen questions a person asks before writing to a stranger, each read from
the model that owns it: `GET /api/discovery/{business_id}/dossier`, drawn at
`#/businesses/<id>` as a chain rather than a grid, with a break in the rule
wherever a fact does not exist.

It composes nothing. What will be sent is the stored draft's own subject and
body — a second rendering here would be a second answer to a question that has
one, and the approval fingerprint would faithfully certify the difference
between what a person read and what went out. A structural test parses the
module and refuses any import that is not a read, negative-controlled against a
mutant that imports `prepare`.

### Three facts were being read from the wrong place

Each was invisible statically and each was caught by a test or by production:

* `open_signals` stops returning a signal the moment somebody approves it, so
  reading the reason for selection from it reports "no reason to approach them"
  for exactly the prospects that got furthest.
* Businesses carry no tenant at all — `save_business` writes none — so scoping
  the dossier on the company record found nothing for anybody. The gate sits on
  the signal, which is the row that has one.
* `decision == "accept"` matched nothing; the repository's word is `accepted`.

### Then production found two more

Read against four real prospects, it told the operator to "Prepare the message"
for Apex Plumbing. Nobody can: its publication records no offer, `prepare`
refuses a publication that cannot say what it is, and the dossier printed that
absence two lines above the instruction.

Behind it, the larger one. **Four of the five addresses Qevik has put on the
internet never recorded what they published.** Written before the field existed,
never re-published — so two businesses with a live artefact, an accepted review
and a reachable number were permanently unreachable, and nothing said so.

The value was never lost: `offer` is read from the delivering mission's recipe
at publication time, and that recipe id is on the mission's own ledger. It now
resolves on read — not a backfill, because the events are append-only and a
resolver cannot go stale or need remembering — and `offer_from` says whether an
offer was recorded or recovered, because a reader who cannot tell them apart
cannot audit either. It refuses at every break in the chain, each with its own
test.

Before: 1 of 3 businesses could be written about. After: 3 of 3, two of them
blocked only on `NO_SENDING_IDENTITY`.

### Next
The blockers are HA-001 and HA-002, both Ayoub's. `website_audited` has not run
since 2026-08-19 — the nightly pass writes `website_verified`, which carries
`{answered, findings}` and no observations — so fact 3 is honest but ageing.
