"""Turning findings into an opportunity worth contacting someone about.

Scoring is a sum of severity weights, which is about as simple as it can be and
is on purpose: a more elaborate model would be tuned against a close rate nobody
has measured yet. When real reply data exists it can earn a better one.

The threshold does real work. Without it every business with a missing ``<h1>``
becomes a prospect, and an outreach engine that contacts people over cosmetic
defects is spam no matter how many approval gates sit in front of it. The floor
is enforced here and configured per niche.
"""

from __future__ import annotations

from .models import (
    Finding,
    NicheProfile,
    Opportunity,
    OpportunityStage,
    Prospect,
)


def score(findings: list[Finding]) -> float:
    return round(sum(finding.weight for finding in findings), 3)


def applicable_findings(findings: list[Finding], profile: NicheProfile) -> list[Finding]:
    """Drop findings this niche has declared it does not care about."""
    ignored = set(profile.ignore_kinds)
    return [finding for finding in findings if finding.kind not in ignored]


def qualify(
    prospect: Prospect,
    findings: list[Finding],
    profile: NicheProfile,
) -> Opportunity:
    """Build an opportunity and decide whether it clears the bar.

    A prospect below threshold is returned as ``DISQUALIFIED`` rather than
    discarded. Knowing how many candidates were looked at and rejected is the
    difference between a funnel and a list of wins, and the metrics depend on it.
    """
    relevant = applicable_findings(findings, profile)
    total = score(relevant)
    qualified = bool(relevant) and total >= profile.qualify_threshold

    return Opportunity(
        prospect_id=prospect.id,
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
    stable. An unstable ranking makes "the top 20 prospects" mean something
    different on every run, which quietly ruins any measurement built on it.
    """
    return sorted(
        opportunities,
        key=lambda item: (-item.score, -len(item.findings), item.id),
    )
