"""What a demo is decides what a message may say about it.

Qevik sends unsolicited work to businesses that did not ask for it. The line
between "I put together a concept" and "we built your new site" is the line
between interesting and dishonest, and it must not depend on how the sentence
came out.
"""

from __future__ import annotations

import pytest

from atlas_kernel.outreach import consistency, demos


def test_every_demo_declares_a_class_from_the_vocabulary() -> None:
    for demo in demos.DEMOS:
        assert demo.classification in demos.CLASSES, demo.slug


def test_the_default_is_the_weakest_claim() -> None:
    """A demo that forgets to declare must not be introduced as client work."""
    assert demos.Demo(slug="x", name="x", industry="x", serves=frozenset(), trade="x",
                      shows="x").classification == "GENERIC_SAMPLE"


def test_the_prospect_built_demos_are_marked_as_such() -> None:
    for slug in ("sample-ahs", "sample-hire360"):
        assert demos.BY_SLUG[slug].classification == "PROSPECT_INSPIRED", slug


def test_nothing_claims_a_customer_approved_it() -> None:
    """No customer has approved anything yet. The moment one does, this changes."""
    assert not [d for d in demos.DEMOS if d.classification == "CLIENT_APPROVED_REBUILD"]


@pytest.mark.parametrize("text,slug,caught", [
    ("I built you a working example", "sample-ahs", True),
    ("We built your new site", "sample-ahs", True),
    ("the concept you commissioned", "sample-ahs", True),
    ("I put together a concept from what you publish", "sample-ahs", False),
    ("built you a working example", "sample-cafe", True),
    ("Ours, not a client's", "sample-cafe", False),
])
def test_overclaiming_is_caught_per_class(text, slug, caught) -> None:
    problems = demos.overclaims(text, demos.BY_SLUG[slug])
    assert bool(problems) is caught, (text, slug, problems)


def test_the_claim_sentence_matches_the_class() -> None:
    assert "not commissioned by you" in demos.claim(demos.BY_SLUG["sample-ahs"])
    assert demos.claim(None) == ""


def test_the_message_guard_refuses_an_overclaiming_draft() -> None:
    """The gate has to fire through the guard outreach actually runs."""
    chosen = demos.Selection(demo=demos.BY_SLUG["sample-ahs"], matched=True)
    problems = consistency.check(
        "Hi — we built your new site, have a look: " + chosen.url,
        business_id="b", speakable=(), unfixable=(), unverified=(),
        chosen=chosen, category="food")
    assert any("PROSPECT_INSPIRED" in p for p in problems), problems
