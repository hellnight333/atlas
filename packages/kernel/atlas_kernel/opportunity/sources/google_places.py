"""Real businesses, with contact details, from Google Places.

The market scan measured the actual constraint: across every Dubai niche,
**2–17% of OpenStreetMap businesses were contactable**. Not defect rate —
reachability. A perfect prospect with no phone and no email is not a prospect,
and OSM is volunteer-maintained so its contact coverage is thin by nature.

Google Places knows the phone, the website and the address for essentially every
trading business. It is the difference between three workable prospects and
several hundred. It costs money, which is why it arrives second and why the
field mask below is not an afterthought.

**Cost control is a design constraint here, not an optimisation.** The Places
API bills per request *and per field tier*: asking for one expensive field
promotes the whole request to that tier. ``FIELD_MASK`` requests exactly what a
prospect record needs and nothing more — no reviews, no photos, no opening
hours, no geometry. Anyone adding a field to it is changing the bill, so the
list is short and commented.

Results are capped and pagination is bounded. An unbounded crawl of a dense city
is a large invoice arriving quietly, and the one thing worse than a scan that
finds too little is one that silently spends.
"""

from __future__ import annotations

import os

import httpx

from ...media.publishers.google_oauth import _env
from ..models import Business

SEARCH_ENDPOINT = "https://places.googleapis.com/v1/places:searchText"

#: Exactly what a prospect record needs. Every entry costs money, and adding one
#: can promote the request to a more expensive tier — so this list is short on
#: purpose and should stay that way.
#:
#: Deliberately absent: photos, reviews, ratings, opening hours, geometry,
#: editorial summaries. None of them change whether a business is worth
#: contacting about a broken website.
FIELD_MASK = ",".join(
    (
        "places.id",
        "places.displayName",
        "places.websiteUri",
        "places.nationalPhoneNumber",
        "places.formattedAddress",
        "nextPageToken",
    )
)

#: Google returns 20 per page. More pages means more requests means more money,
#: so this is a spend ceiling expressed as a number of pages.
MAX_PAGES = 3
REQUEST_TIMEOUT_SECONDS = 30.0

#: Roughly what a scan costs, so a caller can reason about spend without reading
#: Google's pricing page. Indicative only — the published rate is authoritative
#: and changes without asking us.
APPROX_USD_PER_REQUEST = 0.032


class PlacesError(RuntimeError):
    """Places could not be queried.

    Distinct from "found nothing", because an exhausted area and a rejected key
    look identical in an empty list and only one of them means the niche is
    finished.
    """


class NotConfigured(PlacesError):
    """No API key. Its own type so the fix is obvious from the exception."""


def api_key() -> str:
    """The Places key, from the environment.

    Never a constructor default and never a file in the repository, for the same
    reason the OAuth client secret is not: a key in the tree is one ``git add
    -A`` from being published, and this one bills a card.
    """
    key = _env("GOOGLE_PLACES_API_KEY") or os.environ.get("GOOGLE_PLACES_API_KEY")
    if not key or not key.strip():
        raise NotConfigured(
            "no Places API key. Set QEVIK_GOOGLE_PLACES_API_KEY. "
            "Create one in Google Cloud → APIs & Services → Credentials, with "
            "the Places API (New) enabled and the key restricted to it."
        )
    return key.strip()


def _business_from_place(place: dict, area: str) -> Business | None:
    name = ((place.get("displayName") or {}).get("text") or "").strip()
    if not name:
        return None

    website = (place.get("websiteUri") or "").strip() or None
    phone = (place.get("nationalPhoneNumber") or "").strip() or None
    address = (place.get("formattedAddress") or "").strip()

    return Business(
        name=name,
        geography=area.replace("-", " ").title(),
        website=website,
        phone=phone,
        # Places does not return email. Nothing is invented here; the outreach
        # path needs an address and this source honestly cannot supply one.
        email=None,
        sources=["google-places"],
        metadata={
            "place_id": place.get("id"),
            "address": address,
            # As with OSM: an absence in Google's data is a fact about Google's
            # data. The detector's own fetch is what earns the claim that a
            # business has no working website.
            "website_absent_in_places": website is None,
        },
    )


class GooglePlacesSource:
    """Finds businesses with contact details. Produces candidates, not verdicts."""

    def __init__(
        self,
        *,
        query: str,
        area: str = "dubai",
        key: str | None = None,
        client: httpx.Client | None = None,
        max_pages: int = MAX_PAGES,
    ) -> None:
        self.query = query
        self.area = area
        self._key = key
        self._client = client
        self._owns_client = client is None
        self.max_pages = max_pages
        #: Requests actually issued, so a caller can report spend rather than
        #: estimate it.
        self.requests_made = 0

    @property
    def name(self) -> str:
        return f"places:{self.area}:{self.query.replace(' ', '-')}"

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

    def discover(self, profile, limit: int) -> list[Business]:
        key = self._key or api_key()
        headers = {
            "X-Goog-Api-Key": key,
            "X-Goog-FieldMask": FIELD_MASK,
            "Content-Type": "application/json",
        }
        found: list[Business] = []
        token: str | None = None

        for _ in range(self.max_pages):
            if len(found) >= limit:
                break
            payload: dict[str, object] = {"textQuery": self.query, "maxResultCount": 20}
            if token:
                payload["pageToken"] = token

            try:
                response = self._get_client().post(SEARCH_ENDPOINT, headers=headers, json=payload)
            except httpx.HTTPError as error:
                raise PlacesError(f"could not reach Places: {error}") from error
            self.requests_made += 1

            if response.status_code in (401, 403):
                # Structured fields only — Google's free-text message can echo
                # the request, and the request carries the API key.
                raise PlacesError(
                    f"Places rejected the key ({response.status_code}). Check the key is "
                    "valid, that Places API (New) is enabled on the project, and that any "
                    "key restriction allows it."
                )
            if response.status_code == 429:
                raise PlacesError("Places rate-limited the query (429). Back off and retry.")
            if response.status_code >= 400:
                raise PlacesError(f"Places refused the query ({response.status_code}).")

            try:
                body = response.json()
            except ValueError as error:
                raise PlacesError("Places returned a non-JSON body") from error

            for place in body.get("places", []) or []:
                business = _business_from_place(place, self.area)
                if business is not None:
                    found.append(business)

            token = body.get("nextPageToken")
            if not token:
                break

        return found[:limit]
