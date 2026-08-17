"""Google Places discovery, and the spending it does (LEVEL 5).

This source exists because the market scan measured the real constraint:
reachability sat between 2% and 17% across every Dubai niche on OpenStreetMap,
and that — not defect rate — is what made markets unworkable.

It also spends money on every call, so half of what these tests defend is the
bill. The field mask is billed per tier, pagination is capped, and the key must
come from the environment rather than from anywhere a `git add -A` could reach.
"""

from __future__ import annotations

import httpx
import pytest

from atlas_kernel.opportunity.profiles import EXAMPLE_PROFILE
from atlas_kernel.opportunity.sources.google_places import (
    FIELD_MASK,
    GooglePlacesSource,
    NotConfigured,
    PlacesError,
    api_key,
)

PLACE = {
    "id": "ChIJ_example",
    "displayName": {"text": "Al Quoz Auto Garage"},
    "websiteUri": "https://alquozauto.ae",
    "nationalPhoneNumber": "04 123 4567",
    "formattedAddress": "Al Quoz Industrial 3, Dubai",
}


def _source(handler, **kwargs) -> GooglePlacesSource:
    return GooglePlacesSource(
        query=kwargs.pop("query", "car repair in Dubai"),
        key="test-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        **kwargs,
    )


@pytest.fixture(autouse=True)
def no_inherited_key(monkeypatch: pytest.MonkeyPatch):
    """A developer with a real key exported would otherwise run a different test
    from CI, and the one that passes locally is the one nobody investigates."""
    for name in (
        "QEVIK_GOOGLE_PLACES_API_KEY",
        "ATLAS_GOOGLE_PLACES_API_KEY",
        "GOOGLE_PLACES_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


class TestSpending:
    def test_the_field_mask_asks_only_for_what_a_prospect_needs(self) -> None:
        """Every field is billed, and one expensive field promotes the whole
        request to a dearer tier. None of these change whether a business is
        worth contacting about a broken website."""
        for costly in ("photos", "reviews", "rating", "openingHours", "location", "priceLevel"):
            assert costly not in FIELD_MASK, f"{costly} is billed and is not needed"

    def test_it_asks_for_the_fields_a_prospect_actually_needs(self) -> None:
        for needed in ("displayName", "websiteUri", "nationalPhoneNumber"):
            assert needed in FIELD_MASK

    def test_pagination_is_capped_so_a_scan_cannot_spend_without_bound(self) -> None:
        """An unbounded crawl of a dense city is a large invoice arriving
        quietly."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"places": [PLACE], "nextPageToken": "more"})

        source = _source(handler, max_pages=2)
        source.discover(EXAMPLE_PROFILE, 500)
        assert source.requests_made == 2

    def test_it_stops_paging_once_the_limit_is_met(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"places": [PLACE] * 20, "nextPageToken": "more"})

        source = _source(handler, max_pages=5)
        found = source.discover(EXAMPLE_PROFILE, 20)
        assert len(found) == 20
        assert source.requests_made == 1, "paid for a page it did not need"

    def test_it_reports_what_it_spent(self) -> None:
        """So a caller can state the cost rather than estimate it."""
        source = _source(lambda r: httpx.Response(200, json={"places": [PLACE]}))
        source.discover(EXAMPLE_PROFILE, 10)
        assert source.requests_made == 1
        assert source.approx_cost_usd > 0


class TestTheKey:
    def test_a_missing_key_says_exactly_what_to_do(self) -> None:
        with pytest.raises(NotConfigured) as raised:
            api_key()
        message = str(raised.value)
        assert "QEVIK_GOOGLE_PLACES_API_KEY" in message
        assert "Places API (New)" in message

    def test_the_key_comes_from_the_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("QEVIK_GOOGLE_PLACES_API_KEY", "from-env")
        assert api_key() == "from-env"

    def test_a_blank_key_counts_as_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("QEVIK_GOOGLE_PLACES_API_KEY", "   ")
        with pytest.raises(NotConfigured):
            api_key()

    def test_the_key_travels_in_a_header_not_a_url(self) -> None:
        """A key in a query string lands in logs, proxies and referrers."""
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"places": []})

        _source(handler).discover(EXAMPLE_PROFILE, 5)
        assert seen[0].headers["X-Goog-Api-Key"] == "test-key"
        assert "test-key" not in str(seen[0].url)


class TestReachability:
    def test_it_brings_back_the_contact_details_osm_lacks(self) -> None:
        """The entire reason this source exists and costs money."""
        found = _source(lambda r: httpx.Response(200, json={"places": [PLACE]})).discover(
            EXAMPLE_PROFILE, 10
        )
        assert found[0].phone == "04 123 4567"
        assert found[0].website == "https://alquozauto.ae"
        assert found[0].metadata["address"] == "Al Quoz Industrial 3, Dubai"

    def test_it_does_not_invent_an_email(self) -> None:
        """Places does not return email. The outreach path needs one and this
        source honestly cannot supply it."""
        found = _source(lambda r: httpx.Response(200, json={"places": [PLACE]})).discover(
            EXAMPLE_PROFILE, 10
        )
        assert found[0].email is None

    def test_a_missing_website_is_recorded_as_a_fact_about_google(self) -> None:
        """Not about the business. The detector's own fetch earns that claim."""
        place = {k: v for k, v in PLACE.items() if k != "websiteUri"}
        found = _source(lambda r: httpx.Response(200, json={"places": [place]})).discover(
            EXAMPLE_PROFILE, 10
        )
        assert found[0].website is None
        assert found[0].metadata["website_absent_in_places"] is True

    def test_unnamed_places_are_dropped(self) -> None:
        nameless = {"id": "x", "formattedAddress": "somewhere"}
        found = _source(lambda r: httpx.Response(200, json={"places": [nameless, PLACE]})).discover(
            EXAMPLE_PROFILE, 10
        )
        assert [b.name for b in found] == ["Al Quoz Auto Garage"]


class TestFailures:
    def test_a_rejected_key_names_the_three_real_causes(self) -> None:
        source = _source(lambda r: httpx.Response(403, text="denied"))
        with pytest.raises(PlacesError) as raised:
            source.discover(EXAMPLE_PROFILE, 5)
        assert "Places API (New) is enabled" in str(raised.value)

    def test_an_error_never_echoes_the_request(self) -> None:
        """Google's free-text errors can echo the request, and the request
        carries the API key."""
        source = _source(lambda r: httpx.Response(400, text="key=test-key was invalid"))
        with pytest.raises(PlacesError) as raised:
            source.discover(EXAMPLE_PROFILE, 5)
        assert "test-key" not in str(raised.value)

    def test_rate_limiting_says_to_back_off(self) -> None:
        with pytest.raises(PlacesError, match="rate-limited"):
            _source(lambda r: httpx.Response(429)).discover(EXAMPLE_PROFILE, 5)

    def test_a_transport_failure_is_a_places_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route")

        with pytest.raises(PlacesError, match="could not reach"):
            _source(handler).discover(EXAMPLE_PROFILE, 5)

    def test_a_non_json_body_does_not_crash_the_caller(self) -> None:
        with pytest.raises(PlacesError, match="non-JSON"):
            _source(lambda r: httpx.Response(200, text="<html>")).discover(EXAMPLE_PROFILE, 5)


class TestItIsAnOrdinarySource:
    def test_it_satisfies_the_business_source_protocol(self) -> None:
        from atlas_kernel.opportunity.detectors.base import BusinessSource

        assert isinstance(
            _source(lambda r: httpx.Response(200, json={"places": []})), BusinessSource
        )

    def test_it_registers_alongside_the_free_sources(self) -> None:
        """Adding a paid source is a registration; identity resolution then
        merges what both found about the same company."""
        from atlas_kernel.opportunity.detectors.base import DetectorRegistry
        from atlas_kernel.opportunity.sources import SeedListSource

        registry = DetectorRegistry()
        registry.register_source(
            SeedListSource.from_csv("name,website\nAl Quoz Auto Garage,https://alquozauto.ae\n")
        )
        registry.register_source(_source(lambda r: httpx.Response(200, json={"places": [PLACE]})))
        result = registry.discover(EXAMPLE_PROFILE, limit=10)
        assert len(result.businesses) == 1, "the same garage should resolve to one record"
        assert result.duplicates_merged == 1
