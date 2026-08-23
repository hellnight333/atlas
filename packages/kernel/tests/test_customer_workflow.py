"""The customer boundary, tested as two customers who must never meet.

Everything here runs through the HTTP surface with a real auth middleware and
two tenants, because the questions P2.4 has to answer are not "does the service
work" — P2.3 established that — but "can this customer reach that customer's
data", and the only place that is decidable is at the door.

The isolation tests are deliberately repetitive: every read, one per resource.
A boundary that holds for six endpoints and leaks on the seventh is not a
boundary, and the seventh is always the one added last.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atlas_kernel.auth import Scope, User
from atlas_kernel.auth import api as auth_api
from atlas_kernel.auth.models import hash_password
from atlas_kernel.auth.store import AuthStore
from atlas_kernel.customer import api as customer_api
from atlas_kernel.customer import public, strategy
from atlas_kernel.customer.tasks import (
    Proof,
    ProofKind,
    ProofRejected,
    complete,
    completed_ids,
    outstanding,
    verify_approval,
    verify_domain,
)
from atlas_kernel.measurement import schedule
from atlas_kernel.measurement import service as measurement
from atlas_kernel.opportunity.tenancy import TenantId
from atlas_kernel.outreach import opportunity as opp
from atlas_kernel.recommendation import service as rec_service
from atlas_kernel.roadmap import Executability, assess, generate
from atlas_kernel.roadmap.lifecycle import facts_for

A = "tenant-alpha"
B = "tenant-beta"

RESEARCH = {
    # Slow and broken: `performance` and `broken` fire, so `offer-website` has
    # real work and real customer obligations attached to it.
    "alpha-co": {"website": "https://alpha.test", "observations": [
        {"feature": "website", "status": "present"},
        {"feature": "page_speed", "status": "not_found"},
        {"feature": "broken_links", "status": "not_found"},
        {"feature": "page_title", "status": "not_found"},
        {"feature": "contact_form", "status": "present"},
        {"feature": "blog", "status": "unverified"},
    ]},
    # Reachable but uncontactable: a different opportunity mix, so the two
    # tenants' strategies differ for reasons in the evidence.
    "beta-co": {"website": "https://beta.test", "observations": [
        {"feature": "website", "status": "present"},
        {"feature": "click_to_call", "status": "not_found"},
        {"feature": "whatsapp", "status": "not_found"},
        {"feature": "page_speed", "status": "present"},
        {"feature": "h1", "status": "present"},
    ]},
}
OWNER = {"alpha-co": A, "beta-co": B}


@dataclass
class Plan:
    roadmap: object
    readiness: object
    measurements: tuple = ()


def _plan_for(business_id: str) -> Plan:
    research = RESEARCH[business_id]
    observations = research["observations"]
    absent = frozenset(o["feature"] for o in observations
                       if o["status"] == "not_found")
    present = frozenset(o["feature"] for o in observations
                        if o["status"] == "present")
    ranked = opp.for_host(research["website"], category="logistics",
                          absent=absent, present=present)
    recommendations = rec_service.propose(
        business_id=business_id, tenant_id=OWNER[business_id],
        opportunities=ranked, business_model="LOGISTICS", plan="ADVANCED")
    roadmap = generate(business_id=business_id, tenant_id=OWNER[business_id],
                       observations=observations, recommendations=recommendations,
                       business_model="LOGISTICS")
    return Plan(roadmap=roadmap,
                readiness=assess(business_id=business_id, observations=observations,
                                 business_model="LOGISTICS"))


def _app() -> FastAPI:
    app = FastAPI()
    # The real auth middleware, so the tenant boundary is exercised through the
    # same path production uses. Stubbing the dependency instead would test a
    # door that does not exist.
    auth_api.install(app, AuthStore())
    customer_api.install(app)

    def research_reader(*, business_id: str, tenant: TenantId):
        # The reader is the tenant boundary for this source: a business owned by
        # somebody else is *absent*, not forbidden.
        if OWNER.get(business_id) != tenant:
            return None
        return RESEARCH[business_id]

    def plan_reader(*, business_id: str, tenant: TenantId):
        if OWNER.get(business_id) != tenant:
            return None
        return _plan_for(business_id)

    app.state.research_reader = research_reader
    app.state.plan_reader = plan_reader
    app.state.business_events = []
    return app


def _as(tenant: str, *, scopes=frozenset(Scope)) -> User:
    return User(username=f"user-{tenant}", password_hash=hash_password("test-only-password"),
                tenant_id=tenant, scopes=scopes)


@pytest.fixture
def client(monkeypatch):
    """A client that can act as either tenant, one request at a time."""
    app = _app()
    holder = {"user": _as(A)}
    monkeypatch.setattr(AuthStore, "authenticate", lambda self, token: holder["user"])

    class Acting(TestClient):
        def acting_as(self, user: User):
            holder["user"] = user
            return self

    with Acting(app) as test_client:
        test_client.headers["Authorization"] = "Bearer test"
        yield test_client


#: Every customer-facing read, so the isolation tests cannot miss one.
READS = [
    "/api/customer/businesses/{b}/research",
    "/api/customer/businesses/{b}/roadmap",
    "/api/customer/businesses/{b}/strategy",
    "/api/customer/businesses/{b}/tasks",
    "/api/customer/businesses/{b}/previews",
    "/api/customer/businesses/{b}/publications",
    "/api/customer/businesses/{b}/measurements",
]


# ======================================================= the boundary holds

def test_a_customer_sees_their_own_business(client) -> None:
    client.acting_as(_as(A))
    for path in READS:
        response = client.get(path.format(b="alpha-co"))
        assert response.status_code == 200, (path, response.text)


@pytest.mark.parametrize("path", READS)
def test_a_customer_cannot_see_another_tenants_business(client, path) -> None:
    client.acting_as(_as(A))
    assert client.get(path.format(b="beta-co")).status_code == 404
    client.acting_as(_as(B))
    assert client.get(path.format(b="alpha-co")).status_code == 404


@pytest.mark.parametrize("path", READS)
def test_the_boundary_is_symmetric(client, path) -> None:
    """A cannot see B, and B cannot see A. Checked both ways because a filter
    written from one tenant's perspective often only works from that one."""
    client.acting_as(_as(B))
    assert client.get(path.format(b="beta-co")).status_code == 200
    assert client.get(path.format(b="alpha-co")).status_code == 404


@pytest.mark.parametrize("path", READS)
def test_a_missing_business_is_indistinguishable_from_another_tenants(
        client, path) -> None:
    """403-vs-404 tells an attacker which ids exist, and enumerating ids is the
    cheapest attack there is."""
    client.acting_as(_as(A))
    theirs = client.get(path.format(b="beta-co"))
    nonexistent = client.get(path.format(b="no-such-business"))
    assert theirs.status_code == nonexistent.status_code == 404
    assert theirs.json() == nonexistent.json()


def test_an_account_with_no_tenant_reaches_nothing(client) -> None:
    """Empty means not established. An operator account runs Qevik; it does not
    read one customer's file."""
    client.acting_as(_as(""))
    assert client.get("/api/customer/me").status_code == 403
    for path in READS:
        assert client.get(path.format(b="alpha-co")).status_code == 403


def test_no_route_lets_the_caller_name_a_tenant() -> None:
    """A customer cannot ask for another customer's data because there is no
    argument in which to ask."""
    for route in customer_api.build_router().routes:
        assert "tenant" not in route.path
        assert "tenant" not in {p for p in getattr(route, "param_convertors", {})}


def test_the_tenant_comes_from_the_user_and_nothing_else(client) -> None:
    client.acting_as(_as(A))
    assert client.get("/api/customer/me").json()["tenant_id"] == A
    # A header or query string naming another tenant changes nothing.
    response = client.get("/api/customer/me?tenant_id=" + B,
                          headers={"X-Tenant-Id": B})
    assert response.json()["tenant_id"] == A


def test_no_aggregate_leaks_another_tenants_counts(client) -> None:
    client.acting_as(_as(A))
    body = client.get("/api/customer/businesses/alpha-co/tasks").json()
    assert body["business_id"] == "alpha-co"
    for group in ("outstanding", "completed"):
        blob = repr(body[group])
        assert "beta" not in blob and B not in blob


# =============================================== research reports both halves

def test_research_reports_what_was_not_checked(client) -> None:
    client.acting_as(_as(A))
    body = client.get("/api/customer/businesses/alpha-co/research").json()
    assert body["not_verified"] == ["blog"]
    assert set(body["confirmed_absent"]) == {"page_speed", "broken_links",
                                             "page_title"}
    assert "not a finding either way" in body["note"]


def test_missing_evidence_is_never_presented_as_a_weakness(client) -> None:
    client.acting_as(_as(A))
    body = client.get("/api/customer/businesses/alpha-co/research").json()
    assert "blog" not in body["confirmed_absent"]
    strategy_body = client.get("/api/customer/businesses/alpha-co/strategy").json()
    for priority in strategy_body["priorities"]:
        if priority["state"] == "unmeasured":
            assert priority["score"] is None, "unmeasured must not carry a number"


# =============================================== the strategy is derived

def test_the_strategy_is_generated_from_this_business_evidence(client) -> None:
    client.acting_as(_as(A))
    alpha = client.get("/api/customer/businesses/alpha-co/strategy").json()
    client.acting_as(_as(B))
    beta = client.get("/api/customer/businesses/beta-co/strategy").json()
    assert alpha["prose"] != beta["prose"]
    assert alpha["priorities"] != beta["priorities"]


def test_every_sentence_of_the_strategy_passes_the_claim_gate() -> None:
    from atlas_kernel.measurement.attribution import Attribution, permits

    for business_id in RESEARCH:
        plan = _plan_for(business_id)
        summary = strategy.summarise(roadmap=plan.roadmap, readiness=plan.readiness)
        for line in summary["prose"]:
            assert permits(Attribution.UNKNOWN, line), line


def test_a_strong_dimension_gets_no_work_in_the_strategy() -> None:
    plan = _plan_for("alpha-co")
    summary = strategy.summarise(roadmap=plan.roadmap, readiness=plan.readiness)
    strong = set(summary["already_working"])
    for entry in summary["qevik_can_start"]:
        task = next(t for t in plan.roadmap.tasks if t.id == entry["task_id"])
        assert task.dimension not in strong


# =============================================== customer tasks need proof

def test_a_customer_task_is_not_complete_because_somebody_said_so() -> None:
    plan = _plan_for("alpha-co")
    customer_tasks = [t for t in plan.roadmap.tasks if t.is_customer]
    assert customer_tasks, "the fixture must have a customer obligation"
    task = customer_tasks[0]

    with pytest.raises(ProofRejected, match="whose"):
        Proof(kind=ProofKind.ATTESTATION, reference="done")

    signed = Proof(kind=ProofKind.ATTESTATION, reference="done",
                   attested_by="ayoub@alpha.test")
    event = complete(task, signed, tenant=A)
    assert event.detail["verified_by_system"] is False, \
        "an attestation is somebody's word and must be recorded as one"
    assert event.actor == "ayoub@alpha.test"


def test_an_observed_proof_is_actually_observed() -> None:
    with pytest.raises(ProofRejected, match="does not resolve"):
        verify_domain("definitely-not-a-real-qevik-domain.invalid")
    proof = verify_domain("https://example.com/whatever")
    assert proof.kind is ProofKind.OBSERVED
    assert proof.reference == "example.com"


def test_an_approval_that_was_not_granted_is_not_proof() -> None:
    from atlas_kernel.approval.models import ApprovalRequest, ApprovalState

    pending = ApprovalRequest(title="Approve the site", state=ApprovalState.PENDING)
    with pytest.raises(ProofRejected, match="nothing has been agreed"):
        verify_approval(pending)


def test_qevik_cannot_complete_its_own_work_as_the_customer() -> None:
    """The conversion the whole distinction exists to prevent, arriving as a
    plausible-looking call."""
    plan = _plan_for("alpha-co")
    qevik_task = next(t for t in plan.roadmap.tasks if not t.is_customer)
    with pytest.raises(ProofRejected, match="work we owe them"):
        complete(qevik_task, Proof(kind=ProofKind.OBSERVED, reference="x"), tenant=A)


def test_another_tenant_cannot_complete_a_task() -> None:
    plan = _plan_for("alpha-co")
    task = next(t for t in plan.roadmap.tasks if t.is_customer)
    with pytest.raises(PermissionError, match="different tenant"):
        complete(task, Proof(kind=ProofKind.OBSERVED, reference="x"), tenant=B)


def test_completion_is_scoped_when_read_back() -> None:
    plan = _plan_for("alpha-co")
    task = next(t for t in plan.roadmap.tasks if t.is_customer)
    event = complete(task, Proof(kind=ProofKind.OBSERVED, reference="alpha.test"),
                     tenant=A)
    assert completed_ids([event], tenant=A) == frozenset({task.id})
    assert completed_ids([event], tenant=B) == frozenset()


def test_outstanding_tasks_say_what_they_unblock() -> None:
    plan = _plan_for("alpha-co")
    waiting = outstanding(plan.roadmap, facts_for(plan.roadmap))
    assert waiting
    for entry in waiting:
        assert entry["do"], "a customer task must say what to do"
        assert "unblocks" in entry


# =============================================== the two approvals stay apart

def test_execution_approval_is_not_publication_approval() -> None:
    from atlas_kernel.publication.models import PUBLISH_ACTION
    from atlas_kernel.roadmap.gate import EXECUTE_ACTION

    assert EXECUTE_ACTION != PUBLISH_ACTION


def test_a_task_with_no_executor_is_never_offered_as_executable(client) -> None:
    client.acting_as(_as(A))
    body = client.get("/api/customer/capabilities").json()
    executable = {e["offer_id"] for e in body["executable"]}
    for entry in body["offered_only"]:
        assert entry["offer_id"] not in executable
        assert entry["executable"] is False

    plan = _plan_for("alpha-co")
    for task in plan.roadmap.tasks:
        if task.executability is Executability.QEVIK_CAN_EXECUTE:
            assert task.capability_id


def test_a_customer_cannot_reach_another_tenants_asset() -> None:
    """There is no asset route on this surface, so the guard that matters is the
    one on the outcome itself — asserted here from the customer's position
    rather than only where it was written."""
    from atlas_kernel.execution.models import ExecutionOutcome
    from atlas_kernel.execution.service import visible_to

    theirs = ExecutionOutcome(job_id="j", run_id="r", recommendation_id="rec",
                              business_id="beta-co", tenant_id=B,
                              asset_ids=("asset-1",))
    assert visible_to(theirs, B)
    assert not visible_to(theirs, A)
    orphan = theirs.model_copy(update={"tenant_id": None})
    assert not visible_to(orphan, A) and not visible_to(orphan, B), \
        "an outcome with no tenant belongs to nobody"


def test_a_customer_cannot_approve_another_tenants_job() -> None:
    from atlas_kernel.roadmap import gate
    from atlas_kernel.roadmap.lifecycle import TaskFacts

    # alpha-co's plan, because beta-co's opportunities map only to an offer
    # with no executor — there is no job of theirs to try to approve.
    plan = _plan_for("alpha-co")
    task = next(t for t in plan.roadmap.tasks
                if t.executability is Executability.QEVIK_CAN_EXECUTE)
    assert task.tenant_id == A
    reasons = gate.unmet(task, recommendation=None, approval=None,
                         facts=TaskFacts(), tenant=B)
    assert any("different tenant" in r for r in reasons), reasons


# =============================================== measurement stays honest

def test_a_missing_provider_is_unavailable_not_zero() -> None:
    nothing = measurement.open_baseline(
        business_id="alpha-co", tenant_id=A, metric_key="sessions",
        value=None, source="analytics")
    assert measurement.progress_of(nothing) is measurement.Progress.UNAVAILABLE
    assert nothing.baseline.value is None
    assert nothing.improved is None
    report = measurement.report(nothing)
    assert report["change"] is None
    assert "0" not in report["progress"]
    for wrong in ("no_improvement", "failed"):
        assert wrong not in report["progress"]


def test_the_schedule_separates_overdue_from_impossible() -> None:
    baseline = measurement.open_baseline(
        business_id="alpha-co", tenant_id=A, metric_key="sessions",
        value=100.0, source="analytics")
    overdue = measurement.record_intervention(
        baseline, at=datetime.now(UTC) - timedelta(days=40))
    waiting = measurement.open_baseline(
        business_id="alpha-co", tenant_id=A, metric_key="clicks",
        value=None, source="search-console")

    plan = schedule.plan([overdue, waiting])
    assert plan["due_now"] == [overdue.id]
    assert measurement.Progress.UNAVAILABLE.value in plan["by_state"]
    assert waiting.id not in plan["due_now"], \
        "a metric nobody can read is not overdue"


def test_nothing_in_the_schedule_reads_a_metric() -> None:
    from pathlib import Path

    source = Path(schedule.__file__).read_text(encoding="utf-8")
    for forbidden in ("httpx", "requests", "import socket", "urllib"):
        assert forbidden not in source


# =============================================== the public boundary

def test_a_public_audit_carries_nothing_private() -> None:
    ranked = opp.for_host("https://alpha.test", category="logistics",
                          absent=frozenset({"page_speed"}),
                          present=frozenset({"website"}))
    payload = public.audit(website="https://alpha.test",
                           observations=RESEARCH["alpha-co"]["observations"],
                           opportunities=ranked)
    blob = repr(payload)
    for private in (A, B, "alpha-co", "tenant", "evidence", "recommendation_id"):
        assert private not in blob, private


def test_the_public_guard_refuses_a_field_nobody_allowed() -> None:
    """Allow-list, not redaction: a field added upstream is invisible until
    somebody adds it deliberately."""
    for payload in ({"tenant_id": "t"}, {"website": "x", "evidence": ["e"]},
                    {"website": "x", "business_id": "b"},
                    {"opportunities": [{"key": "k", "evidence": ["e"]}]}):
        with pytest.raises(public.Leak):
            public.guard(payload)


def test_the_public_audit_counts_rather_than_names() -> None:
    payload = public.audit(website="https://alpha.test",
                           observations=RESEARCH["alpha-co"]["observations"])
    assert isinstance(payload["checked"]["confirmed"], int)
    assert isinstance(payload["summary"]["to_fix"], int)
    assert "page_title" not in repr(payload), "naming the gaps gives away the work"


# =============================================== metering is possible later

def test_an_execution_retains_what_it_would_be_metered_on() -> None:
    from atlas_kernel.execution.models import ExecutionOutcome

    fields = set(ExecutionOutcome.model_fields)
    assert {"estimated_units", "actual_units", "tenant_id", "job_id", "run_id",
            "asset_ids", "capability_id", "recommendation_id"} <= fields
    blank = ExecutionOutcome(job_id="j", run_id="r", recommendation_id="rec",
                             business_id="b")
    assert blank.actual_units is None, "None means nobody counted, never zero work"


# =============================================== handlers stay thin

def test_no_handler_reimplements_kernel_logic() -> None:
    """A rule enforced in a handler applies only to callers who came through
    that door."""
    from pathlib import Path

    source = Path(customer_api.__file__).read_text(encoding="utf-8")
    for forbidden in ("def assess", "def generate(", "PublicationStatus.PUBLISHED",
                      "ApprovalState.APPROVED", "engine.begin", "text("):
        assert forbidden not in source, forbidden


# =============================================== the public entry point

@pytest.fixture
def public_client(monkeypatch):
    """A client with no credentials at all, as a visitor has none."""
    app = _app()

    def audit_reader(*, website: str):
        if "alpha" not in website:
            return None
        return {"observations": RESEARCH["alpha-co"]["observations"],
                "opportunities": opp.for_host(website, category="logistics",
                                              absent=frozenset({"page_speed"}),
                                              present=frozenset({"website"}))}

    app.state.public_audit_reader = audit_reader
    with TestClient(app) as client:
        yield client


def test_a_visitor_with_no_account_can_audit_a_site(public_client) -> None:
    response = public_client.post("/api/public/audit",
                                  json={"website": "https://alpha.test"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["website"] == "https://alpha.test"
    assert isinstance(body["summary"]["to_fix"], int)
    assert body["opportunities"]


def test_the_public_audit_exposes_nothing_private(public_client) -> None:
    body = public_client.post("/api/public/audit",
                              json={"website": "https://alpha.test"}).json()
    blob = repr(body)
    for private in (A, B, "alpha-co", "tenant", "evidence", "recommendation_id",
                    "business_id", "page_title"):
        assert private not in blob, private


def test_an_unaudited_site_is_told_so_rather_than_guessed_at(public_client) -> None:
    body = public_client.post("/api/public/audit",
                              json={"website": "https://never-seen.test"}).json()
    assert body["checked"] == {"confirmed": 0, "not_verified": 0}
    assert body["summary"] == {"working": 0, "to_fix": 0}
    assert body["opportunities"] == []


def test_the_public_route_does_not_fetch_anything_on_request() -> None:
    """A route that crawled an arbitrary URL on request is a request-triggered
    outbound fetch: an amplifier, and a way to put Qevik's address in a
    stranger's logs."""
    from pathlib import Path

    from atlas_kernel.customer import api as customer_module

    source = Path(customer_module.__file__).read_text(encoding="utf-8")
    for forbidden in ("httpx.", "requests.", "urlopen", "discover(", "crawl("):
        assert forbidden not in source, forbidden


def test_a_public_audit_needs_a_website(public_client) -> None:
    assert public_client.post("/api/public/audit", json={}).status_code == 400
    assert public_client.post("/api/public/audit",
                              json={"website": "   "}).status_code == 400


@pytest.mark.real_auth
def test_the_customer_routes_are_still_closed(public_client) -> None:
    """Adding a public route must not open the authenticated ones.

    `real_auth` because conftest authenticates every other test as an operator;
    this one is *about* authentication, so it needs the genuine middleware with
    no credentials at all — which is what a visitor has.
    """
    for path in READS:
        assert public_client.get(path.format(b="alpha-co")).status_code == 401
    assert public_client.get("/api/customer/me").status_code == 401
