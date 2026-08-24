# QEVIK — FINAL PRE-SALES / 24-HOUR EXECUTION PLAN

## Objective

The immediate objective is **commercial validation**, not additional architecture.

Qevik already has LLM planning, research → decision → generation → testing → repair → deployment → verification, durable jobs, authentication, approvals, business/audit persistence, 20 audited dental prospects, 20 bilingual demos, `qevik.ai`, `app.qevik.ai`, `sites.qevik.ai`, Cloudflare, noindex protection, and outbound drafts with sending disabled.

The next 24 hours should answer:

> Can Qevik produce a commercially credible website/app proposal quickly enough, and specifically enough, that a real business owner wants to talk?

Do not optimize the engineering system before answering that.

---

## 1. Protect the current system

Before changes:

- Back up relevant production state.
- Continue using `atlas_businesses`, `atlas_business_events`, `atlas_outreach_messages`, and existing approvals.
- Do not create another customer/prospect table.
- Preserve all audit evidence.
- Do not send outbound messages automatically.
- Do not connect SMTP, WhatsApp API, Twilio, ElevenLabs, Meta, publishing APIs, or payment APIs unless explicitly authorized.
- Do not implement fake booking.
- Do not fabricate clients, testimonials, awards, doctors, reviews, years of experience, booking availability, features, or certifications.
- Do not publish unsolicited prospect demos as portfolio/client work.
- Keep prospect demos `noindex`.
- Run the full test suite before and after significant changes.

Legal sender identity:

**Ayoub Soleimani**  
**Asia Link Internet Content Provider LLC**  
Office 301, Al Othman Building  
Deiram, Dubai, UAE  
+971 50 102 9104

Qevik is a brand/product, not the legal company. Never describe Qevik as a licensed company or invent a Qevik trade licence.

---

## 2. Broaden Qevik's positioning

The public website must NOT look like a dental-only agency.

Position Qevik as:

> **Websites and digital products built from a business objective.**

Target categories:

- dental and medical clinics
- restaurants
- cafés and coffee shops
- bakeries
- salons and beauty
- gyms and fitness
- real estate
- cleaning companies
- car detailing and automotive
- car rental
- hotels and tourism
- professional services
- law/accounting/consulting
- construction/interior
- local retailers
- e-commerce
- education/training
- other local businesses
- internal dashboards
- responsive web apps
- Android/iOS/web app projects

Do not claim completed client work unless it actually exists.

---

## 3. Create a multi-industry showcase

Create clearly labelled **Qevik sample/demo projects**, not fake clients.

At minimum:

### Restaurant sample

- hero
- menu/categories
- featured dishes
- location/map
- hours
- call
- verified WhatsApp where applicable
- reservation/request CTA
- gallery
- Arabic/English
- mobile-first design
- Restaurant structured data where appropriate

Reservation must remain a request/integration placeholder unless a real provider is connected.

### Café / coffee shop sample

- menu
- signature drinks
- location
- hours
- directions
- call/verified WhatsApp
- offers
- gallery
- bilingual layout
- local SEO

### Service-business sample

Examples: salon, cleaning, car detailing, gym, repair.

Include:

- services
- service area
- enquiry/request form
- call
- WhatsApp when valid
- FAQ
- local SEO

### Professional-business sample

Examples: real estate, accounting, consulting.

Include:

- service pages
- service area
- lead form
- FAQ
- contact
- map where appropriate
- bilingual support

### App/dashboard sample

Create a polished frontend demonstration such as:

- restaurant management dashboard
- booking-management dashboard
- small-business CRM
- sales-lead dashboard
- inventory dashboard

It is a demonstration unless the backend is genuinely implemented. Do not claim production capability that does not exist.

---

## 4. Make the website factory modular

Support composable modules rather than one dental template.

### Conversion

- click-to-call
- WhatsApp only when verified
- enquiry form
- sticky mobile CTA
- directions
- contact form
- lead capture
- quote/request form

### Local business

- Google Maps
- opening hours
- address
- service areas
- appropriate structured data
- canonical
- hreflang
- sitemap
- robots
- OpenGraph

### Restaurant

- menu
- categories
- dietary information
- reservation request
- gallery
- location
- hours

### Professional services

- service pages
- lead form
- FAQ
- service area
- contact

Do not add fake payment/order/booking functionality.

---

## 5. Run a new business-discovery job

YES — run another discovery job now.

Do not blindly collect hundreds of businesses. Find businesses where:

1. an obvious website weakness exists;
2. Qevik can actually fix it;
3. the business is reachable;
4. the improvement can be demonstrated;
5. the business has commercial value.

Start with Dubai.

Priority:

- restaurants
- cafés
- coffee shops
- salons/beauty
- gyms/fitness
- car detailing
- auto repair
- real estate
- cleaning
- professional services

Secondary:

- bakeries
- boutique hotels
- tourism
- training
- interior design
- contractors
- other local services

Do not restrict discovery to businesses without websites. A poor existing website can be a stronger replacement/upgrade opportunity.

---

## 6. Store evidence in the existing architecture

For each discovered business preserve:

- immutable business ID
- name
- website
- phone
- address
- category
- Google/place identifier where available
- source URLs
- discovery timestamp
- website status
- HTTPS status
- mobile usability
- Arabic/English presence
- click-to-call
- WhatsApp
- maps/directions
- contact form
- booking/reservation
- opening hours
- menu/service pages
- structured data
- title/H1
- performance observations
- strongest confirmed weakness
- Qevik opportunity
- NOT_VERIFIED items
- DO_NOT_SAY items

Use exactly:

- `CONFIRMED_PRESENT`
- `CONFIRMED_ABSENT`
- `NOT_VERIFIED`

Never convert "not observed" into "absent".

No new prospect/customer table.

---

## 7. Commercial scoring

Rank prospects using:

- severity of weakness
- customer impact
- whether Qevik can fix it now
- visibility of improvement
- contactability
- business value
- existing website quality
- replacement/upgrade likelihood
- ability to demonstrate the improvement

Do not let "no website" dominate the score automatically.

---

## 8. Generate demos for the strongest prospects

Initially generate 5 strong demos.

Each must:

- use verified business information
- preserve real name/phone/address where verified
- avoid fabricated claims
- avoid fake reviews
- avoid fake booking
- be clearly a demo/spec
- remain `noindex`
- have correct canonical handling
- support English + Arabic where appropriate
- pass mobile and desktop browser verification

Record demo relationships in the existing business timeline.

---

## 9. Current-vs-Qevik comparison

For each top prospect produce:

1. Clinic/business name
2. Existing website
3. Strongest confirmed weakness
4. Qevik improvement
5. Other things already done well
6. Exact evidence
7. DO_NOT_SAY
8. Outreach angle
9. Recommended first contact
10. Demo URL

The comparison must be fair and evidence-backed.

Never say "your website is bad" when a specific observation can be made.

---

## 10. Outreach preparation

Do NOT send automatically.

### WhatsApp

Short:

- identify yourself
- identify the specific evidence-backed reason
- mention the prepared sample
- provide demo
- ask whether they want the comparison
- no hard sell

### Email

Prepare:

- subject
- personal opening
- confirmed observation
- what Qevik changed
- demo URL
- concise CTA
- legal sender block

No invented recipient email addresses.

No sending until explicitly approved.

---

## 11. Google setup

Prepare the technical checklist for:

### Search Console

- Domain property for `qevik.ai`
- DNS TXT verification
- sitemap submission
- indexing requests
- canonical/hreflang inspection
- verify prospect demos remain `noindex`

User-owned Google verification actions remain manual.

### Google Business Profile

Before creation/verification, determine whether the actual office is customer-facing.

If it is not, use a service-area configuration where permitted.

Never claim Google verification until it happens.

Do not use an appointment URL pointing to the placeholder request form.

---

## 12. Dedicated Google account

Prepare a dedicated Google account for Qevik operations for:

- Search Console
- Business Profile
- Google Cloud
- Maps/Places
- Analytics later

Use the real legal entity information where Google requests legal/business information.

Never store Google passwords in Git or source code.

---

## 13. Email under qevik.ai

Do this after the public website is ready and before serious outreach.

Prepare:

- `hello@qevik.ai`
- `sales@qevik.ai`

Configure:

- SPF
- DKIM
- DMARC
- mailbox
- forwarding if needed
- signature

The legal footer remains:

**Asia Link Internet Content Provider LLC**

Do not connect automated sending until manual sales validation proves the offer.

---

## 14. Meta / WhatsApp

Do NOT implement yet.

Only proceed after the sales test demonstrates that WhatsApp automation is useful.

Later:

- Meta Business
- WhatsApp Business Platform
- dedicated business number
- verification
- webhooks
- templates where required
- opt-in/compliance
- approval boundary
- message logging

Do not automate personal WhatsApp or WhatsApp Web.

Do not send bulk unsolicited messages.

---

## 15. Google Maps / Places

When needed, prepare:

- Google Cloud project
- current Places APIs
- restricted credentials
- billing
- application restrictions
- API restrictions

Follow Google's terms and preserve source evidence.

Never expose API keys.

---

## 16. Cloudflare

Current decision:

**Cloudflare token remains disabled.**

Do not request/install one without a concrete automation requirement.

If required later:

- qevik.ai only
- Zone Read
- DNS Edit
- IP restriction
- 90-day expiry
- no account-wide permissions
- no Zone Settings Edit unless concretely required
- no Cache Purge unless measured necessary

---

## 17. Security

Keep:

- rotated admin credential
- secrets out of Git
- `atlas.env` 0600
- hashed sessions
- rate limiting
- deny-by-default
- approval fingerprints
- production/test DB isolation
- prospect noindex
- public :8443 closed
- SSH fallback
- HTTPS

Never print credentials in logs, reports, screenshots, artifacts, or chat.

---

## 18. Do NOT build these today

Do not start:

- Projects
- Inbox
- Video Factory
- Game Factory
- publishing adapters
- analytics/revenue systems
- autonomous sales
- automated mass email
- automated WhatsApp
- ElevenLabs
- Twilio
- payment integration
- complex CRM UI
- mobile publishing
- Play Store integration
- App Store integration
- unnecessary infrastructure

unless a real commercial result requires one.

---

## 19. One-day execution order

### Step 1 — Safety

- backup
- full test
- verify production DB
- verify admin login
- verify public URLs

### Step 2 — Multi-industry discovery

Run a serious Dubai discovery job.

Initial target:

- 20 restaurants/cafés
- 10 salons/beauty
- 10 gyms/fitness
- 10 automotive
- 10 professional services
- 10 other local businesses

Do not automatically build all demos.

Rank them first.

### Step 3 — Rank the strongest 10

Produce evidence-backed commercial briefs.

### Step 4 — Build 5 strong demos

Only where the improvement is obvious and defensible.

### Step 5 — Build multi-industry public samples

At minimum:

- restaurant
- café
- service business
- professional business
- app/dashboard

### Step 6 — Prepare outreach

Draft WhatsApp/email.

No sending.

### Step 7 — Prepare Google setup

Search Console + Business Profile checklist.

### Step 8 — Prepare email setup

`hello@qevik.ai` and `sales@qevik.ai`.

### Step 9 — STOP

Do not start another engineering phase.

---

## 20. Success criteria

The day is successful if we finish with:

- original dental prospects preserved
- additional multi-industry prospects discovered
- top prospects ranked with evidence
- 5+ strong demos
- Qevik positioned for multiple industries
- restaurant sample
- café sample
- service-business sample
- professional-business sample
- app/dashboard sample
- Google setup ready
- email setup ready
- outreach drafts ready
- zero automatic sends
- zero fabricated claims
- zero production DB contamination
- tests passing

The real success criterion is:

> **At least one real business owner responds positively enough to start a commercial conversation.**

Until that happens, prefer sales experiments over infrastructure.

---

## Final rule

For every proposed implementation ask:

**Will this materially increase the probability of getting the first paying Qevik customer?**

If yes, do it.

If no, defer it.

Do not confuse more features, tests, infrastructure, integrations, or automation with market validation.

Qevik already has enough machinery to test the market.

Now make the output broad enough to sell beyond dental, specific enough to demonstrate value, and disciplined enough that every claim made to a real business can be defended with evidence.
