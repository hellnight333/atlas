# Opportunity Factory (M014)

Finds businesses with a specific, **provable** commercial defect and produces a
proposal built from those findings — approval-gated end to end.

Ranked first in [`BUSINESS_ROADMAP.md`](../BUSINESS_ROADMAP.md) because it compounds
where the other factories are capped, and because every other factory's commercial path
runs through it. Read [`SHIP_RULE.md`](../SHIP_RULE.md) before extending this.

---

## The two invariants

Everything else here is ordinary code. These two are load-bearing, enforced in the type
system and by tests rather than by review:

### 1. A finding cannot exist without evidence

`Finding` requires an `Evidence` object naming **what was observed, where, when and by
what**. There is no constructor path that produces an unevidenced finding — the model
rejects it. A claim about someone's business that Atlas cannot substantiate must be
impossible to create, not merely discouraged.

### 2. A proposal cannot exist without findings

`Proposal` requires at least one `Finding` and every claim in it cites one by id. A
proposal citing nothing is rejected at construction. This is what makes "never generic
templates" a property of the system rather than a hope about prompt quality.

Both are checked in `tests/test_opportunity_invariants.py`, which fails if either can
be bypassed.

---

## Layering

Mirrors the Media Factory's discipline, for the same reason: the source layer must not
learn about the channel it eventually reaches.

```
SOURCE      Prospect                a business. no findings, no scoring, no channel.
            Finding                 one evidenced defect. immutable once observed.
            Opportunity             a scored bundle of findings worth selling against.

OFFER       Proposal                generated from findings. cites them. no channel.
            OutreachMessage         a proposal rendered for one channel.

DELIVERY    OutreachGate            the one place a human is asked.
            OutreachChannel         disposable. email today, anything later.

MEASURE     PipelineEvent           discovered → qualified → … → won/lost.
```

**Nothing in SOURCE may reference a channel, a proposal or a send.** A prospect is a
fact about the world; it does not know it is being sold to. This is what lets the same
discovery feed Website, Amazon, SaaS and Business Automation later without a rewrite —
each is a different OFFER over the same SOURCE.

## Detectors are disposable, like providers

Detection is capability-based, exactly as media rendering is:

- `opportunity.discover` — produce candidate prospects for a niche and geography
- `opportunity.inspect` — inspect one prospect, return evidenced findings

The kernel asks for a capability. It never asks for a specific detector and never
branches on which one answered. Swapping a detector is a registration change.

The MVP ships detectors that need **no credentials and no paid API**: reachability,
TLS validity, mobile viewport, response weight and latency, and SEO basics. Each
performs a real HTTP fetch and records what it actually saw. None of them guess.

## What the MVP deliberately does not do

Out of scope, and each omission is a decision rather than an oversight:

- **No crawling framework.** Discovery in the MVP is a seed list the operator supplies.
  Finding names is cheap; producing evidenced findings is the value, and that is where
  the build went.
- **No WhatsApp, no CRM, no multi-channel.** One channel.
- **No auto-send.** There is no code path from generation to send that does not pass a
  human. See below.
- **No integrations with other factories.** The seams exist; the integrations do not.

## Approval, and why there is exactly one gate

Reuses `atlas_kernel.approval` — the same service the Media Factory publishes through,
not a second approval system.

**The human approves an outcome:** this prospect, this proposal text, this channel. They
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
3. **Contact frequency.** A prospect contacted once is not contactable again within the
   configured window, regardless of approvals.

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
| Discovered | candidates seen |
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
