# QEVIK HUMAN ACTIONS

Things only Ayoub can do. **No secret values in this file, ever** — variable
names, where to obtain them, and how Qevik will verify them.

Derived from repository state and from the live action centre
(`GET /api/missions/actions`), not copied from a specification. Every row here
is also surfaced in app.qevik.ai.

| ID | Action | Category | Why needed | Blocks | Exact human step | Credential / account | Where | Verification | Status | Priority |
|---|---|---|---|---|---|---|---|---|---|---|
| HA-001 | Create the DNS records for qevik.ai | DNS | **Now the real blocker.** HA-008 is resolved and roughly 258 businesses are addressable once the nightly audit fills the field. With no MX a reply bounces; with no SPF/DMARC a receiving server has nothing to authenticate against and cold mail from a new domain is filtered rather than delivered | C-13, C-14, and the whole commercial chain past preparation | Create MX, SPF (TXT), DMARC (TXT `_dmarc`) and the DKIM key. Exact values and the order to create them are in `docs/qevik-docs/70_EMAIL_INFRASTRUCTURE.md`; the verification TXT must exist before a DKIM key can be generated | Cloudflare account (holds the zone; Qevik has no token for it) | dash.cloudflare.com | `outreach/deliverability.measure()` finds MX, SPF and DMARC. The action closes itself on the next read of the action centre | OPEN | 1 |
| HA-002 | Provide the mailbox and SMTP settings | CREDENTIAL | `EmailChannel.configured()` is false, so nothing can send | C-13, C-14 | Create the mailbox (Google Workspace recommended in `70_EMAIL_INFRASTRUCTURE.md`), then set the five settings on the host | `QEVIK_SMTP_HOST`, `QEVIK_SMTP_PORT`, `QEVIK_SMTP_USER`, `QEVIK_SMTP_PASSWORD`, `QEVIK_SMTP_FROM` | Credential centre in app.qevik.ai, or `/opt/qevik/atlas.env` | All five present, so `EmailChannel.configured()` is true. **Sending is proven only by a message arriving in a real inbox with SPF, DKIM and DMARC passing in its headers** — not by the settings existing | OPEN | 1 |
| ~~HA-008~~ | ~~Decide where email addresses come from~~ **DONE 2026-08-31** — read from audited pages; 72% of a real sample carry one | PRODUCT_DECISION | 412 businesses carry **0** email addresses and no source collects one. HA-001 and HA-002 together enable email to nobody | C-13, and the first real send by email | Decide DQ-007: read `mailto:` from audited homepages, buy a source, or stay on manual WhatsApp | none | — | `outreach_reachability()` reports `by_email > 0` | OPEN | 1 |
| HA-003 | Provision the HP Z8 | PHYSICAL | It has never registered with the fleet | C-19 | `sudo bash infra/provision_node.sh`, reboot, run it again; then `sudo tailscale up --hostname=atlas-z8` — that opens a URL you approve in a browser, which is why nobody else can do it for you | Tailscale login | In front of the machine | A worker whose machine is `atlas-z8` appears in Fabric and reports a heartbeat | OPEN | 3 |
| HA-004 | Provision the Lenovo i9 | PHYSICAL | Same | C-20 | As HA-003, with `--hostname=atlas-lenovo` | Tailscale login | In front of the machine | A worker whose machine is `atlas-lenovo` appears in Fabric and reports a heartbeat | OPEN | 3 |
| HA-005 | Make the ledger reachable from the tailnet | NETWORK | A worker connects straight to Postgres. On qevik-core-01 it listens on 127.0.0.1 only and Tailscale is not installed, so a fully provisioned machine with an approved Tailscale login would still have nothing to connect to | C-19, C-20 — and it is a prerequisite for both, so doing it once serves both | Install Tailscale on the control plane and run `tailscale up`; bind Postgres to the tailnet address as well as loopback and allow the worker's user from that network in `pg_hba.conf`. **Do not expose 5432 to the public internet** — the tailnet is the point | Tailscale login, root on qevik-core-01 | tailscale.com/download/linux | A worker running on another machine appears in Fabric and reports a heartbeat | OPEN | 3 |
| HA-006 | Provide the Google Places key | CREDENTIAL | OpenStreetMap knows 2–17% of businesses are contactable; Places knows nearly all. Without it discovery finds businesses it cannot reach | Quality of C-01, and therefore how many opportunities carry a verified recipient | Create an API key with the Places API enabled | `QEVIK_GOOGLE_PLACES_API_KEY` | console.cloud.google.com/apis/credentials | **No probe, deliberately** — Places bills every authenticated request. Verified instead by a discovery run returning businesses with a phone or a website | OPEN | 2 |
| HA-007 | Provide a model-provider credential | CREDENTIAL | No model is registered, so any model-backed role refuses to start rather than substituting one silently | Model-backed planning and review. **Not** the health-check or website paths, which call no model | Add one key through the credential centre | `QEVIK_ANTHROPIC_API_KEY`, `QEVIK_OPENAI_API_KEY` or `QEVIK_DASHSCOPE_API_KEY` — one is enough | Each provider's console | The credential centre's Test button, which lists models and changes nothing | OPEN | 2 |

The live action centre (`GET /api/missions/actions`) is authoritative for the
full list and currently serves twelve, including analytics and search-console
credentials that nothing yet reads. Rows are promoted here when a capability
actually waits on them.

## Not yet actions

These appear in the roadmap's externally-blocked list and are **not** open
actions, because nothing in the repository is waiting on them. Raising them now
would put permanent items at the top of a list whose value is that its top is
real.

- Amazon, Noon, YouTube, Instagram, advertising credentials — C-33, no adapter.
- Apple Developer, Google Play — C-31, no app factory.
- Image / video / music / STT / TTS providers — C-30, and the provider choice
  is itself an open decision (DQ-004).
- Stripe — C-29. Payment Links need no key; the adapter is deliberately unbuilt.

Move a row up when the capability that needs it exists.

<!-- human-action:public-assets -->
## HA-008 — qevik.ai cannot be rebuilt: its artwork is not in the repository

**Open.** Raise in app.qevik.ai as a DECISION with three options as soon as the
control plane is reachable — the SSH link is currently degrading (HTTPS answers
200, TCP/22 connects, the banner exchange times out), so this file is the record
until then.

Every route on qevik.ai serves the homepage and no URL returns 404. The fix is
written and reviewed — `infra/qevik-production.Caddyfile` and the 404 page in
`apps/public/build.py`, landed as `f1171ef` and `5b20f59`.

It cannot be applied. The config rewrites unknown URLs to `/404.html`, and
building that page needs `apps/public/assets/` — 12 photographs and 2 icons a
blanket `assets/` rule at `.gitignore:85` keeps out of the repository. Without
them the site does not build, the page is not produced, and
`deploy_public.sh --check` correctly refuses to install a config pointing at a
file that will not exist.

The images are on the host at `/srv/qevik-public/assets/`.

**The options, each reversible:**

- **track** — except `apps/public/assets/` from the ignore rule and commit the
  14 files. Any checkout can then build and verify the site. About half a
  megabyte.
- **fetch** — pull them from the host at build time. No binaries in git, but a
  build then needs host access, and the tests that skip today keep skipping
  anywhere else.
- **elsewhere** — an object store or another location you name. Needs the
  location, and a credential if it is private.

**Nothing is deployed, no image is invented, and the ignore rule is not touched
without an answer.** Two completed tasks are waiting on this.
