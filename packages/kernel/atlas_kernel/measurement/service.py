"""Recording measurements, and reading them back without crossing a tenant.

Persistence is the existing `BusinessEvent` timeline under a `measurement`
factory — the same choice as research, recommendations and jobs, for the same
reason. A measurement is something that happened to a business; its history is
what makes a later claim checkable, and an append-only log is the only shape
where "what did we say in July" has an answer.

The read path is here rather than in the opportunity repository because a
measurement is not an opportunity concern, but it obeys the same rule P1.1
established: the tenant is a parameter, and a record with no tenant belongs to
nobody.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from ..opportunity.models import BusinessEvent
from ..opportunity.tenancy import TenantId, owns
from ..opportunity.tenancy import require as _require_tenant
from .attribution import Attribution, refuse
from .models import BY_KEY, BaselineState, Measurement, Observation, Window

# roadmap imports measurement, not the other way round, so this stays a hint.
if TYPE_CHECKING:
    from ..roadmap.models import Roadmap

log = logging.getLogger(__name__)

FACTORY = "measurement"
RECORDED = "measurement_recorded"


class ProvenanceMissing(Exception):
    """A measurement was attached to work it cannot be traced to."""


class OutsideWindow(Exception):
    """An observation was taken outside the period it claims to describe."""


def check_provenance(measurement: Measurement, *, known_jobs: set[str] | None = None,
                     known_recommendations: set[str] | None = None) -> None:
    """Refuse a measurement that cannot be traced to real work.

    Provenance is checked against what actually exists rather than against the
    presence of a string, because a fabricated id is exactly as convincing as a
    real one until somebody follows it.
    """
    if not measurement.business_id:
        raise ProvenanceMissing("a measurement must name the business it describes")
    if measurement.job_id and known_jobs is not None and measurement.job_id not in known_jobs:
        raise ProvenanceMissing(
            f"job {measurement.job_id!r} does not exist for this business — a "
            "measurement cannot be attached to work that did not happen")
    if (measurement.recommendation_id and known_recommendations is not None
            and measurement.recommendation_id not in known_recommendations):
        raise ProvenanceMissing(
            f"recommendation {measurement.recommendation_id!r} does not exist for "
            "this business")


def check_window(measurement: Measurement) -> None:
    """Refuse an observation taken outside the window it claims to cover."""
    observed = measurement.observed
    if observed is None or not observed.available:
        return
    if not measurement.window.defined:
        raise OutsideWindow(
            "an observation was recorded against an undefined window; two numbers "
            "with no period are not a before-and-after")
    if not measurement.window.contains(observed.observed_at):
        raise OutsideWindow(
            f"the observation was taken at {observed.observed_at:%Y-%m-%d}, outside "
            f"{measurement.window.describe()}")


def record(measurement: Measurement, *, actor: str = "measurement",
           known_jobs: set[str] | None = None,
           known_recommendations: set[str] | None = None) -> BusinessEvent:
    """Validate, then write one measurement to the business's timeline."""
    check_provenance(measurement, known_jobs=known_jobs,
                     known_recommendations=known_recommendations)
    check_window(measurement)
    return BusinessEvent(
        business_id=measurement.business_id, factory=FACTORY, kind=RECORDED,
        actor=actor,
        detail={
            "measurement_id": measurement.id,
            "tenant_id": measurement.tenant_id,
            "metric_key": measurement.metric_key,
            "recommendation_id": measurement.recommendation_id,
            "job_id": measurement.job_id,
            "asset_ids": list(measurement.asset_ids),
            "baseline": measurement.baseline.model_dump(mode="json")
            if measurement.baseline else None,
            "observed": measurement.observed.model_dump(mode="json")
            if measurement.observed else None,
            "window": measurement.window.model_dump(mode="json"),
            "state": measurement.state.value,
            "attribution": measurement.attribution.value,
            "confidence": measurement.confidence.value,
            "attribution_source": measurement.attribution_source,
            "ai": [o.model_dump(mode="json") for o in measurement.ai],
            # Stored so a customer-facing surface never has to compose its own
            # sentence, and so what was said is auditable later.
            "statement": measurement.statement(),
        },
    )


def read(events: list, *, tenant: TenantId | None = None,
         metric_key: str = "") -> list[dict]:
    """TENANT_SCOPED. Measurements for one tenant, newest first."""
    tenant = _require_tenant(tenant, method="measurement.read")
    found: list[dict] = []
    for event in events:
        kind = getattr(event, "kind", None) or event.get("kind")
        if kind != RECORDED:
            continue
        detail = getattr(event, "detail", None) or event.get("detail") or {}
        if not owns(detail.get("tenant_id"), tenant):
            continue
        if metric_key and detail.get("metric_key") != metric_key:
            continue
        found.append(dict(detail))
    return sorted(found, key=lambda d: d.get("measurement_id", ""), reverse=True)


def summarise(measurements: list[dict]) -> dict:
    """What can honestly be said about a set of measurements.

    Counts what is unmeasured rather than dropping it. A report that silently
    omits the metrics with no baseline reads as though everything was measured,
    which is a stronger claim than the data supports.
    """
    total = len(measurements)
    measured = [m for m in measurements
                if m.get("state") == BaselineState.MEASUREMENT_AVAILABLE.value]
    unmeasured = total - len(measured)
    by_level: dict[str, int] = {}
    for m in measured:
        by_level[m.get("attribution", "UNKNOWN")] = \
            by_level.get(m.get("attribution", "UNKNOWN"), 0) + 1
    return {
        "total": total, "measured": len(measured), "not_measured": unmeasured,
        "by_attribution": by_level,
        "strongest": max(by_level, key=lambda k: ("UNKNOWN", "OBSERVED", "ASSOCIATED",
                                                  "ATTRIBUTED").index(k))
        if by_level else Attribution.UNKNOWN.value,
        "statements": [m.get("statement", "") for m in measured],
    }


def vet(sentence: str, level: Attribution) -> str:
    """The customer-facing gate. Empty means the sentence is supported.

    Thin on purpose: the judgement lives in `attribution`, where it is derived
    from evidence rather than from a word list, and this is the seam a
    presentation layer calls.
    """
    return refuse(level, sentence)


# --- baselines ---------------------------------------------------------------
#
# The gap P1.5 left: a roadmap could say "connect Search Console" and nothing
# could act on the answer. These turn that into a baseline the moment a source
# exists, and — just as importantly — report honestly while it does not.


class SourceUnavailable(Exception):
    """A baseline was requested for a metric with nothing to read it from.

    Raised rather than returning a zero-valued baseline. A zero is a reading,
    and a reading nobody took is the single most damaging thing this layer can
    invent: every later comparison against it would show improvement.
    """


def open_baseline(*, business_id: str, tenant_id: str | None, metric_key: str,
                  value: float | None, source: str, observed_at: datetime | None = None,
                  covering_days: int = 30, recommendation_id: str = "",
                  roadmap_task_id: str = "", detail: str = "") -> Measurement:
    """Record what a metric read *before* anything was done to it.

    `value=None` is allowed and is not a failure: it records that the source was
    reachable and had nothing to report, which is different from not having
    looked. The resulting measurement reports NO_BASELINE and UNKNOWN
    confidence, and says so in its own statement.
    """
    if not source:
        raise SourceUnavailable(
            f"{metric_key}: a baseline needs a source. Without one there is "
            "nothing to record, and recording zero would invent a reading.")
    if metric_key not in BY_KEY:
        raise SourceUnavailable(f"{metric_key!r} is not in the metric catalogue")

    end = observed_at or datetime.now(UTC)
    start = end - timedelta(days=covering_days)
    return Measurement(
        business_id=business_id, tenant_id=tenant_id, metric_key=metric_key,
        recommendation_id=recommendation_id,
        window=Window(baseline_start=start, baseline_end=end),
        baseline=Observation(value=value, source=source, observed_at=end,
                             detail=detail or f"baseline over {covering_days} days"),
        notes=f"roadmap_task={roadmap_task_id}" if roadmap_task_id else "")


def close_measurement(baseline: Measurement, *, value: float | None, source: str,
                      intervention_at: datetime, observed_at: datetime | None = None,
                      covering_days: int = 30, job_id: str = "",
                      asset_ids: tuple[str, ...] = (), attribution_source: str = "",
                      detail: str = "") -> Measurement:
    """Take the later reading against an existing baseline.

    The intervention timestamp is required rather than defaulted, because
    whether the work preceded the observation is what separates OBSERVED from
    ASSOCIATED — and a default would silently supply the ordering that
    distinction exists to check.
    """
    end = observed_at or datetime.now(UTC)
    start = end - timedelta(days=covering_days)
    return baseline.model_copy(update={
        "window": baseline.window.model_copy(update={
            "intervention_at": intervention_at,
            "observation_start": start, "observation_end": end}),
        "observed": Observation(value=value, source=source, observed_at=end,
                                detail=detail or f"observed over {covering_days} days"),
        "job_id": job_id or baseline.job_id,
        "asset_ids": asset_ids or baseline.asset_ids,
        "attribution_source": attribution_source or baseline.attribution_source,
    })


def awaiting_source(roadmap: Roadmap, *,
                    measured: frozenset[str] = frozenset()) -> tuple[dict, ...]:
    """Which of a roadmap's measurement tasks still have nothing to read from.

    The honest answer to "why is there no number here yet", phrased so it cannot
    be read as poor performance: a metric with no source is unmeasured, and
    unmeasured is not zero and not bad.
    """
    from ..roadmap.models import Executability

    waiting = []
    for task in roadmap.tasks:
        if task.executability is not Executability.MEASURE_FIRST:
            continue
        if not task.metric_key or task.metric_key in measured:
            continue
        metric = BY_KEY.get(task.metric_key)
        waiting.append({
            "task_id": task.id, "metric": task.metric_key,
            "label": metric.label if metric else task.metric_key,
            "needs": task.task.action or "a source Qevik can read",
            "state": BaselineState.NO_BASELINE.value,
            "statement": f"{metric.label if metric else task.metric_key}: "
                         "no baseline yet — nothing has been connected to read it from.",
        })
    return tuple(waiting)
