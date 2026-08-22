"""When a metric is due to be read again, and what a worker would pick up.

Not a scheduler. A scheduler is a process with a clock, retries and a lease,
and building one before anything needs it produces a background job that runs
forever doing nothing. What is missing today is smaller and is the part that
would still be needed afterwards: **the answer to "what is due?"**, computed
from the measurement's own window.

A future worker asks `due()`, reads the metrics from whatever source is
connected, and calls `close_measurement`. Nothing here reads a source, and
nothing here invents a number — a metric with no source stays
`measurement_unavailable`, which is a state and not a failure.
"""

from __future__ import annotations

from datetime import UTC, datetime

from .models import Measurement
from .service import Progress, progress_of

#: What a worker would act on. Anything else is either not started, already
#: read, or waiting on a source nobody has connected.
ACTIONABLE: frozenset[Progress] = frozenset({Progress.INTERVENTION_OCCURRED})


def due(measurements: list[Measurement], *, now: datetime | None = None
        ) -> tuple[Measurement, ...]:
    """Measurements whose window has closed and which nobody has read again.

    Ordered by how overdue they are, so a worker that can only get through some
    of them takes the oldest first rather than whichever the list happened to
    start with.
    """
    at = now or datetime.now(UTC)
    ready = [m for m in measurements if progress_of(m, now=at) in ACTIONABLE]
    return tuple(sorted(ready, key=lambda m: m.window.observation_end or at))


def plan(measurements: list[Measurement], *, now: datetime | None = None) -> dict:
    """What is outstanding, in the terms a surface or an operator needs.

    Deliberately reports the waiting-on-a-source group separately: those are not
    late, and a queue that mixes "overdue" with "impossible" trains whoever
    reads it to ignore both.
    """
    at = now or datetime.now(UTC)
    grouped: dict[str, list[dict]] = {}
    for measurement in measurements:
        entry = {"id": measurement.id, "metric": measurement.metric_key,
                 "business_id": measurement.business_id,
                 "reading_due": (measurement.window.observation_end.isoformat()
                                 if measurement.window.observation_end else None)}
        grouped.setdefault(progress_of(measurement, now=at).value, []).append(entry)
    return {
        "due_now": [m.id for m in due(measurements, now=at)],
        "by_state": grouped,
        "note": "Nothing here reads a metric. A metric with no connected source "
                "stays unavailable, which is a state rather than a failure.",
    }
