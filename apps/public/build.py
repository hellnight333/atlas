#!/usr/bin/env python3
"""Build the public qevik.ai site.

Five pages sharing one shell. Written as a builder rather than five hand-kept
HTML files because the parts that must not drift are exactly the parts a person
forgets: canonical URLs, OpenGraph tags, the operating-entity line in the footer,
and the sitemap. Here the sitemap is generated from the same PAGES list the nav
is, so a page cannot exist without being listed or be listed without existing.

Content rules this file enforces, because the site is a commercial claim:

- Qevik is a **brand operated by Asia Link Internet Content Provider LLC**, never
  presented as its own licensed company.
- The appointment form takes a **request**. Nothing books. Any wording that
  implies automated booking is refused by `check()` below.
- No testimonials, no client names, no awards, no invented statistics. The only
  numbers on the site come from the audit of twenty Dubai clinic websites, are
  reported in aggregate, and name nobody.

    build.py            # write to ./dist
    build.py --out DIR
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import copy_ar  # noqa: E402

HERE = Path(__file__).resolve().parent
SITE = "https://qevik.ai"
TODAY = date(2026, 8, 19).isoformat()

NAME = "Ayoub Soleimani"
PHONE_DISPLAY = "+971 50 102 9104"
PHONE_TEL = "+971501029104"
PHONE_WA = "971501029104"
ENTITY = "Asia Link Internet Content Provider LLC"
ADDRESS_1 = "Office 301, Al Othman Building"
ADDRESS_2 = "Deiram, Dubai, UAE"

SAMPLE = "https://sites.qevik.ai/sample/"
SAMPLE_AR = "https://sites.qevik.ai/sample/ar/"
SAMPLE_CARROT = "https://sites.qevik.ai/sample-carrot/"


#: The portfolio, with the sales facts §21 asks for kept beside each entry:
#: what it demonstrates, which interactions genuinely work, and what would need
#: a real integration. Written here rather than in a database because it is
#: copy — a person edits it when the sample changes.
SHOWCASE = {
    "pulse": {
        "slug": "sample-pulse", "name": "Pulse", "industry": "Fitness · web application",
        "shot": "sample-pulse-m.png",
        "concept": "A product interface with no marketing page at all — sidebar, dense stat row, "
                   "live chart, training log. It exists to answer one question: can you build "
                   "software, not just websites.",
        "design": "Dark, dense, mono for every number so columns align. No hero, no footer, no "
                  "sticky call bar. On a phone the sidebar becomes a bottom rail, the way an app does.",
        "real": ["Chart tabs switch the series, axis labels and legend",
                 "Responsive sidebar collapses to a mobile rail"],
        "needs": ["Accounts and sign-in", "Storing a workout", "Syncing from a device"],
        "pitch": "For anyone who says “we need an internal tool, not a website”.",
        "bilingual": False,
    },
    "nar": {
        "slug": "sample-nar", "name": "NAR", "industry": "Fine dining",
        "shot": "sample-nar-m.png",
        "concept": "An editorial restaurant page that opens full-bleed with no navigation "
                   "anywhere. The menu is a priced list, not a grid of cards.",
        "design": "Chromeless and dark, one enormous serif line, asymmetric splits that never "
                  "align, a horizontal snapping rail for the room. Imagery is CSS, not "
                  "photographs of a restaurant that does not exist.",
        "real": ["Table request form that states plainly it is not connected",
                 "Horizontal scroll rail with snap points"],
        "needs": ["A reservation provider", "Table availability"],
        "pitch": "For a restaurant whose current site looks like a takeaway menu.",
        "bilingual": False,
    },
    "apex": {
        "slug": "sample-apex", "name": "APEX Detailing", "industry": "Automotive",
        "shot": "sample-apex-m.png",
        "concept": "A four-step quote configurator that is the page rather than a form at the "
                   "bottom of one. Vehicle, services, plan, contact — priced live.",
        "design": "Dark technical, condensed uppercase, hard grid, numbered steps. Where NAR "
                  "wants you to slow down, this wants you finished in ninety seconds.",
        "real": ["Full configurator with running total", "Multi-select services",
                 "Plan discount recalculates", "Step navigation with validation"],
        "needs": ["Sending the quote", "Scheduling a slot", "Payment"],
        "pitch": "For any service business that currently says “call for a price”.",
        "bilingual": False,
    },
    "verdant": {
        "slug": "sample-verdant", "name": "Verdant", "industry": "Retail",
        "shot": "sample-verdant-m.png",
        "concept": "A storefront: filter rail, search, product grid and a basket that slides "
                   "over the page. No hero, no services section — a shop starts at the products.",
        "design": "Light, warm, roomy. Humanist sans throughout with no mono and no serif, "
                  "against Pulse's density and APEX's hard grid.",
        "real": ["Filter by light, care and size", "Live text search",
                 "Add to basket, remove, running subtotal", "Cart drawer with scrim and Escape"],
        "needs": ["Payment", "Stock levels", "Delivery pricing"],
        "pitch": "For a shop selling through Instagram DMs and a spreadsheet.",
        "bilingual": False,
    },
    "homefix": {
        "slug": "sample-homefix", "name": "HomeFix Dubai", "industry": "Home services",
        "shot": "sample-homefix-m.png",
        "concept": "Someone's AC died at 2pm in August. Everything assumes a person on a phone "
                   "who wants a number and a human — the estimator is the first thing under the "
                   "headline and the whole page is three screens deep.",
        "design": "Bright, blunt, enormous touch targets, an urgent strip above everything and "
                  "two full-width thumb buttons pinned to the bottom. Nothing is subtle.",
        "real": ["Estimator: job × units × urgency produces a range",
                 "Counter and urgency multiplier recalculate live",
                 "Labels adapt — “units” becomes “points” for electrical work"],
        "needs": ["Dispatching a technician", "Arrival windows", "Payment"],
        "pitch": "The category our own market scan ranked first — 82% reachable on WhatsApp.",
        "bilingual": False,
    },
    "ledgerloop": {
        "slug": "sample-ledgerloop", "name": "LedgerLoop", "industry": "B2B SaaS",
        "shot": "sample-ledgerloop-m.png",
        "concept": "A B2B marketing site with the product embedded in the hero — the inverse of "
                   "Pulse, so the pair demonstrates both halves of the same capability.",
        "design": "Light, tight, low-chroma. Full link bar with the CTA inside the header, "
                  "alternating feature rows rather than a card grid, three-column pricing with "
                  "a billing toggle, and a comparison matrix.",
        "real": ["Product preview tabs switch views", "Queue filters by document type",
                 "Pricing toggle recalculates all three tiers"],
        "needs": ["Everything behind it — this is a concept, not a running product"],
        "pitch": "For when the conversation is “we need a product, not a brochure”.",
        "bilingual": False,
    },
    "meridian": {
        "slug": "sample-meridian", "name": "Meridian", "industry": "Real estate",
        "shot": "sample-meridian-m.png",
        "concept": "Search-first. Criteria on the left, results on the right, detail sliding in "
                   "over both — a two-pane application rather than a page with listings on it.",
        "design": "Night palette with gold, serif wordmark and prices, sans for everything "
                  "operational. Verdant is also a filtered grid, so this one narrows toward a "
                  "single decision instead of accumulating into a basket.",
        "real": ["Filter by deal, area, bedrooms and a price slider", "Sorting",
                 "Save to a list with a live count", "Full detail overlay with viewing request"],
        "needs": ["Real listings", "Map integration", "Agent routing"],
        "pitch": "For an agency whose site is a WordPress theme with a contact form.",
        "bilingual": False,
    },
    "carrot": {
        "slug": "sample-carrot", "name": "Carrot Dash", "industry": "Game",
        "shot": "sample-carrot-m.png",
        "concept": "A one-button browser game. Hop the fences, eat the carrots. Genuinely "
                   "playable — the physics, the rising difficulty and the score are real.",
        "design": "Almost nothing here resembles a website: no navigation, no sections, no "
                  "scrolling, no footer. One canvas filling the viewport and one button. "
                  "Everything is drawn — no sprite sheets, no audio files, no libraries, under 14kB.",
        "real": ["Full gameplay: variable-height jumps, collision, rising speed",
                 "Score and a best score kept between visits",
                 "Keyboard, mouse and touch all drive the same one button"],
        "needs": ["Leaderboards", "Accounts", "App-store packaging — not implemented"],
        "pitch": "Proves the studio makes things you play, not only pages you read.",
        "bilingual": False,
    },
    "foundry": {
        "slug": "sample-foundry", "name": "Foundry", "industry": "AI · automation",
        "shot": "sample-foundry-m.png",
        "concept": "An operator console for the build pipeline Qevik actually runs: objective, "
                   "research, plan, generate, test, repair, deploy, verify — including the "
                   "approval gate and a failed test that repairs itself.",
        "design": "A run view rather than a dashboard of aggregates: a vertical timeline of "
                  "steps on the left, the selected step's evidence on the right, a streaming log. "
                  "Terminal-adjacent without pretending to be a terminal.",
        "real": ["The whole run plays through with per-step states",
                 "Every step is inspectable — artefacts, counts, log lines",
                 "Shows the approval pause and the self-repair, because both are real"],
        "needs": ["This page simulates one run; it does not execute the pipeline"],
        "pitch": "Shows the machinery behind everything else in the portfolio.",
        "bilingual": False,
    },
    "atelier": {
        "slug": "sample-atelier", "name": "ATELIER", "industry": "Luxury salon",
        "shot": "sample-atelier-m.png",
        "concept": "A visit builder that accumulates time rather than price — because someone is "
                   "deciding whether a colour and a facial fit into the same afternoon.",
        "design": "Pale, warm and unhurried against NAR's dark drama. Centred wordmark over a "
                  "rule, type sitting low in the opening, treatments as a quiet expanding list "
                  "with no cards anywhere.",
        "real": ["Expanding treatment list", "Add or remove from a visit",
                 "Running total in hours and minutes, not money"],
        "needs": ["Real availability", "Stylist rosters", "Booking"],
        "pitch": "For a salon whose current site is a template with stock photography.",
        "bilingual": False,
    },
    "clinic": {
        "slug": "sample", "name": "Sample Dental Clinic", "industry": "Health · bilingual",
        "shot": "sample_mobile_en.png",
        "concept": "The bilingual local-business product: English and Arabic as separate indexed "
                   "pages, verified opening hours, tap-to-call, map, appointment request.",
        "design": "Generated from a template rather than hand-built, and honest about it. This "
                  "is what a clinic, salon or café receives.",
        "real": ["Full Arabic page with RTL layout, Arabic day names and ص/م markers",
                 "Tap-to-call, WhatsApp where the number can receive it, map link",
                 "hreflang, per-language canonicals, sitemap covering both"],
        "needs": ["Appointment booking — the form takes a request only"],
        "pitch": "The everyday product. Bilingual, local-SEO complete, live in a day.",
        "bilingual": True,
    },
}

#: Qevik's own sample sites. Not clients — every one is flagged as a sample on
#: the page itself and carries our number, so the buttons genuinely work. The
#: twenty clinic demos are deliberately absent: they were built unsolicited from
#: public listings, none of those businesses are customers, and showing them as
#: portfolio would invent a relationship that does not exist.
#: path -> (nav label, <title>, meta description)
PAGES: dict[str, tuple[str, str, str]] = {
    "/": (
        "Home",
        "Qevik — digital products built around your business",
        "Websites, web applications, SaaS interfaces, e-commerce, games and "
        "AI-assisted automation — designed, built, tested in a real browser and "
        "deployed. Dubai, English and Arabic.",
    ),
    "/services/": (
        "Services",
        "Services — Qevik",
        "Business websites, bilingual English and Arabic pages, local SEO, "
        "conversion basics that actually get used, and managed hosting with "
        "HTTPS and ongoing changes.",
    ),
    "/work/": (
        "Work",
        "Work — Qevik",
        "A live sample site you can open and use, in English and Arabic, plus "
        "what we found auditing twenty Dubai dental clinic websites.",
    ),
    "/about/": (
        "About",
        "About — Qevik",
        "Qevik is the website product operated by Asia Link Internet Content "
        "Provider LLC in Dubai. One person builds your site; you deal with him "
        "directly.",
    ),
    # The work sub-pages live in PAGES so each gets a title, description,
    # canonical and sitemap entry from the same source as the top-level five.
    **{
        f"/work/{key}/": (
            data["name"],
            f"{data['name']} — {data['industry']} — Qevik",
            data["concept"][:200],
        )
        for key, data in SHOWCASE.items()
    },
    "/contact/": (
        "Contact",
        "Contact — Qevik",
        "Talk to Ayoub Soleimani directly on WhatsApp or by phone about a "
        "website for your Dubai business.",
    ),
}

#: The five primary routes exist in both languages. Arabic lives under /ar/ and
#: each page is canonical for itself — pointing the Arabic canonical at English
#: declares it a duplicate, and duplicates are dropped from the index, removing
#: the Arabic page from exactly the searches it exists to win.
PRIMARY = ("/", "/services/", "/work/", "/about/", "/contact/")

for _path in PRIMARY:
    _ar = "/ar/" if _path == "/" else "/ar" + _path
    PAGES[_ar] = (copy_ar.NAV[_path], *copy_ar.META[_path])


def counterpart(path: str) -> str:
    """The same page in the other language."""
    if path.startswith("/ar/"):
        rest = path[3:]
        return rest if rest else "/"
    return "/ar/" if path == "/" else "/ar" + path


def is_arabic(path: str) -> bool:
    return path.startswith("/ar/") or path == "/ar"


#: Wording that would claim something Qevik does not do. Checked against every
#: built page, so a marketing sentence cannot quietly overstate the product.
FORBIDDEN = (
    (r"\bbook (?:your |an )?appointment(?!\s+request)", "implies automated booking"),
    (r"\bbooking system\b", "there is no booking backend"),
    (r"\bautomatic(?:ally)? book", "nothing books automatically"),
    (r"\bguarantee", "no outcome is guaranteed"),
    (r"#1 on google", "no ranking is promised"),
    (r"\bqevik\s+(?:llc|fz-?llc|fze|dmcc|fzco)\b", "Qevik is not a licensed entity"),
    (r"\bqevik is (?:a|an) (?:licen[cs]ed|registered)", "Qevik is not a licensed entity"),
    (r"\btrusted by\b", "no customers to cite"),
    (r"\bour clients\b", "no clients yet"),
    (r"\btestimonial", "no testimonials"),
    (r"\baward[- ]winning\b", "no awards"),
)



#: Arabic labels for the portfolio. Only what appears on the Arabic Work page —
#: the detail pages stay English, and the cards there link straight to the live
#: product rather than to a page the visitor cannot read.
AR_LABELS = {
    "carrot": ("Carrot Dash", "لعبة"),
    "foundry": ("Foundry", "ذكاء اصطناعي وأتمتة"),
    "atelier": ("ATELIER", "صالون فاخر"),
    "pulse": ("Pulse", "تطبيق ويب · لياقة"),
    "nar": ("NAR", "مطعم"),
    "apex": ("APEX Detailing", "سيارات"),
    "verdant": ("Verdant", "متجر إلكتروني"),
    "homefix": ("HomeFix Dubai", "خدمات منزلية"),
    "ledgerloop": ("LedgerLoop", "منتج SaaS"),
    "meridian": ("Meridian", "عقارات"),
    "clinic": ("Sample Dental Clinic", "رعاية صحية · ثنائي اللغة"),
}

#: The homepage showcase. Each entry is a product *type* rather than an
#: industry, because the point being proved is range of product, not range of
#: sector — six restaurants would demonstrate nothing.
SHOWCASE_TABS = (
    ("website", "Website", "موقع", "nar",
     "An editorial restaurant that opens full-bleed with no navigation at all.",
     "مطعم يفتح بملء الشاشة بلا أي قائمة تنقّل.",
     "Scroll the menu, open the room, request a table.",
     "تصفّح القائمة، شاهد المكان، اطلب طاولة."),
    ("app", "Web app", "تطبيق ويب", "pulse",
     "A product interface: sidebar, live charts, training log. No marketing page.",
     "واجهة منتج: قائمة جانبية ورسوم بيانية حيّة وسجلّ تمارين. بلا صفحة تسويقية.",
     "Switch the chart between volume and sessions.",
     "بدّل الرسم البياني بين الحِمل وعدد الجلسات."),
    ("saas", "SaaS", "منتج SaaS", "ledgerloop",
     "A B2B marketing site with the product embedded in the hero.",
     "موقع تسويقي لمنتج B2B مع واجهة المنتج داخل الافتتاحية.",
     "Filter the approvals queue, switch the billing period.",
     "صفِّ قائمة الموافقات، وبدّل دورة الفوترة."),
    ("commerce", "E-commerce", "متجر إلكتروني", "verdant",
     "A storefront: filter rail, search, product grid, basket drawer.",
     "متجر: فلاتر وبحث وشبكة منتجات وسلّة تنزلق فوق الصفحة.",
     "Filter by light and care, then add to the basket.",
     "صفِّ حسب الإضاءة والعناية، ثم أضف إلى السلّة."),
    ("interactive", "Configurator", "حاسبة تفاعلية", "apex",
     "A four-step quote configurator that prices as you tap.",
     "حاسبة عرض سعر من أربع خطوات تتغيّر أمامك.",
     "Pick a vehicle and services — the total moves.",
     "اختر سيارة وخدمات — يتغيّر المجموع فوراً."),
    ("ai", "AI & automation", "ذكاء اصطناعي", "foundry",
     "The build pipeline as an operator console, including the approval pause.",
     "مسار البناء كوحدة تحكّم، بما فيها وقفة الموافقة.",
     "Press Run and watch it research, plan, fail a test and repair itself.",
     "اضغط تشغيل وراقبه يبحث ويخطّط ويفشل في اختبار ثم يصلح نفسه."),
    ("game", "Game", "لعبة", "carrot",
     "A one-button browser game with real physics and a score.",
     "لعبة متصفّح بزرّ واحد، بفيزياء حقيقية ونقاط.",
     "Press space or tap to jump. Hold to jump higher.",
     "اضغط المسافة أو المس للقفز. استمر بالضغط لقفزة أعلى."),
)


def showcase_block(lang: str = "en") -> str:
    """A real tab set: the image, the words and the call to action all change.

    Deliberately not an iframe of each product. `sites.qevik.ai` sends
    `X-Frame-Options: DENY`, and relaxing that for a cosmetic embed would trade
    a real protection for a nested scroll area that behaves badly on a phone.
    The tab switch is genuine state, and every panel links straight to the live
    thing.
    """
    arabic = lang == "ar"
    tabs, panels = "", ""
    for index, (key, en_label, ar_label, sample, en_desc, ar_desc, en_do, ar_do) in enumerate(
        SHOWCASE_TABS
    ):
        d = SHOWCASE[sample]
        first = index == 0
        tabs += (
            f'<button role="tab" id="tab-{key}" aria-controls="panel-{key}" '
            f'aria-selected="{"true" if first else "false"}" data-tab="{key}">'
            f'{ar_label if arabic else en_label}</button>'
        )
        panels += f"""
      <div class="sc-panel" role="tabpanel" id="panel-{key}" aria-labelledby="tab-{key}"{"" if first else " hidden"}>
        <figure class="sc-shot">
          <img src="/assets/{fingerprinted(d['shot'])}" width="390" height="844"
               alt="{d['name']}" loading="{"eager" if first else "lazy"}">
        </figure>
        <div class="sc-copy">
          <p class="sc-name">{d['name']}</p>
          <p class="sc-desc">{ar_desc if arabic else en_desc}</p>
          <p class="sc-try"><strong>{"جرّب:" if arabic else "Try:"}</strong>
             {ar_do if arabic else en_do}</p>
          <a class="btn primary" href="https://sites.qevik.ai/{d['slug']}/" rel="noopener">
            {"افتح المنتج الحيّ" if arabic else "Open the live product"}</a>
        </div>
      </div>"""

    return f"""
    <div class="switcher">
      <div class="sc-tabs" role="tablist"
           aria-label="{"أنواع المنتجات" if arabic else "Product types"}">{tabs}</div>
      {panels}
    </div>
    <script>
    // Real state, not an animation: the picture, the words, the suggested
    // interaction and the link all change together.
    document.querySelectorAll('.sc-tabs button').forEach(function (tab) {{
      tab.addEventListener('click', function () {{
        document.querySelectorAll('.sc-tabs button').forEach(function (t) {{
          t.setAttribute('aria-selected', String(t === tab));
        }});
        document.querySelectorAll('.sc-panel').forEach(function (panel) {{
          panel.hidden = panel.id !== 'panel-' + tab.dataset.tab;
        }});
      }});
    }});
    </script>"""


def sample_cards(lang: str = "en") -> str:
    """The portfolio grid. English links to a detail page; Arabic to the product."""
    arabic = lang == "ar"
    cards = ""
    for key, d in SHOWCASE.items():
        name, industry = AR_LABELS.get(key, (d["name"], d["industry"])) if arabic \
            else (d["name"], d["industry"])
        live = f"https://sites.qevik.ai/{d['slug']}/"
        target = live if arabic else f"/work/{key}/"
        links = (
            f'<a href="{live}" rel="noopener">{copy_ar.UI["open"]}</a>'
            if arabic
            else f'<a href="/work/{key}/">Details</a> · <a href="{live}" rel="noopener">Open</a>'
        )
        if d["bilingual"]:
            links += f' · <a href="{live}ar/" rel="noopener">العربية</a>'
        cards += f"""
      <article class="sample">
        <a href="{target}"{' rel="noopener"' if arabic else ''}>
          <img src="/assets/{fingerprinted(d['shot'])}" width="390" height="844"
               alt="{name} — {industry}." loading="lazy">
        </a>
        <div class="sample-body">
          <p class="sample-kind">{name}</p>
          <p class="sample-detail">{industry}</p>
          <p class="sample-links">{links}</p>
        </div>
      </article>"""
    return cards


#: Filled during the build: "site.css" -> "site.9f2a1c.css". Cloudflare caches
#: /assets/* for a day, so an edited stylesheet kept serving the old bytes even
#: though the origin had the new ones. Fingerprinting makes a changed file a
#: different URL, which no cache can serve stale and which needs no purge.
ASSETS: dict[str, str] = {}


def fingerprinted(name: str) -> str:
    return ASSETS.get(name, name)


def shell(path: str, body: str, *, og_type: str = "website", extra_head: str = "") -> str:
    label, title, description = PAGES[path]
    canonical = f"{SITE}{path}"
    arabic = is_arabic(path)
    lang, direction = ("ar", "rtl") if arabic else ("en", "ltr")
    other = counterpart(path)
    ui = copy_ar.UI if arabic else {
        "skip": "Skip to content", "operated_by": "Operated by",
        "talk": "Talk to a person", "english": "English", "arabic": "العربية",
        "brand_note": f"Qevik is a product and brand of {ENTITY}. It is not a separately "
                      "licensed company.",
        "legal": f"{ENTITY}. Qevik is its trading brand.",
        "tagline": "Digital products for Dubai businesses. Built, tested and hosted.",
    }

    # Only the five primary routes exist in Arabic. A work detail page has no
    # Arabic counterpart, so it must not advertise one — an hreflang pointing at
    # a 404 is worse than none, and a language switch that breaks is the first
    # thing an Arabic-speaking visitor tests.
    bilingual = path in PRIMARY or arabic
    if bilingual:
        en_href = f"{SITE}{other if arabic else path}"
        ar_href = f"{SITE}{path if arabic else other}"
        alternates = (
            f'<link rel="alternate" hreflang="en" href="{en_href}">\n'
            f'<link rel="alternate" hreflang="ar" href="{ar_href}">\n'
            f'<link rel="alternate" hreflang="x-default" href="{en_href}">'
        )
        switch = (
            f'<a class="lang" href="{other}" lang="{"en" if arabic else "ar"}" '
            f'hreflang="{"en" if arabic else "ar"}">'
            f'{ui["english"] if arabic else ui["arabic"]}</a>'
        )
    else:
        alternates = ""
        switch = ""

    nav_paths = PRIMARY if not arabic else tuple(counterpart(p) for p in PRIMARY)
    links = []
    for item in nav_paths:
        here = item == path or (item.rstrip("/").endswith("/work") and "/work/" in path)
        mark = ' class="here" aria-current="page"' if here else ""
        links.append(f'<a href="{item}"{mark}>{PAGES[item][0]}</a>')
    nav = "".join(links)

    year = TODAY[:4]

    return f"""<!doctype html>
<html lang="{lang}" dir="{direction}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{description}">
<link rel="canonical" href="{canonical}">
{alternates}
<meta property="og:type" content="{og_type}">
<meta property="og:url" content="{canonical}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:site_name" content="Qevik">
<meta property="og:locale" content="{"ar_AE" if arabic else "en_AE"}">
<meta property="og:locale:alternate" content="{"en_AE" if arabic else "ar_AE"}">
<meta property="og:image" content="{SITE}/assets/{fingerprinted("og.png")}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{description}">
<meta name="twitter:image" content="{SITE}/assets/{fingerprinted("og.png")}">
<meta name="theme-color" content="#0d6e6b">
<link rel="icon" href="/assets/{fingerprinted("favicon.svg")}" type="image/svg+xml">
<link rel="apple-touch-icon" href="/assets/{fingerprinted("icon-180.png")}">
<link rel="stylesheet" href="/assets/{fingerprinted("site.css")}">
{extra_head}
</head>
<body>
<a class="skip" href="#main">{ui["skip"]}</a>
<header class="site">
  <div class="bar">
    <a class="brand" href="{"/ar/" if arabic else "/"}"><span class="mark">Q</span><span>Qevik</span></a>
    <nav aria-label="Primary">{nav}</nav>
    {switch}
    <a class="call" href="tel:{PHONE_TEL}" dir="ltr">{PHONE_DISPLAY}</a>
  </div>
</header>
<main id="main">
{body}
</main>
<footer class="site">
  <div class="cols">
    <div>
      <p class="fbrand">Qevik</p>
      <p>{ui["tagline"]}</p>
    </div>
    <div>
      <p class="flabel">{ui["operated_by"]}</p>
      <p>{ENTITY}<br>{ADDRESS_1}<br>{ADDRESS_2}</p>
      <p class="fnote">{ui["brand_note"]}</p>
    </div>
    <div>
      <p class="flabel">{ui["talk"]}</p>
      <p><a href="tel:{PHONE_TEL}" dir="ltr">{PHONE_DISPLAY}</a><br>
         <a href="https://wa.me/{PHONE_WA}" rel="noopener">WhatsApp</a></p>
      <p>{NAME}</p>
    </div>
  </div>
  <p class="legal">&copy; {year} {ui["legal"]}</p>
</footer>
</body>
</html>
"""


def home() -> str:
    return f"""
<section class="hero">
  <div class="wrap hero-grid">
   <div>
    <p class="eyebrow">Dubai · Websites · Apps · SaaS · Games</p>
    <h1>Digital products built around your business.</h1>
    <p class="lead">Websites, web applications, SaaS interfaces, e-commerce, games and AI-assisted
      automation — designed around what the product actually has to do, then built, tested in a
      real browser and deployed. Every example below is live; open one and use it.</p>
    <div class="cta-row">
      <a class="btn primary" href="https://wa.me/{PHONE_WA}" rel="noopener">Start a project</a>
      <a class="btn" href="/work/">Explore our work</a>
      <a class="btn ghost" href="{SAMPLE_CARROT}" rel="noopener">Play the game we built</a>
    </div>
    <p class="micro">No obligation. The example is a real, live page — open it and press the buttons.</p>
   </div>
   <figure class="hero-shot">
     <img src="/assets/{fingerprinted("sample_mobile_en.png")}" width="390" height="844"
          alt="A generated clinic site on a phone, with a call button, an appointment request button, WhatsApp and directions." fetchpriority="high">
     <figcaption>A generated site, on a phone</figcaption>
   </figure>
  </div>
</section>

<section class="band">
  <div class="wrap">
    <h2>What Qevik is</h2>
    <p class="stand">A digital product studio in Dubai. You describe what you need in plain
      language. The work is researched, planned, built, tested and deployed — then the live
      address is opened in a real browser and checked, and a person reviews it before anyone
      else sees it.</p>
    <p class="stand">The output is not always a website. It might be a dashboard, a storefront,
      a configurator, a mobile-first application or a game. What it is depends on what the
      business actually needs.</p>
    <div class="grid three">
      <div class="card">
        <h3>Websites</h3>
        <p>Business sites, local and multilingual, built from your own verified details.
          Nothing invented — no staff you do not employ, no reviews nobody wrote.</p>
      </div>
      <div class="card">
        <h3>Web applications</h3>
        <p>Dashboards, internal tools, customer portals and request systems. Interfaces people
          use rather than pages they read.</p>
      </div>
      <div class="card">
        <h3>SaaS products</h3>
        <p>Product interfaces with the marketing site around them — pricing, features and the
          application itself.</p>
      </div>
      <div class="card">
        <h3>E-commerce</h3>
        <p>Catalogues, search, filtering and a basket. Payment through a real provider when you
          choose one.</p>
      </div>
      <div class="card">
        <h3>Games &amp; interactive</h3>
        <p>Playable browser games and configurators. Things that respond, not screenshots of
          things that would.</p>
      </div>
      <div class="card">
        <h3>AI &amp; automation</h3>
        <p>Research, planning, generation, testing and verification wired into a pipeline —
          the machinery that builds everything above.</p>
      </div>
    </div>
  </div>
</section>

<section class="band alt">
  <div class="wrap">
    <h2>Who it is for</h2>
    <p class="stand">The parts every local business needs are the same — who you are, what you
      offer, where you are, when you are open, and how to reach you. What changes is the shape of
      the middle. Qevik composes that per industry rather than forcing one template on everyone.</p>
    <div class="industries">
      <div><h3>Food &amp; drink</h3><p>Restaurants, cafés, roasteries, bakeries — menus by
        category, prices, table requests.</p></div>
      <div><h3>Health &amp; beauty</h3><p>Clinics, salons, spas, gyms — treatments with
        durations, opening hours, appointment requests.</p></div>
      <div><h3>Home &amp; automotive</h3><p>Cleaning, detailing, repairs, maintenance — service
        lists, service areas, FAQ, quote requests.</p></div>
      <div><h3>Professional services</h3><p>Real estate, accounting, consulting, legal — service
        pages, FAQ, call-back requests.</p></div>
      <div><h3>Retail &amp; local trade</h3><p>Shops, showrooms, workshops — what you stock,
        where you are, and a reason to visit.</p></div>
      <div><h3>Internal tools</h3><p>Dashboards and web applications — see the fitness app in
        the samples. Scoped individually, not generated.</p></div>
    </div>
    <p class="micro">Not on the list does not mean not possible. The template is composed from
      parts, so a new kind of business is a new arrangement rather than a new product.</p>
  </div>
</section>

<section class="band">
  <div class="wrap">
    <h2>How it works</h2>
    <p class="stand">Seven steps. Each one leaves a record, so if something goes wrong it is
      possible to say exactly where.</p>
    <ol class="steps">
      <li><span class="n">1</span><div><h3>You say what you want</h3>
        <p>In plain language — “a website for my dental clinic in Karama, in Arabic as well”.
          No forms full of technical choices.</p></div></li>
      <li><span class="n">2</span><div><h3>Research</h3>
        <p>Your public business listing and existing website are read, so the site starts from facts
          about your business rather than a blank template.</p></div></li>
      <li><span class="n">3</span><div><h3>Planning</h3>
        <p>A language model decides the steps and their order, and the plan is validated before
          anything runs. Where no model is available it falls back to a fixed plan and records that
          it did.</p></div></li>
      <li><span class="n">4</span><div><h3>Generation</h3>
        <p>The pages are written — English and Arabic, with your contact details, services, hours
          and map.</p></div></li>
      <li><span class="n">5</span><div><h3>Testing</h3>
        <p>The site is tested before it goes anywhere. <strong>If a test fails, the system repairs
          the site and runs the tests again</strong> rather than shipping something broken.</p></div></li>
      <li><span class="n">6</span><div><h3>Deployment</h3>
        <p>Published to a real address over HTTPS. Every version is kept, so going back to the
          previous one is immediate.</p></div></li>
      <li><span class="n">7</span><div><h3>Verification</h3>
        <p>A browser opens the live URL — the public one, not a copy — and checks what a visitor
          actually receives.</p></div></li>
    </ol>
  </div>
</section>

<section class="band alt">
  <div class="wrap">
    <h2>Why it is different</h2>
    <div class="grid two">
      <div class="card">
        <h3>It checks its own work</h3>
        <p>Most sites are “finished” when someone stops editing. Here the last step is a browser
          opening the public address and confirming the page loads, the heading is right, and the
          buttons point where they should.</p>
      </div>
      <div class="card">
        <h3>It repairs its own failures</h3>
        <p>When a build fails its tests, the system regenerates and re-runs them. Nothing broken
          reaches your address.</p>
      </div>
      <div class="card">
        <h3>Nothing goes out without a person</h3>
        <p>Publishing, and anything that reaches someone outside the system, requires explicit
          human approval tied to that exact action. The software cannot approve itself.</p>
      </div>
      <div class="card">
        <h3>Long jobs survive</h3>
        <p>Work runs detached on the server. A dropped connection does not kill a build, and the
          result is still there when the link comes back.</p>
      </div>
    </div>
  </div>
</section>

<section class="band">
  <div class="wrap">
    <h2>What you get</h2>
    <div class="grid three tight">
      <div class="feat"><h3>English &amp; Arabic</h3><p>Separate pages, real right-to-left layout,
        cross-linked so search engines index both.</p></div>
      <div class="feat"><h3>Local SEO</h3><p>Your name, address and phone stated consistently,
        with dentist/business structured data and your verified opening hours.</p></div>
      <div class="feat"><h3>Google Maps</h3><p>A directions link that opens the map app on a
        phone.</p></div>
      <div class="feat"><h3>Click to call</h3><p>A tap-to-dial button, fixed to the bottom of the
        screen on mobile where a thumb reaches it.</p></div>
      <div class="feat"><h3>WhatsApp</h3><p>Where your number can receive it. A WhatsApp link on a
        landline is a dead end, so we only add it to a mobile that works.</p></div>
      <div class="feat"><h3>Appointment requests</h3><p>A form that sends you an enquiry.
        <strong>It does not book</strong> — see the note below.</p></div>
      <div class="feat"><h3>Hosting &amp; HTTPS</h3><p>Hosted and served over HTTPS, with the
        certificate renewed automatically.</p></div>
      <div class="feat"><h3>Managed changes</h3><p>New hours, a new service, a changed number —
        message and it gets done. You are not editing anything.</p></div>
      <div class="feat"><h3>Fast on a phone</h3><p>No heavy frameworks, no stock photography, no
        sliders. It loads.</p></div>
    </div>
    <div class="note">
      <p><strong>About appointments, plainly.</strong> The appointment section is a
        <em>request</em> form and an integration point. It does not run a booking calendar, does not
        confirm a slot, and does not tell a patient they have an appointment. Connecting real online
        booking means choosing a provider and setting it up — a separate conversation, not something
        quietly implied here.</p>
    </div>
  </div>
</section>

<section class="band">
  <div class="wrap">
    <h2>See it working</h2>
    <p class="stand">Seven kinds of product, each a live thing you can open and use. Switch
      between them — the example changes, not just the colour.</p>
    {showcase_block("en")}
  </div>
</section>

<section class="band alt">
  <div class="wrap">
    <h2>What we found in Dubai</h2>
    <p class="stand">Before building anything we audited the live websites of twenty dental clinics
      in Dubai, by loading each homepage in a browser. These are the aggregate results. No clinic is
      named, and none of them are customers.</p>
    <div class="stats">
      <div><b>12<span>/20</span></b><small>had no Arabic version</small></div>
      <div><b>6<span>/20</span></b><small>had no way to request an appointment online</small></div>
      <div><b>4<span>/20</span></b><small>were served without HTTPS</small></div>
      <div><b>4<span>/20</span></b><small>had no structured data for local search</small></div>
      <div><b>4<span>/20</span></b><small>published a number that can receive WhatsApp</small></div>
      <div><b>1<span>/20</span></b><small>did not finish loading within 30 seconds</small></div>
    </div>
    <p class="micro">Measured 19 August 2026 by loading each clinic's homepage once. A single fetch
      from one network — enough to be worth knowing, not enough to be a verdict.</p>
  </div>
</section>

<section class="closing">
  <div class="wrap">
    <h2>Want to see what yours would look like?</h2>
    <p class="lead">Send a message with your clinic or business name. You get a link to a working
      example built from your own public details — before any money is discussed.</p>
    <div class="cta-row">
      <a class="btn primary" href="https://wa.me/{PHONE_WA}" rel="noopener">Message on WhatsApp</a>
      <a class="btn" href="tel:{PHONE_TEL}">Call {PHONE_DISPLAY}</a>
    </div>
  </div>
</section>
"""


def services() -> str:
    return f"""
<section class="page-head">
  <div class="wrap">
    <p class="eyebrow">Services</p>
    <h1>What Qevik does</h1>
    <p class="lead">Five things, done properly, for small businesses in Dubai.</p>
  </div>
</section>

<section class="band">
  <div class="wrap">
    <article class="service">
      <h2>Business websites</h2>
      <p>A complete site built from your own details — what you do, where you are, when you are
        open, and how to reach you. No template to fill in, no page builder to learn.</p>
      <ul class="ticks">
        <li>Written from your public business listing, so the facts start correct</li>
        <li>Services, opening hours, address and map</li>
        <li>Tested and browser-verified before it goes live</li>
        <li>Every version kept, so reverting is immediate</li>
      </ul>
    </article>

    <article class="service">
      <h2>Bilingual websites — English and Arabic</h2>
      <p>Not a translate widget. Two real pages, each at its own address, each written out
        properly, joined so a search engine knows they are the same business.</p>
      <ul class="ticks">
        <li>Correct right-to-left layout, Arabic day names, Arabic AM/PM markers</li>
        <li>Each language page is canonical for itself, so neither is treated as a duplicate</li>
        <li>Digits, phone numbers and your address stay exactly as they are</li>
        <li>Where we do not have a verified Arabic form of something, it is left out rather than invented</li>
      </ul>
    </article>

    <article class="service">
      <h2>Local SEO</h2>
      <p>The part that decides whether someone searching “dentist near me” finds you at all.</p>
      <ul class="ticks">
        <li>Consistent name, address and phone across the page and the structured data</li>
        <li>Dentist / local-business schema, with your verified opening hours</li>
        <li>Page titles and descriptions written per page, not duplicated</li>
        <li>robots.txt and a sitemap listing both language versions</li>
        <li>Area named in the English heading, because that is what people type</li>
      </ul>
    </article>

    <article class="service">
      <h2>Conversion basics</h2>
      <p>Most clinic sites lose enquiries at the last step. These are the things that actually get
        used on a phone.</p>
      <ul class="ticks">
        <li>Tap-to-call, fixed to the bottom of the screen where a thumb reaches</li>
        <li>Directions that open the map app</li>
        <li>WhatsApp — only where your number can receive one</li>
        <li>An appointment <strong>request</strong> form (see the note below)</li>
      </ul>
      <div class="note small">
        <p><strong>Appointments:</strong> the form takes a request and is an integration point for a
          real booking provider later. It does not book, confirm or hold a slot, and it never tells a
          patient they have an appointment.</p>
      </div>
    </article>

    <article class="service">
      <h2>Managed hosting and maintenance</h2>
      <p>The site is hosted, served over HTTPS, and kept current. You do not log into anything.</p>
      <ul class="ticks">
        <li>HTTPS with certificates renewed automatically</li>
        <li>Changes by message — new hours, a new service, a changed number</li>
        <li>Versioned deployments, so a change can be undone immediately</li>
        <li>Daily backups of the underlying data</li>
      </ul>
    </article>
  </div>
</section>

<section class="closing">
  <div class="wrap">
    <h2>Not sure which of these you need?</h2>
    <p class="lead">Send your business name. You get a working example first, then we talk.</p>
    <div class="cta-row">
      <a class="btn primary" href="https://wa.me/{PHONE_WA}" rel="noopener">Message on WhatsApp</a>
      <a class="btn" href="/contact/">Other ways to reach us</a>
    </div>
  </div>
</section>
"""


def work() -> str:
    return f"""
<section class="page-head">
  <div class="wrap">
    <p class="eyebrow">Work</p>
    <h1>{len(SHOWCASE)} things we built</h1>
    <p class="lead">Not mockups and not one template reskinned. Play the game, build a quote,
      filter the shop, watch a build run. Each behaves exactly as a real product would, because
      it is one.</p>
  </div>
</section>

<section class="band">
  <div class="wrap">
    <h2>{len(SHOWCASE)} builds, {len(SHOWCASE)} different problems</h2>
    <p class="stand">Not one template in {len(SHOWCASE)} colours. A restaurant that opens
      full-bleed with no navigation at all. A quote configurator that prices as you tap. A shop
      with filters and a basket. A fitness application with a sidebar and live charts. A playable
      game. Each is a different structure because each product needs a different one.</p>
    <p class="stand">A structural check compares every pair on navigation, hero, section order,
      type, layout devices, call-to-action placement, footer and interaction model, and refuses any
      two that are the same page in different colours.</p>
    <div class="samples">{sample_cards()}</div>
    <p class="micro">All {len(SHOWCASE)} are Qevik samples, not client work, and each says so on
      the page. The contact details are ours, so every button works — the call button dials Qevik.</p>
  </div>
</section>

<section class="band alt">
  <div class="wrap">
    <h2>The same site, both languages</h2>
    <p class="stand">Two separate pages rather than a switch that rewrites the text in place. The
      Arabic page is laid out right to left, with Arabic headings, Arabic day names and ص/م
      markers. The Arabic is written, not machine-translated at render time — where there is no
      verified Arabic form of something, it is left out rather than invented.</p>
    <div class="shots">
      <figure>
        <img src="/assets/{fingerprinted("sample-restaurant.png")}" width="390" height="844"
             alt="English restaurant sample on a phone: menu, table request, WhatsApp and directions." loading="lazy">
        <figcaption>English</figcaption>
      </figure>
      <figure>
        <img src="/assets/{fingerprinted("sample-restaurant-ar.png")}" width="390" height="844"
             alt="The same restaurant page in Arabic, laid out right to left." loading="lazy">
        <figcaption>العربية</figcaption>
      </figure>
    </div>
  </div>
</section>

<section class="band">
  <div class="wrap">
    <h2>What a generated site includes</h2>
    <div class="compare">
      <table>
        <caption>Every item below is present on the sample above and was verified by loading the live page.</caption>
        <thead><tr><th>Item</th><th>On the sample</th></tr></thead>
        <tbody>
          <tr><td>English page</td><td><span class="yes">Yes</span></td></tr>
          <tr><td>Arabic page, right-to-left</td><td><span class="yes">Yes</span></td></tr>
          <tr><td>Served over HTTPS</td><td><span class="yes">Yes</span></td></tr>
          <tr><td>Tap-to-call button</td><td><span class="yes">Yes</span></td></tr>
          <tr><td>Google Maps directions</td><td><span class="yes">Yes</span></td></tr>
          <tr><td>WhatsApp link</td><td><span class="yes">Yes — the number can receive one</span></td></tr>
          <tr><td>Opening hours, on the page and in structured data</td><td><span class="yes">Yes</span></td></tr>
          <tr><td>Local-business structured data</td><td><span class="yes">Yes</span></td></tr>
          <tr><td>robots.txt and sitemap covering both languages</td><td><span class="yes">Yes</span></td></tr>
          <tr><td>Appointment <em>request</em> form</td><td><span class="part">Yes — takes a request, does not book</span></td></tr>
          <tr><td>Online booking with a calendar</td><td><span class="no">No — not built</span></td></tr>
          <tr><td>Doctor profiles, insurers, patient reviews</td><td><span class="no">No — never invented</span></td></tr>
        </tbody>
      </table>
    </div>
    <p class="micro">The last two rows are on the list on purpose. A site that quietly implies
      online booking, or lists doctors who do not work at a clinic, causes a problem for a real
      patient — so those are stated as absent rather than left ambiguous.</p>
  </div>
</section>

<section class="band alt">
  <div class="wrap">
    <h2>Twenty Dubai clinic websites, audited</h2>
    <p class="stand">To find out whether this was worth building, we loaded the homepage of twenty
      dental clinic websites in Dubai and recorded what was there. Reported in aggregate — no clinic
      is named, and none of them are customers.</p>
    <div class="stats">
      <div><b>12<span>/20</span></b><small>no Arabic version</small></div>
      <div><b>6<span>/20</span></b><small>no online appointment request</small></div>
      <div><b>4<span>/20</span></b><small>no HTTPS</small></div>
      <div><b>4<span>/20</span></b><small>no local-business structured data</small></div>
      <div><b>3<span>/20</span></b><small>no opening hours on the homepage</small></div>
      <div><b>1<span>/20</span></b><small>did not load within 30 seconds</small></div>
    </div>
    <p class="micro">Measured 19 August 2026, one homepage fetch each. Features can exist on inner
      pages we did not read — an absence here means “not on the homepage we loaded”, which is not
      the same as “does not exist”.</p>
  </div>
</section>

<section class="closing">
  <div class="wrap">
    <h2>See yours before you decide</h2>
    <p class="lead">Send your business name and we will build a working example from your public
      details.</p>
    <div class="cta-row">
      <a class="btn primary" href="https://wa.me/{PHONE_WA}" rel="noopener">Message on WhatsApp</a>
      <a class="btn" href="tel:{PHONE_TEL}">Call {PHONE_DISPLAY}</a>
    </div>
  </div>
</section>
"""


def about() -> str:
    return f"""
<section class="page-head">
  <div class="wrap">
    <p class="eyebrow">About</p>
    <h1>Who you are dealing with</h1>
    <p class="lead">One person, one company, and a system that does the repetitive part.</p>
  </div>
</section>

<section class="band">
  <div class="wrap narrow">
    <h2>Qevik</h2>
    <p>Qevik is a website product for small businesses in Dubai. You describe what you need; the
      system researches your business, plans the work, builds the site, tests it, deploys it and
      then opens the live address in a browser to verify what a visitor receives.</p>
    <p>It exists because the same work was being done by hand, badly, everywhere: a clinic pays for
      a site, gets one language, no structured data, a phone number that is not a link, and no way
      to change the opening hours without emailing someone.</p>

    <h2>Who runs it</h2>
    <p><strong>{NAME}</strong> builds and runs Qevik. There is no agency, no account manager and no
      call centre. If you message the number on this site, you are messaging him.</p>

    <h2>The operating company</h2>
    <p>Qevik is the product and brand. The licensed company behind it is:</p>
    <address class="entity">
      <strong>{ENTITY}</strong><br>
      {ADDRESS_1}<br>
      {ADDRESS_2}
    </address>
    <p class="micro">Qevik is not a separately licensed company. Any agreement, invoice or contract
      is with {ENTITY}. If a Qevik trade licence is registered later, this page will say so.</p>

    <h2>What we will not do</h2>
    <ul class="ticks">
      <li>Put a doctor, an insurer or a patient review on your site unless you gave it to us</li>
      <li>Show a booking form that pretends to book something</li>
      <li>Promise a search ranking, a number of patients, or a result we cannot control</li>
      <li>Publish your site without you seeing it first</li>
    </ul>

    <h2>Contact</h2>
    <p><a href="tel:{PHONE_TEL}">{PHONE_DISPLAY}</a> · <a href="https://wa.me/{PHONE_WA}" rel="noopener">WhatsApp</a></p>
  </div>
</section>

<section class="closing">
  <div class="wrap">
    <h2>Questions before anything else?</h2>
    <p class="lead">Ask them. No form, no sequence of emails — just a message.</p>
    <div class="cta-row">
      <a class="btn primary" href="https://wa.me/{PHONE_WA}" rel="noopener">Message on WhatsApp</a>
      <a class="btn" href="/contact/">Contact details</a>
    </div>
  </div>
</section>
"""


def contact() -> str:
    return f"""
<section class="page-head">
  <div class="wrap">
    <p class="eyebrow">Contact</p>
    <h1>Talk to a person</h1>
    <p class="lead">There is no contact form on this page, on purpose. A form is a thing that
      collects your details and then makes you wait. These reach {NAME} directly.</p>
  </div>
</section>

<section class="band">
  <div class="wrap narrow">
    <div class="contact-grid">
      <a class="contact-card" href="https://wa.me/{PHONE_WA}" rel="noopener">
        <span class="ctag">Fastest</span>
        <h2>WhatsApp</h2>
        <p>{PHONE_DISPLAY}</p>
        <p class="micro">Send your business name and we will reply with a working example.</p>
      </a>
      <a class="contact-card" href="tel:{PHONE_TEL}">
        <span class="ctag">Direct</span>
        <h2>Phone</h2>
        <p>{PHONE_DISPLAY}</p>
        <p class="micro">Dubai hours. If it rings out, send a WhatsApp instead.</p>
      </a>
    </div>

    <h2>What to send</h2>
    <p>Your business name and the area you are in is enough. From that we can find your public
      listing and build a working example — English and Arabic — for you to look at.</p>
    <ul class="ticks">
      <li>You get a real link, live on the internet, not a picture</li>
      <li>Nothing is published under your own domain unless you ask for it</li>
      <li>Price is discussed after you have seen something, not before</li>
    </ul>

    <h2>Where we are</h2>
    <address class="entity">
      <strong>{ENTITY}</strong><br>
      {ADDRESS_1}<br>
      {ADDRESS_2}
    </address>
    <p class="micro">Qevik is the trading brand of {ENTITY}, not a separately licensed company.</p>
  </div>
</section>
"""


def organization_schema() -> str:
    """One JSON-LD block, on the home page only.

    Describes the operating company and names Qevik as its brand — the same
    relationship the footer states in words. Publishing an `Organization` called
    "Qevik" with a licence-like identity would be the structured-data version of
    the claim this site is careful not to make in prose.
    """
    return f"""<script type="application/ld+json">{{
  "@context": "https://schema.org",
  "@type": "ProfessionalService",
  "name": "{ENTITY}",
  "brand": {{"@type": "Brand", "name": "Qevik"}},
  "alternateName": "Qevik",
  "url": "{SITE}",
  "telephone": "{PHONE_TEL}",
  "founder": {{"@type": "Person", "name": "{NAME}"}},
  "address": {{
    "@type": "PostalAddress",
    "streetAddress": "{ADDRESS_1}",
    "addressLocality": "Deiram, Dubai",
    "addressCountry": "AE"
  }},
  "areaServed": {{"@type": "City", "name": "Dubai"}},
  "description": "Bilingual English and Arabic websites for small businesses in Dubai, built, tested, browser-verified and hosted.",
  "knowsLanguage": ["en", "ar"]
}}</script>"""


def work_page(key: str):
    def build() -> str:
        d = SHOWCASE[key]
        url = f"https://sites.qevik.ai/{d['slug']}/"
        real = "".join(f"<li>{item}</li>" for item in d["real"])
        needs = "".join(f"<li>{item}</li>" for item in d["needs"])
        arabic = (
            f'<a class="btn" href="{url}ar/" rel="noopener">افتح بالعربية</a>'
            if d["bilingual"] else ""
        )
        return f"""
<section class="page-head">
  <div class="wrap">
    <p class="eyebrow"><a href="/work/" style="color:inherit">Work</a> · {d['industry']}</p>
    <h1>{d['name']}</h1>
    <p class="lead">{d['concept']}</p>
    <div class="cta-row">
      <a class="btn primary" href="{url}" rel="noopener">Open the sample</a>
      {arabic}
      <a class="btn ghost" href="/work/">All work</a>
    </div>
    <p class="micro">A Qevik concept demonstration. {d['name']} is not a real business and is not
      a client. The contact details on it are ours, so the buttons genuinely work.</p>
  </div>
</section>

<section class="band">
  <div class="wrap">
    <figure class="showcase-shot" style="max-width:340px;margin:0 0 2rem">
      <img src="/assets/{fingerprinted(d['shot'])}" width="390" height="844"
           alt="{d['name']} on a phone." fetchpriority="high">
    </figure>
    <h2>Design direction</h2>
    <p class="stand">{d['design']}</p>

    <div class="grid two">
      <div class="card">
        <h3>What actually works</h3>
        <ul class="ticks">{real}</ul>
      </div>
      <div class="card">
        <h3>What would need building</h3>
        <ul class="ticks plain">{needs}</ul>
        <p class="micro" style="margin-top:.8rem">Listed rather than implied. Nothing on the
          sample pretends to do these.</p>
      </div>
    </div>

    <div class="note">
      <p><strong>Where this fits.</strong> {d['pitch']}</p>
    </div>
  </div>
</section>
"""
    return build




# --------------------------------------------------------------------------
# Arabic pages. Built from copy_ar, which is authored prose rather than a
# translation table — see that module for why the brand and the legal entity
# stay in Latin.
# --------------------------------------------------------------------------

def ar_home() -> str:
    c = copy_ar.HOME
    cards = "".join(
        f'<div class="card"><h3>{h}</h3><p>{b}</p></div>' for h, b in c["cards"]
    )
    steps = "".join(
        f'<li><span class="n">{i}</span><div><h3>{h}</h3><p>{b}</p></div></li>'
        for i, (h, b) in enumerate(c["steps"], 1)
    )
    return f"""
<section class="hero"><div class="wrap hero-grid">
  <div>
    <p class="eyebrow">{c["eyebrow"]}</p>
    <h1>{c["h1"]}</h1>
    <p class="lead">{c["lead"]}</p>
    <div class="cta-row">
      <a class="btn primary" href="https://wa.me/{PHONE_WA}" rel="noopener">{c["cta1"]}</a>
      <a class="btn" href="/ar/work/">{c["cta2"]}</a>
      <a class="btn ghost" href="{SAMPLE_CARROT}" rel="noopener">{c["cta3"]}</a>
    </div>
  </div>
  <figure class="hero-shot">
    <img src="/assets/{fingerprinted("sample-pulse-m.png")}" width="390" height="844"
         alt="لوحة تحكّم تطبيق لياقة على الهاتف." fetchpriority="high">
  </figure>
</div></section>

<section class="band"><div class="wrap">
  <h2>{c["what_h"]}</h2>
  <p class="stand">{c["what_p1"]}</p>
  <p class="stand">{c["what_p2"]}</p>
  <div class="grid three">{cards}</div>
</div></section>

<section class="band alt"><div class="wrap">
  <h2>{c["show_h"]}</h2>
  <p class="stand">{c["show_p"]}</p>
  {showcase_block("ar")}
</div></section>

<section class="band"><div class="wrap">
  <h2>{c["how_h"]}</h2>
  <p class="stand">{c["how_p"]}</p>
  <ol class="steps">{steps}</ol>
</div></section>

<section class="closing"><div class="wrap">
  <h2>{c["close_h"]}</h2>
  <p class="lead">{c["close_p"]}</p>
  <div class="cta-row">
    <a class="btn primary" href="https://wa.me/{PHONE_WA}" rel="noopener">{c["cta1"]}</a>
    <a class="btn" href="tel:{PHONE_TEL}" dir="ltr">{PHONE_DISPLAY}</a>
  </div>
</div></section>
"""


def ar_services() -> str:
    c = copy_ar.SERVICES
    blocks = ""
    for heading, lede, points in c["items"]:
        ticks = "".join(f"<li>{x}</li>" for x in points)
        blocks += (f'<article class="service"><h2>{heading}</h2><p>{lede}</p>'
                   f'<ul class="ticks">{ticks}</ul></article>')
    return f"""
<section class="page-head"><div class="wrap">
  <p class="eyebrow">{c["eyebrow"]}</p>
  <h1>{c["h1"]}</h1>
  <p class="lead">{c["lead"]}</p>
</div></section>

<section class="band"><div class="wrap">
  {blocks}
  <div class="note"><p>{c["note"]}</p></div>
</div></section>

<section class="closing"><div class="wrap">
  <h2>{c["close_h"]}</h2>
  <p class="lead">{c["close_p"]}</p>
  <div class="cta-row">
    <a class="btn primary" href="https://wa.me/{PHONE_WA}" rel="noopener">{copy_ar.HOME["cta1"]}</a>
    <a class="btn" href="/ar/contact/">{copy_ar.NAV["/contact/"]}</a>
  </div>
</div></section>
"""


def ar_work() -> str:
    c = copy_ar.WORK
    return f"""
<section class="page-head"><div class="wrap">
  <p class="eyebrow">{c["eyebrow"]}</p>
  <h1>{c["h1"]}</h1>
  <p class="lead">{c["lead"]}</p>
</div></section>

<section class="band"><div class="wrap">
  <h2>{c["h2"]}</h2>
  <p class="stand">{c["p1"]}</p>
  <p class="stand">{c["p2"]}</p>
  <div class="samples">{sample_cards("ar")}</div>
  <p class="micro">{c["note"]}</p>
</div></section>

<section class="closing"><div class="wrap">
  <h2>{c["close_h"]}</h2>
  <p class="lead">{c["close_p"]}</p>
  <div class="cta-row">
    <a class="btn primary" href="https://wa.me/{PHONE_WA}" rel="noopener">{copy_ar.HOME["cta1"]}</a>
    <a class="btn" href="tel:{PHONE_TEL}" dir="ltr">{PHONE_DISPLAY}</a>
  </div>
</div></section>
"""


def ar_about() -> str:
    c = copy_ar.ABOUT
    nots = "".join(f"<li>{x}</li>" for x in c["s4_items"])
    return f"""
<section class="page-head"><div class="wrap">
  <p class="eyebrow">{c["eyebrow"]}</p>
  <h1>{c["h1"]}</h1>
  <p class="lead">{c["lead"]}</p>
</div></section>

<section class="band"><div class="wrap narrow">
  <h2>{c["s1_h"]}</h2>
  <p>{c["s1_p1"]}</p>
  <p>{c["s1_p2"]}</p>

  <h2>{c["s2_h"]}</h2>
  <p>{c["s2_p"]}</p>

  <h2>{c["s3_h"]}</h2>
  <p>{c["s3_p"]}</p>
  <address class="entity" dir="ltr" style="text-align:start">
    <strong>{ENTITY}</strong><br>{ADDRESS_1}<br>{ADDRESS_2}
  </address>
  <p class="micro">{c["s3_note"]}</p>

  <h2>{c["s4_h"]}</h2>
  <ul class="ticks plain">{nots}</ul>

  <h2>{c["s5_h"]}</h2>
  <p><a href="tel:{PHONE_TEL}" dir="ltr">{PHONE_DISPLAY}</a> ·
     <a href="https://wa.me/{PHONE_WA}" rel="noopener">WhatsApp</a></p>
</div></section>
"""


def ar_contact() -> str:
    c = copy_ar.CONTACT
    items = "".join(f"<li>{x}</li>" for x in c["send_items"])
    return f"""
<section class="page-head"><div class="wrap">
  <p class="eyebrow">{c["eyebrow"]}</p>
  <h1>{c["h1"]}</h1>
  <p class="lead">{c["lead"]}</p>
</div></section>

<section class="band"><div class="wrap narrow">
  <div class="contact-grid">
    <a class="contact-card" href="https://wa.me/{PHONE_WA}" rel="noopener">
      <span class="ctag">{c["wa_tag"]}</span>
      <h2>{c["wa_h"]}</h2>
      <p dir="ltr" style="text-align:start">{PHONE_DISPLAY}</p>
      <p class="micro">{c["wa_p"]}</p>
    </a>
    <a class="contact-card" href="tel:{PHONE_TEL}">
      <span class="ctag">{c["tel_tag"]}</span>
      <h2>{c["tel_h"]}</h2>
      <p dir="ltr" style="text-align:start">{PHONE_DISPLAY}</p>
      <p class="micro">{c["tel_p"]}</p>
    </a>
  </div>

  <h2>{c["send_h"]}</h2>
  <p>{c["send_p"]}</p>
  <ul class="ticks">{items}</ul>

  <h2>{c["where_h"]}</h2>
  <address class="entity" dir="ltr" style="text-align:start">
    <strong>{ENTITY}</strong><br>{ADDRESS_1}<br>{ADDRESS_2}
  </address>
  <p class="micro">{copy_ar.UI["brand_note"]}</p>
  <p class="micro">{c["email_note"]}</p>
</div></section>
"""


BUILDERS = {
    "/": (home, organization_schema()),
    "/services/": (services, ""),
    "/work/": (work, ""),
    "/about/": (about, ""),
    "/contact/": (contact, ""),
    **{f"/work/{key}/": (work_page(key), "") for key in SHOWCASE},
    "/ar/": (ar_home, ""),
    "/ar/services/": (ar_services, ""),
    "/ar/work/": (ar_work, ""),
    "/ar/about/": (ar_about, ""),
    "/ar/contact/": (ar_contact, ""),
}


def check(path: str, html: str) -> list[str]:
    """Refuse a page that claims something Qevik does not do."""
    problems = []
    text = re.sub(r"<[^>]+>", " ", html).lower()
    for pattern, why in FORBIDDEN:
        if match := re.search(pattern, text):
            problems.append(f"{path}: {match.group(0)!r} — {why}")
    return problems


def sitemap() -> str:
    urls = "\n".join(
        f"  <url><loc>{SITE}{p}</loc><lastmod>{TODAY}</lastmod>"
        f"<priority>{'1.0' if p == '/' else '0.8'}</priority></url>"
        for p in PAGES
    )
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}\n</urlset>\n'


def robots() -> str:
    """Allow the marketing site; keep the control plane out of the index.

    `app.qevik.ai` is a different host and carries its own robots.txt, so these
    lines do not cover it — they exist for the case where a path on this host
    ever proxies to it, and cost nothing.
    """
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /auth/\n"
        "Disallow: /control/\n"
        "Disallow: /health\n"
        "\n"
        f"Sitemap: {SITE}/sitemap.xml\n"
    )


def favicon() -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        '<rect width="64" height="64" rx="14" fill="#0d6e6b"/>'
        '<path d="M32 14a18 18 0 1 0 10.6 32.5l4.6 4.6 4.2-4.2-4.6-4.6A18 18 0 0 0 32 14zm0 6a12 12 0 1 1 0 24 12 12 0 0 1 0-24z" fill="#fff"/>'
        "</svg>\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE / "dist")
    args = parser.parse_args(argv)

    out = args.out
    if out.exists():
        shutil.rmtree(out)
    (out / "assets").mkdir(parents=True)

    # Hash and copy assets first, so the pages can reference the hashed names.
    for asset in (
        "site.css",
        "sample_mobile_en.png",
        "sample_mobile_ar.png",
        "sample_desktop.png",
        "sample-restaurant.png",
        "sample-restaurant-ar.png",
        "sample-pulse-m.png",
        "sample-homefix-m.png",
        "sample-ledgerloop-m.png",
        "sample-meridian-m.png",
        "sample-carrot-m.png",
        "sample-foundry-m.png",
        "sample-atelier-m.png",
        "sample-nar-m.png",
        "sample-apex-m.png",
        "sample-verdant-m.png",
        "sample-cafe.png",
        "sample-detailing.png",
        "sample-property.png",
        "sample-salon.png",
        "og.png",
        "icon-180.png",
    ):
        source = HERE / "assets" / asset
        if not source.exists():
            print(f"missing asset: {source}", file=sys.stderr)
            return 1
        digest = hashlib.sha256(source.read_bytes()).hexdigest()[:8]
        stem, _, suffix = asset.rpartition(".")
        hashed = f"{stem}.{digest}.{suffix}"
        ASSETS[asset] = hashed
        shutil.copy(source, out / "assets" / hashed)

    favicon_bytes = favicon().encode("utf-8")
    favicon_name = f"favicon.{hashlib.sha256(favicon_bytes).hexdigest()[:8]}.svg"
    ASSETS["favicon.svg"] = favicon_name
    (out / "assets" / favicon_name).write_bytes(favicon_bytes)

    problems: list[str] = []
    for path, (builder, extra) in BUILDERS.items():
        html = shell(path, builder(), extra_head=extra)
        problems += check(path, html)
        target = out / path.strip("/") / "index.html" if path != "/" else out / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")
        print(f"  {path:<12} {len(html):>6} bytes")

    if problems:
        print("\nREFUSED — a page claims something Qevik does not do:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1

    (out / "sitemap.xml").write_text(sitemap(), encoding="utf-8")
    (out / "robots.txt").write_text(robots(), encoding="utf-8")

    # /favicon.ico is requested by browsers whether or not a page links one.
    # Serving the same SVG at the unhashed path keeps that request from 404ing.
    (out / "assets" / "favicon.svg").write_bytes(favicon_bytes)

    print(f"\nbuilt {len(PAGES)} pages + sitemap, robots, favicon -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
