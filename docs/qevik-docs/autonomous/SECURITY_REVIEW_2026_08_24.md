# Security review — 24 August 2026

Every item from §18 of the directive, checked against the repository at
`4875a56`. Each is **FIXED**, **HELD** (a property that already holds and was
verified rather than assumed), **PENDING_INFRASTRUCTURE**, or **OPEN** with the
reason it was not closed.

Nothing here is asserted from memory. Where a claim is "we checked and it was
fine", the check is named.

---

## FIXED this session

### SSRF — the crawler would fetch from inside its own network

**Severity: high.** Research fetches a URL somebody supplied — a customer form, a
directory listing, or a redirect Qevik did not choose — from inside the
deployment, with no address check at all.

`http://169.254.169.254/latest/meta-data/iam/security-credentials/` was a valid
"business website". Qevik would fetch it, receive the instance's cloud
credentials, and file them as research on the business timeline: readable through
the customer API, quotable in a proposal, included in a report.
`http://127.0.0.1:5432` and `http://10.0.0.5/admin` are the same shape.
`file:///etc/passwd` was a URL the crawler would accept.

Fixed in `research/addresses.py`:

- Every **resolved** address is checked, not the first. A name answering with one
  public and one private address is the standard bypass for a check that reads
  `[0]`.
- Every **redirect hop** is checked. `follow_redirects` was on, so httpx walked
  the chain before anything could inspect it; it is off now and `_follow` walks
  it with a bounded length.
- Only `http` and `https`.
- A refusal is **data**: a blocked address becomes a `Page` with a reason, so
  research reports `NOT_VERIFIED` rather than crashing, and a business genuinely
  hosted on a private network is one we could not check rather than one we lie
  about.

Verified by a test that starts a real HTTP server on loopback serving a secret,
points the real fetcher at it, and asserts the secret never arrives.

### Command injection — no shell, and an allow-list

**HELD, verified.** `grep -rn "shell=True"` across the kernel returns nothing.
`mission/gitspace.py` runs git through `subprocess.run` with an argument list, an
allow-list of permitted subcommands, and an explicit refusal of `--force`, `-f`
and `--hard`. `PROTECTED` refuses `main`, `master`, `trunk` and `production`.

### Arbitrary code execution from chat

**FIXED by construction.** `chat/` starts nothing, opens no repository and drives
no worker; a message becomes a proposal that a person must approve. Asserted by
an AST walk over the module for imports and calls — not a text scan, which the
first version of that test defeated by matching its own docstring. The scan has a
negative control: it must flag `gitspace`, which does run git.

### Prompt-injection boundary

**FIXED by construction, and this is the reason for the above.** A plan is
written by a model that has read the customer's website, their email and their
research — all attacker-influenced. Requiring a person to look at the plan before
anything runs is what keeps an injected instruction a proposal.

Two supporting properties are tested: a *proposed* plan produces no mission at
all until somebody approves it, and a **blocked** plan cannot be approved into
one.

### Credential leakage

**HELD, verified by sweep.** No route in `credentials/api.py` returns a stored
secret in any state or through any error path — tested by sweeping a canary
string across every route including the 409s, the validation errors, and a probe
that echoes the key back the way a real API's 400 does. A source-level test
asserts `.resolve(` never appears in the HTTP module.

The vault seals rather than degrading: with no master key it refuses to store
rather than falling back to plaintext.

### Path traversal

**HELD, verified.** `mission/api.py` resolves `report_path` under the reports
directory and refuses anything that escapes. `report_path` arrives on an event,
and an event is data — treating it as a filesystem instruction is an
arbitrary-file-read with extra steps. Tested with `../../../secret.txt`.

### Tenant isolation

**HELD, verified per route.** Every read and both write routes on the customer
surface, every mission route, every chat route, every credential route, every
model route: another tenant's resource is **absent**, with a body identical to a
missing one. 403-versus-404 tells a caller which ids exist.

Tested individually per endpoint rather than once — a boundary that holds for six
endpoints and leaks on the seventh is not a boundary, and the seventh is always
the one added last.

### Secret scanning

**HELD.** `mission/gitspace.py` scans a diff for secret-shaped strings before
committing and refuses. Every session commit was scanned with the scanner
negative-controlled against a planted canary first — a silent scanner and a clean
diff look identical.

### Git isolation

**HELD, verified.** A mission commits to `mission/<id>` in its own worktree,
never to main; there is no push path in the allow-list; history is never
rewritten. Proven end to end: `test_chat_to_commit.py` asserts the commit's SHA
does not appear in `git log main`.

---

## PENDING_INFRASTRUCTURE

### Multi-worker races

`mission/claims.py` has the abstraction and two implementations. `LocalClaims` is
correct for one process including its threads (eight threads race a barrier;
exactly one wins) and reports `multiprocess_safe = False`. `PostgresClaims`
writes out `SELECT … FOR UPDATE SKIP LOCKED` and **refuses to construct** without
`i_have_a_database=True`, because its failure mode is not an exception — it is
two workers quietly running one mission and committing the same change twice.

`verified()` and `multiprocess_safe` are deliberately separate questions. There
is no fake that makes multi-worker correctness pass, and a test asserts its
absence.

**Run one worker.** `/api/health` reports `SINGLE_WORKER_ONLY` so the constraint
is visible to whoever operates it.

---

## OPEN, with the reason

### DNS rebinding

The SSRF guard resolves, then httpx resolves again when it connects. A name that
changes its answer between the two calls passes.

Closing it means connecting to the *checked* IP with the hostname in the Host
header — a transport-level change to how the client is constructed, not a check
that can be added at the call site. It is a narrower attack than the one closed
(it needs attacker-controlled authoritative DNS with a very low TTL, and Qevik's
crawler makes one request per page rather than re-fetching), which is why the
broad fix shipped first.

**Not claimed as fixed.**

### Rate limiting

`auth/api.py` rate-limits login, which is the endpoint where it matters most —
credential stuffing. **Nothing else is limited.**

The exposures that follow: `POST /api/chat/{id}/plan` spends money at a provider
on every call; `/api/public/audit` is unauthenticated; research triggers outbound
fetches. The first is bounded by `QuotaLedger` reservations rather than by
request count, which limits the money and not the load; the second reads stored
research and never crawls on request, which was a deliberate choice recorded in
its docstring.

A per-tenant limiter belongs in front of the planning and audit routes. Not built
because it wants a shared store to be correct across processes — the same
dependency as the claim table, and building a per-process limiter would provide
the appearance of a limit without the property.

### Webhook verification

**Not applicable yet, and deliberately so.** There are no webhook endpoints;
`grep -rn webhook` across the API surfaces returns nothing. Stripe, Amazon, Noon,
YouTube and Instagram are registered with `adapter_ready=False`, so none has an
inbound callback.

Recorded as a gate rather than a gap: **the first webhook endpoint must ship with
signature verification in the same commit.** An unverified webhook is an
unauthenticated write from the internet, and it is always added under time
pressure because a provider is waiting.

### Worker isolation

The mission worker runs as its own OS process with its own git worktree, which is
the isolation that exists. It is **not** sandboxed — no container, no seccomp, no
filesystem confinement — so an agent that decided to write outside its worktree
could.

Bounded by the agent being a model with a file-writing tool rather than a shell,
and by the commit step only staging the worktree. Real sandboxing is a host
concern and is recorded as `PENDING_INFRASTRUCTURE` in `MASTER_STATE.md`.

### Approval boundaries

**HELD**, and worth restating because it is the property most easily lost: two
distinct approvals exist — execution ("should Qevik do this work") and artefact
("may this exact output go live") — and the artefact approval's fingerprint
covers the published **bytes** via `bundle_hash`. The SEO artefacts were merged
into the bundle *before* hashing for this reason, and a test asserts the hash
changes when they are removed.

`READY_TO_PUBLISH` is not `PUBLISHED`, and the customer decide route says so in
the response where whoever builds the screen will read it.

---

## Summary

| Item | State |
|---|---|
| SSRF | **FIXED** |
| Command injection | HELD, verified |
| Arbitrary execution from chat | FIXED by construction |
| Prompt-injection boundary | FIXED by construction |
| Credential leakage | HELD, verified by canary sweep |
| Path traversal | HELD, verified |
| Tenant isolation | HELD, verified per route |
| Secret scanning | HELD, negative-controlled |
| Git isolation | HELD, verified end to end |
| Multi-worker races | PENDING_INFRASTRUCTURE |
| DNS rebinding | **OPEN**, narrower than what was fixed |
| Rate limiting | **OPEN** beyond login; wants a shared store |
| Webhook verification | Not applicable; gate recorded for the first one |
| Worker isolation | Process + worktree only; sandbox is PENDING_INFRASTRUCTURE |
| Approval boundaries | HELD, verified |
