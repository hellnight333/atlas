"""Allowances, and the rule that a limit reduces the day rather than cancelling it.

Doc 11 asks for a daily production loop and a twelve-a-day target while having
no concept of a limit at all. The binding one is not money: YouTube grants a
fixed daily allowance of units and an upload costs a large share of it, so the
media factory's ceiling is set by a platform that does not sell more.

The operator's instruction was explicit — when a limit binds, produce what fits
rather than stopping. That is what `plan()` is for, and most of what follows
defends it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from atlas_kernel.quota import (
    LimitKind,
    Plan,
    QuotaExhausted,
    QuotaLedger,
    QuotaPolicy,
    QuotaWindow,
)
from atlas_kernel.quota.policies import (
    YOUTUBE_DAILY_UNITS,
    YOUTUBE_UPLOAD_UNITS,
    default_policies,
    youtube_policy,
)

NOON = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


class Clock:
    """A movable clock, so a daily rollover does not take a day to test."""

    def __init__(self, at: datetime = NOON) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at

    def advance(self, **kwargs) -> None:
        self.at += timedelta(**kwargs)


def _ledger(*policies: QuotaPolicy, clock: Clock | None = None) -> tuple[QuotaLedger, Clock]:
    clock = clock or Clock()
    return QuotaLedger(list(policies), now=clock), clock


class TestTheTwoKindsOfLimit:
    """Conflating them produces the worst response to an exhausted quota:
    spending more money on a limit that money cannot move."""

    def test_a_platform_limit_says_money_will_not_help(self) -> None:
        ledger, _ = _ledger(youtube_policy())
        with pytest.raises(QuotaExhausted) as raised:
            ledger.spend("youtube.data.units", YOUTUBE_DAILY_UNITS + 1, essential=True)
        assert "not for sale" in str(raised.value)
        assert raised.value.kind is LimitKind.PLATFORM

    def test_a_spend_limit_says_the_ceiling_is_a_decision(self) -> None:
        ledger, _ = _ledger(QuotaPolicy(resource="llm.usd", limit=10.0, kind=LimitKind.SPEND))
        with pytest.raises(QuotaExhausted) as raised:
            ledger.spend("llm.usd", 50.0)
        assert "raise the ceiling" in str(raised.value)

    def test_the_error_carries_what_was_asked_and_what_was_left(self) -> None:
        ledger, _ = _ledger(QuotaPolicy(resource="r", limit=100.0))
        ledger.spend("r", 90.0)
        with pytest.raises(QuotaExhausted) as raised:
            ledger.spend("r", 50.0)
        assert raised.value.remaining == 10.0
        assert raised.value.requested == 50.0


class TestPlanningTheDay:
    """A limit reduces the day's output; it does not cancel it."""

    def test_six_uploads_fit_in_a_day_not_twelve(self) -> None:
        """The headline finding, as an executable statement. 10,000 units a day
        against 1,600 an upload is six, and doc 11 asks for twelve."""
        ledger, _ = _ledger(youtube_policy())
        plan = ledger.plan(
            "youtube.data.units", unit_cost=YOUTUBE_UPLOAD_UNITS, maximum=12, minimum=12
        )
        assert plan.count == 5, "one upload's worth is held back by the floor"
        assert plan.shortfall == 7
        assert not plan.met_the_floor

    def test_the_floor_is_available_to_essential_work(self) -> None:
        ledger, _ = _ledger(youtube_policy())
        assert (
            ledger.plan(
                "youtube.data.units",
                unit_cost=YOUTUBE_UPLOAD_UNITS,
                maximum=12,
                essential=True,
            ).count
            == 6
        )

    def test_it_produces_what_fits_rather_than_nothing(self) -> None:
        """The operator's rule: 'increase profitability rather than stop and do
        nothing'."""
        ledger, _ = _ledger(QuotaPolicy(resource="r", limit=30.0))
        plan = ledger.plan("r", unit_cost=10.0, maximum=12, minimum=5)
        assert plan.count == 3
        assert plan.shortfall == 2, "short of the floor, but still producing"

    def test_it_never_exceeds_the_ceiling_it_was_asked_for(self) -> None:
        ledger, _ = _ledger(QuotaPolicy(resource="r", limit=10_000.0))
        assert ledger.plan("r", unit_cost=1.0, maximum=12).count == 12

    def test_a_plan_of_zero_explains_itself(self) -> None:
        """A production loop that quietly returns zero is indistinguishable
        from one that is broken."""
        ledger, _ = _ledger(QuotaPolicy(resource="r", limit=10.0))
        ledger.spend("r", 10.0, essential=True)
        plan = ledger.plan("r", unit_cost=5.0, maximum=12)
        assert plan.count == 0
        assert "nothing affordable" in plan.reason
        assert "Resets at" in plan.reason

    def test_a_spend_limited_plan_of_zero_names_the_remedy(self) -> None:
        ledger, _ = _ledger(QuotaPolicy(resource="llm.usd", limit=1.0, kind=LimitKind.SPEND))
        ledger.spend("llm.usd", 1.0, essential=True)
        assert "Raise the ceiling" in ledger.plan("llm.usd", unit_cost=0.5, maximum=5).reason

    def test_meeting_the_target_is_reported_as_such(self) -> None:
        ledger, _ = _ledger(QuotaPolicy(resource="r", limit=1000.0))
        assert "covers the target" in ledger.plan("r", unit_cost=1.0, maximum=3).reason

    def test_a_nonsensical_plan_is_refused(self) -> None:
        ledger, _ = _ledger(QuotaPolicy(resource="r", limit=10.0))
        with pytest.raises(ValueError, match="unit_cost must be positive"):
            ledger.plan("r", unit_cost=0, maximum=1)
        with pytest.raises(ValueError, match="above maximum"):
            ledger.plan("r", unit_cost=1, maximum=1, minimum=5)


class TestReserveBeforeActing:
    def test_a_refused_spend_records_nothing(self) -> None:
        """A partially applied spend is worse than a refusal, because it is
        invisible."""
        ledger, _ = _ledger(QuotaPolicy(resource="r", limit=10.0))
        with pytest.raises(QuotaExhausted):
            ledger.spend("r", 99.0)
        assert ledger.remaining("r") == 10.0

    def test_affords_answers_without_raising(self) -> None:
        ledger, _ = _ledger(QuotaPolicy(resource="r", limit=10.0))
        assert ledger.affords("r", 5.0)
        assert not ledger.affords("r", 50.0)
        assert not ledger.affords("unregistered", 1.0)

    def test_an_unmetered_resource_is_an_error_not_an_allowance(self) -> None:
        """An unmetered resource is how a limit gets discovered from a 403."""
        ledger, _ = _ledger()
        with pytest.raises(KeyError, match="no quota policy"):
            ledger.spend("youtube.data.units", 1.0)

    def test_a_negative_spend_is_refused(self) -> None:
        ledger, _ = _ledger(QuotaPolicy(resource="r", limit=10.0))
        with pytest.raises(ValueError, match="cannot be negative"):
            ledger.spend("r", -5.0)


class TestTheFloor:
    def test_ordinary_work_cannot_touch_the_reserve(self) -> None:
        """A production loop that spends the whole day's quota on bulk work
        leaves nothing for the one upload that mattered."""
        ledger, _ = _ledger(QuotaPolicy(resource="r", limit=100.0, floor=20.0))
        assert ledger.remaining("r") == 80.0
        assert ledger.remaining("r", essential=True) == 100.0
        with pytest.raises(QuotaExhausted):
            ledger.spend("r", 90.0)
        ledger.spend("r", 90.0, essential=True)

    def test_a_floor_may_not_swallow_the_whole_limit(self) -> None:
        with pytest.raises(ValueError, match="leaving nothing for ordinary work"):
            QuotaPolicy(resource="r", limit=10.0, floor=10.0)


class TestWindows:
    def test_a_daily_allowance_returns_after_midnight(self) -> None:
        ledger, clock = _ledger(QuotaPolicy(resource="r", limit=10.0))
        ledger.spend("r", 10.0, essential=True)
        assert ledger.remaining("r") == 0.0
        clock.advance(hours=13)  # past midnight UTC
        assert ledger.remaining("r") == 10.0

    def test_a_rolling_window_forgives_gradually_not_at_midnight(self) -> None:
        """The difference is real: there is no hour at which a burst is
        forgiven, so a scheduler assuming a daily reset is wrong every
        afternoon."""
        ledger, clock = _ledger(
            QuotaPolicy(resource="r", limit=10.0, window=QuotaWindow.ROLLING_24H)
        )
        ledger.spend("r", 10.0, essential=True)
        clock.advance(hours=13)  # past midnight, but inside 24h
        assert ledger.remaining("r") == 0.0, "a rolling window has no midnight"
        clock.advance(hours=12)
        assert ledger.remaining("r") == 10.0

    def test_a_rolling_window_has_no_reset_time_to_report(self) -> None:
        ledger, _ = _ledger(QuotaPolicy(resource="r", limit=10.0, window=QuotaWindow.ROLLING_24H))
        assert ledger.status("r").resets_at is None

    def test_a_monthly_allowance_returns_at_the_turn_of_the_month(self) -> None:
        ledger, clock = _ledger(QuotaPolicy(resource="r", limit=10.0, window=QuotaWindow.MONTHLY))
        ledger.spend("r", 10.0, essential=True)
        clock.advance(days=10)
        assert ledger.remaining("r") == 0.0
        clock.advance(days=10)
        assert ledger.remaining("r") == 10.0

    def test_december_rolls_into_january(self) -> None:
        clock = Clock(datetime(2026, 12, 20, tzinfo=UTC))
        ledger, _ = _ledger(
            QuotaPolicy(resource="r", limit=10.0, window=QuotaWindow.MONTHLY), clock=clock
        )
        assert ledger.status("r").resets_at == datetime(2027, 1, 1, tzinfo=UTC)


class TestReporting:
    def test_the_report_puts_the_tightest_allowance_first(self) -> None:
        """The shape a daily report needs: what is about to stop the factory."""
        ledger, _ = _ledger(
            QuotaPolicy(resource="roomy", limit=100.0),
            QuotaPolicy(resource="tight", limit=100.0),
        )
        ledger.spend("tight", 95.0)
        assert [s.resource for s in ledger.report()] == ["tight", "roomy"]

    def test_a_status_reads_as_a_sentence(self) -> None:
        ledger, _ = _ledger(QuotaPolicy(resource="r", limit=100.0))
        ledger.spend("r", 25.0)
        assert str(ledger.status("r")) == "r: 25/100 used, 75 left (platform)"

    def test_a_plan_reads_as_a_sentence(self) -> None:
        ledger, _ = _ledger(QuotaPolicy(resource="r", limit=30.0))
        assert str(ledger.plan("r", unit_cost=10.0, maximum=12)).startswith("r: 3 of 12 —")

    def test_exhaustion_is_visible_without_arithmetic(self) -> None:
        ledger, _ = _ledger(QuotaPolicy(resource="r", limit=10.0))
        assert not ledger.status("r").exhausted
        ledger.spend("r", 10.0, essential=True)
        assert ledger.status("r").exhausted


class TestTheDefaults:
    def test_youtube_is_the_binding_constraint_out_of_the_box(self) -> None:
        ledger = QuotaLedger(default_policies(), now=Clock())
        assert ledger.status("youtube.data.units").kind is LimitKind.PLATFORM
        assert ledger.remaining("youtube.data.units") < YOUTUBE_DAILY_UNITS

    def test_instagram_is_rolling_and_youtube_is_daily(self) -> None:
        """Getting this backwards makes a scheduler wrong every afternoon."""
        ledger = QuotaLedger(default_policies(), now=Clock())
        assert ledger.status("instagram.publish.posts").window is QuotaWindow.ROLLING_24H
        assert ledger.status("youtube.data.units").window is QuotaWindow.DAILY

    def test_metered_providers_are_spend_limits_not_platform_limits(self) -> None:
        ledger = QuotaLedger(default_policies(), now=Clock())
        for resource in ("places.search.usd", "llm.usd", "brave.search.queries"):
            assert ledger.status(resource).kind is LimitKind.SPEND

    def test_every_default_is_registered_and_usable(self) -> None:
        ledger = QuotaLedger(default_policies(), now=Clock())
        assert len(ledger.report()) == len(default_policies())


class TestPlanIsPlainData:
    def test_a_plan_can_be_serialised_for_a_report(self) -> None:
        plan = Plan(resource="r", count=3, requested=12, shortfall=2, reason="because")
        assert plan.model_dump()["count"] == 3
