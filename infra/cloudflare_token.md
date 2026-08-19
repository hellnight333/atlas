# Cloudflare API token — proposal

**Status: NOT REQUESTED YET.** This document exists so the exact permissions can
be approved before a token is created. No token has been asked for, issued or
stored.

## Why a token at all

Three things are currently unverifiable from the server, and each has already
cost time:

1. **Which SSL/TLS mode the zone is in.** Whether the origin should serve HTTP
   or HTTPS behind the proxy is determined entirely by this setting, and today
   the only way to know it is for the operator to read it in the dashboard.
2. **Whether a DNS record is proxied.** A record flipped to DNS-only exposes the
   origin IP and bypasses every protection in front of it; a record flipped to
   proxied makes TLS-ALPN-01 impossible. Both have concrete failure signatures
   that are cheap to detect and expensive to guess at.
3. **Whether the records still point here.** A silent change is the single most
   likely cause of a future "the site is down" that is not the server's fault —
   the misdiagnosis this project has already paid for once.

All three are **reads**. None of them require the ability to change anything.

## Exact permissions requested

Created at *My Profile → API Tokens → Create Token → Custom token*.

| Permission | Level | Why |
|---|---|---|
| **Zone → Zone → Read** | Read | Confirm the zone exists, is active, and which nameservers it uses |
| **Zone → DNS → Read** | Read | Confirm the four records still point at `2.28.62.83` and which are proxied |
| **Zone → Zone Settings → Read** | Read | Read the SSL/TLS mode, so the origin's HTTP-vs-HTTPS question is answered by observation |

**Zone Resources:** `Include → Specific zone → qevik.ai` — this zone only, not
"all zones from an account".

**Client IP Address Filtering:** `Is in → 2.28.62.83/32`. The token is used from
the server, so a token leaked from the server is useless from anywhere else.

**TTL:** set an expiry — 90 days. A token that never expires is a permanent
liability for a capability that is only occasionally useful.

### Deliberately excluded

- **Every write permission.** Nothing in the current or planned work changes a
  Cloudflare record. DNS was left manual on purpose: an agent that can create
  DNS records can also repoint an existing production hostname, and that
  belongs behind an approval gate, not inside a convenience token.
- **Cache Purge.** Measured rather than assumed: every response from
  `qevik.ai`, `app.qevik.ai` and `sites.qevik.ai` returns
  `cf-cache-status: DYNAMIC`, so Cloudflare is caching none of the HTML. There
  is nothing to purge, and the permission would be power held for no reason.
- **Account-level permissions of any kind.**

## What the token can and cannot do

**Can:** read the zone's status, its DNS records, and its settings — the same
information the dashboard shows on three read-only pages.

**Cannot:** create, edit or delete a DNS record; change the SSL/TLS mode; alter
a firewall or WAF rule; purge cache; touch any other zone; touch account
settings, billing or members; be used from any IP other than the server.

The worst case if it leaks is that someone learns `qevik.ai` points at
`2.28.62.83` — which is public information, recoverable with `dig`.

## Storage

```
/opt/qevik/cloudflare.env      # 0600, root:root
```

containing one line, `QEVIK_CLOUDFLARE_API_TOKEN=...`, referenced by the unit as
`EnvironmentFile=-/opt/qevik/cloudflare.env`. The leading `-` means a missing
file never fails the service, which is how every other credential on this host
already works.

- **Not in Git.** `/opt/qevik/` is outside the repository, and `.gitignore`
  already covers `*.env`.
- **Not in logs.** The client sends it as an `Authorization` header and never
  writes it to output; the failure path prints the HTTP status, not the request.
- **Not in this document, or any other.**

## What I need from you

Create the token with exactly the three read permissions above, scoped to
`qevik.ai`, IP-filtered to `2.28.62.83/32`, with a 90-day expiry — then place it
on the server yourself:

```
ssh -i ~/.ssh/naml_hetzner root@2.28.62.83
umask 077
printf 'QEVIK_CLOUDFLARE_API_TOKEN=%s\n' 'PASTE_HERE' > /opt/qevik/cloudflare.env
```

Doing it that way means the token never passes through a chat transcript.
Cloudflare's own *Verify* button on the token page confirms it works before it
goes anywhere.
