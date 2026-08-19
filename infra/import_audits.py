#!/usr/bin/env python3
"""Import the audited clinics into the businesses Atlas already keeps.

    import_audits.py [--dry-run]

Uses `resolve_business`, so re-running does not create twenty more companies —
identity resolution matches on strong keys and updates what it already has. That
matters more than it sounds: this will be re-run after every re-audit, and a
pipeline that duplicates its own customers on the second run is worse than one
that never ran.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "/opt/qevik/atlas/packages/kernel")

from atlas_kernel.opportunity.audit_import import (  # noqa: E402
    audit_event,
    business_from_prospect,
    commercial_score,
    demo_event,
    opportunity_from_audit,
    strongest_opportunity,
)
from atlas_kernel.opportunity.repository import OpportunityRepository  # noqa: E402

PROSPECTS = Path(os.environ.get("QEVIK_PROSPECTS", "/var/lib/qevik/prospects"))
AUDITS = Path(os.environ.get("QEVIK_AUDITS", "/var/lib/qevik/audits"))


def latest(directory: Path, prefix: str) -> list[dict]:
    files = sorted(directory.glob(f"{prefix}-*.json"))
    if not files:
        raise SystemExit(f"no {prefix} records under {directory}")
    return json.loads(files[-1].read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    prospects = {p["name"]: p for p in latest(PROSPECTS, "prospects")}
    audits = latest(AUDITS, "audits")
    repo = OpportunityRepository()

    imported = matched = 0
    for audit in audits:
        prospect = prospects.get(audit["clinic"])
        if prospect is None:
            print(f"  ! no prospect record for {audit['clinic']!r}")
            continue

        business = business_from_prospect(prospect)
        if args.dry_run:
            score, reasons = commercial_score(audit)
            print(f"  would import {business.name[:38]:<40} score={score:>4.0f}  {','.join(reasons[:3])}")
            continue

        resolved, created = repo.resolve_business(business)
        imported += created
        matched += not created

        opportunity = opportunity_from_audit(resolved.id, audit)
        for finding in opportunity.findings:
            repo.save_finding(finding)
        repo.save_opportunity(opportunity)
        repo.record_event(audit_event(resolved.id, audit, opportunity_id=opportunity.id))
        # The demo is the offer. A prospect history that records the audit but
        # not what was built from it cannot answer the first question asked when
        # one of them replies: what did we actually show them?
        if prospect.get("demo_url"):
            repo.record_event(demo_event(resolved.id, prospect, opportunity_id=opportunity.id))

        best = strongest_opportunity(audit)
        print(
            f"  {'new ' if created else 'seen'} {resolved.name[:36]:<38} "
            f"score={opportunity.score:>4.0f} findings={len(opportunity.findings):>2} "
            f"top={best['feature'] if best else '-'}"
        )

    if args.dry_run:
        return 0

    print()
    print(f"businesses : {imported} created, {matched} already known")
    print("stage      : qualified (the audit is the qualification)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
