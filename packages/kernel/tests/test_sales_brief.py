"""The rules that decide what a salesperson may and may not claim.

This is the highest-consequence logic in the commercial path and the cheapest to
get subtly wrong: every branch here ends in a sentence a human says out loud to
a prospect who knows their own website. A bug does not raise — it produces a
confident, wrong claim.

The three states must stay apart. `unverified` becoming a talking point is the
specific failure that turns "we audited your site" into "we guessed".
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "infra"))

from sales_brief import DEMO_PROVIDES, brief_for  # noqa: E402


def audit(**findings: str) -> dict:
    return {
        "clinic": "Test Dental",
        "url": "https://example.test/",
        "reachable": True,
        "http_status": 200,
        "load_ms": 100,
        "page_bytes": 1000,
        "is_https": True,
        "findings": [
            {"feature": feature, "status": status, "evidence": f"evidence for {feature}", "note": ""}
            for feature, status in findings.items()
        ],
    }


def test_a_verified_gap_the_demo_closes_becomes_a_talking_point() -> None:
    brief = brief_for(audit(click_to_call="not_found"), None)
    assert [p["feature"] for p in brief["talking_points"]] == ["click_to_call"]
    assert brief["talking_points"][0]["their_site"] == "NOT_FOUND"
    assert brief["talking_points"][0]["demo"] == "PRESENT"


def test_unverified_never_becomes_a_talking_point() -> None:
    """The whole point of keeping three states rather than two.

    `unverified` means the homepage did not show it. Inner pages were not read.
    Treating that as a gap is claiming knowledge the audit does not have.
    """
    brief = brief_for(audit(insurance_info="unverified", emergency_info="unverified"), None)
    assert brief["talking_points"] == []
    reasons = {d["reason"] for d in brief["do_not_say"]}
    assert reasons == {"NOT_VERIFIED"}


def test_a_feature_their_site_has_is_forbidden_not_ignored() -> None:
    """Silence would let someone claim it anyway. The list has to say so."""
    brief = brief_for(audit(whatsapp="present"), None)
    assert brief["talking_points"] == []
    forbidden = brief["do_not_say"][0]
    assert forbidden["reason"] == "THEIR_SITE_HAS_IT"
    assert "no whatsapp" in forbidden["claim"].lower()


def test_a_gap_the_demo_also_has_is_forbidden_as_a_promise() -> None:
    """Their site lacks doctor profiles. So does the demo — deliberately.

    This must not read as an opportunity. It is a promise that breaks the moment
    they scroll the page we just sent them.
    """
    brief = brief_for(audit(doctors_team="not_found"), None)
    assert brief["talking_points"] == []
    forbidden = brief["do_not_say"][0]
    assert forbidden["reason"] == "DEMO_DOES_NOT_HAVE_IT"
    assert forbidden["claim"].startswith("We will give you")


@pytest.mark.parametrize("feature", ["doctors_team", "insurance_info", "social_proof"])
def test_the_demo_never_claims_facts_it_cannot_know(feature: str) -> None:
    """Doctors, insurers and testimonials are never generated. Not negotiable."""
    assert DEMO_PROVIDES[feature] is False


def test_the_appointment_caveat_is_always_carried() -> None:
    """It renders and does not submit. Every brief must say so, every time."""
    brief = brief_for(audit(click_to_call="not_found"), None)
    assert any("does NOT submit" in c for c in brief["caveats"])


def test_unconfirmed_hours_are_called_out() -> None:
    brief = brief_for(audit(), {"hours_status": "NOT_VERIFIED"})
    assert any("hours were not confirmed" in c.lower() for c in brief["caveats"])

    confirmed = brief_for(audit(), {"hours_status": "CONFIRMED_PRESENT"})
    assert not any("hours were not confirmed" in c.lower() for c in confirmed["caveats"])


def test_page_weight_is_not_turned_into_a_claim() -> None:
    """"Their site has no page weight" is noise that buries the real lines."""
    brief = brief_for(audit(page_weight="present"), None)
    assert brief["do_not_say"] == []


def test_score_counts_only_verified_closeable_gaps() -> None:
    brief = brief_for(
        audit(
            click_to_call="not_found",   # weight 5, demo has it
            insurance_info="unverified",  # must not count
            doctors_team="not_found",     # demo lacks it, must not count
            whatsapp="present",           # theirs has it, must not count
        ),
        None,
    )
    assert brief["score"] == 5
