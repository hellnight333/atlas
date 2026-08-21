"""Opportunities must come from evidence, and only from evidence we trust.

The failure this guards against is the one that makes outreach worthless: a
plausible-sounding product recommendation that nobody checked. "They could use a
customer portal" is true of every business on earth and therefore says nothing.
"""

from __future__ import annotations

import pytest

from atlas_kernel.outreach import opportunity as opp

ABSENT = frozenset({"arabic", "click_to_call", "whatsapp", "google_maps"})
PRESENT = frozenset({"social_proof", "services_navigation", "structured_data"})


def test_an_opportunity_cannot_be_built_without_evidence() -> None:
    with pytest.raises(opp.Unsupported):
        opp.Opportunity(key="k", name="n", product="Website redesign", family="website",
                        priority="HIGH", confidence="HIGH", evidence=(), why="", builds="",
                        user="", interaction="", value="")


def test_an_opportunity_must_name_a_product_in_the_vocabulary() -> None:
    with pytest.raises(opp.Unsupported):
        opp.Opportunity(key="k", name="n", product="Something we made up", family="website",
                        priority="HIGH", confidence="HIGH", evidence=("seen",), why="",
                        builds="", user="", interaction="", value="")


def test_nothing_is_derived_from_an_unverified_feature() -> None:
    """A checker that could not see Arabic has not established its absence."""
    none_at_all = opp.derive(category="food", absent=frozenset(), present=frozenset())
    assert none_at_all == (), "no evidence must produce no opportunities"


def test_absence_drives_the_fix_and_presence_drives_the_product() -> None:
    found = {o.key for o in opp.derive(category="food", absent=ABSENT, present=PRESENT)}
    assert {"arabic", "reachability", "whatsapp"} <= found, "confirmed absences"
    assert {"proof", "discovery", "editorial"} <= found, "things they already have"


def test_every_derived_opportunity_cites_what_it_was_derived_from() -> None:
    for o in opp.derive(category="food", absent=ABSENT, present=PRESENT):
        assert o.evidence, o.key
        assert all(("absent" in e or "already" in e) for e in o.evidence), o.evidence


def test_ranking_puts_the_best_evidenced_high_priority_item_first() -> None:
    ranked = opp.for_host("ahscatering.com", category="food", absent=ABSENT, present=PRESENT)
    assert ranked[0].key == "proof"
    assert opp.headline(ranked) == "Proof system"
    assert [o.priority for o in ranked] == sorted(
        (o.priority for o in ranked), key=opp.PRIORITIES.index), "priority order"


def test_research_beats_a_rule_for_the_same_opportunity() -> None:
    """A rule sees a feature flag; research saw thirty-two orphaned pages."""
    derived = {o.key: o for o in opp.derive(category="food", absent=ABSENT, present=PRESENT)}
    researched = {o.key: o for o in
                  opp.for_host("www.ahscatering.com", category="food",
                               absent=ABSENT, present=PRESENT)}
    assert len(researched["proof"].evidence) > len(derived["proof"].evidence)
    assert "170 photographs" in " ".join(researched["proof"].evidence)


def test_an_unresearched_host_still_gets_the_derived_set() -> None:
    ranked = opp.for_host("some-other-business.ae", category="food",
                          absent=ABSENT, present=PRESENT)
    assert ranked and all(o.evidence for o in ranked)


def test_the_vocabulary_has_no_duplicate_products_across_families() -> None:
    """Two families offering the same product name makes the family meaningless."""
    seen: dict[str, str] = {}
    for family, products in opp.FAMILIES.items():
        for product in products:
            if product in seen and product not in ("Comparison",):
                raise AssertionError(f"{product!r} in both {seen[product]} and {family}")
            seen[product] = family
