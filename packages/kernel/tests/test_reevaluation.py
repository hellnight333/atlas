"""Re-evaluation, tested on the pair a naive diff gets wrong.

Two of the six change kinds carry all the risk. A feature that was confirmed and
is now unverified looks identical to a decline unless you separate them — and
reporting a crawler timeout as "your site got worse" is the exact dishonesty the
whole evidence architecture exists to prevent. The mirror case, unverified then
confirmed, is our coverage improving and not their business changing, even when
the new reading is bad news.

Everything else here is about the baseline never moving. A delta is worthless if
the thing it is measured against can be rewritten.
"""

from __future__ import annotations

import pytest

from atlas_kernel.mission.reevaluation import (
    ABOUT_OUR_CHECKING,
    ABOUT_THE_BUSINESS,
    Change,
    candidates,
    classify,
    compare,
    read,
    to_event,
)
from atlas_kernel.opportunity.tenancy import TenantRequired

A, B = "tenant-alpha", "tenant-beta"


def _obs(**features) -> list[dict]:
    return [{"feature": name, "status": status} for name, status in features.items()]


# ============================================ the pair that gets it wrong

def test_losing_visibility_is_never_reported_as_a_decline() -> None:
    """The crawler timing out is not the customer's site getting worse."""
    result = compare(business_id="b", tenant=A,
                     previous=_obs(page_speed="present"),
                     current=_obs(page_speed="unverified"))

    change = result.changes[0]
    assert change.change is Change.NOW_UNVERIFIED
    assert not change.about_the_business
    assert change.change not in ABOUT_THE_BUSINESS
    assert change.change in ABOUT_OUR_CHECKING


def test_closing_a_blind_spot_is_not_a_change_to_their_business() -> None:
    """Even when the new reading is bad news, what changed is our checking."""
    result = compare(business_id="b", tenant=A,
                     previous=_obs(page_speed="unverified"),
                     current=_obs(page_speed="not_found"))

    change = result.changes[0]
    assert change.change is Change.NOW_CONFIRMED
    assert not change.about_the_business


def test_the_statement_never_merges_their_site_with_our_coverage() -> None:
    result = compare(
        business_id="b", tenant=A,
        previous=_obs(page_speed="present", h1="present", blog="unverified"),
        current=_obs(page_speed="not_found", h1="unverified", blog="present"))

    said = result.statement()
    assert "on the site itself" in said
    assert "about our coverage rather than the business" in said
    assert len(result.business_changes) == 1      # page_speed genuinely changed
    assert len(result.coverage_changes) == 2      # h1 lost, blog gained


# ============================================ the other four kinds

def test_an_unchanged_feature_is_unchanged() -> None:
    result = compare(business_id="b", tenant=A,
                     previous=_obs(https="present"), current=_obs(https="present"))
    assert result.changes[0].change is Change.UNCHANGED
    assert not result.anything_changed


def test_a_feature_confirmed_for_the_first_time_is_newly_observed() -> None:
    result = compare(business_id="b", tenant=A, previous=[],
                     current=_obs(website="present"))
    assert result.changes[0].change is Change.NEWLY_OBSERVED
    assert result.first_seen == ("website",)


def test_a_first_reading_that_establishes_nothing_is_not_a_finding() -> None:
    """A new feature nobody could check is not something newly observed."""
    result = compare(business_id="b", tenant=A, previous=[],
                     current=_obs(ai_visibility="unverified"))
    assert result.changes[0].change is Change.NOW_UNVERIFIED
    assert not result.changes[0].about_the_business


def test_a_genuine_reversal_is_a_contradiction() -> None:
    result = compare(business_id="b", tenant=A,
                     previous=_obs(arabic="not_found"), current=_obs(arabic="present"))
    change = result.changes[0]
    assert change.change is Change.CONTRADICTED
    assert change.about_the_business, "both readings were confirmed and disagree"


def test_a_feature_the_new_engine_no_longer_checks_is_a_coverage_change() -> None:
    """Our pipeline changed, not their site."""
    result = compare(business_id="b", tenant=A,
                     previous=_obs(legacy_feature="present"), current=[])
    assert result.changes[0].change is Change.NOW_UNVERIFIED
    assert result.no_longer_checked == ("legacy_feature",)


def test_an_unrecognised_status_is_treated_as_unverified() -> None:
    """A status we do not understand is not a finding we can rely on."""
    assert classify("present", "maybe") is Change.NOW_UNVERIFIED
    assert classify("nonsense", "present") is Change.NOW_CONFIRMED


# ============================================ the baseline never moves

def test_neither_input_is_modified() -> None:
    """A delta is worthless if the thing it measures against can be rewritten."""
    previous = _obs(https="present", h1="present")
    current = _obs(https="not_found")
    before = [dict(o) for o in previous]

    compare(business_id="b", tenant=A, previous=previous, current=current)
    assert previous == before


def test_the_comparison_is_appended_not_substituted() -> None:
    result = compare(business_id="b", tenant=A,
                     previous=_obs(https="present"), current=_obs(https="not_found"))
    event = to_event(result)
    assert event.kind == "business_reevaluated"
    # It carries the comparison, not a replacement set of observations.
    assert "changes" in event.detail
    assert "observations" not in event.detail


# ============================================ tenancy

def test_a_comparison_is_readable_only_by_its_own_tenant() -> None:
    result = compare(business_id="b", tenant=A,
                     previous=_obs(https="present"), current=_obs(https="present"))
    events = [to_event(result)]
    assert read(events, tenant=A)
    assert read(events, tenant=B) == []


def test_every_entry_point_requires_a_tenant() -> None:
    for call in (lambda: compare(business_id="b", tenant=None, previous=[], current=[]),
                 lambda: read([], tenant=None),
                 lambda: candidates([], tenant=None)):
        with pytest.raises(TenantRequired):
            call()


# ============================================ who is worth re-evaluating

def test_a_business_with_no_previous_research_is_a_candidate() -> None:
    found = candidates([{"business_id": "b1", "tenant_id": A, "name": "Bare Co",
                         "observations": []}], tenant=A)
    assert len(found) == 1
    assert "no previous research" in found[0].reason


def test_a_business_missing_newly_checkable_features_is_a_candidate() -> None:
    found = candidates(
        [{"business_id": "b1", "tenant_id": A,
          "observations": _obs(https="present")}],
        tenant=A, known_features=frozenset({"https", "website", "ai_visibility"}))
    assert len(found) == 1
    assert "2 feature(s)" in found[0].reason


def test_a_fully_checked_business_is_not_re_researched_for_nothing() -> None:
    """Running one anyway spends quota to produce UNCHANGED rows."""
    found = candidates(
        [{"business_id": "b1", "tenant_id": A,
          "observations": _obs(https="present", website="present")}],
        tenant=A, known_features=frozenset({"https", "website"}))
    assert found == ()


def test_another_tenants_business_is_never_a_candidate() -> None:
    found = candidates([{"business_id": "b1", "tenant_id": B, "observations": []}],
                       tenant=A)
    assert found == ()


def test_a_candidate_says_why_rather_than_just_naming_itself() -> None:
    found = candidates([{"business_id": "b1", "tenant_id": A, "name": "X",
                         "observations": []}], tenant=A)
    assert found[0].reason
    assert found[0].business_id == "b1"
