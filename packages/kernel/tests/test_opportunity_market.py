"""Choosing a market by measurement (LEVEL 5).

Picking a niche by opinion puts a person in the loop of a question that data can
answer. This scans instead, and these tests defend the parts of it that are easy
to get subtly wrong.

The scoring is the interesting bit. A market needs to be findable, defective
*and* reachable at once, so ``opportunity_rate`` multiplies rather than averages
— a niche full of broken websites nobody can contact is worth nothing, and an
average would let one good half hide the other. Measured live in Dubai, that is
not hypothetical: contactability came back between 2% and 17% and was the
binding constraint every time.
"""

from __future__ import annotations

import httpx

from atlas_kernel.opportunity.detectors.base import DetectorRegistry
from atlas_kernel.opportunity.detectors.website import WebsiteDetector
from atlas_kernel.opportunity.market import MarketResult, MarketScan, render_report
from atlas_kernel.opportunity.models import Business
from atlas_kernel.opportunity.profiles import EXAMPLE_PROFILE

GOOD_PAGE = (
    "<!doctype html><html><head><title>Fine Garage</title>"
    '<meta name="description" content="Servicing since 2010.">'
    '<meta name="viewport" content="width=device-width">'
    '<script type="application/ld+json">{"@type":"AutoRepair"}</script>'
    "</head><body><h1>Fine Garage</h1><p>"
    + ("Full servicing, diagnostics and bodywork in Al Quoz since 2010. " * 12)
    + "</p></body></html>"
)
BAD_PAGE = "<html><body><p>Coming soon</p></body></html>"


class FixedSource:
    def __init__(self, businesses: list[Business], name: str = "fixed") -> None:
        self._businesses = businesses
        self.name = name

    def discover(self, profile, limit):
        return self._businesses[:limit]


class BrokenSource:
    name = "broken"

    def discover(self, profile, limit):
        raise RuntimeError("endpoint unreachable")


def _business(i: int, *, site: bool = True, email: bool = False, phone: bool = False) -> Business:
    return Business(
        name=f"Garage {i}",
        geography="Dubai",
        website=f"https://g{i}.test" if site else None,
        email=f"g{i}@test.ae" if email else None,
        phone="+97141234567" if phone else None,
    )


def _scan(page: str = BAD_PAGE, **kwargs) -> MarketScan:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, html=page)

    registry = DetectorRegistry()
    registry.register_detector(
        WebsiteDetector(
            client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
        )
    )
    return MarketScan(detectors=registry, **kwargs)


class TestScoring:
    def test_a_market_needs_defects_and_reachability_together(self) -> None:
        """The product, not the average. This is the whole scoring decision."""
        unreachable = MarketResult(area="d", niche="n", found=100, sampled=10, qualified=10)
        assert unreachable.qualified_rate == 1.0
        assert unreachable.reachable_rate == 0.0
        assert unreachable.opportunity_rate == 0.0, "perfect prospects nobody can contact"

    def test_reachable_counts_either_route(self) -> None:
        """A name alone is not a lead; an email or a phone is."""
        r = MarketResult(area="d", niche="n", found=100, with_email=5, with_phone=30)
        assert r.reachable == 30

    def test_rates_are_zero_rather_than_dividing_by_nothing(self) -> None:
        empty = MarketResult(area="d", niche="n")
        assert (empty.qualified_rate, empty.reachable_rate, empty.opportunity_rate) == (
            0.0,
            0.0,
            0.0,
        )

    def test_qualified_rate_is_of_the_sample_not_the_market(self) -> None:
        """Otherwise inspecting 8 of 300 would read as a 3% defect rate."""
        r = MarketResult(area="d", niche="n", found=300, sampled=8, qualified=4)
        assert r.qualified_rate == 0.5

    def test_size_beats_rate_when_ranking(self) -> None:
        """90% across eleven businesses is a worse market than 30% across two
        thousand, and only the product says so."""
        small = MarketResult(
            area="d", niche="small", found=11, sampled=10, qualified=9, with_phone=11
        )
        large = MarketResult(
            area="d", niche="large", found=2000, sampled=10, qualified=3, with_phone=2000
        )
        assert [r.niche for r in _scan().rank([small, large])] == ["large", "small"]


class TestMeasuring:
    def test_a_defective_market_scores_on_real_inspection(self) -> None:
        businesses = [_business(i, email=True) for i in range(6)]
        result = _scan(BAD_PAGE, sample_size=6).measure(
            FixedSource(businesses), EXAMPLE_PROFILE, area="dubai", niche="car-repair"
        )
        assert result.found == 6
        assert result.sampled == 6
        assert result.qualified == 6
        assert result.reachable_rate == 1.0

    def test_a_healthy_market_qualifies_nobody(self) -> None:
        """The scan must be able to say 'there is no opportunity here'."""
        result = _scan(GOOD_PAGE, sample_size=5).measure(
            FixedSource([_business(i, email=True) for i in range(5)]),
            EXAMPLE_PROFILE,
            area="dubai",
            niche="car-repair",
        )
        assert result.sampled == 5
        assert result.qualified == 0
        assert result.opportunity_rate == 0.0

    def test_businesses_with_no_website_are_not_counted_as_qualified_or_clean(self) -> None:
        """They need a phone call, not an email. Counting them as unqualified
        would understate a niche that is in fact wide open."""
        result = _scan(BAD_PAGE, sample_size=10).measure(
            FixedSource([_business(i, site=False, phone=True) for i in range(8)]),
            EXAMPLE_PROFILE,
            area="dubai",
            niche="car-repair",
        )
        assert result.found == 8
        assert result.with_website == 0
        assert result.sampled == 0, "inspected a business that has no site"

    def test_the_sample_is_bounded(self) -> None:
        """Every inspection is a live request to a real company."""
        result = _scan(BAD_PAGE, sample_size=3).measure(
            FixedSource([_business(i) for i in range(50)]),
            EXAMPLE_PROFILE,
            area="dubai",
            niche="car-repair",
        )
        assert result.found == 50
        assert result.sampled == 3

    def test_a_dead_source_is_recorded_not_raised(self) -> None:
        result = _scan().measure(BrokenSource(), EXAMPLE_PROFILE, area="dubai", niche="dental")
        assert result.error is not None
        assert "unreachable" in result.error
        assert result.found == 0

    def test_a_failed_scan_is_excluded_from_the_ranking(self) -> None:
        """A niche that could not be measured must not be ranked as a poor one."""
        good = MarketResult(area="d", niche="ok", found=100, sampled=10, qualified=5, with_phone=50)
        failed = MarketResult(area="d", niche="dead", error="boom")
        assert [r.niche for r in _scan().rank([good, failed])] == ["ok"]


class TestReport:
    def test_it_renders_a_readable_table(self) -> None:
        rows = render_report(
            [
                MarketResult(
                    area="dubai",
                    niche="car-repair",
                    found=300,
                    sampled=8,
                    qualified=1,
                    with_phone=24,
                )
            ]
        )
        assert "dubai" in rows and "car-repair" in rows
        assert "%" in rows

    def test_a_failed_scan_says_so_in_the_table(self) -> None:
        """Silently omitting it would make a half-covered scan look complete."""
        rows = render_report([MarketResult(area="dubai", niche="dental", error="endpoint down")])
        assert "scan failed" in rows
        assert "endpoint down" in rows

    def test_rows_serialise_for_storage(self) -> None:
        """Scans are meant to run daily; a trend needs the rows kept."""
        row = MarketResult(
            area="dubai", niche="beauty", found=300, sampled=6, with_phone=6
        ).as_row()
        assert row["area"] == "dubai"
        assert set(row) >= {
            "found",
            "sampled",
            "qualified_rate",
            "reachable_rate",
            "opportunity_rate",
        }


class TestItContactsNobody:
    def test_measuring_never_produces_a_proposal_or_a_message(self) -> None:
        """A scan is research. It reads public pages, as any visitor does."""
        scan = _scan(BAD_PAGE, sample_size=4)
        result = scan.measure(
            FixedSource([_business(i, email=True) for i in range(4)]),
            EXAMPLE_PROFILE,
            area="dubai",
            niche="car-repair",
        )
        assert not hasattr(result, "proposals")
        assert not hasattr(result, "messages")
        assert isinstance(result, MarketResult)
