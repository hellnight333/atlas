# Google Search Console and Business Profile — what Ayoub must do by hand

Updated 2026-08-19.

**Nothing here has been done.** Both require signing in to a Google account, which
only the operator can do. This document exists so the steps are decided in
advance rather than improvised, and so the site is already in the state each
step expects.

What is already true, so none of it blocks you:

| | |
|---|---|
| `qevik.ai` serves over HTTPS | ✅ |
| `www.qevik.ai` → `qevik.ai`, path preserved | ✅ 301 |
| All five pages return 200 | ✅ |
| A wrong URL returns a real 404, not a soft one | ✅ |
| `robots.txt` and `sitemap.xml` | ✅ live |
| Canonical, OpenGraph, unique titles and descriptions | ✅ per page |
| Structured data | ✅ `ProfessionalService` on the home page |
| Favicon, apple-touch icon, OG image | ✅ |
| Control plane excluded from search | ✅ `X-Robots-Tag: noindex` on `app.qevik.ai` |
| Client demos excluded from search | ✅ `noindex` on `sites.qevik.ai/demo-*` |

---

## 1 · Google Search Console

**Roughly ten minutes. Do this first** — it is what tells Google the site exists.

1. Open <https://search.google.com/search-console> and sign in with the Google
   account that should own this long-term. Use a business account, not a
   personal one you might lose access to.
2. **Add property → Domain** (not "URL prefix"). A domain property covers
   `qevik.ai`, `www.qevik.ai`, `app.` and `sites.` in one, and both http and
   https.
3. Google will show a **TXT record** to add to DNS. Add it in Cloudflare:
   *DNS → Records → Add record → TXT*, name `@`, value as given, TTL Auto.
   Leave every existing record alone.
4. Wait a minute, press **Verify**.
5. **Sitemaps → Add a new sitemap →** `sitemap.xml`, submit. It should read
   "Success" with 5 discovered URLs.
6. **URL Inspection**, paste `https://qevik.ai/`, then **Request indexing**.
   Repeat for `/services/`, `/work/`, `/about/`, `/contact/`. This is not
   required but it is markedly faster than waiting to be crawled.

**Tell me the TXT record** if you would rather I confirm the DNS side is correct
before you press Verify. I cannot add it — there is no Cloudflare token, by
your instruction.

### What to check a week later

- **Pages** → 5 indexed, 0 with errors
- **Page indexing** → nothing from `app.qevik.ai` or a `demo-` URL. If either
  appears, the `noindex` header is not being served and I should look.
- **Mobile usability** → no issues

---

## 2 · Google Business Profile

**Do this after Search Console.** Verification can take days, so starting it
early matters more than finishing it.

⚠️ **Not started, and not verified.** No Google account credentials are
available to this system, and a Business Profile must be created by the person
who owns the business.

### Before you begin, decide one thing

**Is the Deiram office a place customers visit?** The answer changes the whole
listing and cannot be casually changed later:

- **Yes, customers come to the office** → an address-based listing. The address
  is shown publicly and Google may post a verification card to it.
- **No, you go to them / it is remote** → a **service-area business**. The
  address is hidden and you name the areas served instead.

For a website service, **service-area is almost certainly correct.** Publishing
an office address invites walk-ins to a room that is not a shopfront, and a
listing whose address does not look like a real trading premises is a common
reason verification is refused.

### The checklist

**Identity**
- [ ] Business name: **Qevik** — the trading name people will search
- [ ] Do **not** enter "Qevik LLC" or "Qevik FZ-LLC". Qevik is not a licensed
      company; the licence is Asia Link Internet Content Provider LLC. Google
      compares the name against your trade licence during verification, and a
      mismatch is grounds for refusal or suspension.
- [ ] If Google asks for the legal entity, give **Asia Link Internet Content
      Provider LLC**

**Category**
- [ ] Primary: **Website designer**
- [ ] Secondary (optional): *Internet marketing service*, *Web hosting company*
- [ ] Not "Software company" — it changes which searches you appear in

**Address / service area**
- [ ] Choose **service area** unless customers genuinely visit (see above)
- [ ] Service areas: Dubai; add Sharjah and Abu Dhabi only if you will actually
      travel there
- [ ] If address-based: Office 301, Al Othman Building, Deiram, Dubai, UAE —
      exactly as on the trade licence

**Contact**
- [ ] Phone: **+971 50 102 9104** — the same number as on the website, digit for
      digit. Google cross-checks this.
- [ ] Website: **https://qevik.ai** (with https, no trailing path)
- [ ] Appointment link: **leave blank.** There is no booking system, and
      pointing it at the request form would be the same overstatement the
      website avoids.

**Hours**
- [ ] Set real hours you will actually answer the phone during
- [ ] Sunday–Thursday is the UAE working week; do not copy a Mon–Fri pattern
- [ ] If it is a phone answered whenever you are awake, say so with wider hours
      rather than leaving it blank

**Photos and logo**
- [ ] Logo: square, ≥ 720×720. `apps/public/assets/icon-180.png` is the mark but
      is only 180px — I can render a larger one on request.
- [ ] Cover photo: 1200×630. `apps/public/assets/og.png` works as a starting
      point.
- [ ] Add 3–5 real photos. **Screenshots of actual generated sites are fine and
      are honest.** Stock photos of a generic office are not, and Google
      sometimes removes them.
- [ ] No photo of an office you do not trade from

**Description** (750 characters max)

> Qevik builds websites for small businesses in Dubai — clinics especially — in
> both English and Arabic. Each site is built from your own business details,
> tested, opened in a real browser to check what a visitor receives, then hosted
> with HTTPS. Includes local SEO basics, Google Maps directions, click-to-call
> and WhatsApp where your number supports it, plus ongoing changes. Qevik is
> operated by Asia Link Internet Content Provider LLC.

- [ ] Paste as-is. It claims nothing that is not built. Do not add "online
      booking" — there is none.

**Verification**
- [ ] Expect **video verification** for a service-area business in the UAE: a
      continuous unedited recording showing your work location, tools, and
      evidence you run the business
- [ ] Have the **trade licence** ready — Asia Link Internet Content Provider LLC
- [ ] Postcard verification can take 2–3 weeks and often does not reach UAE
      office addresses reliably. Prefer video if offered.
- [ ] **Do not** mark the profile as verified anywhere in our records until
      Google says so

### After verification

- [ ] Check the public listing shows the same name, phone and website as
      `qevik.ai` — inconsistency here is the single most common local SEO fault
- [ ] Add the Business Profile URL to the website footer
- [ ] Turn **off** messaging unless you will answer it — an unanswered Google
      message is worse than no channel
- [ ] Add `LocalBusiness` structured data with the verified details once the
      listing is live, and tell me so I can update the site's JSON-LD to match
- [ ] Set a reminder to post something monthly; dormant profiles rank worse

---

## What I need from you to go further

| Item | Why | Blocking? |
|---|---|---|
| Search Console TXT record added | Only way Google learns the site exists | Yes, for indexing |
| Decision: service-area or address | Changes the listing irreversibly | Yes, for GBP |
| Trade licence to hand | Required at verification | Yes, for GBP |
| A larger square logo | 180px is below Google's 720px minimum | No — I can render one |

Nothing on this list can be automated from here without Google account access,
and none of it should be: a Business Profile created by software on someone's
behalf is exactly the kind of listing Google suspends.
