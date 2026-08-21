# AHS Catering & Events — source audit

Read from `https://ahscatering.com/` on 2026-08-21, across all twelve public
pages, the header, the footer and the contact form. **Everything below was
observed on their site.** Nothing here is inferred, and where something could
not be established it says so.

This exists so the concept at `sites.qevik.ai/sample-ahs/` can be checked line
by line against the source rather than against taste.

---

## 1. Confirmed business facts

| Fact | Where |
|---|---|
| Trading name **AHS**, tagline **Beyond Catering** | Logo, every page |
| Dubai-based event catering | Homepage copy |
| "Backed by 20+ years of culinary mastery, halal-certified kitchens and a planning team that perfects every detail of your celebration." | Homepage hero, verbatim |
| **"Your Dream Event, Our Signature Cuisine"** | Homepage H2, verbatim |
| Two arms: **Corporate Events** and **Private Events** | Two homepage H2s |
| **EATLUX** — their own concept/sub-brand | Top-level nav, dedicated page |
| Founder is **Managing Partner and Founder of EATLUX** | Homepage H2 |
| Named consultant **Kristina** | Contact form: "complimentary consultation … with Kristina" |
| Capability strip: **Capacity · HACCP Certified · Sustainability · Local Products · Special Dietary Needs** | Homepage H3s |
| **No prices published anywhere.** They ask "Catering budget per person" as an input | All pages / contact form |

**Testimonials exist and are attributed** — two named individuals with roles on
the homepage. Not reproduced in the concept; see §9.

## 2. Navigation and services

Eleven top-level items, wrapping onto three lines at 1280:

`About Us · EATLUX · Private Catering · Corporate Catering · Live Station
Catering · Canapé & Dessert Catering · Wedding Catering · Gala Catering ·
Ramadan 2026 · Blog · Contact`

Footer repeats all eleven as "Quick Links", plus **Privacy Policy**.

Photograph counts per service page — this is where their real assets are, and
the homepage surfaces almost none of them:

| Page | Photographs |
|---|---|
| Corporate catering | 19 |
| Live station catering | 18 |
| Canapé & dessert | 17 |
| Private catering | 16 |
| Gala catering | 9 |
| Blog | 7 |
| About us | 6 |
| **Homepage** | **10** (several the same logo SVG repeated) |

## 3. Contact methods

| Method | Value | Evidence |
|---|---|---|
| Phone | **+971 55 749 2608** | Footer "Contact number", plain text on all 12 pages |
| Email | **Info@ahscatering.com** | Footer "Contact email", plain text on all 12 pages |
| WhatsApp | **971557492608** | Click-to-Chat widget config: `class="ht_ctc_chat_data" data-settings="{"number":"971557492608","pre_filled":"Hello, I do have a question regarding your catering services. Sent from ahscatering.com"}"` |
| Address | **Dubai Investment Park 2** | Footer "Address" |
| Map | **none** | No map link and no iframe on any page, including Contact |

**Two conversion defects on their own site, both confirmed:**

- The phone number and email are **plain text on every page** — there is not a
  single `tel:` or `mailto:` link anywhere on the site. On a phone the number
  cannot be tapped.
- No map or directions link exists, despite an address in the footer.

The first matches the `click_to_call` finding already recorded against this
business in the audit timeline.

## 4. Social accounts

Only two are linked, and both appear site-wide:

- Instagram — `https://www.instagram.com/ahscatering`
- LinkedIn — `https://www.linkedin.com/company/ahs-catering-and-events`

The footer labels the LinkedIn link "Linkedin". **No Facebook, TikTok, YouTube
or X account is linked from the site**, so none is shown in the concept.

## 5. Existing CTAs, in their own words

`PLAN YOUR EVENT` · `Get Quote` (desktop hero) · `Get Custom Offer` (mobile
hero) · `CALL US` · `CONTACT` · `LET'S HANDLE YOUR EVENT` (contact page) ·
"Tell Us About Your Event. We'll Handle The Rest"

Note their own inconsistency: the same hero button is "Get Quote" on desktop and
"Get Custom Offer" on mobile.

## 6. Their enquiry structure — verbatim

This is the most valuable thing on their site and the concept's brief is built
from it:

Name · Phone number · Email · Event date · Event timings · Event location ·
Number of guests

- **Occasion type** — Birthday, Engagement, Wedding, Private party,
  Housewarming, Graduation, Breakfast, Brunch, Corporate lunch,
  Opening ceremonies, Product launch
- **Event site** — Indoor, Outdoor
- **Services needed** — Catering, Mocktail station, Furniture, Decoration,
  Table setup, Flower centerpieces, Balloons, Dessert setup, Beach setup,
  Specialty cake, Event planning and management, Entertainment
- **Serving staff** — Waiters, Bartenders, Hostesses, Mixologists
- **Food allergy** — No / Yes, then "Please indicate type of allergy"
- **Type of service** — Buffet, Canapes, Pass around, Seated dinner,
  Live cooking (bbq), Private chef
- **Type of cuisine**
- **Catering budget per person**
- **Complimentary consultation with Kristina** — Yes / No

## 7. Brand elements to preserve

Gold `#E1C25F` on near-black; cloche/dome logo mark; "Beyond Catering"; the
uppercase headline voice; full-bleed dark food photography in the hero. Their
type is Roboto and Poppins — generic WordPress theme faces, deliberately not
carried over.

## 8. Content that must survive a redesign

Two arms · seven event types · EATLUX · live stations · the five capability
statements · founder positioning · bespoke quoting with no prices · phone ·
email · WhatsApp · address · both social accounts · Ramadan seasonal offering ·
blog.

## 9. Deliberately not included, and why

| Omitted | Why |
|---|---|
| **Their photographs** | Rights uncertain, no permission. Not re-hosted on a public Qevik directory. Every image region is a labelled composed treatment cut to the real crop, so their pictures drop in later. |
| **Their two named testimonials** | They are on the source site and attributed, so reproducing them is permitted by the brief — but putting named individuals' words on an unsolicited third-party page implies we verified them. Same stance as the photography. Available on request. |
| **The 11-item navigation** | Deliberate UX change. Every destination stays reachable; the visitor is no longer asked to classify themselves before seeing anything. |
| **Their "Sent from ahscatering.com" WhatsApp pre-fill** | It would be false coming from a Qevik page. |
| **A map link** | They publish an address but no map. Inventing a pin would be inventing a location. |
| **Blog** | Content-dependent; nothing to show without reproducing their posts. |
| **"Catering budget per person"** | Present in their form, left out of the concept's brief so nothing on the page can read as a price. |

## 10. One deployment note

Cloudflare's **Email Address Obfuscation** rewrites the `mailto:` in the served
HTML to `/cdn-cgi/l/email-protection#…` with the address replaced by
`[email protected]`. Its decoder restores both the href and the visible text on
load, so a real visitor sees `Info@ahscatering.com` and a working `mailto:` —
verified in a browser against the live URL.

Worth knowing because a source-fidelity check run against **raw HTML** reports
the email as missing. Check the rendered page, not the response body.

## 11. Uncertainty

- Whether the founder named on the contact form is the same person as the
  "Managing Partner and Founder of EATLUX" on the homepage. The concept uses
  the **role**, never a name.
- Whether "Dubai Investment Park 2" is a visitable address or a kitchen. Shown
  as published, with no map and no claim either way.
