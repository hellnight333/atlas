"""Web search, the money it spends and the rate limit it must respect.

Places finds businesses; it cannot answer "what do this company's competitors
charge". That question is why this provider exists, and it bills per query, so
half of what these tests defend is the invoice and the other half is the rule
that search results are data rather than instruction.
"""

from __future__ import annotations

import httpx
import pytest

from atlas_kernel.research import (
    WEB_SEARCH,
    BraveSearch,
    NotConfigured,
    SearchError,
    SearchQuery,
)
from atlas_kernel.research.brave import api_key

BODY = {
    "web": {
        "results": [
            {
                "url": "https://example.ae/pricing",
                "title": "Pricing — Example Garage",
                "description": "Full service from AED 300.",
                "age": "2 weeks ago",
            },
            {
                "url": "https://competitor.ae",
                "title": "Competitor",
                "description": "Dubai's oldest workshop.",
            },
        ]
    }
}


def _search(handler, **kwargs) -> BraveSearch:
    return BraveSearch(
        key="test-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        # Nothing here should sleep for a second per request.
        min_interval=kwargs.pop("min_interval", 0.0),
        **kwargs,
    )


@pytest.fixture(autouse=True)
def no_inherited_key(monkeypatch: pytest.MonkeyPatch):
    """A developer with a real key exported would otherwise run a different
    test from CI, and the one that passes locally is the one nobody
    investigates."""
    for prefix in ("QEVIK_", "ATLAS_", ""):
        monkeypatch.delenv(f"{prefix}BRAVE_API_KEY", raising=False)


class TestSearching:
    def test_it_answers_the_question_places_cannot(self) -> None:
        found = _search(lambda r: httpx.Response(200, json=BODY)).search("garage pricing dubai")
        assert found.urls == ["https://example.ae/pricing", "https://competitor.ae"]
        assert found.results[0].title == "Pricing — Example Garage"
        assert found.results[0].age == "2 weeks ago"

    def test_a_bare_string_is_a_valid_query(self) -> None:
        """The common case should not require constructing a model."""
        assert _search(lambda r: httpx.Response(200, json=BODY)).search("x").query == "x"

    def test_results_without_a_url_are_dropped(self) -> None:
        body = {"web": {"results": [{"title": "no link"}, BODY["web"]["results"][0]]}}
        found = _search(lambda r: httpx.Response(200, json=body)).search("x")
        assert found.urls == ["https://example.ae/pricing"]

    def test_an_empty_index_is_not_an_error(self) -> None:
        """Distinct from a rejected key, which is."""
        assert len(_search(lambda r: httpx.Response(200, json={})).search("x")) == 0

    def test_the_market_and_the_age_of_a_page_can_be_narrowed(self) -> None:
        """SA rather than AE: Brave supports Saudi Arabia and not the Emirates.
        See TestMarketNarrowing."""
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=BODY)

        _search(handler).search(SearchQuery(text="x", country="SA", freshness="pm"))
        assert "country=SA" in str(seen[0].url)
        assert "freshness=pm" in str(seen[0].url)


class TestSpending:
    def test_a_query_cannot_ask_for_an_unbounded_page(self) -> None:
        """Providers cap a page at 20, then charge for the request anyway."""
        with pytest.raises(ValueError):
            SearchQuery(text="x", count=500)

    def test_it_reports_what_it_spent(self) -> None:
        """So a research run can state its cost rather than estimate it."""
        found = _search(lambda r: httpx.Response(200, json=BODY)).search("x")
        assert found.requests_made == 1
        assert found.approx_cost_usd > 0

    def test_it_never_returns_more_than_was_asked_for(self) -> None:
        found = _search(lambda r: httpx.Response(200, json=BODY)).search(
            SearchQuery(text="x", count=1)
        )
        assert len(found) == 1


class TestTheRateLimit:
    def test_it_paces_itself_to_the_free_tier(self) -> None:
        """One query per second is the free tier's actual limit, and a research
        loop fanning out across prospects hits it within a second of starting.
        Pacing belongs in the client, not in every caller's memory."""
        slept: list[float] = []
        search = _search(
            lambda r: httpx.Response(200, json=BODY), min_interval=1.05, sleep=slept.append
        )
        search.search("first")
        search.search("second")
        assert slept, "the second query went out without waiting"
        assert 0 < slept[0] <= 1.05

    def test_the_first_query_never_waits(self) -> None:
        slept: list[float] = []
        _search(
            lambda r: httpx.Response(200, json=BODY), min_interval=1.05, sleep=slept.append
        ).search("only")
        assert slept == []

    def test_a_slow_caller_pays_nothing_for_pacing(self) -> None:
        """Measured from the last request rather than slept unconditionally."""
        slept: list[float] = []
        search = _search(
            lambda r: httpx.Response(200, json=BODY), min_interval=0.001, sleep=slept.append
        )
        search.search("first")
        search.search("second")
        assert slept == [] or slept[0] < 0.001


class TestTheKey:
    def test_a_missing_key_says_exactly_where_to_get_one(self) -> None:
        with pytest.raises(NotConfigured) as raised:
            api_key()
        assert "QEVIK_BRAVE_API_KEY" in str(raised.value)

    def test_the_key_comes_from_the_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("QEVIK_BRAVE_API_KEY", "from-env")
        assert api_key() == "from-env"

    def test_a_blank_key_counts_as_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("QEVIK_BRAVE_API_KEY", "   ")
        with pytest.raises(NotConfigured):
            api_key()

    def test_the_key_travels_in_a_header_not_a_url(self) -> None:
        """A key in a query string lands in logs, proxies and referrers."""
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=BODY)

        _search(handler).search("x")
        assert seen[0].headers["X-Subscription-Token"] == "test-key"
        assert "test-key" not in str(seen[0].url)


class TestFailures:
    def test_a_rejected_key_is_not_reported_as_an_empty_web(self) -> None:
        with pytest.raises(SearchError, match="rejected the key"):
            _search(lambda r: httpx.Response(403, text="denied")).search("x")

    def test_an_error_never_echoes_the_request(self) -> None:
        """A provider's free-text error can echo the request, and the request
        carries the key."""
        search = _search(lambda r: httpx.Response(401, text="token test-key rejected"))
        with pytest.raises(SearchError) as raised:
            search.search("x")
        assert "test-key" not in str(raised.value)

    def test_rate_limiting_explains_the_free_tier(self) -> None:
        with pytest.raises(SearchError, match="one query per second"):
            _search(lambda r: httpx.Response(429)).search("x")

    def test_a_transport_failure_is_a_search_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route")

        with pytest.raises(SearchError, match="could not reach"):
            _search(handler).search("x")

    def test_a_non_json_body_does_not_crash_the_caller(self) -> None:
        with pytest.raises(SearchError, match="non-JSON"):
            _search(lambda r: httpx.Response(200, text="<html>")).search("x")

    def test_a_failed_request_still_counts_against_pacing(self) -> None:
        """Otherwise a burst of failures ignores the rate limit and turns one
        429 into a stream of them."""
        slept: list[float] = []
        search = _search(lambda r: httpx.Response(500), min_interval=1.05, sleep=slept.append)
        for _ in range(2):
            with pytest.raises(SearchError):
                search.search("x")
        assert slept, "a failed request did not update the pacing clock"


class TestItIsACapability:
    def test_the_capability_is_named_not_the_vendor(self) -> None:
        assert WEB_SEARCH == "web.search"

    def test_results_are_a_dumb_record_with_no_way_to_become_a_prompt(self) -> None:
        """Search results are untrusted text from strangers. The type carries no
        method that renders itself into an instruction, so the boundary between
        data and instruction is visible rather than remembered."""
        result = _search(lambda r: httpx.Response(200, json=BODY)).search("x").results[0]
        assert not [
            name
            for name in dir(result)
            if name.startswith(("as_prompt", "to_prompt", "render", "instruction"))
        ]


class TestMarketNarrowing:
    """Brave narrows to a fixed list of countries. **The UAE is not on it** —
    Saudi Arabia is, the Emirates are not — and Dubai is the target geography,
    so this is a constraint on the business rather than a detail."""

    def test_the_uae_is_not_a_supported_market(self) -> None:
        from atlas_kernel.research.brave import SUPPORTED_COUNTRIES

        assert "AE" not in SUPPORTED_COUNTRIES
        assert "SA" in SUPPORTED_COUNTRIES, "Saudi is supported; the asymmetry is the point"

    def test_an_unsupported_market_fails_before_spending_a_request(self) -> None:
        """It would be a 422 that costs a paid request to discover."""
        search = _search(lambda r: httpx.Response(200, json=BODY))
        with pytest.raises(SearchError, match="does not narrow results to AE"):
            search.search(SearchQuery(text="garages", country="AE"))
        assert search.requests_made == 0

    def test_it_says_to_put_the_geography_in_the_query_instead(self) -> None:
        with pytest.raises(SearchError, match="query text"):
            _search(lambda r: httpx.Response(200, json=BODY)).search(
                SearchQuery(text="garages", country="ae")
            )

    def test_an_unsupported_market_is_never_silently_dropped(self) -> None:
        """Returning global results to a caller who asked for one country gives
        them wrong-market data with no way to notice."""
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=BODY)

        with pytest.raises(SearchError):
            _search(handler).search(SearchQuery(text="garages", country="AE"))
        assert seen == []

    def test_a_supported_market_is_normalised_and_sent(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=BODY)

        _search(handler).search(SearchQuery(text="garages", country="sa"))
        assert "country=SA" in str(seen[0].url)


class TestValidationErrors:
    def test_a_422_names_the_parameter_brave_objected_to(self) -> None:
        """The prose body said "Unable to validate request parameter(s)" and
        nothing else; the useful part sat in a structured field. Discarding it
        is the same mistake the Gmail 403 made."""
        body = {
            "error": {
                "status": 422,
                "detail": "Unable to validate request parameter(s)",
                "meta": {"errors": [{"loc": ["query", "count"], "msg": "must be <= 20"}]},
            }
        }
        with pytest.raises(SearchError) as raised:
            _search(lambda r: httpx.Response(422, json=body)).search("x")
        assert "count" in str(raised.value)
        assert "must be <= 20" in str(raised.value)

    def test_a_422_without_structured_fields_still_reads_sensibly(self) -> None:
        with pytest.raises(SearchError, match="rejected the query parameters"):
            _search(lambda r: httpx.Response(422, text="nope")).search("x")
