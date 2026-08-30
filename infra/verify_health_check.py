"""Build the digital product from a real audit and check it is usable.

Reads only. Run on the control-plane host.

The question this answers is not "does the code run" — the unit tests do that.
It is: **take a real business Qevik audited, produce the artefact, and confirm
the result is something that business could actually open and act on.**

Writes the page to /tmp so it can be looked at. Publishes nothing, sends
nothing, and records nothing on the timeline.
"""
from __future__ import annotations

import json

from sqlalchemy import text

from atlas_kernel.db import SessionLocal
from atlas_kernel.execution.capabilities.healthcheck import (
    NothingObserved,
    Unevidenced,
    build_health_check,
)

OUT = "/tmp/health_check_sample.html"


def _audits(limit: int = 40) -> list[dict]:
    with SessionLocal() as session:
        rows = session.execute(text(
            "SELECT business_id, detail FROM atlas_business_events "
            "WHERE kind='website_audited' ORDER BY at DESC LIMIT :limit"),
            {"limit": limit}).mappings().all()
    found = []
    for row in rows:
        detail = row["detail"]
        if isinstance(detail, str):
            detail = json.loads(detail)
        found.append({"business_id": row["business_id"], "research": detail or {}})
    return found


def _name(business_id: str) -> str:
    with SessionLocal() as session:
        return session.execute(text(
            "SELECT name FROM atlas_businesses WHERE id = :id"),
            {"id": business_id}).scalar() or ""


def main() -> int:
    audits = _audits()
    print("real audits read: %d" % len(audits))
    if not audits:
        print("no audits on this deployment; nothing to build from")
        return 0

    built = refused = 0
    first_page = ""
    first_name = ""
    for audit in audits:
        name = _name(audit["business_id"])
        if not name:
            continue
        try:
            files, provenance = build_health_check(
                business_name=name, research=audit["research"])
        except (NothingObserved, Unevidenced) as no:
            refused += 1
            print("   refused  %-34s %s" % (name[:34], str(no)[:44]))
            continue
        built += 1
        if not first_page:
            first_page, first_name = files["index.html"], name
            first = provenance

    print("\nbuilt %d, refused %d" % (built, refused))
    if not first_page:
        print("nothing could be built from real data")
        return 1

    print("\nfirst artefact: %s" % first_name)
    print("   checks           : %d" % first["checks"])
    print("   confirmed absent : %d" % first["confirmed_absent"])
    print("   confirmed present: %d" % first["confirmed_present"])
    print("   not verified     : %d" % first["not_verified"])
    print("   bytes            : %d" % len(first_page))

    # Is it usable? Three things a real reader depends on.
    unevidenced = [c for c in first["claims"]
                   if c["verdict"] != "NOT_VERIFIED" and not c["evidence"]]
    print("\n   every claim carries evidence : %s" % (not unevidenced))
    print("   self-contained (no CDN)      : %s" % (
        "<script src" not in first_page and "cdn." not in first_page))
    print("   names the business           : %s" % (first_name in first_page))

    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write(first_page)
    print("\nwritten to %s — nothing was published or sent" % OUT)

    return 1 if unevidenced else 0


if __name__ == "__main__":
    raise SystemExit(main())
