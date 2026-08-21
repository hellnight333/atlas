#!/usr/bin/env python3
"""Run the research engine over prospects and record what it found.

Read-only against every prospect's site: only GET, only public URLs, robots
obeyed, budget enforced. The only thing written anywhere is one append-only
`researched` event per business on Atlas's own timeline.

    research_prospects.py --limit 5              # five least-recently researched
    research_prospects.py --business <id>        # one, by id
    research_prospects.py --limit 3 --dry-run    # look, record nothing
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "kernel"))

from sqlalchemy import text  # noqa: E402

from atlas_kernel.db import SessionLocal  # noqa: E402
from atlas_kernel.opportunity.models import BusinessEvent  # noqa: E402
from atlas_kernel.opportunity.repository import OpportunityRepository  # noqa: E402
from atlas_kernel.research import pipeline  # noqa: E402
from atlas_kernel.research.net import Budget  # noqa: E402


def targets(limit: int, business_id: str) -> list[tuple[str, str, str]]:
    with SessionLocal() as session:
        if business_id:
            rows = session.execute(text(
                "SELECT id, name, website FROM atlas_businesses WHERE id = :i"),
                {"i": business_id})
        else:
            # Least recently researched first, and never one without a website.
            rows = session.execute(text("""
                SELECT b.id, b.name, b.website FROM atlas_businesses b
                LEFT JOIN (SELECT business_id, MAX(at) AS last
                           FROM atlas_business_events WHERE kind = 'researched'
                           GROUP BY business_id) r ON r.business_id = b.id
                WHERE COALESCE(b.website, '') <> ''
                ORDER BY r.last ASC NULLS FIRST, b.name
                LIMIT :n"""), {"n": limit})
        return [(r[0], r[1], r[2]) for r in rows]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--business", default="")
    parser.add_argument("--pages", type=int, default=25)
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    chosen = targets(args.limit, args.business)
    if not chosen:
        print("nothing to research")
        return 1
    repository = OpportunityRepository()
    for business_id, name, website in chosen:
        result = pipeline.research(
            business_id, website,
            budget=Budget(max_pages=args.pages, delay_seconds=args.delay))
        detail = pipeline.to_event_detail(result)
        print(f"{name[:38]:<40}{result.state.value:<9}"
              f"{len(result.observations()):>3} obs  "
              f"{len(result.ran)}/{len(result.stages)} stages"
              f"{'  [dry run]' if args.dry_run else ''}")
        if result.failed_stages:
            print(f"    failed: {', '.join(result.failed_stages)}")
        if not args.dry_run:
            repository.record_event(BusinessEvent(
                business_id=business_id, factory="research", kind="researched",
                actor="research_engine", detail=detail))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
