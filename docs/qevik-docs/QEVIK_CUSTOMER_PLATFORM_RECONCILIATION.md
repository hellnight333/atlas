# Customer platform — reconciled against production

The expanded customer direction is recorded here as phased slices with their
preconditions, so the autonomous loop can take them one at a time. It is not a
plan to build; it is a map of what already exists, what is blocked, and what
order the blocking clears in.

Reconciled 2026-09-01 against `qevik-core-01` and the repository.

## What production actually contains

| | |
|---|---|
| businesses | 412 |
| audited | 353 |
| with an email address | 45 |
| opportunities raised | 142 (138 open) |
| artefacts published | 5 |
| outreach drafted | 16 |
| **outreach sent** | **0** |
| inbound leads | 0 |
| tenants with any data | 1 (Qevik's own) |
| console users | 2 |
| connectors declared | 17 |
| **connectors connected** | **0** |

**There are no customers.** Every item in §2–§13 of the direction describes an
experience for somebody who does not yet exist, and the direction's own rule —
production-first, no speculative integrations — forbids building it for them.

## What already exists and is not the gap

`customer/api.py` already serves fourteen reads: `/me`, `/capabilities`,
`/plan`, `/actions`, `/integrations`, and per-business `research`, `roadmap`,
`strategy`, `tasks`, `previews`, `publications`, `measurements`, plus `/audit`
and task completion. `integrations/registry.py` declares seventeen connectors
including Search Console, Analytics, Business Profile and Amazon.
`publication/connections.py` holds connector state.

So the customer plane is not missing a backend. It is missing a **client** and
an **occupant**, and the second is the binding constraint: a client for zero
customers is a speculative build, and this is recorded as **C-27** already.

## The binding constraint, stated plainly

The journey in §15 begins at ONBOARDING, but Qevik's actual position is earlier:
it has produced evidence about 412 businesses and told none of them. The first
customer arrives through the chain that is already built and already blocked —

    audit → opportunity → artefact → publication → outreach → **send** →
    conversation → proposal → customer

— and `send` is **HA-001** (DNS) and **HA-002** (SMTP), both the owner's.
Nothing downstream of it can be production-backed until one message reaches one
business. Building onboarding, a connector centre, a diagnostic surface, plans
or an advisor before then produces capability nothing can exercise.

## Phases, in the order their preconditions clear

**P-C0 — reach one business.** Blocked on HA-001, HA-002. Everything below
depends on it and nothing else does.

**P-C1 — one real conversation.** Inbound capture exists (`customer/inbound.py`,
`lead_captured`); zero rows. Precondition: P-C0.

**P-C2 — the customer's own view of what Qevik already knows.** The reads
exist. Precondition: one customer, and **DQ-006** (what allowance Qevik's own
tenant has), which already blocks C-27/C-28.

**P-C3 — connector centre.** Honest state per connector, no fake OAuth. The
registry and the store exist; the honesty rule is already the three-state
doctrine. Precondition: a customer with an account to connect.

**P-C4 — diagnostic and capability map.** Largely derivable from data already
held: audits, findings, signals, publications, contactability. Precondition:
P-C2, so it has somewhere to render.

**P-C5 — growth plan.** `customer/strategy.py` exists. Precondition: P-C4.

**P-C6 — plans, entitlements, credits, billing.** Needs commercial decisions
that do not exist yet — prices, entitlements, tiers. Those belong in the
Decision Queue **when a customer makes them real**, not before.

**P-C7 — AI advisor, sales/service roles, marketplace audits, execution modes.**
Each depends on a customer, a connector, or a plan above.

## Duplication risks to refuse

- A second CRM or conversation system. `customer/inbound.py` and the outreach
  models already own inbound and outbound, and they are deliberately separate.
- A second human-action or decision centre. `controlplane/actions.py` derives
  and `controlplane/human.py` stores; one inbox, one `ActionKind`.
- A second customer entity. `atlas_businesses.id` is the only company record and
  a test enforces it.
- A second orchestrator. Missions run Qevik's work; the devloop runs
  development. Neither hosts the other.

## What the loop should do about this now

Nothing in P-C0..P-C7 is deterministic and unblocked today. The queue therefore
stays on production defects, which is where the evidence is. This file is the
map for when HA-001 and HA-002 clear.
