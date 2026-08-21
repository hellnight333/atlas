# AHS Catering & Events — source audit

Read from `https://ahscatering.com/` on 2026-08-21: the twelve pages linked from
their navigation, plus their WordPress REST API, which exposes **sixty pages and
four posts** — most of which the navigation does not reach.

**Everything below was observed on their site.** Where something could not be
established it says so. The machine-readable form is
[`apps/samples/ahs/source.py`](../../apps/samples/ahs/source.py); the concept
generator and the tests both read from it, so the site and this document cannot
drift apart.

---

## 1. What they actually are

| Fact | Where |
|---|---|
| Trading name **AHS**, tagline **Beyond Catering** | Logo, every page |
| "more than 20 years of excellence in luxury weddings, corporate functions, and private celebrations" | About, verbatim |
| Founder **Ali Darwish** — started at 16 polishing cutlery, learned front-of-house, then the kitchen | About |
| "You can't lead excellence if you don't understand the details." | About, verbatim |
| **EATLUX** — "the UAE's first-ever Show Belt Dining Experience" | EATLUX page, blog |
| EATLUX was created by **Kristina** (from wedding planning) with **Ali** | EATLUX page |
| Halal-certified kitchens · HACCP · sustainability · local sourcing · dietary needs | Homepage |
| **No prices published anywhere**; the form asks "catering budget per person" | All pages |

This resolves the two questions the previous audit left open: the founder is
named, and Kristina is his EATLUX co-founder rather than the same person.

## 2. Their client list — theirs, published, not ours

From the About page, verbatim: **MBC Group, Michelin, Dubai Mall, Gucci,
Booking.com, Validus, Hyundai, Red Bull, Nestlé, Messara Living, the Romanian
Consulate, Sephora** — "and many more".

From their Formula 1 post: **Amazon, Bybit, DHL, Dubai Police, DEWA**, and
serving at the **Formula 1 Abu Dhabi Grand Prix 2025**.

Seventeen named brands, in two paragraphs, on two pages, linked from neither the
homepage nor the work.

## 3. The finding that changes the pitch

Their REST API returns **32 event pages carrying 170 photographs**, against a
**501-item media library**:

| Sample | Photographs | Words of text |
|---|---|---|
| Winter wonderland | 7 | 2 |
| Nestle | 6 | 1 |
| Roger Vivier Dubai Mall | 6 | 4 |
| Geidea board meeting | 6 | 3 |
| Breakfast catering for Pepsi in DIP | 5 | 6 |
| Porsche | 3 | 1 |

Every one is a title and photographs. **No date, no guest count, no service
style, no menu, no story on any of them.** The homepage links to none of the 32.

So a corporate buyer cannot answer the only question that matters — *have they
done my kind of event* — about a company that has catered Formula 1, Nestlé,
Porsche and Gucci. That is not a business that needs a redesign. It is a
business with world-class proof and no proof system.

## 4. Contact methods

| Method | Value | Evidence |
|---|---|---|
| Phone | **+971 55 749 2608** | Footer, plain text on all 12 pages |
| Email | **Info@ahscatering.com** | Footer, plain text on all 12 pages |
| WhatsApp | **971557492608** | Click-to-Chat config: `class="ht_ctc_chat_data" data-settings="{"number":"971557492608",…}"` |
| Address | **Dubai Investment Park 2** | Footer |
| Map | **none** | No map link or iframe on any page |

**There is not one `tel:` or `mailto:` link anywhere on the site.** On a phone
the number cannot be tapped. This matches the `click_to_call` finding already on
their timeline.

## 5. Social accounts

Instagram `ahscatering` and LinkedIn `ahs-catering-and-events`, site-wide. **No
Facebook, TikTok, YouTube or X is linked**, so none appears in the concept, and
a test fails the build if one is added.

## 6. Arabic — confirmed absent

`html lang="en-US"`. No `hreflang` alternates, no language switcher, no WPML or
TranslatePress, no `/ar/` route. The site is English only — while they sell
Ramadan iftars, an Arabic-theme dinner, and MBC Group's iftar.

## 7. Their blog

Four posts, **all published 2025-11-11**, all filed *Uncategorized*, **103–331
words**, and **not one of them carries an image** — beside a 501-item media
library. Their largest achievement, Formula 1 Abu Dhabi 2025, is the 103-word
one.

The subjects are good and they are theirs: Formula 1 · EATLUX show-belt dining ·
behind the scenes · sustainability and luxury. The concept keeps all four
subjects and presents them as a reader would want them.

## 8. Other defects, all confirmed

- **Testimonials name a different brand.** `/reviews/` is not in the navigation,
  and two of its three testimonials thank *"Al Hamra Street"* rather than AHS.
- **The privacy policy is the unedited WordPress sample.** "Who we are — Our
  website address is…", then sections on blog comments, Gravatar and embedded
  content. Nothing about catering, events or guest data.
- **Duplicate and stale routes**: `/home-old-old/`, `/homeold/`,
  `/sample-page-2-2/` titled "New Home", `/privet/`, `/corporate-events-2/`
  titled "PRIVATE EVENTS", three Ramadan pages, and two competing
  corporate-catering URLs.
- **Their CMS clones pages without renaming them**: `/nas-daily-x-solana-16-2/`
  is titled "Birthday" and `/nas-daily-x-solana-2-3-4/` is titled "Staff party
  for real estate". The address and the page disagree.
- **Every heading is duplicated in the DOM**, and the eleven-item navigation
  appears three times per page — a theme rendering desktop and mobile copies.

## 9. Their services — substantial, and the source for the concept's pages

| Page | Words | Photographs | Headings they publish |
|---|---|---|---|
| Wedding catering | 1045 | 9 | Seated & plated · Buffet & live stations |
| Live station catering | 981 | 17 | BBQ · Seafood & oyster bar · Pasta & sliders |
| Corporate catering | 878 | 19 | Tailored menus · Presentation · On-time service |
| Canapé & dessert | 805 | 16 | European · Arabic delight · Asian & international |
| Private catering | 795 | 15 | Housewarming · Birthday · Gatherings · Seated dinners |
| Gala catering | 787 | 7 | Black-tie award nights · Executive dinners |
| Ramadan 2026 | 554 | 17 | Grilled & carving stations · Signature dessert |
| EATLUX | 756 | 1 | Show belt dining |

## 10. Their enquiry structure — verbatim

Name · Phone · Email · Event date · Timings · Location · Number of guests, then:
**Occasion type** (11 options) · **Event site** · **Services needed** (12) ·
**Serving staff** (4) · **Food allergy** · **Type of service** (6) ·
**Type of cuisine** · **Catering budget per person** · **Complimentary
consultation with Kristina**.

They already know exactly what they need in order to quote. It is asked as one
long form at the end rather than collected while the visitor reads.

## 11. Deliberately not included, and why

| Omitted | Why |
|---|---|
| **Their photographs** | Rights uncertain, no permission sought or given. Not re-hosted. Every image region is a composed CSS treatment and says so. |
| **Their testimonials** | Attributed on their site, so reproducible — but putting named individuals' words on an unsolicited page implies we verified them. Also two of three name a different brand. |
| **Client logos** | Their client *names* are their own published claim and appear as text. Logos are trademarks and are not reproduced. |
| **Their WhatsApp pre-fill** | "Sent from ahscatering.com" would be false from a Qevik page. |
| **A map link** | They publish an address and no map. A pin would be a location we chose. |
| **"Budget per person"** | Left out of the brief so nothing on the page can read as a price. |
| **The 11-item navigation** | Deliberate change to six. Every destination stays reachable. |

## 12. Two deployment notes

**Cloudflare Email Obfuscation** rewrites `mailto:` in the served HTML to
`/cdn-cgi/l/email-protection#…`. Its decoder restores the href and the visible
text, so a real visitor sees the address — verified in a browser. A
source-fidelity check run against the raw response reports the email missing;
check the rendered page.

**The edge caches the stylesheet for four hours.** A correct CSS fix shipped and
was invisible because `styles.css` was served from cache over new HTML. The
stylesheet is now content-addressed (`styles-<hash>.css`), so a changed
stylesheet is a different URL and cannot go stale.

## 13. Remaining uncertainty

- Whether "Dubai Investment Park 2" is a visitable address or a kitchen. Shown
  as published, with no map and no claim either way.
- Whether "Al Hamra Street" in their testimonials is a former trading name (AHS
  is a plausible acronym for it) or copy taken from elsewhere. **Not asserted in
  the concept either way** — the testimonials are simply not reproduced.
- Guest counts, dates and service styles for all 32 events. They publish none,
  and the concept marks every one of them *not published* rather than guessing.
