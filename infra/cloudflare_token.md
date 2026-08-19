# Cloudflare API token — scope, storage, and what Qevik may change

**Token status: NOT YET CREATED.** Creating it requires the Cloudflare dashboard,
which only the operator can reach. This document specifies exactly what to create
and what the code is permitted to do with it, written *before* any token exists so
the boundary is agreed rather than discovered.

Updated 2026-08-19.

---

## 1. Permissions to grant

*My Profile → API Tokens → Create Token → Custom token.*

| Permission | Level | Why it is needed |
|---|---|---|
| **Zone → Zone** | **Read** | Resolve the zone id, confirm the zone is active, read its nameservers to detect delegation drift |
| **Zone → DNS** | **Edit** | Create and update the records for new customer and demo hostnames — the infrastructure maintenance this token exists for |

**Zone Resources:** `Include → Specific zone → qevik.ai`. This zone only. Never
"All zones from an account".

**Client IP Address Filtering:** `Is in → 2.28.62.83/32`.

This restriction is compatible with how the token is used. Every call originates
from `qevik-core-01` itself — the code runs on the server, under systemd, reading
the credential from the server's own filesystem. There is no path where the token
is used from a laptop, a CI runner, or a browser. A copy of this token taken from
anywhere else is inert.

**Expiry:** 90 days.

### Deliberately not granted

- **Zone Settings → Edit.** The directive allows it "only if a later Qevik
  operation genuinely requires it". None does today: the SSL/TLS mode is set
  correctly and nothing in the roadmap changes it. Adding it now would be power
  held on speculation. If an operation later needs it, that is a separate
  request with a stated reason.
- **Zone Settings → Read.** Dropped from the earlier read-only proposal. With
  DNS Edit present, the marginal value of reading the SSL mode does not justify
  another permission; the mode is observable from the outside by whether the
  origin handshake succeeds.
- **Cache Purge.** Measured, not assumed: every response from `qevik.ai`,
  `app.qevik.ai` and `sites.qevik.ai` returns `cf-cache-status: DYNAMIC`.
  Cloudflare caches none of this HTML, so there is nothing to purge.
- **Workers, Account Admin, Billing, User, Memberships, Load Balancing,
  Firewall, Page Rules, SSL certificates** — all excluded, as directed.

---

## 2. What Qevik is allowed to change

The token *technically* permits any DNS edit in the zone. The code narrows that
much further, because a permission is a ceiling and not a policy.

### Allowed, and only as part of an approved operation

- **Create** an `A` record for a new subdomain of `qevik.ai` pointing at
  `2.28.62.83`, proxied.
- **Update** an existing `A` record's target **only** when it already points at
  `2.28.62.83` — i.e. reclaiming a record Qevik itself created.

### Refused by the code, regardless of what the token allows

| Refused | Why |
|---|---|
| `qevik.ai`, `www`, `app`, `sites` | The four records serving production. An agent editing these can take the whole business offline, and did not need to. |
| Any `NS` record | Nameserver changes are delegation changes. Explicitly out of scope. |
| Any `MX` record | Mail delivery. Nothing here sends or receives on this domain, and a wrong `MX` silently loses mail. |
| `SOA`, `DNSKEY`, `DS` | Zone authority and DNSSEC. |
| **Deleting any record** | There is no operation that needs it. A delete is the one DNS mistake with no partial recovery. |
| Any record outside `qevik.ai` | Enforced by the token's zone scope *and* by the code. |
| Registrar or delegation settings | Not reachable by this token at all — those live in the account/registrar API, which is not granted. |

### Nothing happens automatically

A DNS write is an **outward-facing action** and goes through the same approval
gate as publishing a site: it requires an approval object bound to the exact
resolved parameters — record name, type, and target — which the plan cannot
construct for itself. An approval authorises *one* change to *one* record and is
consumed when used.

There is no scheduled job, timer, or autonomous loop that writes DNS. Every write
traces to an operation the operator approved.

---

## 3. Storage

```
/opt/qevik/cloudflare.env      # 0600, root:root
```

One line: `QEVIK_CLOUDFLARE_API_TOKEN=...`, referenced by the unit as
`EnvironmentFile=-/opt/qevik/cloudflare.env`. The leading `-` means a missing
file never fails the service — the same pattern as every other credential here.

- **Not in Git.** `/opt/qevik/` is outside the repository; `.gitignore` covers `*.env`.
- **Not in logs.** Sent as an `Authorization` header; the client never logs the
  header, and failure paths print the HTTP status and Cloudflare error code only.
- **Not in reports, generated pages, or chat output.**
- **Not in this file.**

### Placing it

Do this yourself, so the token never passes through a transcript:

```
ssh -i ~/.ssh/naml_hetzner root@2.28.62.83
umask 077
printf 'QEVIK_CLOUDFLARE_API_TOKEN=%s\n' 'PASTE_TOKEN_HERE' > /opt/qevik/cloudflare.env
chmod 600 /opt/qevik/cloudflare.env
```

Cloudflare's *Verify* button on the token page confirms it works before it is
placed anywhere.

---

## 4. Rotation

- **Expiry:** 90 days, set at creation. First expiry falls on **2026-11-17**.
- **Rotation:** create the replacement first, place it, confirm
  `cloudflare_status.py` still reports the zone, then delete the old token in
  the dashboard. Overlapping rather than gapped, so a failed rotation is not an
  outage.
- **On suspected exposure:** delete the token in the dashboard immediately —
  that is the revocation, and it is instant. Then rotate. Because the token is
  IP-filtered and read/DNS-scoped, the exposure window's worst case is a DNS
  change from `2.28.62.83`, which is the server the operator controls.
- **A token that never expires is not a convenience**, it is a permanent
  liability for an occasional capability.

---

## 5. Verifying, once it exists

```
.venv/bin/python infra/cloudflare_status.py
```

Reports the zone status, its nameservers, and every record with its proxy state
— all reads. It prints no secret. If the token is absent it says so and exits 0,
because a missing optional credential is not a failure.
