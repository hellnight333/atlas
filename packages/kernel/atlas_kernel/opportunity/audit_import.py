"""Turn a website audit into permanent business intelligence.

The audit was a JSON file next to a demo. That is fine for one run and useless
as a sales asset: nothing linked a weakness to a company, nothing survived a
re-audit, and nothing could answer "why did we contact them, and what did we
know at the time".

Everything here writes into structures that already exist — `Business`,
`Finding`, `Opportunity`, `BusinessEvent`. No prospect table, no parallel store.
`CLAUDE.md` forbids a second customer entity and a test enforces it, and the
rule is right: the clinic we audit today is the customer we invoice later, and
two records would drift the moment one of them mattered.

**The three states are kept apart on purpose.**

- `CONFIRMED_ABSENT` becomes a `Finding` — queryable, scoreable, and safe to say
  out loud because it carries the evidence that produced it.
- `CONFIRMED_PRESENT` and `NOT_VERIFIED` are recorded in the audit
  `BusinessEvent` and **never** become findings.

That asymmetry is the whole safety property. A finding is something we are
willing to tell a business owner about their own website; an unverified
observation is something we did not look hard enough to claim. Collapsing them
would produce a pitch that collapses the moment the owner opens their own menu.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .models import (
    Business,
    BusinessEvent,
    Evidence,
    EvidenceKind,
    Finding,
    FindingKind,
    Opportunity,
    OpportunityStage,
    Severity,
)

#: This factory's namespace in the shared timeline.
WEBSITE_FACTORY = "website"

#: Audit feature -> the finding it becomes when CONFIRMED ABSENT.
#: A feature missing from this map is deliberately not a finding: it is
#: recorded in the event and left out of scoring rather than guessed at.
FEATURE_TO_FINDING: dict[str, tuple[FindingKind, Severity]] = {
    "click_to_call": (FindingKind.NO_CLICK_TO_CALL, Severity.HIGH),
    "whatsapp": (FindingKind.NO_WHATSAPP, Severity.HIGH),
    "booking_link": (FindingKind.NO_BOOKING_PATH, Severity.HIGH),
    "https": (FindingKind.NO_HTTPS, Severity.HIGH),
    "viewport_meta": (FindingKind.NOT_MOBILE_FRIENDLY, Severity.HIGH),
    "opening_hours": (FindingKind.NO_OPENING_HOURS, Severity.MEDIUM),
    "google_maps": (FindingKind.NO_MAP_OR_DIRECTIONS, Severity.MEDIUM),
    "structured_data": (FindingKind.NO_STRUCTURED_DATA, Severity.MEDIUM),
    "contact_form": (FindingKind.NO_CONTACT_FORM, Severity.MEDIUM),
    "arabic": (FindingKind.NO_ARABIC, Severity.MEDIUM),
    "services_navigation": (FindingKind.NO_SERVICES_NAVIGATION, Severity.MEDIUM),
    "meta_description": (FindingKind.MISSING_META_DESCRIPTION, Severity.LOW),
    "page_title": (FindingKind.MISSING_TITLE, Severity.MEDIUM),
    "h1": (FindingKind.NO_H1, Severity.LOW),
    "image_alt_text": (FindingKind.POOR_IMAGE_ALT_TEXT, Severity.LOW),
    "page_weight": (FindingKind.SLOW_RESPONSE, Severity.MEDIUM),
}

#: What a confirmed absence is worth commercially, 0-10. Weighted by what it
#: costs a dental practice in enquiries, not by how hard it is for us to build —
#: otherwise the score measures our convenience and calls it their opportunity.
COMMERCIAL_WEIGHT: dict[str, int] = {
    "booking_link": 9,
    "whatsapp": 9,
    "click_to_call": 9,
    "https": 8,
    "viewport_meta": 8,
    "opening_hours": 7,
    "google_maps": 6,
    "structured_data": 6,
    "services_navigation": 6,
    "contact_form": 5,
    "arabic": 5,
    # The clickable line in a search result. It became a finding but carried no
    # weight, so a clinic with no <title> scored as if nothing were wrong — a
    # hole a test found rather than a customer.
    "page_title": 5,
    "meta_description": 4,
    "page_weight": 4,
    "h1": 3,
    "image_alt_text": 2,
}

#: Above this, a homepage is slow enough that a patient feels it.
SLOW_MS = 4000


def business_from_prospect(prospect: dict) -> Business:
    """The company, from its own listing. Nothing inferred."""
    address = str(prospect.get("address", ""))
    return Business(
        name=prospect["name"],
        geography=prospect.get("area") or "Dubai",
        website=prospect.get("existing_website") or None,
        phone=prospect.get("phone") or None,
        sources=prospect.get("sources") or ["google-places"],
        metadata={
            "address": address,
            "place_id": prospect.get("place_id"),
            "niche": "dental",
        },
    )


def _evidence(audit: dict, finding_row: dict) -> Evidence:
    """What was actually observed, and where to check it.

    Kept per finding rather than per audit so a single claim can be defended on
    its own. "Your homepage has no tel: link" is answerable; "our audit found
    problems" is not.
    """
    return Evidence(
        kind=EvidenceKind.HTML_CONTENT,
        source=audit.get("url", ""),
        observed={
            "feature": finding_row["feature"],
            "status": finding_row["status"],
            "detail": finding_row.get("evidence", ""),
            "http_status": audit.get("http_status"),
            "load_ms": audit.get("load_ms"),
        },
        summary=f"{finding_row['feature']}: {finding_row.get('evidence', '')}"[:280],
        detector="website_audit/homepage",
        observed_at=datetime.now(UTC),
    )


def findings_from_audit(business_id: str, audit: dict) -> list[Finding]:
    """Confirmed absences only.

    `not_found` becomes a finding; `present` and `unverified` never do. This is
    the function that keeps an unverified observation from turning into a sales
    claim, so it stays deliberately dull.
    """
    findings: list[Finding] = []
    for row in audit.get("findings", []):
        if row.get("status") != "not_found":
            continue
        mapped = FEATURE_TO_FINDING.get(row["feature"])
        if mapped is None:
            continue
        kind, severity = mapped
        findings.append(
            Finding(
                business_id=business_id,
                kind=kind,
                severity=severity,
                statement=f"{row['feature'].replace('_', ' ')} not present on the homepage",
                evidence=[_evidence(audit, row)],
                # Observed directly on their own page, so high — but not 1.0.
                # A homepage is one page, and certainty about a whole site from
                # one page is exactly the overreach this pipeline avoids.
                confidence=0.9,
            )
        )

    if audit.get("load_ms", 0) > SLOW_MS:
        findings.append(
            Finding(
                business_id=business_id,
                kind=FindingKind.SLOW_RESPONSE,
                severity=Severity.MEDIUM,
                statement=f"Homepage took {audit['load_ms']}ms to load",
                evidence=[
                    Evidence(
                        kind=EvidenceKind.TIMING,
                        source=audit.get("url", ""),
                        observed={"load_ms": audit["load_ms"]},
                        summary=f"measured {audit['load_ms']}ms to first render",
                        detector="website_audit/homepage",
                    )
                ],
                confidence=0.8,
            )
        )
    return findings


def commercial_score(audit: dict) -> tuple[float, list[str]]:
    """A score, and the reasons that produced it.

    Returned together on purpose. A number nobody can explain is a number nobody
    should act on, and the reasons are what the salesperson actually says.
    """
    reasons: list[str] = []
    total = 0.0
    for row in audit.get("findings", []):
        if row.get("status") != "not_found":
            continue
        weight = COMMERCIAL_WEIGHT.get(row["feature"])
        if weight is None:
            continue
        total += weight
        if weight >= 6:
            reasons.append(row["feature"])
    if audit.get("load_ms", 0) > SLOW_MS:
        total += 6
        reasons.append(f"slow homepage ({audit['load_ms']}ms)")
    return total, reasons


def audit_event(
    business_id: str, audit: dict, *, opportunity_id: str | None = None,
    read_by: str = "",
) -> BusinessEvent:
    """The whole audit, all three states, as permanent history.

    This is the record that answers "what did we know when we contacted them".
    It keeps `present` and `unverified` alongside `not_found`, which findings
    deliberately do not — so the timeline can show that a feature was never
    checked, rather than leaving a silence that later reads as absence.

    `read_by` says how the page was obtained, because that decides what an
    absence is worth. A browser renders a phone number a plain fetch never
    sees, so `not_found` from an unrendered read and `not_found` from a
    rendered one are not the same claim. Recorded rather than reasoned about
    here: the events that predate this field say nothing, and a default would
    assert something about them that nobody checked.
    """
    counts = {"present": 0, "not_found": 0, "unverified": 0}
    for row in audit.get("findings", []):
        counts[row.get("status", "unverified")] = counts.get(row.get("status", "unverified"), 0) + 1

    score, reasons = commercial_score(audit)
    return BusinessEvent(
        business_id=business_id,
        factory=WEBSITE_FACTORY,
        kind="website_audited",
        opportunity_id=opportunity_id,
        actor="website_audit/homepage",
        detail={
            "url": audit.get("url", ""),
            "http_status": audit.get("http_status"),
            "load_ms": audit.get("load_ms"),
            "page_bytes": audit.get("page_bytes"),
            "audited_at": str(audit.get("audited_at", "")),
            "read_by": read_by,
            "counts": counts,
            "commercial_score": score,
            "score_reasons": reasons,
            # Verbatim, so a later audit can be diffed against this one and the
            # question "did they fix it?" has an answer.
            "observations": audit.get("findings", []),
        },
    )


def demo_event(
    business_id: str, record: dict, *, opportunity_id: str | None = None
) -> BusinessEvent:
    """The demo built for this business, as permanent history.

    Without this the timeline shows that a clinic was audited and then, later,
    that someone contacted them — with no record of what they were shown. The
    demo *is* the offer; a prospect history that omits it cannot answer "what
    did we actually put in front of them", which is the first question asked
    when one of them replies.

    Records the hours provenance too, so a page missing its opening hours can
    be traced to CONFIRMED_ABSENT or NOT_VERIFIED rather than looking like a
    rendering fault.
    """
    return BusinessEvent(
        business_id=business_id,
        factory=WEBSITE_FACTORY,
        kind="website_demo_published",
        opportunity_id=opportunity_id,
        actor="website_factory/dental",
        detail={
            "demo_url": record.get("demo_url", ""),
            "slug": record.get("slug", ""),
            "version_id": record.get("version_id", ""),
            "languages": ["en", "ar"],
            "published_at": str(record.get("regenerated_at") or record.get("generated_at", "")),
            # Which facts the page was allowed to state.
            "hours_status": record.get("hours_status", "NOT_VERIFIED"),
            "hours_days": len(record.get("opening_hours") or []),
            "phone_on_file": record.get("phone", ""),
            "existing_website": record.get("existing_website", ""),
            # Stated rather than implied: the form is UI only.
            "appointment_backend": "NOT_IMPLEMENTED",
        },
    )


def opportunity_from_audit(business_id: str, audit: dict) -> Opportunity:
    """The commercial opportunity, staged by what we have actually done.

    Starts at QUALIFIED rather than DISCOVERED because the audit *is* the
    qualification — we have looked at their site and formed an evidence-backed
    view. It advances to PROPOSED only when a demo exists to propose.
    """
    score, _ = commercial_score(audit)
    return Opportunity(
        business_id=business_id,
        niche="dental",
        findings=findings_from_audit(business_id, audit),
        stage=OpportunityStage.QUALIFIED,
        score=score,
        currency="AED",
    )


def strongest_opportunity(audit: dict) -> dict[str, Any] | None:
    """The single most commercially defensible improvement for this business.

    One, not a list. A pitch that opens with seven problems sounds like a
    lecture; one that opens with the most expensive one sounds like someone who
    looked.
    """
    best: tuple[int, dict] | None = None
    for row in audit.get("findings", []):
        if row.get("status") != "not_found":
            continue
        weight = COMMERCIAL_WEIGHT.get(row["feature"], 0)
        if best is None or weight > best[0]:
            best = (weight, row)
    if best is None:
        return None
    return {
        "feature": best[1]["feature"],
        "weight": best[0],
        "evidence": best[1].get("evidence", ""),
    }
