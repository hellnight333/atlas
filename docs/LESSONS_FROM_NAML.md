# Lessons carried over from the Naml ops dashboard

Atlas is a greenfield build — **no code is copied**. But these are production bugs that
were already paid for once. Read this before writing provider, queue or deploy code.

## Database

**`idle in transaction` sessions are the #1 cause of "it worked, then it broke."**
A connection that opens a transaction and never commits holds locks until something
times out. Symptom: the system works for hours, then requests hang for no visible reason.
- Always check `pg_stat_activity` **first** when diagnosing intermittent failures.
- Set `idle_in_transaction_session_timeout` at the DB level from day one.
- Every kernel DB helper must be context-managed. No manual `commit()` in business logic.

**Never combine `UNIQUE` with a non-null default on a generated column.**
A `click_token TEXT UNIQUE DEFAULT ''` column meant the *second* row in any batch insert
collided with the first and rolled back the entire batch. Generate the value per row, or
allow NULL (NULLs don't collide under UNIQUE).

**Case and join keys must be documented, not guessed.** In the old prod schema, statuses
were UPPERCASE, one table's join key was `_id` not `id`, and a `name` column held JSON
text. Atlas schema rules: lowercase enums, `id` everywhere, no JSON-in-TEXT columns.

## Deploys

**Multi-worker processes desync on hot deploy.** With 4 uvicorn workers, pushing new code
left some workers on the old module — new routes returned 404 intermittently. A full
process restart was the only fix. Atlas: **workers must be replaced, never reloaded.**

**A naive restart = 30-90s of 502s.** Never report "done" off a single 200. Wait for the
service to be genuinely healthy (multiple consecutive 200s) before declaring success, and
warn the operator before the window. Atlas should target zero-downtime from Phase 1 —
the job queue makes this easy, since in-flight work survives in Postgres.

**More workers is not better.** 12 workers was measurably worse than 4: slow boot, higher
flakiness. Tune from measurement, not intuition.

**Runtime-installed dependencies are ephemeral.** Anything `pip install`ed into a running
container disappears on the next deploy, breaking features silently. Every dependency
belongs in the image. No exceptions.

## Infrastructure

**Docker lost all images on host reboot** until storage was moved to a bind mount.
Verify image persistence survives a reboot before trusting any host.

**Never `sed -i` a bind-mounted config file.** `sed -i` writes a *new inode*; the
container keeps reading the old one. The edit appears to work and changes nothing.
Write in place, then restart the container — don't trust a config `reload` subcommand.

**Restarting an app container can leave the reverse proxy with a stale DNS entry.**
If the app is restarted, restart the proxy too, or it routes to a dead IP.

## Providers

**Provider constraints are real and undocumented — encode them as validation, not comments.**
Two examples that cost real debugging time:
- Seedance rejects `first_frame_url` and `images`/`videos` in the same request. Mutually
  exclusive, not additive.
- Seedance reference-to-video rejects a reference video *longer than the output*. The
  reference must be trimmed before submission.

In Atlas, each provider adapter owns a **validator** that rejects impossible payloads
locally, before spending a network call or a credit.

**Prepaid balances hit zero and fail silently or ambiguously.** Exhausted API credit
surfaced as a generic 402 or a 502 — never as "you are out of money." Every paid provider
adapter must expose a `check_balance()` and the scheduler must preflight it, so a job
fails with *"provider X out of credit"* rather than a mystery 500.

## Application code

**The monolith is the thing to avoid.** The old dashboard reached ~30k lines in a single
`main.py`. Feature velocity was fine; everything else — testing, review, deploys, worker
memory, onboarding — degraded. This is the primary reason Atlas is a monorepo of packages
with a hard kernel/studio boundary.

**Long-running buttons need synchronous visible feedback before the first `await`.**
Otherwise the operator clicks again, and again. Applies to every Atlas surface.

**Never emit raw control bytes into inline `<script>`.** A `\x00` inside a JS regex in a
server-rendered page killed the entire script block silently. Prefer allow-lists over
control-character ranges — and prefer not server-rendering JS at all, which Atlas doesn't.
