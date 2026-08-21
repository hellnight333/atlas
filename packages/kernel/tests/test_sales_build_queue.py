"""The build queue, the media gate, and the opportunities that justify both.

Three things must hold no matter what the interface does:

- ticking a product box requests nothing — a build starts on an explicit action;
- a queued job is not a product, and only READY may reach a customer;
- nothing here creates a second customer entity. Every write is a BusinessEvent
  against the same immutable business id.
"""

from __future__ import annotations

import pytest

from atlas_kernel.control import sales
from atlas_kernel.outreach import opportunity


def test_job_states_are_explicit_and_have_no_done() -> None:
    """The middle states name what is happening, not merely that something is.

    CANCELLED is terminal and deliberately retained: one real job is in it, and
    a vocabulary unable to express the state a record already holds forces
    either a rewrite of history or a job displayed as something it is not.
    """
    assert sales.JOB_STATES == ("QUEUED", "RESEARCHING", "DESIGNING", "BUILDING",
                                "MEDIA", "QA", "REVIEW", "READY", "FAILED", "CANCELLED")
    assert "DONE" not in sales.JOB_STATES, "'done' hides whether QA ran"
    assert sales.JOB_STATES.index("QA") < sales.JOB_STATES.index("READY")
    assert sales.TERMINAL_JOB_STATES == {"READY", "FAILED", "CANCELLED"}


def test_the_historical_cancelled_job_is_still_expressible() -> None:
    """A live record sits in CANCELLED. Dropping it would mean rewriting it."""
    assert "CANCELLED" in sales.JOB_STATES


def test_the_media_vocabulary_starts_at_no_permission() -> None:
    assert sales.MEDIA_PERMISSION[0] == "none"
    assert set(sales.MEDIA_PERMISSION) == {"none", "permission_pending", "use_originals",
                                           "edit_enhance", "generate_matching"}


def test_asked_and_unanswered_is_not_the_same_as_refused() -> None:
    """The state everything else collapses into wrongly."""
    assert "permission_pending" in sales.MEDIA_PERMISSION
    assert "permission_pending" not in sales.MEDIA_ALLOWS_ORIGINALS
    assert sales.MEDIA_ALLOWS_ORIGINALS == {"use_originals", "edit_enhance",
                                            "generate_matching"}
    assert "none" not in sales.MEDIA_ALLOWS_ORIGINALS


def test_a_product_list_offers_more_than_websites() -> None:
    """The whole point of the pass: the answer is not always a website."""
    kinds = " ".join(sales.PRODUCTS).lower()
    for shape in ("app", "portal", "dashboard", "configurator", "estimator", "game"):
        assert shape in kinds, shape


def test_every_opportunity_can_actually_be_requested() -> None:
    """The button sends an opportunity's product; the API validates against
    PRODUCTS. When those were two hand-written lists they disagreed at once and
    six of eight opportunities came back "unknown product"."""
    buildable = set(sales.PRODUCTS)
    for host_set in opportunity.RESEARCHED.values():
        for o in host_set:
            assert o.product in buildable, f"{o.name} -> {o.product!r} cannot be requested"
    for rule in opportunity.RULES:
        assert rule.product in buildable, f"{rule.name} -> {rule.product!r}"


def test_the_product_list_is_derived_not_typed() -> None:
    assert opportunity.PRODUCTS <= set(sales.PRODUCTS)
    assert set(sales.NATIVE) <= set(sales.PRODUCTS)


def test_opportunities_reaching_the_dashboard_all_carry_evidence() -> None:
    ranked = opportunity.for_host(
        "ahscatering.com", category="food",
        absent=frozenset({"arabic", "click_to_call"}),
        present=frozenset({"social_proof", "structured_data"}))
    assert ranked, "a business with confirmed gaps must produce opportunities"
    for o in ranked:
        assert o.evidence and all(e.strip() for e in o.evidence), o.key
        assert o.builds and o.user and o.value, o.key


def test_the_dashboard_never_pitches_an_unverified_feature() -> None:
    """NOT_VERIFIED is our blind spot, not their weakness."""
    nothing_confirmed = opportunity.derive(category="food", absent=frozenset(),
                                           present=frozenset())
    assert nothing_confirmed == ()


@pytest.mark.parametrize("bad", ["", "maybe", "yes", "ALL"])
def test_an_unknown_media_permission_is_refused(bad) -> None:
    assert bad not in sales.MEDIA_PERMISSION


def test_the_queue_writes_are_events_not_a_new_table() -> None:
    """One customer entity. A prospect table here would be the second."""
    source = (sales.__file__).replace(".pyc", ".py")
    text = open(source, encoding="utf-8").read()
    for write in ("media_permission_recorded", "product_build_requested"):
        assert f'kind="{write}"' in text, write
    assert "BusinessEvent(" in text
    for forbidden in ("class Prospect(", "CREATE TABLE", "prospects_table"):
        assert forbidden not in text, forbidden
