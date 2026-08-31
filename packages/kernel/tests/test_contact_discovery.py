"""Email addresses a business actually published.

Every rule here has a stranger's inbox on the other end of it. An address Qevik
derived rather than read is a guess that either bounces or reaches somebody who
never published it, and once written into a message the guess is
indistinguishable from a fact.
"""

from __future__ import annotations

import pytest

from atlas_kernel.opportunity.contacts import (
    ContactType,
    Presented,
    contactable_at,
    normalise,
    observed,
)

PAGE = """
<html><body>
  <a href="mailto:bookings@example.ae">Book a table</a>
  <p>General enquiries: info@example.ae</p>
  <p>Ask for Ahmed: ahmed.hassan@example.ae</p>
</body></html>
"""


class TestOnlyWhatThePageStates:
    def test_a_mailto_link_is_read(self) -> None:
        found = observed(PAGE, url="https://example.ae/")

        assert "bookings@example.ae" in {c.address for c in found}

    def test_an_address_in_the_text_is_read(self) -> None:
        found = {c.address for c in observed(PAGE, url="https://example.ae/")}

        assert "info@example.ae" in found

    def test_nothing_is_derived_from_the_domain(self) -> None:
        """`info@` a domain is a guess. A page that states no address yields
        none, however obvious the pattern looks."""
        assert observed("<html><body>Call us on 04 123 4567</body></html>",
                        url="https://example.ae/") == ()

    def test_the_source_page_travels_with_every_address(self) -> None:
        """Provenance: the claim has to be checkable against the page that
        made it."""
        for contact in observed(PAGE, url="https://example.ae/contact"):
            assert contact.source_url == "https://example.ae/contact"

    def test_a_mailto_beats_the_same_address_in_text(self) -> None:
        """The link is the stronger evidence that it was published to be
        written to, and the provenance should record the stronger form."""
        page = ('<a href="mailto:info@example.ae">write</a>'
                "<p>or email info@example.ae</p>")

        found = observed(page, url="https://example.ae/")

        assert len(found) == 1
        assert found[0].presented is Presented.MAILTO


class TestWhoseAddressItIs:
    @pytest.mark.parametrize("local", ["info", "bookings", "sales", "hello",
                                       "reservations", "enquiries", "support"])
    def test_a_role_address_is_usable(self, local: str) -> None:
        found = observed(f'<a href="mailto:{local}@example.ae">x</a>',
                         url="https://example.ae/")

        assert found[0].contact_type is ContactType.BUSINESS
        assert found[0].usable is True

    def test_a_person_the_business_presents_as_its_contact_is_usable(self) -> None:
        """The inventory an earlier version threw away. An owner-operated
        business whose published contact is a Gmail address is a real business
        contact, and judging it by its domain discards exactly the small
        businesses this engine exists to find."""
        found = observed(
            '<p>Ahmed Hassan &mdash; Owner</p>'
            '<a href="mailto:ahmed@gmail.com">email us</a>',
            url="https://example.ae/")

        assert found[0].contact_type is ContactType.INDIVIDUAL
        assert found[0].displayed_name == "Ahmed Hassan"
        assert found[0].displayed_role == "owner"
        assert found[0].usable is True

    def test_an_address_in_a_testimonial_is_not_a_business_contact(self) -> None:
        """It appears on the business's own site and is not the business's
        contact. Reading context rather than the domain is what tells them
        apart."""
        found = observed(
            "<div>Great service! &mdash; john@gmail.com, posted by a customer "
            "review</div>", url="https://example.ae/")

        assert found[0].contact_type is ContactType.PERSONAL
        assert found[0].usable is False
        assert found[0].displayed_name == "", (
            "a name guessed out of review prose is a claim about a person")

    def test_an_address_with_no_context_at_all_is_unknown(self) -> None:
        """Four types, not three. `UNKNOWN` is the honest answer when the page
        says nothing, and collapsing it into either would decide DQ-005 by
        accident."""
        from atlas_kernel.opportunity.contacts import classify

        kind, _, _ = classify("zayed@example.ae", context="")

        assert kind is ContactType.UNKNOWN

    def test_the_domain_alone_never_decides(self) -> None:
        """The rule that keeps owner-operated businesses in the funnel."""
        gmail_as_contact = observed(
            '<h2>Contact Us</h2><p>Reem Saleh, Manager</p>'
            '<a href="mailto:reem@gmail.com">write</a>', url="https://x/")
        own_domain_in_a_review = observed(
            "<p>testimonial from sara@thecompany.ae</p>", url="https://x/")

        assert gmail_as_contact[0].usable is True
        assert own_domain_in_a_review[0].usable is False

    def test_contactability_prefers_the_business_channel(self) -> None:
        assert contactable_at(observed(PAGE, url="https://x/")) == "bookings@example.ae"

    def test_a_page_with_only_unassociated_addresses_yields_none(self) -> None:
        page = "<p>review by ahmed.hassan@example.ae, posted by a customer</p>"

        found = observed(page, url="https://x/")

        assert found and contactable_at(found) == ""


class TestAddressesThatAreNotTheBusiness:
    @pytest.mark.parametrize("address", [
        "no-reply@example.ae", "postmaster@example.ae", "webmaster@example.ae",
        "someone@example.com", "hello@yourdomain.com",
        "abc@sentry.io", "x@wixpress.com",
        "a1b2c3d4e5f6a7b8@tracking.net",
        "logo@2x.png",
    ])
    def test_they_are_not_collected(self, address: str) -> None:
        """Writing to a tools vendor, a placeholder or an image filename
        reaches nobody who published anything."""
        found = observed(f'<a href="mailto:{address}">x</a>', url="https://x/")

        assert address not in {c.address for c in found}

    def test_a_real_address_on_a_real_domain_survives_the_filter(self) -> None:
        """The negative control. A filter that rejected everything would pass
        every test above and collect nothing, for ever."""
        found = observed('<a href="mailto:info@apexplumbing.ae">x</a>',
                         url="https://x/")

        assert [c.address for c in found] == ["info@apexplumbing.ae"]


class TestOneSpellingPerAddress:
    @pytest.mark.parametrize("written", [
        "INFO@Example.AE", " info@example.ae ", "mailto:info@example.ae",
        "info@example.ae.", "info@example.ae?subject=Hello",
    ])
    def test_they_normalise_to_one(self, written: str) -> None:
        assert normalise(written) == "info@example.ae"

    def test_dots_and_tags_in_the_local_part_are_left_alone(self) -> None:
        """Stripping them merges addresses some providers treat as distinct,
        which is a guess about somebody's mail server."""
        assert normalise("First.Last+shop@Example.AE") == "first.last+shop@example.ae"

    def test_two_different_addresses_stay_different(self) -> None:
        assert normalise("info@a.ae") != normalise("info@b.ae")

    def test_the_same_address_twice_on_a_page_is_one_contact(self) -> None:
        page = ("<p>info@example.ae</p><p>INFO@EXAMPLE.AE</p>"
                '<a href="mailto:info@example.ae">x</a>')

        assert len(observed(page, url="https://x/")) == 1


def test_it_does_no_fetching_of_its_own() -> None:
    """Structural. The audit already holds the HTML; a fetch here would be a
    second visit to somebody's site, and a second scraper."""
    import ast
    import inspect

    from atlas_kernel.opportunity import contacts

    tree = ast.parse(inspect.getsource(contacts))
    imported = {alias.name.split(".")[0]
                for node in ast.walk(tree) if isinstance(node, ast.Import)
                for alias in node.names}
    imported |= {(node.module or "").split(".")[0]
                 for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}

    assert not imported & {"httpx", "requests", "playwright", "urllib",
                           "socket"}, imported


def test_discovery_is_not_authorisation() -> None:
    """An address being known is not permission to write to it. Suppression,
    cooldown and approval are unchanged and this module knows nothing of them."""
    import ast
    import inspect

    from atlas_kernel.opportunity import contacts

    source = ast.unparse(ast.parse(inspect.getsource(contacts)))

    for boundary in ("send", "deliver", "OutreachService", "approve",
                     "suppression", "cooldown"):
        assert boundary not in source, (
            f"contact discovery references {boundary!r}; finding an address and "
            "being allowed to use it are separate")


class TestTheAddressReachesTheBusinessRecord:
    """Discovery is only useful if it makes a business contactable — and only
    safe if it never moves where a message goes."""

    def test_it_only_fills_an_absent_address(self) -> None:
        """A record that already carries one was matched on it or given it
        deliberately. Overwriting from a scrape would move where a message goes
        without anybody deciding to."""
        import inspect

        from atlas_kernel.opportunity.repository import OpportunityRepository

        source = inspect.getsource(OpportunityRepository.record_contactability)

        assert "email IS NULL OR email = ''" in source
        assert "UPDATE atlas_businesses SET email" in source

    def test_it_writes_provenance_beside_the_address(self) -> None:
        """The address must always be traceable to the page that stated it."""
        import inspect

        from atlas_kernel.opportunity.repository import OpportunityRepository

        source = inspect.getsource(OpportunityRepository.record_contactability)

        assert "contact_observed" in source
        assert "source_url" in source

    def test_it_validates_against_the_same_shape_outreach_uses(self) -> None:
        """A record whose email does not satisfy `verified_recipient` is a
        business that looks contactable and is not."""
        import inspect

        from atlas_kernel.opportunity.repository import OpportunityRepository

        source = inspect.getsource(OpportunityRepository.record_contactability)

        assert "EMAIL_SHAPE" in source

    def test_the_audit_reads_contacts_without_fetching_again(self) -> None:
        """The page is fetched for the audit's own purpose. A second fetch to
        hunt for contacts would be a second visit to somebody's site."""
        from pathlib import Path

        script = (Path(__file__).resolve().parents[3]
                  / "infra" / "audit_discovered.py").read_text(encoding="utf-8")

        # The call, not its exact arguments — an earlier version of this
        # assertion broke when the observation timestamp was added, which is a
        # stale test rather than a regression.
        assert "observed(html, url=url" in script
        # One fetch in the whole loop, the audit's own.
        assert script.count("session.open(") == 1

    def test_only_a_usable_address_is_promoted(self) -> None:
        """Personal and ambiguous addresses are recorded and never become
        contactability."""
        from pathlib import Path

        script = (Path(__file__).resolve().parents[3]
                  / "infra" / "audit_discovered.py").read_text(encoding="utf-8")

        assert 'audit.get("contactable_at")' in script
        assert "contactable_at=contactable_at(contacts)" in script


class TestTemplatePlaceholders:
    """`you@company.com` reached a real measurement run and was counted as two
    businesses' contact, because two sites shipped the same untouched theme."""

    @pytest.mark.parametrize("address", [
        "you@company.com", "youremail@example.com", "name@website.com",
        "your-email@yourcompany.com", "username@mysite.com",
    ])
    def test_a_shipped_placeholder_is_not_a_contact(self, address: str) -> None:
        found = observed(f'<a href="mailto:{address}">x</a>', url="https://x/")

        assert found == ()

    @pytest.mark.parametrize("address", [
        "info@company.ae", "info@realfirm.ae", "hello@sitedesign.ae",
        "name.surname@clinic.ae",
    ])
    def test_a_real_address_that_merely_resembles_one_survives(
            self, address: str) -> None:
        """The negative control, and the one that matters: a business genuinely
        called Company or Website must not be silently discarded."""
        found = observed(f'<h2>Contact Us</h2><a href="mailto:{address}">x</a>',
                         url="https://x/")

        assert [c.address for c in found] == [address]
