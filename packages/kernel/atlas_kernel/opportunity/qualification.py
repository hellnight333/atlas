"""Turning findings into an opportunity worth contacting someone about.

Scoring is a sum of severity weights **discounted by confidence**, which is
about as simple as it can be and is on purpose: a more elaborate model would be
tuned against a close rate nobody has measured yet. When real reply data exists
it can earn a better one.

Two floors do real work here, and both are configured per niche rather than
hardcoded.

**The qualification threshold.** Without it every business with a missing
``<h1>`` becomes a target, and an outreach engine that contacts people over
cosmetic defects is spam no matter how many approval gates sit in front of it.

**The confidence floor.** A weak signal should never reach a business owner
stated as a fact. Findings below the floor are dropped before scoring rather
than merely down-weighted, because enough weak signals would otherwise sum their
way past the threshold and arrive as confident assertions.
"""

from __future__ import annotations

from .models import (
    Business,
    Finding,
    NicheProfile,
    Opportunity,
    OpportunityStage,
)


def score(findings: list[Finding]) -> float:
    """Total confidence-weighted severity.

    ``Finding.weight`` is already severity times confidence, so a high-severity
    guess cannot outscore a moderate certainty.
    """
    return round(sum(finding.weight for finding in findings), 3)


def applicable_findings(findings: list[Finding], profile: NicheProfile) -> list[Finding]:
    """Drop what this niche does not care about, and what we are unsure of."""
    ignored = set(profile.ignore_kinds)
    return [
        finding
        for finding in findings
        if finding.kind not in ignored and finding.confidence >= profile.min_confidence
    ]


def qualify(
    business: Business,
    findings: list[Finding],
    profile: NicheProfile,
) -> Opportunity:
    """Build an opportunity and decide whether it clears the bar.

    A business below threshold is returned as ``DISQUALIFIED`` rather than
    discarded. Knowing how many candidates were looked at and rejected is the
    difference between a funnel and a list of wins, and the metrics depend on it.
    """
    relevant = applicable_findings(findings, profile)
    total = score(relevant)
    qualified = bool(relevant) and total >= profile.qualify_threshold

    return Opportunity(
        business_id=business.id,
        niche=profile.id,
        findings=relevant,
        score=total,
        estimated_value=profile.estimated_value,
        currency=profile.currency,
        stage=OpportunityStage.QUALIFIED if qualified else OpportunityStage.DISQUALIFIED,
    )


def rank(opportunities: list[Opportunity]) -> list[Opportunity]:
    """Best first.

    Ties break on the number of findings, then on id — so the order is total and
    stable. An unstable ranking makes "the top 20 businesses" mean something
    different on every run, which quietly ruins any measurement built on it.
    """
    return sorted(
        opportunities,
        key=lambda item: (-item.score, -len(item.findings), item.id),
    )
