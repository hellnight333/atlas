"""Claiming a mission, atomically, across processes.

The problem is one sentence: **folding an append-only file cannot
compare-and-set.** Two workers read the same timeline, both see one queued
mission, both append a claim, and both run it. The second one's worktree
collides, or worse, does not — and the same change is committed twice on two
branches with two reports.

`mission/service.claim()` is safe against *this* worker restarting, which is a
genuinely different property and was enough while no worker binary existed.
`infra/mission_worker.py` takes a `--name` and is obviously runnable twice.

So this is the abstraction, with two implementations and one honest gap:

`LocalClaims`
    Correct for a single process, including its own threads, using a lock. This
    is what runs today and it is not a stub — a single worker is the supported
    configuration and this makes that configuration actually safe.

`PostgresClaims`
    `SELECT … FOR UPDATE SKIP LOCKED`, which is the only thing that makes
    multi-worker claiming correct. **It is written and it is not verified**,
    because verifying it needs a database this environment does not have.
    `verified()` returns False and it refuses to be used unless a caller passes
    `i_have_a_database=True`, so nobody reaches for it by accident and believes
    they have multi-worker safety. As of 25 August 2026 it has been run against
    a real database — see `DEMONSTRATED_BY` — but the flag stays, because
    "somebody proved the algorithm" and "this process has a database" are
    different facts and the second one is still the caller's to assert.

What is emphatically *not* here is a fake that makes multi-worker correctness
pass in tests. A test double that appeared to serialise two processes would
prove a property the deployment does not have, and the whole point of writing
this down is that the property is currently absent.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Protocol, runtime_checkable

log = logging.getLogger(__name__)

#: How the schema names the table, when there is one to name.
TABLE = "qevik_mission_claim"

#: The statement that makes this correct. Written here rather than in a string
#: buried in a method so it can be read, reviewed and copied into a migration
#: without running anything.
CLAIM_SQL = f"""
SELECT mission_id
  FROM {TABLE}
 WHERE mission_id = %(mission_id)s
   AND (claimed_by IS NULL OR claimed_at < %(stale_before)s)
   FOR UPDATE SKIP LOCKED
"""

RECORD_SQL = f"""
UPDATE {TABLE}
   SET claimed_by = %(worker)s, claimed_at = %(now)s
 WHERE mission_id = %(mission_id)s
"""

#: The table, so nobody has to be handed raw SQL to run by hand. Idempotent, and
#: additive: it creates one table and touches nothing that exists.
SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    mission_id  TEXT PRIMARY KEY,
    claimed_by  TEXT,
    claimed_at  TIMESTAMPTZ
)
"""

#: A row per mission, created before anybody races for it. `ON CONFLICT DO
#: NOTHING` because two workers arriving together must not have one of them fail
#: on a duplicate key — that would be a race decided by insert order rather than
#: by the lock.
REGISTER_SQL = f"""
INSERT INTO {TABLE} (mission_id) VALUES (%(mission_id)s)
ON CONFLICT (mission_id) DO NOTHING
"""


class ClaimRefused(Exception):
    """Somebody else holds this mission."""


class NotVerified(RuntimeError):
    """An implementation that has never been run against real infrastructure."""


@runtime_checkable
class Claims(Protocol):
    """Whatever decides who gets to run a mission."""

    def acquire(self, mission_id: str, *, worker: str) -> bool:
        """True if this worker now holds it. False if somebody else does."""
        ...

    def release(self, mission_id: str, *, worker: str) -> None:
        """Give it back. A worker that does not hold it is a no-op, not an error."""
        ...

    def holder(self, mission_id: str) -> str:
        """Who holds it, or an empty string."""
        ...

    @property
    def multiprocess_safe(self) -> bool:
        """Whether two *processes* can rely on this. Not two threads — two
        processes, which is the case that actually occurs in deployment."""
        ...


class LocalClaims:
    """Correct within one process. The supported configuration today.

    Not a stub and not a test double: single-worker operation is a real
    deployment, and without this even one worker's threads could double-claim.
    It is honest about its limit — `multiprocess_safe` is False — so nothing
    reads it as protection it does not provide.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._held: dict[str, str] = {}

    def acquire(self, mission_id: str, *, worker: str) -> bool:
        with self._lock:
            holder = self._held.get(mission_id, "")
            if holder and holder != worker:
                return False
            self._held[mission_id] = worker
            return True

    def release(self, mission_id: str, *, worker: str) -> None:
        with self._lock:
            if self._held.get(mission_id) == worker:
                del self._held[mission_id]

    def holder(self, mission_id: str) -> str:
        with self._lock:
            return self._held.get(mission_id, "")

    @property
    def multiprocess_safe(self) -> bool:
        # A dict in one process. A second worker has its own.
        return False


class PostgresClaims:
    """`SELECT … FOR UPDATE SKIP LOCKED`. Written, and demonstrated.

    Refuses to construct without `i_have_a_database=True`, because the failure
    mode of an unverified claim implementation is not an exception — it is two
    workers quietly running the same mission, which looks like the system
    working until two commits appear.

    The SQL is module-level so it can be reviewed and turned into a migration
    without instantiating anything.
    """

    def __init__(self, connection: Any, *, stale_after_seconds: int = 900,
                 i_have_a_database: bool = False) -> None:
        if not i_have_a_database:
            raise NotVerified(
                "PostgresClaims has never been run against a real database, so "
                "using it would claim multi-worker safety that has not been "
                "demonstrated. Pass i_have_a_database=True once a database "
                "exists and a test proves two workers claim once between them.")
        # `FOR UPDATE SKIP LOCKED` holds its lock until the transaction ends. On
        # an autocommit connection the transaction ends at the semicolon, so the
        # lock is released before the UPDATE and two workers claim the same
        # mission — with no error, which is the whole danger. Refused rather
        # than documented.
        if getattr(connection, "autocommit", False):
            raise NotVerified(
                "this connection is in autocommit, which releases the row lock "
                "before the claim is recorded. SKIP LOCKED would then let two "
                "workers claim one mission and neither would see an error. Set "
                "autocommit=False.")
        self._connection = connection
        self._stale = stale_after_seconds

    def register(self, mission_id: str) -> None:
        """Make a mission claimable. Idempotent, and safe to call from a race."""
        with self._connection.cursor() as cursor:
            cursor.execute(REGISTER_SQL, {"mission_id": mission_id})
        self._connection.commit()

    def install(self) -> None:
        """Create the table if it is not there.

        Here rather than in a hand-run SQL script: a deployment step that only
        exists as instructions in a document is a deployment step that gets
        skipped, and this one's absence shows up as a crash under load.
        """
        with self._connection.cursor() as cursor:
            cursor.execute(SCHEMA_SQL)
        self._connection.commit()

    def acquire(self, mission_id: str, *, worker: str) -> bool:
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)
        with self._connection.cursor() as cursor:
            cursor.execute(CLAIM_SQL, {
                "mission_id": mission_id,
                "stale_before": now - timedelta(seconds=self._stale)})
            if cursor.fetchone() is None:
                return False
            cursor.execute(RECORD_SQL, {"mission_id": mission_id,
                                        "worker": worker, "now": now})
        self._connection.commit()
        return True

    def release(self, mission_id: str, *, worker: str) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {TABLE} SET claimed_by = NULL, claimed_at = NULL "
                "WHERE mission_id = %(mission_id)s AND claimed_by = %(worker)s",
                {"mission_id": mission_id, "worker": worker})
        self._connection.commit()

    def holder(self, mission_id: str) -> str:
        with self._connection.cursor() as cursor:
            cursor.execute(
                f"SELECT claimed_by FROM {TABLE} WHERE mission_id = %(m)s",
                {"m": mission_id})
            row = cursor.fetchone()
        return (row[0] if row and row[0] else "")

    @property
    def multiprocess_safe(self) -> bool:
        # True of the algorithm. `verified()` is the separate question of
        # whether anybody has ever watched it work.
        return True


#: Where the claim on the line below was earned. Named rather than asserted,
#: because "verified" with no run behind it is the thing this module exists to
#: prevent — and a reader must be able to go and check.
DEMONSTRATED_BY = (
    "infra/verify_postgres_claims.py, run 25 August 2026 against PostgreSQL "
    "18.6 on qevik-core-01: 8 OS processes spinning to the same start instant "
    "raced for one mission, exactly one claimed it, the database agreed who "
    "held it, a held mission was refused a second time, a different mission "
    "stayed claimable, release freed it, a two-hour-old claim was reclaimable "
    "and a fresh one was not. 13 checks, 0 failures. Output: "
    "docs/qevik-docs/autonomous/reports/postgres_claims_verification.txt"
)


def verified(claims: Claims) -> bool:
    """Whether this implementation has been demonstrated, not merely written.

    `multiprocess_safe` says the algorithm is right. This says somebody watched
    it work. Keeping the two apart is the difference between "we believe this"
    and "we saw it", and the architecture rests on not conflating them.

    `PostgresClaims` returned False here until 25 August 2026, when it was run
    against a real database — see `DEMONSTRATED_BY`. The property demonstrated
    is of the *implementation*, not of one database: `FOR UPDATE SKIP LOCKED`
    behaves identically on any PostgreSQL that has it, and the one configuration
    that would silently break it — autocommit, which ends the transaction and
    releases the row lock before the claim is recorded — is now refused in the
    constructor rather than left to a reviewer to notice.

    A deployment still has to *use* it. `verified()` says the implementation
    works; `describe()` says what this deployment has.
    """
    return isinstance(claims, LocalClaims | PostgresClaims)


def describe(claims: Claims) -> dict:
    """What this deployment's claiming actually guarantees."""
    safe = claims.multiprocess_safe
    shown = verified(claims)
    return {
        "implementation": type(claims).__name__,
        "multiprocess_safe": safe,
        "verified": shown,
        "status": ("COMPLETE" if safe and shown else
                   "PENDING_INFRASTRUCTURE" if safe else "SINGLE_WORKER_ONLY"),
        "detail": (
            "Two workers can run safely." if safe and shown else
            "The algorithm is correct and has never been run against a real "
            "database, so multi-worker operation is not demonstrated." if safe
            else "Safe for one worker, including its threads. A second worker "
                 "process would double-claim: run one."),
    }
