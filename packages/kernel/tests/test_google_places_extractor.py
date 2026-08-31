"""Reading a Google Places response into sightings.

The gap this closes: `sources/google_places.py` could fetch from Places and
nothing could turn the result into a sighting, so 352 of 412 businesses in
production arrived through a script that wrote business rows directly. They have
no discovery state and no `claims_about_the_world`, and can never appear in the
discovery feed.
"""

from __future__ import annotations

import json

import pytest

from atlas_kernel.opportunity.extractors import (
    GOOGLE_PLACES,
    ExtractionError,
    extract_google_places,
    get,
    sighting_from,
)
from atlas_kernel.opportunity.models import Evidence


def _response(*places) -> Evidence:
    return Evidence(kind="http_response", source="google-places",
                    statement="Places answered",
                    observed={"status": 200,
                              "content_type": "application/json",
                              "body": json.dumps({"places": list(places)})})


PLACE = {
    "id": "ChIJtd5iPVRpXz4RCJWftl-3J9w",
    "displayName": {"text": "Aveda Dubai", "languageCode": "en"},
    "websiteUri": "http://avedubai.ae/",
    "nationalPhoneNumber": "054 444 1254",
    "formattedAddress": "Jumeirah, Dubai, UAE",
    "regularOpeningHours": {"openNow": True},
}


class TestReadingWhatPlacesReturned:
    def test_a_place_becomes_one_extraction(self) -> None:
        found = extract_google_places(_response(PLACE))

        assert len(found) == 1
        assert found[0].fields["name"] == "Aveda Dubai"
        assert found[0].fields["source_url"] == "http://avedubai.ae/"

    def test_the_nested_display_name_is_read_as_text(self) -> None:
        """`displayName` is an object. Read as a string it produces a name like
        `{'text': ...}` — the sort of value that reaches a real business in a
        real message."""
        name = extract_google_places(_response(PLACE))[0].fields["name"]

        assert name == "Aveda Dubai"
        assert "{" not in name and "languageCode" not in name

    def test_the_place_id_is_the_source_id(self) -> None:
        """Without it a second scan cannot recognise the same listing, and every
        run would report the whole city as new."""
        assert extract_google_places(_response(PLACE))[0].source_id == PLACE["id"]

    def test_a_place_with_no_id_is_skipped(self) -> None:
        found = extract_google_places(_response(
            {**PLACE, "id": ""}, {**PLACE, "id": "ChIJ-second"}))

        assert [e.source_id for e in found] == ["ChIJ-second"]

    def test_a_place_with_no_name_is_skipped(self) -> None:
        """An anonymous row cannot be written to or researched."""
        found = extract_google_places(_response({"id": "x", "websiteUri": "http://a/"}))

        assert found == []

    def test_a_place_with_no_website_is_still_a_sighting(self) -> None:
        """Only `name` is required. A business with no site is exactly the kind
        the engine most wants to find."""
        found = extract_google_places(_response(
            {"id": "x", "displayName": {"text": "No Site Cafe"}}))

        assert len(found) == 1
        assert "source_url" not in found[0].fields

    def test_an_empty_answer_is_not_an_error(self) -> None:
        assert extract_google_places(_response()) == []

    def test_a_response_with_no_places_key_is_an_error(self) -> None:
        """"Places returned nothing" and "we called the wrong endpoint" must not
        read the same."""
        evidence = Evidence(kind="http_response", source="google-places",
                            statement="something else",
                            observed={"status": 200,
                                      "content_type": "application/json",
                                      "body": json.dumps({"error": "nope"})})

        with pytest.raises(ExtractionError):
            extract_google_places(evidence)

    def test_unreadable_json_is_an_error(self) -> None:
        evidence = Evidence(kind="http_response", source="google-places",
                            statement="broken",
                            observed={"status": 200,
                                      "content_type": "application/json",
                                      "body": "<html>"})

        with pytest.raises(ExtractionError):
            extract_google_places(evidence)


class TestWhatItRefusesToClaim:
    def test_it_cannot_evidence_novelty(self) -> None:
        """Places returns what it holds and never states that a listing is new
        to it. A sighting from here can be NEW_TO_QEVIK or KNOWN and never
        PROVEN_NEW_TO_SOURCE."""
        assert GOOGLE_PLACES.can_evidence_novelty is False

    def test_a_sighting_from_it_carries_no_novelty_by_default(self) -> None:
        extraction = extract_google_places(_response(PLACE))[0]
        evidence = _response(PLACE)

        sighting = sighting_from(extraction, evidence, source="google-places")

        assert sighting.novelty is None

    def test_it_states_no_city_or_country(self) -> None:
        """Places returns one formatted address, not parts. A city read out of
        it would be Qevik parsing an address and calling the result a fact the
        source stated. The model refused an earlier version that did."""
        declared = {rule.name for rule in GOOGLE_PLACES.fields}

        assert "city" not in declared and "country" not in declared
        sighting = sighting_from(extract_google_places(_response(PLACE))[0],
                                 _response(PLACE), source="google-places")
        assert sighting.city == "" and sighting.country == ""

    def test_it_extracts_no_phone(self) -> None:
        """A phone is not a Sighting field. A sighting records that a source saw
        a business; how to reach it belongs to the business record."""
        found = extract_google_places(_response(PLACE))[0]

        assert "phone" not in found.fields
        assert PLACE["nationalPhoneNumber"] not in json.dumps(found.fields)

    def test_it_refuses_evidence_from_another_source(self) -> None:
        overpass = Evidence(kind="http_response", source="openstreetmap",
                            statement="overpass",
                            observed={"status": 200,
                                      "content_type": "text/html",
                                      "body": json.dumps({"elements": []})})

        with pytest.raises(ExtractionError):
            extract_google_places(overpass)


class TestItIsRegistered:
    def test_a_recipe_can_name_it(self) -> None:
        """`EXTRACTORS` was a one-tuple, so no recipe could declare Places as
        its extractor and no Places response could become a sighting."""
        assert get("google-places") is GOOGLE_PLACES

    def test_openstreetmap_still_works(self) -> None:
        """The negative control: adding a second must not disturb the first."""
        assert get("openstreetmap").id == "openstreetmap"

    def test_both_are_described(self) -> None:
        from atlas_kernel.opportunity.extractors import describe

        assert {row["id"] for row in describe()} == {"openstreetmap",
                                                     "google-places"}
