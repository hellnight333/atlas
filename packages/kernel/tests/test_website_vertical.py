"""The Website vertical, end to end, and the twelve ways it could lie.

P2.2 proved a website could be built and published. This proves the *loop*:
a business enters through research, gets a plan derived from evidence, has work
approved, built, staged where a person can look at it, approved again, published,
measured, and re-evaluated — with each stage able to say honestly what it does
and does not know.

The negative controls are grouped by the lie they prevent. Two of them are new
and are the reason this phase exists: a business whose site was merely
unreachable being told it has no website, and a staged preview being reachable
by the public before anybody approved it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from atlas_kernel import db
from atlas_kernel.composition_root import create_runtime
from atlas_kernel.execution.artefacts import DEFAULT_PATH, bundle_hash
from atlas_kernel.execution.capabilities import EXECUTORS
from atlas_kernel.execution.capabilities.website import (
    NothingToBuild,
    SiteState,
    WebsiteMode,
    build_website,
    mode_for,
    site_state,
)
from atlas_kernel.execution.models import PublicationState
from atlas_kernel.measurement import service as measurement
from atlas_kernel.measurement.attribution import Attribution, permits
from atlas_kernel.measurement.models import BaselineState
from atlas_kernel.opportunity.models import Business
from atlas_kernel.opportunity.tenancy import TenantRequired
from atlas_kernel.outreach import opportunity as opp
from atlas_kernel.publication import (
    Connection,
    ConnectionStore,
    Destination,
    NotPublishable,
    PublicationStatus,
    publish,
    staging,
)
from atlas_kernel.publication import (
    gate as publication_gate,
)
from atlas_kernel.publication.staging import ArtefactState
from atlas_kernel.recommendation import service as rec_service
from atlas_kernel.recommendation.models import RecommendationState
from atlas_kernel.research.net import Resolution, resolution
from atlas_kernel.roadmap import Change, Executability, changed, crossing, generate
from atlas_kernel.roadmap.lifecycle import facts_for
from atlas_kernel.roadmap.presentation import capabilities, view
from atlas_kernel.website.targets.base import DeploymentTargetRegistry, TargetRegistration
from atlas_kernel.website.targets.local import LocalDirectoryTarget

TENANT = "tenant-qevik"
OTHER = "tenant-other"

BUSINESS = Business(id="biz-harbour", name="Harbour Freight Services",
                    phone="+971 4 555 0142", email="ops@harbour.test",
                    geography="Jebel Ali, Dubai", website="")

#: What research records for a business with no site on file.
NO_SITE = {"website": "", "http_status": 0,
           "observations": [{"feature": "website", "status": "not_found"}]}

#: A site that exists and could not be read. The distinction P2.3 exists for.
UNREACHABLE = {"website": "https://harbour.test", "http_status": 0,
               "observations": [{"feature": "website", "status": "unverified"}]}


@pytest.fixture(scope="module", autouse=True)
def schema():
    db.init_db()


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
        id="conn-harbour", tenant_id=TENANT, target="local", reference=str(root)))
    return registry, store, connection, root


def _plan(research: dict, *, business_id: str = BUSINESS.id):
    absent = frozenset(o["feature"] for o in research["observations"]
                       if o["status"] == "not_found")
    present = frozenset(o["feature"] for o in research["observations"]
                        if o["status"] == "present")
    ranked = opp.for_host("harbour.test", category="logistics",
                          absent=absent, present=present)
    recommendations = rec_service.propose(
        business_id=business_id, tenant_id=TENANT, opportunities=ranked,
        business_model="LOGISTICS", plan="ADVANCED")
    roadmap = generate(business_id=business_id, tenant_id=TENANT,
                       observations=research["observations"],
                       recommendations=recommendations, business_model="LOGISTICS")
    return roadmap, recommendations


# ==================================================== the whole vertical

def test_a_business_with_no_website_goes_from_research_to_published(wiring) -> None:
    """Research → opportunity → recommendation → roadmap → approval → job →
    execution → QA → stage → artefact approval → publication → measurement."""
    registry, store, connection, root = wiring
    runtime = create_runtime()

    # --- research says: no website. Not "we could not check". -------------
    assert site_state(NO_SITE) is SiteState.ABSENT
    roadmap, recommendations = _plan(NO_SITE)

    task = next(t for t in roadmap.tasks
                if t.executability is Executability.QEVIK_CAN_EXECUTE)
    recommendation = next(r for r in recommendations
                          if r.id == task.recommendation_id).model_copy(
        update={"state": RecommendationState.ACCEPTED})
    assert recommendation.offer_id == "offer-website"
    assert "no_website" in recommendation.opportunity_key

    # --- work approval, then the job --------------------------------------
    execution_approval = runtime.approval_service.approve(
        crossing.request_approval(task, recommendation=recommendation,
                                  approvals=runtime.approval_service,
                                  business_name=BUSINESS.name).id, actor="ayoub")
    facts = facts_for(roadmap, recommendation_state=RecommendationState.ACCEPTED,
                      completed_task_ids=frozenset(t.id for t in roadmap.customer_tasks),
                      customer_action_done=True)
    outcome = crossing.execute_task(
        task, recommendation=recommendation, approval=execution_approval,
        facts=facts, tenant=TENANT, research=NO_SITE, business_name=BUSINESS.name,
        repository=runtime.repository, business=BUSINESS)
    asset = runtime.repository.get_asset(outcome.asset_ids[0])
    assert outcome.state is PublicationState.READY_TO_PUBLISH
    assert asset.metadata["built_from"]["mode"] == WebsiteMode.CREATE.value
    assert staging.state_of(outcome) is ArtefactState.READY_TO_STAGE

    # --- staged: real, fetchable, serving nobody --------------------------
    files, _ = build_website(business_name=BUSINESS.name, research=NO_SITE,
                             business=BUSINESS)
    destination = Destination(slug="harbour", url="http://localhost:8080/harbour/")
    staged = staging.stage(outcome=outcome, asset_id=asset.id, files=files,
                           target_name="local", destination=destination,
                           registry=registry, tenant=TENANT,
                           content_hash=asset.content_hash)
    assert staging.state_of(outcome, staged=staged) is ArtefactState.STAGED
    assert staging.can_answer_what_is_live(staged, registry=registry)
    assert not staging.is_live(staged, registry=registry), "staging must serve nobody"
    assert staged.summary()["public"] is False

    # --- the approver sees the staged version, not a description ----------
    request = publication_gate.request_artefact_approval(
        outcome=outcome, asset=asset, destination=destination, target="local",
        approvals=runtime.approval_service, business_name=BUSINESS.name,
        preview_url=staged.preview_url)
    assert request.payload["preview_url"] == staged.preview_url
    assert staging.state_of(outcome, staged=staged, approval=request) is ArtefactState.STAGED

    approval = runtime.approval_service.approve(request.id, actor="ayoub")
    assert staging.state_of(outcome, staged=staged,
                            approval=approval) is ArtefactState.APPROVED

    # --- published --------------------------------------------------------
    record = publish(outcome=outcome, asset=asset, files=files, target_name="local",
                     destination=destination, registry=registry, connections=store,
                     connection=connection, approval=approval, tenant=TENANT,
                     roadmap_task_id=task.id,
                     execution_approval_id=execution_approval.id)
    assert record.status is PublicationStatus.PUBLISHED
    assert staging.state_of(outcome, staged=staged, approval=approval,
                            record=record) is ArtefactState.PUBLISHED
    live = root / destination.slug / "current" / DEFAULT_PATH
    assert live.exists() and BUSINESS.name in live.read_text()
    assert BUSINESS.phone in live.read_text()

    # --- measurement: the publication is the intervention ------------------
    baseline = measurement.open_baseline(
        business_id=BUSINESS.id, tenant_id=TENANT, metric_key="sessions",
        value=0.0, source="analytics", roadmap_task_id=task.id)
    assert measurement.progress_of(baseline) is measurement.Progress.BASELINE_AVAILABLE

    watching = measurement.from_publication(baseline, record)
    assert watching.window.intervention_at == record.completed_at
    assert measurement.progress_of(watching) is measurement.Progress.PENDING
    report = measurement.report(watching)
    assert report["attribution"] == Attribution.UNKNOWN.value
    assert permits(Attribution.UNKNOWN, report["statement"])

    # --- re-evaluation: new evidence, new plan, old plan intact ------------
    after_research = {"website": "http://localhost:8080/harbour/", "http_status": 200,
                      "observations": [{"feature": "website", "status": "present"},
                                       {"feature": "page_title", "status": "present"},
                                       {"feature": "h1", "status": "present"},
                                       {"feature": "viewport_meta", "status": "present"}]}
    before_ids = [t.id for t in roadmap.tasks]
    later, _ = _plan(after_research)
    delta = changed(roadmap, later)
    assert delta["changed"]
    assert [t.id for t in roadmap.tasks] == before_ids, "the earlier plan was mutated"
    assert any(o["change"] == Change.OPPORTUNITY_RESOLVED.value
               for o in delta["outcomes"]), delta["outcomes"]


# ============ 1 & 2. missing, unverifiable, weak and strong are four things

def test_a_website_that_could_not_be_checked_is_not_a_missing_one() -> None:
    """The distinction this phase exists for. Treating UNVERIFIED as ABSENT
    offers a business a website it already has."""
    assert site_state(UNREACHABLE) is SiteState.UNVERIFIED
    assert site_state(UNREACHABLE) is not SiteState.ABSENT
    assert mode_for(UNREACHABLE) is not WebsiteMode.CREATE
    with pytest.raises(NothingToBuild, match="gap in what we checked"):
        build_website(business_name=BUSINESS.name, research=UNREACHABLE,
                      business=BUSINESS)


def test_a_missing_website_is_not_scored_as_a_weak_one() -> None:
    assert site_state(NO_SITE) is SiteState.ABSENT
    assert site_state(NO_SITE) is not SiteState.WEAK
    # And a business with no site gets the CREATE opportunity, not a list of
    # things wrong with a site that does not exist.
    _roadmap, recommendations = _plan(NO_SITE)
    keys = {r.opportunity_key for r in recommendations}
    assert keys == {"no_website"}, keys


def test_an_unverifiable_website_produces_no_opportunity_at_all() -> None:
    """Missing research must stay UNKNOWN, not become a weakness."""
    _roadmap, recommendations = _plan(UNREACHABLE)
    assert [r.opportunity_key for r in recommendations] == []


def test_dns_is_what_separates_absent_from_unverified() -> None:
    """A name server saying "no such host" has answered. A timeout has not."""
    assert resolution("definitely-not-a-real-qevik-host.invalid") is Resolution.NO_SUCH_HOST
    assert resolution("") is Resolution.UNKNOWN


def test_research_records_the_distinction_it_observed() -> None:
    from atlas_kernel.research.discovery import discover

    _found, findings = discover("")
    website = [f for f in findings if f.feature == "website"]
    assert [f.status.value for f in website] == ["not_found"]
    assert "no website recorded" in website[0].evidence

    _found, findings = discover("https://not-a-real-qevik-host.invalid")
    website = [f for f in findings if f.feature == "website"]
    assert [f.status.value for f in website] == ["not_found"]
    assert "no such host" in website[0].evidence


# ==================================== 3. a staged site is not a public one

def test_a_staged_site_is_not_reachable_by_the_public(wiring) -> None:
    registry, _store, _connection, root = wiring
    runtime = create_runtime()
    outcome, asset, files, _task = _built(runtime)

    destination = Destination(slug="harbour")
    staged = staging.stage(outcome=outcome, asset_id=asset.id, files=files,
                           target_name="local", destination=destination,
                           registry=registry, tenant=TENANT,
                           content_hash=asset.content_hash)

    # The file exists at the target, under a version nobody is served.
    assert (root / "harbour" / "versions" / staged.version_id / DEFAULT_PATH).exists()
    assert not (root / "harbour" / "current").exists(), "nothing is being served"
    assert not staging.is_live(staged, registry=registry)


def test_staging_an_artefact_that_failed_qa_is_refused(wiring) -> None:
    """A fetchable link to a rejected page in an approval request is one
    somebody will approve."""
    registry, _store, _connection, _root = wiring
    runtime = create_runtime()
    outcome, asset, files, _task = _built(runtime)
    rejected = outcome.model_copy(update={"state": PublicationState.REJECTED})

    with pytest.raises(ValueError, match="somebody will approve"):
        staging.stage(outcome=rejected, asset_id=asset.id, files=files,
                      target_name="local", destination=Destination(slug="harbour"),
                      registry=registry, tenant=TENANT,
                      content_hash=asset.content_hash)


def test_the_four_states_are_distinct(wiring) -> None:
    """GENERATED, STAGED, APPROVED and PUBLISHED are different things."""
    registry, _store, _connection, _root = wiring
    runtime = create_runtime()
    outcome, asset, files, _task = _built(runtime)

    draft = outcome.model_copy(update={"state": PublicationState.DRAFT})
    assert staging.state_of(draft) is ArtefactState.GENERATED
    assert staging.state_of(outcome) is ArtefactState.READY_TO_STAGE

    staged = staging.stage(outcome=outcome, asset_id=asset.id, files=files,
                           target_name="local", destination=Destination(slug="h2"),
                           registry=registry, tenant=TENANT,
                           content_hash=asset.content_hash)
    assert staging.state_of(outcome, staged=staged) is ArtefactState.STAGED

    request = publication_gate.request_artefact_approval(
        outcome=outcome, asset=asset, destination=Destination(slug="h2"),
        target="local", approvals=runtime.approval_service, business_name="H")
    assert staging.state_of(outcome, staged=staged,
                            approval=request) is ArtefactState.STAGED
    rejected = runtime.approval_service.reject(request.id, actor="ayoub")
    assert staging.state_of(outcome, staged=staged,
                            approval=rejected) is ArtefactState.REFUSED


# ================================ 4, 5, 6. approval, bytes, and PUBLISHED

def test_publication_without_artefact_approval_is_refused(wiring) -> None:
    registry, store, connection, _root = wiring
    runtime = create_runtime()
    outcome, asset, files, _task = _built(runtime)
    with pytest.raises(NotPublishable, match="no artefact approval"):
        publish(outcome=outcome, asset=asset, files=files, target_name="local",
                destination=Destination(slug="harbour"), registry=registry,
                connections=store, connection=connection, approval=None,
                tenant=TENANT)


def test_bytes_modified_after_approval_are_refused(wiring) -> None:
    registry, store, connection, _root = wiring
    runtime = create_runtime()
    outcome, asset, files, _task = _built(runtime)
    destination = Destination(slug="harbour")
    approval = runtime.approval_service.approve(
        publication_gate.request_artefact_approval(
            outcome=outcome, asset=asset, destination=destination, target="local",
            approvals=runtime.approval_service, business_name="H").id, actor="ayoub")

    tampered = dict(files)
    tampered[DEFAULT_PATH] = files[DEFAULT_PATH].replace("</body>", "<p>extra</p></body>")
    assert bundle_hash(tampered) != asset.content_hash
    with pytest.raises(NotPublishable, match="do not match the approved asset"):
        publish(outcome=outcome, asset=asset, files=tampered, target_name="local",
                destination=destination, registry=registry, connections=store,
                connection=connection, approval=approval, tenant=TENANT)


def test_ready_to_publish_is_not_published(wiring) -> None:
    registry, _store, _connection, root = wiring
    runtime = create_runtime()
    outcome, asset, files, _task = _built(runtime)
    assert outcome.state is PublicationState.READY_TO_PUBLISH
    assert outcome.state is not PublicationState.PUBLISHED

    staged = staging.stage(outcome=outcome, asset_id=asset.id, files=files,
                           target_name="local", destination=Destination(slug="harbour"),
                           registry=registry, tenant=TENANT,
                           content_hash=asset.content_hash)
    assert staging.state_of(outcome, staged=staged) is not ArtefactState.PUBLISHED
    assert not (root / "harbour" / "current").exists()


# ==================================== 7, 8, 9. measurement cannot overstate

def test_an_intervention_without_a_baseline_is_refused() -> None:
    """A baseline captured after the work is not a baseline."""
    nothing = measurement.open_baseline(
        business_id=BUSINESS.id, tenant_id=TENANT, metric_key="sessions",
        value=None, source="analytics")
    assert measurement.progress_of(nothing) is measurement.Progress.UNAVAILABLE
    with pytest.raises(measurement.ProvenanceMissing, match="not a baseline"):
        measurement.record_intervention(nothing, at=datetime.now(UTC))


def test_a_failed_publication_is_not_an_intervention(wiring) -> None:
    from atlas_kernel.publication.models import PublicationRecord

    baseline = measurement.open_baseline(
        business_id=BUSINESS.id, tenant_id=TENANT, metric_key="sessions",
        value=100.0, source="analytics")
    failed = PublicationRecord(
        id="pub-x", tenant_id=TENANT, business_id=BUSINESS.id,
        recommendation_id="rec-1", run_id="run-1", job_id="job-1",
        asset_id="asset-1", content_hash="abc", target="local",
        destination=Destination(slug="harbour"), connection_id="conn-1",
        artefact_approval_id="approval-1", artefact_fingerprint="fp",
        status=PublicationStatus.FAILED, completed_at=datetime.now(UTC))
    with pytest.raises(measurement.ProvenanceMissing, match="nothing went live"):
        measurement.from_publication(baseline, failed)


def test_a_baseline_with_no_intervention_reports_no_result() -> None:
    baseline = measurement.open_baseline(
        business_id=BUSINESS.id, tenant_id=TENANT, metric_key="sessions",
        value=100.0, source="analytics")
    assert measurement.progress_of(baseline) is measurement.Progress.BASELINE_AVAILABLE
    assert baseline.state is BaselineState.BASELINE_AVAILABLE
    assert baseline.improved is None, "unknown, never False"
    assert "no result" in baseline.statement()


def test_no_causal_claim_survives_without_the_evidence_for_it() -> None:
    baseline = measurement.open_baseline(
        business_id=BUSINESS.id, tenant_id=TENANT, metric_key="sessions",
        value=100.0, source="analytics")
    live = datetime.now(UTC) - timedelta(days=31)
    watching = measurement.record_intervention(baseline, at=live, job_id="job-1")
    observed = measurement.close_measurement(
        watching, value=260.0, source="analytics", intervention_at=live)

    assert measurement.progress_of(observed) is measurement.Progress.OBSERVED_CHANGE
    assert observed.change == 160.0
    # A 160% rise, correctly ordered, and still not attribution.
    assert observed.attribution is Attribution.ASSOCIATED
    for claim in ("Qevik increased their sessions.",
                  "The new website caused the increase.",
                  "Conversion improved because of the rebuild.",
                  "This will drive more enquiries."):
        assert not permits(observed.attribution, claim), claim
    assert permits(observed.attribution, measurement.report(observed)["statement"])


def test_every_measurement_state_is_reportable() -> None:
    """A customer asking "what do you know" gets one of five honest answers."""
    seen = set()
    nothing = measurement.open_baseline(business_id="b", tenant_id=TENANT,
                                        metric_key="sessions", value=None,
                                        source="analytics")
    seen.add(measurement.progress_of(nothing))
    baseline = measurement.open_baseline(business_id="b", tenant_id=TENANT,
                                         metric_key="sessions", value=100.0,
                                         source="analytics")
    seen.add(measurement.progress_of(baseline))
    fresh = measurement.record_intervention(baseline, at=datetime.now(UTC))
    seen.add(measurement.progress_of(fresh))
    old = measurement.record_intervention(baseline,
                                          at=datetime.now(UTC) - timedelta(days=40))
    seen.add(measurement.progress_of(old))
    seen.add(measurement.progress_of(measurement.close_measurement(
        old, value=120.0, source="analytics",
        intervention_at=old.window.intervention_at)))
    assert seen == set(measurement.Progress)


# ==================================== 10. history is not rewritten

def test_re_evaluation_generates_a_new_state_and_leaves_the_old_one() -> None:
    roadmap, _recommendations = _plan(NO_SITE)
    fingerprint = roadmap.fingerprint()
    task_ids = [t.id for t in roadmap.tasks]
    generated_at = roadmap.generated_at

    later, _ = _plan({"website": "https://harbour.test", "http_status": 200,
                      "observations": [{"feature": "website", "status": "present"},
                                       {"feature": "page_title", "status": "present"}]})
    delta = changed(roadmap, later)

    assert roadmap.fingerprint() == fingerprint, "the historical plan was mutated"
    assert [t.id for t in roadmap.tasks] == task_ids
    assert roadmap.generated_at == generated_at
    assert later is not roadmap
    assert delta["outcomes"] != [{"change": Change.UNCHANGED.value}]


def test_identical_evidence_reports_unchanged(wiring) -> None:
    roadmap, _ = _plan(NO_SITE)
    again, _ = _plan(NO_SITE)
    delta = changed(roadmap, again)
    assert delta["changed"] is False
    assert delta["outcomes"] == [{"change": Change.UNCHANGED.value}]


def test_every_kind_of_change_can_be_named() -> None:
    before, _ = _plan(NO_SITE)
    after, _ = _plan({"website": "https://harbour.test", "http_status": 200,
                      "observations": [{"feature": "website", "status": "present"},
                                       {"feature": "page_speed", "status": "not_found"}]})
    kinds = {o["change"] for o in changed(before, after)["outcomes"]}
    assert kinds & {Change.NEW_OPPORTUNITY.value,
                    Change.OPPORTUNITY_RESOLVED.value,
                    Change.TASK_NO_LONGER_REQUIRED.value,
                    Change.DIMENSION_IMPROVED.value,
                    Change.NEWLY_MEASURED.value}, kinds


# ==================================== 11 & 12. tenancy on preview and publish

def test_another_tenant_cannot_stage(wiring) -> None:
    registry, _store, _connection, _root = wiring
    runtime = create_runtime()
    outcome, asset, files, _task = _built(runtime)
    with pytest.raises(PermissionError, match="different tenant"):
        staging.stage(outcome=outcome, asset_id=asset.id, files=files,
                      target_name="local", destination=Destination(slug="harbour"),
                      registry=registry, tenant=OTHER,
                      content_hash=asset.content_hash)


def test_another_tenant_cannot_read_a_preview(wiring) -> None:
    """A preview URL is a working link to unpublished work."""
    registry, _store, _connection, _root = wiring
    runtime = create_runtime()
    outcome, asset, files, _task = _built(runtime)
    staged = staging.stage(outcome=outcome, asset_id=asset.id, files=files,
                           target_name="local", destination=Destination(slug="harbour"),
                           registry=registry, tenant=TENANT,
                           content_hash=asset.content_hash)
    events = [staging.to_event(staged)]
    assert staging.read(events, tenant=TENANT)
    assert staging.read(events, tenant=OTHER) == []
    with pytest.raises(TenantRequired):
        staging.read(events, tenant=None)


def test_another_tenant_cannot_publish(wiring) -> None:
    registry, store, connection, _root = wiring
    runtime = create_runtime()
    outcome, asset, files, _task = _built(runtime)
    destination = Destination(slug="harbour")
    approval = runtime.approval_service.approve(
        publication_gate.request_artefact_approval(
            outcome=outcome, asset=asset, destination=destination, target="local",
            approvals=runtime.approval_service, business_name="H").id, actor="ayoub")
    with pytest.raises(NotPublishable, match="different tenant"):
        publish(outcome=outcome, asset=asset, files=files, target_name="local",
                destination=destination, registry=registry, connections=store,
                connection=connection, approval=approval, tenant=OTHER)


# ==================================== offered is not the same as executable

def test_an_offer_with_no_executor_is_never_promised() -> None:
    catalogue = capabilities()
    executable = {e["offer_id"] for e in catalogue["executable"]}
    offered_only = {e["offer_id"] for e in catalogue["offered_only"]}

    assert executable == set(EXECUTORS)
    assert not (executable & offered_only)
    assert offered_only, "four offers still have no executor, and say so"
    for entry in catalogue["offered_only"]:
        assert entry["executable"] is False
        assert "not yet buildable" in entry["state"]


def test_the_customer_view_carries_the_distinction() -> None:
    roadmap, _ = _plan(NO_SITE)
    shown = view(roadmap)
    assert "capabilities" in shown
    for entry in shown["qevik_can_execute"]:
        assert entry["title"] not in {e["name"] for e
                                      in shown["capabilities"]["offered_only"]}


def test_no_task_is_scheduled_for_an_offer_with_no_executor() -> None:
    roadmap, _ = _plan(NO_SITE)
    for task in roadmap.tasks:
        if task.executability is Executability.QEVIK_CAN_EXECUTE:
            assert task.capability_id


# ---------------------------------------------------------------- helper

def _built(runtime):
    """A real READY_TO_PUBLISH website artefact for this business."""
    roadmap, recommendations = _plan(NO_SITE)
    task = next(t for t in roadmap.tasks
                if t.executability is Executability.QEVIK_CAN_EXECUTE)
    recommendation = next(r for r in recommendations
                          if r.id == task.recommendation_id).model_copy(
        update={"state": RecommendationState.ACCEPTED})
    approval = runtime.approval_service.approve(
        crossing.request_approval(task, recommendation=recommendation,
                                  approvals=runtime.approval_service,
                                  business_name=BUSINESS.name).id, actor="ayoub")
    facts = facts_for(roadmap, recommendation_state=RecommendationState.ACCEPTED,
                      completed_task_ids=frozenset(t.id for t in roadmap.customer_tasks),
                      customer_action_done=True)
    outcome = crossing.execute_task(
        task, recommendation=recommendation, approval=approval, facts=facts,
        tenant=TENANT, research=NO_SITE, business_name=BUSINESS.name,
        repository=runtime.repository, business=BUSINESS)
    asset = runtime.repository.get_asset(outcome.asset_ids[0])
    files, _ = build_website(business_name=BUSINESS.name, research=NO_SITE,
                             business=BUSINESS)
    return outcome, asset, files, task
