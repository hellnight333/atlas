"""Which opportunity to look at first. Deterministic, and explainable.

Ranking before an LLM, on purpose. A model asked to order a list will produce an
order, and it will be plausible, and nobody will be able to say why one thing
came above another six weeks later. This produces a number with its working
shown, so "why is this first" has an answer somebody can disagree with.

A model may later *explain* an opportunity or enrich it with context. It must
not become the authority on whether the evidence exists or whether something is
actually new — those are `extractors.py` and `discovery.py`, and they are
deterministic for exactly that reason.

## What is scored, and what is not

Scored: how much evidence there is, how direct it is, how recently it was seen,
how confident the inference is, and whether Qevik can actually do the work.

**Not scored: revenue.** Nothing here has measured what a dental practice in
Dubai is worth, and a placeholder would sort the list by a fiction. `value`
stays `UNKNOWN` with no number, and `UNKNOWN` is never rendered as zero — a
business nobody has valued is not a business worth nothing.

## Why "can Qevik do it" is weighted at all

An opportunity Qevik cannot execute is not worthless — it is worth knowing, and
worth building for. But it is worth less *today* than one that can be acted on
this afternoon, and an operator working down a list needs the actionable ones at
the top. Read from `EXECUTORS`, so the answer changes when a capability ships
rather than when somebody remembers to update a constant.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from .signals import Signal

#: What each component can contribute. Data rather than branching, so tuning is
#: an edit and the weights are visible in one place.
#:
#: They sum to 1.0 deliberately: a score is then a fraction of the best possible
#: case, which is a thing an operator can reason about, rather than an unbounded
#: number whose scale nobody knows.
WEIGHTS: dict[str, float] = {
    "evidence": 0.30,
    "confidence": 0.25,
    "recency": 0.20,
    "executable": 0.15,
    "specificity": 0.10,
}

#: Evidence beyond this adds nothing. Ten sources saying the same thing is
#: better than one; a hundred is not ten times better than ten, and without a
#: cap a noisy source would dominate the list by volume alone.
EVIDENCE_PLATEAU = 5

#: How long an observation stays fully fresh, and how long until it is worth
#: nothing on this axis. A business seen this morning and one seen last quarter
#: are not equally worth acting on.
FRESH_DAYS = 1.0
STALE_DAYS = 30.0


class Component(BaseModel):
    """One part of a score, and why it came out that way."""

    model_config = ConfigDict(frozen=True)

    name: str
    #: 0..1 before weighting.
    raw: float
    weight: float
    because: str

    @property
    def contribution(self) -> float:
        return self.raw * self.weight


class Ranked(BaseModel):
    """A scored opportunity. The score is never the whole answer."""

    model_config = ConfigDict(frozen=True)

    signal_id: str
    business_id: str
    kind: str
    score: float
    components: tuple[Component, ...]
    #: Carried through untouched. See the module note: nothing here measures it.
    value_amount: float | None = None
    value_status: str = "UNKNOWN"
    needs_approval: bool = True
    detected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def summary(self) -> dict:
        return {
            "signal_id": self.signal_id, "business_id": self.business_id,
            "kind": self.kind, "score": round(self.score, 4),
            "why": [{"name": c.name, "raw": round(c.raw, 3),
                     "weight": c.weight,
                     "contribution": round(c.contribution, 4),
                     "because": c.because}
                    for c in self.components],
            # Never a bare number. The status travels with it and UNKNOWN
            # carries no amount at all.
            "value": {"amount": self.value_amount, "status": self.value_status},
            "needs_approval": self.needs_approval,
            "detected_at": self.detected_at.isoformat(),
        }


def _evidence(signal: Signal) -> Component:
    pieces = sum(len(o.evidence) for o in signal.observations)
    raw = min(pieces, EVIDENCE_PLATEAU) / EVIDENCE_PLATEAU
    return Component(
        name="evidence", raw=raw, weight=WEIGHTS["evidence"],
        because=(f"{pieces} piece(s) of evidence; {EVIDENCE_PLATEAU} or more "
                 "counts as full, because a hundred is not ten times better "
                 "than ten"))


def _confidence(signal: Signal) -> Component:
    if not signal.inferences:
        # An opportunity that draws no inference is an observation somebody has
        # to interpret. Not worthless, and not confident either.
        return Component(name="confidence", raw=0.0,
                         weight=WEIGHTS["confidence"],
                         because="no inference was drawn from this")
    best = max(i.confidence for i in signal.inferences)
    return Component(
        name="confidence", raw=best, weight=WEIGHTS["confidence"],
        because=(f"the strongest inference is held at {best:.2f}, and an "
                 "inference may never be certain"))


def _recency(signal: Signal, *, now: datetime) -> Component:
    seen = min((o.observed_at for o in signal.observations), default=now)
    days = max(0.0, (now - seen).total_seconds() / 86400)
    if days <= FRESH_DAYS:
        raw, why = 1.0, "seen within the last day"
    elif days >= STALE_DAYS:
        raw, why = 0.0, f"last seen {days:.0f} days ago"
    else:
        raw = 1.0 - (days - FRESH_DAYS) / (STALE_DAYS - FRESH_DAYS)
        why = f"last seen {days:.1f} days ago"
    return Component(name="recency", raw=raw, weight=WEIGHTS["recency"],
                     because=why)


def _executable(signal: Signal) -> Component:
    """Whether Qevik can act on this today."""
    from atlas_kernel.execution.capabilities import EXECUTORS

    named = [a.capability for a in signal.actions if a.capability]
    # A capability that is an agent id rather than an offer id counts as
    # actionable: `researcher` is a role Qevik runs, and "go and check" is
    # something it can do this afternoon.
    from atlas_kernel.fabric.agents import Registry, UnknownAgent

    registry = Registry()
    doable = []
    for capability in named:
        if capability in EXECUTORS:
            doable.append(capability)
            continue
        try:
            registry.get(capability)
        except UnknownAgent:
            continue
        doable.append(capability)

    if not named:
        return Component(name="executable", raw=0.0, weight=WEIGHTS["executable"],
                         because="no action names a capability")
    raw = len(doable) / len(named)
    return Component(
        name="executable", raw=raw, weight=WEIGHTS["executable"],
        because=(f"{len(doable)} of {len(named)} suggested action(s) name "
                 "something Qevik can carry out today"))


def _specificity(signal: Signal) -> Component:
    """Whether this is about one business or a whole market.

    A named business is easier to act on than a market observation, so it ranks
    higher — not because it matters more, but because an operator can do
    something with it today.
    """
    if signal.business_id:
        return Component(name="specificity", raw=1.0,
                         weight=WEIGHTS["specificity"],
                         because="about one identified business")
    return Component(name="specificity", raw=0.4,
                     weight=WEIGHTS["specificity"],
                     because="about a market rather than one business")


def rank(signal: Signal, *, now: datetime | None = None) -> Ranked:
    """Score one opportunity, showing the working."""
    moment = now or datetime.now(UTC)
    components = (
        _evidence(signal), _confidence(signal), _recency(signal, now=moment),
        _executable(signal), _specificity(signal),
    )
    return Ranked(
        signal_id=signal.id, business_id=signal.business_id,
        kind=signal.kind.value,
        score=sum(c.contribution for c in components),
        components=components,
        value_amount=signal.estimated_value,
        value_status=signal.value_status,
        needs_approval=not signal.is_actionable_without_a_person,
        detected_at=signal.created_at,
    )


def order(signals: list[Signal], *, now: datetime | None = None) -> list[Ranked]:
    """Every opportunity, best first.

    Ties break on `signal_id` rather than on input order, so two runs over the
    same data produce the same list. A ranking that reorders itself between
    refreshes is one nobody trusts.
    """
    scored = [rank(s, now=now) for s in signals]
    return sorted(scored, key=lambda r: (-r.score, r.signal_id))


def describe() -> dict:
    return {
        "weights": dict(WEIGHTS),
        "evidence_plateau": EVIDENCE_PLATEAU,
        "fresh_days": FRESH_DAYS, "stale_days": STALE_DAYS,
        "note": ("Revenue is not scored. Nothing has measured what an "
                 "opportunity is worth, and a placeholder would sort the list "
                 "by a fiction. UNKNOWN carries no amount and is never zero."),
    }


__all__ = ["Component", "EVIDENCE_PLATEAU", "Ranked", "WEIGHTS", "describe",
           "order", "rank"]
