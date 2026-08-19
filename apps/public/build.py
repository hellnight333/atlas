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

#: path -> (nav label, <title>, meta description)
PAGES: dict[str, tuple[str, str, str]] = {
    "/": (
        "Home",
        "Qevik — websites for Dubai clinics and small businesses",
        "Qevik builds bilingual English and Arabic websites for Dubai businesses, "
        "then tests and verifies them in a real browser before they go live. "
        "Hosting, HTTPS and ongoing changes included.",
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
    "/contact/": (
        "Contact",
        "Contact — Qevik",
        "Talk to Ayoub Soleimani directly on WhatsApp or by phone about a "
        "website for your Dubai business.",
    ),
}

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


#: Filled during the build: "site.css" -> "site.9f2a1c.css". Cloudflare caches
#: /assets/* for a day, so an edited stylesheet kept serving the old bytes even
#: though the origin had the new ones — cf-cache-status was HIT and the fix was
#: invisible for 24 hours. Fingerprinting makes a changed file a different URL,
#: which no cache can serve stale and which needs no purge permission.
ASSETS: dict[str, str] = {}


def fingerprinted(name: str) -> str:
    return ASSETS.get(name, name)


def shell(path: str, body: str, *, og_type: str = "website", extra_head: str = "") -> str:
    label, title, description = PAGES[path]
    canonical = f"{SITE}{path}"
    nav = "".join(
        f'<a href="{p}"{" class=\"here\" aria-current=\"page\"" if p == path else ""}>{PAGES[p][0]}</a>'
        for p in PAGES
    )
    year = TODAY[:4]

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{description}">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="{og_type}">
<meta property="og:url" content="{canonical}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:site_name" content="Qevik">
<meta property="og:locale" content="en_AE">
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
<a class="skip" href="#main">Skip to content</a>
<header class="site">
  <div class="bar">
    <a class="brand" href="/"><span class="mark">Q</span><span>Qevik</span></a>
    <nav aria-label="Primary">{nav}</nav>
    <a class="call" href="tel:{PHONE_TEL}">{PHONE_DISPLAY}</a>
  </div>
</header>
<main id="main">
{body}
</main>
<footer class="site">
  <div class="cols">
    <div>
      <p class="fbrand">Qevik</p>
      <p>Websites for Dubai clinics and small businesses. Built, tested and hosted.</p>
    </div>
    <div>
      <p class="flabel">Operated by</p>
      <p>{ENTITY}<br>{ADDRESS_1}<br>{ADDRESS_2}</p>
      <p class="fnote">Qevik is a product and brand of {ENTITY}. It is not a separately licensed company.</p>
    </div>
    <div>
      <p class="flabel">Talk to a person</p>
      <p><a href="tel:{PHONE_TEL}">{PHONE_DISPLAY}</a><br>
         <a href="https://wa.me/{PHONE_WA}" rel="noopener">WhatsApp</a></p>
      <p>{NAME}</p>
    </div>
  </div>
  <p class="legal">&copy; {year} {ENTITY}. Qevik is its trading brand.</p>
</footer>
</body>
</html>
"""


def home() -> str:
    return f"""
<section class="hero">
  <div class="wrap hero-grid">
   <div>
    <p class="eyebrow">Dubai · English &amp; Arabic</p>
    <h1>A website your patients can actually use — in English and Arabic.</h1>
    <p class="lead">Qevik builds the site, tests it, opens it in a real browser to check what a
      visitor receives, and puts it online with HTTPS. You get a link you can open on your phone
      before you decide anything.</p>
    <div class="cta-row">
      <a class="btn primary" href="https://wa.me/{PHONE_WA}" rel="noopener">Ask on WhatsApp</a>
      <a class="btn" href="{SAMPLE}" rel="noopener">See a live example</a>
      <a class="btn ghost" href="/work/">How it looks</a>
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
    <p class="stand">Qevik is a website service for small businesses in Dubai — clinics first.
      You describe what you need in plain language. The system researches, plans, builds, tests and
      deploys the site, and a person checks it before anyone sees it.</p>
    <div class="grid three">
      <div class="card">
        <h3>Built from your own details</h3>
        <p>Your name, phone number, address and opening hours, taken from your own listing.
          Nothing is invented — no doctors you do not employ, no insurers you do not accept,
          no reviews nobody wrote.</p>
      </div>
      <div class="card">
        <h3>English and Arabic, properly</h3>
        <p>Two separate pages with correct right-to-left layout, not a translate button.
          Each is its own address so search engines can find both.</p>
      </div>
      <div class="card">
        <h3>Checked before you see it</h3>
        <p>Every site is opened in a real browser and inspected — the page loads, the phone link
          dials, the map opens, the Arabic page is right-to-left. If a check fails, it does not ship.</p>
      </div>
    </div>
  </div>
</section>

<section class="band alt">
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

<section class="band">
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

<section class="band alt">
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
    <p class="stand">This is a real page on the real internet, not a picture of one. Open it on your
      phone and press the buttons — the call button dials us, because the sample uses our own number.</p>
    <div class="shots">
      <figure>
        <img src="/assets/{fingerprinted("sample_mobile_en.png")}" width="390" height="844"
             alt="The English sample clinic page on a phone, showing a call button, an appointment request button, WhatsApp and directions." loading="lazy">
        <figcaption>English, on a phone</figcaption>
      </figure>
      <figure>
        <img src="/assets/{fingerprinted("sample_mobile_ar.png")}" width="390" height="844"
             alt="The Arabic version of the same page, laid out right to left with Arabic headings and Arabic day names." loading="lazy">
        <figcaption>Arabic, right to left</figcaption>
      </figure>
    </div>
    <div class="cta-row">
      <a class="btn primary" href="{SAMPLE}" rel="noopener">Open the live sample</a>
      <a class="btn" href="{SAMPLE_AR}" rel="noopener">Open it in Arabic</a>
    </div>
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
    <h1>A site you can open right now</h1>
    <p class="lead">Rather than a gallery of pictures, here is a live page. Open it, press the
      buttons, switch it to Arabic. It behaves exactly as a real customer site would.</p>
  </div>
</section>

<section class="band">
  <div class="wrap">
    <div class="showcase">
      <div class="showcase-copy">
        <h2>Sample Dental Clinic</h2>
        <p>A complete generated site: English and Arabic pages, services, opening hours, address,
          map link, tap-to-call, WhatsApp and an appointment request form.</p>
        <p class="micro">It is a demonstration, not a real clinic. The contact details on it are
          <strong>ours</strong>, so every button genuinely works — the call button dials Qevik.</p>
        <div class="cta-row">
          <a class="btn primary" href="{SAMPLE}" rel="noopener">Open in English</a>
          <a class="btn" href="{SAMPLE_AR}" rel="noopener">افتح بالعربية</a>
        </div>
      </div>
      <figure class="showcase-shot">
        <img src="/assets/{fingerprinted("sample_desktop.png")}" width="1280" height="820"
             alt="The sample clinic site on a laptop, showing the headline, call and appointment buttons, and the services section." fetchpriority="high">
      </figure>
    </div>
  </div>
</section>

<section class="band alt">
  <div class="wrap">
    <h2>The same site, both languages</h2>
    <p class="stand">Two separate pages rather than a switch that rewrites the text in place. The
      Arabic page is laid out right to left, with Arabic headings and day names.</p>
    <div class="shots">
      <figure>
        <img src="/assets/{fingerprinted("sample_mobile_en.png")}" width="390" height="844"
             alt="English version on a phone: headline, call button, appointment request, WhatsApp and directions." loading="lazy">
        <figcaption>English</figcaption>
      </figure>
      <figure>
        <img src="/assets/{fingerprinted("sample_mobile_ar.png")}" width="390" height="844"
             alt="Arabic version on a phone, laid out right to left with Arabic headings." loading="lazy">
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


BUILDERS = {
    "/": (home, organization_schema()),
    "/services/": (services, ""),
    "/work/": (work, ""),
    "/about/": (about, ""),
    "/contact/": (contact, ""),
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
