"""Does a real audited business now get a health check recommended? Reads only.

Run on the control-plane host. Reconstructs `Finding`s from stored
`website_audited` evidence and asks the detector what it would suggest — the
same function the verification pass calls, on the same data.

Writes no signal, creates no mission, publishes nothing.
"""
from __future__ import annotations

import collections
import json

from sqlalchemy import text

from atlas_kernel.db import SessionLocal
from atlas_kernel.opportunity import detect
from atlas_kernel.opportunity.models import Business, Evidence, Finding, Severity
from atlas_kernel.opportunity.website_audit import FEATURE_NOTES

#: Audited absences that are real findings, mapped to the kinds the detector
#: knows. Read from the audit's own vocabulary rather than invented here.
KIND_FOR = {
    "page_title": "missing_title",
    "meta_description": "missing_meta_description",
    "h1": "missing_h1",
    "viewport_meta": "not_mobile_friendly",
    "structured_data": "no_structured_data",
}


def _findings(business_id: str, detail: dict) -> list[Finding]:
    from atlas_kernel.opportunity.models import FindingKind

    response = Evidence(kind="http_response",
                        statement=f"the server answered {detail.get('http_status')}",
                        source="audit", detail={"url": detail.get("url", "")})
    found = []
    for observation in detail.get("observations") or []:
        if observation.get("status") != "not_found":
            continue
        kind = KIND_FOR.get(observation.get("feature", ""))
        if kind is None:
            continue
        found.append(Finding(
            business_id=business_id, kind=FindingKind(kind),
            severity=Severity.MEDIUM,
            statement=observation.get("note") or observation.get("feature", ""),
            confidence=0.9,
            evidence=[Evidence(kind="html_content", source="audit",
                               statement=observation.get("evidence", ""),
                               detail={})]))
    return found, response


def main() -> int:
    with SessionLocal() as session:
        rows = session.execute(text(
            "SELECT e.business_id, b.name, e.detail "
            "FROM atlas_business_events e JOIN atlas_businesses b "
            "ON b.id = e.business_id WHERE e.kind='website_audited' "
            "ORDER BY e.at DESC LIMIT 40")).mappings().all()

    print("real audits: %d" % len(rows))
    suggested = collections.Counter()
    shown = 0
    for row in rows:
        detail = row["detail"]
        if isinstance(detail, str):
            detail = json.loads(detail)
        findings, response = _findings(row["business_id"], detail or {})
        business = Business(id=row["business_id"], name=row["name"],
                            website=(detail or {}).get("url") or None)
        signal = detect.weak_web_presence(business, findings, response,
                                          source="verification")
        if signal is None:
            suggested["no opportunity raised"] += 1
            continue
        action = signal.actions[0]
        suggested[action.capability] += 1
        if action.capability == detect.HEALTH_CHECK_OFFER and shown < 2:
            shown += 1
            print("\n%s" % row["name"][:52])
            print("   suggests : %s" % action.capability)
            print("   outward  : %s | needs approval: %s"
                  % (action.reach.value, action.needs_approval))
            print("   says     : %s" % action.statement[:96])

    print("\nwhat the detector suggests across %d real audits:" % len(rows))
    for capability, count in suggested.most_common():
        print("   %-28s %d" % (capability, count))

    return 0 if suggested.get(detect.HEALTH_CHECK_OFFER) else 1


if __name__ == "__main__":
    raise SystemExit(main())
