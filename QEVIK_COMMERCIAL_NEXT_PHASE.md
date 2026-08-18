# QEVIK — Commercial Demo, Lead Intelligence & qevik.ai Plan

## Objective

Stop expanding Qevik indiscriminately. The next phase is commercial validation.

The current 20 Dubai dental demos prove that Qevik can research real businesses, generate individualized sites, test them, deploy them and verify them. However, some existing clinic websites are already better than the generated demos.

Therefore the next product goal is:

> Research the prospect's existing website and public business presence, identify evidence-backed weaknesses and opportunities, generate a materially better demo, make the important customer-facing functions genuinely work, preserve all research and opportunity data, and prepare the prospect for human-approved outreach.

Do not claim any capability works unless it is tested end-to-end.

---

# 1. Upgrade the demo — functionality, not just appearance

The demo must compete with the prospect's existing website.

At minimum, investigate and implement where appropriate:

- Call Now
- WhatsApp
- Book Appointment
- real appointment/request form
- Google Maps / directions
- opening hours
- services
- doctor/team section when verified
- insurance information when verified
- FAQ
- mobile sticky CTA
- English/Arabic where appropriate
- local SEO/schema
- accessibility
- performance optimization
- contact form
- clear conversion paths

## Call Now

- Use a correctly normalized `tel:` URI.
- Test on desktop and mobile.
- Test Android behavior.
- Do not use malformed phone numbers or spaces that break dialing.
- The number must match the verified business source.

## WhatsApp

- Use the verified business number.
- Test the link.
- Do not invent a WhatsApp number.
- If WhatsApp is unavailable, do not fabricate it.

## Book Appointment

Never create a fake booking experience.

Acceptable states:

1. Existing booking URL found and verified → link to it.
2. Existing provider found but integration is not implemented → record the provider and limitation.
3. No booking mechanism → a real Qevik appointment/request workflow may be implemented.

If a Qevik form exists, test:

- validation
- submission
- persistence
- notification
- success state
- failure state
- mobile UX
- spam protection

Never claim an appointment was booked unless a real booking was created.

---

# 2. Audit the existing website first

For every one of the 20 clinics, research the current website before generating or updating the demo.

Capture:

- business name
- phone
- WhatsApp if available
- address
- district
- opening hours
- Google/Places URL
- website URL
- booking URL
- email
- social profiles
- services
- specialties
- doctors/providers if publicly listed
- languages
- insurance information if publicly listed
- emergency information if publicly listed

Audit whether the existing site has:

- Home
- About
- Services
- Doctors/team
- Contact
- Booking
- Contact form
- WhatsApp
- click-to-call
- Google Maps
- opening hours
- FAQ
- blog/content
- gallery
- reviews/testimonials
- insurance information
- pricing
- Arabic/English
- mobile navigation
- SEO metadata
- structured data
- strong CTAs

Distinguish:

- Present
- Not found
- Could not verify

Never convert "could not verify" into "missing."

---

# 3. Store strengths, weaknesses and opportunities

Every prospect needs a durable website audit.

Example:

```text
Category: Conversion
Severity: High
Observed: Appointment CTA sends users to a generic contact page.
Evidence: source URL / screenshot
Opportunity: Direct appointment CTA on every major section.
Confidence: High
```

Possible categories:

- Conversion
- Mobile UX
- Performance
- Navigation
- Content
- SEO
- Local SEO
- Trust
- Booking
- Contact
- WhatsApp
- Accessibility
- Multilingual
- Technical
- Structured data
- Social proof

Do not invent weaknesses to make Qevik look better.

---

# 4. Create a prospect opportunity score

Score each prospect on:

| Dimension | Score |
|---|---:|
| Existing website quality | 1–10 |
| Mobile UX | 1–10 |
| Conversion UX | 1–10 |
| Booking experience | 1–10 |
| Contact accessibility | 1–10 |
| Local SEO | 1–10 |
| Content quality | 1–10 |
| Trust/social proof | 1–10 |
| Performance | 1–10 |
| Qevik improvement potential | 1–10 |

Create an overall opportunity score.

The highest score should represent the strongest commercial opportunity, not simply the oldest-looking website.

---

# 5. Preserve all 20 businesses permanently

Do not throw away the research after generating a site.

Each prospect record should retain:

## Identity

- name
- phone
- address
- website
- Google/Places identifiers
- map URL

## Research

- sources
- pages visited
- services
- booking mechanism
- contact methods
- social links
- languages
- opening hours

## Website audit

- strengths
- weaknesses
- missing features
- mobile findings
- conversion findings
- technical findings
- SEO findings

## Qevik opportunity

- opportunity score
- recommended pitch
- recommended improvements
- demo URL
- screenshots
- comparison
- reason to contact

## Outreach

- contact status
- email
- phone
- WhatsApp
- email sent
- call attempted
- response
- meeting
- proposal
- won/lost
- notes

Keep historical snapshots so a future audit can be compared with the original state.

---

# 6. Current website vs Qevik comparison

For every prospect create a factual comparison.

Example:

```text
CURRENT WEBSITE
Booking: yes
WhatsApp: yes
Mobile CTA: weak
Services: strong
Structured data: not verified
Arabic: no
Performance: moderate

QEVIK
Direct call CTA: yes
Booking CTA: yes
WhatsApp: yes
Service navigation: yes
Local schema: yes
Mobile-first layout: yes
Research-backed content: yes
```

The comparison must be evidence-based.

The goal is not to make Qevik appear better artificially. The goal is to identify where it actually wins.

---

# 7. Research-driven content

Use researched information for:

- services
- positioning
- location
- opening hours
- contact details
- specialties
- languages
- booking
- relevant local information

Clearly distinguish:

- sourced facts
- generated marketing copy
- recommendations
- assumptions

Never fabricate:

- dentists
- awards
- years of experience
- testimonials
- certifications
- patient numbers
- medical claims
- pricing
- guarantees

---

# 8. Lead intelligence

Qevik should eventually support:

```text
Prospect
  → Research
  → Website audit
  → Opportunity score
  → Demo
  → Verification
  → Outreach recommendation
  → Email / Call / WhatsApp
  → Response
  → Meeting
  → Proposal
  → Sale
```

For each prospect generate an outreach brief:

```text
PROSPECT:
ABC Dental Clinic

WHY CONTACT:
Evidence-backed reason.

STRONGEST WEAKNESS:
Specific observed issue.

QEVIK IMPROVEMENT:
Specific improvement.

DEMO:
URL

BEST PITCH:
Short personalized pitch.

DO NOT SAY:
Anything unsupported by evidence.
```

---

# 9. First sales experiment

Do not automate outreach yet.

Select the five strongest prospects from the 20.

For each:

1. Review the real website.
2. Review the Qevik demo.
3. Review the audit.
4. Review the strongest opportunity.
5. Prepare a personalized pitch.
6. Human sends the email.
7. Human calls where appropriate.
8. Record the outcome.

Track:

```text
Prospect
→ Contacted
→ Replied
→ Interested
→ Demo viewed
→ Meeting
→ Proposal
→ Paid
```

The first commercial milestone is **not another engineering milestone**.

It is:

> Can a real business owner see a meaningful improvement and agree to a conversation or pay for it?

---

# 10. Qevik admin access

The operator must be able to log into Qevik without Claude.

Fix the current login/access problem.

Requirements:

- document the exact admin URL
- provide a safe initial credential retrieval/reset procedure
- never print passwords into logs
- never commit credentials
- provide password rotation
- verify login externally
- verify logout
- verify session expiry
- verify rate limiting
- verify access to jobs and approvals

If the admin password exists in `/opt/qevik/atlas.env`, do not paste it into chat. Provide a secure rotation/retrieval procedure instead.

---

# 11. qevik.ai and Cloudflare

Prepare the real domain:

`qevik.ai`

Before changing DNS, inspect and report the current configuration.

Inventory:

- DNS records
- A/AAAA
- CNAME
- proxied vs DNS-only
- SSL/TLS
- origin IP
- subdomains
- SPF
- DKIM
- DMARC
- redirects
- firewall rules
- certificates
- Workers/Pages/Tunnels if present

Do not delete or overwrite existing Cloudflare records blindly.

Propose the target architecture first.

A possible structure is:

```text
qevik.ai
www.qevik.ai
app.qevik.ai
api.qevik.ai
sites.qevik.ai
```

Verify whether this is actually appropriate before implementing it.

---

# 12. HTTPS and production routing

The self-signed certificate is not acceptable for customer-facing use.

After DNS is correct:

- obtain a trusted certificate
- verify HTTPS
- verify HTTP → HTTPS
- verify control UI
- verify API routing
- verify generated sites
- verify mobile browser behavior
- verify no redirect to a closed port
- verify external access

Do not call the system production-ready until external HTTPS verification succeeds.

Keep the unauthenticated control API private.

---

# 13. Future booking architecture

Do not hard-code one provider.

Create an abstraction such as:

```text
AppointmentProvider
  ├── ExistingWebsiteBooking
  ├── Calendly
  ├── Google Calendar
  ├── CustomQevikBooking
  └── Future providers
```

Track:

- provider
- booking URL
- status
- prospect
- appointment request
- timestamp
- notification status

Only implement real providers when there is a demonstrated customer need.

---

# 14. ElevenLabs + Twilio

Do not integrate them immediately.

Prepare clean provider interfaces for future:

```text
OutreachProvider
  ├── EmailProvider
  ├── WhatsAppProvider
  ├── TwilioVoiceProvider
  └── ElevenLabsVoiceProvider
```

Potential future flow:

```text
Prospect
→ research
→ demo
→ approved outreach
→ AI/human call
→ meeting
→ proposal
→ payment
→ deployment
```

Do not make autonomous sales calls until compliance, consent, approval and outcome tracking are implemented and tested.

---

# 15. Do NOT build these yet

Do not start:

- Video Factory
- Game Factory
- publishing adapters
- large analytics systems
- thousands of demos
- unrelated platform capabilities

until there is a commercial signal.

The immediate objective is:

> Make Qevik capable of producing a demo that is demonstrably better than the prospect's existing website, explain exactly why it is better, and turn that improvement into a sales conversation.

---

# 16. Exact instruction for the next Claude session

> **Do not build another generic platform capability. Work on the commercial demo and lead-intelligence layer.**
>
> 1. Audit the current generated template against the best of the 20 real dental prospects.
> 2. Audit all 20 existing websites.
> 3. Record strengths, weaknesses, missing features and evidence.
> 4. Persist the complete research and audit data.
> 5. Add an opportunity score.
> 6. Produce a current-website-vs-Qevik comparison for every prospect.
> 7. Upgrade the demo around the highest-value conversion features.
> 8. Make Call Now, WhatsApp, booking, maps and forms genuinely functional where applicable.
> 9. Do not fake booking, submissions or integrations.
> 10. Never fabricate business facts, doctors, awards, testimonials, credentials, prices or medical claims.
> 11. Create an outreach brief for every prospect.
> 12. Rank the five strongest prospects for initial outreach.
> 13. Fix Qevik admin login so the operator can actually log in externally.
> 14. Inspect the current Cloudflare/qevik.ai configuration before making changes.
> 15. Report a proposed domain architecture and then implement it safely.
> 16. Establish trusted HTTPS and verify externally.
> 17. Do not integrate ElevenLabs or Twilio yet; prepare provider interfaces only.
> 18. Do not start Projects, Video Factory, Game Factory, publishing adapters or unrelated infrastructure.
>
> At the end report:
> - what genuinely works
> - what was tested externally
> - bugs found
> - remaining blockers
> - five best prospects
> - each prospect's strongest weakness
> - each prospect's strongest Qevik opportunity
> - recommended pitch
> - demo URL
> - exact next action required from me
>
> Do not report anything as operational unless it was actually exercised and verified.

---

# 17. Definition of success

This phase is complete when:

- Qevik researches a real business.
- Qevik audits its existing website.
- Weaknesses are evidence-backed.
- Qevik generates a materially better demo.
- Call works.
- WhatsApp works where applicable.
- Booking works or its limitation is explicitly documented.
- Maps works.
- The site works on mobile.
- Business data is accurate.
- Research/provenance is stored.
- Opportunity score exists.
- Outreach brief exists.
- The operator can log into Qevik.
- `qevik.ai` has a verified production architecture.
- HTTPS is trusted.
- Five prospects are ready for human outreach.

## Ultimate test

The most important success criterion is:

> **Can a real business owner compare their current website with the Qevik version, immediately understand the improvement, and agree to a conversation or pay for it?**

That is the next milestone. Not another architecture milestone.
