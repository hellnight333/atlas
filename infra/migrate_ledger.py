"""Copy the mission ledger from its file into Postgres. Reversible.

The file is **never modified and never deleted**. That is the rollback: point
`QEVIK_LEDGER` back at `file` and the original is exactly where it was, having
been read and nothing else. Nothing here is destructive, so nothing here needs
undoing.

Idempotent, because a migration that must be run exactly once is one somebody
will run twice. A mission event is identified by its mission id and its own
`updated_at` — the same pair `service.fold` uses to decide which event wins — so
re-running copies only what is missing.

## Historical ties, and the ordering fact used to resolve them

Fifty-five of the existing events share `(mission_id, updated_at)` with another
event, in fourteen groups. They were written before an event stamped its own
moment, so the worker's cost, scratch and report notes all inherited the
timestamp of the transition before them.

`fold` breaks such a tie by whichever event it sees last, and the file's order
is its line order. That line order is an **existing immutable fact about the
file** — not something invented here — so it is what the migrated rows are made
to reproduce: each row's `id` carries its line number, zero-padded, and the
reader orders by `(at, id)`.

`at` stays truthful — it is the event's own recorded moment — and `detail` is
copied byte for byte. Nothing is normalised, rewritten or renumbered. **No
schema change was required**, because the existing primary key can carry the
order the file already had.

    migrate_ledger.py --timeline /var/lib/qevik/control/missions.jsonl
    migrate_ledger.py --timeline … --check     # compare, copy nothing
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "kernel"))

from sqlalchemy import text  # noqa: E402

from atlas_kernel.db import SessionLocal, init_db  # noqa: E402
from atlas_kernel.mission.service import FACTORY, KIND  # noqa: E402
from atlas_kernel.mission.timeline import Timeline  # noqa: E402


def key(event: dict) -> tuple[str, str]:
    """What makes two events the same event.

    The mission and the moment it was updated — the pair `fold` already treats
    as identity. Not the row id: the file has none, and inventing one at copy
    time would make every re-run look like new events.
    """
    detail = event.get("detail") or {}
    return (str(detail.get("mission_id", "")),
            str(detail.get("updated_at", "")))


def rows_there() -> int:
    """How many mission events are stored. Not how many identities they have."""
    with SessionLocal() as session:
        return int(session.execute(
            text("SELECT count(*) FROM atlas_business_events "
                 "WHERE factory = :f AND kind = :k"),
            {"f": FACTORY, "k": KIND}).scalar() or 0)


def already_there() -> set[tuple[str, str]]:
    with SessionLocal() as session:
        rows = session.execute(
            text("""
            SELECT detail->>'mission_id' AS mission_id,
                   detail->>'updated_at' AS updated_at
            FROM atlas_business_events
            WHERE factory = :factory AND kind = :kind
            """), {"factory": FACTORY, "kind": KIND}).mappings().all()
    return {(str(r["mission_id"] or ""), str(r["updated_at"] or ""))
            for r in rows}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeline", required=True)
    parser.add_argument("--check", action="store_true",
                        help="compare and copy nothing")
    args = parser.parse_args()

    init_db()
    # Explicitly the file backend. Reading the source of a migration through
    # whatever the environment happens to say would, once the switch is thrown,
    # copy the destination onto itself.
    source = Timeline(Path(args.timeline), backend="file")
    # Numbered as read. The line an event sits on is the file's own ordering
    # fact and the only one that survives a tie.
    events = []
    for line, event in enumerate(source.read(), start=1):
        if event.get("kind") == KIND:
            events.append({**event, "_line": line})
    print(f"file:     {len(events)} mission event(s), "
          f"{source.corrupt} unparseable")

    present = already_there()
    stored = rows_there()
    # Two different questions, and conflating them printed "117 events now"
    # over 158 rows: how many *events* are there, and how many distinct
    # identities are there. The second is what idempotency turns on; the first
    # is what a person reads.
    print(f"postgres: {stored} row(s), {len(present)} distinct identit(ies)")

    missing = [e for e in events if key(e) not in present]
    print(f"to copy:  {len(missing)}")
    if args.check:
        extra = present - {key(e) for e in events}
        print(f"in postgres and not in the file: {len(extra)}")
        return 0

    with SessionLocal() as session:
        for event in missing:
            session.execute(
                text("""
                INSERT INTO atlas_business_events
                    (id, business_id, factory, kind, actor, detail, at)
                VALUES (:id, :business_id, :factory, :kind, :actor, :detail, :at)
                """),
                # The line the event came from, zero-padded so it sorts. This is
                # what preserves the file's order through a tie: `at` is equal
                # for tied events by definition, so the reader's `ORDER BY at,
                # id` falls through to this. A random id here is what made
                # seven of thirteen missions fold differently.
                {"id": f"evt-m{event['_line']:08d}-{uuid4().hex[:6]}",
                 "business_id": event.get("business_id", ""),
                 "factory": event.get("factory", FACTORY),
                 "kind": event.get("kind", KIND),
                 "actor": event.get("actor", ""),
                 # `detail` verbatim. Nothing is normalised: the historical
                 # events keep the timestamps they were written with, ties and
                 # all, and the ordering is carried by the id beside them.
                 "detail": json.dumps(event.get("detail") or {}, default=str),
                 # The moment it was recorded, not the moment it was copied.
                 # `at` orders the rows, and stamping now would file thirteen
                 # missions' history as having happened in one second.
                 "at": _at(event)})
        session.commit()
    print(f"copied:   {len(missing)}")

    after = rows_there()
    print(f"postgres: {after} row(s) now")
    return 0 if after >= stored + len(missing) else 1


def _at(event: dict) -> datetime:
    stamp = (event.get("detail") or {}).get("updated_at", "")
    try:
        return datetime.fromisoformat(str(stamp))
    except ValueError:
        return datetime.now(UTC)


if __name__ == "__main__":
    raise SystemExit(main())
