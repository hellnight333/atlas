#!/usr/bin/env python3
"""Move test fixtures out of the production tables, without destroying them.

Quarantine rather than delete. These rows are almost certainly test junk, but
"almost certainly" is not a standard worth applying to commercial history that
cannot be reconstructed — so they are copied into `atlas_quarantined_fixtures`
with their whole original row, the table they came from and why they were
classified, then removed from the production table. Reversing it is a SELECT.

`atlas_quarantined_fixtures` is an operational archive, not a second customer
entity: it holds no business identity, is never joined to, and nothing reads it
except a human asking "what was moved and why".

Three refusals protect the real data:

- It re-runs the audit first and **stops** if any candidate belongs to one of the
  twenty audited businesses.
- It counts the real businesses' rows before and after, in the same transaction,
  and rolls back if the number moved.
- `--apply` is required. The default reports and changes nothing.

    quarantine_fixtures.py            # dry run
    quarantine_fixtures.py --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "kernel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_contamination import (  # noqa: E402
    FIXTURE_CHANNELS,
    FIXTURE_RECIPIENTS,
    engine,
    real_business_ids,
)
from sqlalchemy import text  # noqa: E402

SCHEMA = """
CREATE TABLE IF NOT EXISTS atlas_quarantined_fixtures (
    id            TEXT PRIMARY KEY,
    source_table  TEXT NOT NULL,
    reason        TEXT NOT NULL,
    row           JSONB NOT NULL,
    quarantined_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    recipient_clause = " OR ".join(f"recipient LIKE '{p}'" for p in FIXTURE_RECIPIENTS)
    channel_list = ", ".join(f"'{c}'" for c in FIXTURE_CHANNELS)
    where = f"channel IN ({channel_list}) OR ({recipient_clause})"

    with engine().begin() as conn:
        real = real_business_ids(conn)
        print(f"real businesses with a demo : {len(real)}")

        overlap = conn.execute(
            text(
                f"SELECT count(*) FROM atlas_outreach_messages "
                f"WHERE ({where}) AND business_id = ANY(:ids)"
            ),
            {"ids": list(real)},
        ).scalar()
        if overlap:
            print(f"STOP — {overlap} candidate(s) belong to a real business.", file=sys.stderr)
            return 1

        before = conn.execute(
            text(
                "SELECT count(*) FROM atlas_outreach_messages WHERE business_id = ANY(:ids)"
            ),
            {"ids": list(real)},
        ).scalar()

        messages = conn.execute(
            text(f"SELECT * FROM atlas_outreach_messages WHERE {where}")
        ).mappings().all()

        orphans = conn.execute(
            text(
                "SELECT * FROM atlas_business_events e WHERE NOT EXISTS "
                "(SELECT 1 FROM atlas_businesses b WHERE b.id = e.business_id)"
            )
        ).mappings().all()

        print(f"outreach fixtures           : {len(messages)}")
        print(f"events with no business row : {len(orphans)}")
        print(f"real-business outreach rows : {before}")

        if not args.apply:
            print("\ndry run — nothing changed. Re-run with --apply.")
            return 0

        conn.execute(text(SCHEMA))

        for row in messages:
            conn.execute(
                text(
                    "INSERT INTO atlas_quarantined_fixtures (id, source_table, reason, row)"
                    " VALUES (:id, 'atlas_outreach_messages', :reason, :row)"
                    " ON CONFLICT (id) DO NOTHING"
                ),
                {
                    "id": row["id"],
                    "reason": (
                        f"channel={row['channel']!r} recipient={row['recipient']!r} — "
                        "test fixture written by the suite against the production database"
                    ),
                    "row": json.dumps(dict(row), default=str),
                },
            )
        conn.execute(text(f"DELETE FROM atlas_outreach_messages WHERE {where}"))

        for row in orphans:
            conn.execute(
                text(
                    "INSERT INTO atlas_quarantined_fixtures (id, source_table, reason, row)"
                    " VALUES (:id, 'atlas_business_events', :reason, :row)"
                    " ON CONFLICT (id) DO NOTHING"
                ),
                {
                    "id": row["id"],
                    "reason": (
                        f"business_id={row['business_id']!r} has no row in atlas_businesses "
                        "— orphaned by a test that created events for a business it never saved"
                    ),
                    "row": json.dumps(dict(row), default=str),
                },
            )
        conn.execute(
            text(
                "DELETE FROM atlas_business_events e WHERE NOT EXISTS "
                "(SELECT 1 FROM atlas_businesses b WHERE b.id = e.business_id)"
            )
        )

        after = conn.execute(
            text(
                "SELECT count(*) FROM atlas_outreach_messages WHERE business_id = ANY(:ids)"
            ),
            {"ids": list(real)},
        ).scalar()

        # Same transaction, so a mismatch rolls the whole thing back rather than
        # leaving production half-cleaned.
        if after != before:
            raise SystemExit(
                f"ABORT — real-business outreach went {before} -> {after}. Rolled back."
            )

        print()
        print(f"quarantined  : {len(messages)} outreach + {len(orphans)} events")
        print(f"real-business outreach unchanged at {after}")
        print("archive      : atlas_quarantined_fixtures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
