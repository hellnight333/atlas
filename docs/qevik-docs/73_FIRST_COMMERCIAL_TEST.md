# The first commercial test

**Status: five drafts prepared, zero sent. Sending is not possible from this
system** — `atlas_kernel.outreach.channels` imports no client of any kind, every
channel raises `ChannelNotConnected`, and no SMTP, WhatsApp, Meta or Twilio
credential exists on the host.

## What is being tested

One question: **will a real Dubai business owner reply to an unsolicited message
that names a specific, verified problem with their website and links to
something working?**

Not whether they buy. A reply is the signal; everything after it is a
conversation Qevik has never had and cannot design in advance.

Two things are varied deliberately, because five messages cannot support more:

| Variable | Arm A | Arm B |
|---|---|---|
| **What we link to** | a demo built for *them* (3 clinics) | a Qevik sample from *their trade* (2 non-clinics) |
| **Industry** | dental (3) | staffing and catering (2) |

The comparison is qualitative. Five messages will not produce a statistic, and
treating them as one would be the second-worst outcome after sending something
untrue.

## How the five were chosen

Every audited business was scored 0–100 on the Commercial Opportunity Score
(`atlas_kernel.outreach.scoring`), where each component must be explainable from
a stored event: reachability 20, confirmed weakness 25, Qevik improvement 25,
apparent quality 15, evidence confidence 10, outreach relevance 5.

Two rules do most of the work:

- **A weakness Qevik cannot fix scores their pain but never becomes a sentence.**
  Every audited clinic is missing `booking_link` and Qevik has no appointment
  backend, so it is excluded from `FIXABLE` and the message generator cannot
  reach it.
- **`unverified` scores nothing in either direction.** It lowers confidence
  rather than raising weakness, because the honest response to not knowing is to
  claim less.

Then every candidate's claims were **re-tested live** (`infra/verify_claims.py`)
before any message was written. This changed the answer materially:

- **Three of Malabar's five recorded weaknesses were already fixed.** Its score
  fell 86 → 78 and two sentences were removed from its draft.
- **"No HTTPS" was false for three prospects.** The audit only knew their
  *listed* URL began `http://`; all three serve HTTPS and redirect to it
  correctly. That claim would have been wrong in the opening line.
- **Kings' audit had never completed** — two zero-byte responses. The live check
  found the site *does* load, in 15.8 seconds. The approved message says it "did
  not finish loading within 30 seconds", which is no longer accurate.

Verification also exposed a bias in the ranking itself: re-checking only ever
*lowers* a score, so an unverified list puts whichever businesses we looked at
least recently on top. Confidence now prices staleness in, and
`--verified-only` ranks solely among re-checked prospects.

## The five

| # | Prospect | Score | Contact | Confirmed claim used | Linked to |
|---|---|---|---|---|---|
| 1 | Malabar Dental Clinic | 78 | 052 151 4300 | no Arabic version | demo built for them |
| 2 | The TopDent | 69 | 052 275 7585 | no Arabic version | demo built for them |
| 3 | Pearl Dental implants & Aligners | 67 | 054 475 2767 | no Arabic version | demo built for them |
| 4 | 360 Agency / StaffFinder.io | 86 | 058 550 0125 | number not tappable on mobile | `sample-meridian` |
| 5 | AHS Catering & Events | 83 | 054 567 5675 | number not tappable on mobile | `sample-nar` |

All five are UAE mobiles, so all five are WhatsApp-reachable. This is not a
preference — `70_EMAIL_INFRASTRUCTURE.md` shows qevik.ai has no MX, so an email
from the domain cannot receive a reply.

### Changes from the originally proposed five, with reasons

- **Kings — removed.** Last of eighteen clinics at 37/100. Its audit never
  completed, so nothing about its site was confirmed either way, and the live
  re-check refutes the specific wording of its already-approved message. It
  should not be sent as approved. It is a legitimate prospect for a *rewritten*
  message about a 15.8-second homepage, which needs fresh approval.
- **Dubai Sky Clinic (69) and Klinika (67) — held back.** Both are strong on
  evidence; both are landline-only. A landline is a phone call through
  reception, which is a different experiment with a different failure mode, and
  email to them is not available. Better as a second wave.
- **360 Agency and AHS Catering — added.** The two highest verified scores in
  the whole pool, both with mobiles, both outside dental. They exist in this
  test because the positioning says Qevik is not a dental website generator, and
  that claim has never been tested.

## Price

**One number, and only when asked: AED 1,500 setup + AED 199/month.**

No tiers in the first test. Three options asks a prospect to evaluate Qevik's
pricing structure before they have decided whether they want anything at all,
and it converts "do you want this?" into "which of these?", which is a question
they answer by leaving. `offer.PRICE_IN_FIRST_MESSAGE` is `False` and the
message generator refuses any draft containing a price.

The three internal positions exist for later, and are not to be quoted yet:
entry website, professional website, custom digital product.

## What gets recorded, and where

No new table. Everything folds onto the `BusinessEvent` timeline each business
already has:

| Event | Meaning |
|---|---|
| `prospect_scored` | the score and every component's reasoning |
| `claims_verified` | each intended claim re-tested live, with its verdict |
| `experiment_prepared` | a draft exists, `sent: False` |
| `experiment_sent` | **a human confirms they sent it, with the real time** |
| `experiment_response` | what came back, verbatim |
| `experiment_objection` | what they actually cared about |
| `experiment_outcome` | how it ended |

`NOT_CONTACTED` and `NO_REPLY` are different states and are never merged.
Silence is not rejection. A draft being approved is not a send, and nothing is
marked sent because a draft exists.

## Success criteria

In order, and none of them is "more product":

1. One real reply of any kind.
2. One prospect asks for more information.
3. One prospect asks the price.
4. One prospect accepts a call.
5. One prospect asks *"how much to do this for us?"*
6. One prospect pays.

Until (1) exists, further product work is speculative.

## Product gaps — recorded, not built

Only two are known from evidence rather than guessed, and neither is being
implemented:

- **Appointment booking.** Absent from every audited clinic and excluded from
  everything Qevik offers. If two or more prospects ask for it unprompted, it
  becomes a real requirement. One asking is a conversation, not a roadmap.
- **A sendable email identity.** Not a product gap so much as a precondition;
  `70_EMAIL_INFRASTRUCTURE.md` has the exact records. Needed before any outreach
  that is not WhatsApp.

## Stop list

Not to be built until commercial evidence demands it:

Projects · Inbox · Video Factory · ElevenLabs · Twilio · publishing adapters ·
analytics · revenue dashboards · autonomous measurement loops · further
portfolio samples · further games · further SaaS demos · another website
template · another infrastructure refactor · appointment booking · a CRM ·
a second prospect or customer table · automated sending of any kind ·
a Cloudflare API token · reopening `:8443`.
