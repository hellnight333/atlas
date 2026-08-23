# P-B1 — autonomous control plane, core slice

**Agent:** Claude Opus 5 (1M context), Claude Code
**Range:** `d2e902f` → `7d579c8` (3 commits)
**Cost:** UNKNOWN — this environment exposes no token or price accounting to
the agent. Recorded as UNKNOWN rather than estimated, per §3.

## Objective

Build the persistent orchestration layer: a human request becomes a plan,
delegated to an agent, executed in an isolated Git workspace, tested,
committed, and recorded — continuing when the UI is closed.

## What was built

| Unit | Files | Commit | Tests |
|---|---|---|---|
| Coding-agent boundary + fake + LLM adapter | `mission/agents.py` | `b317f41` | 26 |
| Persistent worker | `mission/worker.py` | `b317f41` | (same file) |
| Git worktree isolation | `mission/gitspace.py` | `7d579c8` | 16 |

Built on the Mission layer (`f56f46f`) from the previous run.

## Systems reused rather than duplicated

`llm.LLMProvider` / `AnthropicProvider` / `OpenAICompatibleProvider` /
`ModelRegistry` — Claude arrives through the first, Codex/Qwen/DeepSeek through
the second, so four providers cost zero new integrations. `ModelSpec`'s
cost-per-mtok fields are the price table. `Mission` / `AgentInvocation` /
`Blocker`. `BusinessEvent` for all persistence. `opportunity.tenancy`.

No second job registry, approval system, quota ledger or tenant mechanism.

## The properties that carry the weight

**An agent saying "done" is not done.** `claims_done` is an assertion; the
acceptance check decides. The worker also catches the worse case — an agent
reporting success having changed no files, which is dangerous precisely because
tests pass on an unchanged repository.

**Repair is bounded.** An agent that fixes one test by breaking another would
run forever. Exhausting `max_attempts` is a recorded failure with a reason, and
a `succeed_after` fake proves the retry actually retries.

**Every exit leaves a known state.** Success, test failure, blocker, or the
acceptance check itself crashing — all release the claim and record why.

**Nothing commits that did not pass review**, asserted by reading the source.

**The worker imports no HTTP or UI.** Closing the browser cannot stop work that
never referenced it.

**Git:** never a protected branch, never `--force`/`--hard`, no push path at
all (allow-list, not deny-list), and a pre-commit secret scan that aborts rather
than warns and names the file rather than the match.

## Tests

**Full suite 2416 passed, 25 skipped.** ruff 22, mypy 135 — both at baseline.
42 tests added across the two files, including a real git repository built in a
temp directory rather than a mock.

Negative controls covering §16: duplicate claim, stale recovery, cross-tenant
access, execution without approval, agent failure, test failure, malformed
report, secret in a commit, unauthorised push, worktree collision, max attempts,
UI-independence, worker restart, fake success, provider unavailable, invalid
repository path, arbitrary command rejection.

**Not covered:** cost-limit enforcement (§10 — the ceiling is not yet wired to
`QuotaLedger`), unsupported-model rejection.

## Not built from P-B1

§7 conversation persistence · §9 durable per-mission report · §12 Mission
Control read API · §13 chat UI contract · §17 self-use proof · §18 business
re-evaluation mission type · §10 cost ceilings.

## Honest status

The vertical slice in §2 is **partially proven**. Plan → queued → claim →
implement → test → review → commit → complete runs end to end and is tested,
including in a real worktree. What is *not* proven is the §2 acceptance test in
full: there is no HTTP intake, so "close the web UI, worker continues" has been
established by construction — the worker imports nothing from the UI — rather
than by running a server and closing a browser.

**Nothing was pushed. No production data touched. No external API called.**

## Next action

1. §9 durable per-mission report, written by the worker on every exit.
2. §12 Mission Control read API over `mission.fold` / `history`.
3. §10 cost ceiling wired to `QuotaLedger`, becoming a `HumanAction` when hit.
4. §7 conversation persistence, then §17 self-use.
