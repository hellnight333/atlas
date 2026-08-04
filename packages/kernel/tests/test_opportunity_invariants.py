"""The two invariants the Opportunity Factory rests on (M014).

Atlas is about to tell a stranger that something is wrong with their business.
Two properties make that legitimate rather than presumptuous, and both are
enforced by construction rather than by review:

1. **A finding cannot exist without evidence.** If Atlas cannot say what it
   observed, where and when, it does not get to make the claim.
2. **A proposal cannot exist without findings.** Every claim cites one, so
   "never send generic templates" is a property of the type system instead of a
   hope about how well a prompt was written.

Each is tested from both directions: the guard rejects what it should, and — the
part that actually matters — it is not trivially satisfiable by an empty or
malformed value that would let a real violation slip past.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from atlas_kernel.opportunity.models import (
    Evidence,
    EvidenceKind,
    Finding,
    FindingKind,
    Opportunity,
    Proposal,
    ProposalClaim,
    Severity,
)


def _evidence(source: str = "https://example.test") -> Evidence:
    return Evidence(
        kind=EvidenceKind.HTML_CONTENT,
        source=source,
        observed={"title": None},
        summary="No <title> element.",
        detector="website",
    )


def _finding(**overrides) -> Finding:
    payload = {
        "prospect_id": "p1",
        "kind": FindingKind.MISSING_TITLE,
        "severity": Severity.HIGH,
        "statement": "The page has no title.",
        "evidence": [_evidence()],
    }
    payload.update(overrides)
    return Finding(**payload)


# ---------------------------------------------------------------------------
# Invariant 1 — no finding without evidence
# ---------------------------------------------------------------------------


class TestFindingRequiresEvidence:
    def test_a_finding_with_evidence_is_fine(self) -> None:
        finding = _finding()
        assert finding.evidence[0].source == "https://example.test"

    def test_empty_evidence_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="evidence"):
            _finding(evidence=[])

    def test_missing_evidence_field_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Finding(
                prospect_id="p1",
                kind=FindingKind.MISSING_TITLE,
                severity=Severity.HIGH,
                statement="The page has no title.",
            )

    def test_evidence_must_name_what_was_inspected(self) -> None:
        """An Evidence with a blank source would satisfy invariant 1 while
        proving nothing — the guard has to bite one level down too."""
        with pytest.raises(ValidationError, match="what was inspected"):
            Evidence(kind=EvidenceKind.HTML_CONTENT, source="   ")

    def test_a_finding_must_state_something(self) -> None:
        with pytest.raises(ValidationError, match="state what is wrong"):
            _finding(statement="  ")

    def test_findings_are_immutable_once_observed(self) -> None:
        """An observation that can be edited after the fact is not evidence of
        anything. The approval fingerprint depends on this holding."""
        finding = _finding()
        with pytest.raises(ValidationError):
            finding.statement = "something else"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Invariant 2 — no proposal without findings
# ---------------------------------------------------------------------------


class TestProposalRequiresFindings:
    def _proposal(self, **overrides) -> Proposal:
        payload = {
            "prospect_id": "p1",
            "opportunity_id": "o1",
            "subject": "Your site has no title",
            "body": "We looked at your site today.",
            "claims": [ProposalClaim(finding_id="f1", text="The page has no title.")],
        }
        payload.update(overrides)
        return Proposal(**payload)

    def test_a_cited_proposal_is_fine(self) -> None:
        assert self._proposal().claims[0].finding_id == "f1"

    def test_a_proposal_with_no_claims_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="generic templates are not permitted"):
            self._proposal(claims=[])

    def test_a_claim_must_say_something(self) -> None:
        with pytest.raises(ValidationError, match="must say something"):
            ProposalClaim(finding_id="f1", text="   ")

    def test_a_proposal_needs_a_subject_and_body(self) -> None:
        with pytest.raises(ValidationError, match="subject and a body"):
            self._proposal(body="   ")


# ---------------------------------------------------------------------------
# Fingerprints — what an approval actually binds to
# ---------------------------------------------------------------------------


class TestFingerprints:
    def test_editing_the_body_changes_the_proposal_fingerprint(self) -> None:
        original = Proposal(
            prospect_id="p1",
            opportunity_id="o1",
            subject="Subject",
            body="Original body",
            claims=[ProposalClaim(finding_id="f1", text="A claim.")],
        )
        edited = original.model_copy(update={"body": "Edited body"})
        assert original.fingerprint != edited.fingerprint

    def test_changing_the_facts_changes_the_findings_fingerprint(self) -> None:
        """A re-run detector that finds something different must invalidate an
        approval granted on the old facts."""
        first = Opportunity(prospect_id="p1", niche="n", findings=[_finding()])
        second = Opportunity(
            prospect_id="p1",
            niche="n",
            findings=[_finding(statement="The page has no heading.")],
        )
        assert first.findings_fingerprint != second.findings_fingerprint

    def test_finding_order_does_not_change_the_fingerprint(self) -> None:
        """Two detectors racing must not look like the facts changed."""
        a, b = _finding(), _finding(kind=FindingKind.MISSING_H1, statement="No h1.")
        assert (
            Opportunity(prospect_id="p1", niche="n", findings=[a, b]).findings_fingerprint
            == Opportunity(prospect_id="p1", niche="n", findings=[b, a]).findings_fingerprint
        )

    def test_absent_and_blank_are_different_facts(self) -> None:
        """ "No meta description" and "an empty meta description" are different
        observations, and a fingerprint that conflates them would hide a real
        change from the check that guards every send."""
        absent = Evidence(kind=EvidenceKind.HTML_CONTENT, source="s", observed={"desc": None})
        blank = Evidence(kind=EvidenceKind.HTML_CONTENT, source="s", observed={"desc": ""})
        assert absent.fingerprint != blank.fingerprint
