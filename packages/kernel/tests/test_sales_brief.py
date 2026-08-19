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


def test_an_unreachable_site_is_the_finding_not_the_absence_of_one() -> None:
    """Their site timing out must not produce an empty brief.

    An audit with no findings and an audit of a site that would not load are
    opposite situations, and collapsing them reports the strongest available
    finding as nothing at all.
    """
    down = audit()
    down["reachable"] = False
    down["error"] = "BrowserError: Timeout 30000ms exceeded"

    brief = brief_for(down, None)
    assert brief["talking_points"], "a site that will not load is a finding"
    assert brief["talking_points"][0]["feature"] == "reachable"
    assert brief["score"] >= 20, "it should outrank any combination of feature gaps"

    # And it is still bounded by what one fetch can prove.
    assert any(d["reason"] == "NOT_VERIFIED" for d in brief["do_not_say"])


def test_whatsapp_is_promised_only_to_clinics_whose_number_can_receive_it() -> None:
    """The one capability that varies per prospect.

    The demo renders a WhatsApp button only for a UAE mobile, because wa.me on a
    landline is a dead link. A blanket False suppressed a genuine weight-5 point
    for the clinics that *do* have a mobile; a blanket True would promise a dead
    button to the sixteen that do not.
    """
    gap = audit(whatsapp="not_found")

    mobile = brief_for(gap, {"phone": "052 151 4300"})
    assert [p["feature"] for p in mobile["talking_points"]] == ["whatsapp"]
    assert mobile["score"] == 5

    landline = brief_for(gap, {"phone": "04 355 8808"})
    assert landline["talking_points"] == []
    assert landline["do_not_say"][0]["reason"] == "DEMO_DOES_NOT_HAVE_IT"

    # No record at all is treated as unable to receive, not as able.
    assert brief_for(gap, None)["talking_points"] == []
