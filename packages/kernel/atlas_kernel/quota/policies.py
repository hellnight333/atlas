"""Known platform allowances.

**Every number here is a platform policy, and platform policies change without
telling anyone.** Doc 11 §36 says not to hard-code them permanently, so these
are defaults in a configuration layer rather than constants in a connector, and
each carries the date it was believed correct.

The right posture is to treat them as an opening estimate and reconcile against
what the platform actually reports on the first real day of use. A quota model
that is confidently wrong is worse than one that is openly approximate, because
the first stops production for a reason nobody can find.
"""

from __future__ import annotations

from .models import LimitKind, QuotaPolicy, QuotaWindow

#: YouTube Data API, believed correct 2026-08.
#:
#: The default project allowance is 10,000 units per day and Google's own quota
#: calculator prices ``videos.insert`` at 1,600 units — **roughly six uploads a
#: day for the entire project**, which is the binding constraint on any daily
#: media target. At least one third-party source claims the insert cost was cut
#: by an order of magnitude; Google's published calculator had not changed when
#: this was checked. Measure real consumption on the first upload day and
#: correct this number from observation rather than from either claim.
#:
#: Not for sale. Raising it means an audited extension request that takes weeks
#: and is frequently refused, so a production plan must be built around it
#: rather than in spite of it.
YOUTUBE_DAILY_UNITS = 10_000.0
YOUTUBE_UPLOAD_UNITS = 1_600.0

#: Held back so a scheduled upload that matters is not starved by bulk work
#: earlier in the day. One upload's worth.
YOUTUBE_FLOOR_UNITS = YOUTUBE_UPLOAD_UNITS


def youtube_policy() -> QuotaPolicy:
    return QuotaPolicy(
        resource="youtube.data.units",
        limit=YOUTUBE_DAILY_UNITS,
        window=QuotaWindow.DAILY,
        kind=LimitKind.PLATFORM,
        floor=YOUTUBE_FLOOR_UNITS,
    )


def instagram_policy(limit: float = 50.0) -> QuotaPolicy:
    """Instagram content publishing, believed correct 2026-08.

    A **rolling** 24-hour window rather than a daily one, which matters: there
    is no midnight at which a burst is forgiven, so capacity returns gradually
    and a scheduler that assumes a daily reset will be wrong every afternoon.
    """
    return QuotaPolicy(
        resource="instagram.publish.posts",
        limit=limit,
        window=QuotaWindow.ROLLING_24H,
        kind=LimitKind.PLATFORM,
    )


def brave_monthly_policy(limit: float = 2_000.0) -> QuotaPolicy:
    """Brave's free tier. A spend limit in disguise — the paid tiers are larger,
    so if this binds, the question is whether the research is worth the money."""
    return QuotaPolicy(
        resource="brave.search.queries",
        limit=limit,
        window=QuotaWindow.MONTHLY,
        kind=LimitKind.SPEND,
    )


def spend_policy(resource: str, usd_per_day: float) -> QuotaPolicy:
    """A daily money ceiling for anything billed per call.

    Places, the language models and any other metered provider. Money raises
    this one, which is precisely the trade worth making when the work pays for
    itself — the point of a ceiling is to notice the decision, not to prevent
    it.
    """
    return QuotaPolicy(
        resource=resource,
        limit=usd_per_day,
        window=QuotaWindow.DAILY,
        kind=LimitKind.SPEND,
    )


def default_policies() -> list[QuotaPolicy]:
    """A starting set. Deliberately conservative on spend."""
    return [
        youtube_policy(),
        instagram_policy(),
        brave_monthly_policy(),
        spend_policy("places.search.usd", 5.0),
        spend_policy("llm.usd", 10.0),
    ]
