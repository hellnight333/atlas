"""Measurement, tested on the difference between zero and nothing.

A metrics API makes this easy to lose. Search Console genuinely returns zero
clicks for a page nobody clicked — that is a measurement. A refused request, an
expired token, or a property the account cannot see returns nothing — that is our
outage. Recording the second as zero manufactures a decline out of an
authentication error, and the customer reads "your clicks fell to zero" in a
report they paid for.

The second theme is the comparison, because a measurement product's whole value
is the comparison and that is where the dishonesty lives: different windows,
different sources, or a conversion rate over eleven sessions all produce a number
that looks like a result.
"""

from __future__ import annotations

from datetime import date

import pytest

from atlas_kernel.measurement.providers import (
    MINIMUM_SAMPLE,
    SUPPLIES,
    AnalyticsProvider,
    LocalFixtureProvider,
    MeasurementProvider,
    Metric,
    PendingCredentialProvider,
    ProviderUnavailable,
    Reading,
    SearchConsoleProvider,
    change,
    comparable,
    window,
)

STARTS, ENDS = date(2026, 8, 1), date(2026, 8, 28)


def _reading(metric: Metric, value: float | None, *, source: str = "analytics",
             sample: int | None = None, starts: date = STARTS,
             ends: date = ENDS) -> Reading:
    return Reading(metric=metric, source=source, value=value, starts=starts,
                   ends=ends, sample_size=sample)


# ============================================ zero is not nothing

def test_an_unestablished_reading_is_none_and_never_zero() -> None:
    """The one distinction this module exists to preserve."""
    nothing = _reading(Metric.CLICKS, None)
    assert nothing.value is None
    assert nothing.established is False
    assert nothing.summary()["state"] == "NOT_VERIFIED"


def test_a_genuine_zero_is_a_measurement() -> None:
    """Nobody clicked. That is a fact, and it must not read as an outage."""
    measured = _reading(Metric.CLICKS, 0.0, source="search-console")
    assert measured.established is True
    assert measured.summary()["state"] == "MEASURED"


def test_an_unavailable_provider_raises_rather_than_returning_zero() -> None:
    provider = LocalFixtureProvider(unavailable=True)
    with pytest.raises(ProviderUnavailable) as refused:
        provider.read(Metric.SESSIONS, property_url="https://x.ae",
                      starts=STARTS, ends=ENDS)
    assert "not a fall to zero" in str(refused.value)


def test_a_metric_the_fixture_has_no_entry_for_is_unestablished() -> None:
    """Not zero. The fixture must preserve the same distinction the real
    providers do, or tests written against it prove the wrong thing."""
    provider = LocalFixtureProvider(readings={Metric.CLICKS: 12.0})
    reading = provider.read(Metric.SESSIONS, property_url="https://x.ae",
                            starts=STARTS, ends=ENDS)
    assert reading.value is None
    assert reading.established is False


def test_the_fixture_invents_no_plausible_traffic() -> None:
    """A generator of realistic numbers makes every test a test of the
    generator, and a demo indistinguishable from a real measurement."""
    empty = LocalFixtureProvider()
    reading = empty.read(Metric.CLICKS, property_url="https://x.ae",
                         starts=STARTS, ends=ENDS)
    assert reading.value is None


# ============================================ a source answers what it can

def test_a_provider_refuses_a_metric_it_cannot_supply() -> None:
    """Asking and recording the empty answer would look like a measurement."""
    console = LocalFixtureProvider(supplies=SUPPLIES["search-console"])
    with pytest.raises(ProviderUnavailable, match="does not supply"):
        console.read(Metric.SESSIONS, property_url="https://x.ae",
                     starts=STARTS, ends=ENDS)


def test_the_two_sources_supply_different_metrics() -> None:
    assert Metric.CLICKS in SUPPLIES["search-console"]
    assert Metric.SESSIONS in SUPPLIES["analytics"]
    assert not (SUPPLIES["search-console"] & SUPPLIES["analytics"])


# ============================================ pending, and named

def test_search_console_names_its_credential_and_refuses() -> None:
    provider = SearchConsoleProvider()
    assert provider.credential == "QEVIK_SEARCH_CONSOLE_REFRESH_TOKEN"
    with pytest.raises(ProviderUnavailable) as refused:
        provider.read(Metric.CLICKS, property_url="https://x.ae",
                      starts=STARTS, ends=ENDS)
    assert "Credential Centre" in str(refused.value)
    assert "different from the number being zero" in str(refused.value)


def test_analytics_names_its_credential_and_refuses() -> None:
    provider = AnalyticsProvider()
    assert provider.credential == "QEVIK_ANALYTICS_REFRESH_TOKEN"
    with pytest.raises(ProviderUnavailable):
        provider.read(Metric.SESSIONS, property_url="https://x.ae",
                      starts=STARTS, ends=ENDS)


def test_both_credentials_are_the_names_the_centre_uses() -> None:
    """So the refusal and the Credential Centre name one thing."""
    from atlas_kernel.integrations import BY_ID

    assert SearchConsoleProvider().credential == BY_ID["search-console"].credential
    assert AnalyticsProvider().credential == BY_ID["analytics"].credential


def test_a_pending_provider_still_declares_what_it_would_measure() -> None:
    """An absent provider is an invisible gap; this one can be listed."""
    assert SearchConsoleProvider().supplies == SUPPLIES["search-console"]


def test_the_live_adapters_are_deliberately_unwritten() -> None:
    """Written blind against an API nobody can run, they would encode the exact
    mistake this module exists to prevent — Search Console returns *no row* for
    a query that matched nothing, which the naive implementation reports as
    zero impressions."""
    from pathlib import Path

    from atlas_kernel.measurement import providers

    source = Path(providers.__file__).read_text(encoding="utf-8")
    assert "httpx" not in source and "googleapiclient" not in source
    assert "deliberately unwritten" in source


def test_every_provider_satisfies_the_protocol() -> None:
    for provider in (LocalFixtureProvider(), SearchConsoleProvider(),
                     AnalyticsProvider(),
                     PendingCredentialProvider("x", credential="Y")):
        assert isinstance(provider, MeasurementProvider), provider


# ============================================ the comparison is where it lies

def test_two_readings_of_different_lengths_are_not_comparable() -> None:
    """A longer window has more of everything."""
    allowed, why = comparable(
        _reading(Metric.CLICKS, 100.0, ends=date(2026, 8, 7)),
        _reading(Metric.CLICKS, 200.0))
    assert allowed is False
    assert "days against" in why


def test_two_sources_are_not_comparable_with_each_other() -> None:
    """They count differently; a difference between them is not a change in the
    business."""
    allowed, why = comparable(
        _reading(Metric.CLICKS, 100.0, source="search-console"),
        _reading(Metric.CLICKS, 120.0, source="analytics"))
    assert allowed is False
    assert "count differently" in why


def test_an_unestablished_reading_cannot_be_compared() -> None:
    """The difference between a number and nothing is not a change."""
    allowed, why = comparable(_reading(Metric.CLICKS, None),
                              _reading(Metric.CLICKS, 120.0))
    assert allowed is False
    assert "not a change" in why


def test_a_ratio_over_a_tiny_sample_is_refused() -> None:
    """It may be one visitor out of two, and it renders as 50%."""
    allowed, why = comparable(
        _reading(Metric.CONVERSION_RATE, 0.5, sample=2),
        _reading(Metric.CONVERSION_RATE, 0.25, sample=4))
    assert allowed is False
    assert str(MINIMUM_SAMPLE) in why


def test_a_ratio_with_no_sample_size_is_refused() -> None:
    allowed, why = comparable(_reading(Metric.CONVERSION_RATE, 0.5),
                              _reading(Metric.CONVERSION_RATE, 0.6))
    assert allowed is False
    assert "no sample size" in why


def test_a_ratio_over_a_real_sample_compares() -> None:
    """The negative control: the refusals above are about the sample, not about
    ratios being refused generally."""
    allowed, _ = comparable(
        _reading(Metric.CONVERSION_RATE, 0.02, sample=500),
        _reading(Metric.CONVERSION_RATE, 0.03, sample=600))
    assert allowed is True


def test_change_refuses_to_state_a_number_it_cannot_defend() -> None:
    """A caller showing a customer "+18%" has to have passed `comparable`, and
    this makes that structural rather than a convention."""
    result = change(_reading(Metric.CLICKS, None), _reading(Metric.CLICKS, 120.0))
    assert result["comparable"] is False
    assert result["delta"] is None
    assert result["state"] == "NOT_VERIFIED"


def test_a_real_change_is_stated_with_its_window_and_source() -> None:
    result = change(_reading(Metric.CLICKS, 100.0, source="search-console"),
                    _reading(Metric.CLICKS, 118.0, source="search-console"))
    assert result["comparable"] is True
    assert result["delta"] == 18.0
    assert "search-console" in result["statement"]
    assert "28 days" in result["statement"]


# ============================================ windows

def test_a_window_never_includes_today() -> None:
    """Both sources report partial data for the current day, and a partial day
    compared against a whole one is a fall that did not happen."""
    from datetime import UTC, datetime

    starts, ends = window(28)
    assert ends < datetime.now(UTC).date()
    assert (ends - starts).days == 27


def test_a_window_is_the_length_asked_for() -> None:
    starts, ends = window(7, ending=date(2026, 8, 28))
    assert starts == date(2026, 8, 22) and ends == date(2026, 8, 28)
    assert _reading(Metric.CLICKS, 1.0, starts=starts, ends=ends).days == 7
