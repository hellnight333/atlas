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
from collections.abc import Iterator
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class Timeline:
    """Append-only mission events in a file. Read by folding, never by seeking."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        #: Lines that would not parse. Counted rather than raised, and exposed so
        #: a health check can notice a timeline quietly rotting.
        self.corrupt = 0

    def append(self, event: Any) -> None:
        """One event, one line, one write call."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = _record(event)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str) + "\n")
            handle.flush()
            # The worker may be a different process reading this file within
            # milliseconds. Buffered-but-unwritten is indistinguishable from
            # lost to that reader.
            os.fsync(handle.fileno())

    def read(self) -> list[dict]:
        """Every event, oldest first, skipping anything that will not parse."""
        return list(self)

    def __iter__(self) -> Iterator[dict]:
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
