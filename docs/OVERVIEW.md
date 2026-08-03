# How Atlas works

A short tour of the architecture, for people using Atlas rather than building
it. For the internal design see [ARCHITECTURE.md](ARCHITECTURE.md).

## Four layers

```
SURFACES    the desktop application
STUDIOS     screens for a kind of work — image, research, review, agents
KERNEL      orchestrator · scheduler · runtime · automation · approvals
            cluster · knowledge graph · organizations · audit
PROVIDERS   model adapters  (simulations only in this release)
```

## The one rule

**No studio may call a provider directly.** Every capability flows through the
kernel.

This is what stops Atlas becoming a pile of disconnected tools. Because
everything routes through one place, Atlas can schedule it, approve it, place
it on a machine, record its lineage and recover it after a crash — uniformly,
for every kind of work. A screen that reached past the kernel would lose all of
that.

## The path work takes

```
Trigger → Conditions → Planner → Scheduler → Approval gate
        → Placement → Reservation → Lease → Worker → Provider → Asset
```

Read as a sentence: something starts work, conditions decide whether it should
proceed, the planner turns it into steps, the scheduler queues them, **a human
approves if a policy says so**, the cluster decides which machine, capacity is
reserved before any job exists, the worker runs it, and the result is recorded
with its lineage.

Two properties fall out of that ordering:

- **Approval happens before a job exists.** Not after work starts and not by
  cancelling it — the job is never created.
- **Capacity is reserved before work is created.** Nothing starts that cannot
  finish, and every terminal path returns the slot.

## Nothing is autonomous

When an approval policy matches, execution stops and waits for a person. There
is no setting to disable that for irreversible actions, and no "trusted mode".

An AI operating system that can publish, delete or spend on its own is a
liability, not a feature.

## Where your data lives

One PostgreSQL database on your machine, bundled with Atlas. No account, no
cloud, no sync. Audit records are append-only: no kernel path can update or
delete one.

## What is real today

Everything above is implemented **except the provider layer**, which ships as
two simulations. See [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md).
