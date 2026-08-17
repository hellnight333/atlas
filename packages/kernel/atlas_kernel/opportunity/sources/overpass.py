"""Real businesses, from OpenStreetMap.

The Opportunity Factory shipped with a seed list and a note saying that finding
names is cheap while producing evidenced findings is the hard part. That was
true, and it left the factory unable to answer the question the whole system
exists for: *find businesses in Dubai that do not have a proper website.*

This is the smallest honest discovery source. OpenStreetMap has millions of
businesses with names, phones, addresses and — crucially — a ``website`` tag.
Overpass queries it for free, with no API key, no account and no credential to
protect, which is why it comes before Google Places rather than after.

**What OSM's missing ``website`` tag is and is not.** It is a *lead*: a business
with no website tag is a business worth checking. It is **not** evidence that
they have no website — OSM is volunteer-maintained and its coverage of a tag
nobody is obliged to fill in is patchy. The spec is explicit about this:

    "Do not label a business 'no website' solely because one crawler failed.
    Use multiple signals where practical."

So this source produces *candidates*, and the existing website detector produces
the *evidence*. A business arriving here with no website tag is recorded as
exactly that — an absence in someone else's dataset, attributed to OSM — and the
detector's own fetch is what decides whether a site really exists.

Rate limits are real and the public endpoint is a shared, donated resource.
Queries are bounded by area and category, results are capped, and a single
request serves a whole niche rather than one per business.
"""

from __future__ import annotations

import httpx

from ..models import Business

#: Public Overpass endpoints. The first is the main instance; the second is a
#: mirror used when the first is busy, which it often is.
ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)

#: Overpass is a shared, donated service. A long timeout is politeness, not
#: patience: a query that gives up early and retries costs the endpoint more
#: than one that waits.
REQUEST_TIMEOUT_SECONDS = 180.0

#: Bounding boxes as (south, west, north, east). Deliberately data rather than
#: geocoding: one dependency fewer, and a box is auditable in a way a geocoder's
#: answer is not.
AREAS: dict[str, tuple[float, float, float, float]] = {
    "dubai": (24.79, 54.89, 25.36, 55.57),
    "abu-dhabi": (24.28, 54.28, 24.58, 54.297),
    "sharjah": (25.28, 55.36, 25.42, 55.55),
}

#: Candidate niches, as OSM tag filters. Each entry is a list of `key=value`
#: pairs; a business matching any of them qualifies.
#:
#: Chosen for job value and search behaviour rather than count: these are
#: services somebody looks up at the moment they need one, where a single job is
#: worth hundreds or thousands of dirhams. A business with no findable website
#: is losing those searches to whoever does have one.
NICHES: dict[str, list[str]] = {
    "car-repair": ["shop=car_repair", "shop=tyres", "shop=car_parts"],
    "dental": ["amenity=dentist", "healthcare=dentist"],
    "beauty": ["shop=beauty", "shop=hairdresser", "leisure=spa"],
    "trades": ["craft=carpenter", "craft=electrician", "craft=plumber", "craft=hvac"],
    "clinic": ["amenity=clinic", "amenity=doctors"],
    "veterinary": ["amenity=veterinary"],
}


class OverpassError(RuntimeError):
    """Overpass could not be queried.

    Distinct from "found nothing": an empty area and an unreachable endpoint
    look identical in a result list, and only one of them means the niche is
    exhausted.
    """


def build_query(area: str, niche: str, limit: int) -> str:
    """An Overpass QL query for one niche in one area.

    Only elements carrying a ``name`` are requested. An unnamed node cannot be
    written to, cannot be researched, and would arrive as an anonymous row that
    poisons the funnel counts.
    """
    try:
        south, west, north, east = AREAS[area]
    except KeyError:
        raise OverpassError(f"unknown area {area!r} (known: {', '.join(sorted(AREAS))})") from None
    try:
        filters = NICHES[niche]
    except KeyError:
        raise OverpassError(
            f"unknown niche {niche!r} (known: {', '.join(sorted(NICHES))})"
        ) from None

    bbox = f"{south},{west},{north},{east}"
    clauses = "".join(
        f'nwr[{tag.split("=")[0]}="{tag.split("=")[1]}"]["name"]({bbox});' for tag in filters
    )
    return f"[out:json][timeout:120];({clauses});out center {limit};"


def _business_from_element(element: dict, area: str) -> Business | None:
    tags = element.get("tags") or {}
    name = (tags.get("name") or "").strip()
    if not name:
        return None

    # Several tags carry a website. Checking only `website` would report
    # businesses as siteless when OSM recorded the URL under a different key,
    # which is the exact false positive this source must not produce.
    website = next(
        (tags[key] for key in ("website", "contact:website", "url", "website:en") if tags.get(key)),
        None,
    )
    phone = next(
        (tags[k] for k in ("phone", "contact:phone", "contact:mobile") if tags.get(k)), None
    )
    email = next((tags[k] for k in ("email", "contact:email") if tags.get(k)), None)

    address = ", ".join(
        part
        for part in (
            tags.get("addr:street"),
            tags.get("addr:district") or tags.get("addr:suburb"),
            tags.get("addr:city"),
        )
        if part
    )

    return Business(
        name=name,
        geography=tags.get("addr:city") or area.replace("-", " ").title(),
        website=website,
        phone=phone,
        email=email,
        sources=["openstreetmap"],
        metadata={
            "osm_id": f"{element.get('type')}/{element.get('id')}",
            "osm_tags": {
                k: v for k, v in tags.items() if k in {"shop", "amenity", "craft", "healthcare"}
            },
            "address": address,
            # Recorded explicitly rather than inferred later. "OSM has no
            # website tag for this business" is a fact about OSM; "this business
            # has no website" is a claim the detector has to earn.
            "website_absent_in_osm": website is None,
        },
    )


class OverpassSource:
    """Finds businesses in an area and niche. Produces candidates, not verdicts."""

    def __init__(
        self,
        *,
        area: str = "dubai",
        niche: str = "car-repair",
        client: httpx.Client | None = None,
    ) -> None:
        self.area = area
        self.niche = niche
        self._client = client
        self._owns_client = client is None

    @property
    def name(self) -> str:
        return f"osm:{self.area}:{self.niche}"

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=REQUEST_TIMEOUT_SECONDS,
                headers={"User-Agent": "Qevik/0.1 (business research; contact via qevik.com)"},
            )
        return self._client

    def close(self) -> None:
        if self._client is not None and self._owns_client:
            self._client.close()
            self._client = None

    def discover(self, profile, limit: int) -> list[Business]:
        query = build_query(self.area, self.niche, limit)
        last: Exception | None = None

        for endpoint in ENDPOINTS:
            try:
                response = self._get_client().post(endpoint, data={"data": query})
            except httpx.HTTPError as error:
                last = error
                continue
            if response.status_code == 429:
                # Rate limited. Trying the mirror immediately is the polite
                # response; hammering this one is not.
                last = OverpassError(f"{endpoint} rate-limited the query")
                continue
            if response.status_code >= 400:
                last = OverpassError(f"{endpoint} returned {response.status_code}")
                continue
            try:
                elements = response.json().get("elements", [])
            except ValueError as error:
                last = error
                continue

            found = [
                business
                for element in elements
                if (business := _business_from_element(element, self.area)) is not None
            ]
            return found[:limit]

        raise OverpassError(f"no Overpass endpoint answered: {last}")
