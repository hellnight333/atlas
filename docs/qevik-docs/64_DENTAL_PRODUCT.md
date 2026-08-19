# The dental vertical — what the product actually is

The commercial deliverable is not "a website generator". It is one bilingual,
locally-optimised clinic site, generated from a clinic's own verified listing
facts, published at a real HTTPS address, and honest about the one thing it
cannot do. Twenty of them exist and are live.

Updated 2026-08-19.

---

## What is generated

`dental.render_site()` emits four files per clinic:

| File | Purpose |
|---|---|
| `index.html` | English page |
| `ar/index.html` | Arabic page, `dir="rtl"` |
| `robots.txt` | Points at the sitemap |
| `sitemap.xml` | Both language URLs, cross-linked with `xhtml:link` |

Published through `PublicHostTarget` — publish to `versions/<id>/`, then promote
by swapping the `current` symlink. Rollback is an ordinary promotion of an
earlier id.

Live at `https://sites.qevik.ai/<slug>/` and `…/ar/`.

---

## The rule the template is built around

**Nothing on a generated page may be a fact the clinic did not supply.**

Everything on the page traces to the Google listing: name, phone, address,
district. What is absent from the listing is absent from the page. There are no
invented doctor names, no invented insurers, no invented opening hours, no
stock photography implying a premises, no testimonials.

This is not caution for its own sake. The demo is shown to the clinic that owns
the facts, and a single fabricated detail — a dentist who does not work there,
an insurer they do not accept — ends the conversation and deserves to.

Three consequences worth naming, because each looks like a missing feature and
is not:

- **The Arabic headline drops the district.** Area names come from an English
  listing, and the bidi algorithm reorders a Latin word out of an Arabic
  sentence onto its own line. Inventing an Arabic spelling of a Dubai district
  would be the same fabrication. The address block still carries the location.
- **WhatsApp appears on 4 of 20 sites.** `whatsapp_href()` is gated on a UAE
  mobile pattern, because `wa.me/` a landline or a toll-free number produces a
  dead link. 16 of the 20 clinics publish only a landline. The absence is
  recorded as `CONFIRMED_ABSENT`, not as a failure.
- **Opening hours appear only where the listing carried them.** The JSON-LD
  omits `openingHours` rather than guessing.

---

## Bilingual

Both pages are rendered from the same facts through `_strings.py`, which holds
the English and Arabic `Strings` side by side — service names, assurances, day
names, form labels. Translation is not applied at render time; both languages
are written out and reviewed.

Each page is **canonical for itself**, and the two are joined by `hreflang`
alternates plus `x-default` on English. Pointing the Arabic canonical at the
English page — which an earlier version did — declares it a duplicate, and
duplicates are dropped from the index, removing the Arabic page from precisely
the searches it exists to win.

Verified on all 20: every Arabic page returns 200, carries `lang="ar" dir="rtl"`,
self-canonicalises, and contains no Latin text in its headline.

---

## Conversion surface

Measured across all 20 live English pages:

| Element | Present |
|---|---|
| `tel:` link | 20/20 |
| Google Maps directions | 20/20 |
| Appointment form | 20/20 |
| Sticky mobile call/book bar | 20/20 |
| WhatsApp | 4/20 — gated, see above |

### The appointment form does not submit anywhere

**`NOT_IMPLEMENTED`, deliberately and visibly.** There is no booking backend, no
queue, no notification. The form's submit handler says so in the page's own
language and directs the visitor to phone the clinic.

A fake success message would be the one lie on these pages that reaches a
patient rather than a prospect — someone believing an appointment exists when
none does. The form is present because it demonstrates the shape of the
finished product; it is honest because the alternative is indefensible.

Building the backend is a separate, deliberate decision. Until it is made, this
stays exactly as it is.

---

## Regenerating

```
infra/regenerate_demos.py            # dry run — reports which sites would change
infra/regenerate_demos.py --deploy   # publish and promote all 20
```

Reads the newest file under `/var/lib/qevik/prospects/` and re-renders from the
stored facts. It does **not** re-query Google Places: a template change should
not also move the data it is rendered from, and discovery costs money to return
facts already on disk.

`infra/prospect_pipeline.py` is the discovery path and does spend. Use it to
find new clinics, not to pick up a template change.

---

## Tests

`packages/kernel/tests/test_dental_vertical.py` — 24 tests, covering the
fabrication rules, the WhatsApp gating, the canonical/hreflang relationship, the
bidi headline, and the appointment form's honesty.

Two of these tests previously *encoded* the WhatsApp bug and were corrected when
the bug was found. A test that asserts current behaviour is not evidence that
the behaviour is right.

---

## Beyond dental — `business.py`

Added 2026-08-19. `dental.py` is unchanged and stays that way: twenty live
demos and two approved outreach messages point at pages it renders, and the
sales experiment must not move while the product broadens underneath it.

`website/verticals/business.py` is a second renderer with nothing
industry-specific in it. A `Business` carries its own sections, its own words in
both languages, and its own `schema.org` type; the template arranges them and
adds what every local business needs — address, hours, map, tap-to-call,
WhatsApp where the number can receive it, sticky call bar.

Every rule from the dental template carries over, because they are about honesty
rather than dentistry: no invented staff or reviews, WhatsApp only on a mobile
that can receive it, and nothing books. A restaurant's "request a table" and a
salon's "request an appointment" are different promises and both are still
requests — each says so on the page, in that page's language.

### The six samples

`infra/samples.py` builds Qevik's own samples, live at `sites.qevik.ai`:

| Slug | Type | Shape |
|---|---|---|
| `sample-restaurant` | `Restaurant` | Menu by category with prices, table request |
| `sample-cafe` | `CafeOrCoffeeShop` | Drinks, retail beans, single-line hours |
| `sample-detailing` | `AutoWash` | Services, service area, FAQ, quote request |
| `sample-salon` | `BeautySalon` | Treatments with durations, appointment request |
| `sample-property` | `RealEstateAgent` | Service groups, FAQ, call-back request |
| `sample` | `Dentist` | The original dental template |

They are **ours, not clients.** Each carries Qevik's own phone number — so every
button genuinely works and no fictional number that might belong to a real
person is published — and each is flagged on the page in both languages as a
sample rather than a real business.

The twenty clinic demos are deliberately absent from the public site. They were
built unsolicited from public listings, none of those businesses are customers,
and showing them as portfolio would invent a relationship that does not exist.
They also carry `X-Robots-Tag: noindex`, because twenty pages on our domain
holding a real clinic's name, address and phone would compete in local search
with the business they were built for.

### A cross-site scripting hole, found by a test

`json.dumps` escapes quotes but not `</script>`, so a business name containing
markup closed the JSON-LD block and injected into the page. The names come from
Google listings — untrusted input. `business.py` now escapes `<` as `<`.

`dental.py` was checked directly rather than assumed safe, and was already
correct; a regression test now pins that.
