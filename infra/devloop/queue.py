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
    -- The allowed-path contract, as a JSON list of repo-relative patterns.
    -- What the task may change; the driver compares the diff against it and
    -- refuses to land anything outside. NULL only on rows that predate the
    -- column, and such a row cannot run until somebody declares one.
    paths               TEXT,
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

-- Every review that ran, whatever it concluded. A clean review records no
-- findings, so without this there is no evidence it happened — and "no
-- findings" would be indistinguishable from "never reviewed".
CREATE TABLE IF NOT EXISTS reviews (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT NOT NULL,
    round           INTEGER NOT NULL,
    reviewed_sha    TEXT NOT NULL,
    verdict         TEXT NOT NULL,
    findings        INTEGER NOT NULL DEFAULT 0,
    at              TEXT NOT NULL
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

-- Every scope check that ran, on which commit, and what it found. The
-- declared contract, the paths actually changed and the ones outside the
-- contract are all kept, so the verdict can be read back and disagreed with
-- rather than trusted. Keyed on the commit, like a review: the landing gate
-- asks whether *this* head was measured and kept to its contract.
CREATE TABLE IF NOT EXISTS scope_checks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL,
    round       INTEGER NOT NULL,
    sha         TEXT NOT NULL,
    declared    TEXT NOT NULL,
    changed     TEXT NOT NULL,
    undeclared  TEXT NOT NULL,
    verdict     TEXT NOT NULL,
    at          TEXT NOT NULL
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


#: A pattern that matches every path is not a contract. Refused at the door
#: rather than tolerated, because a task allowed to change anything is exactly
#: the task whose scope nobody checked, wearing a field that says somebody did.
_VACUOUS = frozenset({"", ".", "/", "*", "**", "./", "*/", "**/"})


def contract(paths: list[str] | tuple[str, ...] | None) -> list[str]:
    """Normalise an allowed-path contract, or refuse it.

    Each entry is a repo-relative path, a directory (trailing `/`), or a
    glob. What makes a contract usable is that it bounds something: an empty
    list, a bare `*`, an absolute path or one that climbs out of the tree are
    all refused, since none of them names a place inside the repository that
    the diff can be held to.
    """
    if not paths:
        raise ValueError(
            "a task must declare the paths it is allowed to change. Scope "
            "stated only in the brief is scope nobody enforces.")
    cleaned: list[str] = []
    for one in paths:
        if not isinstance(one, str):
            raise ValueError(f"a path pattern must be a string, not {one!r}")
        text = one.strip()
        if text.startswith("./"):
            text = text[2:]
        if text in _VACUOUS or text.lstrip("*/") == "":
            raise ValueError(
                f"{one!r} allows every path; a contract that bounds nothing "
                f"is not a contract")
        if text.startswith("/") or ".." in text.split("/"):
            raise ValueError(
                f"{one!r} is not a path inside the repository")
        if text not in cleaned:
            cleaned.append(text)
    return cleaned


def allowed_paths(task: dict) -> list[str]:
    """The contract a task row carries, or an empty list when it has none.

    A row from before the column exists has NULL here. That is reported as no
    contract rather than as an empty one so the driver can refuse to run it
    for the right reason: not that the list is empty, but that nobody set it.
    """
    raw = task.get("paths")
    if not raw:
        return []
    try:
        loaded = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return [one for one in loaded if isinstance(one, str)] if isinstance(loaded, list) else []


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
        self._migrate()

    def _migrate(self) -> None:
        """Columns added after a database was first written.

        `CREATE TABLE IF NOT EXISTS` leaves an existing table exactly as it
        was, so a column that arrived later has to be added by hand. A row
        that predates the column keeps NULL — the honest record that no
        contract was ever declared for it, which is not the same as an empty
        one.
        """
        have = {row["name"] for row in
                self._db.execute("PRAGMA table_info(tasks)")}
        if "paths" not in have:
            self._db.execute("ALTER TABLE tasks ADD COLUMN paths TEXT")

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

    def add(self, *, title: str, brief: str, origin: str, paths: list[str],
            evidence: dict | None = None, priority: int = 50,
            requires_deploy: bool = False, requires_prod_check: bool = False,
            task_id: str = "") -> str:
        """Enqueue work. Refuses production-origin work with no evidence.

        The refusal is the point. Requirement: never generate work merely to
        keep the agents busy — so a task claiming production evidence must
        carry some, and a task with none must say plainly where it came from.

        `paths` is the allowed-path contract, and it is not optional. A task's
        scope used to live in the prose of its brief, and a builder that
        wandered out of it was caught only by somebody reading the diff
        afterwards — one did, and the breach was found after three review
        rounds had been spent on it. The contract is a list the driver can
        compare a diff against, so the comparison is made by the loop rather
        than by whoever remembers to look.
        """
        if origin == "production" and not (evidence or {}):
            raise ValueError(
                "a task whose origin is production must carry the evidence. "
                "Work with no evidence behind it is work invented to fill a "
                "queue, and that is the failure this loop exists to avoid.")
        declared = contract(paths)
        ident = task_id or f"t-{uuid.uuid4().hex[:12]}"
        with self._write() as db:
            db.execute(
                "INSERT INTO tasks (id, title, brief, state, origin, priority,"
                " evidence, requires_deploy, requires_prod_check, paths,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (ident, redact(title), redact(brief), State.QUEUED, origin,
                 int(priority), json.dumps(evidence or {}),
                 int(requires_deploy), int(requires_prod_check),
                 json.dumps(declared), _now(), _now()))
            db.execute(
                "INSERT INTO transitions (task_id, from_state, to_state, reason,"
                " actor, at) VALUES (?,?,?,?,?,?)",
                (ident, None, State.QUEUED, f"enqueued from {origin}",
                 "queue", _now()))
        return ident

    def claim(self, *, owner: str, host_reachable: bool = True) -> dict | None:
        """Take the highest-priority runnable task, atomically.

        Runnable means QUEUED, **or** in flight with an expired lease — a task
        whose driver died. That is the whole reason the lease exists: without
        it a crash at 02:00 leaves the work claimed by a process that no longer
        exists, and the queue never advances past it.
        """
        with self._write() as db:
            # A task that must deploy or be verified in production cannot
            # finish while the control plane is unreachable. Skipped rather
            # than started and failed forty minutes later at its deploy gate.
            # Built in pieces rather than by concatenating a format string:
            # `%` binds tighter than `+`, so appending a clause before the
            # substitution silently formatted the wrong fragment.
            in_flight = ",".join("?" * len(State.IN_FLIGHT))
            runnable = (
                f"SELECT * FROM tasks WHERE (state = ?"
                f" OR (state IN ({in_flight}) AND lease_expires_at IS NOT NULL"
                f" AND lease_expires_at < ?))")
            if not host_reachable:
                # A task that must deploy or be verified in production cannot
                # finish while the control plane is unreachable. Skipped rather
                # than started and failed at its deploy gate forty minutes on.
                runnable += " AND requires_deploy = 0 AND requires_prod_check = 0"
            runnable += " ORDER BY priority DESC, created_at LIMIT 1"
            row = db.execute(
                runnable,
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

    def declare_paths(self, task_id: str, paths: list[str], *,
                      actor: str, reason: str = "") -> list[str]:
        """Set or replace the contract on a task that is not in flight.

        This is how a row that predates the contract column gets one, and how
        a person widens a contract the builder ran into. It leaves a
        transition naming who set it and to what, so the contract a task was
        landed under is part of its history rather than a field somebody
        overwrote.
        """
        declared = contract(paths)
        with self._write() as db:
            row = db.execute("SELECT state FROM tasks WHERE id = ?",
                             (task_id,)).fetchone()
            if row is None:
                raise KeyError(task_id)
            if row["state"] in State.IN_FLIGHT:
                raise ValueError(
                    f"{task_id} is {row['state']}; a contract is not changed "
                    f"under a task that is being measured against it")
            db.execute("UPDATE tasks SET paths = ?, updated_at = ? WHERE id = ?",
                       (json.dumps(declared), _now(), task_id))
            db.execute(
                "INSERT INTO transitions (task_id, from_state, to_state,"
                " reason, actor, at) VALUES (?,?,?,?,?,?)",
                (task_id, row["state"], row["state"],
                 redact(f"allowed-path contract set to {declared}"
                        + (f": {reason}" if reason else "")),
                 actor, _now()))
        return declared

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

    def record_review(self, task_id: str, *, round: int, sha: str,
                      verdict: str, findings: int) -> None:
        """That a review of this commit happened, whatever it concluded."""
        with self._write() as db:
            db.execute(
                "INSERT INTO reviews (task_id, round, reviewed_sha, verdict,"
                " findings, at) VALUES (?,?,?,?,?,?)",
                (task_id, round, sha, verdict, findings, _now()))

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

    def review_was_clean(self, task_id: str) -> bool:
        """Whether the commit about to land was reviewed and left nothing blocking.

        Keyed on the **reviewed commit**, not the round number. Rounds restart
        when a task is reopened, and the first version counted findings by
        round — so a reopened task inherited its earlier run's objections and a
        genuinely clean review was refused. It failed in the safe direction and
        was still wrong.

        A commit that no review examined is not clean. That is the case this
        exists for: an unreviewed head must never reach `main`, and defaulting
        the other way is how a round that never reached the reviewer lands.
        """
        row = self._db.execute(
            "SELECT head_sha FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None or not row["head_sha"]:
            return False
        examined = self._db.execute(
            "SELECT count(*) AS n FROM findings"
            " WHERE task_id = ? AND reviewed_sha = ?",
            (task_id, row["head_sha"])).fetchone()
        reviewed = self._db.execute(
            "SELECT count(*) AS n FROM reviews"
            " WHERE task_id = ? AND reviewed_sha = ?",
            (task_id, row["head_sha"])).fetchone()
        if not int(reviewed["n"]):
            # No review of this exact commit is recorded. Findings alone cannot
            # prove one happened: a clean review records none.
            return False
        blocking = self._db.execute(
            "SELECT count(*) AS n FROM findings"
            " WHERE task_id = ? AND reviewed_sha = ?"
            "   AND severity IN ('blocking','major')",
            (task_id, row["head_sha"])).fetchone()
        return int(blocking["n"]) == 0

    # -- scope ------------------------------------------------------------

    def record_scope(self, task_id: str, *, round: int, sha: str,
                     declared: list[str], changed: list[str],
                     undeclared: list[str]) -> str:
        """What the driver measured against the contract, on which commit.

        The verdict is derived here from the lists and never passed in, so a
        record cannot say `in_scope` while naming an undeclared path.
        """
        verdict = "in_scope" if not undeclared else "out_of_scope"
        with self._write() as db:
            db.execute(
                "INSERT INTO scope_checks (task_id, round, sha, declared,"
                " changed, undeclared, verdict, at) VALUES (?,?,?,?,?,?,?,?)",
                (task_id, round, sha, json.dumps(list(declared)),
                 json.dumps(list(changed)), json.dumps(list(undeclared)),
                 verdict, _now()))
        return verdict

    def scope_was_kept(self, task_id: str) -> bool:
        """Whether the commit about to land was measured and stayed in scope.

        Keyed on the head commit for the same reason `review_was_clean` is.
        A head no scope check examined is not in scope: the record has to say
        so, and a missing record defaults to refusal, because the alternative
        is a path to `main` that a diff outside the contract can take by
        arriving at the landing gate through some route the check never saw.
        """
        row = self._db.execute(
            "SELECT head_sha FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None or not row["head_sha"]:
            return False
        latest = self._db.execute(
            "SELECT verdict FROM scope_checks WHERE task_id = ? AND sha = ?"
            " ORDER BY id DESC LIMIT 1", (task_id, row["head_sha"])).fetchone()
        return bool(latest) and latest["verdict"] == "in_scope"

    def scope_checks(self, task_id: str) -> list[dict]:
        """Every scope check for a task, oldest first, lists decoded."""
        out = []
        for row in self._db.execute(
                "SELECT * FROM scope_checks WHERE task_id = ? ORDER BY id",
                (task_id,)):
            one = dict(row)
            for key in ("declared", "changed", "undeclared"):
                one[key] = json.loads(one[key])
            out.append(one)
        return out

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

    def run(self, run_id: str) -> dict | None:
        """What one invocation did: tasks completed, failures, why it stopped."""
        row = self._db.execute("SELECT * FROM runs WHERE id = ?",
                               (run_id,)).fetchone()
        return dict(row) if row else None

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


__all__ = ["DEFAULT_DB", "LEASE", "Queue", "State", "allowed_paths", "contract", "redact"]
