# Multi-worker claiming

*Status: the implementation is verified. The deployment is still single-worker
until a DSN is set.*

Step 5 of the Munder-Difflin ordering. It was listed as
`PENDING_INFRASTRUCTURE` — "needs a database". Checking the host found
PostgreSQL 18.6 already running on qevik-core-01 with a `qevik_test` database
and psycopg 3.3.4 in the deployment venv, so the blocker had already lifted and
nobody had noticed.

## What was demonstrated

`infra/verify_postgres_claims.py`, run 25 August 2026. Full output:
`reports/postgres_claims_verification.txt`.

Eight separate OS processes, each with its own connection, **spinning until a
shared start instant** so they reach the `SELECT` together. A staggered start
would let the first finish before the second began, and the run would pass
against an implementation with no locking at all.

| | |
|---|---|
| every worker answered | 8 of 8 |
| nothing raised | — |
| exactly one worker claimed it | `worker-1` |
| the database agrees who holds it | holder is `worker-1` |
| a different mission is still claimable | the negative control on "refuses everything" |
| a held mission is refused a second time | the same call that succeeded for the winner |
| release frees it, and it can be claimed again | — |
| a two-hour-old claim can be taken over | otherwise a crashed worker holds a mission for ever |
| a fresh claim cannot | the negative control on the line above |
| an autocommit connection is refused | see below |

13 checks, 0 failures. The rows it created were deleted; `count(*)` returned 0
afterwards.

## The bug the verification found

`SELECT … FOR UPDATE SKIP LOCKED` holds its lock **until the transaction ends**.
On an autocommit connection that is the semicolon — so the lock is released
before the `UPDATE` that records the claim, and two workers claim one mission
**with no error at all**. That is the exact failure mode this whole module
exists to prevent, and it was one keyword argument away.

`PostgresClaims.__init__` now refuses an autocommit connection.

## Two things that are still separate questions

`multiprocess_safe` says the algorithm is right. `verified()` says somebody
watched it work. Both are now `True` for `PostgresClaims`, and they remain two
fields, because merging them is how the next unverified implementation gets to
inherit this one's evidence.

`DEMONSTRATED_BY` in `claims.py` names the run, the host, the database version
and the report — a claim of verification with nothing behind it is precisely
what this module exists to prevent, so a reader can go and check. A test asserts
the report file exists and says it passed: a pointer that outlives its file is a
citation, not evidence.

## What the deployment has

Still `LocalClaims`. `create_app` builds `PostgresClaims` only when
`QEVIK_CLAIMS_DSN` is set; without it the control plane stays single-worker and
`/api/health` says `SINGLE_WORKER_ONLY`.

A configured-but-unreachable database **falls back to `LocalClaims` and logs an
error naming the loss of safety**. Refusing to start would take the whole
control plane down over a capability only the worker needs; falling back
silently would leave the operator believing they had multi-worker safety they
did not. `/api/health` reports which implementation is in use, so it is a claim
that can be checked rather than assumed.

## What is not done

- **No second worker is actually running.** Setting `QEVIK_CLAIMS_DSN` and
  starting a second `mission_worker.py` is a deployment decision, not a code
  one, and claiming multi-worker operation before that happens would be
  fabricated completion.
- **`register()` is not called by the mission worker.** A mission has to have a
  row in `qevik_mission_claim` before anything can race for it; wiring that into
  the mission lifecycle is the remaining step.
- The table is created by `install()` rather than by a migration framework.
  Idempotent and additive, and it creates one table.
