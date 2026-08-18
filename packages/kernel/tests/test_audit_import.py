"""Turning an audit into business intelligence, without inventing any.

The property under test is the one the sales pitch rests on: **only a confirmed
absence becomes a finding.** A feature that was present, or that the audit could
not see, must never become something we say to a business owner about their own
website.
"""

from __future__ import annotations

import pytest

from atlas_kernel.opportunity.audit_import import (
    COMMERCIAL_WEIGHT,
    FEATURE_TO_FINDING,
    audit_event,
    business_from_prospect,
    commercial_score,
    findings_from_audit,
    opportunity_from_audit,
    strongest_opportunity,
)
from atlas_kernel.opportunity.models import EvidenceKind, FindingKind, OpportunityStage

PROSPECT = {
    "name": "NOA Dental Clinic",
    "phone": "04 398 7075",
    "address": "Mankhool Road, Dubai",
    "area": "Mankhool",
    "existing_website": "https://noadental.example",
    "place_id": "ChIJ_noa",
    "sources": ["google-places"],
}


def _audit(**overrides) -> dict:
    base = {
        "clinic": "NOA Dental Clinic",
        "url": "https://noadental.example",
        "reachable": True,
        "http_status": 200,
        "load_ms": 1129,
        "findings": [
            {"feature": "click_to_call", "status": "present", "evidence": "href=tel:043987075"},
            {"feature": "whatsapp", "status": "not_found", "evidence": "no wa.me link"},
            {"feature": "booking_link", "status": "not_found", "evidence": "no booking link"},
            {"feature": "doctors_team", "status": "unverified", "evidence": "may be on a subpage"},
            {"feature": "insurance_info", "status": "unverified", "evidence": "not on homepage"},
        ],
    }
    base.update(overrides)
    return base


class TestOnlyConfirmedAbsenceBecomesAClaim:
    def test_a_confirmed_absence_becomes_a_finding(self) -> None:
        findings = findings_from_audit("biz_1", _audit())
        assert {f.kind for f in findings} == {
            FindingKind.NO_WHATSAPP,
            FindingKind.NO_BOOKING_PATH,
        }

    def test_a_present_feature_never_does(self) -> None:
        findings = findings_from_audit("biz_1", _audit())
        assert FindingKind.NO_CLICK_TO_CALL not in {f.kind for f in findings}

    def test_an_unverified_feature_never_does(self) -> None:
        """The whole safety property. A homepage visit cannot see a doctors page
        two clicks away, and telling a dentist their site lacks one it has ends
        the conversation."""
        findings = findings_from_audit("biz_1", _audit())
        statements = " ".join(f.statement for f in findings).lower()
        assert "doctor" not in statements
        assert "insurance" not in statements

    def test_every_finding_carries_checkable_evidence(self) -> None:
        """A claim without evidence is an opinion, and an opinion is not
        something to put in front of an owner about their own website."""
        for finding in findings_from_audit("biz_1", _audit()):
            assert finding.evidence
            assert finding.evidence[0].source == "https://noadental.example"
            assert finding.evidence[0].kind is EvidenceKind.HTML_CONTENT
            assert finding.evidence[0].observed["status"] == "not_found"

    def test_confidence_is_high_but_never_certain(self) -> None:
        """One page is not the whole site."""
        for finding in findings_from_audit("biz_1", _audit()):
            assert 0.5 < finding.confidence < 1.0

    def test_an_unmapped_feature_is_dropped_rather_than_guessed(self) -> None:
        audit = _audit(
            findings=[{"feature": "something_new", "status": "not_found", "evidence": "x"}]
        )
        assert findings_from_audit("biz_1", audit) == []


class TestSlowness:
    def test_a_slow_homepage_is_a_measured_finding(self) -> None:
        findings = findings_from_audit("biz_1", _audit(load_ms=7786))
        slow = [f for f in findings if f.kind is FindingKind.SLOW_RESPONSE]
        assert slow and slow[0].evidence[0].kind is EvidenceKind.TIMING
        assert "7786" in slow[0].statement

    def test_a_fast_homepage_is_not(self) -> None:
        findings = findings_from_audit("biz_1", _audit(load_ms=800))
        assert not [f for f in findings if f.kind is FindingKind.SLOW_RESPONSE]


class TestScoring:
    def test_the_score_comes_with_its_reasons(self) -> None:
        """A number nobody can explain is a number nobody should act on."""
        score, reasons = commercial_score(_audit())
        assert score == COMMERCIAL_WEIGHT["whatsapp"] + COMMERCIAL_WEIGHT["booking_link"]
        assert set(reasons) == {"whatsapp", "booking_link"}

    def test_unverified_features_do_not_raise_the_score(self) -> None:
        with_unverified = commercial_score(_audit())[0]
        without = commercial_score(
            _audit(findings=[f for f in _audit()["findings"] if f["status"] != "unverified"])
        )[0]
        assert with_unverified == without

    def test_a_clinic_with_nothing_missing_scores_zero(self) -> None:
        audit = _audit(findings=[{"feature": "whatsapp", "status": "present", "evidence": "ok"}])
        assert commercial_score(audit)[0] == 0
        assert strongest_opportunity(audit) is None

    def test_the_strongest_opportunity_is_one_thing_not_a_list(self) -> None:
        """A pitch opening with seven problems is a lecture."""
        best = strongest_opportunity(_audit())
        assert best["feature"] in ("whatsapp", "booking_link")
        assert best["weight"] == 9


class TestTheTimeline:
    def test_the_event_keeps_all_three_states(self) -> None:
        """Findings keep only absences; the event has to keep everything, so a
        later reader can tell 'never checked' from 'not there'."""
        event = audit_event("biz_1", _audit())
        assert event.detail["counts"] == {"present": 1, "not_found": 2, "unverified": 2}
        assert len(event.detail["observations"]) == 5

    def test_the_event_is_namespaced_to_this_factory(self) -> None:
        event = audit_event("biz_1", _audit())
        assert event.factory == "website"
        assert event.kind == "website_audited"
        assert event.business_id == "biz_1"

    def test_the_raw_observations_survive_for_later_comparison(self) -> None:
        """So 'did they fix it?' has an answer after a re-audit."""
        event = audit_event("biz_1", _audit())
        assert {o["feature"] for o in event.detail["observations"]} == {
            "click_to_call",
            "whatsapp",
            "booking_link",
            "doctors_team",
            "insurance_info",
        }


class TestTheBusinessRecord:
    def test_it_is_built_from_the_listing_and_nothing_else(self) -> None:
        business = business_from_prospect(PROSPECT)
        assert business.name == "NOA Dental Clinic"
        assert business.phone == "04 398 7075"
        assert business.geography == "Mankhool"
        assert business.metadata["place_id"] == "ChIJ_noa"

    def test_the_place_id_is_carried_so_branches_stay_distinct(self) -> None:
        from atlas_kernel.opportunity.identity import identity_keys

        assert "place:ChIJ_noa" in identity_keys(business_from_prospect(PROSPECT))

    def test_the_opportunity_starts_qualified_because_the_audit_qualified_it(self) -> None:
        opportunity = opportunity_from_audit("biz_1", _audit())
        assert opportunity.stage is OpportunityStage.QUALIFIED
        assert opportunity.niche == "dental"
        assert opportunity.currency == "AED"
        assert len(opportunity.findings) == 2


class TestTheMappingIsHonest:
    def test_every_mapped_feature_has_a_commercial_weight(self) -> None:
        missing = set(FEATURE_TO_FINDING) - set(COMMERCIAL_WEIGHT)
        assert not missing, f"scored as findings but unweighted: {missing}"

    @pytest.mark.parametrize("feature", ["whatsapp", "booking_link", "click_to_call"])
    def test_the_conversion_features_carry_the_most_weight(self, feature: str) -> None:
        assert COMMERCIAL_WEIGHT[feature] >= 9
