"""How strong this business already is — and the honesty to say "very".

The engine exists to find opportunities, which is exactly why this stage has to
be able to return STRONG. A system that only knows how to find fault will find
fault in a company with twenty years of trading, named blue-chip clients and a
full portfolio, and the message it writes will be wrong in a way the recipient
can see at a glance.

So position is graded from what the business demonstrably has, not from what it
lacks, and a strong grade is allowed to *suppress* opportunities downstream. The
question is never "how do we find something wrong". It is "what could be built
that would add to this".

Deliberately separate from `opportunity/market.py`, which grades niches for
market selection. Different question, different subject, no shared state.
"""

from __future__ import annotations

import re
from enum import StrEnum

from ..opportunity.website_audit import Category, Finding, Status
from .cms.base import CMSFacts

_TAG = re.compile(r"<[^>]+>")

#: Signals that a business is established. Each is something on their own site.
_CLIENT_LIST = re.compile(r"(our clients|trusted by|worked with|clients include|"
                          r"our partners|brands we)", re.I)
_LONGEVITY = re.compile(r"\b(\d{2})\+?\s*(?:years|yrs)\b", re.I)
_CREDENTIAL = re.compile(r"(iso\s?\d{4}|haccp|certified|accredited|award|licen[cs]ed)", re.I)
_TESTIMONIAL = re.compile(r"(testimonial|what our clients say|reviews?\b)", re.I)


class Grade(StrEnum):
    STRONG = "STRONG"
    ESTABLISHED = "ESTABLISHED"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    NOT_VERIFIED = "NOT_VERIFIED"


def assess(pages_html: list[str], *, cms: CMSFacts | None = None,
           official_channels: int = 0) -> tuple[dict, list[Finding]]:
    if not pages_html:
        return ({"grade": Grade.NOT_VERIFIED.value}, [Finding(
            feature="market_position", category=Category.TRUST, status=Status.UNVERIFIED,
            evidence="nothing was retrieved, so position was not assessed")])

    combined = "\n".join(pages_html)
    text = _TAG.sub(" ", combined)
    reasons: list[str] = []
    score = 0

    years = max((int(m.group(1)) for m in _LONGEVITY.finditer(text)), default=0)
    if years >= 10:
        score += 2
        reasons.append(f"claims {years}+ years trading")
    elif years:
        score += 1
        reasons.append(f"claims {years} years trading")

    if _CLIENT_LIST.search(text):
        score += 2
        reasons.append("publishes a client or partner list")
    if _TESTIMONIAL.search(text):
        score += 1
        reasons.append("publishes testimonials or reviews")
    if _CREDENTIAL.search(text):
        score += 1
        reasons.append("publishes certifications or awards")
    if official_channels >= 2:
        score += 1
        reasons.append(f"{official_channels} official social channels linked")

    portfolio = len(cms.image_pages) if cms and cms.detected else 0
    library = cms.media_total if cms and cms.media_total else 0
    if portfolio >= 10:
        score += 2
        reasons.append(f"{portfolio} portfolio entries carrying "
                       f"{sum(p.images for p in cms.image_pages)} photographs")
    elif portfolio >= 3:
        score += 1
        reasons.append(f"{portfolio} portfolio entries")
    if library >= 200:
        score += 1
        reasons.append(f"a {library}-item media library")

    grade = (Grade.STRONG if score >= 7 else Grade.ESTABLISHED if score >= 5
             else Grade.MODERATE if score >= 3 else Grade.WEAK)

    # The finding is PRESENT for anything from MODERATE up: being established is
    # a strength of theirs, and recording it as a status quo the audit "found
    # missing" would be exactly backwards.
    findings = [Finding(
        feature="market_position", category=Category.TRUST,
        status=Status.PRESENT if grade in (Grade.STRONG, Grade.ESTABLISHED, Grade.MODERATE)
        else Status.NOT_FOUND,
        evidence=f"{grade.value} — " + ("; ".join(reasons) if reasons
                                        else "nothing on the site establishes standing"))]
    if grade is Grade.STRONG:
        findings.append(Finding(
            feature="established_business", category=Category.TRUST, status=Status.PRESENT,
            evidence="a strong operator: lead with what could be added, never with "
                     "what is wrong"))
    return ({"grade": grade.value, "score": score, "reasons": reasons,
             "years_claimed": years, "portfolio_entries": portfolio,
             "media_library": library}, findings)


def suppresses_criticism(grade: str) -> bool:
    """Whether outreach must open with addition rather than defect."""
    return grade in (Grade.STRONG.value, Grade.ESTABLISHED.value)
