"""Chat, tested on the two ways the missing middle could be built wrongly.

**It could execute.** A surface that did what a message said would make natural
language the authorisation boundary — and the language arriving here is not
trusted input. A plan is written by a model that has read the customer's
website, their email, their research. Requiring a person to look at the plan
before anything runs is what keeps a prompt injection a proposal.

**It could invent a plan.** With no model configured, the tempting output is a
generic three-step template. That is the most damaging possible answer: it looks
like Qevik understood the request, it gets approved, a worker picks it up, and an
agent implements steps nobody derived from anything. So a plan is either
produced by a model that saw the request, or it is a blocker. There is no third
kind, and that is asserted directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atlas_kernel.auth import Scope, User
from atlas_kernel.auth import api as auth_api
from atlas_kernel.auth.models import hash_password
from atlas_kernel.auth.store import AuthStore
from atlas_kernel.chat import api as chat_api
from atlas_kernel.chat import planner, service
from atlas_kernel.chat.models import ConversationStatus, Role
from atlas_kernel.credentials.service import CredentialService
from atlas_kernel.credentials.vault import Vault
from atlas_kernel.mission import service as mission_service
from atlas_kernel.mission.models import Blocker, Plan, PlanStep
from atlas_kernel.modelchoice.store import SelectionStore

A, B = "tenant-alpha", "tenant-beta"


def _user(tenant: str, *scopes: Scope) -> User:
    return User(username=f"u-{tenant}",
                password_hash=hash_password("test-only-password"),
                tenant_id=tenant, scopes=frozenset(scopes or frozenset(Scope)))


@pytest.fixture
def app():
    application = FastAPI()
    auth_api.install(application, AuthStore())
    chat_api.install(application)
    application.state.credentials = CredentialService(
        Vault(master_key="test-only-master-key-not-real"))
    application.state.model_selections = SelectionStore()
    missions: list = []
    application.state.mission_events = missions
    application.state.mission_sink = missions.append
    return application


@pytest.fixture
def client(app, monkeypatch):
    holder = {"user": _user(A)}
    monkeypatch.setattr(AuthStore, "authenticate", lambda self, token: holder["user"])

    class Acting(TestClient):
        def acting_as(self, user: User):
            holder["user"] = user
            return self

    with Acting(app) as test_client:
        test_client.headers["Authorization"] = "Bearer test"
        yield test_client


def _open(client, text: str = "Rebuild the website for Al Hamra") -> str:
    response = client.post("/api/chat", json={"text": text})
    assert response.status_code == 201, response.text
    return response.json()["conversation_id"]


# ============================================ chat executes nothing

#: Names that mean this module can make something happen outside itself.
EXECUTES = {"subprocess", "Popen", "run", "system", "eval", "exec", "Worker",
            "GitWorkspace", "popen", "spawn"}


def _reaches_for(module) -> set[str]:
    """Every name a module imports or calls. Parsed, not grepped.

    A text scan is defeated by prose: the first version of this test failed on
    the docstring that describes the test, because the docstring names the
    things it forbids. An AST walk sees code and not commentary, which is the
    property this check needs to have.
    """
    import ast

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add((node.module or "").split(".")[0])
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Name):
                names.add(target.id)
            elif isinstance(target, ast.Attribute):
                names.add(target.attr)
    return names


def test_the_chat_surface_cannot_run_anything() -> None:
    """Nothing here starts a process, opens a repository or drives a worker.

    A surface that did what a message said would make natural language the
    authorisation boundary, and the language arriving here has passed through a
    model that read the customer's website and email.
    """
    for module in (chat_api, service):
        reaches = _reaches_for(module) & EXECUTES
        assert reaches == set(), f"{module.__name__} reaches for {reaches}"


def test_the_execution_scan_can_actually_fail() -> None:
    """A scan that finds nothing because it looks for nothing is not a scan."""
    from atlas_kernel.mission import gitspace

    assert _reaches_for(gitspace) & EXECUTES, (
        "gitspace runs git, so the scan must flag it")


def test_approving_queues_a_mission_and_runs_nothing(client, app) -> None:
    conversation = _open(client)
    _propose(app, conversation, client)

    body = client.post(f"/api/chat/{conversation}/decide",
                       json={"approved": True}).json()
    assert body["mission_id"]
    assert body["mission_status"] == "queued"
    assert "closing this page does not stop it" in body["note"]

    # Queued, claimed by nothing. The worker is elsewhere.
    folded = mission_service.fold(app.state.mission_events, tenant=A)
    assert folded[0]["status"] == "queued"
    assert folded[0]["claimed_by"] == ""


def _propose(app, conversation_id: str, client, *, steps=True):
    """Attach a plan the way the planner would, without needing a live model."""
    current = service.rehydrate(
        next(c for c in service.fold(app.state.chat_events, tenant=A)
             if c["conversation_id"] == conversation_id), tenant=A)
    plan = (Plan(goal="Rebuild the site", approval_required=True,
                 steps=(PlanStep(order=1, title="Generate the pages"),))
            if steps else
            Plan(goal="", approval_required=True,
                 blockers=(Blocker(kind="PENDING_CREDENTIAL", detail="no model",
                                   action="Add a credential"),)))
    updated, event = service.plan_for(current, plan, tenant=A,
                                      provider="test", model="test-model")
    app.state.chat_sink(event)
    return updated


# ============================================ a plan is never invented

def test_with_no_model_the_plan_is_a_blocker_not_a_template(client, app) -> None:
    """A template plan looks like understanding and is not.

    It would be approved, queued, and implemented as steps nobody derived from
    the request — wrong in a way that survives review.
    """
    conversation = _open(client)
    body = client.post(f"/api/chat/{conversation}/plan").json()

    assert body["blocked"] is True
    plan = body["proposal"]["plan"]
    assert plan["steps"] == []
    assert plan["blockers"], "a blocked plan must say what is in the way"
    assert plan["blockers"][0]["kind"] == "PENDING_CREDENTIAL"
    assert "Credential Centre" in plan["blockers"][0]["action"]


def test_the_blocker_says_qevik_will_not_invent_one(client) -> None:
    conversation = _open(client)
    body = client.post(f"/api/chat/{conversation}/plan").json()
    assert "invent a plan" in body["proposal"]["plan"]["blockers"][0]["detail"]


def test_a_blocked_plan_cannot_be_approved_into_a_mission(client, app) -> None:
    """Approving it would queue work that cannot start."""
    conversation = _open(client)
    client.post(f"/api/chat/{conversation}/plan")

    response = client.post(f"/api/chat/{conversation}/decide",
                           json={"approved": True})
    assert response.status_code == 409
    assert "cannot start" in response.json()["detail"]
    assert mission_service.fold(app.state.mission_events, tenant=A) == []


def test_an_empty_plan_is_refused_before_it_reaches_a_person(app) -> None:
    """A plan with no steps and no blockers proposes nothing, and shown to
    somebody it reads as agreement."""
    conversation, event = service.start(tenant=A, text="do something")
    app.state.chat_sink(event)
    with pytest.raises(service.PlanRejected, match="reads as agreement"):
        service.plan_for(conversation, Plan(goal="x"), tenant=A)


def test_the_planner_reports_which_model_wrote_the_plan(client) -> None:
    """Approval is agreement with a specific proposal from a specific model."""
    conversation = _open(client)
    proposal = client.post(f"/api/chat/{conversation}/plan").json()["proposal"]
    # No model here, so both are empty and the reason says why — never a
    # plausible-looking model name attached to a plan no model wrote.
    assert proposal["model"] == "" and proposal["provider"] == ""
    assert proposal["reason"]


# ============================================ the plan is shown before it runs

def test_the_plan_is_readable_before_anybody_approves(client, app) -> None:
    conversation = _open(client)
    _propose(app, conversation, client)

    body = client.get(f"/api/chat/{conversation}").json()
    assert body["status"] == ConversationStatus.PLAN_PROPOSED.value
    assert body["awaiting_approval"] is True
    # As prose, not as JSON somebody has to read a schema for.
    shown = [m for m in body["messages"] if m["role"] == "assistant"][-1]["text"]
    assert "1. Generate the pages" in shown
    assert "Nothing runs until you approve this." in shown


def test_a_blocked_plan_puts_the_blocker_above_the_steps(app) -> None:
    """A plan whose steps are listed above the reason they cannot run reads as
    a plan that will run."""
    conversation, event = service.start(tenant=A, text="ship it")
    app.state.chat_sink(event)
    plan = Plan(goal="Ship", approval_required=True,
                steps=(PlanStep(order=1, title="Deploy"),),
                blockers=(Blocker(kind="PENDING_HOST", detail="no host",
                                  action="Provide a host"),))
    updated, _ = service.plan_for(conversation, plan, tenant=A)
    shown = updated.messages[-1].text
    assert shown.index("cannot proceed") < shown.index("1. Deploy")


def test_declining_keeps_the_plan_on_the_record(client, app) -> None:
    """It is the most useful thing in the file when the next one is written."""
    conversation = _open(client)
    _propose(app, conversation, client)

    body = client.post(f"/api/chat/{conversation}/decide",
                       json={"approved": False, "why": "too broad"}).json()
    assert body["status"] == ConversationStatus.PLAN_REJECTED.value
    assert body["plan"] is not None, "the declined plan must survive"
    assert body["mission_id"] == ""
    assert mission_service.fold(app.state.mission_events, tenant=A) == []


def test_planning_twice_after_a_mission_exists_is_refused(client, app) -> None:
    """Two plans and no way to say which one was approved."""
    conversation = _open(client)
    _propose(app, conversation, client)
    client.post(f"/api/chat/{conversation}/decide", json={"approved": True})

    response = client.post(f"/api/chat/{conversation}/plan")
    assert response.status_code == 409
    assert "already produced mission" in response.json()["detail"]


# ============================================ provenance survives

def test_the_conversation_records_who_asked_and_who_approved(client, app) -> None:
    conversation = _open(client)
    _propose(app, conversation, client)
    client.post(f"/api/chat/{conversation}/decide", json={"approved": True})

    body = client.get(f"/api/chat/{conversation}").json()
    assert body["started_by"] == "u-tenant-alpha"
    history = client.get(f"/api/chat/{conversation}/history").json()["history"]
    assert len(history) >= 3, "start, plan, approve"
    assert [h["status"] for h in history][-1] == "mission_created"


def test_a_conversation_references_a_mission_and_does_not_become_one(client, app
                                                                    ) -> None:
    """Collapsing them would make the record of what was asked mutable by the
    thing that was asked to do it."""
    conversation = _open(client)
    _propose(app, conversation, client)
    body = client.post(f"/api/chat/{conversation}/decide",
                       json={"approved": True}).json()

    assert body["conversation_id"] != body["mission_id"]
    assert body["conversation_id"].startswith("chat-")
    assert body["mission_id"].startswith("mission-")


def test_the_mission_carries_the_full_lifecycle_not_a_shortcut(client, app) -> None:
    """A mission constructed already-queued would have no history explaining
    how it got there, and the history is what a person reads when it fails."""
    conversation = _open(client)
    _propose(app, conversation, client)
    body = client.post(f"/api/chat/{conversation}/decide",
                       json={"approved": True}).json()

    history = mission_service.history(app.state.mission_events,
                                      body["mission_id"], tenant=A)
    assert [h["status"] for h in history] == [
        "draft", "planning", "awaiting_approval", "queued"]


def test_a_model_written_message_is_distinguishable_from_a_typed_one(app) -> None:
    """A transcript that blurs them is one nobody can find their request in."""
    conversation, event = service.start(tenant=A, text="hello")
    app.state.chat_sink(event)
    updated, _ = service.plan_for(
        conversation, Plan(goal="g", steps=(PlanStep(order=1, title="s"),)),
        tenant=A, provider="qwen", model="qwen-max")

    typed = [m for m in updated.messages if m.role is Role.USER][0]
    written = [m for m in updated.messages if m.role is Role.ASSISTANT][0]
    assert typed.model == "" and typed.provider == ""
    assert written.model == "qwen-max" and written.provider == "qwen"


# ============================================ tenancy and persistence

def test_another_tenants_conversation_is_absent(client, app) -> None:
    conversation, event = service.start(tenant=B, text="theirs")
    app.state.chat_sink(event)

    missing = client.get("/api/chat/chat-000000000000")
    other = client.get(f"/api/chat/{conversation.id}")
    assert other.status_code == missing.status_code == 404
    assert other.json() == missing.json()


def test_one_tenant_never_sees_anothers_conversations(client, app) -> None:
    _open(client)
    _, event = service.start(tenant=B, text="theirs")
    app.state.chat_sink(event)

    client.acting_as(_user(B))
    body = client.get("/api/chat").json()
    assert all(c["tenant_id"] == B for c in body["conversations"])
    assert len(body["conversations"]) == 1


def test_an_account_with_no_tenant_reaches_nothing(client) -> None:
    client.acting_as(_user(""))
    assert client.get("/api/chat").status_code == 403
    assert client.post("/api/chat", json={"text": "hi"}).status_code == 403


def test_approving_with_no_mission_timeline_refuses_rather_than_marking_it_done(
        client, app) -> None:
    """Marking the conversation approved while queuing nothing is worse than
    refusing: the person believes work started."""
    conversation = _open(client)
    _propose(app, conversation, client)
    app.state.mission_sink = None

    response = client.post(f"/api/chat/{conversation}/decide",
                           json={"approved": True})
    assert response.status_code == 503
    assert client.get(f"/api/chat/{conversation}").json()["status"] == (
        ConversationStatus.PLAN_PROPOSED.value), "still awaiting approval"


def test_a_conversation_survives_being_folded_from_the_timeline(client, app
                                                                ) -> None:
    """The timeline is the storage; the object is derived."""
    conversation = _open(client, "Rebuild the site")
    _propose(app, conversation, client)

    folded = service.fold(app.state.chat_events, tenant=A)
    assert len(folded) == 1
    assert folded[0]["status"] == ConversationStatus.PLAN_PROPOSED.value
    assert folded[0]["plan"]["steps"][0]["title"] == "Generate the pages"


def test_the_fold_takes_the_latest_by_time_not_by_position(app) -> None:
    """Two processes append to one timeline; arrival order is not event order.
    `mission.fold` learned this by folding a completed mission back to
    awaiting_approval."""
    conversation, first = service.start(tenant=A, text="hello")
    updated, second = service.send(conversation, tenant=A, text="and also this")

    forwards = service.fold([first, second], tenant=A)
    backwards = service.fold([second, first], tenant=A)
    assert forwards == backwards
    assert len(forwards[0]["messages"]) == 2
    assert updated.messages[-1].text == "and also this"


# ============================================ input limits

def test_an_oversized_message_is_refused(client) -> None:
    response = client.post("/api/chat", json={"text": "x" * 20_000})
    assert response.status_code == 422


def test_an_empty_message_is_refused(client) -> None:
    assert client.post("/api/chat", json={"text": "   "}).status_code == 422


def test_planning_requires_execute_because_it_spends_money(client) -> None:
    """It changes nothing here and still costs something at the provider."""
    conversation = _open(client)
    client.acting_as(_user(A, Scope.READ))
    assert client.post(f"/api/chat/{conversation}/plan").status_code == 403


def test_the_planner_marks_a_provider_failure_differently_from_a_missing_one(
        app) -> None:
    """One is worth retrying and the other never is, so they are different
    blocker kinds and different actions."""
    conversation, _ = service.start(tenant=A, text="do the thing")
    proposal = planner.propose(conversation, tenant=A,
                               credentials=app.state.credentials)
    assert proposal.plan.blockers[0].kind == planner.NO_MODEL
    assert planner.PLANNING_FAILED != planner.NO_MODEL


# ============================================ a rejected key is not a missing one

def test_a_provider_refusing_a_key_is_not_reported_as_a_missing_key(
        tmp_path, monkeypatch) -> None:
    """These need opposite actions from the person reading the screen.

    "Add a model credential" is useless advice to somebody who already added
    one, and it sends them to re-enter a key that is present and working as
    intended — the provider is the one refusing it.
    """
    from atlas_kernel.chat import planner, service
    from atlas_kernel.credentials.location import paths_for
    from atlas_kernel.credentials.service import CredentialService, Status
    from atlas_kernel.credentials.vault import FileSecretStore, Vault
    from atlas_kernel.mission.timeline import Timeline

    monkeypatch.setenv("QEVIK_VAULT_MASTER_KEY", "test-only-master-key")
    where = paths_for(tmp_path)
    records = Timeline(where.records)
    credentials = CredentialService(Vault(FileSecretStore(where.vault)),
                                    events=records.read(), sink=records.append)
    conversation, _ = service.start(tenant="t1", text="Add a dark mode toggle.",
                                    started_by="ayoub")

    absent = planner.propose(conversation, tenant="t1", credentials=credentials)
    assert absent.plan.blockers[0].kind == planner.NO_MODEL

    credentials.store(provider="qwen", tenant="t1", secret="sk-not-a-real-key")
    credentials.verify(provider="qwen", tenant="t1",
                       probe=lambda _: (Status.INVALID_CREDENTIAL, "refused"))

    refused = planner.propose(conversation, tenant="t1", credentials=credentials)
    assert refused.plan.blockers[0].kind == planner.EXTERNAL_PROVIDER
    assert "qwen" in refused.plan.blockers[0].detail
    assert "not a missing credential" in refused.plan.blockers[0].action


def test_neither_case_invents_a_plan(tmp_path, monkeypatch) -> None:
    """The rule the whole planner rests on: a plan is produced by a model that
    saw the request, or it is a blocker. There is no third kind."""
    from atlas_kernel.chat import planner, service
    from atlas_kernel.credentials.location import paths_for
    from atlas_kernel.credentials.service import CredentialService
    from atlas_kernel.credentials.vault import FileSecretStore, Vault

    monkeypatch.setenv("QEVIK_VAULT_MASTER_KEY", "test-only-master-key")
    where = paths_for(tmp_path)
    credentials = CredentialService(Vault(FileSecretStore(where.vault)))
    conversation, _ = service.start(tenant="t1", text="Add a dark mode toggle.",
                                    started_by="ayoub")

    proposal = planner.propose(conversation, tenant="t1",
                               credentials=credentials)
    assert proposal.blocked is True
    assert proposal.plan.steps == ()
    assert proposal.model == "", "no model may be named when none was reached"
