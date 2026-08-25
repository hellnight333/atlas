# Four operational gates

*What became genuinely operational, and what did not. Verified on qevik-core-01
with real processes: 35/35 end to end, 10/10 claim safety, 7/7 two workers.*

## 1. Atomic claims in production, and a refusal that cannot be skipped

`qevik-worker.service` runs the mission worker as its own unit — separate from
the control plane, so restarting the API to deploy does not kill a mission and
killing the worker does not take the console down.

`/opt/qevik/worker.env` (0600) carries `QEVIK_CLAIMS_DSN` and
`QEVIK_REQUIRE_ATOMIC_CLAIMS=1`. **In the environment, never on the command
line**: a DSN carries a password and argv is readable by every user on the host
through `ps`. The DSN is derived from `ATLAS_DATABASE_URL` so there is one
source of truth for that credential.

`--require-atomic-claims` is the deployment *declaring what it is*. Without it,
an unreachable claim database degrades to local claiming and logs the loss.
With it, the process refuses to start. That asymmetry is deliberate: the failure
being prevented is not an outage, it is a **quiet success** — an operator
believes two workers are safe, both fall back, both take the same mission, two
commits of the same change appear and nothing anywhere reports an error. Dying
at start-up is recoverable; that is not.

The same declaration now exists for the control plane (`UnsafeClaiming`), so
`/api/health` reports the truth about the deployment rather than about its own
unused claims object:

    claiming: PostgresClaims · multiprocess_safe true · verified true
              status COMPLETE · "Two workers can run safely."

**Proven** — `infra/verify_claim_safety.py`, 10/10 on the host: the worker and
the control plane each refuse with no database and with an unreachable one, the
refusal never prints the DSN, both still degrade-and-log without the
declaration, and both start normally against the real database. Every refusal
has its negative control.

## 2. Budgets charged from the real execution path

**Persistence went into the ledger, not above it.** `QuotaLedger`'s own
docstring said storing `QuotaSpend` rows and replaying them was all it would
take; it was never wired, so every restart forgot the month's usage. Putting it
anywhere else would mean `credits`, `fabric.budgets` and whatever comes next
each needing their own answer — and the second one written is the one that
disagrees.

`QuotaLedger(events=…, sink=…)` now replays policies and spends from
`quota.jsonl`. `credits` and `fabric.budgets` became durable at once, and the
worker and the control plane read the **same file**, so there is one balance
rather than two.

The worker calls `fabric.budgets.reserve()` after the work, against an
`Envelope(tenant, mission, agent)`. After, not before: the estimate gates
*dispatch* — the scheduler already refuses missions the tenant cannot afford —
and this records what was actually consumed. Charging an estimate and never
reconciling is how a month's usage drifts from the month's bill.

**An unknown cost is recorded, not invented.** `Mission.total_cost` is `None`
when no invocation reported one. Charging a guess would put a fiction in the
ledger; charging zero would say the work was free. The fact goes on the timeline
instead — `cost UNKNOWN … This is not a zero` — where an uncharged mission is
visible.

No second budget system exists. `reserve()` checks tenant, mission and agent and
commits to all or none, on the one ledger.

## 3. A model-backed mission — wired, and blocked at the provider

This is the gate that did **not** close, and the distinction matters.

The path is wired and proven up to the provider's authentication boundary:

    credentials: restored 1 record(s) from the timeline
    model registry: skipping qwen (INVALID_CREDENTIAL)
    no model is available for planning

Reading that in order: the worker read the credential the **Credential Centre**
stored, the model registry refused to turn a provider-rejected key into a model,
and the worker refused to run rather than substituting a stub. Every one of
those is the designed behaviour.

The mission stayed `queued` and untouched — correct, because nothing claimed it.
Failing a mission because the *host* has no usable model would discard work over
a configuration problem.

`--agent fake` exists and was deliberately not used. Everything it produces
would claim work no model did.

**The blocker is factual:** the configured DashScope key is rejected by
DashScope. Tested against three endpoints — the configured regional one, intl,
and Beijing — all `INVALID_CREDENTIAL`, so it is not a region mismatch. No other
provider key is present on the host. A completed model-backed run needs a key
the provider accepts; nothing else is missing.

### A real bug found on the way

The worker read `<vault_root>/credentials.json` while the control plane writes
`<QEVIK_STATE>/vault.json`. **Two different files.** A key entered in the
Credential Centre was invisible to the worker, and the worker's refusal would
have read as "no credential configured" to an operator looking at a Centre
showing one connected. `_vault_file()` now accepts either the file or the
directory containing it, and the worker reads the record timeline too — the
vault holds the secret, the timeline holds the record, and a worker with only
one of them finds nothing.

## 4. Conversations that outlive the process

`from_environment` handed the chat surface an in-memory list. Every restart
forgot every conversation, so the sentence a person typed, the plan proposed
from it and the approval that queued a mission all vanished **while the mission
itself survived** — leaving work in flight that nothing could explain.

`chat.jsonl` beside the others. `chat/service.py` already had `fold`, `history`
and `rehydrate`; only the durable store was missing.

`is not None`, never truthiness — `Timeline` defines `__len__`, so a brand-new
one is falsy and `or` would silently swap durable storage back for a list. That
exact mistake has been made in this file before.

**Proven** — the end-to-end run starts a conversation, kills the server, starts
a new one and reads the conversation back with the person's words intact. The
console acceptance separately proves the conversation still references its
mission after a restart.

## Where each timeline lives

    /var/lib/qevik/control/missions.jsonl      missions
    /var/lib/qevik/control/chat.jsonl          conversations
    /var/lib/qevik/control/credentials.jsonl   credential records
    /var/lib/qevik/control/quota.jsonl         allowances and spends
    /var/lib/qevik/control/vault.json          the sealed secrets
    /var/lib/qevik/control/reports/            durable mission reports

Every one is append-only JSONL folded on read, and every one is shared by the
control plane and the worker. None holds a secret except the vault, which holds
nothing else.

## What remains

- **A provider key the provider accepts.** The only thing between here and a
  completed model-backed mission.
- **`Conversation` (the agent-to-agent protocol type) is still not persisted.**
  Distinct from chat conversations, which now are.
- **No second worker is actually running.** One is, with atomic claims; the
  safety is proven for two.
