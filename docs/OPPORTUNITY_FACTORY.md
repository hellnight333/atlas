# Opportunity Factory (M014)

Finds businesses with a specific, **provable** commercial defect and produces a
proposal built from those findings — approval-gated end to end.

Ranked first in [`BUSINESS_ROADMAP.md`](../BUSINESS_ROADMAP.md) because it compounds
where the other factories are capped, and because every other factory's commercial path
runs through it. Read [`SHIP_RULE.md`](../SHIP_RULE.md) before extending this.

> **FROZEN 2026-08-04.** The architecture below is settled. No further
> architectural change unless implementation against real businesses reveals a
> real-world problem — not because something could be tidier, and not because a
> future factory might want it differently. Both are how a frozen design thaws.
>
> Remaining blockers are external, and all three are Ayoub's to define:
> **niche + geography**, **the initial offer**, **a sending identity**. The first
> two unblock a live scan; only the third unblocks outreach.

---

## Business is the permanent customer record

**One row per company, for the life of the relationship.** Not a Prospect —
"prospect" is a role a company plays inside one pipeline, and naming the
permanent record after one role is how every factory ends up with its own copy
of the same customer: a Prospect here, a Client in the website factory, a Seller
in the Amazon factory, three rows for one company and no way to tell they are
the same.

A `Business` knows who it is and how to reach it, and nothing about what is being
done with it. Opportunities reference `business_id`. Websites, listings, media,
projects, deployments and support history will reference it the same way, each
owning its own state and none duplicating this record.

`Business` deliberately has **no niche**. A company is not "a dental clinic in
the example-uae-services niche" — it is a company, which may be qualified under
several niches over its life. The niche lives on the Opportunity, which is the
thing that has one.

### The business timeline

`atlas_business_events` is **Atlas's permanent memory of a company**, not the
Opportunity Factory's log that others may borrow. One company, one chronological
history, whichever part of Atlas caused the entry:

```python
repo.record_event(BusinessEvent(business_id=b, kind="sent"))
repo.record_event(BusinessEvent(business_id=b, factory="website", kind="deployed"))
repo.record_event(BusinessEvent(business_id=b, factory="amazon", kind="listing_updated"))

repo.timeline(b)                     # the whole history, oldest first
repo.timeline(b, factory="website")  # one factory's slice
```

`kind` is a **plain string namespaced by `factory`**, not a closed enum. An enum
spanning every factory would make this package a dependency of all of them, and
the first factory needing a new kind would have to edit code it does not own.
`opportunity_id` is nullable because a deployment or a support ticket is not an
opportunity, and requiring one would force other factories to invent a fake.

`record_event` is public for exactly this reason: it is the one call another
factory needs in order to contribute.

**The funnel filters on `factory`.** A website factory writing `"sent"` to mean a
deploy notification would otherwise inflate the reply-rate denominator with
nothing looking wrong — a silent corruption, which is the kind worth designing
against.

**No join table was built.** A generic "business owns X" links table with one
real relation would be an abstraction with no user. Each factory adds its own
`business_id` reference when it exists. What matters today is that there is
exactly one Business record with a stable id — that costs nothing and is what
prevents the duplication.

### Standing rule: one customer entity, one immutable id

> Business IDs are immutable. Every factory — website, Amazon, media, SaaS,
> support, billing — references the same Business id. **No factory creates its
> own customer entity.**

`Business` is frozen, so the id cannot be reassigned, and `merged_with` checks
explicitly rather than trusting itself — `model_copy` does not validate. An id
that can change is a history that can be orphaned: timeline entries written
yesterday would point at nothing, and nothing downstream recovers that.

The second half is enforced by `tests/test_one_customer_entity.py`, which reads
the source and fails if any table or model outside the allow-list is named for a
company — `atlas_clients`, `WebsiteClient`, `atlas_amazon_businesses`. The
failure it prevents is slow and quiet: a factory finds it inconvenient to reach
across to `atlas_businesses`, adds its own table, nothing breaks that day, and
months later one company has three rows, a split timeline, and a suppression on
one that does not protect the others.

Matching is on the **head noun** rather than the substring, because a thing is
named by what it ends in. `WebsiteClient` is a client; `ClientSecrets` is a set
of secrets and `ContactHistory` is a history. Substring matching flagged both of
the latter on the first run, and a guard that cries wolf earns an allow-list,
then a longer one, then gets ignored.

## Identity resolution

Autonomous discovery means several sources reporting the same businesses. Google
Maps and a directory will both return the same clinic, spelled differently.
Without resolution the funnel double-counts it, the cooldown protects only one
copy, and someone eventually receives two proposals from the same sender.

**Standing rule: false negatives are acceptable, false positives are not.**
Duplicate records cost a row. Merging two different companies takes one
company's history into another's and attaches its findings to the other's
proposal — a false claim about a stranger's website, which is exactly what the
evidence rule exists to prevent. Once it has happened the timeline above is no
longer a record of anything.

This is not a tuning preference. It decides which way **every** ambiguous case
goes, and `tests/test_business_memory.py` states it as an invariant: each
plausible-looking match Atlas might be tempted by — same name and city, a shared
four-digit extension, a shared hosting platform — is asserted to be *refused*.
There is also a test asserting that two rows for one company is the **correct**
outcome when nothing strong agrees, so the intent survives someone later
"improving" the matcher.

Conservative must not mean silent: refused matches are surfaced through
`find_possible_duplicates` for a human, because a duplicate nobody can see is a
duplicate nobody can fix.

So matching is on **strong keys only** — domain, email, phone. A shared name and
city is a *weak* key: it is surfaced as a possible duplicate for a human and
**never merged automatically**, because two branches of one clinic and two
unrelated companies with a common name are indistinguishable from here.

Domains are normalised to the full host, deliberately **not** to a registrable
domain — reducing `one.wixsite.com` and `two.wixsite.com` to `wixsite.com` would
merge every business on a shared platform into a single company.

Resolution happens twice: `BusinessIndex` dedupes within a run, and
`OpportunityRepository.resolve_business` dedupes against everything ever stored.
The first matters because one run of three sources reports the same clinic three
times before anything is written; the second because a company found this month
and again next month is one company.

## The three invariants

Everything else here is ordinary code. These three are load-bearing, enforced in the type
system and by tests rather than by review:

### 1. A finding cannot exist without evidence

`Finding` requires an `Evidence` object naming **what was observed, where, when and by
what**. There is no constructor path that produces an unevidenced finding — the model
rejects it. A claim about someone's business that Atlas cannot substantiate must be
impossible to create, not merely discouraged.

### 2. Every finding carries a confidence

Not all detectors are equally reliable and not all observations are equally
direct. `Finding.confidence` records how much this particular observation is
worth trusting, and scoring multiplies severity by it — so a high-severity guess
cannot outscore a moderate certainty.

**The number must be justified by how the observation was made**, never invented.
A confidence a detector makes up is worse than none, because it looks like rigour.
The website detector's values are named constants, each with its reason:

| Confidence | Observation | Why not higher |
|---|---|---|
| 0.95 | A transport failure Atlas watched happen | A site can be down for a minute and fine for a year |
| 0.85 | A tag read out of the returned document | SPAs inject `<title>` and meta tags client-side |
| 0.70 | Visible text counted in the served HTML | A React site legitimately ships almost no body text |
| 0.60 | A field missing from someone else's record | Only as good as the source, often a stale directory |
| 0.45 | One timing sample, one network, one place | Enough to raise the question, not to assert it |

`NicheProfile.min_confidence` drops weak findings **before** scoring rather than
merely down-weighting them. Otherwise enough weak signals sum their way past the
qualification bar and arrive at a business owner stated as fact.

Confidence is part of the finding fingerprint, so a re-run that becomes *less*
sure invalidates an approval granted on the confident version.

### 3. A proposal cannot exist without findings

`Proposal` requires at least one `Finding` and every claim in it cites one by id. A
proposal citing nothing is rejected at construction. This is what makes "never generic
templates" a property of the system rather than a hope about prompt quality.

All three are checked in `tests/test_opportunity_invariants.py`,
`tests/test_opportunity_discovery.py` and `tests/test_opportunity_identity.py`,
which fail if any can be bypassed.

---

## Layering

Mirrors the Media Factory's discipline, for the same reason: the source layer must not
learn about the channel it eventually reaches.

```
SOURCE      Business                the permanent customer record. one per company.
            Finding                 one evidenced defect. immutable once observed.
            Opportunity             a scored bundle of findings worth selling against.

OFFER       Proposal                generated from findings. cites them. no channel.
            OutreachMessage         a proposal rendered for one channel.

DELIVERY    OutreachGate            the one place a human is asked.
            OutreachChannel         disposable. email today, anything later.

MEASURE     PipelineEvent           discovered → qualified → … → won/lost.
```

**Nothing in SOURCE may reference a channel, a proposal or a send.** A business is a
fact about the world; it does not know it is being sold to. This is what lets the same
discovery feed Website, Amazon, SaaS and Business Automation later without a rewrite —
each is a different OFFER over the same SOURCE.

## Detectors are disposable, like providers

Detection is capability-based, exactly as media rendering is:

- `opportunity.discover` — produce candidate businesses for a niche and geography
- `opportunity.inspect` — inspect one business, return evidenced findings

The kernel asks for a capability. It never asks for a specific detector and never
branches on which one answered. Swapping a detector is a registration change.

The MVP ships detectors that need **no credentials and no paid API**: reachability,
TLS validity, mobile viewport, response weight and latency, and SEO basics. Each
performs a real HTTP fetch and records what it actually saw. None of them guess.

## What the MVP deliberately does not do

Out of scope, and each omission is a decision rather than an oversight:

- **No crawling framework.** Discovery in the MVP is a seed list the operator
  supplies. Finding names is cheap; producing evidenced findings is the value,
  and that is where the build went. The *architecture* is multi-source and
  autonomous — the registry queries every registered source, resolves the
  results against each other, tolerates one being down, and privileges the seed
  list nowhere. Google Maps, directories, public web and data APIs each drop in
  as a `BusinessSource` registration with no caller change.
- **No WhatsApp, no CRM, no multi-channel.** One channel.
- **No auto-send.** There is no code path from generation to send that does not pass a
  human. See below.
- **No integrations with other factories.** The seams exist; the integrations do not.

## Approval, and why there is exactly one gate

Reuses `atlas_kernel.approval` — the same service the Media Factory publishes through,
not a second approval system.

**The human approves an outcome:** this business, this proposal text, this channel. They
are not asked to authorise detector runs, scoring, or rendering. Those are Atlas's
problem.

**The approval binds to a fingerprint of the proposal.** If the proposal changes after
approval — a re-run detector, an edited paragraph, a different offer — the fingerprint
no longer matches and the send is refused rather than honoured. Approval is consent to
a particular message, not standing permission to contact someone.

`OutreachChannel.send()` is unreachable without an approved, fingerprint-matched
`OutreachMessage`. `test_opportunity_outreach.py` asserts there is no path around it.

## No spam

Three mechanisms, none of which is a prompt instruction:

1. **The gate above.** Nothing sends unapproved.
2. **Suppression.** A checked list of addresses and domains, consulted immediately
   before send, not at generation time — so a suppression added after approval still
   takes effect.
3. **Contact frequency.** A business contacted once is not contactable again within
   the configured window, regardless of approvals. Identity resolution is part of
   this guarantee: a duplicate record would be a second cooldown, and therefore a
   second email.

## The niche profile

One niche, one geography, expressed as **data**, not code:

`NicheProfile` carries the niche name, geography, which defects matter and how much they
are weighted, the offer, and the value assumption. Changing target market is editing a
profile. `profiles.py` ships one worked example so the pipeline runs end to end.

**The example profile is a placeholder for Ayoub's choice, not a recommendation.** His
read on the GCC market decides this, and it is one file to change.

## Success metric

Not emails sent. `metrics.py` reports the funnel:

| Stage | Meaning |
|---|---|
| Discovered | distinct companies seen, after identity resolution |
| Qualified | at least one evidenced finding above threshold |
| Proposed | proposal generated and cited |
| Approved | a human said yes |
| Sent | delivered to a channel |
| Replied | any response |
| Meeting | a conversation booked |
| Won / Lost | outcome |

**Close rate is the number the factory rests on, and it is unproven.** The MVP exists to
measure it honestly and early. If it is near zero, that is the most valuable thing this
milestone can produce, and it produces it in days rather than months.
