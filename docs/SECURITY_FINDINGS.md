# Open security findings

Findings that are **recorded and left for an explicit operational decision**.
Nothing here is acted on automatically.

---

## F-001 — credential-bearing file in `/tmp` on `qevik-core-01`

**Status:** open, awaiting an operational decision
**Found:** 2026-08-26, incidentally, while scanning `/tmp` after a separate leak
**Severity:** low-to-moderate. Real exposure, narrow audience.

### What

`/tmp/db.bak` — 61,600 bytes, dated **2026-08-21 23:58**, owned `root:root`,
originally mode **`-rw-r--r--`** (world-readable). It contains
`ATLAS_DATABASE_URL` with its password.

### What was done

Permissions tightened to **`0600`** (root-only). That is the whole of the
action taken, and it is reversible.

### What was deliberately **not** done

- **Not read.** The file was never opened. The automatic classifier blocked
  reading it, which is the correct behaviour for a credential-bearing file, and
  that block was not worked around.
- **Not deleted.** It was not created by this work and its purpose is unknown.
  Deleting a file nobody has inspected is not cleanup, it is destruction of
  something that might matter.
- **No rotation requested.** Standing instruction.

### What is known, from metadata only

| | |
|---|---|
| size | 61,600 bytes, 1,605 lines |
| `PGDMP` header | absent — not a `pg_dump` |
| `ATLAS_` keys | 1 |
| DSN target | database `atlas` on `localhost:5432` — **not** the `qevik` database |
| accounts that could have read it | `root`, and `qevik` (the service account) |

The exposure window is 2026-08-21 → 2026-08-26. The only non-root account on the
host is `qevik`, which already receives that URL legitimately through
`EnvironmentFile=`. So the practical escalation is small; the finding is that a
credential sat in a world-readable path at all.

### Status 2026-08-26 (unchanged)

Re-confirmed: still not read, still not deleted, still `0600`. No rotation
raised — the current test credentials are deliberately in use for
provider-boundary testing.

### The decision that is open

1. Inspect and delete, or
2. move it somewhere durable if it is a wanted backup, or
3. leave it at `0600` and take no further action.

---

## F-002 — a DSN was written to a log by this work

**Status:** closed, with a guard
**Found:** 2026-08-26

A verification harness was run detached on the server. The redaction had been
written into the *shell invocation*, and the detached rerun dropped the pipe;
psycopg then failed to parse the SQLAlchemy-form `postgresql+psycopg://` URL and
quoted the whole conninfo string, password included, into `/tmp/rec_verify.log`
and into the session transcript.

**Fixed:** the log was destroyed. `infra/verify_recurrence.py` now carries
`_redacted()` and normalises the URL before handing it to psycopg, so the parse
error that caused the leak cannot happen and the redaction cannot be forgotten
at a call site. Verified against the exact string that leaked.

**Residual:** the live `qevik` database password appeared in one session
transcript. No rotation requested; recorded here so the decision is on the record
rather than lost in a conversation.
