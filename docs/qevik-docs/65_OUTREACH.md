# Outreach — prepared, and deliberately unable to send

Updated 2026-08-19.

Five drafts exist for the five ranked prospects. **Nothing has been sent, and
nothing currently can be.** That is a property of the code, not a setting.

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

### To connect a channel later

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
| Approved | 0 |
| Sent | 0 |
| Channels connected | none |

Regenerate with `infra/outreach_drafts.py`. It has no send capability; sending
requires an approved, separate step that does not yet exist.

**Known hygiene issue:** `atlas_outreach_messages` also contains rows on a
`recording` channel addressed to `b@clinic.test` — test fixtures written into
the production database by suite runs. None touch the twenty clinics, but any
"how many have we sent" query must be scoped by channel until that is cleaned up.
