#!/usr/bin/env python3
"""Audit the homepage of every discovered business, across all categories.

`audit_prospects.py` reads the dental prospect file and assumes that shape. This
reads a discovery run and carries the category through, so the output can answer
the question the discovery was for: **which industry is worth attacking first.**

Each homepage is loaded in a real browser, because several UAE small-business
sites render their phone number and enquiry button client-side and a plain fetch
would report both as missing — producing a pitch built on a false claim.

Findings keep three states and never collapse them. `unverified` means the
homepage did not show it; inner pages are not read, and absent from our sample is
not absent from their site.

Results are written to the business timeline, so the evidence outlives the file.

    audit_discovered.py --limit 40        # a slice, to sanity-check first
    audit_discovered.py                   # everything with a website
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "kernel"))

from atlas_kernel.browser import PlaywrightSession  # noqa: E402
from atlas_kernel.opportunity.models import BusinessEvent  # noqa: E402
from atlas_kernel.opportunity.repository import OpportunityRepository  # noqa: E402
from atlas_kernel.opportunity.website_audit import audit_html  # noqa: E402

PROSPECTS = Path(os.environ.get("QEVIK_PROSPECTS", "/var/lib/qevik/prospects"))
WEBSITE_FACTORY = "website"


def latest_discovery() -> Path:
    files = sorted(PROSPECTS.glob("discovery-*.json"))
    if not files:
        raise SystemExit(f"no discovery records under {PROSPECTS}")
    return files[-1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=25.0)
    args = parser.parse_args(argv)

    source = args.records or latest_discovery()
    rows = json.loads(source.read_text(encoding="utf-8"))

    # One row per business — a business found by two queries is still one site,
    # and fetching it twice costs time and tells us nothing new.
    by_business: dict[str, dict] = {}
    for row in rows:
        if row.get("website") and row["business_id"] not in by_business:
            by_business[row["business_id"]] = row
    targets = list(by_business.values())
    if args.limit:
        targets = targets[: args.limit]

    print(f"records : {source}")
    print(f"to audit: {len(targets)} businesses with a website")
    print()

    repo = OpportunityRepository()
    results: list[dict] = []
    reachable = 0

    session = PlaywrightSession(headless=True, viewport=(390, 844)).start()
    try:
        for index, row in enumerate(targets, 1):
            url = row["website"]
            started = time.monotonic()
            audit: dict = {
                "business_id": row["business_id"],
                "name": row["name"],
                "category": row["category"],
                "url": url,
                "phone": row.get("phone", ""),
                "address": row.get("address", ""),
                "audited_at": datetime.now(UTC).isoformat(),
            }
            try:
                page = session.open(url)
                # The same call audit_prospects.py uses. There is no
                # session.content(); reaching for one produced 3/3 unreachable
                # and an error that read like every site was down.
                html = session.extract("document.documentElement.outerHTML") or ""
                elapsed = int((time.monotonic() - started) * 1000)
                findings = audit_html(html, url=url, page_bytes=len(html))
                audit.update(
                    reachable=True,
                    http_status=page.status,
                    load_ms=elapsed,
                    page_bytes=len(html),
                    is_https=url.lower().startswith("https"),
                    findings=[f.model_dump() if hasattr(f, "model_dump") else dict(f)
                              for f in findings],
                    error="",
                )
                reachable += 1
            except Exception as failure:  # noqa: BLE001 - one dead site must not end the run
                audit.update(
                    reachable=False,
                    http_status=0,
                    load_ms=int((time.monotonic() - started) * 1000),
                    page_bytes=0,
                    is_https=url.lower().startswith("https"),
                    findings=[],
                    error=str(failure).split("\n")[0][:160],
                )

            results.append(audit)
            repo.record_event(
                BusinessEvent(
                    business_id=row["business_id"],
                    factory=WEBSITE_FACTORY,
                    kind="website_audited",
                    actor="audit_discovered.py",
                    detail={
                        "url": url,
                        "category": row["category"],
                        "reachable": audit["reachable"],
                        "http_status": audit["http_status"],
                        "load_ms": audit["load_ms"],
                        "page_bytes": audit["page_bytes"],
                        "is_https": audit["is_https"],
                        "error": audit["error"],
                        # Verbatim, all three states, so a later run can be
                        # diffed against this one.
                        "observations": audit["findings"],
                    },
                )
            )

            if index % 20 == 0 or index == len(targets):
                print(f"  {index:>3}/{len(targets)}  reachable {reachable}")
    finally:
        session.close()

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    out = PROSPECTS / f"multi-audits-{stamp}.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    print()
    print(f"audited   : {len(results)}")
    print(f"reachable : {reachable}")
    print(f"unreachable: {len(results) - reachable}")
    print(f"records   : {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
