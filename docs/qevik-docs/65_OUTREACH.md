# Outreach — prepared, and deliberately unable to send

Updated 2026-08-19.

Five drafts exist for the five ranked prospects, approved for **manual** sending
— the operator contacts each prospect personally, and the point is to learn how
the offer lands. Nothing has been sent.

Automated email sending was built later and is a **separate path**: it requires
its own authorisation (`authorized_automated_at`), a canonical fingerprint over
the exact artefact, and an explicit send action. The five manual drafts cannot
enter it — they carry no automated authorisation, and a test asserts they never
will. See §26–27 of `QEVIK_HISTORICAL_DECISIONS.md`.

What still cannot happen is a *real* send: no SMTP credential is configured, so
`EmailChannel.configured()` is false and the channel refuses.

---

## Who is writing

Qevik is a **brand operated by Asia Link Internet Content Provider LLC**. It is
not a separately licensed UAE entity, and may become one later.

Every signature comes from `atlas_kernel/outreach/identity.py`. One place,
because a signature assembled per-message drifts, and the part most likely to
drift is the legal status.

```
Ayoub Soleimani
Qevik — by Asia Link Internet Content Provider LLC
Office 301, Al Othman Building
Deiram, Dubai, UAE
+971 50 102 9104
```

WhatsApp gets a shorter form — name, brand, number. A postal address in a phone
message reads as a mail-merge.

`entity_claims()` refuses any phrasing that presents Qevik as its own company:
`Qevik LLC`, `Qevik FZ-LLC`, `Qevik is a licensed…`, `Qevik's trade licence`,
`registered as Qevik`. Writing one of those to a Dubai business is a false claim
about a regulated status, made to someone who can check it in a public register.

The guard is tested from both directions — it fires on the false phrasings and
stays quiet on `Qevik — by Asia Link…` and `I build websites under the Qevik
name`. A guard that flags every mention of the brand is one that gets switched
off.

---

## Why nothing can send

`atlas_kernel/outreach/channels.py` defines the shape and withholds the
capability. `EmailChannel` and `WhatsAppChannel` both raise
`ChannelNotConnected`. No SMTP client, no provider SDK, no HTTP client is
imported anywhere in the package, and a test asserts that stays true.

The usual way to "prepare" a sender is to write the client and leave a flag off.
That produces a system one truthy value away from messaging twenty real
businesses. Adding a provider here is a visible diff instead.

What a channel checks, in order:

| Check | Why it is in this order |
|---|---|
| **Reachable** | Runs first. "That number cannot receive WhatsApp" stays true after a provider is added, so learning it now beats learning it on send day |
| **Approved** | An approval bound to *these words to this recipient*, not a global "sending is on" |
| **Connected** | Last, and currently always fails |

`WhatsAppChannel.can_reach` already does real work: 16 of the 20 audited clinics
publish a landline, and a WhatsApp message to a landline is not an error the
sender sees — it is silence. `outreach_drafts.py` calls it before writing any
draft that recommends WhatsApp, so a campaign cannot report five sends and
produce three.

### To connect a channel later — done for email, 2026-08-30

All four steps below were carried out for `EmailChannel`. They are kept as the
record of what was done, and as the procedure for the next channel — WhatsApp
has not been connected and, by decision, is not to be automated.

1. Write the provider adapter in its own file under `atlas_kernel/outreach/`.
2. Make `configured()` return True only when its credential is present, loaded
   from a `0600` file under `/opt/qevik/` via `EnvironmentFile=-`.
3. Leave the reachability and approval checks exactly as they are.
4. The `test_no_provider_client_is_imported_anywhere_in_the_package` test will
   fail. That is the point — change it deliberately, in the same review.

---

## Where a draft lives

Two places, on purpose:

- **`atlas_outreach_messages`** — an `OutreachMessage` row per channel, status
  `DRAFT`, `approval_id` and `approved_fingerprint` and `sent_at` all null. This
  is the record the send path will read, so approvals and receipts have one home
  rather than two answers to "was this sent".
- **`/var/lib/qevik/outreach/<slug>.json`** — the human-readable draft, for
  reading and editing before approval.

Plus an `outreach_drafted` event on the business timeline, carrying the claim
and its evidence. Without it, a later reader sees an audit, a demo, then either
silence or a message with no history — and cannot tell whether a decision was
taken or forgotten.

---

## Why a draft is still a draft

Writing the words is deliberately not asking anybody about them: every row
`outreach_drafts.py` writes stays at `DRAFT` rather than `AWAITING_APPROVAL`,
so composing text never reads as a request for a decision. The cost of that is
a pile of drafts nobody has decided about, and until now no record anywhere of
*why* any particular one was still sitting there.

`atlas_kernel/outreach/unreviewed.py` answers it per row, from the records and
never by guessing. It reads, and it can do nothing else — no approve, no send,
no delete, structurally, because a list of undecided things is the most
tempting place in this system to grow a control that decides all of them at
once.

Two questions, kept apart, because a reader needs both:

**Has anyone been asked?** Always one of two, from the row itself:

| State | Means |
|---|---|
| `NEVER_PUT_TO_A_PERSON` | still a draft, no approval, no fingerprint, no authorisation |
| `ASKED_AND_UNANSWERED` | `AWAITING_APPROVAL` — the only status that records the question being put |

**Is there something in the record a reviewer would have to settle first?** Zero
or more, most decisive first:

| Condition | Read from |
|---|---|
| `REPLACED_BY_A_LATER_DRAFT` | a later message for the same business, channel **and origin** |
| `ADDRESSED_TO_NOBODY` | `recipient` is empty — `outreach_drafts.py` writes every email row this way |
| `THE_CHANNEL_CANNOT_REACH_IT` | the channel's own `can_reach` refuses the address |
| `EVIDENCE_MOVED_AFTER_IT_WAS_WRITTEN` | `business_reevaluated` changes dated after the draft |

Each carries the record it was read from, so a person can follow every
statement back to a row rather than trust a sentence saying the records were
consulted.

**A decision is never listed as undecided.** Four independent signals decide
that, not the status column: the two messages approved by hand on 2026-08-19
carry `approved_fingerprint`, so they stay out. What becomes of them is DQ-008
and belongs to a person.

**"The channel cannot send today" is not one of the reasons.** Reviewing is
deciding whether these words may go to this business; sending is a separate act
behind its own authorisation, and folding a missing SMTP credential in here
would tell an operator that a decision they *can* take is blocked on one they
cannot.

Read it at `GET /api/missions/outreach-unreviewed` — `GET` and `READ` only —
and on the Publications screen in app.qevik.ai, under **Drafted, never
decided**. The screen prints the kernel's wording and has no control on it.

The four conditions were not invented for the code. Each is something the
written record already says about the drafts that exist:
`73_FIRST_COMMERCIAL_TEST.md` holds Dubai Sky Clinic and Klinika back because
both are landline-only, which is `THE_CHANNEL_CANNOT_REACH_IT`; the email rows
`outreach_drafts.py` writes carry an empty recipient because no discovered
business held an address when they were composed (HA-008, DQ-007), which is
`ADDRESSED_TO_NOBODY`; and the shape of the Kings problem — a live re-check
contradicting what the words claim — is `EVIDENCE_MOVED_AFTER_IT_WAS_WRITTEN`,
though that particular message is approved and so belongs to DQ-008 rather than
to this list. All of it was recorded by hand, in documents, where nothing could
read it per draft. What is new is that the
answer is now read from the rows themselves, per draft, and does not depend on
somebody having written a paragraph about it.

---

## What a draft may say

Assembled from that prospect's dossier, then checked before being written. A
draft that would make a forbidden claim is **refused**, not flagged.

Refused for everyone:

- `book your appointment`, `booking system`, `we have booked` — there is no
  booking backend
- `guaranteed`, `#1 on google` — no outcome is promised
- `your website is down` — a 30-second timeout is slowness, not death
- `free forever` — no pricing has been agreed
- any phrasing from `FORBIDDEN_ENTITY_CLAIMS`

Refused per prospect, from their own audit:

- anything their site **already has** — they know their site, and one wrong
  claim discredits the rest
- anything **NOT_VERIFIED** — the audit reads the homepage; a feature can live
  on an inner page
- anything **the demo does not do** — doctors, insurers, testimonials,
  emergency info, and the appointment form

The guard caught its own author: the honest sentence "wiring it to a real
booking system is a decision for later" tripped `booking system`. The copy was
reworded rather than the guard weakened — a guard with exceptions eventually
lets the dishonest version through on the same exception.

Every email carries the placeholder disclosure, and a test asserts it:

> the appointment form on that example is a placeholder. It does not send
> anywhere yet, and it says so on the page itself.

---

## Current state

| | |
|---|---|
| Drafts written | 5 (Kings, Malabar, Dubai Sky, TopDent, Klinika) |
| Status | `DRAFT` / `DRAFT_NOT_SENT` |
| Approved | 0 **as of 2026-08-19** — see below |
| Sent | 0 |
| Channels connected | none |

**The approved count is stale, and this line is not the place to correct it.**
`.qevik/DECISION_QUEUE.md` DQ-008 records two messages approved by hand on
2026-08-19 that carry `approved_fingerprint` and have never been sent, and
`.qevik/PRODUCTION_EVIDENCE.md` E-34 measured them in production on 2026-08-31.
Whether those two are withdrawn, re-approved or left where they are is DQ-008
and belongs to a person; the reader described above simply keeps them out of the
undecided list, because they are decisions somebody took.

For what is actually on file at any moment, read
`GET /api/missions/outreach-unreviewed` rather than this table. A count written
into a document is true on the day it is written.

Regenerate with `infra/outreach_drafts.py`. It has no send capability; sending
requires an approved, separate step that does not yet exist.

---

## Test contamination — fixed 2026-08-19

The suite had **no database isolation**. It wrote to whatever
`ATLAS_DATABASE_URL` pointed at, which on this server is production, and every
run left rows behind: **108 outreach rows** on a `recording` channel addressed to
reserved test domains, plus **81 events referencing businesses that were never
saved**. None touched the twenty audited clinics, but the contamination made
"how many businesses have we contacted" unanswerable without knowing which rows
to ignore.

**Isolation.** `packages/kernel/tests/conftest.py` redirects `ATLAS_DATABASE_URL`
to `<database>_test` before `atlas_kernel.db` builds its engine — which is why it
sits above the other imports and must stay there. Redirecting rather than asking
each test to opt in is deliberate: an opt-in is what a new test forgets, and that
failure is silent.

**Quarantine, not deletion.** `infra/quarantine_fixtures.py` copies each row
whole into `atlas_quarantined_fixtures` with its source table and the reason,
then removes it from production. Reversing it is a SELECT. It refuses to run if
any candidate belongs to one of the twenty, and rolls back in the same
transaction if their row count moves.

**The guard.** `test_production_is_not_a_test_fixture.py` opens the *production*
database read-only and asserts it stays clean: no test-only channel, no reserved
test domain, no orphaned event, twenty businesses with a demo, every demo backed
by an audit, and nothing on the email or WhatsApp channels that is no longer an
unsent draft. It lives outside the redirect on purpose — a guard inside the thing
it guards verifies nothing. It skips, rather than fails, where production is
unreachable.

**Re-drafting** used to add five rows per run. It now replaces prior drafts,
scoped to rows that are still a draft *and* carry no approval, no fingerprint and
no send time — anything approved or sent is history and is never touched.

---

## Measuring the experiment

`atlas_kernel/outreach/experiment.py` records the commercial test as events on
the timeline each business already has. No new table, and no mutable `stage`
column — a funnel computed from current state cannot show that a prospect
replied, took a meeting, and then went quiet.

| Stage | Captures |
|---|---|
| `experiment_prepared` | prospect, channel, message version, demo URL |
| `experiment_sent` | sent timestamp (timezone required), channel, version |
| `experiment_response` | response type **and their words, unsummarised** |
| `experiment_meeting` | whether it happened |
| `experiment_objection` | one per event, so the same objection is countable |
| `experiment_price_discussed` | amount, currency, recurring, accepted-or-not |
| `experiment_outcome` | won / lost / no_reply / disqualified, and why |

`fold()` derives the current state. Two distinctions it protects:

- **`not_contacted` is not `no_reply`.** A prospect nobody messaged is not a
  result — counting it as one puts a zero in the numerator and a one in the
  denominator of the only ratio this exercise produces.
- **`accepted: None` is not `accepted: False`.** A price named and unanswered is
  not a price refused.

`message_version` is a digest of the exact wording sent, so "which version got
replies" is answerable a week later.

Record by hand — the first contact is made from a phone:

```
infra/experiment.py prepare
infra/experiment.py sent --slug demo-x --at 2026-08-19T14:30+04:00
infra/experiment.py response --slug demo-x --type interested --says "..."
infra/experiment.py objection --slug demo-x --says "already pay someone"
infra/experiment.py status
```

A naive timestamp is refused: the operator is at +04:00 and the server records
UTC, and the one thing this measures is how long a reply took.
