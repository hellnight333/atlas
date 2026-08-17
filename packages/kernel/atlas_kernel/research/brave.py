"""Web search through Brave.

Chosen for the reason the execution plan gave: it is the cheapest credible
index with a plain HTTP API and no crawl of its own to maintain. It is an
adapter, not a dependency — `SearchProvider` is the interface and swapping to
Serper or Tavily is a registration, not a refactor.

Two things this module takes seriously.

**The free tier is one query per second, not a suggestion.** Exceeding it
returns 429, and a research loop that fans out across twenty prospects will hit
it within a second of starting. The pacing below is therefore part of the
client rather than something every caller is expected to remember.

**Spend is reported, never estimated.** Requests are counted as they are issued
so a research run can state its cost, the same contract the Places source
follows.
"""

from __future__ import annotations

import os
import time

import httpx

from ..media.publishers.google_oauth import _env
from .models import SearchQuery, SearchResult, SearchResults

SEARCH_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"

#: Brave's free tier permits one query per second. The paid tiers are faster,
#: but pacing to the slowest tier costs a research run a few seconds and saves
#: it from a 429 that looks like an outage.
MIN_SECONDS_BETWEEN_REQUESTS = 1.05

#: Brave narrows results to these markets and rejects anything else with a 422.
#: **The UAE is not on the list** — Saudi Arabia is, the Emirates are not — which
#: matters because Dubai is the target geography. For an unsupported market the
#: geography belongs in the query text ("garages in Dubai"), and this set exists
#: so that discovery happens here rather than as a paid request that fails.
SUPPORTED_COUNTRIES = frozenset(
    """AR AU AT BE BR CA CL DK FI FR DE GR HK IN ID IT JP KR MY MX NL NZ NO CN
    PL PT PH RU SA ZA ES SE CH TW TR GB US ALL""".split()
)

REQUEST_TIMEOUT_SECONDS = 20.0

#: Indicative only. The published rate is authoritative and changes without
#: asking us; this exists so a caller can reason about spend without reading a
#: pricing page.
APPROX_USD_PER_REQUEST = 0.005


class SearchError(RuntimeError):
    """The web could not be searched.

    Distinct from "found nothing", because an exhausted query and a rejected
    key look identical in an empty list and only one of them means the question
    has no answer.
    """


class NotConfigured(SearchError):
    """No API key. Its own type so the fix is obvious from the exception."""


def api_key() -> str:
    """The Brave key, from the environment.

    Never a constructor default and never a file in the repository: a key in
    the tree is one ``git add -A`` from being published, and this one bills a
    card.
    """
    key = _env("BRAVE_API_KEY") or os.environ.get("BRAVE_API_KEY")
    if not key or not key.strip():
        raise NotConfigured(
            "no Brave API key. Set QEVIK_BRAVE_API_KEY. Create one at "
            "https://api-dashboard.search.brave.com/ under Subscriptions."
        )
    return key.strip()


def _validation_reason(response: httpx.Response) -> str:
    """Why Brave called the request invalid, from its structured fields only.

    The free-text body is not used. A provider's prose error can echo the
    request, and while this request carries its key in a header rather than the
    query string, the habit is what keeps that true — the Gmail 403 that cost an
    afternoon said nothing useful in prose and said everything in a field the
    code was throwing away.
    """
    try:
        errors = ((response.json() or {}).get("error") or {}).get("meta", {}).get("errors", [])
    except ValueError:
        return ""
    parts: list[str] = []
    for error in errors or []:
        where = ".".join(str(p) for p in (error.get("loc") or []) if p != "query")
        message = str(error.get("msg") or "").strip()
        parts.append(f"{where}: {message}" if where and message else message or where)
    return " · ".join(p for p in dict.fromkeys(parts) if p)


def _result_from_web(item: dict) -> SearchResult | None:
    url = (item.get("url") or "").strip()
    if not url:
        return None
    return SearchResult(
        url=url,
        title=(item.get("title") or "").strip(),
        description=(item.get("description") or "").strip(),
        # Verbatim. Providers disagree about the format and a wrong parse is
        # worse than a string a human can read.
        age=(item.get("age") or item.get("page_age") or "").strip(),
    )


class BraveSearch:
    """Searches the web. Returns untrusted text, and says what it cost."""

    name = "brave"

    def __init__(
        self,
        *,
        key: str | None = None,
        client: httpx.Client | None = None,
        min_interval: float = MIN_SECONDS_BETWEEN_REQUESTS,
        sleep=time.sleep,
    ) -> None:
        self._key = key
        self._client = client
        self._owns_client = client is None
        self._min_interval = min_interval
        self._sleep = sleep
        self._last_request_at: float | None = None
        #: Requests actually issued, so a caller can report spend rather than
        #: estimate it.
        self.requests_made = 0

    @property
    def approx_cost_usd(self) -> float:
        return round(self.requests_made * APPROX_USD_PER_REQUEST, 4)

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS)
        return self._client

    def close(self) -> None:
        if self._client is not None and self._owns_client:
            self._client.close()
            self._client = None

    def _pace(self) -> None:
        """Wait out the free tier's one-per-second limit.

        Measured from the last request rather than slept unconditionally, so a
        caller that is already slow pays nothing for this.
        """
        if self._last_request_at is None or self._min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self._min_interval:
            self._sleep(self._min_interval - elapsed)

    def search(self, query: SearchQuery | str) -> SearchResults:
        if isinstance(query, str):
            query = SearchQuery(text=query)

        key = self._key or api_key()
        headers = {
            # In a header, never a query string: a key in a URL lands in logs,
            # proxies and referrer headers.
            "X-Subscription-Token": key,
            "Accept": "application/json",
        }
        params: dict[str, object] = {"q": query.text, "count": query.count}
        if query.country:
            # Checked before the request rather than after. An unsupported
            # market is a 422 that costs a paid request to discover, and
            # silently dropping it would return global results to a caller who
            # asked for one country and had no way to notice.
            if query.country.upper() not in SUPPORTED_COUNTRIES:
                raise SearchError(
                    f"Brave does not narrow results to {query.country.upper()}. "
                    "The UAE in particular is unsupported. Put the geography in the "
                    'query text instead — "garages in Dubai" — or use ALL.'
                )
            params["country"] = query.country.upper()
        if query.freshness:
            params["freshness"] = query.freshness

        self._pace()
        try:
            response = self._get_client().get(SEARCH_ENDPOINT, headers=headers, params=params)
        except httpx.HTTPError as error:
            raise SearchError(f"could not reach Brave: {error}") from error
        finally:
            self._last_request_at = time.monotonic()
        self.requests_made += 1

        if response.status_code in (401, 403):
            # Never the response body: a provider's free-text error can echo
            # the request, and the request carries the key.
            raise SearchError(
                f"Brave rejected the key ({response.status_code}). Check the key is valid "
                "and that the subscription is active."
            )
        if response.status_code == 429:
            raise SearchError(
                "Brave rate-limited the query (429). The free tier allows one query per "
                "second and a fixed monthly quota; check the plan before retrying."
            )
        if response.status_code == 422:
            reason = _validation_reason(response)
            raise SearchError(
                f"Brave rejected the query parameters{f' — {reason}' if reason else ''}."
            )
        if response.status_code >= 400:
            raise SearchError(f"Brave refused the query ({response.status_code}).")

        try:
            body = response.json()
        except ValueError as error:
            raise SearchError("Brave returned a non-JSON body") from error

        found: list[SearchResult] = []
        for item in (body.get("web") or {}).get("results", []) or []:
            result = _result_from_web(item)
            if result is not None:
                found.append(result)

        return SearchResults(
            query=query.text,
            results=found[: query.count],
            provider=self.name,
            requests_made=self.requests_made,
            approx_cost_usd=self.approx_cost_usd,
        )
