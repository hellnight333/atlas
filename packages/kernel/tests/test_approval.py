from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from atlas_kernel.agents.schedule_models import (
    QueueEntryStatus,
    RuntimeExecutionStatus,
    SchedulerPriority,
)
from atlas_kernel.api import app, approval_service, repository, runtime
from atlas_kernel.approval.events import (
    ApprovalApproved,
    ApprovalCreated,
    ApprovalRejected,
    ExecutionWaitingApproval,
)
from atlas_kernel.approval.models import (
    ApprovalCondition,
    ApprovalContext,
    ApprovalPolicy,
    ApprovalPolicyMode,
    ApprovalScope,
    ApprovalState,
)
from atlas_kernel.approval.policies import ApprovalPolicyEngine
from atlas_kernel.approval.service import ApprovalError, SelfApprovalError

client = TestClient(app)

KERNEL_ROOT = Path(__file__).resolve().parents[1] / "atlas_kernel"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clear_policies() -> None:
    for policy in repository.list_approval_policies():
        repository.delete_approval_policy(policy.id)


def _policy(**overrides: object) -> ApprovalPolicy:
    defaults: dict[str, object] = {
        "name": "test-policy",
        "mode": ApprovalPolicyMode.SCOPED,
        "scopes": [ApprovalScope.DELETE],
    }
    defaults.update(overrides)
    policy = ApprovalPolicy(**defaults)  # type: ignore[arg-type]
    repository.upsert_approval_policy(policy)
    return policy


def _context(**overrides: object) -> ApprovalContext:
    defaults: dict[str, object] = {"action": "text.generate", "requested_by": "atlas"}
    defaults.update(overrides)
    return ApprovalContext(**defaults)  # type: ignore[arg-type]


def _create_project() -> str:
    workspace = client.post("/workspaces", json={"name": "approval-ws", "description": "a"})
    project = client.post(
        "/projects",
        json={
            "workspace_id": workspace.json()["workspace_id"],
            "name": "approval-project",
            "description": "a",
        },
    )
    return project.json()["project_id"]


def _create_agent(project_id: str) -> str:
    agent = client.post(
        "/agents",
        json={
            "name": "Approval Agent",
            "description": "a",
            "role": "operator",
            "project_id": project_id,
            "capabilities": ["image"],
            "permission_set": ["execute_workflow"],
        },
    )
    return agent.json()["id"]


def _schedule_with_scopes(agent_id: str, scopes: list[str], cost: float = 0.0) -> tuple[str, str]:
    """Builds a real schedule through the scheduler whose step declares scopes."""
    from atlas_kernel.agents.plan_models import PlanStep
    from atlas_kernel.agents.schedule_models import SchedulerRequest

    step = PlanStep(
        description="approval-gated step",
        capability="image",
        action="image.generate",
        payload={"prompt": "gated", "approval_scopes": scopes, "estimated_cost": cost},
        expected_output="image",
    )
    schedule = runtime.agent_scheduler.create_schedule(
        SchedulerRequest(
            plan_id=f"plan-{agent_id[:8]}",
            agent_id=agent_id,
            steps=[step],
            priority=SchedulerPriority.NORMAL,
            available_executors=["local"],
        )
    )
    return schedule.schedule_id, schedule.queue_entries[0].id


# ---------------------------------------------------------------------------
# Policy engine — declarative, no hardcoded rules
# ---------------------------------------------------------------------------


def test_no_policy_means_no_approval_required() -> None:
    _clear_policies()
    evaluation = approval_service.evaluate(_context(scopes=[ApprovalScope.DELETE]))
    assert evaluation.required is False


def test_always_policy_requires_approval_for_any_action() -> None:
    _clear_policies()
    _policy(name="always", mode=ApprovalPolicyMode.ALWAYS)
    evaluation = approval_service.evaluate(_context())
    assert evaluation.required is True
    assert evaluation.policy_name == "always"


def test_never_policy_exempts_action() -> None:
    _clear_policies()
    _policy(name="never", mode=ApprovalPolicyMode.NEVER, priority=100)
    _policy(name="always", mode=ApprovalPolicyMode.ALWAYS, priority=1)
    evaluation = approval_service.evaluate(_context(scopes=[ApprovalScope.DELETE]))
    assert evaluation.required is False
    assert evaluation.policy_name == "never"


def test_scoped_policy_only_fires_on_matching_scope() -> None:
    _clear_policies()
    _policy(name="delete-guard", scopes=[ApprovalScope.DELETE])

    assert approval_service.evaluate(_context(scopes=[ApprovalScope.DELETE])).required is True
    assert approval_service.evaluate(_context(scopes=[ApprovalScope.NETWORK])).required is False


def test_cost_threshold_policy() -> None:
    _clear_policies()
    _policy(name="cost", scopes=[], cost_threshold=10.0)

    assert approval_service.evaluate(_context(estimated_cost=25.0)).required is True
    assert approval_service.evaluate(_context(estimated_cost=5.0)).required is False


def test_declarative_conditions_scope_a_policy() -> None:
    _clear_policies()
    _policy(
        name="prod-only",
        mode=ApprovalPolicyMode.ALWAYS,
        conditions=[ApprovalCondition(field="payload.env", operator="equals", value="prod")],
    )

    assert approval_service.evaluate(_context(payload={"env": "prod"})).required is True
    assert approval_service.evaluate(_context(payload={"env": "dev"})).required is False


def test_project_scoped_policy_beats_global_policy() -> None:
    _clear_policies()
    _policy(name="global", mode=ApprovalPolicyMode.ALWAYS)
    _policy(name="project-exempt", mode=ApprovalPolicyMode.NEVER, project_id="project-x")

    assert approval_service.evaluate(_context(project_id="project-x")).required is False
    assert approval_service.evaluate(_context(project_id="project-y")).required is True


def test_unsupported_condition_operator_raises() -> None:
    engine = ApprovalPolicyEngine()
    policy = ApprovalPolicy(
        name="bad",
        mode=ApprovalPolicyMode.ALWAYS,
        conditions=[ApprovalCondition(field="action", operator="regex", value=".*")],
    )
    with pytest.raises(ValueError, match="Unsupported approval condition operator"):
        engine.evaluate([policy], ApprovalContext(action="x"))


def test_all_supported_scopes_are_policy_addressable() -> None:
    _clear_policies()
    for scope in ApprovalScope:
        _clear_policies()
        _policy(name=f"guard-{scope.value}", scopes=[scope])
        assert approval_service.evaluate(_context(scopes=[scope])).required is True


# ---------------------------------------------------------------------------
# Request lifecycle
# ---------------------------------------------------------------------------


def test_create_approve_flow_and_history() -> None:
    _clear_policies()
    _policy(name="always", mode=ApprovalPolicyMode.ALWAYS)

    request = approval_service.create_request(title="Delete asset", context=_context())
    assert request.state is ApprovalState.PENDING

    approved = approval_service.approve(request.id, actor="ayoub", comment="looks fine")
    assert approved.state is ApprovalState.APPROVED
    assert approved.decided_at is not None

    history = approval_service.list_history(request.id)
    kinds = [event.event_type for event in history]
    assert "created" in kinds
    assert "approved" in kinds


def test_reject_flow() -> None:
    _clear_policies()
    _policy(name="always", mode=ApprovalPolicyMode.ALWAYS)
    request = approval_service.create_request(title="Publish", context=_context())

    rejected = approval_service.reject(request.id, actor="ayoub", comment="not yet")
    assert rejected.state is ApprovalState.REJECTED
    assert rejected.decisions[-1].comment == "not yet"


def test_cancel_flow() -> None:
    _clear_policies()
    _policy(name="always", mode=ApprovalPolicyMode.ALWAYS)
    request = approval_service.create_request(title="Cancel me", context=_context())

    cancelled = approval_service.cancel(request.id, actor="system", comment="superseded")
    assert cancelled.state is ApprovalState.CANCELLED


def test_terminal_requests_cannot_be_decided_again() -> None:
    _clear_policies()
    _policy(name="always", mode=ApprovalPolicyMode.ALWAYS)
    request = approval_service.create_request(title="Once", context=_context())
    approval_service.approve(request.id, actor="ayoub")

    with pytest.raises(ApprovalError, match="already approved"):
        approval_service.approve(request.id, actor="mani")
    with pytest.raises(ApprovalError, match="already approved"):
        approval_service.reject(request.id, actor="mani")


def test_requester_may_not_approve_their_own_request() -> None:
    _clear_policies()
    _policy(name="always", mode=ApprovalPolicyMode.ALWAYS)
    request = approval_service.create_request(title="Self", context=_context(requested_by="ayoub"))

    with pytest.raises(SelfApprovalError):
        approval_service.approve(request.id, actor="ayoub")


def test_only_designated_approvers_may_decide() -> None:
    _clear_policies()
    _policy(name="always", mode=ApprovalPolicyMode.ALWAYS, required_approvers=["mani"])
    request = approval_service.create_request(title="Restricted", context=_context())

    with pytest.raises(ApprovalError, match="not an approver"):
        approval_service.approve(request.id, actor="someone-else")

    assert approval_service.approve(request.id, actor="mani").state is ApprovalState.APPROVED


def test_multi_approver_quorum() -> None:
    _clear_policies()
    _policy(
        name="two-eyes",
        mode=ApprovalPolicyMode.ALWAYS,
        required_approvers=["ayoub", "mani"],
        approvals_required=2,
    )
    request = approval_service.create_request(title="Quorum", context=_context())

    first = approval_service.approve(request.id, actor="ayoub")
    assert first.state is ApprovalState.PENDING, "one approval must not satisfy a quorum of two"

    second = approval_service.approve(request.id, actor="mani")
    assert second.state is ApprovalState.APPROVED


def test_same_actor_cannot_approve_twice_to_reach_quorum() -> None:
    _clear_policies()
    _policy(
        name="two-eyes",
        mode=ApprovalPolicyMode.ALWAYS,
        required_approvers=["ayoub", "mani"],
        approvals_required=2,
    )
    request = approval_service.create_request(title="Quorum", context=_context())
    approval_service.approve(request.id, actor="ayoub")

    with pytest.raises(ApprovalError, match="already approved"):
        approval_service.approve(request.id, actor="ayoub")


def test_expiry_transitions_pending_request() -> None:
    _clear_policies()
    _policy(name="expiring", mode=ApprovalPolicyMode.ALWAYS, expires_after_seconds=1)
    request = approval_service.create_request(title="Expires", context=_context())
    assert request.expires_at is not None

    # Move the deadline into the past rather than sleeping.
    request.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    repository.update_approval_request(request)

    fetched = approval_service.get(request.id)
    assert fetched is not None
    assert fetched.state is ApprovalState.EXPIRED

    with pytest.raises(ApprovalError, match="already expired"):
        approval_service.approve(request.id, actor="ayoub")


def test_expire_due_sweep() -> None:
    _clear_policies()
    _policy(name="expiring", mode=ApprovalPolicyMode.ALWAYS, expires_after_seconds=1)
    request = approval_service.create_request(title="Sweep", context=_context())
    request.expires_at = datetime.now(UTC) - timedelta(seconds=5)
    repository.update_approval_request(request)

    expired_ids = {r.id for r in approval_service.expire_due()}
    assert request.id in expired_ids


def test_escalation_adds_approver() -> None:
    _clear_policies()
    _policy(name="always", mode=ApprovalPolicyMode.ALWAYS, required_approvers=["ayoub"])
    request = approval_service.create_request(title="Escalate", context=_context())

    escalated = approval_service.escalate(request.id, actor="ayoub", escalated_to="mani")
    assert "mani" in escalated.required_approvers
    assert approval_service.approve(request.id, actor="mani").state is ApprovalState.APPROVED


def test_request_changes_keeps_request_pending() -> None:
    _clear_policies()
    _policy(name="always", mode=ApprovalPolicyMode.ALWAYS)
    request = approval_service.create_request(title="Changes", context=_context())

    updated = approval_service.request_changes(request.id, actor="ayoub", comment="tweak it")
    assert updated.state is ApprovalState.PENDING
    assert updated.decisions[-1].comment == "tweak it"


def test_history_is_append_only() -> None:
    assert not hasattr(repository, "update_approval_history_event")
    assert not hasattr(repository, "delete_approval_history_event")
    assert not hasattr(repository, "delete_approval_history")


def test_pending_queue_is_priority_ordered() -> None:
    _clear_policies()
    _policy(name="always", mode=ApprovalPolicyMode.ALWAYS)
    low = approval_service.create_request(title="low", context=_context(), priority=1)
    high = approval_service.create_request(title="high", context=_context(), priority=99)

    ids = [r.id for r in approval_service.list_pending()]
    assert ids.index(high.id) < ids.index(low.id)


# ---------------------------------------------------------------------------
# Runtime waiting + scheduler pause
# ---------------------------------------------------------------------------


def test_runtime_pauses_and_creates_approval_when_policy_requires_it() -> None:
    _clear_policies()
    _policy(name="delete-guard", scopes=[ApprovalScope.DELETE])

    project_id = _create_project()
    agent_id = _create_agent(project_id)
    schedule_id, _entry_id = _schedule_with_scopes(agent_id, ["delete"])

    jobs_before = len(repository.list_jobs())
    executions = runtime.agent_runtime.start_schedule(schedule_id)
    assert len(executions) == 1
    execution = executions[0]

    assert execution.status is RuntimeExecutionStatus.WAITING_APPROVAL
    assert execution.approval_id is not None
    assert execution.job_id is None, "no job may be created before approval"
    assert len(repository.list_jobs()) == jobs_before, "no work reached the worker"
    assert execution.provider_name is None, "no provider may be selected before approval"

    schedule = repository.get_schedule(schedule_id)
    assert schedule is not None
    assert schedule.queue_entries[0].status is QueueEntryStatus.WAITING_APPROVAL


def test_api_runtime_start_is_gated_too() -> None:
    """Regression: AgentFoundation builds its own AgentRuntime, so the gate has
    to reach that one as well. Testing only the composition-root runtime once
    let an ungated execution path ship."""
    _clear_policies()
    _policy(name="delete-guard", scopes=[ApprovalScope.DELETE])

    project_id = _create_project()
    agent_id = _create_agent(project_id)
    schedule_id, _ = _schedule_with_scopes(agent_id, ["delete"])

    jobs_before = len(repository.list_jobs())
    response = client.post(f"/runtime/schedule/{schedule_id}/start")
    assert response.status_code == 200

    execution = response.json()[0]
    assert execution["status"] == "waiting_approval"
    assert execution["approval_id"] is not None
    assert execution["job_id"] is None
    assert execution["provider_name"] is None
    assert len(repository.list_jobs()) == jobs_before


def test_every_agent_runtime_in_the_api_carries_the_gate() -> None:
    from atlas_kernel.api import agent_foundation
    from atlas_kernel.api import runtime as composed

    assert composed.agent_runtime.approval_gate is not None
    assert agent_foundation._runtime.approval_gate is not None
    assert agent_foundation._runtime.approval_gate is composed.approval_gate


def test_scheduler_waiting_approval_is_distinct_from_ready() -> None:
    assert QueueEntryStatus.WAITING_APPROVAL != QueueEntryStatus.READY
    assert QueueEntryStatus.WAITING_APPROVAL.value == "waiting_approval"

    _clear_policies()
    _policy(name="delete-guard", scopes=[ApprovalScope.DELETE])
    project_id = _create_project()
    agent_id = _create_agent(project_id)
    schedule_id, entry_id = _schedule_with_scopes(agent_id, ["delete"])
    runtime.agent_runtime.start_schedule(schedule_id)

    queue = client.get(f"/scheduler/{schedule_id}/queue").json()
    entry = next(e for e in queue if e["id"] == entry_id)
    assert entry["status"] == "waiting_approval"
    assert entry["status"] != "ready"


def test_execution_resumes_and_completes_after_approval() -> None:
    _clear_policies()
    _policy(name="delete-guard", scopes=[ApprovalScope.DELETE])

    project_id = _create_project()
    agent_id = _create_agent(project_id)
    schedule_id, _ = _schedule_with_scopes(agent_id, ["delete"])
    execution = runtime.agent_runtime.start_schedule(schedule_id)[0]
    assert execution.status is RuntimeExecutionStatus.WAITING_APPROVAL

    approval_service.approve(execution.approval_id or "", actor="ayoub")

    resumed = runtime.agent_runtime.resume_after_approval(execution.execution_id)
    assert resumed.status is RuntimeExecutionStatus.COMPLETED
    assert resumed.job_id is not None
    assert resumed.provider_name is not None


def test_approval_is_linked_to_the_execution_it_gated() -> None:
    """Without this link the Approval Center cannot resume anything."""
    _clear_policies()
    _policy(name="delete-guard", scopes=[ApprovalScope.DELETE])

    project_id = _create_project()
    agent_id = _create_agent(project_id)
    schedule_id, entry_id = _schedule_with_scopes(agent_id, ["delete"])
    execution = runtime.agent_runtime.start_schedule(schedule_id)[0]

    approval = approval_service.get(execution.approval_id or "")
    assert approval is not None
    assert approval.execution_id == execution.execution_id
    assert approval.schedule_id == schedule_id
    assert approval.entry_id == entry_id


def test_resume_reuses_the_same_execution_record() -> None:
    """A resumed execution must keep its id, or the approval would point at a
    record that never completes."""
    _clear_policies()
    _policy(name="delete-guard", scopes=[ApprovalScope.DELETE])

    project_id = _create_project()
    agent_id = _create_agent(project_id)
    schedule_id, _ = _schedule_with_scopes(agent_id, ["delete"])
    paused = runtime.agent_runtime.start_schedule(schedule_id)[0]

    approval_service.approve(paused.approval_id or "", actor="ayoub")
    resumed = runtime.agent_runtime.resume_after_approval(paused.execution_id)

    assert resumed.execution_id == paused.execution_id
    assert resumed.status is RuntimeExecutionStatus.COMPLETED
    assert not any(
        e.status is RuntimeExecutionStatus.WAITING_APPROVAL
        and e.execution_id == paused.execution_id
        for e in runtime.agent_runtime.list_waiting_approval()
    )


def test_api_resume_execution_completes_the_paused_work() -> None:
    _clear_policies()
    _policy(name="delete-guard", scopes=[ApprovalScope.DELETE])

    project_id = _create_project()
    agent_id = _create_agent(project_id)
    schedule_id, _ = _schedule_with_scopes(agent_id, ["delete"])
    paused = client.post(f"/runtime/schedule/{schedule_id}/start").json()[0]

    client.post(f"/approvals/{paused['approval_id']}/approve", json={"actor": "ayoub"})
    resumed = client.post(f"/approvals/{paused['approval_id']}/resume-execution")

    assert resumed.status_code == 200
    body = resumed.json()
    assert body["status"] == "completed"
    assert body["job_id"] is not None
    assert body["provider_name"] is not None


def test_rejected_approval_blocks_execution_permanently() -> None:
    _clear_policies()
    _policy(name="delete-guard", scopes=[ApprovalScope.DELETE])

    project_id = _create_project()
    agent_id = _create_agent(project_id)
    schedule_id, _ = _schedule_with_scopes(agent_id, ["delete"])
    execution = runtime.agent_runtime.start_schedule(schedule_id)[0]

    approval_service.reject(execution.approval_id or "", actor="ayoub", comment="unsafe")

    jobs_before = len(repository.list_jobs())
    resumed = runtime.agent_runtime.resume_after_approval(execution.execution_id)

    assert resumed.status is RuntimeExecutionStatus.APPROVAL_REJECTED
    assert resumed.job_id is None
    assert len(repository.list_jobs()) == jobs_before

    schedule = repository.get_schedule(schedule_id)
    assert schedule is not None
    assert schedule.queue_entries[0].status is QueueEntryStatus.CANCELLED


def test_unapproved_execution_stays_paused_on_resume_attempt() -> None:
    _clear_policies()
    _policy(name="delete-guard", scopes=[ApprovalScope.DELETE])

    project_id = _create_project()
    agent_id = _create_agent(project_id)
    schedule_id, _ = _schedule_with_scopes(agent_id, ["delete"])
    execution = runtime.agent_runtime.start_schedule(schedule_id)[0]

    resumed = runtime.agent_runtime.resume_after_approval(execution.execution_id)
    assert resumed.status is RuntimeExecutionStatus.WAITING_APPROVAL
    assert resumed.job_id is None


def test_execution_without_matching_policy_runs_normally() -> None:
    _clear_policies()
    _policy(name="delete-guard", scopes=[ApprovalScope.DELETE])

    project_id = _create_project()
    agent_id = _create_agent(project_id)
    schedule_id, _ = _schedule_with_scopes(agent_id, ["network"])

    execution = runtime.agent_runtime.start_schedule(schedule_id)[0]
    assert execution.status is RuntimeExecutionStatus.COMPLETED
    assert execution.approval_id is None


def test_waiting_executions_are_listable() -> None:
    _clear_policies()
    _policy(name="delete-guard", scopes=[ApprovalScope.DELETE])
    project_id = _create_project()
    agent_id = _create_agent(project_id)
    schedule_id, _ = _schedule_with_scopes(agent_id, ["delete"])
    execution = runtime.agent_runtime.start_schedule(schedule_id)[0]

    waiting_ids = {e.execution_id for e in runtime.agent_runtime.list_waiting_approval()}
    assert execution.execution_id in waiting_ids

    listed = client.get("/approvals/waiting-executions").json()
    assert execution.execution_id in {e["execution_id"] for e in listed}


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_api_approval_round_trip() -> None:
    _clear_policies()
    created = client.post(
        "/approvals",
        json={
            "title": "API approval",
            "action": "asset.delete",
            "scopes": ["delete"],
            "requested_by": "atlas",
        },
    )
    assert created.status_code == 200
    approval_id = created.json()["id"]

    assert client.get(f"/approvals/{approval_id}").status_code == 200
    assert client.post(f"/approvals/{approval_id}/view", json={"actor": "ayoub"}).status_code == 200

    approved = client.post(
        f"/approvals/{approval_id}/approve", json={"actor": "ayoub", "comment": "ok"}
    )
    assert approved.status_code == 200
    assert approved.json()["state"] == "approved"

    history = client.get("/approvals/history", params={"approval_id": approval_id})
    assert history.status_code == 200
    assert {e["event_type"] for e in history.json()} >= {"created", "viewed", "approved"}


def test_api_self_approval_is_forbidden() -> None:
    created = client.post("/approvals", json={"title": "Self", "requested_by": "ayoub"}).json()
    response = client.post(f"/approvals/{created['id']}/approve", json={"actor": "ayoub"})
    assert response.status_code == 403


def test_api_deciding_twice_conflicts() -> None:
    created = client.post("/approvals", json={"title": "Twice", "requested_by": "atlas"}).json()
    client.post(f"/approvals/{created['id']}/approve", json={"actor": "ayoub"})
    again = client.post(f"/approvals/{created['id']}/reject", json={"actor": "mani"})
    assert again.status_code == 409


def test_api_missing_approval_is_404() -> None:
    assert client.get("/approvals/approval-does-not-exist").status_code == 404


def test_api_policy_upsert_and_list() -> None:
    _clear_policies()
    created = client.put(
        "/approval-policies",
        json={
            "name": "api-policy",
            "mode": "scoped",
            "scopes": ["network", "delete"],
            "required_approvers": ["ayoub"],
            "priority": 5,
        },
    )
    assert created.status_code == 200
    policy_id = created.json()["id"]

    listed = client.get("/approval-policies").json()
    assert policy_id in {p["id"] for p in listed}

    updated = client.put(
        "/approval-policies",
        json={"id": policy_id, "name": "api-policy-v2", "mode": "always"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "api-policy-v2"
    assert len(client.get("/approval-policies").json()) == 1, "upsert must not duplicate"


def test_api_pending_filter() -> None:
    _clear_policies()
    pending = client.post("/approvals", json={"title": "Pending", "requested_by": "atlas"}).json()
    decided = client.post("/approvals", json={"title": "Decided", "requested_by": "atlas"}).json()
    client.post(f"/approvals/{decided['id']}/approve", json={"actor": "ayoub"})

    pending_ids = {a["id"] for a in client.get("/approvals", params={"pending_only": True}).json()}
    assert pending["id"] in pending_ids
    assert decided["id"] not in pending_ids


def test_api_resume_execution_requires_approved_state() -> None:
    created = client.post("/approvals", json={"title": "No exec", "requested_by": "atlas"}).json()
    blocked = client.post(f"/approvals/{created['id']}/resume-execution")
    assert blocked.status_code == 409

    client.post(f"/approvals/{created['id']}/approve", json={"actor": "ayoub"})
    no_execution = client.post(f"/approvals/{created['id']}/resume-execution")
    assert no_execution.status_code == 409


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


def test_approval_events_are_emitted() -> None:
    from atlas_kernel.api import event_bus

    seen: list[str] = []
    for event_type in (ApprovalCreated, ApprovalApproved, ApprovalRejected):
        event_bus.subscribe(event_type, lambda e: seen.append(type(e).__name__))

    _clear_policies()
    _policy(name="always", mode=ApprovalPolicyMode.ALWAYS)
    approved = approval_service.create_request(title="Events", context=_context())
    approval_service.approve(approved.id, actor="ayoub")
    rejected = approval_service.create_request(title="Events", context=_context())
    approval_service.reject(rejected.id, actor="ayoub")

    assert {"ApprovalCreated", "ApprovalApproved", "ApprovalRejected"} <= set(seen)


def test_execution_waiting_approval_event_is_emitted() -> None:
    from atlas_kernel.api import event_bus

    seen: list[ExecutionWaitingApproval] = []
    event_bus.subscribe(ExecutionWaitingApproval, seen.append)

    _clear_policies()
    _policy(name="delete-guard", scopes=[ApprovalScope.DELETE])
    project_id = _create_project()
    agent_id = _create_agent(project_id)
    schedule_id, _ = _schedule_with_scopes(agent_id, ["delete"])
    runtime.agent_runtime.start_schedule(schedule_id)

    assert seen
    assert seen[-1].approval_id


# ---------------------------------------------------------------------------
# Architecture contracts
# ---------------------------------------------------------------------------


def test_approval_layer_never_touches_providers() -> None:
    for name in ("service.py", "policies.py", "gate.py", "models.py"):
        source = (KERNEL_ROOT / "approval" / name).read_text(encoding="utf-8")
        assert "ProviderManager" not in source
        assert "ProviderRouter" not in source
        assert "select_provider(" not in source
        assert "from ..providers" not in source


def test_approval_service_contains_no_auto_decision() -> None:
    """Nothing may approve on Atlas's behalf. Every transition out of PENDING
    other than expiry must carry a human actor."""
    tree = ast.parse((KERNEL_ROOT / "approval" / "service.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in {"approve", "reject"}:
            args = {a.arg for a in node.args.args}
            assert "actor" in args, f"{node.name} must require an actor"


def test_runtime_gate_is_optional_and_defaults_to_open() -> None:
    """A runtime built without a gate must behave exactly as before Milestone 008."""
    from atlas_kernel.agents.runtime import AgentRuntime

    bare = AgentRuntime()
    assert bare.approval_gate is None


def test_scheduler_was_not_redesigned() -> None:
    source = (KERNEL_ROOT / "agents" / "scheduler.py").read_text(encoding="utf-8")
    assert "approval" not in source.lower(), "scheduler must stay unaware of approvals"
