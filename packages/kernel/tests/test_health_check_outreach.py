"""What a message may say about a published health check.

The artefact at the URL is a report about a website the business already has.
The website message says one was built for them. Pointing the second at the
first is a false statement to a stranger, over Qevik's name, and it is one
missing field away from happening.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from atlas_kernel.outreach import identity, preparation
from atlas_kernel.outreach.preparation import (
    COMPOSABLE,
    NotPreparable,
    compose_health_check,
    prepare,
)

BUSINESS = SimpleNamespace(id="b1", name="Apex Plumbing Services Dubai",
                           email="hello@apex.test", phone=None,
                           website="https://apex.test/")
SIGNAL = {"id": "sig-1", "business_id": "b1", "evidence_fingerprints": ["f1"]}


def _publication(offer: str = "offer-health-check") -> dict:
    return {"url": "https://sites.qevik.ai/site-98cf44bff7fa44dc/",
            "site_id": "site-98cf44bff7fa44dc", "commit": "c" * 40,
            "mission_id": "m1", "offer": offer}


def _prepared(offer: str = "offer-health-check"):
    return prepare(business=BUSINESS, signal=SIGNAL,
                   publication=_publication(offer), approved_scope="scope",
                   answers=("opening hours are published",))


class TestAPublicationThatCannotSayWhatItIs:
    def test_a_record_with_no_offer_is_refused(self) -> None:
        """Every publication written before the field existed has none.
        Defaulting to `offer-website` would tell a business a site was built
        for them when what is there is a report about their own."""
        with pytest.raises(NotPreparable) as refused:
            _prepared("")

        assert "does not say what it published" in str(refused.value)

    def test_an_offer_this_module_cannot_write_about_is_refused(self) -> None:
        """Composing for an unknown offer means guessing what is at the URL,
        and the guess is published to the business it is about."""
        with pytest.raises(NotPreparable):
            _prepared("offer-imagery")

    def test_the_website_message_still_works(self) -> None:
        """The negative control. A guard that refused everything would pass the
        two tests above and break the only outreach that exists."""
        assert "A website for" in _prepared("offer-website").subject


class TestWhatTheHealthCheckMessageSays:
    def test_it_describes_a_report_not_a_build(self) -> None:
        prepared = _prepared()

        assert "health check" in prepared.body.lower()
        assert "I checked" in prepared.body
        assert prepared.url in prepared.body

    def test_it_never_says_a_website_was_built(self) -> None:
        """The exact confusion this exists to prevent."""
        body = _prepared().body.lower()

        for built in ("i built", "built one", "built a website",
                      "rather than describe what that would look like"):
            assert built not in body, built

    def test_it_claims_no_relationship_and_no_request(self) -> None:
        """Neither is true. A stranger reading either would be reading a lie
        about their own dealings with us."""
        body = _prepared().body.lower()

        for claimed in ("you asked", "you requested", "as requested",
                        "as discussed", "following up", "our previous",
                        "thank you for your enquiry", "as agreed",
                        "you signed", "your account"):
            assert claimed not in body, claimed

    def test_it_says_that_some_checks_could_not_be_established(self) -> None:
        """The artefact reports three states and the message must not flatten
        them into two — a reader told "here is what is wrong" reads every line
        as a fault, including the ones marked unverified."""
        body = _prepared().body

        assert "could not verify" in body
        assert "marked as such rather than counted against" in body

    def test_it_promises_no_outcome(self) -> None:
        """Nothing has measured any."""
        body = _prepared().body.lower()

        for promised in ("more customers", "more leads", "rank higher",
                         "increase revenue", "guarantee", "will improve",
                         "double your", "roi"):
            assert promised not in body, promised

    def test_the_call_to_action_asks_for_nothing(self) -> None:
        body = _prepared().body

        assert "if you would like" in body.lower()
        assert "you can ignore this message" in body

    def test_it_carries_no_price(self) -> None:
        """`outreach/offer.py` holds one and says why it must not appear in a
        first message."""
        body = _prepared().body.lower()

        for money in ("aed", "usd", "$", "price", "quote", "invoice", "fee"):
            assert money not in body, money

    def test_it_signs_off_as_the_licensed_entity(self) -> None:
        """Qevik is a brand, not a company. Writing otherwise is a false
        statement about a regulated status to a business that will check."""
        body = _prepared().body

        assert identity.EMAIL_SIGNATURE in body
        assert identity.entity_claims(body) == []

    def test_the_subject_is_about_their_site_not_our_offer(self) -> None:
        assert _prepared().subject == (
            "What I found on Apex Plumbing Services Dubai's website")

    def test_the_business_name_appears_as_stored(self) -> None:
        assert BUSINESS.name in _prepared().body


class TestItRemainsTheSamePipeline:
    def test_a_health_check_message_still_blocks_on_a_sending_identity(
            self) -> None:
        """The approval and delivery boundary is unchanged: a new message type
        does not get a new way out."""
        assert preparation.NO_SENDING_IDENTITY in _prepared().blocked_on

    def test_its_fingerprint_covers_the_words_that_would_go_out(self) -> None:
        """An approval binds to exact words. A message type whose fingerprint
        ignored its own body could be approved and something else sent."""
        import dataclasses

        first = _prepared()
        edited = dataclasses.replace(first, body=first.body + " one more line")

        assert edited.fingerprint != first.fingerprint

    def test_both_composable_offers_are_declared(self) -> None:
        assert set(COMPOSABLE) == {"offer-website", "offer-health-check"}


def test_the_two_messages_are_not_interchangeable() -> None:
    """Read side by side, because the whole risk is that one is sent where the
    other belongs."""
    site = prepare(business=BUSINESS, signal=SIGNAL,
                   publication=_publication("offer-website"),
                   approved_scope="s", answers=()).body
    check = compose_health_check(business_name=BUSINESS.name,
                                 url="https://sites.qevik.ai/x/", answers=())[1]

    assert "I built one" in site
    assert "I built one" not in check
    assert "health check" in check.lower()
    assert "health check" not in site.lower()
