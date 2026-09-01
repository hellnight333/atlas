# UX / product gap assessment — evidence from the running system

Audited 2026-09-01 against `https://qevik.ai`, `app.qevik.ai`, `/srv/qevik-public`
on qevik-core-01, and the repository. Every claim below is a measurement.

## 1. The public site's entire content is unreachable

This is not a design gap. It is a production defect, and it is the largest
single finding of the audit.

`https://qevik.ai/services/` returns **the homepage** — 25,331 bytes, title
"Qevik — digital products built around your business". On disk at
`/srv/qevik-public/services/index.html` there is a real page: 7,362 bytes,
title "Services — Qevik".

Every route behaves this way:

| route | on disk | served |
|---|---|---|
| `/services/` | 7,362 B, "Services — Qevik" | homepage |
| `/about/` | 5,919 B | homepage |
| `/contact/` | 5,030 B | homepage |
| `/work/` | 16,850 B | homepage |
| `/ar/` | 20,575 B — the whole Arabic site | homepage |
| `/work/{apex,atelier,carrot,clinic,foundry,hire360,homefix,…}` | 7 case studies | homepage |
| `/nonsense-does-not-exist/` | — | homepage, **HTTP 200** |

**Cause**, read from `/etc/caddy/Caddyfile`:

    root * /srv/qevik-public
    try_files {path} /index.html
    file_server

`try_files` tests for a *file*. `/services/` is a directory, so it misses and
falls through to the SPA-style `/index.html` fallback. The site is not a SPA —
`apps/public/build.py` generates five pages plus case studies and a sitemap.

**Consequences measured, not supposed:**

- Roughly 60 KB of written marketing content, an entire Arabic site and seven
  case studies are invisible to every visitor.
- `sitemap.xml` advertises 10+ URLs; every one serves identical bytes. Search
  engines are being handed a site of duplicates.
- There is no 404 at all. Any URL returns 200 and the homepage.
- The nav links `/services/`, `/work/`, `/about/`, `/contact/` — so **every
  navigation click on the site is broken.**

Nothing in §1–§6 of the product direction can be built on top of this: there is
no point designing HOW IT WORKS, FEATURES, INTEGRATIONS or PRICING pages while
the server cannot serve a second page.

### Status — fixed in the repository, not yet on the host

`infra/qevik-production.Caddyfile` — the file `infra/deploy_console.sh` copies to
`/etc/caddy/Caddyfile` — no longer carries the SPA fallback. The `qevik.ai` block
is now `root` + `file_server`, which resolves a directory to its own
`index.html`, plus a `handle_errors` block that serves a real 404 page with a 404
status (and the Arabic one under `/ar/`). `apps/public/build.py` builds
`/404.html` and `/ar/404.html` from the same shell as every other page; both are
`noindex` and neither is in the sitemap.

There was a third way to be broken, and it was the live one: **nothing in this
repository had ever written to `/srv/qevik-public`.** `deploy_console.sh` copied
the Caddyfile and restarted Caddy; the public site had reached the host by some
other route entirely. Installing the fixed config on its own would have pointed
`handle_errors` at two files the host has never had, and every unknown URL would
have answered with a bare file-server error while the deploy exited zero — the
same shape of failure as the original defect.

So `infra/deploy_public.sh` builds the site, ships it to the document root the
Caddyfile declares — refusing if the build is missing any path that Caddyfile
rewrites to — and then installs that Caddyfile as `/etc/caddy/Caddyfile`,
validates it on the host, restarts Caddy (restart, not reload: the admin API is
off), puts the previous config back if Caddy does not come up, and asserts at the
origin — not through Cloudflare — that `/services/` serves its own page, that an
unknown URL answers 404 with the built page, and that an unknown URL under `/ar/`
answers in Arabic. It exits non-zero if any of that is untrue.

### The fourth way to be broken, and it was also live

All of the above was committed, reviewed and tested on 2026-09-01, and every URL
on qevik.ai still served the homepage — because **nothing ran it.** The pages
were published by `deploy_public.sh` and the config was installed by
`deploy_console.sh`, and the development loop's `deployed` gate
(`infra/devloop/gates.py`) runs `infra/deploy_control.sh`, which called neither.
The task was marked done and production-verified against a site that had not
changed.

Two things follow from that, and both are now true:

- The two halves are **one script**. `deploy_public.sh` owns the pages and the
  config together; `deploy_console.sh` no longer installs the Caddyfile itself.
  There is nothing left for a second script to forget.
- `infra/deploy_control.sh` — the script the gate actually executes — runs it,
  last, after the kernel, console and workers are verified up, and then checks
  that `app.qevik.ai/api/health` still answers JSON through the restarted Caddy.

Guarded by `packages/kernel/tests/test_public_serving.py`, which asserts the
config is the one that serves a page per URL, that the built artefact satisfies
it, that the deploy carries both to the host together, and that the script named
in `gates.py` is the one that does it — reading that name out of the gate rather
than repeating it. Any one of the four alone passed while the site was broken.

### What that deploy must not take away

Installing the fix replaces `/etc/caddy/Caddyfile` in full, and that file is the
whole web server: `qevik.ai`, the operator console at `app.qevik.ai`, every
customer site at `sites.qevik.ai`, and the fallback door on the bare IP. Anything
the host serves that is not also in `infra/qevik-production.Caddyfile` stops
being served at the restart — silently, with a zero exit, and unseen by every
check the deploy makes afterwards, all of which ask about `qevik.ai`.

Two mechanisms in `infra/` produce exactly that. `enable_domain.sh` puts a
customer domain in `/etc/caddy/sites.d/` and relies on an `import` in the live
config to pull it in; `secure_8443.sh` rewrites the `:8443` block's address in
place to take that port off the public internet. Neither is in the repository's
copy of the config.

So `deploy_public.sh` now reads the config the host is running **before it
touches anything**, compares the set of site addresses and top-level imports
against the one it is about to install, and refuses if the host serves something
this config does not — naming it. This is deliberately stricter than the same
question about the document root, which is reported and not refused: a host-only
file 404s one URL and might have been left by anyone, while a host-only site
block takes a whole hostname off the air and every site block on a server is
deliberate. `bash infra/deploy_public.sh --check-config <file>` asks it of a
file, without a host.

If that refusal fires, it is a real finding and it needs a person: the block on
the host has to be copied into `infra/qevik-production.Caddyfile` before the
deploy can proceed.

**The measurements above still describe the live site**, and will until a deploy
runs. Applying this needs the host: it is the loop's `deployed` gate, or an
operator running `bash infra/deploy_public.sh` with the SSH key. No claim of
production verification belongs here until `https://qevik.ai/services/` returns
its own page and an unknown URL returns 404.

## 2. What the site actually says today

One page, 1,569 visible words, eight sections: *What Qevik is · Who it is for ·
How it works · Why it is different · What you get · See it working · What we
found in Dubai · Want to see what yours would look like?*

It positions Qevik as a digital-products agency — "Websites, apps, SaaS
interfaces, e-commerce, games". The direction asks it to communicate a business
growth platform. That is a repositioning, and it is a **product decision**
(what Qevik sells and to whom), not a design task.

## 3. Integrations: 17 declared, 0 connected

`integrations/registry.py` declares 17. Production has **zero** connections and
no business has ever connected anything. An integrations page built now would
list 17 things none of which any customer has used. The direction's own rule —
never imply an integration exists because it is listed — makes the honest
version of this page mostly "not yet available", which is a real design problem
worth solving deliberately rather than by accident.

## 4. The app: correct state model, engineering aesthetic

`app.qevik.ai` is served from `/srv/qevik-control/`. It has 18 nav items, a
dark console palette, and — verified live today — a working human-decision
inbox with typed responses and safety refusals.

The information architecture is sound and the API contracts are real. What it
lacks against §7–§10 is: dates on actions, filters and sorting, explicit
loading/empty/stale/failed states, and a visual system that is not a terminal.
`docs/DESIGN_SYSTEM.md` exists (238 lines) and is the reference to work from.

## 5. Ordering, by evidence rather than by the list

1. **Fix the routing.** One config change, unblocks 60 KB of existing content,
   an Arabic site and seven case studies. Deterministic. No design decision.
2. **A real 404.** Currently every wrong URL is a 200.
3. Then the IA and visual work of §1, which now has somewhere to live.
4. The app redesign (§7–§10) — independent of the site, can proceed in
   parallel.
5. Integrations, onboarding, chat, pricing — each blocked on a customer, a
   connector or a commercial decision. See
   `QEVIK_CUSTOMER_PLATFORM_RECONCILIATION.md`.

## 6. Product decisions this raises

**Positioning** — the site sells digital products; the direction describes a
growth platform. Which Qevik sells, and to whom, is the owner's call. Recorded
separately if the loop reaches it; it is not needed to fix the routing.

**Pricing** — no pricing decision exists. Building a pricing page requires one.
