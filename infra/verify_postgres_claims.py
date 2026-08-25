#!/usr/bin/env python3
"""Watch two real processes race for one mission, against a real database.

`PostgresClaims.multiprocess_safe` is `True` because the algorithm is right.
`verified()` is the separate question of whether anybody has ever watched it
work — and the two must not be conflated, because the failure mode of an
unverified claim implementation is not an exception. It is two workers quietly
running the same mission, which looks like the system working until two commits
appear.

This is what turns the second question into a yes. It is deliberately **not** a
unit test with a database double: a double that appeared to serialise two
processes would prove a property the deployment does not have.

    python3 infra/verify_postgres_claims.py --dsn "postgresql://…/qevik_test"

Run it against a scratch database. It creates one table, races against it, and
removes its own rows.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "kernel"))

from atlas_kernel.mission.claims import (  # noqa: E402
    TABLE,
    NotVerified,
    PostgresClaims,
    describe,
)

WORKERS = 8
PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (PASSED if ok else FAILED).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))
    return ok


def _connect(dsn: str):
    import psycopg

    # autocommit=False is the point, not an incidental default: the row lock has
    # to outlive the SELECT that took it.
    return psycopg.connect(dsn, autocommit=False)


def _race(dsn: str, mission_id: str, worker: str, start_at: float, out) -> None:
    """One worker, in its own OS process, with its own connection.

    Started well before `start_at` and spinning until it arrives, so all of them
    reach the SELECT within the same millisecond. A staggered start would let the
    first finish before the second began, and the test would pass against an
    implementation with no locking at all.
    """
    claims = PostgresClaims(_connect(dsn), i_have_a_database=True)
    while time.time() < start_at:
        pass
    try:
        out.put((worker, claims.acquire(mission_id, worker=worker)))
    except Exception as error:  # noqa: BLE001 - the parent decides what it means
        out.put((worker, f"ERROR {type(error).__name__}: {error}"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", default=os.environ.get("QEVIK_CLAIMS_DSN", ""))
    parser.add_argument("--keep", action="store_true",
                        help="leave the rows behind for inspection")
    args = parser.parse_args()
    if not args.dsn:
        print("a --dsn (or QEVIK_CLAIMS_DSN) is required; this proves nothing "
              "without a real database")
        return 2

    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    mission = f"mission-verify-{stamp}"
    other = f"mission-other-{stamp}"

    print("Postgres atomic claims — two processes, one mission\n")
    print("1. The table, created by code rather than by hand")
    admin = PostgresClaims(_connect(args.dsn), i_have_a_database=True)
    admin.install()
    with admin._connection.cursor() as cursor:  # noqa: SLF001 - verification
        cursor.execute("SELECT to_regclass(%s)", (TABLE,))
        exists = cursor.fetchone()[0]
    check("the claim table exists", exists is not None, f"to_regclass → {exists}")

    admin.register(mission)
    admin.register(other)
    admin.register(mission)  # twice: registering must be idempotent
    with admin._connection.cursor() as cursor:  # noqa: SLF001
        cursor.execute(f"SELECT count(*) FROM {TABLE} WHERE mission_id = %s",
                       (mission,))
        rows = cursor.fetchone()[0]
    check("registering the same mission twice makes one row", rows == 1,
          f"{rows} rows")

    print(f"\n2. {WORKERS} processes race for {mission}")
    results: mp.Queue = mp.Queue()
    start_at = time.time() + 2.0
    procs = [mp.Process(target=_race, args=(args.dsn, mission, f"worker-{i}",
                                            start_at, results))
             for i in range(WORKERS)]
    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join(timeout=60)

    outcomes = {}
    while not results.empty():
        worker, verdict = results.get()
        outcomes[worker] = verdict
    errors = {w: v for w, v in outcomes.items() if isinstance(v, str)}
    winners = [w for w, v in outcomes.items() if v is True]

    check("every worker answered", len(outcomes) == WORKERS,
          f"{len(outcomes)} of {WORKERS}")
    check("nothing raised", not errors, json.dumps(errors))
    check("exactly one worker claimed it", len(winners) == 1,
          f"winners: {winners or 'none'}")

    holder = admin.holder(mission)
    check("the database agrees who holds it",
          bool(winners) and holder == winners[0], f"holder is {holder!r}")

    print("\n3. Negative controls — a check that always passes proves nothing")
    check("a different mission is still claimable",
          admin.acquire(other, worker="worker-solo"),
          "if this failed, the test above would pass against an "
          "implementation that refuses everything")
    check("a held mission is refused a second time",
          admin.acquire(mission, worker="worker-latecomer") is False,
          "the same call that succeeded for the winner")

    admin.release(mission, worker=winners[0] if winners else "")
    check("release frees it", admin.holder(mission) == "")
    check("and it can then be claimed again",
          admin.acquire(mission, worker="worker-after-release"))

    print("\n4. A dead worker's claim is reclaimable, and a live one's is not")
    with admin._connection.cursor() as cursor:  # noqa: SLF001
        cursor.execute(
            f"UPDATE {TABLE} SET claimed_at = %s WHERE mission_id = %s",
            (datetime.now(UTC) - timedelta(hours=2), mission))
    admin._connection.commit()  # noqa: SLF001
    check("a stale claim can be taken over",
          admin.acquire(mission, worker="worker-supervisor"),
          "otherwise a crashed worker holds a mission for ever")
    check("a fresh claim cannot",
          admin.acquire(mission, worker="worker-thief") is False)

    print("\n5. Autocommit is refused rather than silently unsafe")
    import psycopg
    loose = psycopg.connect(args.dsn, autocommit=True)
    try:
        PostgresClaims(loose, i_have_a_database=True)
        check("an autocommit connection is refused", False,
              "it was accepted — the row lock would end at the semicolon")
    except NotVerified as error:
        check("an autocommit connection is refused", True, str(error)[:70] + "…")
    finally:
        loose.close()

    if not args.keep:
        with admin._connection.cursor() as cursor:  # noqa: SLF001
            cursor.execute(
                f"DELETE FROM {TABLE} WHERE mission_id IN (%s, %s)",
                (mission, other))
        admin._connection.commit()  # noqa: SLF001

    print("\n" + "=" * 66)
    print(f"  {len(PASSED)} passed, {len(FAILED)} failed")
    print("=" * 66)
    if FAILED:
        print("\nNOT VERIFIED. " + "; ".join(FAILED))
        return 1

    print("\nVerified: " + json.dumps(describe(admin), default=str))
    print("\nThis run is the evidence. `verified()` in claims.py may be updated "
          "to accept PostgresClaims only with this output recorded beside it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
