# Google Search Console and Business Profile — remaining manual actions

**Status: nothing claimed, nothing verified.** Qevik is not verified in Search
Console and has no Business Profile. Both require actions only Ayoub can take.

## Search Console

The site is technically ready. Measured 2026-08-21:

| Check | State |
|---|---|
| `https://qevik.ai/sitemap.xml` | 200, lists all 23 routes |
| `https://qevik.ai/robots.txt` | 200, allows crawling, points at the sitemap |
| `X-Robots-Tag` on qevik.ai | absent — the site is indexable |
| `X-Robots-Tag` on `/demo-*` | `noindex, nofollow` — clinic demos stay out of the index |
| English ↔ Arabic hreflang | reciprocal, canonicals self-referencing |
| Verification TXT | **not present** |

**Remaining actions, in order:**

1. Search Console → Add property → **Domain** (not URL-prefix). A domain
   property covers `https://`, `http://`, `www` and every subdomain including
   `sites.qevik.ai` in one place.
2. Add the TXT record it gives you in Cloudflare: `Type TXT, Name @, Content
   google-site-verification=<value>`. This is a *different* value from the
   Workspace verification record in `70_EMAIL_INFRASTRUCTURE.md`; both can
   coexist as separate TXT records on `@`.
3. Verify, then submit `https://qevik.ai/sitemap.xml`.
4. Request indexing for `/`, `/work/`, `/services/`, `/ar/`.
5. In two weeks, read the Arabic pages' impressions separately. That is the only
   real evidence on whether the bilingual work earns anything, and it is the
   claim Qevik makes to every prospect.

**Do not** submit the clinic demos. They carry real clinic names and none of
those businesses are customers; the `noindex` header is deliberate and Search
Console would fight it.

## Business Profile — a decision, not a task

A Google Business Profile requires either a location customers can visit, or a
declared service area with the address hidden. Getting this wrong is not a
cosmetic error: fabricating a storefront is grounds for suspension, and a
suspended profile is hard to recover.

**The question only Ayoub can answer: is Office 301, Al Othman Building a place
a customer could turn up to and be received?** Signage, reception, someone
there during stated hours.

- **If yes** — a standard profile with the address is worth having.
- **If no** — configure it as a **service-area business**: address entered for
  verification, then hidden, with Dubai as the service area. This is the normal
  configuration for an agency and is not a workaround.

**The naming problem, which is the real blocker.** Google requires the profile
name to be the business's real-world name as customers encounter it — and
verification is usually against the trade licence. The licensed entity is *Asia
Link Internet Content Provider LLC*; *Qevik* is a product brand with no separate
licence. Creating a profile named "Qevik" invites a name-mismatch suspension.

**Recommendation: do not create a Business Profile yet.** For a B2B agency
selling by WhatsApp and referral it contributes very little, and the first
commercial test does not depend on it. Revisit if and when Qevik becomes a
registered trade name on the licence.

**Never invent** opening hours, a reception, signage, photographs of premises,
services not offered, or reviews. All of these are checkable and all of them are
grounds for removal.
