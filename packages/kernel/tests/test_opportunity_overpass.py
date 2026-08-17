"""Real business discovery from OpenStreetMap (LEVEL 5).

Driven against a controlled transport, so the query construction and parsing are
exercised without hitting a donated public endpoint on every test run. The live
behaviour was verified separately against Dubai and is recorded in the project
state.

The property this file exists to protect is a distinction the spec makes
explicitly:

    "Do not label a business 'no website' solely because one crawler failed."

OSM's ``website`` tag being absent is a fact about OpenStreetMap, not about the
business. Measured live, 98% of Dubai car-repair entries have no website tag,
which is implausible as a true rate and tells you about volunteer tagging rather
than about Dubai. So this source produces *candidates* and records the absence
as attributable to OSM; the detector's own fetch is what earns the claim.
"""

from __future__ import annotations

import httpx
import pytest

from atlas_kernel.opportunity.profiles import EXAMPLE_PROFILE
from atlas_kernel.opportunity.sources.overpass import (
    AREAS,
    NICHES,
    OverpassError,
    OverpassSource,
    build_query,
)


def _response(elements: list[dict]) -> httpx.Response:
    return httpx.Response(200, json={"elements": elements})


def _source(handler, **kwargs) -> OverpassSource:
    return OverpassSource(client=httpx.Client(transport=httpx.MockTransport(handler)), **kwargs)


ELEMENT = {
    "type": "node",
    "id": 123,
    "tags": {
        "name": "Al Quoz Auto Garage",
        "shop": "car_repair",
        "phone": "+971 4 123 4567",
        "addr:street": "23 Street",
        "addr:city": "Dubai",
    },
}


class TestQueryConstruction:
    def test_it_bounds_the_query_by_area_and_niche(self) -> None:
        query = build_query("dubai", "car-repair", 50)
        south, west, north, east = AREAS["dubai"]
        assert f"{south},{west},{north},{east}" in query
        assert 'shop="car_repair"' in query
        assert "out center 50" in query

    def test_it_only_asks_for_named_businesses(self) -> None:
        """An unnamed node cannot be written to or researched, and would arrive
        as an anonymous row that poisons the funnel counts."""
        assert '["name"]' in build_query("dubai", "dental", 10)

    def test_every_niche_produces_a_valid_query(self) -> None:
        for niche in NICHES:
            query = build_query("dubai", niche, 5)
            assert query.startswith("[out:json]")
            assert query.rstrip().endswith(";")

    @pytest.mark.parametrize("bad", ["atlantis", "", "DUBAI"])
    def test_an_unknown_area_names_the_known_ones(self, bad: str) -> None:
        with pytest.raises(OverpassError, match="known:"):
            build_query(bad, "dental", 5)

    def test_an_unknown_niche_names_the_known_ones(self) -> None:
        with pytest.raises(OverpassError, match="known:"):
            build_query("dubai", "underwater-basket-weaving", 5)


class TestParsing:
    def test_a_business_carries_what_osm_knew(self) -> None:
        found = _source(lambda r: _response([ELEMENT])).discover(EXAMPLE_PROFILE, 10)
        assert len(found) == 1
        business = found[0]
        assert business.name == "Al Quoz Auto Garage"
        assert business.phone == "+971 4 123 4567"
        assert business.geography == "Dubai"
        assert business.sources == ["openstreetmap"]
        assert business.metadata["osm_id"] == "node/123"

    def test_a_missing_website_is_recorded_as_a_fact_about_osm(self) -> None:
        """Not as a fact about the business. The whole source depends on this
        distinction holding."""
        found = _source(lambda r: _response([ELEMENT])).discover(EXAMPLE_PROFILE, 10)
        assert found[0].website is None
        assert found[0].metadata["website_absent_in_osm"] is True

    @pytest.mark.parametrize("key", ["website", "contact:website", "url", "website:en"])
    def test_a_website_under_any_tag_counts_as_having_one(self, key: str) -> None:
        """Checking only `website` would report businesses as siteless because
        OSM filed the URL elsewhere — the exact false positive this must not
        produce."""
        element = {**ELEMENT, "tags": {**ELEMENT["tags"], key: "https://garage.ae"}}
        found = _source(lambda r: _response([element])).discover(EXAMPLE_PROFILE, 10)
        assert found[0].website == "https://garage.ae"
        assert found[0].metadata["website_absent_in_osm"] is False

    def test_unnamed_elements_are_dropped_not_invented(self) -> None:
        nameless = {"type": "node", "id": 9, "tags": {"shop": "car_repair"}}
        found = _source(lambda r: _response([nameless, ELEMENT])).discover(EXAMPLE_PROFILE, 10)
        assert [b.name for b in found] == ["Al Quoz Auto Garage"]

    def test_the_limit_is_honoured(self) -> None:
        many = [
            {**ELEMENT, "id": i, "tags": {**ELEMENT["tags"], "name": f"G{i}"}} for i in range(20)
        ]
        assert len(_source(lambda r: _response(many)).discover(EXAMPLE_PROFILE, 5)) == 5

    def test_an_empty_area_returns_nothing_rather_than_failing(self) -> None:
        assert _source(lambda r: _response([])).discover(EXAMPLE_PROFILE, 10) == []


class TestEndpointHandling:
    def test_it_falls_back_to_the_mirror_when_the_first_is_rate_limited(self) -> None:
        """Overpass is a donated shared service. Trying the mirror is the polite
        response to a 429; hammering the first endpoint is not."""
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url.host)
            if len(seen) == 1:
                return httpx.Response(429, text="slow down")
            return _response([ELEMENT])

        found = _source(handler).discover(EXAMPLE_PROFILE, 10)
        assert len(found) == 1
        assert len(seen) == 2, "did not try the second endpoint"

    def test_every_endpoint_failing_raises_rather_than_reporting_an_empty_area(self) -> None:
        """ "Found nothing" and "could not look" must not render the same way:
        one of them means the niche is exhausted."""
        with pytest.raises(OverpassError, match="no Overpass endpoint answered"):
            _source(lambda r: httpx.Response(504, text="gateway timeout")).discover(
                EXAMPLE_PROFILE, 10
            )

    def test_a_transport_failure_is_also_an_overpass_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route")

        with pytest.raises(OverpassError):
            _source(handler).discover(EXAMPLE_PROFILE, 10)

    def test_a_non_json_body_does_not_crash_the_caller(self) -> None:
        with pytest.raises(OverpassError):
            _source(lambda r: httpx.Response(200, text="<html>error</html>")).discover(
                EXAMPLE_PROFILE, 10
            )


class TestItIsAnOrdinarySource:
    def test_it_satisfies_the_business_source_protocol(self) -> None:
        from atlas_kernel.opportunity.detectors.base import BusinessSource

        assert isinstance(_source(lambda r: _response([])), BusinessSource)

    def test_it_registers_alongside_the_seed_list(self) -> None:
        """Adding discovery is a registration, not a change to any caller."""
        from atlas_kernel.opportunity.detectors.base import DetectorRegistry
        from atlas_kernel.opportunity.sources import SeedListSource

        registry = DetectorRegistry()
        registry.register_source(SeedListSource.from_csv("name,website\nA,https://a.ae\n"))
        registry.register_source(_source(lambda r: _response([ELEMENT])))
        result = registry.discover(EXAMPLE_PROFILE, limit=10)
        assert {b.name for b in result} == {"A", "Al Quoz Auto Garage"}

    def test_its_name_identifies_the_area_and_niche(self) -> None:
        """So a bad source can be switched off without switching off discovery."""
        assert _source(lambda r: _response([]), area="dubai", niche="dental").name == (
            "osm:dubai:dental"
        )
