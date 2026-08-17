"""Limits, and the difference between the two kinds.

Doc 11 specifies a daily production loop and a twelve-a-day target. Neither is
reachable without knowing what the accounts can actually spend, and the document
has no concept of a limit at all. This package is that concept.

**The distinction that matters is whether money can raise the limit.**

A `SPEND` limit is a budget. Brave, Places and the language models all bill per
call, and if the ceiling binds, raising it is a decision about profitability —
exactly the trade the operator asked for: set a floor and a ceiling and keep
producing rather than stopping.

A `PLATFORM` limit is not for sale. The YouTube Data API grants a fixed daily
allowance of units and no amount of money buys more; raising it means an audited
extension request that takes weeks and is often refused. Instagram and TikTok
behave the same way.

Conflating them produces the worst possible response to an exhausted quota:
spending more money on a limit that money cannot move. So `LimitKind` is on
every policy, and an exhaustion error says which kind it hit — because "raise
the budget" and "wait until the window resets" are different actions and only
one of them is available.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class LimitKind(StrEnum):
    """Whether money can raise this limit."""

    #: Billed per unit. The ceiling is a business decision.
    SPEND = "spend"
    #: Granted by a platform. Money does not raise it; an audited request might.
    PLATFORM = "platform"


class QuotaWindow(StrEnum):
    """When the allowance resets."""

    #: Resets at midnight UTC. YouTube's daily quota works this way.
    DAILY = "daily"
    #: A moving 24-hour window. Instagram's publishing limit works this way,
    #: and it is genuinely different: there is no hour at which everything is
    #: forgiven, so a burst is repaid gradually rather than all at once.
    ROLLING_24H = "rolling_24h"
    MONTHLY = "monthly"


class QuotaExhausted(RuntimeError):
    """The allowance is gone.

    Carries the kind, because the remedy depends on it and a caller that cannot
    tell them apart will try to buy its way out of a platform limit.
    """

    def __init__(self, resource: str, kind: LimitKind, remaining: float, requested: float) -> None:
        self.resource = resource
        self.kind = kind
        self.remaining = remaining
        self.requested = requested
        remedy = (
            "raise the ceiling if the work is worth it"
            if kind is LimitKind.SPEND
            else "wait for the window to reset, or apply for an extension — this one is not for sale"
        )
        super().__init__(f"{resource}: asked for {requested:g}, {remaining:g} left. {remedy}.")


class QuotaPolicy(BaseModel):
    """One allowance.

    `floor` is the part held back. A production loop that spends its whole day's
    quota on bulk work leaves nothing for the one upload that mattered, so the
    floor is reserved for work marked essential and is invisible to everything
    else.
    """

    model_config = ConfigDict(frozen=True)

    #: Dotted and specific: "youtube.videos.insert", not "youtube". Two
    #: operations against one API usually have different costs and sometimes
    #: different windows.
    resource: str
    limit: float = Field(gt=0)
    window: QuotaWindow = QuotaWindow.DAILY
    kind: LimitKind = LimitKind.PLATFORM
    #: Held back for essential work. Must leave something for everyone else.
    floor: float = Field(default=0.0, ge=0)

    def model_post_init(self, _: object) -> None:
        if self.floor >= self.limit:
            raise ValueError(
                f"{self.resource}: a floor of {self.floor:g} reserves the entire "
                f"limit of {self.limit:g}, leaving nothing for ordinary work"
            )


class QuotaSpend(BaseModel):
    """What was actually consumed, and when.

    Kept as individual entries rather than a running total because a rolling
    window cannot be computed from a counter — it needs to know when each unit
    was spent in order to know when it is forgiven.
    """

    model_config = ConfigDict(frozen=True)

    resource: str
    amount: float
    at: datetime
    essential: bool = False
    note: str = ""


class QuotaStatus(BaseModel):
    """What is left, in the form a human or a planner can act on."""

    model_config = ConfigDict(frozen=True)

    resource: str
    kind: LimitKind
    limit: float
    used: float
    #: Excludes the floor, so ordinary work sees what it may actually take.
    remaining: float
    #: Includes the floor. What essential work can still get.
    remaining_essential: float
    window: QuotaWindow
    resets_at: datetime | None = None

    @property
    def exhausted(self) -> bool:
        return self.remaining <= 0

    def __str__(self) -> str:
        return (
            f"{self.resource}: {self.used:g}/{self.limit:g} used, "
            f"{self.remaining:g} left ({self.kind})"
        )


def window_start(window: QuotaWindow, now: datetime) -> datetime | None:
    """When the current window opened. `None` for rolling windows.

    A rolling window has no start — every unit expires on its own schedule —
    which is why it is handled by filtering entries rather than by a boundary.
    """
    now = now.astimezone(UTC)
    if window is QuotaWindow.DAILY:
        return datetime.combine(now.date(), datetime.min.time(), tzinfo=UTC)
    if window is QuotaWindow.MONTHLY:
        return datetime.combine(date(now.year, now.month, 1), datetime.min.time(), tzinfo=UTC)
    return None


def window_end(window: QuotaWindow, now: datetime) -> datetime | None:
    """When the current allowance is forgiven. `None` for rolling windows."""
    start = window_start(window, now)
    if start is None:
        return None
    if window is QuotaWindow.DAILY:
        return start + timedelta(days=1)
    year, month = (start.year + 1, 1) if start.month == 12 else (start.year, start.month + 1)
    return start.replace(year=year, month=month)
