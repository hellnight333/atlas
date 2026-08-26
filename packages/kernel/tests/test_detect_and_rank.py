"""Detection and ranking: only what the evidence supports, and why it ranks.

Ranking is deterministic on purpose. A model asked to order a list will produce
one, and it will be plausible, and nobody will be able to say why one thing came
above another six weeks later.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from atlas_kernel.opportunity import detect, extractors, ranking
from atlas_kernel.opportunity.discovery import Classification, DiscoveryState
from atlas_kernel.opportunity.models import Business, Evidence, EvidenceKind
from atlas_kernel.opportunity.scan import Recorded
from atlas_kernel.opportunity.signals import Inference, Observation, Signal, SignalKind


def an_evidence() -> Evidence:
    return Evidence(kind=EvidenceKind.HTTP_RESPONSE, source="https://o.test/",
                    observed={"status": 200,
                              "content_type": "application/json",
                              "body": json.dumps({"elements": []}),
                              "body_truncated": False},
                    detector="recipe:http-fetch")


def a_record(*, name: str = "Marina Dental",
             state: DiscoveryState = DiscoveryState.DISCOVERED_BY_QEVIK,
             website: str | None = None) -> Recorded:
    from atlas_kernel.opportunity.discovery import Sighting

    evidence = an_evidence()
    return Recorded(
        sighting=Sighting(name=name, source="openstreetmap",
                          source_id="node/1", source_url=website or "",
                          city="Dubai", evidence=[evidence]),
        business=Business(name=name, geography="Dubai", website=website),
        classification=Classification(state=state, because="test"))


def an_extraction(*, website_absent: bool) -> extractors.Extraction:
    stated = {"name"} if website_absent else {"name", "source_url"}
    return extractors.Extraction(
        extractor="openstreetmap", source_id="node/1",
        fields={"name": "Marina Dental"},
        presence=extractors.OPENSTREETMAP.presence_for(stated),
        evidence_fingerprint=an_evidence().fingerprint,
        evidence_source="https://o.test/")


# ------------------------------------------------------ what it detects

def test_a_business_new_to_qevik_is_an_opportunity():
    found = detect.new_business(a_record(), source="openstreetmap")
    assert found is not None
    assert found.kind is SignalKind.NEW_BUSINESS
    assert found.observations[0].evidence


def test_a_business_already_known_is_not():
    """A list of businesses Qevik already had is not a discovery feed, and a
    detector firing on every sighting would produce one opportunity per scan
    per business, for ever."""
    assert detect.new_business(
        a_record(state=DiscoveryState.KNOWN), source="openstreetmap") is None


def test_a_source_that_records_no_website_is_a_lead_to_verify():
    found = detect.unverified_web_presence(
        a_record(), an_extraction(website_absent=True), source="openstreetmap")
    assert found is not None
    assert "check whether" in found.actions[0].statement.lower()
    assert "sell" not in found.actions[0].statement.lower()


def test_a_source_that_does_record_one_is_not():
    assert detect.unverified_web_presence(
        a_record(website="https://a.example"),
        an_extraction(website_absent=False), source="openstreetmap") is None


def test_the_web_inference_admits_the_source_may_simply_not_list_it():
    """The false positive this detector must not produce."""
    found = detect.unverified_web_presence(
        a_record(), an_extraction(website_absent=True), source="openstreetmap")
    assert "does not list" in found.inferences[0].would_be_wrong_if


def test_no_detector_claims_anything_about_the_world():
    for entry in detect.describe():
        assert entry["claims_about_the_world"] is False


def test_extractions_are_matched_by_source_id_not_by_position():
    """A sighting skipped for having no name shifts the lists apart, and
    pairing by index would attach one business's evidence to another's."""
    mine = a_record()
    stranger = an_extraction(website_absent=True).model_copy(
        update={"source_id": "node/999"})
    found = detect.from_pass([mine], [stranger], source="openstreetmap")
    assert {s.kind for s in found} == {SignalKind.NEW_BUSINESS}


def test_every_detected_signal_carries_evidence_and_a_hedged_inference():
    found = detect.from_pass([a_record()], [an_extraction(website_absent=True)],
                             source="openstreetmap")
    assert found
    for signal in found:
        assert all(o.evidence for o in signal.observations)
        assert all(0.0 < i.confidence < 1.0 for i in signal.inferences)
        assert all(set(i.rests_on) <= {f for o in signal.observations
                                       for f in o.fingerprints}
                   for i in signal.inferences)


# ------------------------------------------------------------------ ranking

def a_signal(*, confidence: float = 0.5, pieces: int = 1,
             business: str = "b-1", when: datetime | None = None,
             capability: str = "researcher") -> Signal:
    from atlas_kernel.opportunity.signals import Reach, SuggestedAction

    evidence = [Evidence(kind=EvidenceKind.HTTP_RESPONSE,
                         source=f"https://o{n}.test/", observed={"status": 200},
                         detector="t") for n in range(pieces)]
    observation = Observation(statement="a thing", scope="x", evidence=evidence,
                              observed_at=when or datetime.now(UTC))
    return Signal(
        kind=SignalKind.NEW_BUSINESS, business_id=business,
        observations=[observation],
        inferences=[Inference(statement="might mean something",
                              rests_on=tuple(observation.fingerprints),
                              confidence=confidence)],
        actions=[SuggestedAction(statement="look at it", reach=Reach.INTERNAL,
                                 needs_approval=False, capability=capability)])


def test_a_score_shows_its_working():
    scored = ranking.rank(a_signal())
    assert scored.components
    assert all(c.because for c in scored.components)
    assert abs(scored.score - sum(c.contribution
                                  for c in scored.components)) < 1e-9


def test_more_evidence_ranks_higher():
    assert ranking.rank(a_signal(pieces=4)).score > \
           ranking.rank(a_signal(pieces=1)).score


def test_evidence_plateaus_so_a_noisy_source_cannot_dominate():
    many = ranking.rank(a_signal(pieces=ranking.EVIDENCE_PLATEAU))
    absurd = ranking.rank(a_signal(pieces=ranking.EVIDENCE_PLATEAU * 20))
    assert many.score == absurd.score


def test_a_more_confident_inference_ranks_higher():
    assert ranking.rank(a_signal(confidence=0.9)).score > \
           ranking.rank(a_signal(confidence=0.1)).score


def test_something_seen_today_ranks_above_something_seen_last_month():
    now = datetime.now(UTC)
    fresh = ranking.rank(a_signal(when=now), now=now)
    stale = ranking.rank(a_signal(when=now - timedelta(days=40)), now=now)
    assert fresh.score > stale.score


def test_something_qevik_cannot_do_ranks_below_something_it_can():
    """Not worthless — worth less today than one actionable this afternoon."""
    assert ranking.rank(a_signal(capability="researcher")).score > \
           ranking.rank(a_signal(capability="no-such-capability")).score


def test_a_named_business_ranks_above_a_market_observation():
    assert ranking.rank(a_signal(business="b-1")).score > \
           ranking.rank(a_signal(business="")).score


def test_the_order_is_stable_across_runs():
    """A ranking that reorders itself between refreshes is one nobody trusts."""
    signals = [a_signal(confidence=0.5, business=f"b-{n}") for n in range(5)]
    first = [r.signal_id for r in ranking.order(signals)]
    second = [r.signal_id for r in ranking.order(list(reversed(signals)))]
    assert first == second


# ------------------------------------------------------------------- value

def test_value_is_unknown_and_carries_no_number():
    scored = ranking.rank(a_signal())
    assert scored.value_status == "UNKNOWN"
    assert scored.value_amount is None
    assert scored.summary()["value"] == {"amount": None, "status": "UNKNOWN"}


def test_a_number_labelled_unknown_is_refused():
    with pytest.raises(ValueError, match="labelled UNKNOWN"):
        a_signal().model_copy(update={"estimated_value": 5000.0}).model_validate(
            {**a_signal().model_dump(), "estimated_value": 5000.0,
             "value_status": "UNKNOWN"})


def test_a_status_with_no_number_is_refused():
    with pytest.raises(ValueError, match="without a number"):
        Signal.model_validate({**a_signal().model_dump(),
                               "value_status": "REPORTED"})


def test_ranking_does_not_score_revenue_at_all():
    """A placeholder would sort the list by a fiction."""
    assert "value" not in ranking.WEIGHTS
    assert "revenue" not in ranking.WEIGHTS
    assert "not scored" in ranking.describe()["note"]


# ------------------------------------------------------ the surface it feeds

def test_the_opportunities_endpoint_serves_real_rows(tmp_path, monkeypatch):
    """Through the composed app and the real database — no demo rows anywhere.

    An empty list from this endpoint means the scan ran and found nothing, and
    a client must be able to trust that.
    """
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from atlas_kernel.auth.store import AuthStore
    from atlas_kernel.db import SessionLocal, init_db
    from atlas_kernel.opportunity.repository import OpportunityRepository
    from atlas_kernel.qevik.app import Wiring, create_app

    init_db()
    tenant = "tenant-endpoint-real"
    signal = a_signal(business="b-endpoint")
    scored = ranking.rank(signal)
    repo = OpportunityRepository()
    assert repo.save_signal(signal, scored, tenant=tenant)

    app = create_app(Wiring(repository_root=tmp_path,
                            mission_timeline=tmp_path / "m.jsonl"))
    from atlas_kernel.auth.models import Scope, User, hash_password
    who = User(username="t", password_hash=hash_password("test-only-password"),
               tenant_id=tenant, scopes=frozenset(Scope))
    monkeypatch.setattr(AuthStore, "authenticate", lambda self, token: who)
    try:
        with TestClient(app) as client:
            client.headers["Authorization"] = "Bearer t"
            listed = client.get("/api/discovery/opportunities")
            assert listed.status_code == 200, listed.text
            body = listed.json()
            mine = [r for r in body["opportunities"]
                    if r["business_id"] == "b-endpoint"]
            assert mine, "the stored opportunity was not served"
            row = mine[0]
            assert row["evidence_fingerprints"]
            assert row["value"] == {"amount": None, "status": "UNKNOWN"}
            assert {"observations", "inferences", "actions"} <= set(row["detail"])
            assert row["detail"]["inferences"][0]["is_an_inference"] is True

            one = client.get(f"/api/discovery/opportunities/{row['id']}")
            assert one.status_code == 200
            assert one.json()["id"] == row["id"]
    finally:
        with SessionLocal() as session:
            session.execute(text("DELETE FROM atlas_signals WHERE tenant_id=:t"),
                            {"t": tenant})
            session.commit()
