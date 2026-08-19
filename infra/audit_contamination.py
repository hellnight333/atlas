#!/usr/bin/env python3
"""Find test fixtures sitting in the production database. Reports; changes nothing.

The suite has no database isolation — it writes to whatever `ATLAS_DATABASE_URL`
points at, and on this server that is production. Every run has been leaving
rows behind.

Classification is deliberately conservative. A row is a fixture only if it
matches a signature no real business could produce; anything else is treated as
real, because the cost of the two mistakes is not symmetric. Wrongly quarantining
a genuine outreach record loses commercial history that cannot be reconstructed;
wrongly leaving a fixture in place costs an accurate count.

    audit_contamination.py            # report
    audit_contamination.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "kernel"))

from sqlalchemy import create_engine, text  # noqa: E402

#: Domains and addresses only a test would use. RFC 2606 reserves .test and
#: .example precisely so they can never resolve to a real business.
FIXTURE_RECIPIENTS = (
    "%@clinic.test",
    "%@example.com",
    "%@example.test",
    "%@test.test",
    "%@example.org",
)

#: Channels the product does not have. `recording` is a test double that records
#: what would have been sent; nothing in production writes it.
FIXTURE_CHANNELS = ("recording",)


def engine():
    url = os.environ.get("ATLAS_DATABASE_URL", "")
    if not url:
        raise SystemExit("ATLAS_DATABASE_URL is not set")
    return create_engine(url.replace("postgresql+psycopg://", "postgresql+psycopg://"))


def real_business_ids(conn) -> set[str]:
    """The businesses with a published demo — the twenty that matter."""
    rows = conn.execute(
        text(
            "SELECT DISTINCT business_id FROM atlas_business_events "
            "WHERE kind = 'website_demo_published'"
        )
    )
    return {row[0] for row in rows}


def report(conn) -> dict:
    real = real_business_ids(conn)

    recipient_clause = " OR ".join(f"recipient LIKE '{p}'" for p in FIXTURE_RECIPIENTS)
    channel_list = ", ".join(f"'{c}'" for c in FIXTURE_CHANNELS)

    fixtures = conn.execute(
        text(
            f"SELECT id, channel, recipient, status, business_id "
            f"FROM atlas_outreach_messages "
            f"WHERE channel IN ({channel_list}) OR ({recipient_clause})"
        )
    ).fetchall()

    # The safety check that decides whether this is safe to act on: does any
    # candidate belong to one of the twenty real businesses? If so, stop —
    # something is not what it appears and a human should look.
    overlapping = [row for row in fixtures if row.business_id in real]

    totals = conn.execute(
        text("SELECT channel, status, count(*) FROM atlas_outreach_messages GROUP BY 1, 2")
    ).fetchall()

    real_messages = conn.execute(
        text(
            "SELECT channel, status, count(*) FROM atlas_outreach_messages "
            "WHERE business_id = ANY(:ids) GROUP BY 1, 2"
        ),
        {"ids": list(real)},
    ).fetchall()

    orphan_events = conn.execute(
        text(
            "SELECT count(*) FROM atlas_business_events e "
            "WHERE NOT EXISTS (SELECT 1 FROM atlas_businesses b WHERE b.id = e.business_id)"
        )
    ).scalar()

    return {
        "real_businesses_with_demo": len(real),
        "fixture_candidates": len(fixtures),
        "fixture_overlapping_real_business": len(overlapping),
        "totals_by_channel_status": [list(r) for r in totals],
        "real_business_messages": [list(r) for r in real_messages],
        "orphan_events": orphan_events,
        "sample": [list(r)[:4] for r in fixtures[:5]],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    with engine().connect() as conn:
        data = report(conn)

    if args.json:
        print(json.dumps(data, indent=2, default=str))
        return 0

    print(f"real businesses with a published demo : {data['real_businesses_with_demo']}")
    print(f"fixture candidates in outreach        : {data['fixture_candidates']}")
    print(f"  ...belonging to a real business     : {data['fixture_overlapping_real_business']}")
    print(f"events with no business row           : {data['orphan_events']}")
    print()
    print("all outreach rows, by channel and status:")
    for channel, status, count in data["totals_by_channel_status"]:
        print(f"  {channel:<12} {status:<12} {count:>5}")
    print()
    print("outreach belonging to the real businesses:")
    for channel, status, count in data["real_business_messages"]:
        print(f"  {channel:<12} {status:<12} {count:>5}")
    print()
    if data["fixture_overlapping_real_business"]:
        print("STOP — a fixture candidate belongs to a real business. Do not quarantine.")
        return 1
    print("Safe to quarantine: no candidate touches a real business.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
