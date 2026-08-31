"""A cooldown protects a person, not a database row.

Production holds four phone numbers spread across nine business records —
branches of a chain, a group practice on one switchboard. A cooldown keyed only
on the business would let one phone receive three messages inside a fourteen-day
window, each one passing the guard that exists to prevent exactly that.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from atlas_kernel.opportunity.outreach import ContactHistory, normalise_recipient

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
YESTERDAY = NOW - timedelta(days=1)


class TestTheAddressIsWhatReceivesTheMessage:
    def test_two_businesses_on_one_phone_share_a_cooldown(self) -> None:
        """The defect. `drjoydentalclinic.com` is three records on one number."""
        history = ContactHistory()
        history.record("business-1", YESTERDAY, recipient="+971 4 123 4567")

        assert history.within_cooldown("business-2", 14, now=NOW,
                                       recipient="+971 4 123 4567") is True

    def test_a_different_address_is_not_blocked_by_it(self) -> None:
        """Six branches of a chain have six phones. Blocking all of them
        because one was contacted would be the opposite error."""
        history = ContactHistory()
        history.record("business-1", YESTERDAY, recipient="+971 4 123 4567")

        assert history.within_cooldown("business-2", 14, now=NOW,
                                       recipient="+971 4 999 8888") is False

    def test_one_business_reached_at_two_addresses_is_still_one_business(
            self) -> None:
        """Both keys, because they answer different questions."""
        history = ContactHistory()
        history.record("business-1", YESTERDAY, recipient="a@example.ae")

        assert history.within_cooldown("business-1", 14, now=NOW,
                                       recipient="b@example.ae") is True

    def test_outside_the_window_it_permits(self) -> None:
        history = ContactHistory()
        history.record("business-1", NOW - timedelta(days=20),
                       recipient="+971 4 123 4567")

        assert history.within_cooldown("business-2", 14, now=NOW,
                                       recipient="+971 4 123 4567") is False

    def test_omitting_the_recipient_keeps_the_older_rule(self) -> None:
        """Every existing caller keeps working; the check is simply weaker."""
        history = ContactHistory()
        history.record("business-1", YESTERDAY, recipient="+97141234567")

        assert history.within_cooldown("business-1", 14, now=NOW) is True
        assert history.within_cooldown("business-2", 14, now=NOW) is False


class TestOneSpellingPerAddress:
    @pytest.mark.parametrize("written", [
        "+971 50 123 4567", "+971501234567", "971501234567",
        "050 123 4567", "(050) 123-4567",
    ])
    def test_a_phone_written_any_way_is_one_phone(self, written: str) -> None:
        """Without this the guard is defeated by punctuation."""
        assert normalise_recipient(written) == normalise_recipient("+971501234567")

    def test_an_email_is_matched_case_insensitively(self) -> None:
        assert (normalise_recipient("Hello@Example.AE")
                == normalise_recipient("hello@example.ae"))

    def test_two_genuinely_different_numbers_stay_different(self) -> None:
        """The negative control. A normaliser that collapsed everything would
        pass every test above and block all outreach."""
        assert (normalise_recipient("+971501234567")
                != normalise_recipient("+971509999999"))

    def test_nothing_normalises_to_nothing(self) -> None:
        for empty in ("", "   ", None):
            assert normalise_recipient(empty) == ""

    def test_an_empty_recipient_does_not_match_every_other_empty_one(self) -> None:
        """A blank address must not become a key that blocks everything."""
        history = ContactHistory()
        history.record("business-1", YESTERDAY, recipient="")

        assert history.within_cooldown("business-2", 14, now=NOW,
                                       recipient="") is False


def test_the_send_path_passes_the_recipient() -> None:
    """Structural. The rule is worth nothing if the one caller that matters
    still asks the weaker question."""
    import inspect

    from atlas_kernel.opportunity.outreach import OutreachService

    source = inspect.getsource(OutreachService.send)

    assert "recipient=message.recipient" in source


def test_the_loader_reads_both_keys() -> None:
    """A history rebuilt without addresses makes the guard above dead code in
    production while every test here still passes."""
    import inspect

    from atlas_kernel.opportunity.repository import OpportunityRepository

    source = inspect.getsource(OpportunityRepository.load_contact_history)

    assert "m.recipient" in source
    assert "ContactHistory(contacts, recipients)" in source
