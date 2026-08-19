#!/usr/bin/env python3
"""Multi-industry discovery across Dubai, into the businesses Atlas already keeps.

Twenty dental clinics told us the market is a replacement sale, not a
first-website sale. What they cannot tell us is whether dental was the right
category to attack at all — every clinic already had a site, and twelve of the
twenty differed only in lacking Arabic. This spreads the same measurement across
categories so the comparison is evidence rather than a guess.

Uses `resolve_business`, so a business found under two queries is one row with
two source records. Re-running does not duplicate anyone.

Spend is bounded and reported: each text search page costs roughly $0.035, and
`--max-pages` caps pages per query. The dry run tells you the ceiling before any
money is spent.

    discover_dubai.py                 # what it would query, and the cost ceiling
    discover_dubai.py --run
    discover_dubai.py --run --only food
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "kernel"))

from atlas_kernel.opportunity.models import BusinessEvent  # noqa: E402
from atlas_kernel.opportunity.repository import OpportunityRepository  # noqa: E402
from atlas_kernel.opportunity.sources import GooglePlacesSource  # noqa: E402
from atlas_kernel.opportunity.sources.google_places import (  # noqa: E402
    APPROX_USD_PER_REQUEST,
)

OUT = Path(os.environ.get("QEVIK_PROSPECTS", "/var/lib/qevik/prospects"))

#: Category -> the searches that find it. Phrased the way a Dubai resident would
#: search, because that is what Places matches against.
#:
#: Deliberately independent-leaning: "restaurant Dubai" returns hotel chains and
#: franchises whose website is decided in another country and who will never buy
#: from a one-person studio. The narrower phrasings return owner-operated places.
CATEGORIES: dict[str, tuple[str, ...]] = {
    "food": (
        "independent restaurant Dubai",
        "specialty coffee shop Dubai",
        "bakery Dubai",
        "cafeteria Dubai",
        "catering company Dubai",
    ),
    "beauty": (
        "beauty salon Dubai",
        "barber shop Dubai",
        "spa Dubai",
        "aesthetic clinic Dubai",
    ),
    "health": (
        "physiotherapy clinic Dubai",
        "dermatology clinic Dubai",
        "medical centre Dubai",
    ),
    "automotive": (
        "car detailing Dubai",
        "car garage repair Dubai",
        "tyre shop Dubai",
        "car rental Dubai",
    ),
    "home": (
        "cleaning company Dubai",
        "AC maintenance Dubai",
        "plumbing services Dubai",
        "pest control Dubai",
        "movers and packers Dubai",
    ),
    "professional": (
        "accounting firm Dubai",
        "law firm Dubai",
        "business consultancy Dubai",
        "architecture firm Dubai",
        "recruitment agency Dubai",
    ),
    "retail": (
        "furniture shop Dubai",
        "florist Dubai",
        "pet shop Dubai",
        "electronics shop Dubai",
    ),
}

WEBSITE_FACTORY = "website"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--only", default="", help="one category key")
    parser.add_argument("--per-query", type=int, default=12)
    parser.add_argument("--max-pages", type=int, default=1)
    args = parser.parse_args(argv)

    categories = (
        {args.only: CATEGORIES[args.only]} if args.only else CATEGORIES
    )
    queries = [(k, q) for k, qs in categories.items() for q in qs]
    ceiling = len(queries) * args.max_pages * APPROX_USD_PER_REQUEST

    print(f"categories : {len(categories)}")
    print(f"queries    : {len(queries)}")
    print(f"cost ceiling: ${ceiling:.2f} at ${APPROX_USD_PER_REQUEST}/page, "
          f"{args.max_pages} page(s) per query")
    print()

    if not args.run:
        for key, query in queries:
            print(f"  {key:<14} {query}")
        print("\ndry run — nothing queried. Re-run with --run.")
        return 0

    repo = OpportunityRepository()
    records: list[dict] = []
    spend = 0.0
    created = seen = 0

    for key, query in queries:
        source = GooglePlacesSource(query=query, area="dubai", max_pages=args.max_pages)
        try:
            found = source.discover(None, args.per_query)
        except Exception as failure:  # noqa: BLE001 - one bad query must not end the run
            print(f"  {key:<14} {query[:38]:<40} FAILED — {failure}")
            continue
        finally:
            spend += source.approx_cost_usd
            source.close()

        fresh = 0
        for business in found:
            # The category is ours, not Google's — it is how we group the market
            # for comparison, and it must travel with the business.
            business.metadata["qevik_category"] = key
            business.metadata["discovery_query"] = query
            business.metadata["discovered_at"] = datetime.now(UTC).isoformat()

            resolved, is_new = repo.resolve_business(business)
            created += is_new
            seen += not is_new
            fresh += is_new

            if is_new:
                repo.record_event(
                    BusinessEvent(
                        business_id=resolved.id,
                        factory=WEBSITE_FACTORY,
                        kind="business_discovered",
                        actor="discover_dubai.py",
                        detail={
                            "category": key,
                            "query": query,
                            "source": "google-places",
                            "website_on_listing": business.website or "",
                            "phone_on_listing": business.phone or "",
                            "place_id": business.metadata.get("place_id", ""),
                        },
                    )
                )

            records.append(
                {
                    "business_id": resolved.id,
                    "category": key,
                    "query": query,
                    "name": business.name,
                    "website": business.website or "",
                    "phone": business.phone or "",
                    "address": str(business.metadata.get("address", "")),
                    "place_id": business.metadata.get("place_id", ""),
                    "opening_hours": business.metadata.get("opening_hours", []),
                    "new": is_new,
                }
            )

        print(f"  {key:<14} {query[:38]:<40} {len(found):>3} found, {fresh:>3} new")

    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    path = OUT / f"discovery-{stamp}.json"
    path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")

    with_site = sum(1 for r in records if r["website"])
    print()
    print(f"discovered : {len(records)} results, {created} new businesses, {seen} already known")
    print(f"with a website on the listing : {with_site}")
    print(f"without one                   : {len(records) - with_site}")
    print(f"spend      : ${spend:.2f}")
    print(f"records    : {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
