# What Qevik can sell — 24 August 2026

Each line answers one question: **could Qevik take money for this next week, and
deliver it?** Not "is there code", not "is it on the roadmap". The five-prospect
re-evaluation is the reason this document is written in those terms — Qevik
contacted real businesses about work it had no executor for.

`NOW` means an executor exists, the acceptance condition is met, and the only
missing thing is a customer. `NEXT` names the one dependency. `LATER` is
genuinely blocked. `REJECT` is a decision, not a backlog item.

---

## NOW — sellable this week

### Website build / rebuild — `offer-website`

The only capability that is complete end to end: evidence in, multi-page site
out, every page above the thin-content threshold Qevik sells against, sitemap
and robots in the hashed bundle, QA gate, artefact approval over the published
bytes.

**Recurring?** No. One-off, and pricing it as recurring would be the first
dishonest thing in the stack.

**What stops delivery today:** a publication target. Only a filesystem is
connected, so a customer receives a bundle rather than a live site. That is a
host and a DNS record — see LATER.

### Portfolio / case-study system — `offer-portfolio-system`

Executor exists and was built against real evidence: AHS's thirty-two event
pages carrying a hundred and seventy photographs the homepage links to none of.
It consumes research and invents nothing.

**The strongest thing to sell first**, because the argument is made entirely in
the customer's own data and it can be shown to a *strong* business without
implying anything is wrong with them.

### Editorial hub — `offer-editorial`

Executor exists. Sellable to a business that already publishes and buries it.

### Audit — the public route

`POST /api/public/audit` reads stored research and never crawls on request.
Free, and its commercial function is qualification rather than revenue: it is
the thing that makes an outreach message about a specific confirmed finding
rather than a generic pitch.

---

## NEXT — one dependency each, named

### Arabic experience — `offer-arabic-experience`

Executor now exists. **The dependency is the customer, not us**: Arabic copy
written by a person, because Qevik does not translate. Presented as a task for
them before anything is agreed.

Commercially the most interesting item here: three of the five prospects were
contacted about exactly this. The demand is demonstrated. What was missing was
delivery, and now what is missing is a form for them to type Arabic into.

**Next action:** a customer-facing surface for supplying Arabic — the executor
already accepts it, and nothing collects it.

### Structured enquiry — `offer-enquiry-builder`

Executor exists and works with no server: mailto and WhatsApp links composed on
the visitor's device. **Dependency: an email address or WhatsApp number.**

The posted-form upgrade is costed in `hosted_form_gap()` — host, SMTP
credential, spam handling, a retention decision. Two of those are not code.

### Recurring measurement

The genuine recurring-revenue candidate, and the one thing here that could be
priced monthly without pretending. `measurement/schedule.py` exists and nothing
runs it.

**Dependencies:** a scheduler process, plus a Search Console or Analytics
credential for anything worth measuring. Without a data source, a monthly report
saying `NOT_VERIFIED` for every metric is worse than no subscription.

### AI visibility

Adapter, fake provider, measurement model and the `mention ≠ rank` distinction
are built. **One credential activates it.**

Commercially this is the differentiator — nobody else in this market sells
"are you cited by AI assistants" with an honest position-availability model.
Held back by one key.

---

## LATER — blocked on something that is not code

### Live publication

Host + DNS. Until then a customer gets a bundle, not a site, and the last step of
the website vertical is unproven.

### Marketplaces — Amazon, Noon

Registered as `adapter_ready=False`. Beyond the credentials, the real question is
unanswered: **is Qevik a marketplace agency?** That is a different customer, a
different sales motion and a different support burden from "your website is
missing X". Building the abstractions before answering it is how a roadmap grows
without a business growing.

### Social / video

Same shape, plus a sharper risk: these publish under the customer's name to an
audience, and nothing published can be recalled. No adapter before an approval
gate exists.

### Agency / white-label

Requires a second tenant that is an agency rather than a business, and a pricing
model nobody has decided. The tenancy model supports it; the commercial design
does not exist.

---

## REJECT

### Billing, for now

Plans, credits and quota exist and are enforced in units. Money does not. Adding
Stripe before a price is agreed builds the mechanism for a decision nobody has
made — and the first real invoice should follow a delivered site, not precede
one.

**Not "never".** Rejected as *current* work.

### Media/growth business — docs 11 / 11A

A YouTube operation inside a B2B evidence engine: different customers, different
unit economics, different failure modes, sharing a tenancy model with neither.
Its own gap analysis lists legal entity, developer accounts and IP rights as
Tier 1. None of that is code.

### `offer-one-tap-contact` as a separate capability

Two prospects were pitched it. The theme already renders `tel:` links, so the
fix is inside `offer-website`. Keeping it as a separate offer means selling as
distinct work something already included — which the re-evaluation surfaced and
which is the reason this line exists.

---

## The commercial finding

**Qevik's problem is not capability breadth. It is that nothing is live.**

Three capabilities are complete and sellable today, and none has been delivered
to a paying customer, because there is no host to publish to. Meanwhile the
roadmap contains marketplaces, CRM, social and agency — none of which is blocked
by code either, and all of which would be built before the first thing shipped.

The highest-value next action in this whole document is not a feature. It is a
host and a DNS record, which would take one capability from "complete" to
"delivered".

## Order

1. A publication target — the one thing standing between complete and delivered.
2. A surface for a customer to supply Arabic, where demand is already proven.
3. One measurement credential, so recurring revenue can be honest.
4. Nothing in LATER until one customer has been delivered to.
