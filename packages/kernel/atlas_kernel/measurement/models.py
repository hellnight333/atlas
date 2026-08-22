"""What was measured, over what period, and how much of it can be trusted.

The attribution level is **derived, never assigned**. A caller cannot declare a
measurement ATTRIBUTED; it earns that by having a baseline, an observation, a
window they sit inside, an intervention that preceded the window, and a source
that ties the two together. Letting a caller set it would make the whole scale
decorative, which is how "observed" quietly becomes "caused" three refactors
later.

Missing data is missing. A baseline that was never captured is `NO_BASELINE`,
not zero — treating it as zero turns "we do not know what it was before" into
"it was nothing before", which manufactures an improvement out of an absence.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from .attribution import Attribution


class MetricFamily(StrEnum):
    WEBSITE = "website"
    SEO = "seo"
    AI_VISIBILITY = "ai_visibility"
    ECOMMERCE = "ecommerce"
    ADVERTISING = "advertising"
    LEADS = "leads"
    CONTENT = "content"


class Direction(StrEnum):
    """Which way is good. Without it a fall in CPA reads as a regression."""

    UP = "up"
    DOWN = "down"


class Metric(BaseModel):
    """One thing that can be measured, and what a movement in it means."""

    model_config = ConfigDict(frozen=True)

    key: str
    family: MetricFamily
    label: str
    unit: str = "count"
    better: Direction = Direction.UP
    #: Sources that can actually supply it. A metric no connected source
    #: provides is unmeasurable, and saying so is more useful than a zero.
    sources: tuple[str, ...] = ()


#: The catalogue. Deliberately explicit about what a source has to provide:
#: several of these are unmeasurable today and are listed so that a request for
#: them returns "not available" rather than an invented figure.
METRICS: tuple[Metric, ...] = (
    Metric(key="sessions", family=MetricFamily.WEBSITE, label="Sessions",
           sources=("analytics",)),
    Metric(key="page_views", family=MetricFamily.WEBSITE, label="Page views",
           sources=("analytics",)),
    Metric(key="conversion_rate", family=MetricFamily.WEBSITE,
           label="Conversion rate", unit="percent", sources=("analytics",)),
    Metric(key="engagement", family=MetricFamily.WEBSITE, label="Engagement",
           sources=("analytics",)),
    Metric(key="technical_health", family=MetricFamily.WEBSITE,
           label="Technical health", unit="score", sources=("research",)),

    Metric(key="impressions", family=MetricFamily.SEO, label="Impressions",
           sources=("search_console",)),
    Metric(key="clicks", family=MetricFamily.SEO, label="Clicks",
           sources=("search_console",)),
    Metric(key="ctr", family=MetricFamily.SEO, label="CTR", unit="percent",
           sources=("search_console",)),
    #: Only where the source genuinely supplies a position. Search Console does;
    #: an assistant does not, and the AI family below keeps them apart.
    Metric(key="average_position", family=MetricFamily.SEO, label="Average position",
           unit="position", better=Direction.DOWN, sources=("search_console",)),
    Metric(key="indexed_pages", family=MetricFamily.SEO, label="Indexed pages",
           sources=("search_console", "research")),
    Metric(key="orphan_pages", family=MetricFamily.SEO, label="Unlinked pages",
           better=Direction.DOWN, sources=("research",)),

    Metric(key="ai_mention_rate", family=MetricFamily.AI_VISIBILITY,
           label="Mention rate", unit="percent", sources=("ai_visibility",)),
    Metric(key="ai_citation_rate", family=MetricFamily.AI_VISIBILITY,
           label="Citation rate", unit="percent", sources=("ai_visibility",)),

    Metric(key="listing_impressions", family=MetricFamily.ECOMMERCE,
           label="Listing impressions", sources=("marketplace",)),
    Metric(key="listing_ctr", family=MetricFamily.ECOMMERCE, label="Listing CTR",
           unit="percent", sources=("marketplace",)),
    Metric(key="units_sold", family=MetricFamily.ECOMMERCE, label="Units sold",
           sources=("marketplace",)),

    Metric(key="ad_spend", family=MetricFamily.ADVERTISING, label="Spend",
           unit="currency", better=Direction.DOWN, sources=("ads",)),
    Metric(key="cpa", family=MetricFamily.ADVERTISING, label="CPA", unit="currency",
           better=Direction.DOWN, sources=("ads",)),
    Metric(key="roas", family=MetricFamily.ADVERTISING, label="ROAS", unit="ratio",
           sources=("ads",)),

    Metric(key="leads", family=MetricFamily.LEADS, label="Leads",
           sources=("analytics", "crm", "enquiry_form")),
    Metric(key="qualified_leads", family=MetricFamily.LEADS, label="Qualified leads",
           sources=("crm",)),
    Metric(key="response_rate", family=MetricFamily.LEADS, label="Response rate",
           unit="percent", sources=("crm", "outreach")),

    Metric(key="views", family=MetricFamily.CONTENT, label="Views",
           sources=("analytics", "social")),
    Metric(key="reach", family=MetricFamily.CONTENT, label="Reach",
           sources=("social",)),
)

BY_KEY: dict[str, Metric] = {m.key: m for m in METRICS}


class BaselineState(StrEnum):
    #: Never captured. Not zero.
    NO_BASELINE = "NO_BASELINE"
    #: Captured, but too thin or too short to compare against.
    BASELINE_INSUFFICIENT = "BASELINE_INSUFFICIENT"
    #: Captured and usable; nothing observed yet.
    BASELINE_AVAILABLE = "BASELINE_AVAILABLE"
    #: Both ends present.
    MEASUREMENT_AVAILABLE = "MEASUREMENT_AVAILABLE"


class Confidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class Window(BaseModel):
    """The period a before-and-after actually covers.

    A result without one is not a before-and-after, it is two numbers. The
    intervention timestamp is separate from the observation period on purpose:
    whether the work preceded the observation is the difference between
    OBSERVED and ASSOCIATED, and it has to be checkable rather than assumed.
    """

    model_config = ConfigDict(frozen=True)

    baseline_start: datetime | None = None
    baseline_end: datetime | None = None
    intervention_at: datetime | None = None
    observation_start: datetime | None = None
    observation_end: datetime | None = None

    @property
    def defined(self) -> bool:
        return bool(self.observation_start and self.observation_end
                    and self.observation_end > self.observation_start)

    @property
    def baseline_defined(self) -> bool:
        return bool(self.baseline_start and self.baseline_end
                    and self.baseline_end > self.baseline_start)

    @property
    def intervention_precedes_observation(self) -> bool:
        """The ordering causation needs — necessary, nowhere near sufficient."""
        return bool(self.intervention_at and self.observation_start
                    and self.intervention_at <= self.observation_start)

    @property
    def comparable(self) -> bool:
        """Periods of wildly different length do not compare.

        Four weeks against four days is not a before-and-after; it is a longer
        window finding more of everything.
        """
        if not (self.defined and self.baseline_defined):
            return False
        baseline = self.baseline_end - self.baseline_start
        observation = self.observation_end - self.observation_start
        if not baseline or not observation:
            return False
        ratio = baseline.total_seconds() / observation.total_seconds()
        return 0.5 <= ratio <= 2.0

    def contains(self, when: datetime) -> bool:
        if not self.defined:
            return False
        return self.observation_start <= when <= self.observation_end

    def describe(self) -> str:
        if not self.defined:
            return "an undefined window"
        days = (self.observation_end - self.observation_start).days or 1
        return f"the {days}-day window to {self.observation_end:%Y-%m-%d}"


class Observation(BaseModel):
    """One reading, from one source, at one moment."""

    model_config = ConfigDict(frozen=True)

    value: float | None
    source: str
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    #: Free-text provenance: the query, the report, the page. Never a guess.
    detail: str = ""

    @property
    def available(self) -> bool:
        return self.value is not None


class AIVisibilityObservation(BaseModel):
    """A reading from one assistant or search engine, kept system-specific.

    Mention, citation and position are separate fields because they are separate
    facts. `position` is `None` unless the engine genuinely supplies a rank —
    an assistant naming a business is not a ranking, and converting one into the
    other invents a number the customer will eventually check.
    """

    model_config = ConfigDict(frozen=True)

    engine: str
    query: str
    mentioned: bool | None = None
    cited: bool | None = None
    citation_url: str = ""
    #: Only from an engine that provides one. Never derived from a mention.
    position: int | None = None
    position_available: bool = False
    competitors: tuple[str, ...] = ()
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    confidence: Confidence = Confidence.MEDIUM

    def model_post_init(self, _: object) -> None:
        if self.position is not None and not self.position_available:
            raise ValueError(
                f"{self.engine}: a position was supplied without position_available. "
                "A rank may only be recorded from an engine that actually provides "
                "one; a mention is not a rank.")

    def statement(self) -> str:
        """What this engine actually showed, in words that claim no more."""
        parts = [f"{self.engine} for {self.query!r}:"]
        parts.append("mentioned" if self.mentioned else
                     ("not mentioned" if self.mentioned is False else "mention unknown"))
        if self.cited:
            parts.append(f"cited {self.citation_url or 'a source'}")
        parts.append(f"position {self.position}" if self.position_available
                     and self.position is not None else "position not supplied")
        return " ".join(parts)


class Measurement(BaseModel):
    """One metric, before and after, with everything needed to judge it."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: f"meas-{datetime.now(UTC):%Y%m%d%H%M%S%f}")

    business_id: str
    tenant_id: str | None = None
    #: The chain back to why this work happened. Every link is an existing id.
    recommendation_id: str = ""
    job_id: str = ""
    asset_ids: tuple[str, ...] = ()

    metric_key: str
    window: Window = Field(default_factory=Window)
    baseline: Observation | None = None
    observed: Observation | None = None
    target: float | None = None

    #: Set only when a source independently ties the change to the intervention
    #: — a referrer, a landing page, a campaign parameter. Names the source.
    attribution_source: str = ""
    ai: tuple[AIVisibilityObservation, ...] = ()
    notes: str = ""
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def metric(self) -> Metric | None:
        return BY_KEY.get(self.metric_key)

    @property
    def state(self) -> BaselineState:
        if self.baseline is None or not self.baseline.available:
            return BaselineState.NO_BASELINE
        if not self.window.baseline_defined:
            return BaselineState.BASELINE_INSUFFICIENT
        if self.observed is None or not self.observed.available:
            return BaselineState.BASELINE_AVAILABLE
        if not self.window.comparable:
            return BaselineState.BASELINE_INSUFFICIENT
        return BaselineState.MEASUREMENT_AVAILABLE

    @property
    def change(self) -> float | None:
        if self.state is not BaselineState.MEASUREMENT_AVAILABLE:
            return None
        return self.observed.value - self.baseline.value

    @property
    def improved(self) -> bool | None:
        """None when unknown. Never False merely because nothing was measured."""
        delta = self.change
        if delta is None or self.metric is None:
            return None
        if delta == 0:
            return False
        return delta > 0 if self.metric.better is Direction.UP else delta < 0

    @property
    def attribution(self) -> Attribution:
        """Derived from the evidence. Never assigned."""
        if self.state is not BaselineState.MEASUREMENT_AVAILABLE:
            return Attribution.UNKNOWN
        if not self.window.defined:
            return Attribution.UNKNOWN
        if not self.window.intervention_precedes_observation:
            return Attribution.OBSERVED
        if not self.attribution_source:
            return Attribution.ASSOCIATED
        return Attribution.ATTRIBUTED

    @property
    def confidence(self) -> Confidence:
        state, level = self.state, self.attribution
        if state is BaselineState.NO_BASELINE:
            return Confidence.UNKNOWN
        if state is BaselineState.BASELINE_INSUFFICIENT:
            return Confidence.LOW
        if state is BaselineState.BASELINE_AVAILABLE:
            return Confidence.LOW
        if level is Attribution.ATTRIBUTED:
            return Confidence.HIGH
        if level is Attribution.ASSOCIATED:
            return Confidence.MEDIUM
        return Confidence.MEDIUM

    def statement(self) -> str:
        """The strongest sentence this measurement's own evidence licenses."""
        from .attribution import phrasing

        metric = self.metric
        label = metric.label if metric else self.metric_key
        if self.state is not BaselineState.MEASUREMENT_AVAILABLE:
            # Worded to assert nothing. "not measured" and "nothing has been
            # observed" both contain verbs the claim detector reads as stating a
            # change, so a sentence saying there is no result would have failed
            # its own gate — which is the bug this wording exists to avoid.
            reason = {
                BaselineState.NO_BASELINE: "no baseline was captured",
                BaselineState.BASELINE_INSUFFICIENT:
                    "the two periods are not comparable",
                BaselineState.BASELINE_AVAILABLE: "no later reading has been taken",
            }[self.state]
            return f"{label}: no result — {reason}."
        return phrasing(self.attribution, metric=label,
                        before=self.baseline.value, after=self.observed.value,
                        window=self.window.describe(),
                        source=self.attribution_source)


def window_around(intervention: datetime, *, days: int = 30) -> Window:
    """A symmetric before-and-after, which is what `comparable` requires."""
    return Window(
        baseline_start=intervention - timedelta(days=days),
        baseline_end=intervention,
        intervention_at=intervention,
        observation_start=intervention,
        observation_end=intervention + timedelta(days=days),
    )
