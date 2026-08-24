"""Where measurements come from, and what it means when they do not come.

Search Console and Analytics are the two sources that make recurring measurement
worth paying for — without one of them a monthly report says `NOT_VERIFIED` for
every metric, which is worse than no subscription.

The whole module is arranged around one distinction that a metrics API makes
easy to lose:

**Zero and unavailable are different, and only one of them is a fact about the
business.** Search Console genuinely returns zero clicks for a page nobody
clicked — that is a measurement. A refused request, an expired token, or a
property the account cannot see returns nothing at all — that is our outage.
Recording the second as zero manufactures a decline out of an authentication
error, and the customer sees "your clicks fell to zero" in a report they paid
for.

So `Reading.value` is `None` when nothing was established, never `0.0`, and
`ProviderUnavailable` is raised rather than a zero returned. The same reasoning
`aivisibility` uses for "not mentioned" versus "could not ask", applied to
numbers, where it is easier to get wrong because a number always looks like data.

Three implementations, in the pattern the AI-visibility adapters already set:
a protocol, a deterministic local provider for tests, and a
`PendingCredentialProvider` that names the credential and refuses.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class ProviderUnavailable(RuntimeError):
    """No credential, or the source refused. Never a measurement of zero."""


class Metric(StrEnum):
    """What can be measured, named as the customer would name it."""

    IMPRESSIONS = "impressions"
    CLICKS = "clicks"
    POSITION = "position"
    SESSIONS = "sessions"
    CONVERSION_RATE = "conversion_rate"
    BOUNCE_RATE = "bounce_rate"


#: Which source supplies which metric. One registry, so a metric cannot be
#: requested from a provider that has no way to answer it — which would return
#: an empty reading indistinguishable from a genuine absence.
SUPPLIES: dict[str, frozenset[Metric]] = {
    "search-console": frozenset({Metric.IMPRESSIONS, Metric.CLICKS,
                                 Metric.POSITION}),
    "analytics": frozenset({Metric.SESSIONS, Metric.CONVERSION_RATE,
                            Metric.BOUNCE_RATE}),
}


class Reading(BaseModel):
    """One metric over one window, or the honest absence of one."""

    model_config = ConfigDict(frozen=True)

    metric: Metric
    source: str
    #: `None` when nothing was established. **Never 0.0 for that case** — a
    #: refused request is not a measurement of zero, and the difference is the
    #: difference between "nobody visited" and "we could not look".
    value: float | None = None
    #: The window this covers. A number with no window cannot be compared with
    #: the next one.
    starts: date
    ends: date
    #: Present only when the source genuinely reported it.
    sample_size: int | None = None
    detail: str = ""
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def established(self) -> bool:
        return self.value is not None

    @property
    def days(self) -> int:
        return (self.ends - self.starts).days + 1

    def summary(self) -> dict:
        return {"metric": self.metric.value, "source": self.source,
                "value": self.value, "established": self.established,
                "starts": self.starts.isoformat(), "ends": self.ends.isoformat(),
                "days": self.days, "sample_size": self.sample_size,
                "detail": self.detail, "at": self.at.isoformat(),
                "state": "MEASURED" if self.established else "NOT_VERIFIED"}


@runtime_checkable
class MeasurementProvider(Protocol):
    """Somewhere a metric can be read for a property over a window."""

    @property
    def name(self) -> str: ...

    @property
    def supplies(self) -> frozenset[Metric]:
        """Which metrics this source can genuinely answer."""
        ...

    def read(self, metric: Metric, *, property_url: str, starts: date,
             ends: date) -> Reading:
        """Read one metric. Raise `ProviderUnavailable` rather than return zero."""
        ...


class LocalFixtureProvider:
    """A deterministic stand-in for tests and local development.

    Answers from an explicit fixture and never invents a plausible number. A
    provider that generated realistic-looking traffic would make every test a
    test of the generator, and would make a demo indistinguishable from a real
    measurement — which is the one thing a measurement product cannot afford.
    """

    def __init__(self, *, name: str = "local-fixture",
                 supplies: frozenset[Metric] | None = None,
                 readings: dict[Metric, float] | None = None,
                 sample_sizes: dict[Metric, int] | None = None,
                 unavailable: bool = False) -> None:
        self._name = name
        self._supplies = supplies or frozenset(Metric)
        self._readings = dict(readings or {})
        self._samples = dict(sample_sizes or {})
        self._unavailable = unavailable

    @property
    def name(self) -> str:
        return self._name

    @property
    def supplies(self) -> frozenset[Metric]:
        return self._supplies

    def read(self, metric: Metric, *, property_url: str, starts: date,
             ends: date) -> Reading:
        if self._unavailable:
            raise ProviderUnavailable(
                f"{self._name} could not be reached, so nothing was measured. "
                "This is our outage, not a fall to zero.")
        if metric not in self._supplies:
            raise ProviderUnavailable(
                f"{self._name} does not supply {metric.value}. Asking it and "
                "recording the empty answer would look like a measurement.")
        # A metric the fixture has no entry for is *unestablished*, not zero —
        # the same distinction the real providers must preserve.
        value = self._readings.get(metric)
        return Reading(metric=metric, source=self._name, value=value,
                       starts=starts, ends=ends,
                       sample_size=self._samples.get(metric),
                       detail="" if value is not None else
                              "the fixture holds no reading for this metric")


class PendingCredentialProvider:
    """A real source before anybody has connected it.

    Registered rather than absent, so the system can name the source, say what
    it would measure and what it needs, and refuse cleanly. An absent provider
    is an invisible gap; this one appears in the Credential Centre.
    """

    def __init__(self, name: str, *, credential: str,
                 supplies: frozenset[Metric] | None = None) -> None:
        self._name = name
        self.credential = credential
        self._supplies = supplies or SUPPLIES.get(name, frozenset())

    @property
    def name(self) -> str:
        return self._name

    @property
    def supplies(self) -> frozenset[Metric]:
        return self._supplies

    def read(self, metric: Metric, *, property_url: str, starts: date,
             ends: date) -> Reading:
        raise ProviderUnavailable(
            f"{self._name} is not connected. Add {self.credential} in the "
            f"Credential Centre to measure {metric.value}. Until then nothing "
            "is established, which is different from the number being zero.")


class SearchConsoleProvider(PendingCredentialProvider):
    """Google Search Console — impressions, clicks and average position.

    The live adapter is deliberately unwritten rather than written and untested.
    Search Console's API returns rows a query matched, and a query that matched
    nothing returns *no row* — so the naive implementation reports zero
    impressions for a page it never asked about correctly. Writing that against
    no credential, with no way to run it, would produce code that looks finished
    and encodes exactly the mistake this module exists to prevent.

    What it needs, precisely: an OAuth refresh token for an account with at least
    `siteRestrictedFullUser` on the property, and the property verified in
    Search Console. Both are the customer's, not ours.
    """

    def __init__(self) -> None:
        super().__init__("search-console",
                         credential="QEVIK_SEARCH_CONSOLE_REFRESH_TOKEN",
                         supplies=SUPPLIES["search-console"])


class AnalyticsProvider(PendingCredentialProvider):
    """Web analytics — sessions, conversion rate, bounce rate.

    Same position as Search Console, with one extra hazard worth recording: a
    conversion rate is a ratio, and a ratio over a tiny sample is noise wearing
    the clothes of a measurement. `Reading.sample_size` exists for that, and
    `comparable()` refuses a comparison whose sample cannot support it.
    """

    def __init__(self) -> None:
        super().__init__("analytics",
                         credential="QEVIK_ANALYTICS_REFRESH_TOKEN",
                         supplies=SUPPLIES["analytics"])


#: Below this, a ratio is noise. Named rather than inlined so the threshold can
#: be argued with instead of discovered.
MINIMUM_SAMPLE = 30

#: Ratios, where a small sample makes the number meaningless.
RATIOS: frozenset[Metric] = frozenset({Metric.CONVERSION_RATE,
                                       Metric.BOUNCE_RATE})


def comparable(before: Reading, after: Reading) -> tuple[bool, str]:
    """Whether these two readings can honestly be compared.

    A measurement product's whole value is the comparison, and the comparison is
    where the dishonesty lives: different windows, different sources, or a
    conversion rate over eleven sessions all produce a number that looks like a
    result.
    """
    if not before.established or not after.established:
        return False, ("one of these was never established, so the difference "
                       "between them is not a change")
    if before.metric is not after.metric:
        return False, "these are different metrics"
    if before.source != after.source:
        return False, (f"{before.source} and {after.source} count differently; "
                       "a difference between them is not a change in the business")
    if before.days != after.days:
        return False, (f"{before.days} days against {after.days} — a longer "
                       "window has more of everything")
    if before.metric in RATIOS:
        samples = [r.sample_size for r in (before, after)]
        if any(s is None for s in samples):
            return False, ("a ratio with no sample size cannot be judged; it "
                           "may be one visitor out of two")
        if any(s < MINIMUM_SAMPLE for s in samples if s is not None):
            return False, (f"the sample is under {MINIMUM_SAMPLE}, so this "
                           "ratio is noise rather than a measurement")
    return True, "same metric, same source, same window length"


def change(before: Reading, after: Reading) -> dict:
    """The difference, or a refusal to state one.

    Never returns a number it cannot defend. A caller showing a customer "+18%"
    has to have passed `comparable` first, and this makes that structural rather
    than a convention.
    """
    allowed, why = comparable(before, after)
    if not allowed:
        return {"comparable": False, "why": why, "delta": None,
                "state": "NOT_VERIFIED",
                "statement": f"No comparison is possible: {why}."}
    delta = (after.value or 0.0) - (before.value or 0.0)
    return {
        "comparable": True, "why": why, "delta": round(delta, 4),
        "metric": after.metric.value, "source": after.source,
        "before": before.value, "after": after.value,
        "state": "MEASURED",
        "statement": (f"{after.metric.value} moved from {before.value} to "
                      f"{after.value} over {after.days} days, measured by "
                      f"{after.source}."),
    }


def window(days: int, *, ending: date | None = None) -> tuple[date, date]:
    """A closed window ending yesterday by default.

    Never today: both sources report partial data for the current day, and a
    partial day compared against a whole one is a fall that did not happen.
    """
    last = ending or (datetime.now(UTC).date() - timedelta(days=1))
    return last - timedelta(days=days - 1), last
