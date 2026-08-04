"""Building a proposal out of what was actually found.

The rule this file exists to satisfy: **every proposal is generated from real
findings, never from a generic template.** `Proposal` refuses to be constructed
without citations, so the rule cannot be broken silently — but a model that
refuses bad input still needs a generator that produces good input, and that is
this.

The MVP generator is deterministic and needs no API key. That is not a
placeholder for "the real one with an LLM": composing sentences from findings
that were each independently substantiated is *more* defensible than asking a
model to write persuasive prose about a business it cannot see. An LLM-backed
generator can register alongside it later, under the same protocol and the same
citation requirement.

What a recipient sees is specific to them because it is assembled from what was
observed on their site — not because a template had their name substituted into
it.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import (
    Finding,
    FindingKind,
    NicheProfile,
    Opportunity,
    Proposal,
    ProposalClaim,
    Prospect,
    Severity,
)

#: What Atlas proposes doing about each class of defect. Data, so adding a
#: detector means adding a remedy here rather than editing prose in a branch.
REMEDIES: dict[FindingKind, str] = {
    FindingKind.NO_WEBSITE: "Build a small, fast site that shows what you do and how to reach you.",
    FindingKind.SITE_UNREACHABLE: "Get the site reliably online and keep it monitored.",
    FindingKind.NO_HTTPS: "Install a certificate so the browser warning disappears.",
    FindingKind.TLS_INVALID: "Replace the expired or mismatched certificate.",
    FindingKind.NOT_MOBILE_FRIENDLY: "Make the site readable on a phone without pinching or zooming.",
    FindingKind.SLOW_RESPONSE: "Cut the page weight so it opens quickly on mobile data.",
    FindingKind.MISSING_TITLE: "Give each page a title so search results show your business name.",
    FindingKind.MISSING_META_DESCRIPTION: "Write the summary that appears under your name in Google.",
    FindingKind.MISSING_H1: "Add a clear main heading to each page.",
    FindingKind.NO_STRUCTURED_DATA: "Publish your hours, address and contact details in the format search engines read.",
    FindingKind.THIN_CONTENT: "Add enough real content for search engines to understand the business.",
}

#: Worst first — a proposal opens with the thing that costs them the most.
_SEVERITY_ORDER: dict[Severity, int] = {Severity.HIGH: 0, Severity.MEDIUM: 1, Severity.LOW: 2}

#: More than this and a first email reads as a lecture rather than an
#: observation. The rest of the findings still exist and are still recorded;
#: they are simply not all fired at someone who has not replied yet.
MAX_CLAIMS_IN_FIRST_CONTACT = 3


@runtime_checkable
class ProposalGenerator(Protocol):
    """Produces a proposal from an opportunity.

    Any implementation must cite findings — enforced by ``Proposal`` itself, so
    a generator cannot opt out by being careless.
    """

    @property
    def name(self) -> str: ...

    def generate(
        self, prospect: Prospect, opportunity: Opportunity, profile: NicheProfile
    ) -> Proposal: ...


def _ordered(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: (_SEVERITY_ORDER[f.severity], f.kind.value))


class EvidenceProposalGenerator:
    """Composes a proposal from the findings themselves.

    Every sentence about the business traces to one observation. There is no
    paragraph in the output that would read the same for a different recipient,
    because there is no paragraph that was not built from their own findings.
    """

    @property
    def name(self) -> str:
        return "evidence-composer"

    def generate(
        self, prospect: Prospect, opportunity: Opportunity, profile: NicheProfile
    ) -> Proposal:
        if not opportunity.findings:
            # Reachable only by calling this directly on an unqualified
            # opportunity. Better a clear error here than a Pydantic failure
            # three frames down.
            raise ValueError(f"cannot write a proposal for {prospect.name}: no findings to cite")

        selected = _ordered(opportunity.findings)[:MAX_CLAIMS_IN_FIRST_CONTACT]
        claims = [
            ProposalClaim(
                finding_id=finding.id,
                text=finding.statement,
                remedy=REMEDIES.get(finding.kind, ""),
            )
            for finding in selected
        ]

        subject = self._subject(prospect, selected)
        body = self._body(prospect, selected, profile)

        return Proposal(
            prospect_id=prospect.id,
            opportunity_id=opportunity.id,
            subject=subject,
            body=body,
            claims=claims,
            offer=profile.offer,
            price=profile.estimated_value,
            currency=profile.currency,
            findings_fingerprint=opportunity.findings_fingerprint,
            generator=self.name,
        )

    def _subject(self, prospect: Prospect, findings: list[Finding]) -> str:
        headline = findings[0]
        if headline.kind is FindingKind.NO_WEBSITE:
            return f"{prospect.name} — you don't have a website listed"
        if headline.kind in {FindingKind.SITE_UNREACHABLE, FindingKind.TLS_INVALID}:
            return f"{prospect.name} — your website isn't loading for visitors"
        if headline.kind is FindingKind.NO_HTTPS:
            return f"{prospect.name} — your site shows a 'Not secure' warning"
        if headline.kind is FindingKind.NOT_MOBILE_FRIENDLY:
            return f"{prospect.name} — your site is hard to use on a phone"
        return f"{prospect.name} — {len(findings)} things costing you customers online"

    def _body(self, prospect: Prospect, findings: list[Finding], profile: NicheProfile) -> str:
        checked = findings[0].evidence[0].source
        lines = [
            f"Hello {prospect.name},",
            "",
            f"I looked at {checked} today and found a few specific things "
            "that are likely costing you customers:",
            "",
        ]

        for finding in findings:
            observed = finding.evidence[0]
            lines.append(f"• {finding.statement}")
            # The evidence line is the difference between an observation and a
            # sales claim. It is what makes the message answerable.
            lines.append(f"  (Checked {observed.observed_at:%d %b %Y}: {observed.summary})")
            remedy = REMEDIES.get(finding.kind)
            if remedy:
                lines.append(f"  What we'd do: {remedy}")
            lines.append("")

        lines.append(profile.offer)
        if profile.estimated_value is not None:
            lines.append(
                f"Typical cost for this is {profile.estimated_value:,.0f} {profile.currency}."
            )
        lines.extend(
            [
                "",
                "If any of the above is wrong, tell me and I'll correct it — "
                "everything here comes from a single check of your site, "
                "not an assumption about your business.",
                "",
                "Would a short call this week be useful?",
            ]
        )
        return "\n".join(lines)
