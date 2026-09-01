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
