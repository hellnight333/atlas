"""Reading a source by declared rules, and the three answers about absence.

The failure this layer exists to prevent: a model handed a page and asked to
"pull out the business details", producing a Sighting whose name came from a
heading and whose country came from a guess.
"""

from __future__ import annotations

import json

import pytest

from atlas_kernel.opportunity import extractors as X
from atlas_kernel.opportunity.discovery import Sighting
from atlas_kernel.opportunity.models import Evidence, EvidenceKind


def an_evidence(payload: dict, *, content_type: str = "application/json",
                kind: EvidenceKind = EvidenceKind.HTTP_RESPONSE,
                truncated: bool = False) -> Evidence:
    return Evidence(
        kind=kind, source="https://overpass-api.de/api/interpreter",
        observed={"status": 200, "content_type": content_type,
                  "body": json.dumps(payload), "body_truncated": truncated},
        detector="recipe:http-fetch")


def a_node(**tags) -> dict:
    return {"type": "node", "id": 1, "tags": tags}


# ------------------------------------------------ only declared fields appear

def test_an_extractor_declares_exactly_what_it_can_produce():
    assert X.OPENSTREETMAP.produces == ("city", "country", "name", "source_url")


def test_a_rule_naming_a_field_sighting_does_not_have_is_refused():
    """Fails at import rather than producing an extraction nobody can use."""
    with pytest.raises(ValueError, match="not a field of Sighting"):
        X.Field_(name="revenue", reads=("revenue",))


def test_a_rule_must_say_what_it_reads():
    with pytest.raises(ValueError, match="which source keys"):
        X.Field_(name="name", reads=())


def test_only_declared_fields_reach_the_extraction():
    found = X.extract_overpass(an_evidence({"elements": [
        a_node(name="Clinic", phone="+9715", **{"addr:city": "Dubai"})]}))
    assert set(found[0].fields) <= set(X.OPENSTREETMAP.produces)
    # `phone` is in the source and not declared, so it does not appear.
    assert "phone" not in found[0].fields


def test_the_first_key_that_carries_a_value_wins():
    """Several tags carry a website. Reading only `website` reports businesses
    as siteless when OSM recorded the URL under another key."""
    found = X.extract_overpass(an_evidence({"elements": [
        a_node(name="Clinic", **{"contact:website": "https://b.example"})]}))
    assert found[0].fields["source_url"] == "https://b.example"


# ------------------------------------------------------- absence has three answers

def test_a_field_the_source_was_asked_for_and_lacked_is_absent_in_source():
    found = X.extract_overpass(an_evidence({"elements": [a_node(name="Clinic")]}))
    assert found[0].absent_in_source("source_url")
    assert found[0].presence["source_url"] is X.Presence.ABSENT_IN_SOURCE


def test_a_field_nobody_looked_for_is_not_consulted():
    """Not the same as missing. A detector treating them alike produces "this
    clinic has no phone number" about a source that was never asked."""
    found = X.extract_overpass(an_evidence({"elements": [a_node(name="Clinic")]}))
    assert found[0].presence["business_id"] is X.Presence.NOT_CONSULTED
    assert not found[0].absent_in_source("business_id")


def test_a_stated_field_is_observed():
    found = X.extract_overpass(an_evidence({"elements": [
        a_node(name="Clinic", website="https://a.example")]}))
    assert found[0].presence["source_url"] is X.Presence.OBSERVED


def test_presence_covers_every_sighting_field():
    """So NOT_CONSULTED is visible rather than implied by absence from a dict."""
    found = X.extract_overpass(an_evidence({"elements": [a_node(name="C")]}))
    assert set(found[0].presence) == set(Sighting.model_fields)


# ------------------------------------------------------------------ refusals

def test_a_required_field_missing_skips_the_element():
    """An unnamed node cannot be written to or researched, and would arrive as
    an anonymous row that poisons the counts."""
    found = X.extract_overpass(an_evidence({"elements": [
        a_node(amenity="dentist"), a_node(name="Named")]}))
    assert [e.fields["name"] for e in found] == ["Named"]


def test_the_wrong_evidence_kind_is_refused():
    with pytest.raises(X.ExtractionError, match="reads http_response"):
        X.extract_overpass(an_evidence({"elements": []},
                                       kind=EvidenceKind.HTML_CONTENT))


def test_the_wrong_content_type_is_refused():
    with pytest.raises(X.ExtractionError, match="expects"):
        X.extract_overpass(an_evidence({"elements": []},
                                       content_type="text/html"))


def test_a_truncated_body_is_refused_rather_than_partially_read():
    """Extracting from the part that fitted would report the entities in the
    first 256 KB as though they were all of them."""
    with pytest.raises(X.ExtractionError, match="truncated"):
        X.extract_overpass(an_evidence({"elements": []}, truncated=True))


def test_an_empty_body_is_refused():
    evidence = Evidence(kind=EvidenceKind.HTTP_RESPONSE, source="https://x/",
                        observed={"content_type": "application/json",
                                  "body": ""}, detector="t")
    with pytest.raises(X.ExtractionError, match="no body"):
        X.extract_overpass(evidence)


def test_a_response_that_is_not_overpass_shaped_is_refused():
    with pytest.raises(X.ExtractionError, match="elements"):
        X.extract_overpass(an_evidence({"something": "else"}))


def test_unparsable_json_is_refused():
    evidence = Evidence(kind=EvidenceKind.HTTP_RESPONSE, source="https://x/",
                        observed={"content_type": "application/json",
                                  "body": "{not json"}, detector="t")
    with pytest.raises(X.ExtractionError, match="JSON"):
        X.extract_overpass(evidence)


# ---------------------------------------------------------------- provenance

def test_every_extraction_names_the_evidence_it_came_from():
    evidence = an_evidence({"elements": [a_node(name="Clinic")]})
    found = X.extract_overpass(evidence)
    assert found[0].evidence_fingerprint == evidence.fingerprint
    assert found[0].evidence_source == evidence.source


def test_extraction_cannot_manufacture_novelty():
    """`PROVEN_NEW_TO_SOURCE` stays impossible without a source saying so."""
    evidence = an_evidence({"elements": [a_node(name="Clinic")]})
    found = X.extract_overpass(evidence)
    sighting = X.sighting_from(found[0], evidence, source="openstreetmap")
    assert sighting.novelty is None
    assert not X.OPENSTREETMAP.can_evidence_novelty


def test_an_unknown_extractor_is_refused_and_never_substituted():
    with pytest.raises(X.UnknownExtractor, match="no extractor named"):
        X.get("invented")


def test_describe_says_what_it_consumes_and_produces():
    described = X.OPENSTREETMAP.describe()
    assert described["consumes"]["content_type"] == "json"
    assert set(described["produces"]) == set(X.OPENSTREETMAP.produces)
    assert described["can_evidence_novelty"] is False


def test_the_user_agent_does_not_impersonate_a_browser():
    """Overpass answers a `Mozilla/5.0`-prefixed agent with 406, and one that
    says truthfully what we are with 200. Measured on a real discovery run that
    failed, twice, before the token was isolated.

    Also the courtesy every crawling policy asks for: an operator whose logs we
    appear in can find out who we are and tell us to stop.
    """
    from atlas_kernel.research.net import USER_AGENT

    assert not USER_AGENT.startswith("Mozilla")
    assert "Qevik" in USER_AGENT
    # A contact route, so being asked to stop is possible.
    assert "@" in USER_AGENT or "http" in USER_AGENT
    # `crawler` in the URL is matched by anti-scraping heuristics; Overpass
    # refuses the otherwise identical string containing it.
    assert "crawler" not in USER_AGENT.lower()
