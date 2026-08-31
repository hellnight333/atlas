"""The development loop's durable state. SQLite, because it must survive.

**This is not a second Qevik orchestrator.** Qevik's mission engine runs
*declared* recipes through registered tools, and `toolrunner.refusals` rejects
any step naming a tool its agent does not declare. Development is freeform by
definition, so it cannot be hosted there without breaking the one property that
makes the mission engine trustworthy. This queue orchestrates **development
agents only** and knows nothing about businesses, signals or outreach.

## Why SQLite and not the markdown ledgers

`.qevik/EXECUTION_STATE.md` is a projection a person reads. It cannot express an
atomic claim, and the failure it cannot survive is the one that actually
happens: a driver killed between "I took this task" and "I finished it". A
task's lease expires and the work becomes runnable again, which is the same
reason Qevik's own job queue uses Postgres row locks rather than a file.

The database lives under `.qevik/`, which `.gitignore` excludes except for a
named allow-list of markdown files — so this is untracked by construction, and
`README` in `.gitignore` explains that the exclusion exists because credentials
live nearby. Nothing here may hold a secret regardless: see `redact`.

## Everything is append-only except the task row itself

`transitions` records every state change with its reason. A task that ends
CONTESTED can be read backwards to the exact review round that contested it,
and a driver that died can be told apart from one that refused.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

#: Where the durable state lives. Under `.qevik/` so `.gitignore` already
#: excludes it, and beside the ledgers it projects into.
DEFAULT_DB = Path(".qevik/devloop/state.db")

#: How long a claim is good for. Long enough that a slow build is not stolen
#: mid-write, short enough that a machine which lost power at 02:00 has its work
#: back before morning.
LEASE = timedelta(minutes=90)


class State:
    """Where a task is. Terminal states are the four at the bottom."""

    QUEUED = "QUEUED"
    BUILDING = "BUILDING"
    GATING = "GATING"
    REVIEWING = "REVIEWING"
    FIXING = "FIXING"
    DEPLOYING = "DEPLOYING"
    VERIFYING = "VERIFYING"
    #: Parked at a genuine human boundary, with everything needed to resume.
    #: Not a failure and not the end of the run: the loop continues with
    #: independent work and this task becomes runnable the moment the human
    #: request it names is resolved.
    WAITING_FOR_HUMAN = "WAITING_FOR_HUMAN"
    #: Finished, gates passed, review clean.
    DONE = "DONE"
    #: Three rounds and the reviewer still objects. A person decides.
    CONTESTED = "CONTESTED"
    #: Ran into a human boundary — a credential, a decision, a machine.
    BLOCKED = "BLOCKED"
    #: The tooling failed, not the work. Retryable.
    FAILED = "FAILED"

    TERMINAL = frozenset({DONE, CONTESTED, BLOCKED, FAILED})
    #: Parked, not terminal and not runnable. `claim` skips these until the
    #: human request clears, which is what stops a blocked branch from being
    #: retried every minute against a boundary that has not moved.
    PARKED = frozenset({WAITING_FOR_HUMAN})
    #: A task in one of these was claimed by a driver that may be dead.
    IN_FLIGHT = frozenset({BUILDING, GATING, REVIEWING, FIXING, DEPLOYING,
                           VERIFYING})


#: Patterns that must never reach the database, the log, a markdown ledger or an
#: agent prompt. Applied to every string this module stores.
#:
#: Deliberately broad and deliberately dumb. A redactor that tried to understand
#: context would let through the one shape nobody thought of, and the cost of a
#: false positive here is an unreadable log line while the cost of a miss is a
#: credential in git.
_SECRET = re.compile(
    r"""(?xi)
    ( sk-[A-Za-z0-9_\-]{16,}                 # OpenAI-style keys
    | ghp_[A-Za-z0-9]{20,}                   # GitHub tokens
    | eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}   # JWTs
    | -----BEGIN[ A-Z]*PRIVATE\ KEY-----
    | \b[A-Za-z0-9._%+\-]+:[^\s@/]{6,}@      # user:password@host
    )""")

#: Environment names whose *values* must never be written anywhere.
_SECRET_ENV = ("PASSWORD", "SECRET", "TOKEN", "API_KEY", "APIKEY",
               "CREDENTIAL", "PRIVATE_KEY", "SMTP", "DSN", "DATABASE_URL")


def redact(text: str) -> str:
    """Strip anything that looks like a credential. Never optional.

    Two passes, because they catch different things: a pattern match finds a key
    whose shape is recognisable, and the environment sweep finds one whose shape
    is not but whose *value* is sitting in this process's own environment — a
    password with no distinguishing form, echoed back by a failing command.
    """
    if not text:
        return text
    out = _SECRET.sub("[REDACTED]", text)
    for name, value in os.environ.items():
        if not value or len(value) < 8:
            continue
        if any(marker in name.upper() for marker in _SECRET_ENV):
            out = out.replace(value, f"[REDACTED:{name}]")
    return out


SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id                  TEXT PRIMARY KEY,
    title               TEXT NOT NULL,
    -- What the builder is told. The task and the repository, never the
    -- roadmap: an agent handed the whole roadmap optimises for the roadmap.
    brief               TEXT NOT NULL,
    state               TEXT NOT NULL,
    -- Where this came from, so work invented to keep agents busy is visible
    -- as such. 'production' means real data supports it.
    origin              TEXT NOT NULL,
    priority            INTEGER NOT NULL DEFAULT 50,
    -- The production evidence behind it, as JSON. A task with none and an
    -- origin of 'production' is a contradiction the driver refuses.
    evidence            TEXT NOT NULL DEFAULT '{}',
    requires_deploy     INTEGER NOT NULL DEFAULT 0,
    requires_prod_check INTEGER NOT NULL DEFAULT 0,
    -- The immutable review unit. `base_sha` is fixed when the build starts;
    -- the diff Codex reviews is base..HEAD and cannot move under it.
    base_sha            TEXT,
    head_sha            TEXT,
    review_rounds       INTEGER NOT NULL DEFAULT 0,
    attempts            INTEGER NOT NULL DEFAULT 0,
    -- The human request this task waits on, by the canonical id the control
    -- plane derives. Not a copy of the request: the id is the reference, and
    -- the request itself lives where every other human action lives.
    blocked_by          TEXT,
    -- Where to pick the task up. A resolved boundary must not restart work
    -- that was already reviewed and gated.
    resume_stage        TEXT,
    -- The commit the parked work sits on, so resumption is against the tree
    -- that produced it rather than whatever HEAD has become.
    resume_sha          TEXT,
    driver_run_id       TEXT,
    lease_owner         TEXT,
    lease_expires_at    TEXT,
    detail              TEXT NOT NULL DEFAULT '',
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

-- Every state change, with why. Append-only: a task that ended CONTESTED can
-- be read backwards to the round that contested it.
CREATE TABLE IF NOT EXISTS transitions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL,
    from_state  TEXT,
    to_state    TEXT NOT NULL,
    reason      TEXT NOT NULL DEFAULT '',
    actor       TEXT NOT NULL DEFAULT '',
    at          TEXT NOT NULL
);

-- What the reviewer said, per round, kept whether or not it was acted on.
CREATE TABLE IF NOT EXISTS findings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT NOT NULL,
    round           INTEGER NOT NULL,
    severity        TEXT NOT NULL,
    file            TEXT NOT NULL,
    claim           TEXT NOT NULL,
    why_it_matters  TEXT NOT NULL,
    failure_scenario TEXT NOT NULL,
    reviewed_sha    TEXT NOT NULL DEFAULT '',
    at              TEXT NOT NULL
);

-- One driver invocation, so per-run limits survive a restart.
CREATE TABLE IF NOT EXISTS runs (
    id              TEXT PRIMARY KEY,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    tasks_completed INTEGER NOT NULL DEFAULT 0,
    infra_failures  INTEGER NOT NULL DEFAULT 0,
    stopped_because TEXT NOT NULL DEFAULT ''
);

-- Reviewer health. A reviewer that stops finding a defect it is shown is a
-- reviewer that has stopped reviewing, and the loop must not run past that.
CREATE TABLE IF NOT EXISTS reviewer_health (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    at          TEXT NOT NULL,
    detected    INTEGER NOT NULL,
    detail      TEXT NOT NULL DEFAULT ''
);

-- Third-party projects to assess before anything is integrated. Nothing here
-- is a dependency; it is a queue of things somebody must look at first.
CREATE TABLE IF NOT EXISTS evaluations (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    url         TEXT NOT NULL,
    why         TEXT NOT NULL DEFAULT '',
    state       TEXT NOT NULL DEFAULT 'UNEVALUATED',
    verdict     TEXT NOT NULL DEFAULT '',
    at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS tasks_runnable ON tasks (state, priority DESC);
CREATE INDEX IF NOT EXISTS transitions_task ON transitions (task_id, id);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Queue:
    """The driver's durable state. One writer at a time, by design.

    Opened with `WAL` so a reader — the projection writer, a person running
    `status` — never blocks the driver, and with `IMMEDIATE` transactions for
    the claim so two drivers cannot take the same task.
    """

    def __init__(self, path: Path | str = DEFAULT_DB) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path), timeout=30,
                                   isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        self._db.close()

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        """One atomic write. `IMMEDIATE` so a concurrent claim loses the race."""
        for attempt in range(6):
            try:
                self._db.execute("BEGIN IMMEDIATE")
                break
            except sqlite3.OperationalError:
                if attempt == 5:
                    raise
                time.sleep(0.4 * (attempt + 1))
        try:
            yield self._db
            self._db.execute("COMMIT")
        except Exception:
            self._db.execute("ROLLBACK")
            raise

    # -- tasks ------------------------------------------------------------

    def add(self, *, title: str, brief: str, origin: str,
            evidence: dict | None = None, priority: int = 50,
            requires_deploy: bool = False, requires_prod_check: bool = False,
            task_id: str = "") -> str:
        """Enqueue work. Refuses production-origin work with no evidence.

        The refusal is the point. Requirement: never generate work merely to
        keep the agents busy — so a task claiming production evidence must
        carry some, and a task with none must say plainly where it came from.
        """
        if origin == "production" and not (evidence or {}):
            raise ValueError(
                "a task whose origin is production must carry the evidence. "
                "Work with no evidence behind it is work invented to fill a "
                "queue, and that is the failure this loop exists to avoid.")
        ident = task_id or f"t-{uuid.uuid4().hex[:12]}"
        with self._write() as db:
            db.execute(
                "INSERT INTO tasks (id, title, brief, state, origin, priority,"
                " evidence, requires_deploy, requires_prod_check, created_at,"
                " updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (ident, redact(title), redact(brief), State.QUEUED, origin,
                 int(priority), json.dumps(evidence or {}),
                 int(requires_deploy), int(requires_prod_check), _now(), _now()))
            db.execute(
                "INSERT INTO transitions (task_id, from_state, to_state, reason,"
                " actor, at) VALUES (?,?,?,?,?,?)",
                (ident, None, State.QUEUED, f"enqueued from {origin}",
                 "queue", _now()))
        return ident

    def claim(self, *, owner: str) -> dict | None:
        """Take the highest-priority runnable task, atomically.

        Runnable means QUEUED, **or** in flight with an expired lease — a task
        whose driver died. That is the whole reason the lease exists: without
        it a crash at 02:00 leaves the work claimed by a process that no longer
        exists, and the queue never advances past it.
        """
        with self._write() as db:
            row = db.execute(
                "SELECT * FROM tasks WHERE state = ? OR (state IN"
                " (%s) AND lease_expires_at IS NOT NULL AND lease_expires_at < ?)"
                " ORDER BY priority DESC, created_at LIMIT 1"
                % ",".join("?" * len(State.IN_FLIGHT)),
                (State.QUEUED, *sorted(State.IN_FLIGHT), _now())).fetchone()
            # WAITING_FOR_HUMAN is absent from IN_FLIGHT on purpose: a parked
            # task has no lease to expire, so it can never be reclaimed by a
            # timeout. Only `release` moves it back.
            if row is None:
                return None
            expires = (datetime.now(UTC) + LEASE).isoformat()
            reclaimed = row["state"] != State.QUEUED
            db.execute(
                "UPDATE tasks SET state = ?, lease_owner = ?,"
                " lease_expires_at = ?, attempts = attempts + 1, updated_at = ?"
                " WHERE id = ?",
                (State.BUILDING, owner, expires, _now(), row["id"]))
            db.execute(
                "INSERT INTO transitions (task_id, from_state, to_state, reason,"
                " actor, at) VALUES (?,?,?,?,?,?)",
                (row["id"], row["state"], State.BUILDING,
                 "reclaimed after an expired lease" if reclaimed else "claimed",
                 owner, _now()))
            return dict(db.execute("SELECT * FROM tasks WHERE id = ?",
                                   (row["id"],)).fetchone())

    def move(self, task_id: str, to: str, *, reason: str = "",
             actor: str = "driver", **fields: Any) -> None:
        """Record a state change and whatever it decided. Always logged."""
        with self._write() as db:
            current = db.execute("SELECT state FROM tasks WHERE id = ?",
                                 (task_id,)).fetchone()
            sets, values = ["state = ?", "updated_at = ?"], [to, _now()]
            for key, value in fields.items():
                sets.append(f"{key} = ?")
                values.append(redact(value) if isinstance(value, str) else value)
            if to in State.TERMINAL or to in State.PARKED:
                # A parked task has no lease on purpose. It is not runnable, so
                # a lease on it could only ever expire and suggest an
                # abandonment that never happened — and `claim` would still
                # never pick it up, because PARKED is not IN_FLIGHT. Only
                # `release` makes it runnable again.
                sets += ["lease_owner = NULL", "lease_expires_at = NULL"]
            db.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?",
                       (*values, task_id))
            db.execute(
                "INSERT INTO transitions (task_id, from_state, to_state, reason,"
                " actor, at) VALUES (?,?,?,?,?,?)",
                (task_id, current["state"] if current else None, to,
                 redact(reason)[:2000], actor, _now()))

    def park(self, task_id: str, *, request_id: str, stage: str, sha: str,
             reason: str, run_id: str = "") -> None:
        """Hold this task at a human boundary, with enough to resume it.

        Everything the resumption needs is written here rather than left in a
        dead process's memory: which request it waits on, which stage it had
        reached, and the commit it reached it on. A task that restarts from the
        beginning after a two-day wait throws away reviewed, gated work.
        """
        self.move(task_id, State.WAITING_FOR_HUMAN, reason=reason,
                  blocked_by=request_id, resume_stage=stage, resume_sha=sha,
                  driver_run_id=run_id)

    def release(self, task_id: str, *, because: str) -> None:
        """The boundary cleared. The task is runnable again from its stage."""
        self.move(task_id, State.QUEUED, reason=f"unparked: {because}"[:500])

    def waiting_on_human(self) -> list[dict]:
        """Every parked task, so one resolved request can free all of them."""
        return [dict(r) for r in self._db.execute(
            "SELECT * FROM tasks WHERE state = ? ORDER BY priority DESC",
            (State.WAITING_FOR_HUMAN,))]

    def blocked_by(self, request_id: str) -> list[dict]:
        """Which execution tasks one human request holds up."""
        return [dict(r) for r in self._db.execute(
            "SELECT * FROM tasks WHERE blocked_by = ? AND state = ?",
            (request_id, State.WAITING_FOR_HUMAN))]

    def renew(self, task_id: str) -> None:
        """Extend the lease. Called between phases of a long task."""
        with self._write() as db:
            db.execute("UPDATE tasks SET lease_expires_at = ?, updated_at = ?"
                       " WHERE id = ?",
                       ((datetime.now(UTC) + LEASE).isoformat(), _now(),
                        task_id))

    def get(self, task_id: str) -> dict | None:
        row = self._db.execute("SELECT * FROM tasks WHERE id = ?",
                               (task_id,)).fetchone()
        return dict(row) if row else None

    def tasks(self, *, state: str | None = None) -> list[dict]:
        sql = "SELECT * FROM tasks"
        args: tuple = ()
        if state:
            sql += " WHERE state = ?"
            args = (state,)
        sql += " ORDER BY priority DESC, created_at"
        return [dict(r) for r in self._db.execute(sql, args)]

    def transitions(self, task_id: str) -> list[dict]:
        return [dict(r) for r in self._db.execute(
            "SELECT * FROM transitions WHERE task_id = ? ORDER BY id",
            (task_id,))]

    # -- findings ---------------------------------------------------------

    def record_findings(self, task_id: str, *, round: int, sha: str,
                        findings: list[dict]) -> None:
        with self._write() as db:
            for one in findings:
                db.execute(
                    "INSERT INTO findings (task_id, round, severity, file,"
                    " claim, why_it_matters, failure_scenario, reviewed_sha, at)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (task_id, round, one.get("severity", ""),
                     one.get("file", ""), redact(one.get("claim", "")),
                     redact(one.get("why_it_matters", "")),
                     redact(one.get("failure_scenario", "")), sha, _now()))

    def findings(self, task_id: str, *, round: int | None = None) -> list[dict]:
        sql = "SELECT * FROM findings WHERE task_id = ?"
        args: tuple = (task_id,)
        if round is not None:
            sql += " AND round = ?"
            args += (round,)
        return [dict(r) for r in self._db.execute(sql + " ORDER BY id", args)]

    # -- runs and reviewer health ----------------------------------------

    def start_run(self) -> str:
        ident = f"r-{uuid.uuid4().hex[:10]}"
        with self._write() as db:
            db.execute("INSERT INTO runs (id, started_at) VALUES (?,?)",
                       (ident, _now()))
        return ident

    def finish_run(self, run_id: str, *, because: str) -> None:
        with self._write() as db:
            db.execute("UPDATE runs SET finished_at = ?, stopped_because = ?"
                       " WHERE id = ?", (_now(), redact(because)[:500], run_id))

    def bump_run(self, run_id: str, *, completed: int = 0,
                 infra_failures: int = 0) -> dict:
        with self._write() as db:
            db.execute("UPDATE runs SET tasks_completed = tasks_completed + ?,"
                       " infra_failures = infra_failures + ? WHERE id = ?",
                       (completed, infra_failures, run_id))
            return dict(db.execute("SELECT * FROM runs WHERE id = ?",
                                   (run_id,)).fetchone())

    def record_reviewer_health(self, *, detected: bool, detail: str) -> None:
        with self._write() as db:
            db.execute("INSERT INTO reviewer_health (at, detected, detail)"
                       " VALUES (?,?,?)", (_now(), int(detected),
                                           redact(detail)[:1000]))

    def last_reviewer_health(self) -> dict | None:
        row = self._db.execute(
            "SELECT * FROM reviewer_health ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    # -- evaluations ------------------------------------------------------

    def add_evaluation(self, *, name: str, url: str, why: str) -> str:
        ident = f"e-{uuid.uuid4().hex[:8]}"
        with self._write() as db:
            existing = db.execute("SELECT id FROM evaluations WHERE url = ?",
                                  (url,)).fetchone()
            if existing:
                return existing["id"]
            db.execute("INSERT INTO evaluations (id, name, url, why, at)"
                       " VALUES (?,?,?,?,?)", (ident, name, url, why, _now()))
        return ident

    def evaluations(self) -> list[dict]:
        return [dict(r) for r in self._db.execute(
            "SELECT * FROM evaluations ORDER BY at")]


__all__ = ["DEFAULT_DB", "LEASE", "Queue", "State", "redact"]
