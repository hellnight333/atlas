# Business discovery

## The sentence this exists to make unsayable

    Qevik found it, therefore it is new to Google Maps.

It does not follow, and the gap between those two is where an autonomous
discovery system starts inventing. Qevik's memory being empty is a fact about
**Qevik**. Whether a business is new to the world is a fact about the world, and
only the world can supply it.

## Three states, one of which says anything about the world

| state | means | claims about the world |
|---|---|---|
| `KNOWN` | seen before | no |
| `NEW_TO_QEVIK` | absent from Qevik's memory; nothing more | no |
| `DISCOVERED_BY_QEVIK` | absent from memory, **and** Qevik surfaced it itself | no |
| `PROVEN_NEW_TO_SOURCE` | the source evidences it is new **to that source** | yes |

The ladder only climbs on evidence. `classify()` cannot return
`PROVEN_NEW_TO_SOURCE` without a `Novelty`, and `Novelty` cannot be constructed
without naming **the source, the field it read and the value it read** — so a
caller wanting the strong state has to have looked something up, and a reviewer
can go and check the same field. `refuse_unsupported_novelty()` is a second
front door for a state assembled by hand, from a stored row or a model's output.

Even the strong state is narrower than it sounds, and the name says so: new to
Google Maps is not new to the world.

### Why not a boolean

`resolve_business()` returns "did this row exist" as a bool, and the first draft
used it directly as `is_new`. That is the whole bug in one variable: one bit
cannot carry "absent from my notes" and "the world says this is new", and a bool
named `is_new` invites a caller to read whichever it needs.

## Observation, evidence, inference, action — four parts, kept apart

"Seventeen clinics have no Arabic page" is a **count of facts**, each separately
evidenced. "Arabic localisation is commercially valuable here" is a **reading**
of them, and it might be wrong: the seventeen might serve an entirely
English-speaking clientele.

Prose cannot be validated — no checker tells "may be" from "is" reliably, and
one that tried would pass when it should not. So the rules are structural:

1. An observation carries evidence, at least one piece, and has **no
   confidence field** — a confidence on an observation invites recording a
   half-seen thing rather than not recording it.
2. An inference **names the evidence it rests on**, by fingerprint, and every
   fingerprint must be present in the signal. That is "unsupported conclusions
   are refused", as a constructor error rather than a review comment.
3. An inference may not be certain. `0 < confidence < 1`; certainty belongs to
   observations, and an inference claiming it is pretending to be one.
4. An action that reaches outside carries `needs_approval=True` and **cannot be
   constructed otherwise**.

The payload keeps them apart, and each inference carries `is_an_inference: true`
in the data itself so a renderer cannot forget.

Rule 4 is a *label*, not the boundary — `mission/policy.py` is the boundary.
A test asserts the two agree rather than leaving it to be discovered later.

## Memory

The existing `OpportunityRepository`, extended rather than replaced.
`resolve_business` already answers "have we seen this company" on strong keys
only — domain, email, phone — because a shared name and city is not enough and a
wrong merge attaches one company's findings to another's proposal.

`atlas_sightings` is new: one row per observation, not per business. The same
clinic seen by Places in August and Overpass in September is two observations of
one company, and collapsing them into "last source" throws away what discovery
is for. A unique index makes a replayed scan safe; a check in the service would
race itself the moment two workers scan one market.

**A sighting keeps the state it had at the time.** One that was
`DISCOVERED_BY_QEVIK` in August stays that even though the business is `KNOWN`
by September — rewriting it would make the history agree with the present, which
is the one thing a history must not do.

### A discovered business belongs to nobody yet

`tenancy.owns` returns an untenanted row to nobody. That is the existing design
and it is right: a clinic Qevik noticed is not yet anybody's customer, and
assigning it at the moment of *sighting* would decide a commercial question with
a scanner. The **sighting** carries a tenant, because a scan is run on
somebody's behalf. Assignment happens at qualification.

## The order that matters

`resolve` **then** `classify`. A scan that classified first would report every
sighting as new on every run. Asserted through behaviour — three passes, one
discovery — rather than by reading the source.

## Tools

`research/net.Fetcher` as it stands: a budget that cannot be topped up by
constructing a second fetcher, robots consulted before the first request, and
every resolved address checked on **every redirect hop**. `crawler.py` is the
link from a recipe step to an `Evidence` record and decides nothing about what a
fetch means — whether a 404 is "no website" or "we were blocked" is a detector's
judgement, and a fetcher that classified would be one whose mistakes look like
facts.

A refusal is returned, not raised: one private address in a list of forty should
not abandon the other thirty-nine. `was_refused_by_the_guard()` exists so a
caller cannot mistake the guard doing its job for a dead website.

An inconclusive DNS lookup produces **no evidence at all**. A name server that
says *no such host* has answered; one that times out has not.

## Through the scheduler, not beside it

`rec-daily-business-discovery`, 04:15 UTC — inside the night window, clear of the
02:30 canary and the 03:30 backup. Origin `none`, so it changes no repository
and reaches the queue with nobody asked.

Discovery running unattended and contacting nobody unattended are both true at
once, and they have to be: every outward action a signal suggests carries
`needs_approval`, and policy is what gates it.

A market is part of the recipe declaration, not a parameter — recipes have no
variables on purpose, so scanning a second market is a second recipe: a reviewed
change in git rather than a string somebody passed at three in the morning.

## What is not built

The recipe's `http-fetch` steps are **declared and not yet executed by a
worker**. `for_adapter()` refuses them by design — a URL is not a program — and
the worker's roles are code-writing shaped. Running fetch recipes needs a
non-code-writing worker role, which is a real architectural addition rather than
wiring, and is the exact next dependency.

Everything either side of it is proven: the guard fetches and refuses, evidence
is recorded and survives, sightings resolve and classify, the recurrence creates
its mission unattended.

## Files

| Path | What |
|---|---|
| `opportunity/discovery.py` | the three states and the ladder |
| `opportunity/signals.py` | observation / evidence / inference / action |
| `opportunity/scan.py` | resolve, classify, remember |
| `opportunity/crawler.py` | recipe fetch steps into evidence |
| `opportunity/api.py` | the read-only surface; GET only |
| `packages/kernel/tests/test_discovery.py` | 22 tests |
| `packages/kernel/tests/test_signals.py` | 17 tests |
| `infra/verify_discovery.py` | 25 checks, real server, real database |
