# Re-evaluating the five businesses Qevik actually contacted

`python3 infra/run_business_reevaluation.py` · 24 August 2026

Source: `73_FIRST_COMMERCIAL_TEST.md` — the record of what Qevik told five real
Dubai businesses, with the scores and the confirmed claims used to contact them.

**Nothing was re-crawled.** That is the design. Re-crawling answers "what do
their sites look like now", which is a different and less useful question here.
Feeding the *same* evidence to the *current* engine isolates one variable: what
changed about Qevik.

The §18 comparison runs on every prospect and confirms it — zero business
changes, zero coverage changes, on all five. Every difference below is ours.

## The finding

**Qevik contacted three businesses about a missing Arabic version, and until
this session had no capability to build one.**

| Prospect | Score | Contacted about | Could Qevik do it then? |
|---|---:|---|---|
| Malabar Dental Clinic | 78 | no Arabic version | **No executor** |
| The TopDent | 69 | no Arabic version | **No executor** |
| Pearl Dental Implants & Aligners | 67 | no Arabic version | **No executor** |
| 360 Agency / StaffFinder.io | 86 | number not tappable | No executor |
| AHS Catering & Events | 83 | number not tappable | No executor |

`offer-arabic-experience` was in the offer catalogue, the opportunity detector
raised it, the recommender recommended it, and `EXECUTORS` had no entry for it.
The pitch was real — the finding was true, the sites genuinely had no Arabic —
but the delivery did not exist.

## What it looks like now

```
Malabar Dental Clinic  (score 78)
  contacted about : no Arabic version
  Qevik can run   : nothing yet
  needs them first: offer-arabic-experience
```

Three changes, all of them about honesty rather than capability:

1. **The executor exists.** `offer-arabic-experience` can be performed.
2. **It is not promised.** It appears under "needs them first", because Qevik
   does not translate and the Arabic has to come from a person. The customer
   sees a task for them, stated before anything is agreed, instead of a promise
   that fails at execution.
3. **`offer-one-tap-contact` is still listed as having no executor** — and that
   is correct rather than a gap. The theme already renders `tel:` links; the fix
   lives inside `offer-website`, not in a capability of its own. Two prospects
   were pitched it as though it were separate work.

## Why "nothing yet" is the right answer

Before this session the same five would have shown `offer-arabic-experience`
under "Qevik can run" if the registry had been read naively — which is exactly
what the roadmap did until `_executable` learned to consult `EXECUTORS`, and
then again until it learned to consult `REQUIRES_CUSTOMER_INPUT`.

Both corrections move in the same direction: **fewer things promised, each one
true.** A prospect list that says "nothing yet" and names what the customer must
supply is worth more than one that says "five capabilities available" and
produces nothing.

## What this does not say

It does not say these businesses still lack Arabic — nobody looked. It does not
say the scores are still right. It says only what it measured: with identical
evidence, the current engine offers different things, and the difference is
Qevik's capability rather than their websites.

A real re-check needs a crawl, which needs no credential and would be the
obvious next step for any of the five.

## Machine-readable

`business_reevaluation.json`, beside this file, carries the per-prospect
comparison, opportunities, recommendations and executability.
