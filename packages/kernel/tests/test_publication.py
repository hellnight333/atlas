"""Publication, tested on everything that must never reach the outside world.

This is the first place in Qevik where a refusal failing means a stranger sees
something. Every other boundary so far has been internal — a job that should not
have run can be deleted. A page that should not have been published has been
read by the time anybody notices.

So the shape of this file is nine conditions, each removed in turn, each
expected to stop the publication on its own. Plus the two confusions that would
survive all nine being correct: a failed upload recorded as PUBLISHED, and a
successful one read as a business result.

The approval service is the real one. A hand-built `ApprovalRequest` would prove
the guards and prove nothing about whether this reuses the existing approval
architecture rather than having grown a third one beside it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from atlas_kernel import db
from atlas_kernel.approval.models import ApprovalState
from atlas_kernel.composition_root import create_runtime
from atlas_kernel.execution.artefacts import bundle_hash
from atlas_kernel.execution.capabilities.portfolio import build_portfolio_index
from atlas_kernel.execution.models import PublicationState, QAResult, QAVerdict
from atlas_kernel.measurement.attribution import Attribution, permits
from atlas_kernel.outreach import opportunity as opp
from atlas_kernel.publication import (
    Connection,
    ConnectionKind,
    ConnectionNotFound,
    ConnectionStore,
    CredentialUnavailable,
    Destination,
    NotPublishable,
    PublicationRecord,
    PublicationStatus,
    SecretLeak,
    gate,
    publish,
    published_fingerprints,
    read,
    to_event,
)
from atlas_kernel.recommendation import service as rec_service
from atlas_kernel.recommendation.models import RecommendationState
from atlas_kernel.roadmap import Executability, crossing, generate
from atlas_kernel.roadmap.lifecycle import facts_for
from atlas_kernel.website.targets.base import (
    DeploymentError,
    DeploymentTargetRegistry,
    TargetRegistration,
)
from atlas_kernel.website.targets.local import LocalDirectoryTarget

TENANT = "tenant-qevik"
OTHER = "tenant-other"
BUSINESS = "AHS Catering & Events"

RESEARCH = {"facts": {"cms": {"pages": 60, "posts": 4, "media_total": 501,
    "image_page_list": [
        {"slug": "winter-wonderland", "title": "Winter wonderland",
         "url": "https://ahscatering.com/winter-wonderland/", "images": 7},
        {"slug": "nestle", "title": "Nestle",
         "url": "https://ahscatering.com/nestle/", "images": 6},
        {"slug": "porsche", "title": "Porsche",
         "url": "https://ahscatering.com/porsche/", "images": 3}]},
    "seo": {"orphan_count": 32}}}

FEATURES = [("https", "present"), ("page_speed", "present"),
            ("broken_links", "present"), ("click_to_call", "not_found"),
            ("whatsapp", "not_found"), ("contact_form", "present"),
            ("arabic", "not_found"), ("hreflang", "not_found"),
            ("social_proof", "present"), ("portfolio_depth", "present"),
            ("orphan_pages", "not_found"), ("page_title", "present"),
            ("blog", "present")]


@pytest.fixture(scope="module", autouse=True)
def schema():
    db.init_db()


@pytest.fixture(scope="module")
def executed():
    """A real READY_TO_PUBLISH artefact, produced through the P1.6 path."""
    runtime = create_runtime()
    observations = [{"feature": f, "status": s} for f, s in FEATURES]
    ranked = opp.for_host("ahscatering.com", category="food",
                          absent=frozenset({"arabic", "click_to_call", "orphan_pages"}),
                          present=frozenset({"portfolio_depth", "social_proof", "blog"}))
    recommendations = rec_service.propose(
        business_id="ahs", tenant_id=TENANT, opportunities=ranked,
        business_model="CATERING", plan="ADVANCED")
    roadmap = generate(business_id="ahs", tenant_id=TENANT, observations=observations,
                       recommendations=recommendations, business_model="CATERING")
    task = next(t for t in roadmap.tasks
                if t.executability is Executability.QEVIK_CAN_EXECUTE)
    recommendation = next(r for r in recommendations
                          if r.id == task.recommendation_id).model_copy(
        update={"state": RecommendationState.ACCEPTED})

    approval = runtime.approval_service.approve(
        crossing.request_approval(task, recommendation=recommendation,
                                  approvals=runtime.approval_service,
                                  business_name=BUSINESS).id, actor="ayoub")
    facts = facts_for(roadmap, recommendation_state=RecommendationState.ACCEPTED,
                      completed_task_ids=frozenset(t.id for t in roadmap.customer_tasks),
                      customer_action_done=True)
    outcome = crossing.execute_task(
        task, recommendation=recommendation, approval=approval, facts=facts,
        tenant=TENANT, research=RESEARCH, business_name=BUSINESS,
        repository=runtime.repository)
    asset = runtime.repository.get_asset(outcome.asset_ids[0])
    artefact, _ = build_portfolio_index(business_name=BUSINESS, research=RESEARCH,
                                        strengths=recommendation.strengths)
    return outcome, asset, {"index.html": artefact}, approval.id


@pytest.fixture
def wiring(tmp_path):
    """A registered local target and a tenant-owned connection to it."""
    registry = DeploymentTargetRegistry()
    root = tmp_path / "sites"
    root.mkdir()
    registry.register(TargetRegistration(
        target=LocalDirectoryTarget(root, base_url="http://localhost:8080",
                                    name="local")))
    store = ConnectionStore()
    connection = store.register(Connection(
        id="conn-ahs", tenant_id=TENANT, target="local", reference=str(root),
        label="Qevik sites root"))
    return registry, store, connection, root


DESTINATION = Destination(slug="ahs-portfolio",
                          url="http://localhost:8080/ahs-portfolio/")


def _approved(outcome, asset, runtime, *, destination=DESTINATION, target="local"):
    request = gate.request_artefact_approval(
        outcome=outcome, asset=asset, destination=destination, target=target,
        approvals=runtime.approval_service, business_name=BUSINESS)
    return runtime.approval_service.approve(request.id, actor="ayoub")


def _conditions(executed, wiring, **overrides):
    outcome, asset, files, _ = executed
    registry, store, connection, _root = wiring
    base = dict(outcome=outcome, asset=asset, target="local",
                destination=DESTINATION, registry=registry, connection=connection,
                connections=store, approval=None, tenant=TENANT, files=files)
    base.update(overrides)
    return base


# ================================================= the whole crossing

def test_ready_to_publish_becomes_published_once_and_traceably(executed, wiring) -> None:
    """READY_TO_PUBLISH → approve artefact → publish → PUBLISHED → record."""
    outcome, asset, files, execution_approval = executed
    registry, store, connection, root = wiring
    runtime = create_runtime()

    assert outcome.state is PublicationState.READY_TO_PUBLISH
    approval = _approved(outcome, asset, runtime)

    record = publish(outcome=outcome, asset=asset, files=files, target_name="local",
                     destination=DESTINATION, registry=registry, connections=store,
                     connection=connection, approval=approval, tenant=TENANT,
                     execution_approval_id=execution_approval)

    assert record.status is PublicationStatus.PUBLISHED
    assert record.published and record.external_id and record.external_url
    live = root / DESTINATION.slug / "current" / "index.html"
    assert live.exists(), "the artefact is actually on disk and served"
    # Hashed as a bundle, by the same function execution used. A capability may
    # produce one document or a whole site, and a single document is a bundle
    # with one entry — one hashing rule, so the gate and the executor cannot
    # disagree about what was approved.
    assert bundle_hash({"index.html": live.read_text()}) == asset.content_hash


def test_the_record_carries_every_link_in_the_chain(executed, wiring) -> None:
    outcome, asset, files, execution_approval = executed
    registry, store, connection, _root = wiring
    runtime = create_runtime()
    record = publish(outcome=outcome, asset=asset, files=files, target_name="local",
                     destination=DESTINATION, registry=registry, connections=store,
                     connection=connection, approval=_approved(outcome, asset, runtime),
                     tenant=TENANT, roadmap_task_id="task-05",
                     execution_approval_id=execution_approval)

    for link in ("tenant_id", "business_id", "recommendation_id", "roadmap_task_id",
                 "run_id", "job_id", "asset_id", "content_hash", "target",
                 "connection_id", "execution_approval_id", "artefact_approval_id",
                 "artefact_fingerprint", "status", "external_id", "attempted_at",
                 "completed_at"):
        assert record.summary().get(link), f"the record is missing {link}"
    assert record.summary()["destination"]["slug"] == DESTINATION.slug


def test_a_record_is_immutable(executed, wiring) -> None:
    outcome, asset, files, _ = executed
    registry, store, connection, _root = wiring
    runtime = create_runtime()
    record = publish(outcome=outcome, asset=asset, files=files, target_name="local",
                     destination=DESTINATION, registry=registry, connections=store,
                     connection=connection, approval=_approved(outcome, asset, runtime),
                     tenant=TENANT)
    with pytest.raises(ValidationError):
        record.status = PublicationStatus.FAILED


# ============================ 1. the work approval is not the artefact approval

def test_publishing_without_the_artefact_approval_is_refused(executed, wiring) -> None:
    """The P1.6 approval authorised building it. It does not authorise sending
    it anywhere, and the two decisions must stay separate."""
    reasons = gate.unmet(**_conditions(executed, wiring, approval=None))
    assert any("no artefact approval" in r for r in reasons), reasons


def test_the_recommendation_approval_cannot_stand_in_for_it(executed, wiring) -> None:
    """A P1.6 approval object is a real ApprovalRequest. It must still fail,
    because it carries no artefact fingerprint."""
    outcome, asset, _files, _ = executed
    runtime = create_runtime()
    roadmap_approval = runtime.approval_service.get(executed[3])
    assert roadmap_approval is not None and roadmap_approval.state is ApprovalState.APPROVED
    reasons = gate.unmet(**_conditions(executed, wiring, approval=roadmap_approval))
    assert any("records no artefact fingerprint" in r for r in reasons), reasons


def test_a_pending_or_rejected_artefact_approval_does_not_publish(executed, wiring) -> None:
    outcome, asset, _files, _ = executed
    runtime = create_runtime()
    pending = gate.request_artefact_approval(
        outcome=outcome, asset=asset, destination=DESTINATION, target="local",
        approvals=runtime.approval_service, business_name=BUSINESS)
    assert any("is pending" in r for r in
               gate.unmet(**_conditions(executed, wiring, approval=pending)))

    rejected = runtime.approval_service.reject(pending.id, actor="ayoub")
    assert any("is rejected" in r for r in
               gate.unmet(**_conditions(executed, wiring, approval=rejected)))


def test_the_two_approvals_ask_different_questions(executed) -> None:
    outcome, asset, _files, execution_approval_id = executed
    runtime = create_runtime()
    artefact = gate.request_artefact_approval(
        outcome=outcome, asset=asset, destination=DESTINATION, target="local",
        approvals=runtime.approval_service, business_name=BUSINESS)
    execution = runtime.approval_service.get(execution_approval_id)

    # Different action names, so a policy can require different approvers.
    assert artefact.action != execution.action
    # The execution approval says in words that it does not publish; the
    # artefact one says in words that it does. A reviewer holding two requests
    # for the same piece of work can tell which question they are answering.
    assert execution.payload["publishes"] is False
    assert "does not publish" in execution.payload["note"]
    assert "makes the artefact live" in artefact.payload["note"]
    # And only the artefact approval names a destination and a version.
    assert "destination" not in execution.payload
    assert artefact.payload["destination"] == DESTINATION.slug
    assert artefact.payload["content_hash"] == asset.content_hash
    assert artefact.asset_id == asset.id and artefact.job_id == outcome.job_id


def test_approving_one_artefact_does_not_approve_another(executed, wiring) -> None:
    outcome, asset, _files, _ = executed
    runtime = create_runtime()
    approval = _approved(outcome, asset, runtime)

    elsewhere = Destination(slug="somebody-elses-site")
    reasons = gate.unmet(**_conditions(executed, wiring, approval=approval,
                                       destination=elsewhere))
    assert any("changed after approval" in r for r in reasons), reasons


def test_the_bytes_published_must_be_the_bytes_approved(executed, wiring) -> None:
    """The fingerprint covers the asset's hash; the files are a separate
    argument, and without this check nothing compares them."""
    outcome, asset, _files, _ = executed
    runtime = create_runtime()
    reasons = gate.unmet(**_conditions(
        executed, wiring, approval=_approved(outcome, asset, runtime),
        files={"index.html": "<html>something else entirely</html>"}))
    assert any("do not match the approved asset" in r for r in reasons), reasons


# ================================================= 2. QA and state

def test_publishing_without_qa_is_refused(executed, wiring) -> None:
    outcome, asset, _files, _ = executed
    runtime = create_runtime()
    approval = _approved(outcome, asset, runtime)

    no_qa = outcome.model_copy(update={"qa": ()})
    assert any("no QA gates were run" in r for r in
               gate.unmet(**_conditions(executed, wiring, outcome=no_qa,
                                        approval=approval)))

    failed = outcome.model_copy(update={"qa": (
        QAResult(gate="honesty", verdict=QAVerdict.FAIL, detail="claims too much"),)})
    assert any("QA did not pass" in r for r in
               gate.unmet(**_conditions(executed, wiring, outcome=failed,
                                        approval=approval)))


def test_an_unrun_gate_blocks_exactly_as_a_failed_one_does(executed, wiring) -> None:
    outcome, asset, _files, _ = executed
    runtime = create_runtime()
    not_run = outcome.model_copy(update={"qa": (
        QAResult(gate="browser", verdict=QAVerdict.NOT_RUN),)})
    assert any("QA did not pass" in r for r in
               gate.unmet(**_conditions(executed, wiring, outcome=not_run,
                                        approval=_approved(outcome, asset, runtime))))


def test_publishing_before_ready_to_publish_is_refused(executed, wiring) -> None:
    outcome, asset, _files, _ = executed
    runtime = create_runtime()
    approval = _approved(outcome, asset, runtime)
    for state in (PublicationState.DRAFT, PublicationState.REJECTED):
        early = outcome.model_copy(update={"state": state})
        reasons = gate.unmet(**_conditions(executed, wiring, outcome=early,
                                           approval=approval))
        assert any("not READY_TO_PUBLISH" in r for r in reasons), (state, reasons)


# ================================================= 3. provenance

def test_an_asset_from_another_job_is_refused(executed, wiring) -> None:
    outcome, asset, _files, _ = executed
    runtime = create_runtime()
    stranger = asset.model_copy(update={"id": "asset-from-somewhere-else"})
    reasons = gate.unmet(**_conditions(executed, wiring, asset=stranger,
                                       approval=_approved(outcome, asset, runtime)))
    assert any("was not produced by job" in r for r in reasons), reasons


def test_an_asset_with_missing_provenance_is_refused(executed, wiring) -> None:
    outcome, asset, _files, _ = executed
    runtime = create_runtime()
    approval = _approved(outcome, asset, runtime)
    for missing in ("recommendation_id", "business_id", "tenant_id"):
        stripped = dict(asset.metadata)
        stripped.pop(missing, None)
        blinded = asset.model_copy(update={"metadata": stripped})
        reasons = gate.unmet(**_conditions(executed, wiring, asset=blinded,
                                           approval=approval))
        assert any(missing in r for r in reasons), (missing, reasons)


def test_an_execution_with_no_recommendation_or_job_is_refused(executed, wiring) -> None:
    outcome, asset, _files, _ = executed
    runtime = create_runtime()
    approval = _approved(outcome, asset, runtime)
    orphan = outcome.model_copy(update={"recommendation_id": "", "job_id": ""})
    reasons = gate.unmet(**_conditions(executed, wiring, outcome=orphan,
                                       approval=approval))
    assert any("no recommendation" in r for r in reasons), reasons
    assert any("no job or run" in r for r in reasons), reasons


# ================================================= 4. targets and connections

def test_an_unsupported_target_is_refused(executed, wiring) -> None:
    outcome, asset, _files, _ = executed
    runtime = create_runtime()
    reasons = gate.unmet(**_conditions(
        executed, wiring, target="youtube",
        approval=_approved(outcome, asset, runtime, target="youtube")))
    assert any("not registered" in r for r in reasons), reasons


def test_a_missing_connection_is_refused(executed, wiring) -> None:
    outcome, asset, _files, _ = executed
    runtime = create_runtime()
    reasons = gate.unmet(**_conditions(executed, wiring, connection=None,
                                       approval=_approved(outcome, asset, runtime)))
    assert any("no connection to 'local'" in r for r in reasons), reasons


def test_an_unresolvable_credential_is_refused_before_anything_is_attempted(
        executed, wiring) -> None:
    outcome, asset, _files, _ = executed
    _registry, store, _connection, _root = wiring
    runtime = create_runtime()
    token = store.register(Connection(
        id="conn-token", tenant_id=TENANT, target="local",
        kind=ConnectionKind.API_TOKEN, reference="QEVIK_DEFINITELY_NOT_SET"))
    reasons = gate.unmet(**_conditions(executed, wiring, connection=token,
                                       approval=_approved(outcome, asset, runtime)))
    assert any("could not be resolved" in r for r in reasons), reasons


def test_a_connection_for_a_different_target_is_refused(executed, wiring) -> None:
    outcome, asset, _files, _ = executed
    _registry, store, _connection, _root = wiring
    runtime = create_runtime()
    elsewhere = store.register(Connection(
        id="conn-elsewhere", tenant_id=TENANT, target="cloudflare",
        reference="/tmp/whatever"))
    reasons = gate.unmet(**_conditions(executed, wiring, connection=elsewhere,
                                       approval=_approved(outcome, asset, runtime)))
    assert any("is for 'cloudflare'" in r for r in reasons), reasons


# ================================================= 5. tenancy

def test_another_tenants_credential_cannot_be_used(executed, wiring) -> None:
    outcome, asset, _files, _ = executed
    _registry, store, _connection, _root = wiring
    runtime = create_runtime()
    theirs = store.register(Connection(
        id="conn-theirs", tenant_id=OTHER, target="local", reference="/tmp/theirs"))
    reasons = gate.unmet(**_conditions(executed, wiring, connection=theirs,
                                       approval=_approved(outcome, asset, runtime)))
    assert any("belongs to a different tenant" in r for r in reasons), reasons


def test_another_tenants_credential_is_invisible_and_unresolvable(wiring) -> None:
    _registry, store, _connection, _root = wiring
    theirs = store.register(Connection(
        id="conn-theirs", tenant_id=OTHER, target="local", reference="/tmp/theirs"))
    assert store.get("conn-theirs", tenant=TENANT) is None
    assert store.for_target("local", tenant=TENANT).tenant_id == TENANT
    with pytest.raises(ConnectionNotFound):
        store.resolve(theirs, tenant=TENANT)


def test_publishing_as_the_wrong_tenant_is_refused(executed, wiring) -> None:
    outcome, asset, files, _ = executed
    registry, store, connection, _root = wiring
    runtime = create_runtime()
    approval = _approved(outcome, asset, runtime)
    with pytest.raises(NotPublishable, match="different tenant"):
        publish(outcome=outcome, asset=asset, files=files, target_name="local",
                destination=DESTINATION, registry=registry, connections=store,
                connection=connection, approval=approval, tenant=OTHER)


def test_a_publication_record_is_readable_only_by_its_own_tenant(executed, wiring) -> None:
    outcome, asset, files, _ = executed
    registry, store, connection, _root = wiring
    runtime = create_runtime()
    record = publish(outcome=outcome, asset=asset, files=files, target_name="local",
                     destination=DESTINATION, registry=registry, connections=store,
                     connection=connection, approval=_approved(outcome, asset, runtime),
                     tenant=TENANT)
    events = [to_event(record)]
    assert read(events, tenant=TENANT)
    assert read(events, tenant=OTHER) == []


# ================================================= 6. credentials never leak

def test_a_connection_refuses_to_hold_a_credential() -> None:
    for reference in ("sk-live-abcdef123456", "ya29.a0AfH6", "ghp_deadbeef",
                      "-----BEGIN PRIVATE KEY-----", "xoxb-123", "AKIAIOSFODNN7"):
        with pytest.raises(SecretLeak, match="looks like a credential"):
            Connection(id="c", tenant_id=TENANT, target="local", reference=reference)


def test_a_connection_with_no_tenant_is_refused() -> None:
    with pytest.raises(SecretLeak, match="belongs to nobody"):
        Connection(id="c", tenant_id="", target="local", reference="/tmp/x")


def test_no_credential_reaches_the_event_or_the_record(executed, wiring, monkeypatch) -> None:
    outcome, asset, files, _ = executed
    registry, store, _connection, root = wiring
    runtime = create_runtime()
    secret = "super-secret-token-value-nobody-should-see"
    monkeypatch.setenv("QEVIK_TEST_PUBLISH_TOKEN", secret)
    # A credentialed connection whose *reference* is safe and whose resolved
    # value is not. The local target ignores it; what matters is where the
    # resolved value ends up, which must be nowhere.
    connection = store.register(Connection(
        id="conn-token-ahs", tenant_id=TENANT, target="local",
        kind=ConnectionKind.API_TOKEN, reference="QEVIK_TEST_PUBLISH_TOKEN"))
    assert store.resolve(connection, tenant=TENANT) == secret

    record = publish(outcome=outcome, asset=asset, files=files, target_name="local",
                     destination=DESTINATION, registry=registry, connections=store,
                     connection=connection, approval=_approved(outcome, asset, runtime),
                     tenant=TENANT)
    blob = repr(record.model_dump()) + repr(to_event(record).detail) + repr(record.summary())
    assert secret not in blob, "the resolved credential reached a record"
    assert record.connection_id == "conn-token-ahs", "the id identifies it"
    # Not even the reference. The record names the connection, and anything
    # wanting the reference has to go through the tenant-scoped store to get it.
    assert "QEVIK_TEST_PUBLISH_TOKEN" not in blob


def test_the_credential_is_never_in_an_error_message(wiring, monkeypatch) -> None:
    _registry, store, _connection, _root = wiring
    connection = Connection(id="c", tenant_id=TENANT, target="local",
                            kind=ConnectionKind.API_TOKEN, reference="QEVIK_ABSENT_VAR")
    with pytest.raises(CredentialUnavailable) as raised:
        store.resolve(connection, tenant=TENANT)
    assert "QEVIK_ABSENT_VAR" in str(raised.value), "the reference is fine to name"
    monkeypatch.setenv("QEVIK_ABSENT_VAR", "the-secret")
    assert "the-secret" not in str(raised.value)


# ================================================= 7. failure is not success

def test_a_failed_publication_never_becomes_published(executed, wiring) -> None:
    outcome, asset, files, _ = executed
    _registry, store, connection, _root = wiring
    runtime = create_runtime()

    class BrokenHost:
        name = "local"

        def publish(self, site_slug, files):
            raise DeploymentError("the host rejected the upload")

        def promote(self, site_slug, version_id):
            raise AssertionError("promote must not be reached after a failed publish")

    registry = DeploymentTargetRegistry()
    registry.register(TargetRegistration(target=BrokenHost()))

    record = publish(outcome=outcome, asset=asset, files=files, target_name="local",
                     destination=DESTINATION, registry=registry, connections=store,
                     connection=connection, approval=_approved(outcome, asset, runtime),
                     tenant=TENANT)
    assert record.status is PublicationStatus.FAILED
    assert record.status is not PublicationStatus.PUBLISHED
    assert record.published is False
    assert not record.external_id and not record.external_url
    assert "DeploymentError" in record.error
    assert to_event(record).kind == "artefact_publication_failed"


def test_a_failure_is_recorded_rather_than_lost(executed, wiring) -> None:
    """An exception escaping would leave the site in an unknown state with
    nothing written down."""
    outcome, asset, files, _ = executed
    _registry, store, connection, _root = wiring
    runtime = create_runtime()

    class Broken:
        name = "local"

        def publish(self, site_slug, files):
            raise OSError("disk full")

        def promote(self, site_slug, version_id):
            return ""

    registry = DeploymentTargetRegistry()
    registry.register(TargetRegistration(target=Broken()))
    record = publish(outcome=outcome, asset=asset, files=files, target_name="local",
                     destination=DESTINATION, registry=registry, connections=store,
                     connection=connection, approval=_approved(outcome, asset, runtime),
                     tenant=TENANT)
    assert isinstance(record, PublicationRecord)
    assert record.completed_at is not None, "a failure has an end time too"


def test_a_failed_publication_does_not_block_a_retry(executed, wiring) -> None:
    outcome, asset, files, _ = executed
    _registry, store, connection, _root = wiring
    runtime = create_runtime()

    class Broken:
        name = "local"

        def publish(self, site_slug, files):
            raise DeploymentError("transient")

        def promote(self, site_slug, version_id):
            return ""

    broken = DeploymentTargetRegistry()
    broken.register(TargetRegistration(target=Broken()))
    failed = publish(outcome=outcome, asset=asset, files=files, target_name="local",
                     destination=DESTINATION, registry=broken, connections=store,
                     connection=connection, approval=_approved(outcome, asset, runtime),
                     tenant=TENANT)
    assert failed.status is PublicationStatus.FAILED
    # One bad afternoon must not make an artefact permanently unpublishable.
    assert published_fingerprints([to_event(failed)], tenant=TENANT) == ()


# ================================================= 8. no duplicates

def test_the_same_artefact_is_not_published_twice(executed, wiring) -> None:
    outcome, asset, files, _ = executed
    registry, store, connection, _root = wiring
    runtime = create_runtime()
    approval = _approved(outcome, asset, runtime)
    first = publish(outcome=outcome, asset=asset, files=files, target_name="local",
                    destination=DESTINATION, registry=registry, connections=store,
                    connection=connection, approval=approval, tenant=TENANT)
    live = published_fingerprints([to_event(first)], tenant=TENANT)
    assert live

    with pytest.raises(NotPublishable, match="already published"):
        publish(outcome=outcome, asset=asset, files=files, target_name="local",
                destination=DESTINATION, registry=registry, connections=store,
                connection=connection, approval=approval, tenant=TENANT,
                already_published=live)


def test_the_same_artefact_may_go_to_a_different_destination(executed, wiring) -> None:
    outcome, asset, files, _ = executed
    registry, store, connection, _root = wiring
    runtime = create_runtime()
    first = publish(outcome=outcome, asset=asset, files=files, target_name="local",
                    destination=DESTINATION, registry=registry, connections=store,
                    connection=connection, approval=_approved(outcome, asset, runtime),
                    tenant=TENANT)
    live = published_fingerprints([to_event(first)], tenant=TENANT)

    staging = Destination(slug="ahs-portfolio-staging")
    assert gate.check(**_conditions(
        executed, wiring, destination=staging, already_published=live,
        approval=_approved(outcome, asset, runtime, destination=staging)))


# ================================ 9. published is not a business result

def test_publication_success_is_not_business_success(executed, wiring) -> None:
    outcome, asset, files, _ = executed
    registry, store, connection, _root = wiring
    runtime = create_runtime()
    record = publish(outcome=outcome, asset=asset, files=files, target_name="local",
                     destination=DESTINATION, registry=registry, connections=store,
                     connection=connection, approval=_approved(outcome, asset, runtime),
                     tenant=TENANT)

    assert record.published is True
    assert record.is_business_result is False

    # Nothing has been measured, so nothing may be claimed.
    for claim in ("Qevik increased their enquiries.",
                  "This will drive more bookings.",
                  "Enquiries grew because of the new portfolio."):
        assert not permits(Attribution.UNKNOWN, claim)

    detail = to_event(record).detail
    assert "succeeded" not in detail and "improved" not in detail
    assert set(detail) & {"status", "external_id"}, "outcome is stated as status"


def test_the_record_has_no_field_that_could_read_as_a_result(executed, wiring) -> None:
    outcome, asset, files, _ = executed
    registry, store, connection, _root = wiring
    runtime = create_runtime()
    record = publish(outcome=outcome, asset=asset, files=files, target_name="local",
                     destination=DESTINATION, registry=registry, connections=store,
                     connection=connection, approval=_approved(outcome, asset, runtime),
                     tenant=TENANT)
    for forbidden in ("success", "improvement", "uplift", "roi", "conversions",
                      "revenue", "worked"):
        assert not any(forbidden in field for field in record.model_dump()), forbidden


# ================================ ready_to_publish is still not published

def test_ready_to_publish_is_not_published(executed) -> None:
    outcome, _asset, _files, _ = executed
    assert outcome.state is PublicationState.READY_TO_PUBLISH
    assert outcome.state is not PublicationState.PUBLISHED
    assert outcome.publishable, "publishable means allowed to be considered"
    # And nothing in the execution layer can make it so.
    from atlas_kernel.execution import service as execution

    with pytest.raises(NotImplementedError, match="not happen in the execution layer"):
        execution.publish(outcome)


def test_the_execution_layer_still_cannot_reach_the_outside_world() -> None:

    from atlas_kernel.execution import service as execution

    source = Path(execution.__file__).read_text(encoding="utf-8")
    for forbidden in ("httpx", "requests", "smtplib", "boto3", "urllib.request"):
        assert f"import {forbidden}" not in source


def test_only_a_target_reporting_success_can_write_published(executed, wiring) -> None:
    """A read of the source: PUBLISHED must not be reachable from a branch that
    did not come back from a host."""

    from atlas_kernel.publication import service as publication

    source = Path(publication.__file__).read_text(encoding="utf-8")
    # Writes only. Reading the value back — the duplicate check filters on it —
    # is not a way to become published.
    marker = "_record(PublicationStatus.PUBLISHED"
    written = [line for line in source.splitlines()
               if marker in line and not line.strip().startswith("#")]
    assert len(written) == 1, written
    # And the one place it is written sits after the host has returned, so no
    # failure path can reach it.
    before, _, _after = source.partition(marker)
    assert "version = staging.stage(" in before
    assert "except (DeploymentError" in before, \
        "PUBLISHED is written before the failure path, so a failure could reach it"


# ================================================= the gate can fail

def test_the_gate_passes_a_genuinely_publishable_artefact(executed, wiring) -> None:
    """A check that refuses everything is not a check."""
    outcome, asset, _files, _ = executed
    runtime = create_runtime()
    assert gate.check(**_conditions(
        executed, wiring, approval=_approved(outcome, asset, runtime)))
