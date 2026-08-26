"""Discovery: what "new" means, and what Qevik may not claim from it.

The dangerous sentence these tests exist to make unsayable:

    Qevik found it, therefore it is new to Google Maps.

Run against the real database, because "first_seen survives a restart" is a
claim about storage and an in-memory double would pass it while proving nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from atlas_kernel.db import SessionLocal, init_db
from atlas_kernel.opportunity import scan
from atlas_kernel.opportunity.discovery import (
    ABOUT_THE_WORLD,
    Classification,
    DiscoveryState,
    Novelty,
    Origin,
    Sighting,
    classify,
    describe,
    refuse_unsupported_novelty,
)
from atlas_kernel.opportunity.models import Evidence, EvidenceKind
from atlas_kernel.opportunity.repository import OpportunityRepository
from atlas_kernel.opportunity.tenancy import ALL_TENANTS

TENANT = "tenant-discovery"


@pytest.fixture(scope="module", autouse=True)
def schema():
    init_db()


@pytest.fixture
def repo() -> OpportunityRepository:
    return OpportunityRepository()


@pytest.fixture(autouse=True)
def clean():
    """A named marker rather than a truncate: other tests share this database,
    and a cleanup that removes everything removes their fixtures too."""
    yield
    with SessionLocal() as session:
        session.execute(text(
            "DELETE FROM atlas_sightings WHERE source LIKE 'test-disc-%'"))
        session.execute(text(
            "DELETE FROM atlas_businesses WHERE name LIKE 'DiscTest %'"))
        session.commit()


def an_evidence(url: str = "https://places.test/x") -> Evidence:
    return Evidence(kind=EvidenceKind.HTTP_RESPONSE, source=url,
                    observed={"status": 200, "place_id": "PL-1"},
                    detector="test-disc-source")


def a_sighting(**over) -> Sighting:
    fields = dict(name="DiscTest Marina Dental", source="test-disc-places",
                  source_id="PL-1", source_url="https://discteal.test/",
                  country="AE", city="Dubai", evidence=[an_evidence()])
    fields.update(over)
    return Sighting(**fields)


# ============================================== 1. a new entity is discovered

def test_a_new_entity_is_discovered_and_remembered(repo):
    found = scan.record([a_sighting()], repository=repo, tenant=TENANT)
    assert found.seen == 1
    assert len(found.new_to_qevik) == 1
    only = found.recorded[0]
    assert only.classification.state is DiscoveryState.DISCOVERED_BY_QEVIK
    assert only.business.id
    assert repo.get_business(only.business.id, tenant=ALL_TENANTS) is not None


# ==================================== 2. the same entity is not duplicated

def test_the_same_entity_is_not_duplicated_on_the_next_run(repo):
    first = scan.record([a_sighting()], repository=repo, tenant=TENANT)
    second = scan.record([a_sighting()], repository=repo, tenant=TENANT)

    assert first.recorded[0].business.id == second.recorded[0].business.id, \
        "the second scan created a second company"
    assert second.recorded[0].classification.state is DiscoveryState.KNOWN
    assert second.new_to_qevik == []


def test_a_replayed_scan_does_not_double_count_the_sighting(repo):
    """A scan re-run after a crash must be safe."""
    once = a_sighting()
    scan.record([once], repository=repo, tenant=TENANT)
    again = scan.record([once], repository=repo, tenant=TENANT)
    assert not again.recorded[0].stored, "the same sighting was stored twice"

    business_id = again.recorded[0].business.id
    assert len(repo.sightings_for(business_id, tenant=TENANT)) == 1


# =============================== 3 & 4. first/last seen and evidence survive

def test_first_and_last_seen_survive_a_restart(repo):
    early = datetime.now(UTC) - timedelta(days=30)
    first = scan.record([a_sighting(observed_at=early)], repository=repo,
                        tenant=TENANT)
    business_id = first.recorded[0].business.id
    originally = repo.get_business(business_id, tenant=ALL_TENANTS).first_seen_at

    scan.record([a_sighting(observed_at=datetime.now(UTC))], repository=repo,
                tenant=TENANT)

    # A *new* repository object over the same database — the closest a single
    # process gets to "the service restarted".
    reread = OpportunityRepository().get_business(business_id, tenant=ALL_TENANTS)
    assert reread.first_seen_at == originally, "first_seen moved"
    assert reread.last_seen_at >= reread.first_seen_at


def test_evidence_survives_a_restart(repo):
    found = scan.record([a_sighting()], repository=repo, tenant=TENANT)
    business_id = found.recorded[0].business.id

    stored = OpportunityRepository().sightings_for(business_id, tenant=TENANT)
    assert stored, "no sighting survived"
    kept = stored[0]["evidence"]
    assert kept and kept[0]["source"] == "https://places.test/x"
    assert kept[0]["observed"]["place_id"] == "PL-1"
    assert kept[0]["detector"] == "test-disc-source"


def test_previous_observations_accumulate(repo):
    """The record has to carry how we came to know, not just that we know."""
    scan.record([a_sighting(source="test-disc-places")], repository=repo,
                tenant=TENANT)
    found = scan.record(
        [a_sighting(source="test-disc-directory", source_id="DIR-9")],
        repository=repo, tenant=TENANT)
    history = repo.sightings_for(found.recorded[0].business.id, tenant=TENANT)
    assert {row["source"] for row in history} == {
        "test-disc-places", "test-disc-directory"}


def test_a_sighting_keeps_the_state_it_had_at_the_time(repo):
    """A sighting that was a discovery in August stays one in September.
    Rewriting it would make the history agree with the present."""
    scan.record([a_sighting()], repository=repo, tenant=TENANT)
    found = scan.record([a_sighting(source_id="PL-1-again")], repository=repo,
                        tenant=TENANT)
    history = repo.sightings_for(found.recorded[0].business.id, tenant=TENANT)
    assert history[0]["state"] == DiscoveryState.DISCOVERED_BY_QEVIK.value
    assert history[-1]["state"] == DiscoveryState.KNOWN.value


# ============= 5. NEW_TO_QEVIK is not mislabelled as new to the source

def test_qevik_not_having_seen_something_is_not_a_claim_about_the_world():
    found = classify(a_sighting(), known_to_qevik=False)
    assert found.state is DiscoveryState.DISCOVERED_BY_QEVIK
    assert not found.claims_about_the_world
    assert "says nothing about whether the entity is new" in found.because.lower()


def test_only_the_source_can_make_it_proven_new():
    evidence = an_evidence()
    evidenced = a_sighting(novelty=Novelty(
        source="test-disc-places", field="first_review_at",
        value="2026-08-20", evidence=evidence))
    found = classify(evidenced, known_to_qevik=False)
    assert found.state is DiscoveryState.PROVEN_NEW_TO_SOURCE
    assert found.claims_about_the_world
    # And it says new *to that source*, not new outright.
    assert "not the same as new to the world" in found.because


def test_exactly_one_state_claims_anything_about_the_world():
    assert ABOUT_THE_WORLD == {DiscoveryState.PROVEN_NEW_TO_SOURCE}
    for entry in describe():
        if entry["state"] != DiscoveryState.PROVEN_NEW_TO_SOURCE.value:
            assert not entry["claims_about_the_world"], entry


def test_a_hand_assembled_proven_state_without_evidence_is_refused():
    """`classify` cannot produce this, but a stored row, an API body or a
    model's output could."""
    assert refuse_unsupported_novelty(
        DiscoveryState.PROVEN_NEW_TO_SOURCE, None)
    assert refuse_unsupported_novelty(
        DiscoveryState.NEW_TO_QEVIK, None) == ""


def test_novelty_cannot_be_conjured_without_naming_what_was_read():
    """A caller cannot reach the strong state by passing a bare True."""
    with pytest.raises(ValueError):
        Novelty(source="test-disc-places", field="", value="yes",
                evidence=an_evidence())
    with pytest.raises(ValueError):
        Novelty(source="", field="first_review_at", value="2026-08-20",
                evidence=an_evidence())


def test_a_supplied_entity_is_not_a_discovery():
    """Somebody typed it in. That is not Qevik finding anything."""
    found = classify(a_sighting(origin=Origin.SUPPLIED), known_to_qevik=False)
    assert found.state is DiscoveryState.NEW_TO_QEVIK
    assert not found.claims_about_the_world


def test_the_stored_row_records_whether_it_claimed_anything(repo):
    evidenced = a_sighting(novelty=Novelty(
        source="test-disc-places", field="first_review_at",
        value="2026-08-20", evidence=an_evidence()))
    found = scan.record([evidenced], repository=repo, tenant=TENANT)
    row = repo.sightings_for(found.recorded[0].business.id, tenant=TENANT)[0]
    assert row["state"] == DiscoveryState.PROVEN_NEW_TO_SOURCE.value
    assert row["claims_about_the_world"] is True
    assert row["novelty"]["field"] == "first_review_at"


def test_a_discovery_feed_excludes_what_was_already_known(repo):
    scan.record([a_sighting()], repository=repo, tenant=TENANT)
    scan.record([a_sighting(source_id="PL-1-b")], repository=repo,
                tenant=TENANT)
    feed = repo.recent_discoveries(tenant=TENANT)
    assert feed, "nothing in the feed"
    assert all(row["state"] != DiscoveryState.KNOWN.value for row in feed)


# ------------------------------------------------------- the order that matters

def test_resolution_happens_before_classification(repo):
    """A scan that classified first and resolved afterwards would report every
    sighting as new on every run. Asserted through behaviour rather than by
    reading the source: three passes, one discovery."""
    for _ in range(3):
        scan.record([a_sighting(source_id=f"PL-{_}")], repository=repo,
                    tenant=TENANT)
    business_id = scan.record([a_sighting(source_id="PL-final")],
                              repository=repo,
                              tenant=TENANT).recorded[0].business.id
    history = repo.sightings_for(business_id, tenant=TENANT)
    discoveries = [r for r in history
                   if r["state"] != DiscoveryState.KNOWN.value]
    assert len(discoveries) == 1, [r["state"] for r in history]


def test_a_classification_carries_its_reason_in_checkable_terms():
    found = classify(a_sighting(), known_to_qevik=True)
    assert isinstance(found, Classification)
    assert found.because
    assert found.summary()["claims_about_the_world"] is False


# ==================================================== the surface a phone reads

def _app(tmp_path):
    from fastapi import FastAPI

    from atlas_kernel.auth import api as auth_api
    from atlas_kernel.auth.models import Scope, User, hash_password
    from atlas_kernel.auth.store import AuthStore
    from atlas_kernel.opportunity import api as discovery_api

    application = FastAPI()
    auth_api.install(application, AuthStore())
    discovery_api.install(application)
    who = User(username="tester",
               password_hash=hash_password("test-only-password"),
               tenant_id=TENANT, scopes=frozenset(Scope))
    return application, who


def _client(application, who, monkeypatch):
    from fastapi.testclient import TestClient

    from atlas_kernel.auth.store import AuthStore

    monkeypatch.setattr(AuthStore, "authenticate", lambda self, token: who)
    client = TestClient(application)
    client.headers["Authorization"] = "Bearer t"
    return client


def test_the_feed_says_which_rows_claim_anything_about_the_world(
        repo, tmp_path, monkeypatch):
    scan.record([a_sighting()], repository=repo, tenant=TENANT)
    application, who = _app(tmp_path)
    with _client(application, who, monkeypatch) as client:
        answered = client.get("/api/discovery")
    assert answered.status_code == 200, answered.text
    body = answered.json()
    assert body["discoveries"]
    assert all("claims_about_the_world" in row for row in body["discoveries"])
    assert body["counts"]["claiming_about_the_world"] == 0
    # The caveat travels with the data rather than living in a client somebody
    # else wrote.
    assert "not new to the world" in body["note"]


def test_the_states_endpoint_serves_the_kernels_own_meanings(
        tmp_path, monkeypatch):
    """So a surface cannot invent a friendlier meaning for
    DISCOVERED_BY_QEVIK than the one the kernel gives it."""
    application, who = _app(tmp_path)
    with _client(application, who, monkeypatch) as client:
        answered = client.get("/api/discovery/states")
    served = {row["state"]: row for row in answered.json()["states"]}
    assert served[DiscoveryState.DISCOVERED_BY_QEVIK.value][
        "claims_about_the_world"] is False
    assert served[DiscoveryState.PROVEN_NEW_TO_SOURCE.value][
        "claims_about_the_world"] is True


def test_the_evidence_trail_is_reachable_per_business(
        repo, tmp_path, monkeypatch):
    found = scan.record([a_sighting()], repository=repo, tenant=TENANT)
    business_id = found.recorded[0].business.id
    application, who = _app(tmp_path)
    with _client(application, who, monkeypatch) as client:
        answered = client.get(f"/api/discovery/{business_id}/sightings")
    assert answered.status_code == 200, answered.text
    trail = answered.json()
    assert trail["sightings"][0]["evidence"]
    assert trail["first_seen_at"] and trail["last_seen_at"]


def test_an_unknown_business_is_absent_not_forbidden(tmp_path, monkeypatch):
    """A 403 would confirm the record exists."""
    application, who = _app(tmp_path)
    with _client(application, who, monkeypatch) as client:
        answered = client.get("/api/discovery/no-such-business/sightings")
    assert answered.status_code == 404


def test_the_surface_offers_no_way_to_execute_anything(tmp_path):
    """A discovery surface that could start work would be a scanner with
    authority. Approving what a signal suggests is a mission, created through
    the mission API behind policy."""
    from atlas_kernel.opportunity.api import build_router

    for route in build_router().routes:
        assert route.methods == {"GET"}, f"{route.path} accepts {route.methods}"


def _composed(tmp_path):
    from atlas_kernel.qevik.app import Wiring, create_app
    return create_app(Wiring(repository_root=tmp_path,
                             mission_timeline=tmp_path / "m.jsonl"))


def test_discovery_is_wired_into_the_real_control_plane(tmp_path):
    """Not just a router that builds — one the composed app actually serves.

    Asserted by hitting it: `app.routes` holds nested router objects rather
    than their paths, so walking it proves nothing and a route that was never
    included would look identical.

    The suite authenticates by default (`conftest._authenticated_by_default`),
    so a served route answers 200 here. The claim is that it is not 404.
    """
    from fastapi.testclient import TestClient

    with TestClient(_composed(tmp_path), raise_server_exceptions=False) as client:
        for path in ("/api/discovery", "/api/discovery/states"):
            assert client.get(path).status_code != 404, f"{path} is not served"
        assert client.get("/api/discovery/states").status_code == 200


@pytest.mark.real_auth
def test_the_discovery_surface_refuses_an_unauthenticated_caller(tmp_path):
    """With the default-auth fixture opted out, so the genuine middleware runs."""
    from fastapi.testclient import TestClient

    with TestClient(_composed(tmp_path), raise_server_exceptions=False) as client:
        assert client.get("/api/discovery").status_code == 401
        assert client.get("/api/discovery/states").status_code == 401


def test_the_discovery_surface_accepts_no_writes(tmp_path):
    """A discovery surface that could start work would be a scanner with
    authority."""
    from fastapi.testclient import TestClient

    with TestClient(_composed(tmp_path), raise_server_exceptions=False) as client:
        assert client.post("/api/discovery").status_code in (401, 405)
