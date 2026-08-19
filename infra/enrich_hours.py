#!/usr/bin/env python3
"""Add opening hours to the stored prospect records, by place_id.

The clinics were discovered before the field mask asked for hours, so the
records on file have none. Re-running discovery would cost the same money and
risk returning a *different* twenty than the ones already generated, audited and
deployed — so this looks up each place individually, by the id already stored.

Three outcomes are recorded, and kept apart:

    CONFIRMED_PRESENT  Google returned hours. They are stored verbatim.
    CONFIRMED_ABSENT   Google was asked and holds no hours for this place.
    NOT_VERIFIED       The lookup failed, or there was no place_id to look up.

Collapsing the last two is the failure this script is written to avoid. A clinic
whose hours Google genuinely lacks and a clinic we could not reach look identical
in an empty field, and only one of them supports saying anything on a sales call.

    enrich_hours.py            # report what would be fetched, spend nothing
    enrich_hours.py --fetch    # perform the lookups
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "kernel"))

from atlas_kernel.opportunity.sources import (  # noqa: E402
    NotConfigured,
    PlacesError,
    opening_hours_for,
)

PROSPECTS = Path(os.environ.get("QEVIK_PROSPECTS", "/var/lib/qevik/prospects"))

#: Indicative. Place Details with a small mask is cheaper than a text search,
#: but the published rate is authoritative.
APPROX_USD_PER_LOOKUP = 0.005


def latest_records() -> Path:
    files = sorted(PROSPECTS.glob("prospects-*.json"))
    if not files:
        raise SystemExit(f"no prospect records under {PROSPECTS}")
    return files[-1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, default=None)
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args(argv)

    source = args.records or latest_records()
    records = json.loads(source.read_text(encoding="utf-8"))
    todo = [r for r in records if r.get("place_id")]

    print(f"records : {source}  ({len(records)} clinics)")
    print(f"with a place_id : {len(todo)}")
    if not args.fetch:
        print(f"\ndry run — {len(todo)} lookups would cost about "
              f"${len(todo) * APPROX_USD_PER_LOOKUP:.2f}. Re-run with --fetch.")
        return 0

    present = absent = unverified = 0

    for record in records:
        place_id = record.get("place_id")
        if not place_id:
            record["hours_status"] = "NOT_VERIFIED"
            record["opening_hours"] = []
            unverified += 1
            print(f"  {record['name'][:44]:<46} NOT_VERIFIED (no place_id)")
            continue

        try:
            hours = opening_hours_for(place_id)
        except NotConfigured:
            # A missing key is not a fact about any clinic. Stop rather than
            # write twenty NOT_VERIFIEDs that look like twenty findings.
            raise
        except PlacesError as failure:
            record["hours_status"] = "NOT_VERIFIED"
            record["opening_hours"] = []
            unverified += 1
            print(f"  {record['name'][:44]:<46} NOT_VERIFIED ({failure})")
            continue

        record["opening_hours"] = hours
        if hours:
            record["hours_status"] = "CONFIRMED_PRESENT"
            present += 1
            print(f"  {record['name'][:44]:<46} CONFIRMED_PRESENT ({len(hours)} days)")
        else:
            record["hours_status"] = "CONFIRMED_ABSENT"
            absent += 1
            print(f"  {record['name'][:44]:<46} CONFIRMED_ABSENT")

    source.write_text(json.dumps(records, indent=2), encoding="utf-8")
    print()
    print(f"CONFIRMED_PRESENT : {present}")
    print(f"CONFIRMED_ABSENT  : {absent}")
    print(f"NOT_VERIFIED      : {unverified}")
    print(f"spend             : about ${len(todo) * APPROX_USD_PER_LOOKUP:.2f}")
    print(f"written           : {source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
