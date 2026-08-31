#!/usr/bin/env python3
"""Withdraw absences a better reading contradicts. Fetches nothing.

Run on the control-plane host.

    reconcile_audits.py --dry-run     # what it would correct
    reconcile_audits.py               # append the corrections

The first production pass to write observations wrote seven, and two of them
carry claims a previous reading contradicts: Harman House Dubai Mall lost
`contact_form`, `booking_link`, `services_navigation`, `meta_description` and
`viewport_meta` in one night, and Marina Flowers lost `arabic`. A site does not
lose its `<head>` overnight — the earlier reading was a rendered browser and
this one a plain fetch, and a page assembled client-side is nearly empty to the
second. Both businesses have an **open** opportunity, so a health check built
today would have shown each of them five or six things they have.

`toolrunner._record_audit` now applies `website_audit.reconcile` before writing.
This is the same function over the readings already on the timeline, for the
rows written before it did.

## What it does not do

**It does not rewrite anything.** The original audit stays exactly where it is:
history is immutable, and a corrected record that replaced it would destroy the
evidence that the reading happened and what it said.

**It does not manufacture freshness.** The correction is appended now — that is
`BusinessEvent.at` — and carries the *original* `audited_at`, because the
reading it corrects happened then and no new reading has been made. Nothing here
touches anybody's website.

**It claims no new evidence.** A `not_found` becomes `unverified`, which is a
withdrawal. Nothing becomes `present`, and a business whose two readings agree
is left alone.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "kernel"))

from sqlalchemy import text  # noqa: E402

from atlas_kernel.db import SessionLocal  # noqa: E402
from atlas_kernel.opportunity.audit_import import audit_event  # noqa: E402
from atlas_kernel.opportunity.repository import OpportunityRepository  # noqa: E402
from atlas_kernel.opportunity.website_audit import Finding, reconcile  # noqa: E402

CORRECTED = "reconcile_audits.py"


def _detail(raw) -> dict:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except ValueError:
            return {}
    return dict(raw or {})


def _two_readings(session, business_id: str) -> tuple[dict, dict]:
    """The latest audit and the one before it, oldest of the pair second."""
    rows = session.execute(
        text("""
        SELECT detail, at FROM atlas_business_events
        WHERE kind = 'website_audited' AND business_id = :b
        ORDER BY at DESC LIMIT 2
        """), {"b": business_id}).mappings().all()
    if len(rows) < 2:
        return {}, {}
    return _detail(rows[0]["detail"]), _detail(rows[1]["detail"])


def main(dry_run: bool) -> int:
    repo = OpportunityRepository()
    corrected = examined = 0

    with SessionLocal() as session:
        # Only rows the new path wrote. Everything older was written by a
        # single reading with nothing before it to contradict, and a sweep over
        # the whole timeline would be re-deciding audits nobody has questioned.
        ids = [r["business_id"] for r in session.execute(
            text("""
            SELECT DISTINCT business_id FROM atlas_business_events
            WHERE kind = 'website_audited'
              AND coalesce(detail->>'read_by', '') <> ''
            """)).mappings()]

        for business_id in ids:
            latest, previous = _two_readings(session, business_id)
            if not latest or not previous:
                continue
            examined += 1
            observations = latest.get("observations") or []
            if not observations:
                continue
            # Already a correction? Then the rule has been applied and running
            # again would append a second identical record.
            if latest.get("corrects"):
                continue
            current = [Finding.model_validate(row) for row in observations]
            reconciled = reconcile(
                current, previous=previous.get("observations") or [],
                previous_read_by=str(previous.get("read_by") or ""),
                current_read_by=str(latest.get("read_by") or ""))
            withdrawn = [f.feature for f, was in zip(reconciled, current,
                                                     strict=True)
                         if f.status is not was.status]
            if not withdrawn:
                continue

            name = session.execute(
                text("SELECT name FROM atlas_businesses WHERE id = :i"),
                {"i": business_id}).scalar() or business_id
            print(f"   {str(name)[:34]:<36} withdraws {len(withdrawn)}: "
                  f"{', '.join(withdrawn)}")
            corrected += 1
            if dry_run:
                continue

            # The reading time is the reading's, not this run's. The correction
            # is appended now and says nothing new was looked at.
            audit = {
                "url": latest.get("url", ""),
                "http_status": latest.get("http_status"),
                "load_ms": latest.get("load_ms"),
                "page_bytes": latest.get("page_bytes"),
                "audited_at": latest.get("audited_at", ""),
                "findings": [f.model_dump(mode="json") for f in reconciled],
            }
            event = audit_event(business_id, audit,
                                read_by=str(latest.get("read_by") or ""))
            repo.record_event(event.model_copy(update={
                "actor": CORRECTED,
                "detail": {
                    **event.detail,
                    # So the timeline says what this row is. Without it a
                    # reader sees two audits of the same moment and cannot tell
                    # which is the reading and which is the withdrawal.
                    "corrects": {
                        "withdrew": withdrawn,
                        "because": ("the previous reading was made a different "
                                    "way and saw these, so this reading "
                                    "establishes nothing about them"),
                        "previous_read_by": str(previous.get("read_by") or
                                                "method not recorded"),
                    },
                }}))

    print(f"\n   examined {examined} business(es) with two readings, "
          f"{corrected} corrected{' (dry run)' if dry_run else ''}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    raise SystemExit(main(parser.parse_args().dry_run))
