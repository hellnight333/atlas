#!/usr/bin/env python3
"""Find real clinics, build each a real site, and record the prospect.

    prospect_pipeline.py --count 20 [--deploy] [--query "dental clinic in Dubai"]

Deliberately not routed through the model planner. An open-ended objective needs
a plan; this is a known, repeatable process, and running twenty of them through
a language model would add cost, latency and variance to something whose shape
is already decided. The planner earns its place where the steps are unknown.

**Everything on a generated page comes from the clinic's own listing.** Name,
phone and address are facts read from Google Places; the services and
reassurance copy are category-typical and phrased as an offer. Nothing invents a
dentist, a credential, a testimonial or a year of establishment — those are the
first things a prospect checks on their own page, and one invented detail ends
the conversation and the sale with it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, "/opt/qevik/atlas/packages/kernel")

from atlas_kernel.opportunity.sources.google_places import GooglePlacesSource  # noqa: E402
from atlas_kernel.website.targets.public_host import PublicHostTarget  # noqa: E402
from atlas_kernel.website.verticals import dental  # noqa: E402

SITES_ROOT = os.environ.get("QEVIK_SITES_ROOT", "/srv/sites")
PUBLIC_BASE = os.environ.get("QEVIK_SITES_BASE_URL", "http://2.28.62.83")
PROSPECTS = Path(os.environ.get("QEVIK_PROSPECTS", "/var/lib/qevik/prospects"))

_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    return _SLUG.sub("-", value.lower()).strip("-")[:60] or "clinic"


#: Dubai districts a resident would recognise. Matched against, rather than
#: parsed out of, the address — because the first comma-separated fragment of a
#: real Places address is as likely to be "Unit 109" or a mall as a
#: neighbourhood, and "Gentle, modern dentistry in Al Hanaa Centre Mall" is the
#: sentence a prospect reads first about their own clinic.
DUBAI_AREAS = (
    "Al Barsha", "Al Quoz", "Al Karama", "Al Satwa", "Al Safa", "Al Wasl", "Al Nahda",
    "Al Qusais", "Al Mizhar", "Al Warqa", "Al Twar", "Al Rashidiya", "Al Furjan",
    "Business Bay", "Downtown Dubai", "Dubai Marina", "Jumeirah Lakes Towers", "JLT",
    "Jumeirah Village Circle", "JVC", "Jumeirah Beach Residence", "JBR",
    "Palm Jumeirah", "Jumeirah", "Deira", "Bur Dubai", "Mirdif", "Motor City",
    "Arabian Ranches", "Dubai Silicon Oasis", "Silicon Oasis", "Dubai Hills",
    "Dubai Sports City", "Discovery Gardens", "International City", "Dubai Investment Park",
    "Sheikh Zayed Road", "DIFC", "Deira City", "Umm Suqeim", "Oud Metha", "Garhoud",
    "Tecom", "Barsha Heights", "Dubai Healthcare City", "Mankhool", "Jaddaf",
)


def area_of(address: str, name: str = "") -> str:
    """The neighbourhood, for the headline.

    Recognised rather than parsed. "Dentistry in Al Barsha" reads like someone
    local wrote it; "in Al Hanaa Centre Mall" reads like a script did, and a
    prospect deciding whether this was made for them notices immediately.

    Falls back to "Dubai", which is always true. A vaguer headline is a far
    cheaper mistake than a confidently wrong one.
    """
    haystack = f"{address} {name}".lower()
    # Longest first, so "Dubai Hills" is not swallowed by "Dubai" and
    # "Jumeirah Village Circle" is not reduced to "Jumeirah".
    for area in sorted(DUBAI_AREAS, key=len, reverse=True):
        if area.lower() in haystack:
            return area
    return "Dubai"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--query", default="dental clinic in Dubai")
    parser.add_argument("--deploy", action="store_true", help="publish each site")
    parser.add_argument("--prefix", default="demo")
    args = parser.parse_args(argv)

    source = GooglePlacesSource(query=args.query, area="dubai")
    try:
        found = source.discover(None, args.count)
    finally:
        spend = source.approx_cost_usd
        source.close()

    print(f"discovered : {len(found)} businesses for {args.query!r}  (${spend:.3f})")

    target = PublicHostTarget(SITES_ROOT, base_url=PUBLIC_BASE) if args.deploy else None
    PROSPECTS.mkdir(parents=True, exist_ok=True)
    year = datetime.now(UTC).year
    records: list[dict] = []

    for business in found:
        address = str(business.metadata.get("address", ""))
        # Contactability is the constraint the market scan measured: a clinic
        # with no number is not a prospect, and a page whose only call to action
        # cannot be actioned is not a demo.
        if not business.phone:
            print(f"  skipped {business.name!r}: no phone on their listing")
            continue

        slug = f"{args.prefix}-{slugify(business.name)}"
        # A site, not a page: English and Arabic as separate URLs so both can be
        # indexed and linked with hreflang, plus robots.txt and a sitemap.
        files = dental.render_site(
            name=business.name,
            phone=business.phone,
            address=address,
            area=area_of(address, business.name),
            base_url=f"{PUBLIC_BASE}/{slug}",
            year=year,
        )

        record = {
            "name": business.name,
            "phone": business.phone,
            "address": address,
            "area": area_of(address, business.name),
            "existing_website": business.website,
            "has_website": bool(business.website),
            "place_id": business.metadata.get("place_id"),
            "slug": slug,
            "demo_url": "",
            "status": "generated",
            "generated_at": datetime.now(UTC).isoformat(),
            "sources": business.sources,
        }

        if target is not None:
            version = target.publish(slug, files)
            record["demo_url"] = target.promote(slug, version.id)
            record["status"] = "demo_live"
            record["version_id"] = version.id
            print(f"  {business.name[:42]:<44} -> {record['demo_url']}")
        else:
            print(f"  {business.name[:42]:<44} -> (not deployed)")

        records.append(record)

    if target is not None:
        target.close()

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    out = PROSPECTS / f"prospects-{stamp}.json"
    out.write_text(json.dumps(records, indent=2), encoding="utf-8")

    with_site = sum(1 for r in records if r["has_website"])
    print()
    print(f"prospects   : {len(records)}")
    print(f"  no website on their listing : {len(records) - with_site}")
    print(f"  already have one            : {with_site}")
    print(f"records     : {out}")
    print(f"places spend: ${spend:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
