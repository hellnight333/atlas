# Roadmap review — 2026-08-04

Requested under [`SHIP_RULE.md`](SHIP_RULE.md) with a 90-day horizon and no
instruction to preserve the existing order. Criteria: revenue impact, manual work
eliminated, time to first customer value, external blockers, long-term leverage.

Supersedes the ranking in [`BUSINESS_ROADMAP.md`](BUSINESS_ROADMAP.md) for
scheduling purposes. That document's per-factory analysis still stands.

---

## The finding that dominates everything else

**Three factories are built. Three are frozen. None has produced a dirham.**

| Milestone | State | Blocked on |
|---|---|---|
| M013 Media | frozen | GPU worker · YouTube credentials |
| M014 Opportunity | frozen | niche + geography · the offer · sending identity |
| M015 Website | frozen | public TLS endpoint · first customer |

Every blocker is a **decision, not code**. Together they are perhaps an hour of
Ayoub's time. Meanwhile three milestones of finished engineering sit idle.

Reordering will not fix that, because it is not an ordering problem. **The
constraint is not engineering capacity — it is that work keeps being built ahead
of the business inputs it needs, and then frozen.** A fourth factory built the
same way makes four.

So this review produces two things: a re-ranking, and a constraint on what M016
is allowed to be.

---

## Structural changes

Recommended regardless of ordering.

### Remove three "factories" that turned out not to be factories

Each was listed as a destination, and each has been absorbed by whichever factory
needed it first — which is exactly what SHIP-1 prescribes for enablers.

| Was on the list | Reality |
|---|---|
| **Deployment Factory** | Absorbed into Website (M015). `site.deploy` with two adapters, proven on a real host. |
| **SSH Infrastructure Manager** | Absorbed into Website. `SshDirectoryTarget` deploys to a real box today. |
| **Multi-model Orchestrator** | Capability routing has existed since M013. It is a **rule**, not a milestone — extend it when a factory needs a capability it lacks. |

This removes three items from the backlog without removing a single capability.
Eight remain, and the list is now honest about what is actually unbuilt.

### Opportunity and Website are one product, not two milestones

Find a business with a broken site, propose the fix, deliver it. They were built
as separate milestones and should be **operated as one thing** — "the agency" —
with one funnel and one set of numbers.

No code changes. A framing correction, so the two stop being scheduled against
each other and start being measured together.

---

## Re-ranking

Scored 1–5. Weights reflect the 90-day horizon, and that is the main reason this
differs from the last ranking: **over 90 days, time to first customer value is
worth far more than long-term leverage.**

| Criterion | Weight | Why |
|---|---|---|
| Revenue impact | ×3 | SHIP-1 priority 1 |
| Manual work eliminated | ×2.5 | SHIP-1 priority 2 |
| Time to first customer value | ×2.5 | The 90-day frame makes this decisive |
| Freedom from external blockers | ×2 | Three frozen milestones is the evidence |
| Long-term leverage | ×1.5 | Real, but not what the next 90 days turn on |

| # | Milestone | Rev | Manual | Time | Free | Lev | **Total** |
|---|---|---|---|---|---|---|---|
| **1** | **Amazon Factory** | 5 | 4 | 5 | 4 | 3 | **50.0** |
| 2 | Browser / Computer Agent | 2 | 5 | 2 | 4 | 5 | 39.0 |
| 3 | Business Automation | 2 | 4 | 3 | 4 | 3 | 36.0 |
| 4 | Media — finish M013 | 2 | 4 | 3 | 1 | 3 | 30.0 |
| 5 | AI SaaS | 5 | 1 | 1 | 2 | 3 | 28.5 |

### Amazon moves from 3rd to 1st

Not because the earlier analysis was wrong. Under a leverage lens measured in
years, Opportunity genuinely leads — and that analysis produced M014 and M015,
which are built. Over **90 days with three factories frozen**, the binding
criterion changes, and Amazon is the only remaining milestone where:

- **the customer already exists and already pays.** Oskar Phones and Teqtronix
  sell on Amazon UAE and KSA today. No acquisition, no close rate, no trust gap.
- **revenue is a lift on GMV that already exists**, measurable against a live
  baseline in weeks rather than revenue that must first be won.
- **the analysis half needs no credentials at all.** Marketplace listing pages
  are public.

Ayoub already designated these catalogues as the M016 validation datasets, so the
customer question is settled *before* the milestone starts. That is precisely
what the other three lacked.

### The others

**Browser / Computer Agent** is the strongest second and the best long-term buy:
it eliminates more manual work than anything else remaining, and it unblocks the
*apply* half of Amazon. But 12–18 days to be trustworthy, and an unreliable
browser agent inside a live ad account is worse than no agent.

**Media stays low despite being ~70% built.** Sunk effort is still not one of the
criteria, and it scores 1 on blockers — it is the most blocked item on the list.

**AI SaaS stays last.** Maximum revenue ceiling, minimum everything else, and its
true dependency is distribution, which cannot be built.

---

## The highest-return action is not a milestone

One session, five answers, and two complete factories start producing:

| # | Question | Unfreezes |
|---|---|---|
| 1 | Niche + geography | M014 |
| 2 | The offer and price | M014 |
| 3 | Sending identity — domain and mailbox | M014 outreach |
| 4 | Public TLS endpoint — Caddy vhost or Cloudflare | M015 |
| 5 | First website customer (internal counts) | M015 |

Cost: under an hour. Value: two finished factories stop being idle. **Nothing on
the ranking above competes with that ratio**, and it should happen whether or not
M016 starts.

---

## The constraint M016 must satisfy

Given the pattern this review found, one rule governs the next milestone:

> **If it can freeze on an external input, it is out of scope.**

M016 must reach a measurable business result using only what Atlas can already
reach. Anything requiring a new credential, a new account, a hardware
provisioning step, or a decision Ayoub has not already made belongs to a later
phase of that milestone — **never its first deliverable**.

This is not a general principle. It is a correction to a specific, repeated,
three-time mistake, and it should be dropped once a milestone has actually
shipped revenue.
