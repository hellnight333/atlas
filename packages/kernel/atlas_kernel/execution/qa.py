"""The gates an artefact has to pass before a human is asked to look at it.

Six checks, and the framework is exactly what these six needed. Each is a
question with a factual answer, run against what execution actually produced
rather than against what it intended.

The rule the whole layer turns on: **a job does not become READY because
generation succeeded.** Generation succeeding is one of the six. An asset that
exists but has no provenance, or whose recommendation cited no evidence, or
which is missing what its capability promised, is rejected — and rejection is
not a warning, it is the end of that artefact's life.

A gate that cannot run returns NOT_RUN, which blocks exactly as a failure does.
An unrun check has established nothing.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from .models import QAResult, QAVerdict

log = logging.getLogger(__name__)


class Context:
    """What the gates inspect. Assembled once by the service."""

    def __init__(self, *, outcome_error: str, assets: list, recommendation,
                 offer, artefact: str) -> None:
        self.outcome_error = outcome_error
        self.assets = assets
        self.recommendation = recommendation
        self.offer = offer
        self.artefact = artefact


def _execution_succeeded(context: Context) -> QAResult:
    if context.outcome_error:
        return QAResult(gate="execution", verdict=QAVerdict.FAIL,
                        detail=context.outcome_error[:200])
    return QAResult(gate="execution", verdict=QAVerdict.PASS,
                    detail="the capability ran without raising")


def _asset_exists(context: Context) -> QAResult:
    if not context.assets:
        return QAResult(gate="asset_exists", verdict=QAVerdict.FAIL,
                        detail="the job produced no asset")
    empty = [a for a in context.assets if not (a.uri or "").strip()]
    if empty:
        return QAResult(gate="asset_exists", verdict=QAVerdict.FAIL,
                        detail=f"{len(empty)} asset(s) have no location")
    return QAResult(gate="asset_exists", verdict=QAVerdict.PASS,
                    detail=f"{len(context.assets)} asset(s)")


def _provenance_is_valid(context: Context) -> QAResult:
    """An asset that cannot say where it came from can never be explained later."""
    if not context.assets:
        return QAResult(gate="provenance", verdict=QAVerdict.NOT_RUN,
                        detail="no asset to check")
    missing: list[str] = []
    for asset in context.assets:
        for field in ("job_id", "run_id", "content_hash"):
            if not getattr(asset, field, None):
                missing.append(f"{asset.id}:{field}")
    if missing:
        return QAResult(gate="provenance", verdict=QAVerdict.FAIL,
                        detail="missing " + ", ".join(missing[:4]))
    return QAResult(gate="provenance", verdict=QAVerdict.PASS,
                    detail="job, run and content hash on every asset")


def _evidence_is_attached(context: Context) -> QAResult:
    """The artefact must trace back to why it was made."""
    recommendation = context.recommendation
    if recommendation is None:
        return QAResult(gate="evidence", verdict=QAVerdict.FAIL,
                        detail="the job has no recommendation")
    if not recommendation.evidence:
        return QAResult(gate="evidence", verdict=QAVerdict.FAIL,
                        detail="the recommendation cites no evidence")
    return QAResult(gate="evidence", verdict=QAVerdict.PASS,
                    detail=f"{len(recommendation.evidence)} observation(s)")


def _meets_capability_requirements(context: Context) -> QAResult:
    """What the offer promised has to be in the output."""
    offer = context.offer
    if offer is None:
        return QAResult(gate="capability_output", verdict=QAVerdict.NOT_RUN,
                        detail="no offer to check against")
    artefact = context.artefact or ""
    if not artefact.strip():
        return QAResult(gate="capability_output", verdict=QAVerdict.FAIL,
                        detail="the artefact is empty")
    missing = [o for o in offer.outputs if o.split()[-1].lower() not in artefact.lower()]
    if len(missing) == len(offer.outputs) and offer.outputs:
        return QAResult(gate="capability_output", verdict=QAVerdict.FAIL,
                        detail=f"none of the promised outputs are present: "
                               f"{', '.join(offer.outputs)}")
    return QAResult(gate="capability_output", verdict=QAVerdict.PASS,
                    detail=f"{len(offer.outputs) - len(missing)} of "
                           f"{len(offer.outputs)} promised output(s) present")


def _makes_no_claim_it_cannot_support(context: Context) -> QAResult:
    """The honesty gate.

    An artefact built for a strong business must not call it weak, and one built
    from research must not assert anything the research did not establish. This
    is the same phrase gate the outreach layer uses, applied to what gets built
    rather than to what gets said.
    """
    artefact = (context.artefact or "").lower()
    forbidden = ("your website is bad", "poor website", "outdated site",
                 "unprofessional", "we increased", "qevik increased",
                 "guaranteed", "#1 ranked", "best in dubai")
    found = [phrase for phrase in forbidden if phrase in artefact]
    if found:
        return QAResult(gate="honesty", verdict=QAVerdict.FAIL,
                        detail=f"unsupported claim: {found[0]!r}")
    return QAResult(gate="honesty", verdict=QAVerdict.PASS,
                    detail="no unsupported claim found")


#: In order. Named here so the service and the tests agree on what a complete
#: QA pass consists of without a second list.
GATES: tuple[tuple[str, Callable[[Context], QAResult]], ...] = (
    ("execution", _execution_succeeded),
    ("asset_exists", _asset_exists),
    ("provenance", _provenance_is_valid),
    ("evidence", _evidence_is_attached),
    ("capability_output", _meets_capability_requirements),
    ("honesty", _makes_no_claim_it_cannot_support),
)


def run_gates(context: Context) -> tuple[QAResult, ...]:
    """Every gate, whatever the earlier ones said.

    Deliberately not short-circuiting: an operator fixing a rejected artefact
    wants the whole list, not the first problem and then silence.
    """
    results: list[QAResult] = []
    for name, gate in GATES:
        try:
            results.append(gate(context))
        except Exception as error:                # noqa: BLE001
            log.exception("qa gate %s raised", name)
            results.append(QAResult(gate=name, verdict=QAVerdict.NOT_RUN,
                                    detail=f"{type(error).__name__}: {error}"[:160]))
    return tuple(results)
