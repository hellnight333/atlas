"""Recurring work, proven against real processes rather than asserted.

The unit tests cover the decision. This covers the thing unit tests cannot: two
worker processes ticking the same recurrence at the same instant, against one
Postgres, and whether that produces one mission or two.

    python3 infra/verify_recurrence.py [--dsn postgresql://...]

Without a DSN it runs everything except the two-process race and says so. It
does not quietly pass a race it never ran — the whole reason this file exists is
that "we assume the lock works" is how a duplicate reaches production.
"""

from __future__ import annotations

import argparse
import multiprocessing as mp
import os
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "kernel"))

from atlas_kernel.mission import recurrence, service  # noqa: E402
from atlas_kernel.mission.claims import LocalClaims, PostgresClaims  # noqa: E402
from atlas_kernel.mission.models import MissionStatus, Plan, PlanStep  # noqa: E402
from atlas_kernel.mission.timeline import Timeline  # noqa: E402

TENANT = "tenant-recurrence-proof"
ANCHOR = datetime(2026, 8, 1, 2, 0, tzinfo=UTC)
DAY = timedelta(days=1)

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (PASSED if ok else FAILED).append(name)
    print(f"{'  ok  ' if ok else '  FAIL'}  {name}{'  — ' + detail if detail else ''}")
    return ok


def a_recurrence(**over) -> recurrence.Recurrence:
    fields = dict(
        id="rec-proof", tenant_id=TENANT, title="Recurring proof",
        plan=Plan(goal="prove the recurring path end to end",
                  steps=(PlanStep(order=1, title="check", files=("reports/r.md",)),),
                  estimated_cost=0.25, approval_required=False),
        agent_id="self-check", every=DAY, anchor=ANCHOR,
        modifies_qevik_itself=False)
    fields.update(over)
    return recurrence.Recurrence(**fields)


# --------------------------------------------------------- durable, not in memory

def durability(tmp: Path) -> None:
    """A recurrence's mission survives the process that created it."""
    path = tmp / "missions.jsonl"
    rule = a_recurrence()

    timeline = Timeline(path)
    firing = recurrence.assess(rule, at=ANCHOR, missions=[])
    mission, events = recurrence.enqueue(rule, firing, tenant=TENANT)
    for event in events:
        timeline.append(event)
    created_id = mission.id

    # A different Timeline object over the same file — the closest a single
    # process gets to "the worker restarted".
    reread = service.fold(Timeline(path).read(), tenant=TENANT)
    check("a recurring mission is durable, not in memory",
          any(m["mission_id"] == created_id for m in reread))

    found = next(m for m in reread if m["mission_id"] == created_id)
    check("the occurrence key survives the round trip",
          found.get("occurrence") == firing.key, str(found.get("occurrence")))
    check("a non-self-modifying recurrence reaches the queue without a person",
          found["status"] == MissionStatus.QUEUED.value, found["status"])

    # And the same tick again creates nothing.
    again = recurrence.assess(rule, at=ANCHOR + timedelta(hours=6),
                              missions=reread)
    check("ticking again does not create a second mission for the occurrence",
          not again.fires and again.hold is recurrence.Hold.ALREADY_CREATED,
          again.detail)

    # A different tenant must not see it at all — absent, not forbidden.
    other = service.fold(Timeline(path).read(), tenant="tenant-someone-else")
    check("another tenant sees no recurring mission at all", other == [],
          f"{len(other)} visible")


def self_modifying_waits(tmp: Path) -> None:
    """A schedule is not a person."""
    rule = a_recurrence(id="rec-self", modifies_qevik_itself=True)
    mission, _ = recurrence.enqueue(
        rule, recurrence.assess(rule, at=ANCHOR, missions=[]), tenant=TENANT)
    check("a recurrence that touches Qevik's source waits for approval",
          mission.status is MissionStatus.AWAITING_APPROVAL,
          mission.status.value)

    try:
        service.claim(mission, worker="w-x", tenant=TENANT)
        check("...and a worker cannot claim it anyway", False, "it was claimed")
    except service.NotPermitted as refusal:
        check("...and a worker cannot claim it anyway", True, str(refusal)[:60])


def registry_is_honest() -> None:
    """The declared set must not contain a claim we cannot stand behind."""
    check("no declared recurrence claims to be non-self-modifying while the "
          "worker runs inside Qevik's own repository",
          all(r.modifies_qevik_itself for r in recurrence.RECURRENCES)
          or not recurrence.RECURRENCES,
          f"{len(recurrence.RECURRENCES)} declared")


# ------------------------------------------------------------- the actual race

def plain(dsn: str) -> str:
    """A psycopg-parsable DSN. `ATLAS_DATABASE_URL` is the SQLAlchemy form
    (`postgresql+psycopg://`), which psycopg rejects — and its rejection quotes
    the whole string back, password included."""
    return dsn.replace("postgresql+psycopg://", "postgresql://", 1) \
              .replace("postgres+psycopg://", "postgresql://", 1)


def _redacted(err: BaseException) -> str:
    """An error message with no credential in it.

    Written after a real incident in this file: a connection failure put the
    database password into a log, because psycopg quotes the conninfo string
    verbatim and the redaction lived in the shell command rather than here. A
    redaction that has to be remembered at each call site is one that will be
    forgotten at one of them.
    """
    import re
    text = f"{type(err).__name__}: {err}"
    text = re.sub(r"(?i)(postgres(?:ql)?(?:\+\w+)?://)[^\s\"\']*", r"\1<redacted>", text)
    return re.sub(r"://[^@/\s]*@", "://<redacted>@", text)[:300]


def _tick(dsn: str, key: str, name: str, queue) -> None:
    """One process attempting to hold one occurrence key."""
    import psycopg
    try:
        claims = PostgresClaims(psycopg.connect(plain(dsn), autocommit=False),
                                i_have_a_database=True)
        claims.install()
        claims.register(key)
        queue.put((name, claims.acquire(key, worker=name)))
    except BaseException as err:                   # noqa: BLE001 - redacted, not raised
        queue.put((name, f"ERROR {_redacted(err)}"))


def race(dsn: str) -> None:
    """Two processes, one occurrence, one Postgres. Exactly one may win."""
    key = recurrence.key_for("rec-race", datetime.now(UTC).replace(microsecond=0))
    queue = mp.Queue()
    procs = [mp.Process(target=_tick, args=(dsn, key, f"worker-{i}", queue))
             for i in (1, 2)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(30)
    results = [queue.get() for _ in range(2)]
    broken = [r for r in results if isinstance(r[1], str)]
    if broken:
        check("the two-process race ran at all", False, str(broken))
        return
    winners = [n for n, won in results if won]
    check("two processes ticking the same occurrence: exactly one creates it",
          len(winners) == 1, f"winners={winners} results={results}")

    # The negative control. Without the cross-process lock, both "win" — so the
    # test above is measuring the lock and not merely the arithmetic.
    local = [LocalClaims(), LocalClaims()]
    both = [c.acquire("rec-control@x", worker=f"w{i}") for i, c in enumerate(local)]
    check("negative control: two independent in-process locks both succeed, "
          "which is what the Postgres lock is preventing", all(both), str(both))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", default=os.environ.get("QEVIK_CLAIMS_DSN", ""))
    args = parser.parse_args(argv)

    print("recurrence — real processes\n")
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        durability(tmp)
        self_modifying_waits(tmp)
        registry_is_honest()

    if args.dsn:
        race(args.dsn)
    else:
        print("  SKIP  the two-process race — no --dsn given. NOT VERIFIED "
              "here; this is not a pass.")

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
