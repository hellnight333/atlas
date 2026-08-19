"""The portfolio must show range, not one template in different colours.

This is the check that would have caught the first five samples before they were
published. They shared a header, a hero, a card grid, a section order, a footer
and a type stack, and differed only in hex values — measured at 0.75 similarity
against a 0.62 threshold, on every pair.

Structural only. Colour and copy are excluded from the fingerprint on purpose:
they are exactly what changes in a reskin, so counting them would let the failure
this exists to catch score as a pass.
"""

from __future__ import annotations

import sys
from itertools import combinations
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "infra"))

from differentiation import THRESHOLD, fingerprint, strip_comments  # noqa: E402

SAMPLES = REPO / "apps" / "samples"


def built() -> list[tuple[str, str]]:
    return [
        (path.parent.name, path.read_text(encoding="utf-8"))
        for path in sorted(SAMPLES.glob("*/index.html"))
    ]


@pytest.fixture(scope="module")
def prints():
    pages = built()
    if len(pages) < 2:
        pytest.skip("need at least two samples to compare")
    return [fingerprint(name, html) for name, html in pages]


def test_no_two_samples_are_the_same_page_in_different_colours(prints) -> None:
    too_alike = []
    for left, right in combinations(prints, 2):
        similarity, shared = left.compare(right)
        if similarity >= THRESHOLD:
            too_alike.append(f"{left.name} vs {right.name} at {similarity:.2f}: {shared}")
    assert not too_alike, "\n".join(too_alike)


def test_the_samples_use_different_navigation_patterns(prints) -> None:
    """Navigation is the first thing a visitor perceives and the easiest to copy."""
    patterns = [fp.nav for fp in prints]
    assert len(set(patterns)) >= max(2, len(patterns) - 1), patterns


def test_the_samples_do_not_all_share_one_type_stack(prints) -> None:
    stacks = [fp.typography for fp in prints]
    assert len(set(stacks)) > 1, f"every sample sets the same fonts: {stacks[0]}"


def test_at_least_one_sample_is_not_a_marketing_page(prints) -> None:
    """A portfolio of brochures cannot demonstrate building an application."""
    assert any("data table" in fp.layout or "chart" in fp.layout for fp in prints), (
        "no sample demonstrates a product interface — every one is a marketing site"
    )


def test_at_least_one_sample_has_a_stateful_interaction(prints) -> None:
    assert any("stateful ui" in fp.interaction for fp in prints), (
        "no sample demonstrates a multi-step or filtered interaction"
    )


def test_every_sample_declares_itself_a_sample() -> None:
    """A visitor must never mistake one of these for a real business."""
    for name, html in built():
        body = strip_comments(html).lower()
        assert "sample" in body, name
        assert "not a real" in body or "demonstration" in body, name


def test_no_sample_claims_a_completed_transaction() -> None:
    """Nothing books, nothing sells, nothing confirms."""
    for name, html in built():
        body = strip_comments(html).lower()
        for claim in (
            "booking confirmed",
            "appointment confirmed",
            "payment complete",
            "order confirmed",
            "your table is booked",
        ):
            assert claim not in body, f"{name}: {claim!r}"


def test_no_sample_invents_third_party_credibility() -> None:
    for name, html in built():
        body = strip_comments(html).lower()
        for invented in ("testimonial", "as featured in", "award-winning", "trusted by"):
            assert invented not in body, f"{name}: {invented!r}"
