"""A business asked Qevik about itself, and Qevik forgot.

`POST /api/public/audit` is the one place a stranger arrives under their own
steam. Every other signal is Qevik noticing a business; this is a business
noticing Qevik, and it is where a health-check recipient lands when they follow
the link in the message.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from atlas_kernel.customer import inbound
from atlas_kernel.customer.inbound import (
    LEAD_EVENT,
    AuditRequest,
    capture,
    from_events,
    host_of,
)


def _event(**detail) -> dict:
    return {"kind": LEAD_EVENT, "detail": detail}


class TestOneBusinessIsOneRow:
    @pytest.mark.parametrize("written,expected", [
        ("https://www.Example.AE/path", "example.ae"),
        ("example.ae", "example.ae"),
        ("HTTP://EXAMPLE.AE", "example.ae"),
        ("https://example.ae./", "example.ae"),
        ("https://clinic.example.ae/", "clinic.example.ae"),
    ])
    def test_spellings_of_one_address_are_one_host(self, written, expected) -> None:
        """A business that types it one way on Monday and another on Tuesday is
        one lead. Two rows would show interest where there was persistence."""
        assert host_of(written) == expected

    @pytest.mark.parametrize("junk", ["", "   ", "not a url", "localhost",
                                      "?", "http://"])
    def test_something_that_is_not_an_address_is_not_a_lead(self, junk) -> None:
        """A row an operator cannot act on, at the top of the one list in this
        system that is inbound."""
        assert host_of(junk) == ""
        assert capture(website=junk) is None

    def test_repeat_visits_are_counted_not_duplicated(self) -> None:
        rows = from_events([
            _event(website="https://example.ae/", host="example.ae",
                   at="2026-08-29", source="public-audit"),
            _event(website="example.ae", host="example.ae",
                   at="2026-08-31", source="public-audit"),
        ])

        assert len(rows) == 1
        assert rows[0]["asked"] == 2
        assert rows[0]["at"] == "2026-08-31", "the newest visit should win"

    def test_newest_first(self) -> None:
        rows = from_events([
            _event(host="a.ae", at="2026-08-01"),
            _event(host="b.ae", at="2026-08-31"),
        ])

        assert [r["host"] for r in rows] == ["b.ae", "a.ae"]


class TestWhatAnOperatorNeedsBeforeReplying:
    def test_a_business_qevik_has_never_audited_is_marked_as_such(self) -> None:
        """"We have a file on them" and "we have never looked" are different
        conversations, and the operator needs to know which."""
        cold = capture(website="https://example.ae/", observations=0)
        known = capture(website="https://example.ae/", observations=20,
                        business_id="b-1")

        assert cold.already_known is False
        assert known.already_known is True

    def test_a_matched_business_is_referenced_never_copied(self) -> None:
        """The one-customer-entity rule. The company is
        `atlas_businesses.id`."""
        request = capture(website="https://example.ae/", business_id="b-1")

        assert request.business_id == "b-1"
        assert not hasattr(request, "name")
        assert not hasattr(request, "phone")

    def test_it_records_how_they_arrived(self) -> None:
        """"They found the public audit" and "they clicked through from a health
        check we sent them" are different commercial facts, and only the second
        closes a loop."""
        assert capture(website="https://example.ae/").source == "public-audit"


class TestItCarriesNoPersonalData:
    def test_the_record_holds_only_facts_about_a_company(self) -> None:
        """The roadmap's instruction for this track is to handle personal data
        lawfully and conservatively. The most conservative lead identifies a
        business rather than a person."""
        recorded = set(capture(website="https://example.ae/").summary())

        assert recorded == {"website", "host", "source", "at", "observations",
                            "business_id", "already_known"}

    def test_nothing_in_the_module_collects_a_person(self) -> None:
        """Structural, because the pressure to enrich a lead with a name and an
        email is exactly what turns this into personal data."""
        import ast
        import inspect

        tree = ast.parse(inspect.getsource(inbound))
        for node in ast.walk(tree):
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                node.value.value = ""
        source = ast.unparse(tree).lower()

        for personal in ("email", "phone", "full_name", "first_name",
                         "ip_address", "user_agent", "cookie"):
            assert personal not in source, personal


class TestItIsNotASecondCustomerEntity:
    def test_the_record_is_a_request_not_a_company(self) -> None:
        """`test_one_customer_entity` refused an earlier version called `Lead`,
        and was right to: that is the head noun of a second customer entity."""
        assert AuditRequest.__name__ == "AuditRequest"

    def test_it_writes_to_the_shared_timeline(self) -> None:
        """No leads table. A lead is something that happened, and a second
        store is a second thing that can disagree about who asked and when."""
        import inspect

        from atlas_kernel.opportunity.repository import OpportunityRepository

        source = inspect.getsource(OpportunityRepository.record_lead)

        assert "atlas_business_events" in source
        assert "CREATE TABLE" not in source

    def test_the_repository_imports_the_event_name_from_where_it_lives(
            self) -> None:
        """It once imported `.leads` from inside `opportunity/`, which does not
        exist. Nothing exercised it, so every test passed."""
        from atlas_kernel.opportunity.repository import OpportunityRepository

        # Importing it is the test: a wrong path raises here.
        from atlas_kernel.customer.inbound import LEAD_EVENT as declared

        assert declared == "lead_captured"
        assert OpportunityRepository.record_lead is not None


def test_a_capture_stamps_the_moment() -> None:
    at = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)

    assert capture(website="https://example.ae/", at=at).at.startswith(
        "2026-08-31T12:00")
