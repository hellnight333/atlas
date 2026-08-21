"""The commercial score, checked where getting it wrong sends a false claim.

A score here is not an analytics number. It decides which sentence goes to a
real business owner, so the tests below are less about arithmetic than about the
four ways this could produce a message that is untrue:

- treating "we could not check" as "they do not have it",
- offering to fix something Qevik does not build,
- reading a failed audit as a clean bill of health,
- and ranking on evidence that has since been refuted.

Each of those actually happened during the first run against real data, which is
why each has a test.
"""

from __future__ import annotations

import pytest

from atlas_kernel.outreach import scoring


def audit(**overrides) -> dict:
    """A complete, healthy-looking audit that individual tests spoil."""
    base = {
        "http_status": 200,
        "load_ms": 1200,
        "category": "dental",
        "observations": [
            {"feature": "https", "status": "present"},
            {"feature": "arabic", "status": "not_found"},
            {"feature": "whatsapp", "status": "not_found"},
            {"feature": "booking_link", "status": "not_found"},
            {"feature": "insurance_info", "status": "unverified"},
        ],
    }
    base.update(overrides)
    return base


def score(**overrides) -> scoring.Score:
    kwargs = {
        "business_id": "b1", "name": "Test Clinic", "website": "https://example-clinic.ae/",
        "phone": "052 151 4300", "email": "", "category": "dental",
        "audit": audit(), "audit_count": 2, "demo_url": "", "sample_slug": "sample",
    }
    kwargs.update(overrides)
    return scoring.score(**kwargs)


# --- the three states must never collapse ----------------------------------

def test_an_unverified_finding_is_never_spoken_of_as_missing() -> None:
    result = score()
    assert "insurance_info" in result.unverified
    assert "insurance_info" not in result.speakable
    assert "insurance_info" not in result.unfixable


def test_unverified_findings_lower_confidence_rather_than_raising_weakness() -> None:
    """Not knowing is a reason to claim less, not a reason to claim more."""
    known = score(audit=audit(observations=[
        {"feature": "arabic", "status": "not_found"},
        {"feature": "whatsapp", "status": "present"},
    ]))
    unknown = score(audit=audit(observations=[
        {"feature": "arabic", "status": "not_found"},
        {"feature": "whatsapp", "status": "unverified"},
    ]))
    weak = {c.name: c.points for c in known.components}
    murky = {c.name: c.points for c in unknown.components}
    assert murky["weakness"] == weak["weakness"], "an unknown feature inflated their problem"
    assert murky["confidence"] < weak["confidence"]


# --- never offer what Qevik does not build ---------------------------------

def test_booking_is_never_offered_because_qevik_has_no_booking_backend() -> None:
    result = score()
    assert "booking_link" in result.unfixable
    assert "booking_link" not in result.speakable
    assert "booking_link" not in scoring.FIXABLE


def test_a_prospect_whose_only_gap_is_unfixable_scores_no_improvement() -> None:
    result = score(audit=audit(observations=[
        {"feature": "booking_link", "status": "not_found"},
        {"feature": "https", "status": "present"},
    ]))
    parts = {c.name: c.points for c in result.components}
    assert parts["improvement"] == 0
    assert parts["weakness"] > 0, "their problem is real even though we cannot solve it"
    assert result.speakable == ()


# --- a failed audit is not a clean site ------------------------------------

def test_an_audit_that_returned_nothing_is_not_a_passing_grade() -> None:
    """Kings' two recorded runs are zero-byte failures.

    The first version scored that identically to a flawless site and printed
    "the site passed every check we ran". Nothing had been checked.
    """
    empty = score(audit={"http_status": 0, "load_ms": 0, "observations": []})
    assert empty.audit_complete is False
    assert "AUDIT DID NOT COMPLETE" in dict(
        (c.name, c.reason) for c in empty.components)["weakness"]
    assert dict((c.name, c.points) for c in empty.components)["confidence"] == 0


def test_a_genuinely_clean_site_is_distinguishable_from_an_unreadable_one() -> None:
    clean = score(audit=audit(observations=[
        {"feature": "https", "status": "present"},
        {"feature": "arabic", "status": "present"},
    ]))
    unread = score(audit={"http_status": 0, "observations": []})
    assert clean.audit_complete is True and unread.audit_complete is False
    assert clean.total > unread.total


# --- re-verification must be able to overrule the stored audit -------------

def test_a_refuted_finding_stops_being_a_weakness() -> None:
    """Three of Malabar's five stored weaknesses were refuted on re-check."""
    stale = score()
    assert "whatsapp" in stale.speakable

    fresh = score(audit=scoring.apply_verification(
        audit(), {"whatsapp": "REFUTED", "arabic": "CONFIRMED"}))
    assert "whatsapp" not in fresh.speakable, "we would have claimed a gap they had closed"
    assert "arabic" in fresh.speakable
    assert fresh.total < stale.total


def test_an_inconclusive_recheck_downgrades_to_not_verified() -> None:
    fresh = score(audit=scoring.apply_verification(audit(), {"arabic": "NOT_VERIFIED"}))
    assert "arabic" in fresh.unverified
    assert "arabic" not in fresh.speakable


def test_verification_is_what_earns_the_confidence_points() -> None:
    """Stale evidence is optimistic evidence, and must not outrank checked evidence."""
    unchecked = score()
    checked = score(audit=scoring.apply_verification(audit(), {"arabic": "CONFIRMED"}))
    assert checked.verified is True and unchecked.verified is False
    parts = lambda s: {c.name: c.points for c in s.components}
    assert parts(checked)["confidence"] > parts(unchecked)["confidence"]


def test_verification_can_revive_a_site_the_audit_could_not_read() -> None:
    revived = scoring.apply_verification(
        {"http_status": 0, "observations": [], "live_http_status": 200, "live_load_ms": 15805},
        {"site_loads": "REFUTED", "slow_homepage": "CONFIRMED"},
    )
    assert scoring.audit_completed(revived)
    assert revived["load_ms"] == 15805


# --- reachability ----------------------------------------------------------

@pytest.mark.parametrize(
    "phone,expected_kind,at_least",
    [
        ("052 151 4300", "mobile", 20),
        ("04 347 4339", "landline", 8),
        ("800 37569", "toll_free", 0),
        ("", "none", 0),
    ],
)
def test_reachability_reflects_who_actually_answers(phone, expected_kind, at_least) -> None:
    result = score(phone=phone)
    assert result.contact_kind == expected_kind
    points = {c.name: c.points for c in result.components}["reachability"]
    assert points >= at_least


def test_a_switchboard_scores_below_a_landline_which_scores_below_a_mobile() -> None:
    """A toll-free line reaches somebody who cannot buy a website."""
    points = lambda phone: {c.name: c.points for c in score(phone=phone).components}["reachability"]
    assert points("800 37569") < points("04 347 4339") < points("052 151 4300")


# --- the score has to be defensible ----------------------------------------

def test_the_total_is_exactly_the_sum_of_its_parts() -> None:
    result = score()
    assert result.total == sum(c.points for c in result.components)
    assert result.total <= 100


def test_every_component_stays_within_its_declared_maximum() -> None:
    for phone in ("052 151 4300", "800 37569", ""):
        for observations in ([], audit()["observations"]):
            result = score(phone=phone, audit=audit(observations=observations))
            for component in result.components:
                assert 0 <= component.points <= component.out_of
                assert component.out_of == scoring.MAX[component.name]


def test_every_component_carries_the_reasoning_behind_it() -> None:
    """A score nobody can argue with is a score nobody should trust."""
    for component in score().components:
        assert component.reason.strip(), f"{component.name} scored with no stated reason"


def test_the_stored_event_keeps_the_three_states_apart() -> None:
    detail = score().as_event_detail()
    assert detail["speakable_weaknesses"] == ["arabic", "whatsapp"]
    assert detail["unfixable_weaknesses"] == ["booking_link"]
    assert detail["not_verified"] == ["insurance_info"]
    assert detail["scorer_version"] == scoring.VERSION


def test_a_personalised_demo_outranks_a_generic_sample() -> None:
    generic = {c.name: c.points for c in score(sample_slug="sample").components}["relevance"]
    theirs = {c.name: c.points for c in
              score(demo_url="https://sites.qevik.ai/demo-x/").components}["relevance"]
    nothing = {c.name: c.points for c in
               score(sample_slug="", demo_url="").components}["relevance"]
    assert nothing < generic < theirs
