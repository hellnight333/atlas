# Doc 11 — Gap Analysis

What `11_QEVIK_AUTONOMOUS_MEDIA_GROWTH_BUSINESS_ENGINE.md` is missing before it
describes a business rather than a production system.

Doc 11 is the strongest specification in the set. Its production loop is right,
its insistence on provenance and verification is right, and §45's refusal to
claim a publication without platform evidence is the kind of rule that prevents
a year of quiet lying. **Nothing below argues with what it contains.** This is
about what sits outside its frame.

The gaps fall into three tiers: things that stop the business existing at all,
things that separate a business from an activity, and things that are cheaper to
add now than to retrofit.

> **On the numbers.** Every threshold quoted here is a platform policy that
> changes without notice — the same caution doc 11 §36 applies to itself. They
> are given so the *shape* of the constraint is clear, and every one must be
> re-verified against the official source before it is coded. Several are
> already different from when they were first published.

---

## Tier 1 — the business cannot exist without these

### 1.1 There is no legal entity or developer-account layer

§31 models credentials. It does not model the **account behind the
credentials**, and for app stores that account is a legal and financial object
with weeks of lead time:

| | Google Play | Apple |
|---|---|---|
| Cost | one-time registration fee | annual developer programme fee |
| Identity | verification required; organisations need a D-U-N-S number | organisations need a D-U-N-S number |
| Payout | payments profile + bank account | banking + tax forms in App Store Connect |
| Tax | tax info required before payout | same |

YouTube adds its own: **US tax information must be on file or Google withholds
up to 30% of US-derived earnings.** A UAE entity claiming treaty benefits files
a W-8BEN-E. This is not a detail — it is a third of the revenue from the largest
market, decided by a form.

None of this is code. All of it is lead time, and it blocks §15, §16 and §9
completely. It should be modelled as a `LegalEntity` with its own readiness
state, and every portfolio item should reference one.

**Why it matters most:** doc 11 can be fully implemented and still publish
nothing, because the blocker is a D-U-N-S application, not a missing adapter.

### 1.2 API quotas are absent, and they cap the entire media factory

This is the single largest practical omission.

**The YouTube Data API grants a default quota of 10,000 units per day, and
Google's own quota calculator prices `videos.insert` at 1,600 units.** That is
**about six uploads per day across the entire project** — not a rate limit that
can be tuned, since raising it requires an audited quota-extension request that
takes weeks and is frequently refused.

*Checked, and worth re-checking:* Google's published calculator still shows
1,600, but at least one third-party source claims the insert cost was quietly
reduced by an order of magnitude. If true the ceiling is far higher; if false,
building for the optimistic number produces a factory that stops at six uploads
with no explanation. **Measure the actual consumption against the quota page on
the first day of real uploads and treat the ledger's numbers as observed rather
than documented.** This is exactly the case doc 11 §36 means when it says not to
hard-code platform assumptions.

Doc 11 §28 specifies a daily production loop and §41 asks for twelve of
something per day. Neither is reachable under the default quota, and the
document contains no concept of quota at all.

The same shape appears everywhere:

- **Instagram Content Publishing** — a rolling 24-hour publishing limit, a
  Business/Creator account linked to a Facebook Page, and App Review before any
  of it works.
- **TikTok** — direct posting requires an audited application; unaudited apps
  can only draft.
- **Brave search** (now built) — one query per second on the free tier.
- **Places** — billed per request and per field tier.

**What is needed:** a `QuotaLedger` that every connector debits before acting,
that refuses rather than fails, and that makes the daily production plan a
function of available quota instead of an aspiration. The plan for a day should
be computed from what the accounts can actually spend.

### 1.3 A high-volume game factory is aimed directly at the anti-spam rules

Apple's App Review guideline **4.3 (spam)** rejects apps that are minor
variations of one another or of apps already in the store. Google's **Spam and
Minimum Functionality** policy is equivalent. Both are enforced precisely
against the pattern doc 11 §13 describes.

Two consequences the document does not state:

1. **Repeated rejections escalate to account termination**, not just to a
   rejected build. The rejection text developers actually receive is *"this app
   duplicates the content and functionality of other apps submitted by you"* —
   which is a description of a batch factory.
2. **Google terminates related accounts.** One portfolio's spam judgement can
   take down the developer account holding the profitable ones.

§35 treats originality as an internal quality concern. It is really an
**existential platform-policy risk with account-level blast radius**, and it
should be modelled that way: a rejection rate per account, a circuit breaker
that halts submissions when it rises, and a rule that a batch is never submitted
faster than review outcomes come back.

### 1.4 Nothing survives an account termination

Every section assumes accounts keep working. Nothing says what happens when a
channel is terminated, an app is suspended, or a developer account is closed.
For a portfolio whose entire value sits inside three platform accounts, this is
the largest single risk in the business and it is unmodelled.

Needs: account health as a first-class signal, an appeal workflow, **originals
escrowed off-platform** so a terminated channel is a setback rather than a
total loss, and an isolation rule so one factory's risk cannot reach another
factory's account.

### 1.5 The 12-tester rule changes the throughput model, not just the state machine

§15 correctly records that new personal Play accounts must run closed testing
with a minimum number of testers for a continuous period before requesting
production access. It draws the state machine but not the conclusion:

**The earliest a new account can reach production is a fortnight after its first
build, and it needs real opted-in testers who are actual Google accounts.**

"Make 12 games today" therefore cannot mean twelve *published* games today under
any implementation. The throughput model, the daily report and the acceptance
tests all need to reflect a pipeline whose exit is weeks from its entrance —
otherwise the dashboard will show failure every day while working correctly.

Sourcing twelve genuine testers is itself an unsolved operational problem worth
naming.

---

## Tier 2 — the difference between a business and an activity

### 2.1 Revenue is reported, never reconciled

§25's ledger records what platforms *say*. A business needs to know what
*arrived*:

- payout thresholds — AdSense holds earnings until a minimum balance is reached
- payout schedules, and the month-plus lag between earning and receipt
- FX conversion, and who absorbs the spread
- platform fee versus actual net receipt
- **reconciliation against the bank statement**

Today "what made money this week" is answerable. "Did we get paid, and does it
match what they promised" is not. Add a `Payout` record and reconcile it against
`RevenueEvent`; the difference between the two is where fraud, error and
misunderstanding live.

### 2.2 There is no invoicing

§22 has an `invoice` field. Actual invoicing is:

- **sequential, gapless numbering** — a legal requirement in most jurisdictions
- VAT treatment and TRN presentation; place-of-supply rules for foreign sponsors
- payment terms, due dates, credit notes
- dunning — chasing what is unpaid, which is the collections half of revenue

For a UAE entity there is a further trigger: **VAT registration becomes
mandatory above a turnover threshold**, and corporate tax now applies above a
profit threshold. The system knows the turnover before the accountant does, and
should say so as it approaches.

### 2.3 Contracts have no lifecycle

A "contract artifact" is stored. Missing: templates, counterparty verification,
signature, governing law and jurisdiction, and — most usefully — the
**deliverables-versus-delivered check** that determines whether an invoice is
even valid. A sponsorship pipeline that reaches `CONTRACTED` without knowing
what was promised cannot tell whether it was honoured.

### 2.4 Nothing decides what to charge

The CRM records an offer. No component produces one. An agent negotiating
without a rate card will accept whatever it is given, and a sponsor's opening
number is not a valuation.

Needs a rate card derived from real audience data and CPM benchmarks, with a
floor below which the response is a decline rather than a negotiation.

### 2.5 Music and IP rights are missing — and for a kids music channel that is the core asset

The first vertical is built on original songs. The document has no rights model
at all, and this is the area where AI production is least settled:

- **Purely AI-generated work is, on the current US Copyright Office position,
  not copyrightable.** Uncopyrightable music cannot be exclusively licensed, and
  its protection under Content ID is doubtful.
- Content ID claims against your own uploads — who disputes, and on what basis
- the licence terms of every generation model used, which differ on commercial
  use and on ownership of output
- whether a track can be registered with a distributor or PRO at all

A `RightsRecord` per asset — model, licence, commercial-use terms, Content ID
state, registrability — is cheap now and archaeology after a hundred episodes.

### 2.6 No brand clearance before a brand is built

"A funny rabbit wearing a hat" is one search away from Peter Rabbit, Miffy and
several live franchises. §36 lists trademarks as a *publishing* check; clearance
belongs **before** the style bible, the character and fifty episodes exist.

A trademark and likeness search is now a `web.search` call away, which makes its
absence harder to justify than it was when doc 11 was written.

### 2.7 Kids content is the strictest possible regime to start in

Worth stating plainly as a strategy risk, not a gap in the spec. Choosing
children's content as vertical #1 means beginning under:

- COPPA and FTC enforcement, with meaningful penalties per violation
- YouTube made-for-kids: **no comments, no personalised ads, materially lower
  RPM** — §7 notes the monetisation effect but not that it makes vertical #1 the
  worst-paying one
- Play's Families programme and Apple's Kids Category, each with their own ads,
  analytics and parental-gate rules

It is a defensible choice — the content is cheap and evergreen. It should be
made with the trade-off explicit rather than by default.

---

## Tier 3 — cheaper now than later

**3.1 Data protection for the prospect database.** §18 stores contact details of
real people. UAE PDPL and GDPR both require a lawful basis, retention limits and
a deletion path, and outreach requires opt-out and sender identification. M014's
suppression list is the seed; it needs to become a data-subject-request
workflow.

**3.2 Domain and renewal lifecycle.** A lapsed domain ends a business quietly.
Renewal dates, auto-renew state, transfer locks, expiry alerts.

**3.3 Store listing localisation and ASO.** §15 lists store-listing fields but
nothing about keyword research, localisation, or Play's native store-listing
experiments — which is where install volume actually comes from.

**3.4 Review and rating response.** Store reviews are both a support channel and
a ranking input. §19 mentions app-store feedback; there is no response workflow.

**3.5 Forecasting.** §26 computes contribution margin. A business also needs
cash-flow forecast, break-even per portfolio item, and runway.

**3.6 Segregation of duties.** §37's approval centre assumes one user. Financial
approval in a real company needs roles, limits by value, and an audit trail
showing who approved what.

**3.7 Analytics attribution.** Nothing connects a piece of content to the
revenue it produced. Without it, §27's experiment engine can measure views but
not value.

---

## What this changes about the implementation order

§44 puts durable entities, publishing abstraction, accounts and the Inbox first.
That is correct. Three amendments:

1. **`LegalEntity` and `QuotaLedger` belong in Priority 1.** They are cheap to
   build and both are hard blockers discovered late otherwise. Quota in
   particular changes what the daily plan is allowed to contain.
2. **Start the D-U-N-S and developer-account applications now**, in parallel
   with everything else. They are the longest lead time in the project and no
   amount of engineering shortens them.
3. **Rights and clearance move ahead of the first vertical**, because they
   determine whether the asset built by that vertical is ownable.

Against SHIP_RULE, the ordering is unchanged in spirit: none of this is
architecture for its own sake. Each item either unblocks revenue, prevents its
loss, or stops an account termination that would end the portfolio.

---

## The honest summary

Doc 11 specifies a **production and distribution system** to a high standard.
What it does not yet specify is the **company that owns the output** — the legal
entity, the tax position, the money that arrives, the contracts, the rights, and
the platform accounts whose loss would end it.

The distance between the two is smaller than it looks. Most of Tier 1 is
records, lead time and a circuit breaker rather than new subsystems, and the
existing capability/worker/artifact architecture absorbs all of it without a new
pattern.

But until Tier 1 exists, the honest description of the system is *a very good
content factory that cannot legally publish, cannot exceed six uploads a day,
and would be destroyed by a single account suspension.*
