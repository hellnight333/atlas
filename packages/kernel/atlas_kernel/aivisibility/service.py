"""Running a sweep, and refusing to turn our own outage into their weakness.

The arithmetic here is three lines long and the care is all in what is excluded
from it. A mention rate is *mentions ÷ questions that were actually answered*.
An engine that could not be reached contributes to neither side, because it
established nothing — counting it as a miss would mean a provider outage showed
up in a customer's report as their business becoming less visible.

If no engine answered at all, there is no rate. Not zero. `open_baseline`
already accepts `value=None` for exactly this, and reports NO_BASELINE with
UNKNOWN confidence rather than a number.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from ..measurement.models import AIVisibilityObservation, Measurement
from ..measurement.service import open_baseline
from ..opportunity.models import BusinessEvent
from ..opportunity.tenancy import TenantId, owns
from ..opportunity.tenancy import require as _require_tenant
from .providers import ProviderUnavailable, VisibilityProvider, fingerprint, queries_for

log = logging.getLogger(__name__)

FACTORY = "aivisibility"
SWEPT = "ai_visibility_swept"

MENTION_METRIC = "ai_mention_rate"
CITATION_METRIC = "ai_citation_rate"


class Sweep(BaseModel):
    """One pass over a question set, across whichever engines answered."""

    model_config = ConfigDict(frozen=True)

    business_id: str
    tenant_id: str
    business_name: str
    queries: tuple[str, ...]
    query_fingerprint: str
    observations: tuple[AIVisibilityObservation, ...] = ()
    #: Engines asked that could not answer, and why. Kept because a sweep where
    #: three of four engines were down is a different reading from one where all
    #: four answered, and the rate alone cannot show that.
    unavailable: tuple[str, ...] = ()
    swept_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def answered(self) -> tuple[AIVisibilityObservation, ...]:
        """Observations where the engine actually said something either way."""
        return tuple(o for o in self.observations if o.mentioned is not None)

    @property
    def mention_rate(self) -> float | None:
        """Mentions over answers. `None` when nothing answered — never zero."""
        answered = self.answered
        if not answered:
            return None
        return sum(1 for o in answered if o.mentioned) / len(answered)

    @property
    def citation_rate(self) -> float | None:
        answered = tuple(o for o in self.observations if o.cited is not None)
        if not answered:
            return None
        return sum(1 for o in answered if o.cited) / len(answered)

    @property
    def positions_supplied(self) -> tuple[AIVisibilityObservation, ...]:
        """Only engines that genuinely returned a rank. Usually none."""
        return tuple(o for o in self.observations
                     if o.position_available and o.position is not None)

    def statement(self) -> str:
        """What the sweep showed, claiming no more than it established."""
        answered = self.answered
        if not answered:
            return ("AI visibility: no result — no engine answered, so nothing "
                    "was established either way.")
        mentioned = sum(1 for o in answered if o.mentioned)
        ranked = len(self.positions_supplied)
        tail = (f", and {ranked} supplied a position" if ranked
                else ", and no engine supplied a position")
        return (f"AI visibility: mentioned in {mentioned} of {len(answered)} "
                f"answered queries{tail}.")

    def summary(self) -> dict:
        return {
            "business_id": self.business_id, "tenant_id": self.tenant_id,
            "queries": list(self.queries),
            "query_fingerprint": self.query_fingerprint,
            "answered": len(self.answered),
            "asked": len(self.queries),
            "unavailable": list(self.unavailable),
            "mention_rate": self.mention_rate,
            "citation_rate": self.citation_rate,
            "positions_supplied": len(self.positions_supplied),
            "observations": [o.model_dump(mode="json") for o in self.observations],
            "swept_at": self.swept_at.isoformat(),
            "statement": self.statement(),
        }


def sweep(*, business_id: str, business_name: str, tenant: TenantId | None,
          providers: list[VisibilityProvider], category: str = "",
          geography: str = "") -> Sweep:
    """Ask every provider every question, and record what came back.

    A provider that raises is recorded as unavailable and excluded from the
    arithmetic. It is never recorded as a miss.
    """
    tenant = _require_tenant(tenant, method="aivisibility.sweep")
    queries = queries_for(business_name, category=category, geography=geography)
    observations: list[AIVisibilityObservation] = []
    unavailable: list[str] = []

    for provider in providers:
        failed = False
        for query in queries:
            try:
                observations.append(provider.ask(query, business_name=business_name))
            except ProviderUnavailable as refusal:
                log.info("aivisibility: %s unavailable — %s", provider.name, refusal)
                failed = True
                break
        if failed:
            unavailable.append(provider.name)

    return Sweep(business_id=business_id, tenant_id=str(tenant),
                 business_name=business_name, queries=queries,
                 query_fingerprint=fingerprint(queries),
                 observations=tuple(observations), unavailable=tuple(unavailable))


def to_baseline(result: Sweep, *, metric: str = MENTION_METRIC) -> Measurement:
    """Turn a sweep into a measurement baseline, through the existing layer.

    `value=None` when nothing answered, which the measurement model already
    handles: NO_BASELINE, UNKNOWN confidence, and a statement that asserts
    nothing. That is the whole reason this does not compute a zero.
    """
    rate = result.mention_rate if metric == MENTION_METRIC else result.citation_rate
    return open_baseline(
        business_id=result.business_id, tenant_id=result.tenant_id,
        metric_key=metric, value=rate, source=f"ai-visibility:{result.query_fingerprint}",
        detail=f"{len(result.answered)} of {len(result.queries)} queries answered"
               + (f"; unavailable: {', '.join(result.unavailable)}"
                  if result.unavailable else ""))


def to_event(result: Sweep, *, actor: str = "aivisibility") -> BusinessEvent:
    return BusinessEvent(business_id=result.business_id, factory=FACTORY,
                         kind=SWEPT, actor=actor, detail=result.summary())


def read(events: list, *, tenant: TenantId | None = None) -> list[dict]:
    """TENANT_SCOPED. Sweeps for one tenant, newest first."""
    tenant = _require_tenant(tenant, method="aivisibility.read")
    found = []
    for event in events:
        kind = getattr(event, "kind", None) or event.get("kind")
        if kind != SWEPT:
            continue
        detail = getattr(event, "detail", None) or event.get("detail") or {}
        if not owns(detail.get("tenant_id"), tenant):
            continue
        found.append(dict(detail))
    return sorted(found, key=lambda d: d.get("swept_at", ""), reverse=True)
