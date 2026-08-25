# The message protocol, and budgets

*Status: implemented and green. Steps 3 and 4 of the Munder-Difflin ordering.*

## The protocol

`packages/kernel/atlas_kernel/fabric/protocol.py`

Two agents that can talk can talk forever. The planner asks the researcher, the
researcher asks the planner to clarify, and by morning there is a five-figure
bill and no work done. Every safeguard here is a rule rather than a warning in a
prompt — a model asked politely not to loop will loop.

### An agent addresses a capability, never an agent

`request(needs=Capability.RESEARCH)`, not `request(to="researcher")`. The
exchange resolves the recipient through the one registry.

This is how "agents cannot recruit agents" stays true while agents still
collaborate. An agent that could name its correspondent could build a private
chain outside the registry — working relationships nobody declared, nobody can
enumerate, and no policy covers. Addressing a capability means every edge in the
graph is one the registry already knows about.

Asking for a capability nothing *ready* can perform is `REFUSED`, not queued.
Promising it would fail at execution, after the caller was told the work was
happening.

### The cap escalates; it does not truncate

At the hop limit, the message limit, or the budget, the conversation goes to a
person **with the whole chain attached**. Silently returning the last message
would hand the caller a half-finished answer that reads like a finished one, and
the loop — being invisible — would run again tomorrow.

The escalation is written even when the message cap is already full. The cap
bounds work, not the record of why the work stopped; a chain that ends
mid-sentence with no explanation is the worst of both.

After an escalation nothing more is sent, or the loop would continue underneath
the person who was asked to look at it.

| Limit | Default | Catches |
|---|---|---|
| `max_hops` | 4 | A chain that keeps delegating outward |
| `max_messages` | 24 | Two agents re-asking each other inside the hop limit |
| `budget_units` | none set | An exchange that is cheap per message and expensive in total |

### Cycles are caught by who is *still waiting*

Not by "who has been asked before". A second question to the same specialist,
after the first was answered, is ordinary work — a rule that called it a loop
would block normal collaboration. A request routed back to an agent that has not
yet answered is a genuine cycle, and "planner is already waiting on you" is
something a person can act on where "reached 4 hops" is not.

A failure counts as an answer, so a legitimate retry is not refused as a cycle.

### Refused, failed, escalated

`REFUSED` — a rule said no, and names which. `FAILED` — something broke, and it
may be worth retrying. `ESCALATED` — a person now owns it. Collapsing the first
two produces a retry loop against a limit that will refuse it every time.

### The exchange holds nothing

Every method returns a new `Conversation`. Two callers cannot disagree about the
state of an exchange, and a conversation folds from durable events like
everything else. `hops` and `spent` are computed from the messages rather than
tracked beside them — a counter next to the list is a second answer that
disagrees the first time a message is dropped.

`spent` is `None` when nothing reported a cost, never `0.0`. A reply that
arrives with no cost against a configured budget **escalates**: an unmetered
call is not a free one.

## Budgets

`packages/kernel/atlas_kernel/fabric/budgets.py`

`QuotaLedger` already does the hard part — reserve before acting, refuse rather
than fail, windows computed from timestamped entries so a restart does not
forget, and a `plan()` that says why it is not more instead of returning zero.
None of that is rebuilt. What was missing is **scope**.

    TENANT   ⊃   MISSION   ⊃   AGENT   ⊃   CONVERSATION

### Every enclosing scope must afford it

A spend is checked against **all** of them and committed to **all** of them.

- Checking only the tightest lets a hundred conversations, each inside its own
  small budget, empty the tenant's.
- Checking only the widest lets one of them do it alone.
- Committing scope by scope leaves the tenant charged for a spend the
  conversation refused — an overcharge nothing downstream ever learns about.

So: check all, then commit all, in that order. Tested in both directions, plus a
negative control that ordinary work still goes through.

### The tenant scope is the credits resource

`credits` already owns "what may this customer spend": a plan, registered on
this same ledger by `CreditService.assign()`. `Scope.TENANT` resolves to exactly
that resource, and `policy()` **refuses** to define a tenant allowance. A
parallel `budget.<tenant>` would be a second answer to the same question, and
the wrong one is always whichever the operator is not looking at.

This was caught during implementation — the first version invented its own
`budget.<tenant>` — and a test now pins the delegation so it cannot drift back.

### Unmetered is not unlimited

No policy for a *mission* means nobody set that mission a budget, which is
ordinary — the tenant's still applies. No policy for the *tenant* means the
customer is not on a plan, and `reserve()` raises `Unmetered`, having spent
nothing.

`Unmetered` is deliberately not a `QuotaExhausted`. "You have no allowance
configured" and "your allowance is gone" have opposite remedies, and a caller
that confuses them waits for a window that is never going to reset.

`Assessment.headroom` is `None` when nothing is metered. UNKNOWN read as plenty
is the same bug as UNKNOWN cost read as zero.

### The refusal is actionable

It names the **widest** scope that refused, because "the tenant is out of money"
and "this conversation is out" send a person to different places. The remedy
follows `LimitKind`: a `SPEND` limit says it can be raised; a `PLATFORM` limit
says it is not for sale, so nobody wastes an afternoon trying to buy their way
out of one.

### Tenants never share an allowance

Every resource name is tenant-prefixed, including the tenant's own, and keys are
slugified so a dotted key cannot smuggle in a separator and silently merge two
allowances. `mission-1` is not globally unique; without the prefix two tenants
would draw down one budget in the one place nobody would look for a leak.

## What is wired, and what is not

`GET /api/missions/schedule` asks `CreditService.balance()` for the tenant's
real remaining units and passes them to the scheduler, so a mission whose plan
estimates more than the tenant can afford is `BLOCKED` **before** it starts
rather than stopped halfway with the money spent and nothing produced.
`balance()` rather than the raw ledger, because it also subtracts units already
reserved and not yet settled.

One deliberate asymmetry: a tenant with **no plan** yields `None`, which the
scheduler reads as "no allowance configured" and does not block on, while
`reserve()` refuses outright. Refusing to *start* every mission because billing
was never set up would break a single-tenant self-hosted deployment; refusing to
*spend* against an allowance nobody set is still correct.

## What is not built

- **Nothing calls `reserve()` from the worker yet.** The layer is complete and
  tested and the scheduler consults the tenant balance, but per-mission,
  per-agent and per-conversation allowances are not yet charged at execution
  time. Claiming otherwise would be exactly the fabricated completion this
  project refuses.
- `Conversation` is not yet persisted to the mission timeline. It is designed to
  fold (frozen, message-derived counters) but no event kind writes it.
- Provider rate limits are not a protocol input.
- **Routing is first-ready-in-registry-order.** Deterministic, and deliberately
  not clever: choosing by cost, load or placement is a real decision that
  belongs beside the scheduler's, not hidden in a message layer.
