"""A mission timeline on disk, shared by processes that never meet.

The HTTP surface and the worker are separate processes on purpose — that is the
whole reason closing a browser tab cannot kill a deployment. But separate
processes need somewhere to meet, and the meeting place has to survive both of
them restarting.

This is that place: one append-only JSONL file. Not a queue, not a lock, not a
message bus. The HTTP process appends an approval and forgets about it; the
worker reads the file, folds it, finds a queued mission and takes it. Neither
holds a handle to the other, and either can be restarted mid-flight.

**Appends are atomic per line.** Opened `"a"` and written in one `write()` call
with the newline included, so two processes appending concurrently interleave
whole lines rather than shredding each other's JSON. That is a POSIX guarantee
for writes under `PIPE_BUF` to a file opened in append mode, and it is why this
does not need a lock file.

**A corrupt line is skipped, not fatal.** A timeline that refuses to load
because of one bad line takes down every mission that came before it, which is
a much worse failure than losing one record — and the loss is reported rather
than silent.

The honest limitation, stated rather than hidden: this makes `claim()` safe
against a *single* worker restarting, not against two workers racing. Folding a
file cannot compare-and-set. Multi-worker operation needs a database row with
`SELECT … FOR UPDATE SKIP LOCKED`, which is recorded as PENDING_INFRASTRUCTURE
in the service module and is not pretended away here.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from uuid import uuid4
from collections.abc import Iterator
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


#: Which store holds the ledger. Read once, from the environment, and never
#: guessed.
#:
#: `file` is still the default. A deployment moves deliberately, and a default
#: that changed underneath one would be the migration happening by surprise.
ENVIRONMENT = "QEVIK_LEDGER"
FILE = "file"
POSTGRES = "postgres"
BACKENDS = frozenset({FILE, POSTGRES})


class LedgerUnavailable(RuntimeError):
    """The configured store could not be reached.

    Its own type because the one thing that must not happen here is a fallback.
    A ledger that quietly reverted to the local file when the database was away
    would give an off-host worker an empty queue and a local one a private
    history, and neither would report anything wrong.
    """


class Timeline:
    """Append-only mission events. Read by folding, never by seeking.

    Two stores, one interface. The file came first and still works; Postgres
    exists because **a file is only reachable from the machine it is on**, and a
    worker on another machine cannot see a queue it cannot read.

    The events are unchanged — `service._event` has always produced a
    `BusinessEvent`, and `atlas_business_events` is the append-only table that
    already holds the review, publication and outreach decisions. This is not a
    new store; it is the events Qevik already writes going to the table Qevik
    already has.

    Ordering is not part of the contract and never was. `service.fold` takes the
    latest event by its own `updated_at` precisely so that replay order cannot
    matter, which is what makes reading these rows from a database — in whatever
    order it returns them — equivalent to reading the file.
    """

    def __init__(self, path: Path | str, *, backend: str | None = None) -> None:
        self.path = Path(path)
        #: Lines that would not parse. Counted rather than raised, and exposed so
        #: a health check can notice a timeline quietly rotting.
        self.corrupt = 0
        chosen = backend or os.environ.get(ENVIRONMENT, FILE)
        if chosen not in BACKENDS:
            raise ValueError(
                f"{chosen!r} is not a ledger backend. Known: "
                f"{', '.join(sorted(BACKENDS))}.")
        self.backend = chosen

    @property
    def networked(self) -> bool:
        """Whether a process on another machine could read this."""
        return self.backend == POSTGRES

    def append(self, event: Any) -> None:
        """One event, one write. Never both stores."""
        record = _record(event)
        if self.backend == POSTGRES:
            return self._append_row(record)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str) + "\n")
            handle.flush()
            # The worker may be a different process reading this file within
            # milliseconds. Buffered-but-unwritten is indistinguishable from
            # lost to that reader.
            os.fsync(handle.fileno())
        return None

    def _append_row(self, record: dict) -> None:
        """One event, one row, into the table the decisions already live in."""
        from sqlalchemy import text

        from ..db import SessionLocal

        try:
            with SessionLocal() as session:
                session.execute(
                    text("""
                    INSERT INTO atlas_business_events
                        (id, business_id, factory, kind, actor, detail, at)
                    VALUES (:id, :business_id, :factory, :kind, :actor,
                            :detail, :at)
                    """),
                    {"id": f"evt-{uuid4().hex[:12]}",
                     "business_id": record.get("business_id", ""),
                     "factory": record.get("factory", ""),
                     "kind": record.get("kind", ""),
                     "actor": record.get("actor", ""),
                     "detail": json.dumps(record.get("detail") or {},
                                          default=str),
                     "at": datetime.now(UTC)})
                session.commit()
        except Exception as unreachable:           # noqa: BLE001 - re-raised
            # Raised, never swallowed. See `LedgerUnavailable`: a fallback here
            # is a split-brain queue nobody is told about.
            raise LedgerUnavailable(
                f"could not append to the ledger: {unreachable}"[:300]
            ) from unreachable

    def read(self) -> list[dict]:
        """Every event, oldest first, skipping anything that will not parse."""
        return list(self)

    def __iter__(self) -> Iterator[dict]:
        if self.backend == POSTGRES:
            yield from self._rows()
            return
        if not self.path.exists():
            return
        self.corrupt = 0
        with self.path.open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    self.corrupt += 1
                    log.warning("timeline %s: line %d will not parse, skipped",
                                self.path, number)

    def _rows(self) -> Iterator[dict]:
        """Every mission event, in the shape the file produces.

        Filtered to this factory. `atlas_business_events` is shared — the
        opportunity factory's reviews and publications live in it too — and a
        reader that took every row would fold decisions about businesses into
        the mission list.
        """
        from sqlalchemy import text

        from ..db import SessionLocal
        from .service import FACTORY

        try:
            with SessionLocal() as session:
                rows = session.execute(
                    text("""
                    SELECT business_id, factory, kind, actor, detail
                    FROM atlas_business_events
                    WHERE factory = :factory
                    ORDER BY at, id
                    """), {"factory": FACTORY}).mappings().all()
        except Exception as unreachable:           # noqa: BLE001 - re-raised
            raise LedgerUnavailable(
                f"could not read the ledger: {unreachable}"[:300]
            ) from unreachable

        for row in rows:
            detail = row["detail"]
            if isinstance(detail, str):
                try:
                    detail = json.loads(detail)
                except json.JSONDecodeError:
                    self.corrupt += 1
                    continue
            yield {"kind": row["kind"], "factory": row["factory"],
                   "actor": row["actor"], "business_id": row["business_id"],
                   "detail": detail or {}}

    def __len__(self) -> int:
        return sum(1 for _ in self)


def _record(event: Any) -> dict:
    """An event as plain data.

    Accepts a `BusinessEvent` or something already dict-shaped, because the
    sink is handed to a worker that should not have to care which.
    """
    if isinstance(event, dict):
        return dict(event)
    return {
        "kind": getattr(event, "kind", ""),
        "factory": getattr(event, "factory", ""),
        "actor": getattr(event, "actor", ""),
        "business_id": getattr(event, "business_id", ""),
        "detail": getattr(event, "detail", {}) or {},
    }
