"""Which niche, which geography — measured rather than argued about.

Choosing a target market by opinion is a bottleneck with a person in it. This
measures instead: for every (area, niche) pair, discover real businesses,
inspect a sample of their real sites, and report what actually came back. Run it
on a schedule and the answer stays current without anybody being asked.

**The metric is deliberately not "how many lack a website."** Measured live in
Dubai, 98% of car-repair entries had no OpenStreetMap website tag, which is a
fact about volunteer tagging rather than about Dubai. A market is worth entering
only when three things are true at once, so all three are measured:

* **Findable** — enough named businesses exist to work through.
* **Defective** — inspection of their real sites produces evidenced findings
  above the qualification bar. Not a guess from a missing tag.
* **Reachable** — there is some way to contact them. This is the one that
  disqualifies markets in practice, and the one nobody thinks to check: a
  perfect prospect with no email and no phone is not a prospect.

``opportunity_rate`` multiplies qualified by reachable precisely because a niche
that scores well on one and badly on the other is worthless, and an average
would hide that.

Sampling is bounded on purpose. Inspecting every business in a niche means
thousands of live HTTP requests to real companies; a sample answers the question
at a fraction of the cost, and the sample size is recorded so the confidence is
legible rather than implied.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from .detectors.base import DetectorRegistry
from .models import NicheProfile, OpportunityStage
from .qualification import qualify


@dataclass
class MarketResult:
    """What one (area, niche) pair looks like right now."""

    area: str
    niche: str
    #: Businesses the source returned.
    found: int = 0
    #: Of those, how many carry any contact route at all.
    with_email: int = 0
    with_phone: int = 0
    with_website: int = 0
    #: How many were actually inspected. Recorded so the rates below are
    #: readable as estimates rather than as counts.
    sampled: int = 0
    qualified: int = 0
    #: Sources that failed, so a degraded scan does not read as a poor market.
    error: str | None = None
    measured_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def reachable(self) -> int:
        """Contactable by anything. Email or phone — a name alone is not a lead."""
        return max(self.with_email, self.with_phone)

    @property
    def reachable_rate(self) -> float:
        return self.reachable / self.found if self.found else 0.0

    @property
    def qualified_rate(self) -> float:
        """Share of *inspected* businesses with real, evidenced defects."""
        return self.qualified / self.sampled if self.sampled else 0.0

    @property
    def opportunity_rate(self) -> float:
        """Qualified and reachable together.

        A product rather than an average: a niche full of broken websites you
        cannot contact is worth nothing, and averaging would let one good half
        hide the other.
        """
        return self.qualified_rate * self.reachable_rate

    @property
    def estimated_prospects(self) -> float:
        """Roughly how many workable prospects the niche holds."""
        return self.found * self.opportunity_rate

    def as_row(self) -> dict[str, object]:
        return {
            "area": self.area,
            "niche": self.niche,
            "found": self.found,
            "sampled": self.sampled,
            "qualified_rate": round(self.qualified_rate, 3),
            "reachable_rate": round(self.reachable_rate, 3),
            "opportunity_rate": round(self.opportunity_rate, 4),
            "estimated_prospects": round(self.estimated_prospects, 1),
            "error": self.error,
        }


@dataclass
class MarketScan:
    """Measures markets. Contacts nobody."""

    detectors: DetectorRegistry
    #: How many businesses to inspect per niche. Every one is a live request to
    #: a real company, so this is a cost dial, not a detail.
    sample_size: int = 12
    #: How many to ask the source for. Bounds the estimate of market size.
    discover_limit: int = 400

    def measure(self, source, profile: NicheProfile, *, area: str, niche: str) -> MarketResult:
        result = MarketResult(area=area, niche=niche)
        try:
            businesses = source.discover(profile, self.discover_limit)
        except Exception as error:  # noqa: BLE001 — a dead source is data, not a crash
            result.error = str(error)[:200]
            return result

        result.found = len(businesses)
        result.with_email = sum(1 for b in businesses if b.email)
        result.with_phone = sum(1 for b in businesses if b.phone)
        result.with_website = sum(1 for b in businesses if b.website)

        # Only businesses with a website can be inspected. The rest need a
        # different play — a phone call — and counting them as unqualified would
        # understate a niche that is in fact wide open.
        inspectable = [b for b in businesses if b.website][: self.sample_size]
        for business in inspectable:
            try:
                findings = self.detectors.inspect(business, profile)
            except Exception:  # noqa: BLE001 — one unreachable site is not a failed scan
                continue
            result.sampled += 1
            if qualify(business, findings, profile).stage is OpportunityStage.QUALIFIED:
                result.qualified += 1
        return result

    def rank(self, results: list[MarketResult]) -> list[MarketResult]:
        """Best market first.

        Sorted on estimated workable prospects rather than on any single rate: a
        90% qualification rate across eleven businesses is a worse market than
        30% across two thousand, and only the product says so.
        """
        return sorted(
            [r for r in results if r.error is None],
            key=lambda r: (-r.estimated_prospects, -r.opportunity_rate, r.niche),
        )


def render_report(results: list[MarketResult]) -> str:
    """A table a person can act on without opening a database."""
    lines = [
        f"{'area':<10} {'niche':<12} {'found':>6} {'smpl':>5} "
        f"{'qual%':>6} {'reach%':>7} {'opp%':>6} {'prospects':>10}",
        "-" * 70,
    ]
    for r in results:
        if r.error:
            lines.append(f"{r.area:<10} {r.niche:<12}  scan failed: {r.error[:38]}")
            continue
        lines.append(
            f"{r.area:<10} {r.niche:<12} {r.found:>6} {r.sampled:>5} "
            f"{r.qualified_rate * 100:>5.0f}% {r.reachable_rate * 100:>6.0f}% "
            f"{r.opportunity_rate * 100:>5.1f}% {r.estimated_prospects:>10.0f}"
        )
    return "\n".join(lines)
