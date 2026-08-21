# Email infrastructure for qevik.ai — research, not yet implemented

**Status: RESEARCH ONLY. No DNS record has been created or changed.**
Cloudflare holds the zone and Qevik has no Cloudflare token, so every record
below is a manual action for Ayoub in the Cloudflare dashboard.

## What is actually there today

Measured 2026-08-21 from `qevik-core-01`:

| Record | Value |
|---|---|
| `MX qevik.ai` | **none** |
| `TXT qevik.ai` (SPF) | **none** |
| `TXT _dmarc.qevik.ai` | **none** |
| `TXT google._domainkey` and four other common selectors | **none** |
| `NS qevik.ai` | `perla.ns.cloudflare.com`, `elliot.ns.cloudflare.com` |
| `A qevik.ai` | `104.21.30.175`, `172.67.173.123` (Cloudflare proxy) |

Two consequences, and they are the reason the first commercial test is WhatsApp
and not email:

1. **Nothing can receive mail at `@qevik.ai`.** With no MX, a reply to any
   address on the domain bounces. Sending outreach from an address that cannot
   accept a reply is worse than not sending it.
2. **Anyone can forge mail as qevik.ai, and real mail from it will be filtered.**
   With no SPF and no DMARC, a receiving server has nothing to authenticate
   against. A brand-new domain with no alignment records sending cold mail to
   UAE businesses is a spam-folder outcome, not a deliverability risk.

## Recommendation

**Google Workspace Business Starter**, two mailboxes to begin: `hello@qevik.ai`
as the reply-to, `ayoub@qevik.ai` as the human sender. Add `sales@` and
`support@` later as aliases at no cost — separate paid seats buy nothing until
there is somebody else to read them.

Why Workspace over the alternatives:

- Ayoub already operates in Google (`qevikos@gmail.com`, and the Business
  Profile and Search Console work below both live there). One identity provider
  is one place to lose access, not three.
- Deliverability from Google's outbound pools to UAE recipients is the best of
  the realistic options, and this domain has no sending reputation of its own.
- Zoho is roughly a seventh of the price and would do the job; it is the right
  answer if cost is the binding constraint. Its UAE inbox placement is
  measurably worse from a cold domain.
- **Resend / Postmark are not alternatives here.** They send transactional mail
  and give no mailbox. Worth adding later for automated sends; useless for a
  conversation.

## Exact records to create

Create in this order. The verification TXT must exist before Workspace will let
you generate a DKIM key.

**1 — Domain verification** (value comes from the Workspace signup screen):

```
Type: TXT   Name: @   Content: google-site-verification=<value from Google>
```

**2 — MX.** Google's current single-record format. Delete any other MX first;
mixed MX sets deliver to whichever host wins, which is a silent split mailbox.

```
Type: MX    Name: @   Priority: 1    Content: smtp.google.com
```

**3 — SPF.** Exactly one SPF record per domain — two is a permanent error, not a
merge. If a sender is added later (Resend, a CRM), extend this record rather
than adding another.

```
Type: TXT   Name: @   Content: v=spf1 include:_spf.google.com ~all
```

**4 — DKIM.** Generate a **2048-bit** key in Admin console → Apps → Google
Workspace → Gmail → Authenticate email, then publish what it gives you:

```
Type: TXT   Name: google._domainkey   Content: v=DKIM1; k=rsa; p=<long key>
```

Then click **Start authentication** in the console. Generating the key without
starting authentication signs nothing, and the DNS record alone looks correct
while doing nothing at all.

**5 — DMARC, starting at `none`.** Monitor first. Going straight to `reject` on
a domain whose sending patterns nobody has observed is how you discover your own
mail was being dropped.

```
Type: TXT   Name: _dmarc   Content: v=DMARC1; p=none; rua=mailto:dmarc@qevik.ai; fo=1; adkim=s; aspf=s
```

After two weeks of clean aggregate reports, move to `p=quarantine; pct=25`, then
`p=reject`.

### Cloudflare specifics

- MX and TXT records cannot be proxied; Cloudflare greys them out automatically.
  Leave the `A` records proxied as they are.
- Cloudflare's **Email Routing** feature, if it is ever enabled on this zone,
  writes its own MX records and will conflict with Workspace. It is off today.

## Before any email is sent from this domain

- **Warm up.** A domain that has never sent mail suddenly sending twenty cold
  messages is the exact shape of a spam run. Ten to fifteen a day for the first
  fortnight, to recipients likely to reply.
- **Reply-to must be a monitored mailbox**, not a send-only alias.
- The legal sender identity stays **Asia Link Internet Content Provider LLC**.
  Qevik is the product; the footer names both, which is what
  `identity.EMAIL_SIGNATURE` already produces.
- One-click unsubscribe (`List-Unsubscribe`) is required by Gmail and Yahoo for
  bulk senders. Below their volume thresholds it is still the right default.

## What this does not cover

Automated sending. `atlas_kernel.outreach.channels` has no SMTP client and every
channel raises `ChannelNotConnected`; there is no credential on the host. Wiring
a sender is a separate, reviewable change and should not happen until the offer
has a reply to show for itself.
