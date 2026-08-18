"""Recognising a company Atlas has already seen (M014).

Autonomous discovery means several sources reporting the same businesses, so
identity resolution stops being a nicety the moment discovery stops being a
seed list.

**The asymmetry these tests defend: merging two different companies is far worse
than failing to merge one.** A missed merge costs a duplicate row. A wrong merge
attaches one business's findings to another's proposal — a false claim about a
stranger's website, which is the exact failure the evidence rule exists to
prevent. So the interesting tests here are the ones asserting that plausible
matches are *refused*.
"""

from __future__ import annotations

import pytest

from atlas_kernel.opportunity.identity import (
    BusinessIndex,
    identity_keys,
    is_possible_duplicate,
    is_same_business,
    normalise_domain,
    normalise_name,
    normalise_phone,
    with_identity,
)
from atlas_kernel.opportunity.models import Business


def _business(**overrides) -> Business:
    payload = {
        "name": "Al Noor Dental Clinic",
        "geography": "Dubai",
        "website": "https://alnoor.ae",
        "email": "hello@alnoor.ae",
    }
    payload.update(overrides)
    return Business(**payload)


class TestDomainNormalisation:
    @pytest.mark.parametrize(
        "raw",
        [
            "https://alnoor.ae",
            "http://alnoor.ae",
            "https://www.alnoor.ae",
            "www.alnoor.ae",
            "alnoor.ae",
            "https://alnoor.ae/contact?utm=x",
            "  HTTPS://ALNOOR.AE/  ",
        ],
    )
    def test_the_same_site_written_many_ways_gives_one_key(self, raw: str) -> None:
        assert normalise_domain(raw) == "alnoor.ae"

    def test_shared_hosting_platforms_do_not_collapse_into_one_business(self) -> None:
        """The reason the host is not reduced to a registrable domain. Doing so
        would merge every business on Wix into a single company."""
        assert normalise_domain("https://clinic-a.wixsite.com/home") != normalise_domain(
            "https://clinic-b.wixsite.com/home"
        )

    def test_a_missing_website_has_no_domain_key(self) -> None:
        assert normalise_domain(None) is None
        assert normalise_domain("   ") is None


class TestPhoneNormalisation:
    def test_formatting_differences_collapse(self) -> None:
        assert normalise_phone("+971 4 123 4567") == normalise_phone("00971-4-1234567")

    def test_a_fragment_is_not_treated_as_a_number(self) -> None:
        """A four-digit extension shared by two companies must not merge them."""
        assert normalise_phone("1234") is None


class TestNameNormalisation:
    def test_legal_form_noise_is_ignored(self) -> None:
        assert normalise_name("Al Noor Dental Clinic LLC", "Dubai") == normalise_name(
            "al-noor dental clinic", "Dubai"
        )

    def test_place_is_part_of_the_key(self) -> None:
        assert normalise_name("Al Noor Clinic", "Dubai") != normalise_name(
            "Al Noor Clinic", "Sharjah"
        )


class TestMatching:
    def test_a_shared_domain_is_the_same_business(self) -> None:
        left = _business(name="Al Noor Dental", email=None)
        right = _business(name="AL-NOOR DENTAL CLINIC L.L.C.", email="info@alnoor.ae")
        assert is_same_business(left, right)

    def test_a_shared_email_is_the_same_business(self) -> None:
        left = _business(website=None)
        right = _business(name="Al Noor", website="https://different.ae")
        assert is_same_business(left, right)

    def test_a_shared_name_and_city_is_NOT_a_match(self) -> None:
        """The most important assertion in this file.

        Two branches of one clinic, or two unrelated companies with a common
        name, are indistinguishable from a name and a city. Merging them would
        put one business's findings into the other's proposal.
        """
        left = _business(website="https://alnoor-jumeirah.ae", email=None)
        right = _business(website="https://alnoor-marina.ae", email=None)
        assert not is_same_business(left, right)
        assert is_possible_duplicate(left, right)

    def test_a_possible_duplicate_stops_being_one_once_something_strong_agrees(self) -> None:
        left = _business()
        right = _business(name="Al Noor Dental Clinic LLC")
        assert is_same_business(left, right)
        assert not is_possible_duplicate(left, right)

    def test_unrelated_businesses_do_not_match(self) -> None:
        assert not is_same_business(
            _business(),
            _business(name="Jumeirah Auto Garage", website="https://garage.ae", email=None),
        )

    def test_every_business_gets_at_least_a_weak_key(self) -> None:
        """A business with no website, email or phone still has to be
        recognisable, or every discovery run creates a fresh copy of it."""
        keys = identity_keys(Business(name="Nameless Trading", geography="Dubai"))
        assert keys == ["name:nameless-trading|dubai"]


class TestBusinessIndex:
    def test_two_sources_reporting_one_business_resolve_to_one_record(self) -> None:
        index = BusinessIndex()
        first, is_new_first = index.resolve(_business(email=None, sources=["google-maps"]))
        second, is_new_second = index.resolve(
            _business(name="AL NOOR DENTAL CLINIC LLC", phone="+97141234567", sources=["directory"])
        )

        assert is_new_first is True
        assert is_new_second is False
        assert len(index.businesses) == 1
        assert second.id == first.id

    def test_merging_keeps_both_sources(self) -> None:
        """The second source finding a business is a fact about it. Overwriting
        would throw that away."""
        index = BusinessIndex()
        index.resolve(_business(sources=["google-maps"]))
        merged, _ = index.resolve(_business(sources=["directory"]))
        assert merged.sources == ["google-maps", "directory"]

    def test_merging_fills_gaps_without_overwriting_what_is_known(self) -> None:
        """A later source correcting an earlier one is possible; a later source
        being sloppier is more common, and silently replacing a good phone
        number with a worse one is not recoverable."""
        index = BusinessIndex()
        index.resolve(_business(phone=None, sources=["maps"]))
        merged, _ = index.resolve(
            _business(email="wrong@alnoor.ae", phone="+97141234567", sources=["directory"])
        )
        assert merged.email == "hello@alnoor.ae"  # first value kept
        assert merged.phone == "+97141234567"  # genuine gap filled

    def test_lookalikes_are_surfaced_not_merged(self) -> None:
        index = BusinessIndex()
        index.resolve(_business(website="https://alnoor-jumeirah.ae", email=None))
        index.resolve(_business(website="https://alnoor-marina.ae", email=None))

        assert len(index.businesses) == 2, "two different companies were merged"
        assert len(index.possible_duplicates()) == 1

    def test_a_clean_batch_reports_no_duplicates(self) -> None:
        index = BusinessIndex()
        index.resolve(_business())
        index.resolve(
            _business(name="Jumeirah Auto Garage", website="https://garage.ae", email=None)
        )
        assert index.possible_duplicates() == []

    def test_resolving_stamps_the_keys_onto_the_record(self) -> None:
        resolved, _ = BusinessIndex().resolve(_business())
        assert "domain:alnoor.ae" in resolved.identity_keys
        assert with_identity(resolved).identity_keys == resolved.identity_keys


class TestBranchesAreNotOneCompany:
    """Two branches of a clinic share a domain and a switchboard number.

    The original strong-key rule assumed "two companies do not share these",
    which is true of unrelated companies and false of branches — and it merged
    twenty audited Dubai clinics into fifteen businesses. Dr. Joy's three
    locations became one record, both Crossroads locations became one, and the
    evidence gathered on one branch's website was attached to another's.

    That is the misdirected-proposal failure this module exists to prevent,
    arriving through the front door.
    """

    def _branch(self, name: str, place: str) -> Business:
        return Business(
            name=name,
            geography="Dubai",
            website="https://drjoydental.com",
            phone="800 732757",
            metadata={"place_id": place},
        )

    def test_a_differing_place_id_beats_a_shared_domain_and_phone(self) -> None:
        palm = self._branch("Dr. Joy Dental Clinic, Palm Jumeirah", "ChIJ_palm")
        burjuman = self._branch("Dr. Joy Dental Clinic, BurJuman Mall", "ChIJ_burjuman")
        assert not is_same_business(palm, burjuman)

    def test_the_same_place_seen_twice_is_still_one_company(self) -> None:
        """The veto must not break the case resolution exists for."""
        first = self._branch("Dr Joy Dental — Palm", "ChIJ_palm")
        again = self._branch("Dr. Joy Dental Clinic, Palm Jumeirah", "ChIJ_palm")
        assert is_same_business(first, again)

    def test_without_place_ids_the_old_behaviour_is_unchanged(self) -> None:
        """A veto only applies when both records name a place. Sources that do
        not supply one must still resolve on domain as before."""
        left = Business(name="Clinic A", website="https://same-domain.ae")
        right = Business(name="Clinic A Dubai", website="https://same-domain.ae")
        assert is_same_business(left, right)

    def test_one_missing_place_id_does_not_veto(self) -> None:
        """A directory listing without a place id should still merge into the
        Places record — refusing would defeat resolution for every second
        source."""
        with_place = self._branch("Dr. Joy Dental, Palm", "ChIJ_palm")
        without = Business(name="Dr Joy Dental", website="https://drjoydental.com")
        assert is_same_business(with_place, without)

    def test_the_place_key_is_treated_as_strong(self) -> None:
        from atlas_kernel.opportunity.identity import identity_keys, strong_keys

        keys = identity_keys(self._branch("X", "ChIJ_x"))
        assert "place:ChIJ_x" in strong_keys(set(keys))
