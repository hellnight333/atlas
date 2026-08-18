#!/usr/bin/env python3
"""Audit the existing website of every stored prospect.

    audit_prospects.py [--limit 20]

One homepage per clinic, fetched with a real browser so that JavaScript-rendered
sites are read the way a patient sees them rather than as an empty shell. That
distinction matters here: several UAE clinic sites render their phone number and
booking button client-side, and a plain HTTP fetch would report both as missing
and produce a pitch built on a false claim.

The result is written next to the prospect record and kept. The research is the
asset — the demo is downstream of it, and re-running discovery later should be
able to compare against what was true today.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, "/opt/qevik/atlas/packages/kernel")

from atlas_kernel.browser import PlaywrightSession  # noqa: E402
from atlas_kernel.opportunity.website_audit import (  # noqa: E402
    SiteAudit,
    audit_html,
)

PROSPECTS = Path(os.environ.get("QEVIK_PROSPECTS", "/var/lib/qevik/prospects"))
AUDITS = Path(os.environ.get("QEVIK_AUDITS", "/var/lib/qevik/audits"))


def latest_prospects() -> list[dict]:
    files = sorted(PROSPECTS.glob("prospects-*.json"))
    if not files:
        raise SystemExit(f"no prospect records under {PROSPECTS}")
    return json.loads(files[-1].read_text(encoding="utf-8"))


def audit_one(session, prospect: dict) -> SiteAudit:
    url = (prospect.get("existing_website") or "").strip()
    clinic = prospect["name"]
    if not url:
        return SiteAudit(clinic=clinic, url="", error="no website on their listing")

    started = time.monotonic()
    try:
        page = session.open(url)
    except Exception as error:  # noqa: BLE001 - an unreachable site is a finding, not a crash
        return SiteAudit(clinic=clinic, url=url, error=f"{type(error).__name__}: {error}"[:200])

    elapsed = int((time.monotonic() - started) * 1000)
    try:
        html = session.extract("document.documentElement.outerHTML") or ""
    except Exception:  # noqa: BLE001
        html = ""

    if not html:
        return SiteAudit(
            clinic=clinic, url=url, reachable=bool(page.ok), http_status=page.status or 0,
            load_ms=elapsed, error="page loaded but returned no HTML to read",
        )

    return SiteAudit(
        clinic=clinic,
        url=url,
        reachable=bool(page.ok),
        http_status=page.status or 0,
        load_ms=elapsed,
        page_bytes=len(html),
        is_https=url.startswith("https://"),
        findings=audit_html(html, url=url, page_bytes=len(html)),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)

    prospects = latest_prospects()[: args.limit]
    AUDITS.mkdir(parents=True, exist_ok=True)
    audits: list[SiteAudit] = []

    # One browser for the run. Opening twenty would exhaust the box; the cap in
    # PlaywrightSession would refuse the twenty-first anyway.
    with PlaywrightSession(headless=True, viewport=(390, 900)) as session:
        for index, prospect in enumerate(prospects, 1):
            audit = audit_one(session, prospect)
            audits.append(audit)
            if audit.error:
                print(f"  [{index:>2}] {audit.clinic[:38]:<40} {audit.error[:50]}")
            else:
                print(
                    f"  [{index:>2}] {audit.clinic[:38]:<40} "
                    f"{audit.http_status} {audit.load_ms:>5}ms  "
                    f"{len(audit.strengths):>2} present / {len(audit.weaknesses):>2} missing / "
                    f"{len(audit.unverified):>2} unverified"
                )
            # A courtesy pause. These are real businesses' servers and nothing
            # here is urgent.
            time.sleep(1.5)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    out = AUDITS / f"audits-{stamp}.json"
    out.write_text(
        json.dumps([a.model_dump(mode="json") for a in audits], indent=2), encoding="utf-8"
    )

    reachable = [a for a in audits if a.reachable]
    print()
    print(f"audited   : {len(audits)}  ({len(reachable)} reachable)")
    print(f"records   : {out}")

    # Which confirmed absences are most common. This is the input to deciding
    # what the demo should compete on — chosen from the evidence rather than
    # from what is easiest to build.
    tally: dict[str, int] = {}
    for audit in reachable:
        for finding in audit.weaknesses:
            tally[finding.feature] = tally.get(finding.feature, 0) + 1
    print()
    print("most common CONFIRMED gaps across reachable sites:")
    for feature, count in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"  {count:>2}/{len(reachable)}  {feature}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
