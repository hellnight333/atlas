# The Credential Centre — root cause and fix

*Reported: Claude and Qwen stay `NOT_CONFIGURED` after Save; Save/Test do not
work. Verified fixed against the live app, 20/20.*

## Root cause: two defects, one visible symptom

### 1. The vault persisted the secret. The record did not.

`CredentialService._records` was a plain in-memory dict. The **secret** went to
`vault.json` on disk; the **record** — fingerprint, hint, verification result,
which is everything `status` and the Centre read — lived only in the process.

`qevik-control.service` is `Restart=on-failure`, and every deploy restarts it.
So the sequence the operator saw was:

    save      -> PENDING_CREDENTIAL   (correct)
    restart   -> NOT_CONFIGURED       (the record is gone)

Worse than a display bug: the secret was still in the vault, **unreachable and
impossible to forget**, because `forget()` looks the record up before dropping
it. Orphaned key material with no UI path to remove it.

The module docstring already promised "a place to store one that outlives the
session that entered it". That half was never built.

Every sibling module — `publication`, `roadmap`, `credits`, `aivisibility` —
has both a `to_event` and a `read` that folds it back. `credentials` had
`to_event` and **no fold, and nothing appending**. The events were designed and
never wired.

### 2. No probes were registered, so Test answered 501 for everything.

`Wiring.credential_probes` defaulted to `{}` and `from_environment` never
populated it. `POST /api/credentials/{provider}/test` returned:

> no probe is implemented for anthropic, so its credential cannot be tested here

for every provider, without exception. A credential could therefore never leave
`PENDING_CREDENTIAL`, because only a probe can move it.

## The fix

**Records now fold from an append-only timeline**, following the pattern the
rest of the system already uses rather than inventing a store.

- `to_event` is now **lossless** — it carries the reference, connection kind,
  verification status/detail/time, and the stored/rotated moments. It carried
  none of those, so a fold could not have rebuilt a record even if one existed.
- `restore(events)` folds records back; latest wins **by timestamp, not by
  position**, the same rule `mission.fold` uses.
- A new `FORGOTTEN` event, because a timeline that only ever said "stored" would
  resurrect a credential the operator deliberately destroyed.
- `CredentialService(vault, events=…, sink=…)`, and every mutation goes through
  one `_remember()` that updates the dict **and** appends. Two call sites doing
  one of those is how state and log disagree.
- `from_environment` points it at `credentials.jsonl` beside the vault. Its own
  file rather than the mission timeline: both are append-only JSONL, and mixing
  them makes one log neither reader wants whole.

**Real probes ship by default.** `credentials/probes.py` covers anthropic, qwen,
openai, deepseek, stripe and cloudflare. Each makes the cheapest authenticated
call the provider offers — listing models — because a probe that *generated*
something would bill the customer for finding out whether they can be billed.

Three rules the probes follow:

- **The provider's body is never read.** A provider that echoes the request
  echoes the header, and the header is the key. Each probe maps a status code to
  a `Status` and writes its own sentence.
- **`NETWORK_ERROR` is distinct from `INVALID_CREDENTIAL`.** Reporting a timeout
  as a bad key sends somebody to rotate a credential that was fine.
- **403 is `INSUFFICIENT_PERMISSION`, not "wrong key".** It usually means right
  key, wrong plan or missing scope.

A provider with no probe still answers 501 and says so — better than a probe
that always passes, which turns the Centre into decoration.

## Live verification

`/opt/qevik/verify_credentials.py`, run on qevik-core-01 against the running
service on `tenant-qevik`. It creates a temporary operator whose password is
generated on the server and never printed, then removes it.

| | |
|---|---|
| save succeeds | HTTP 201, `PENDING_CREDENTIAL` |
| read back | same status, same fingerprint |
| **restart, then read** | **`PENDING_CREDENTIAL` — survived** |
| test | HTTP 200 (was 501), `INVALID_CREDENTIAL` from the real Anthropic API |
| restart, then read | `INVALID_CREDENTIAL` — the result is durable too |
| the Centre lists it | yes, vault not sealed |
| forget | HTTP 200, and `NOT_CONFIGURED` after another restart |

**20 passed, 0 failed.** Both providers the operator named were confirmed
against their real endpoints:

    qwen      -> INVALID_CREDENTIAL   DashScope rejected the credential
    anthropic -> INVALID_CREDENTIAL   Anthropic rejected the credential

`INVALID_CREDENTIAL` is the *correct* result here — it proves the probe made a
real authenticated call and the provider rejected a deliberately fake key. A
`CONNECTED` would have meant the probe was not really asking.

No secret reached disk: `grep -cE 'sk-[A-Za-z0-9_-]{12,}'` over the live
`credentials.jsonl` returns 0, and the timeline holds only
`stored / verified / forgotten` with fingerprints.

## What the operator does now

Paste the keys into the Centre. They will persist across restarts, and Test
will say whether they work.

The two keys that appeared in a conversation earlier were **test keys**, and the
operator has said so. They are not a pending action and should not be raised
again.
