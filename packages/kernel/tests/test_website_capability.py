"""The website capability, from research to a published page.

The complete lifecycle in one file, because the point of a vertical slice is
that the joins hold, and every join here already existed: the opportunity
engine, the recommendation, the roadmap, the execution approval, the QA gates,
the artefact approval and the publication record. What P2.2 adds is one executor
and one offer.

Most of these tests are about what the capability *refuses* to do. A website
generator is the easiest thing in this system to make dishonest — it produces
confident-looking pages, and a page that invents an opening time is wrong in the
customer's own voice, on their own domain, and they carry the consequences.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from atlas_kernel import db
from atlas_kernel.composition_root import create_runtime
from atlas_kernel.execution.artefacts import DEFAULT_PATH, bundle_hash, normalise, primary
from atlas_kernel.execution.capabilities import EXECUTORS
from atlas_kernel.execution.capabilities.website import (
    FIXES,
    NothingToBuild,
    WebsiteMode,
    build_website,
    improvable,
    mode_for,
)
from atlas_kernel.execution.models import PublicationState
from atlas_kernel.measurement import service as measurement
from atlas_kernel.measurement.attribution import Attribution, permits
from atlas_kernel.opportunity.models import Business
from atlas_kernel.outreach import opportunity as opp
from atlas_kernel.publication import (
    Connection,
    ConnectionStore,
    Destination,
    PublicationStatus,
    publish,
    stage,
)
from atlas_kernel.publication import (
    gate as publication_gate,
)
from atlas_kernel.recommendation import service as rec_service
from atlas_kernel.recommendation.models import RecommendationState
from atlas_kernel.recommendation.offers import BY_ID, offers_for_opportunity
from atlas_kernel.roadmap import Executability, assess, crossing, generate
from atlas_kernel.roadmap.lifecycle import facts_for
from atlas_kernel.website.content import FactSource
from atlas_kernel.website.targets.base import DeploymentTargetRegistry, TargetRegistration
from atlas_kernel.website.targets.local import LocalDirectoryTarget

TENANT = "tenant-qevik"
OTHER = "tenant-other"

BUSINESS = Business(id="biz-sunrise", name="Sunrise Logistics",
                    phone="+971 4 555 0100", email="hello@sunrise.test",
                    geography="Dubai", website="https://sunrise.test")

#: A site that exists and is failing: slow, broken, untitled, thin.
FAILING = {
    "website": "https://sunrise.test", "http_status": 200,
    "observations": [{"feature": f, "status": "not_found"} for f in
                     ("page_speed", "broken_links", "thin_pages", "page_title", "h1")]
    + [{"feature": f, "status": "present"} for f in
       ("viewport_meta", "contact_form", "https", "meta_description")],
    "facts": {"cms": {"service_page_list": [
        {"title": "Freight forwarding", "url": "https://sunrise.test/freight/"},
        {"title": "Customs clearance", "url": "https://sunrise.test/customs/"}]}},
}

#: A site that does everything this capability could add.
STRONG = {
    "website": "https://strong.test", "http_status": 200,
    "observations": [{"feature": f, "status": "present"} for f in FIXES],
}

#: No readable site at all.
NONE_YET = {"website": "", "http_status": 0, "observations": []}


@pytest.fixture(scope="module", autouse=True)
def schema():
    db.init_db()


# ============================================== the capability is registered

def test_the_offer_and_its_executor_agree(self=None) -> None:
    offer = BY_ID["offer-website"]
    assert offer.id in EXECUTORS, "an offer nothing can perform must not be sold"
    assert EXECUTORS[offer.id] is build_website


def test_the_offer_answers_opportunities_that_had_none() -> None:
    """`performance`, `broken` and `thin_content` were website problems with no
    capability behind them, so a customer saw them and could be told nothing."""
    for key in ("performance", "broken", "thin_content"):
        assert [o.id for o in offers_for_opportunity(key)] == ["offer-website"]


def test_it_does_not_claim_a_gap_another_offer_already_answers() -> None:
    """Two offers claiming the same gap is how a customer is sold one fix
    twice. The contact affordances belong to one-tap-contact."""
    website = BY_ID["offer-website"]
    one_tap = BY_ID["offer-one-tap-contact"]
    assert not (website.answers & one_tap.answers)
    for contact_feature in ("click_to_call", "whatsapp", "contact_form"):
        assert contact_feature not in FIXES


# ============================================== mode is derived, not chosen

def test_the_mode_is_derived_from_whether_a_site_could_be_read() -> None:
    assert mode_for(NONE_YET) is WebsiteMode.CREATE
    assert mode_for(FAILING) is WebsiteMode.MODIFY
    assert mode_for({"website": "https://x.test", "http_status": 500}) is WebsiteMode.CREATE


def test_a_caller_cannot_declare_the_mode() -> None:
    """Letting a caller say "create" is how a business with a working website
    gets a new one built over the top of it."""
    import inspect

    assert "mode" not in inspect.signature(build_website).parameters


# ====================================== a strong website is a finding

def test_a_strong_website_produces_no_artefact(self=None) -> None:
    """STRONG WEBSITE + LIMITED WEBSITE OPPORTUNITY, enforced where it cannot be
    argued with: there is nothing to approve, publish or bill for."""
    assert improvable(STRONG) == ()
    with pytest.raises(NothingToBuild, match="strong site is a finding"):
        build_website(business_name="Strong Co", research=STRONG, business=BUSINESS)


def test_a_strong_website_produces_no_roadmap_task() -> None:
    observations = STRONG["observations"] + [
        {"feature": f, "status": "present"} for f in
        ("click_to_call", "whatsapp", "contact_form", "canonical", "sitemap",
         "structured_data", "open_graph", "indexability", "image_alt_text")]
    readiness = assess(business_id="strong", observations=observations,
                       business_model="LOGISTICS")
    ranked = opp.for_host("strong.test", category="logistics",
                          absent=frozenset(), present=frozenset({"page_speed"}))
    recommendations = rec_service.propose(
        business_id="strong", tenant_id=TENANT, opportunities=ranked,
        business_model="LOGISTICS", plan="ADVANCED")
    roadmap = generate(business_id="strong", tenant_id=TENANT,
                       observations=observations, recommendations=recommendations,
                       business_model="LOGISTICS", readiness=readiness)
    website_tasks = [t for t in roadmap.tasks if t.capability_id
                     and "website" in t.task.title.lower()]
    assert website_tasks == [], website_tasks
    assert "technical_health" in roadmap.left_alone


def test_only_confirmed_absent_features_are_addressed() -> None:
    """Unverified is not a gap. Building against it manufactures a weakness."""
    unchecked = {"website": "https://x.test", "http_status": 200,
                 "observations": [{"feature": f, "status": "unverified"}
                                  for f in FIXES]}
    assert improvable(unchecked) == ()
    with pytest.raises(NothingToBuild):
        build_website(business_name="Unknown Co", research=unchecked, business=BUSINESS)


def test_what_the_site_already_does_is_left_alone() -> None:
    _files, provenance = build_website(business_name=BUSINESS.name,
                                       research=FAILING, business=BUSINESS)
    assert "viewport_meta" in provenance["left_alone"]
    assert "a layout that works on a phone" not in provenance["addresses"]
    assert set(provenance["addresses"]) == {FIXES[f] for f in
                                            ("page_speed", "broken_links",
                                             "thin_pages", "page_title", "h1")}


# ====================================== nothing on the page is invented

def test_there_is_no_fact_source_meaning_a_model_wrote_it() -> None:
    assert not hasattr(FactSource, "GENERATED")
    assert {s.value for s in FactSource} == {"operator", "customer",
                                             "business_record", "observed"}


def test_a_business_with_no_recorded_details_gets_a_page_without_them() -> None:
    """The tempting failure is not inventing an address — it is padding a thin
    page with confident copy that asserts nothing anyone supplied."""
    bare = Business(id="biz-bare", name="Bare Co", phone="", email="",
                    geography="", website="")
    files, provenance = build_website(business_name="Bare Co", research=NONE_YET,
                                      business=bare)
    page = files[DEFAULT_PATH]
    assert "Bare Co" in page
    assert set(provenance["not_published_for_want_of_a_source"]) == {
        "phone", "email", "location"}
    for invented in ("Call us today", "Contact us now", "Lorem", "+971 4 000",
                     "info@barecole", "Mon-Fri", "9am"):
        assert invented not in page


def test_service_names_come_from_pages_the_business_publishes() -> None:
    files, _provenance = build_website(business_name=BUSINESS.name,
                                       research=FAILING, business=BUSINESS)
    page = files[DEFAULT_PATH]
    assert "Freight forwarding" in page and "Customs clearance" in page
    # And nothing that was not published.
    assert "Warehousing" not in page


def test_a_site_with_no_business_name_is_refused() -> None:
    # `Business` will not hold an empty name, so the only way to reach this is
    # with no record at all — which is exactly the case worth refusing.
    with pytest.raises(ValidationError, match="must have a name"):
        Business(id="biz-x", name="", phone="", email="", geography="", website="")
    with pytest.raises(NothingToBuild, match="no business name"):
        build_website(business_name="   ", research=NONE_YET, business=None)


# ====================================== both modes produce a real bundle

def test_creating_a_site_where_there_is_none() -> None:
    files, provenance = build_website(business_name=BUSINESS.name,
                                      research=NONE_YET, business=BUSINESS)
    assert provenance["mode"] == WebsiteMode.CREATE.value
    assert DEFAULT_PATH in files and files[DEFAULT_PATH].strip()
    assert BUSINESS.phone in files[DEFAULT_PATH]
    assert provenance["facts"] >= 3


def test_modifying_a_site_that_exists() -> None:
    files, provenance = build_website(business_name=BUSINESS.name,
                                      research=FAILING, business=BUSINESS)
    assert provenance["mode"] == WebsiteMode.MODIFY.value
    assert provenance["addresses"], "a modification must say what it responds to"
    assert DEFAULT_PATH in files


def test_the_build_is_deterministic() -> None:
    """Content-addressed provenance depends on it: the same inputs must produce
    the same bundle, or an approved hash could never be published."""
    first, _ = build_website(business_name=BUSINESS.name, research=FAILING,
                             business=BUSINESS)
    second, _ = build_website(business_name=BUSINESS.name, research=FAILING,
                              business=BUSINESS)
    assert bundle_hash(first) == bundle_hash(second)


# ====================================== one hashing rule, two shapes

def test_a_single_document_is_a_bundle_with_one_entry() -> None:
    assert normalise("<html></html>") == {DEFAULT_PATH: "<html></html>"}
    assert bundle_hash("<html></html>") == bundle_hash({DEFAULT_PATH: "<html></html>"})
    assert primary({"about.html": "a", DEFAULT_PATH: "b"}) == DEFAULT_PATH


def test_a_renamed_file_is_a_different_bundle() -> None:
    assert bundle_hash({"index.html": "x"}) != bundle_hash({"home.html": "x"})


def test_an_empty_build_has_no_hash() -> None:
    assert bundle_hash({}) == "" and bundle_hash("") == ""


# ====================================== the whole lifecycle

@pytest.fixture
def wiring(tmp_path):
    registry = DeploymentTargetRegistry()
    root = tmp_path / "sites"
    root.mkdir()
    registry.register(TargetRegistration(
        target=LocalDirectoryTarget(root, base_url="http://localhost:8080",
                                    name="local")))
    store = ConnectionStore()
    connection = store.register(Connection(
        id="conn-sunrise", tenant_id=TENANT, target="local", reference=str(root)))
    return registry, store, connection, root


def _plan():
    """Research → opportunity → recommendation → roadmap → the website task."""
    observations = FAILING["observations"]
    ranked = opp.for_host("sunrise.test", category="logistics",
                          absent=frozenset({"page_speed", "broken_links",
                                            "thin_pages", "page_title", "h1"}),
                          present=frozenset({"viewport_meta", "contact_form"}))
    recommendations = rec_service.propose(
        business_id=BUSINESS.id, tenant_id=TENANT, opportunities=ranked,
        business_model="LOGISTICS", plan="ADVANCED")
    roadmap = generate(business_id=BUSINESS.id, tenant_id=TENANT,
                       observations=observations, recommendations=recommendations,
                       business_model="LOGISTICS")
    task = next(t for t in roadmap.tasks
                if t.executability is Executability.QEVIK_CAN_EXECUTE
                and t.capability_id)
    recommendation = next(r for r in recommendations if r.id == task.recommendation_id)
    return roadmap, task, recommendation.model_copy(
        update={"state": RecommendationState.ACCEPTED})


def test_the_website_reaches_the_roadmap_as_executable_work() -> None:
    roadmap, task, recommendation = _plan()
    assert recommendation.offer_id == "offer-website"
    assert task.executability is Executability.QEVIK_CAN_EXECUTE
    assert task.evidence, "the task must rest on what research confirmed"
    assert task.metric_key, "and name what would be watched"


def test_research_to_published_website(wiring) -> None:
    """Research → … → roadmap → approval → generation → QA → stage → artefact
    approval → publication → measurement hook."""
    registry, store, connection, root = wiring
    runtime = create_runtime()
    roadmap, task, recommendation = _plan()

    # --- the execution approval: should Qevik do this work? ---------------
    execution_approval = runtime.approval_service.approve(
        crossing.request_approval(task, recommendation=recommendation,
                                  approvals=runtime.approval_service,
                                  business_name=BUSINESS.name).id, actor="ayoub")
    facts = facts_for(roadmap, recommendation_state=RecommendationState.ACCEPTED,
                      completed_task_ids=frozenset(t.id for t in roadmap.customer_tasks),
                      customer_action_done=True)
    outcome = crossing.execute_task(
        task, recommendation=recommendation, approval=execution_approval,
        facts=facts, tenant=TENANT, research=FAILING, business_name=BUSINESS.name,
        repository=runtime.repository, business=BUSINESS)

    assert outcome.state is PublicationState.READY_TO_PUBLISH, outcome.qa
    asset = runtime.repository.get_asset(outcome.asset_ids[0])
    assert asset.metadata["built_from"]["mode"] == WebsiteMode.MODIFY.value
    assert asset.metadata["built_from"]["addresses"]
    assert asset.metadata["files"] == [DEFAULT_PATH]

    files, _ = build_website(business_name=BUSINESS.name, research=FAILING,
                             business=BUSINESS)
    assert bundle_hash(files) == asset.content_hash

    # --- stage: the real artefact on the real host, serving nobody --------
    destination = Destination(slug="sunrise",
                              url="http://localhost:8080/sunrise/")
    version = stage(target_name="local", registry=registry,
                    destination=destination, files=files)
    assert version.preview_url
    assert not (root / destination.slug / "current").exists(), \
        "staging must not make anything live"

    # --- the artefact approval: may this exact page go live? --------------
    request = publication_gate.request_artefact_approval(
        outcome=outcome, asset=asset, destination=destination, target="local",
        approvals=runtime.approval_service, business_name=BUSINESS.name,
        preview_url=version.preview_url)
    assert request.payload["preview_url"] == version.preview_url
    assert not publication_gate.check(
        outcome=outcome, asset=asset, target="local", destination=destination,
        registry=registry, connection=connection, connections=store,
        approval=request, tenant=TENANT, files=files), "pending must not publish"

    approval = runtime.approval_service.approve(request.id, actor="ayoub")
    record = publish(outcome=outcome, asset=asset, files=files, target_name="local",
                     destination=destination, registry=registry, connections=store,
                     connection=connection, approval=approval, tenant=TENANT,
                     roadmap_task_id=task.id,
                     execution_approval_id=execution_approval.id)

    assert record.status is PublicationStatus.PUBLISHED
    live = root / destination.slug / "current" / DEFAULT_PATH
    assert live.exists() and BUSINESS.name in live.read_text()

    # --- the measurement hook: an intervention, not a result --------------
    assert record.completed_at is not None
    baseline = measurement.open_baseline(
        business_id=BUSINESS.id, tenant_id=TENANT, metric_key=task.metric_key,
        value=None, source="analytics", roadmap_task_id=task.id)
    assert baseline.attribution is Attribution.UNKNOWN
    assert record.is_business_result is False
    assert not permits(Attribution.UNKNOWN, "Qevik increased their enquiries.")


def test_nothing_is_published_without_the_artefact_approval(wiring) -> None:
    registry, store, connection, root = wiring
    runtime = create_runtime()
    roadmap, task, recommendation = _plan()
    execution_approval = runtime.approval_service.approve(
        crossing.request_approval(task, recommendation=recommendation,
                                  approvals=runtime.approval_service,
                                  business_name=BUSINESS.name).id, actor="ayoub")
    facts = facts_for(roadmap, recommendation_state=RecommendationState.ACCEPTED,
                      completed_task_ids=frozenset(t.id for t in roadmap.customer_tasks),
                      customer_action_done=True)
    outcome = crossing.execute_task(
        task, recommendation=recommendation, approval=execution_approval,
        facts=facts, tenant=TENANT, research=FAILING, business_name=BUSINESS.name,
        repository=runtime.repository, business=BUSINESS)
    asset = runtime.repository.get_asset(outcome.asset_ids[0])
    files, _ = build_website(business_name=BUSINESS.name, research=FAILING,
                             business=BUSINESS)

    destination = Destination(slug="sunrise")
    # Staging is not publishing, and the execution approval does not authorise it.
    stage(target_name="local", registry=registry, destination=destination, files=files)
    reasons = publication_gate.unmet(
        outcome=outcome, asset=asset, target="local", destination=destination,
        registry=registry, connection=connection, connections=store,
        approval=None, tenant=TENANT, files=files)
    assert any("no artefact approval" in r for r in reasons), reasons
    assert not (root / destination.slug / "current").exists()


def test_a_website_cannot_be_published_by_another_tenant(wiring) -> None:
    _registry, store, _connection, _root = wiring
    roadmap, task, recommendation = _plan()
    store.register(Connection(id="conn-theirs", tenant_id=OTHER,
                              target="local", reference="/tmp/theirs"))
    assert store.get("conn-theirs", tenant=TENANT) is None
    assert task.tenant_id == TENANT
    assert not crossing.gate.check(task, recommendation=recommendation,
                                   approval=None, facts=facts_for(roadmap),
                                   tenant=OTHER)


# ====================================== QA sees the whole bundle

def test_the_qa_gates_read_every_page_not_just_the_index() -> None:
    """A gate reading one document of a bundle would pass a site whose third
    page says something forbidden."""
    from pathlib import Path

    from atlas_kernel.execution import service as execution

    source = Path(execution.__file__).read_text(encoding="utf-8")
    assert 'artefact="\\n".join(' in source
    assert "files[path] for path in sorted(files)" in source
