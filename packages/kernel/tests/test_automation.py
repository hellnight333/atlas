from __future__ import annotations

import ast
from pathlib import Path

from fastapi.testclient import TestClient

from atlas_kernel.api import app, automation_engine, repository
from atlas_kernel.event_bus import (
    AutomationCompleted,
    AutomationFailed,
    AutomationSkipped,
    AutomationStarted,
    AutomationTriggered,
)
from atlas_kernel.models import (
    AutomationAction,
    AutomationCondition,
    AutomationRunStatus,
    AutomationTrigger,
    AutomationTriggerType,
)

client = TestClient(app)

KERNEL_ROOT = Path(__file__).resolve().parents[1] / "atlas_kernel"


def _create_project() -> str:
    workspace = client.post(
        "/workspaces", json={"name": "automation-ws", "description": "automation"}
    )
    assert workspace.status_code == 200
    project = client.post(
        "/projects",
        json={
            "workspace_id": workspace.json()["workspace_id"],
            "name": "automation-project",
            "description": "automation",
        },
    )
    assert project.status_code == 200
    return project.json()["project_id"]


def _create_agent(project_id: str) -> str:
    agent = client.post(
        "/agents",
        json={
            "name": "Automation Agent",
            "description": "automation",
            "role": "operator",
            "project_id": project_id,
            "capabilities": ["text", "workflow"],
            "permission_set": ["read_assets", "execute_workflow"],
        },
    )
    assert agent.status_code == 200
    return agent.json()["id"]


def _rule_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Notify on approval",
        "description": "Send a notification when a review is approved",
        "trigger": {"type": "review_approved"},
        "conditions": [],
        "actions": [{"type": "send_notification", "payload": {"message": "approved"}}],
        "priority": 0,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Rule creation / CRUD
# ---------------------------------------------------------------------------


def test_rule_creation_persists_and_is_listable() -> None:
    project_id = _create_project()
    created = client.post("/automation", json=_rule_payload(project_id=project_id))
    assert created.status_code == 200

    rule = created.json()
    assert rule["enabled"] is True
    assert rule["trigger"]["type"] == "review_approved"
    assert len(rule["actions"]) == 1

    fetched = client.get(f"/automation/{rule['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "Notify on approval"

    listed = client.get("/automation", params={"project_id": project_id})
    assert listed.status_code == 200
    assert rule["id"] in [item["id"] for item in listed.json()]

    stored = repository.get_automation_rule(rule["id"])
    assert stored is not None
    assert stored.project_id == project_id


def test_rule_creation_rejects_unknown_action() -> None:
    response = client.post(
        "/automation", json=_rule_payload(actions=[{"type": "launch_missiles", "payload": {}}])
    )
    assert response.status_code == 400


def test_rule_update_and_delete() -> None:
    rule_id = client.post("/automation", json=_rule_payload()).json()["id"]

    updated = client.put(f"/automation/{rule_id}", json={"name": "Renamed", "priority": 10})
    assert updated.status_code == 200
    assert updated.json()["name"] == "Renamed"
    assert updated.json()["priority"] == 10

    deleted = client.delete(f"/automation/{rule_id}")
    assert deleted.status_code == 200
    assert client.get(f"/automation/{rule_id}").status_code == 404


def test_rules_are_ordered_by_priority_descending() -> None:
    project_id = _create_project()
    low = client.post("/automation", json=_rule_payload(project_id=project_id, priority=1)).json()
    high = client.post("/automation", json=_rule_payload(project_id=project_id, priority=99)).json()

    ordered = [
        item["id"] for item in client.get("/automation", params={"project_id": project_id}).json()
    ]
    assert ordered.index(high["id"]) < ordered.index(low["id"])


def test_conflict_detection_flags_same_trigger_and_priority() -> None:
    project_id = _create_project()
    first = client.post("/automation", json=_rule_payload(project_id=project_id, priority=5)).json()
    second = client.post(
        "/automation", json=_rule_payload(project_id=project_id, priority=5)
    ).json()

    conflicts = client.get("/automation/conflicts", params={"project_id": project_id})
    assert conflicts.status_code == 200
    conflicting_ids = {rule_id for entry in conflicts.json() for rule_id in entry["rule_ids"]}
    assert {first["id"], second["id"]} <= conflicting_ids


# ---------------------------------------------------------------------------
# Trigger evaluation
# ---------------------------------------------------------------------------


def test_trigger_evaluation_per_type() -> None:
    manual = automation_engine.create_rule(
        name="manual", description="", trigger=AutomationTrigger(type=AutomationTriggerType.MANUAL)
    )
    assert automation_engine.evaluate_trigger(manual) is True

    timer_no_interval = automation_engine.create_rule(
        name="timer-empty",
        description="",
        trigger=AutomationTrigger(type=AutomationTriggerType.TIMER),
    )
    assert automation_engine.evaluate_trigger(timer_no_interval) is False

    timer = automation_engine.create_rule(
        name="timer",
        description="",
        trigger=AutomationTrigger(type=AutomationTriggerType.TIMER, timer_seconds=60),
    )
    assert automation_engine.evaluate_trigger(timer) is True

    cron = automation_engine.create_rule(
        name="cron",
        description="",
        trigger=AutomationTrigger(type=AutomationTriggerType.CRON, cron_expression="0 * * * *"),
    )
    assert automation_engine.evaluate_trigger(cron) is True

    event_rule = automation_engine.create_rule(
        name="asset",
        description="",
        trigger=AutomationTrigger(type=AutomationTriggerType.ASSET_IMPORTED),
    )
    assert automation_engine.evaluate_trigger(event_rule, trigger_data=None) is False
    assert automation_engine.evaluate_trigger(event_rule, trigger_data={"asset_id": "a"}) is True


def test_trigger_evaluation_rejects_mismatched_trigger_type() -> None:
    rule = automation_engine.create_rule(
        name="asset-imported",
        description="",
        trigger=AutomationTrigger(type=AutomationTriggerType.ASSET_IMPORTED),
    )
    assert (
        automation_engine.evaluate_trigger(
            rule, AutomationTriggerType.WORKFLOW_FAILED, {"asset_id": "a"}
        )
        is False
    )


def test_timer_trigger_registers_automation_schedule() -> None:
    rule = automation_engine.create_rule(
        name="timer-schedule",
        description="",
        trigger=AutomationTrigger(type=AutomationTriggerType.TIMER, timer_seconds=120),
    )
    schedule = repository.get_automation_schedule_for_rule(rule.id)
    assert schedule is not None
    assert schedule.next_run is not None


# ---------------------------------------------------------------------------
# Condition evaluation
# ---------------------------------------------------------------------------


def test_condition_evaluation_operators() -> None:
    rule = automation_engine.create_rule(
        name="conditions",
        description="",
        trigger=AutomationTrigger(type=AutomationTriggerType.MANUAL),
        conditions=[
            AutomationCondition(type="studio", operator="equals", value="image"),
            AutomationCondition(type="tags", operator="contains", value="hero"),
            AutomationCondition(type="score", operator="greater_than", value=5),
            AutomationCondition(type="asset_id", operator="exists", value=None),
        ],
    )

    assert automation_engine.evaluate_conditions(
        rule, {"studio": "image", "tags": ["hero"], "score": 9, "asset_id": "asset-1"}
    )
    assert not automation_engine.evaluate_conditions(
        rule, {"studio": "video", "tags": ["hero"], "score": 9, "asset_id": "asset-1"}
    )
    assert not automation_engine.evaluate_conditions(
        rule, {"studio": "image", "tags": ["hero"], "score": 1, "asset_id": "asset-1"}
    )
    assert not automation_engine.evaluate_conditions(
        rule, {"studio": "image", "tags": ["hero"], "score": 9}
    )


def test_condition_negative_and_range_operators() -> None:
    rule = automation_engine.create_rule(
        name="more-operators",
        description="",
        trigger=AutomationTrigger(type=AutomationTriggerType.MANUAL),
        conditions=[
            AutomationCondition(type="studio", operator="not_equals", value="video"),
            AutomationCondition(type="user", operator="in", value=["ayoub", "mani"]),
            AutomationCondition(type="tags", operator="not_contains", value="draft"),
            AutomationCondition(type="score", operator="less_than", value=10),
            AutomationCondition(type="hour", operator="between", value=[9, 17]),
            AutomationCondition(type="error", operator="not_exists", value=None),
        ],
    )
    passing = {"studio": "image", "user": "ayoub", "tags": ["hero"], "score": 3, "hour": 12}
    assert automation_engine.evaluate_conditions(rule, passing) is True

    assert not automation_engine.evaluate_conditions(rule, {**passing, "studio": "video"})
    assert not automation_engine.evaluate_conditions(rule, {**passing, "user": "someone"})
    assert not automation_engine.evaluate_conditions(rule, {**passing, "tags": ["draft"]})
    assert not automation_engine.evaluate_conditions(rule, {**passing, "score": 50})
    assert not automation_engine.evaluate_conditions(rule, {**passing, "hour": 22})
    assert not automation_engine.evaluate_conditions(rule, {**passing, "error": "boom"})


def test_unsupported_condition_operator_raises() -> None:
    import pytest

    rule = automation_engine.create_rule(
        name="bad-operator",
        description="",
        trigger=AutomationTrigger(type=AutomationTriggerType.MANUAL),
        conditions=[AutomationCondition(type="studio", operator="regex_match", value=".*")],
    )
    with pytest.raises(ValueError, match="Unsupported condition operator"):
        automation_engine.evaluate_conditions(rule, {"studio": "image"})


def test_graph_relationship_condition() -> None:
    from atlas_kernel.api import graph_service
    from atlas_kernel.models import KnowledgeEdge, KnowledgeNode, RelationshipType

    source = graph_service.create_node(KnowledgeNode(node_type="asset", label="source"))
    target = graph_service.create_node(KnowledgeNode(node_type="asset", label="target"))
    graph_service.create_edge(
        KnowledgeEdge(
            relationship=RelationshipType.DERIVED_FROM, from_node=source.id, to_node=target.id
        )
    )

    rule = automation_engine.create_rule(
        name="graph-condition",
        description="",
        trigger=AutomationTrigger(type=AutomationTriggerType.MANUAL),
        conditions=[
            AutomationCondition(
                type="asset_id", operator="graph_relationship_exists", value="derived_from"
            )
        ],
    )

    assert automation_engine.evaluate_conditions(rule, {"asset_id": source.id}) is True
    assert automation_engine.evaluate_conditions(rule, {"asset_id": target.id}) is False
    assert automation_engine.evaluate_conditions(rule, {}) is False


def test_empty_conditions_always_match() -> None:
    rule = automation_engine.create_rule(
        name="no-conditions",
        description="",
        trigger=AutomationTrigger(type=AutomationTriggerType.MANUAL),
    )
    assert automation_engine.evaluate_conditions(rule, {}) is True


def test_conditions_not_met_skips_run() -> None:
    rule = automation_engine.create_rule(
        name="skip-on-conditions",
        description="",
        trigger=AutomationTrigger(type=AutomationTriggerType.MANUAL),
        conditions=[AutomationCondition(type="studio", operator="equals", value="image")],
        actions=[AutomationAction(type="send_notification", payload={"message": "hi"})],
    )
    run = automation_engine.run_rule(rule.id, trigger_data={"studio": "video"})
    assert run.status is AutomationRunStatus.SKIPPED
    assert run.outputs["skip_reason"] == "conditions not met"


# ---------------------------------------------------------------------------
# Scheduler + runtime integration
# ---------------------------------------------------------------------------


def test_executable_action_submits_through_scheduler_and_runtime() -> None:
    project_id = _create_project()
    agent_id = _create_agent(project_id)

    rule = automation_engine.create_rule(
        name="generate-image",
        description="",
        project_id=project_id,
        trigger=AutomationTrigger(type=AutomationTriggerType.MANUAL),
        actions=[AutomationAction(type="generate_image", payload={"prompt": "a blue ant"})],
    )

    run = automation_engine.run_rule(rule.id, agent_id=agent_id)
    assert run.status is AutomationRunStatus.COMPLETED, run.error

    schedule_id = run.outputs["schedule_id"]
    assert repository.get_schedule(schedule_id) is not None

    execution_ids = run.outputs["execution_ids"]
    assert execution_ids
    execution = repository.get_runtime_execution(execution_ids[0])
    assert execution is not None
    assert execution.status.value == "completed"
    # Runtime — not automation — owns provider selection.
    assert execution.provider_name is not None
    assert execution.job_id is not None


def test_state_action_never_creates_scheduler_or_runtime_work() -> None:
    schedules_before = len(repository.list_schedules())
    executions_before = len(repository.list_runtime_executions())

    rule = automation_engine.create_rule(
        name="notify-only",
        description="",
        trigger=AutomationTrigger(type=AutomationTriggerType.MANUAL),
        actions=[AutomationAction(type="send_notification", payload={"message": "done"})],
    )
    run = automation_engine.run_rule(rule.id)

    assert run.status is AutomationRunStatus.COMPLETED
    assert "schedule_id" not in run.outputs
    assert len(repository.list_schedules()) == schedules_before
    assert len(repository.list_runtime_executions()) == executions_before


def test_rule_priority_maps_to_scheduler_priority() -> None:
    project_id = _create_project()
    agent_id = _create_agent(project_id)

    rule = automation_engine.create_rule(
        name="urgent",
        description="",
        project_id=project_id,
        priority=100,
        trigger=AutomationTrigger(type=AutomationTriggerType.MANUAL),
        actions=[AutomationAction(type="generate_asset", payload={"prompt": "summary"})],
    )
    run = automation_engine.run_rule(rule.id, agent_id=agent_id)
    schedule = repository.get_schedule(run.outputs["schedule_id"])
    assert schedule is not None
    assert schedule.priority.value == "immediate"


def test_scheduler_priority_tiers() -> None:
    from atlas_kernel.models import AutomationRule

    def priority_for(value: int) -> str:
        rule = AutomationRule(
            id="tmp",
            name="tmp",
            description="",
            priority=value,
            trigger=AutomationTrigger(type=AutomationTriggerType.MANUAL),
        )
        return automation_engine._scheduler_priority(rule).value

    assert priority_for(100) == "immediate"
    assert priority_for(50) == "high"
    assert priority_for(0) == "normal"
    assert priority_for(-1) == "low"
    assert priority_for(-50) == "background"


def test_update_rule_rejects_unknown_action() -> None:
    import pytest

    rule = automation_engine.create_rule(
        name="update-guard",
        description="",
        trigger=AutomationTrigger(type=AutomationTriggerType.MANUAL),
    )
    with pytest.raises(ValueError, match="Unsupported automation action"):
        automation_engine.update_rule(rule.id, {"actions": [{"type": "self_destruct"}]})


def test_missing_rule_raises_value_error() -> None:
    import pytest

    with pytest.raises(ValueError, match="Automation rule not found"):
        automation_engine.run_rule("automation-does-not-exist")


def test_cron_rule_registers_schedule_without_next_run() -> None:
    rule = automation_engine.create_rule(
        name="cron-schedule",
        description="",
        trigger=AutomationTrigger(type=AutomationTriggerType.CRON, cron_expression="0 9 * * *"),
    )
    schedule = repository.get_automation_schedule_for_rule(rule.id)
    assert schedule is not None
    assert schedule.next_run is None


def test_timer_rule_advances_next_run_after_execution() -> None:
    rule = automation_engine.create_rule(
        name="timer-advance",
        description="",
        trigger=AutomationTrigger(type=AutomationTriggerType.TIMER, timer_seconds=60),
        actions=[AutomationAction(type="send_notification", payload={"message": "tick"})],
    )
    before = repository.get_automation_schedule_for_rule(rule.id)
    assert before is not None and before.last_run is None

    automation_engine.run_rule(rule.id)

    after = repository.get_automation_schedule_for_rule(rule.id)
    assert after is not None
    assert after.last_run is not None
    assert after.next_run is not None
    assert automation_engine.get_state(rule.id).next_run_at is not None


def test_deleting_rule_removes_its_schedule() -> None:
    rule = automation_engine.create_rule(
        name="timer-delete",
        description="",
        trigger=AutomationTrigger(type=AutomationTriggerType.TIMER, timer_seconds=30),
    )
    assert repository.get_automation_schedule_for_rule(rule.id) is not None

    automation_engine.delete_rule(rule.id)
    assert repository.get_automation_schedule_for_rule(rule.id) is None


def test_archive_and_metadata_state_actions_mutate_asset() -> None:
    from atlas_kernel.models import Asset

    project_id = _create_project()
    asset = repository.create_asset(
        Asset(project_id=project_id, type="image", uri="atlas://automation-asset")
    )

    rule = automation_engine.create_rule(
        name="asset-ops",
        description="",
        project_id=project_id,
        trigger=AutomationTrigger(type=AutomationTriggerType.MANUAL),
        actions=[
            AutomationAction(type="archive_asset", payload={"asset_id": asset.id}),
            AutomationAction(
                type="update_metadata",
                payload={"asset_id": asset.id, "metadata": {"campaign": "summer"}},
            ),
        ],
    )
    run = automation_engine.run_rule(rule.id)
    assert run.status is AutomationRunStatus.COMPLETED

    stored = repository.get_asset(asset.id)
    assert stored is not None
    assert stored.metadata["archived"] is True
    assert stored.metadata["campaign"] == "summer"


def test_publish_state_action_marks_asset_published() -> None:
    from atlas_kernel.models import Asset

    project_id = _create_project()
    asset = repository.create_asset(
        Asset(project_id=project_id, type="image", uri="atlas://publish-me")
    )
    rule = automation_engine.create_rule(
        name="publisher",
        description="",
        project_id=project_id,
        trigger=AutomationTrigger(type=AutomationTriggerType.MANUAL),
        actions=[AutomationAction(type="publish_asset", payload={"asset_id": asset.id})],
    )
    automation_engine.run_rule(rule.id)

    stored = repository.get_asset(asset.id)
    assert stored is not None and stored.metadata["published"] is True


def test_trigger_not_satisfied_skips_run() -> None:
    rule = automation_engine.create_rule(
        name="unsatisfied-trigger",
        description="",
        trigger=AutomationTrigger(type=AutomationTriggerType.ASSET_IMPORTED),
        actions=[AutomationAction(type="send_notification", payload={"message": "x"})],
    )
    run = automation_engine.run_rule(rule.id, trigger_data=None)
    assert run.status is AutomationRunStatus.SKIPPED
    assert run.outputs["skip_reason"] == "trigger not satisfied"


def test_handle_event_skips_disabled_rules() -> None:
    project_id = _create_project()
    rule = automation_engine.create_rule(
        name="disabled-listener",
        description="",
        project_id=project_id,
        trigger=AutomationTrigger(type=AutomationTriggerType.PROJECT_OPENED),
        actions=[AutomationAction(type="send_notification", payload={"message": "opened"})],
    )
    automation_engine.disable_rule(rule.id)

    runs = automation_engine.handle_event(
        AutomationTriggerType.PROJECT_OPENED, {"project_id": project_id}
    )
    assert rule.id not in {run.rule_id for run in runs}


def test_dry_run_helper_matches_dry_run_endpoint() -> None:
    rule = automation_engine.create_rule(
        name="dry-helper",
        description="",
        trigger=AutomationTrigger(type=AutomationTriggerType.MANUAL),
        actions=[AutomationAction(type="create_report", payload={"title": "preview"})],
    )
    run = automation_engine.dry_run(rule.id)
    assert run.status is AutomationRunStatus.COMPLETED
    assert run.outputs["dry_run"] is True
    assert run.outputs["state_actions"][0]["applied"] is False


# ---------------------------------------------------------------------------
# History, logs, audit
# ---------------------------------------------------------------------------


def test_history_records_timing_and_status() -> None:
    rule = automation_engine.create_rule(
        name="history",
        description="",
        trigger=AutomationTrigger(type=AutomationTriggerType.MANUAL),
        actions=[AutomationAction(type="create_task", payload={"title": "follow up"})],
    )
    automation_engine.run_rule(rule.id)
    automation_engine.run_rule(rule.id)

    history = client.get(f"/automation/{rule.id}/history")
    assert history.status_code == 200
    entries = history.json()
    assert len(entries) == 2
    for entry in entries:
        assert entry["status"] == "completed"
        assert entry["start_time"] is not None
        assert entry["end_time"] is not None
        assert entry["duration_ms"] is not None
        assert entry["triggered_by"] == "manual"


def test_logs_are_recorded_per_run() -> None:
    rule = automation_engine.create_rule(
        name="logs",
        description="",
        trigger=AutomationTrigger(type=AutomationTriggerType.MANUAL),
        actions=[AutomationAction(type="send_notification", payload={"message": "logged"})],
    )
    run = automation_engine.run_rule(rule.id)

    logs = client.get("/automation/logs", params={"run_id": run.id}).json()
    assert logs
    assert any(entry["message"] == "send_notification" for entry in logs)


def test_audit_trail_captures_actor_for_each_change() -> None:
    rule = automation_engine.create_rule(
        name="audited",
        description="",
        trigger=AutomationTrigger(type=AutomationTriggerType.MANUAL),
        actor="ayoub",
    )
    automation_engine.update_rule(rule.id, {"name": "audited-v2"}, actor="mani")
    automation_engine.disable_rule(rule.id, actor="ayoub")
    automation_engine.enable_rule(rule.id, actor="mani")

    logs = automation_engine.list_logs(rule_id=rule.id)
    messages = {(log.message.split("'")[0].strip(), log.actor) for log in logs}
    assert ("Rule", "ayoub") in {(m.split()[0], a) for m, a in messages}
    actors = {log.actor for log in logs}
    assert {"ayoub", "mani"} <= actors


def test_state_endpoint_reports_run_summary() -> None:
    rule = automation_engine.create_rule(
        name="stateful",
        description="",
        trigger=AutomationTrigger(type=AutomationTriggerType.MANUAL),
        actions=[AutomationAction(type="create_report", payload={"title": "weekly"})],
    )
    automation_engine.run_rule(rule.id)

    state = client.get(f"/automation/{rule.id}/state").json()
    assert state["rule_id"] == rule.id
    assert state["enabled"] is True
    assert state["total_runs"] == 1
    assert state["last_status"] == "completed"
    assert state["failure_count"] == 0


# ---------------------------------------------------------------------------
# Retry, timeout, failure
# ---------------------------------------------------------------------------


def test_retry_count_recorded_from_runtime_attempts() -> None:
    project_id = _create_project()
    agent_id = _create_agent(project_id)

    rule = automation_engine.create_rule(
        name="retrying",
        description="",
        project_id=project_id,
        trigger=AutomationTrigger(type=AutomationTriggerType.MANUAL),
        actions=[AutomationAction(type="generate_image", payload={"prompt": "retry me"})],
        schedule={"retry_policy": {"max_attempts": 3, "retry_delay": 0.0}},
    )
    run = automation_engine.run_rule(rule.id, agent_id=agent_id)

    assert run.status is AutomationRunStatus.COMPLETED
    assert run.retries >= 0


def test_timeout_marks_run_failed_and_records_error() -> None:
    project_id = _create_project()
    agent_id = _create_agent(project_id)

    rule = automation_engine.create_rule(
        name="timing-out",
        description="",
        project_id=project_id,
        trigger=AutomationTrigger(type=AutomationTriggerType.MANUAL),
        actions=[AutomationAction(type="generate_image", payload={"prompt": "slow"})],
    )
    run = automation_engine.run_rule(rule.id, agent_id=agent_id, timeout_seconds=0.0)

    assert run.status is AutomationRunStatus.FAILED
    assert run.error
    assert run.end_time is not None
    assert run.duration_ms is not None

    state = automation_engine.get_state(rule.id)
    assert state.failure_count == 1


def test_failed_state_action_marks_run_failed() -> None:
    rule = automation_engine.create_rule(
        name="bad-asset",
        description="",
        trigger=AutomationTrigger(type=AutomationTriggerType.MANUAL),
        actions=[AutomationAction(type="archive_asset", payload={})],
    )
    run = automation_engine.run_rule(rule.id)

    assert run.status is AutomationRunStatus.FAILED
    assert "asset_id" in (run.error or "")


def test_run_does_not_raise_into_the_trigger_path() -> None:
    rule = automation_engine.create_rule(
        name="never-raises",
        description="",
        trigger=AutomationTrigger(type=AutomationTriggerType.ASSET_UPDATED),
        actions=[AutomationAction(type="publish_asset", payload={"asset_id": "missing"})],
    )
    runs = automation_engine.handle_event(
        AutomationTriggerType.ASSET_UPDATED, {"asset_id": "missing"}
    )
    assert any(r.rule_id == rule.id and r.status is AutomationRunStatus.FAILED for r in runs)


# ---------------------------------------------------------------------------
# Enable / disable / dry run
# ---------------------------------------------------------------------------


def test_disabled_rule_is_skipped_and_creates_no_work() -> None:
    project_id = _create_project()
    agent_id = _create_agent(project_id)
    schedules_before = len(repository.list_schedules())

    rule = automation_engine.create_rule(
        name="disabled",
        description="",
        project_id=project_id,
        trigger=AutomationTrigger(type=AutomationTriggerType.MANUAL),
        actions=[AutomationAction(type="generate_image", payload={"prompt": "nope"})],
    )
    automation_engine.disable_rule(rule.id)

    run = automation_engine.run_rule(rule.id, agent_id=agent_id)
    assert run.status is AutomationRunStatus.SKIPPED
    assert run.outputs["skip_reason"] == "rule disabled"
    assert len(repository.list_schedules()) == schedules_before


def test_enable_disable_round_trip_via_api() -> None:
    rule_id = client.post("/automation", json=_rule_payload()).json()["id"]

    disabled = client.post(f"/automation/{rule_id}/disable")
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert disabled.json()["disabled_at"] is not None

    enabled = client.post(f"/automation/{rule_id}/enable")
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True
    assert enabled.json()["disabled_at"] is None


def test_dry_run_plans_without_scheduling_or_executing() -> None:
    project_id = _create_project()
    agent_id = _create_agent(project_id)
    schedules_before = len(repository.list_schedules())
    executions_before = len(repository.list_runtime_executions())

    rule = automation_engine.create_rule(
        name="dry",
        description="",
        project_id=project_id,
        trigger=AutomationTrigger(type=AutomationTriggerType.MANUAL),
        actions=[AutomationAction(type="generate_image", payload={"prompt": "preview"})],
    )

    response = client.post(f"/automation/{rule.id}/dry-run", json={"agent_id": agent_id})
    assert response.status_code == 200
    run = response.json()

    assert run["status"] == "completed"
    assert run["outputs"]["dry_run"] is True
    assert run["outputs"]["planned_steps"][0]["action"] == "image.generate"
    assert "schedule_id" not in run["outputs"]
    assert len(repository.list_schedules()) == schedules_before
    assert len(repository.list_runtime_executions()) == executions_before


def test_rule_level_dry_run_flag_is_honoured() -> None:
    project_id = _create_project()
    agent_id = _create_agent(project_id)

    rule = automation_engine.create_rule(
        name="always-dry",
        description="",
        project_id=project_id,
        dry_run=True,
        trigger=AutomationTrigger(type=AutomationTriggerType.MANUAL),
        actions=[AutomationAction(type="generate_image", payload={"prompt": "preview"})],
    )
    run = automation_engine.run_rule(rule.id, agent_id=agent_id)
    assert run.outputs["dry_run"] is True
    assert "schedule_id" not in run.outputs


# ---------------------------------------------------------------------------
# Event bus + graph
# ---------------------------------------------------------------------------


def test_event_bus_emits_full_lifecycle() -> None:
    from atlas_kernel.api import event_bus

    seen: list[str] = []
    for event_type in (
        AutomationTriggered,
        AutomationStarted,
        AutomationCompleted,
        AutomationFailed,
        AutomationSkipped,
    ):
        event_bus.subscribe(event_type, lambda e: seen.append(type(e).__name__))

    rule = automation_engine.create_rule(
        name="events",
        description="",
        trigger=AutomationTrigger(type=AutomationTriggerType.MANUAL),
        actions=[AutomationAction(type="send_notification", payload={"message": "ping"})],
    )
    automation_engine.run_rule(rule.id)
    assert {"AutomationTriggered", "AutomationStarted", "AutomationCompleted"} <= set(seen)

    automation_engine.disable_rule(rule.id)
    automation_engine.run_rule(rule.id)
    assert "AutomationSkipped" in seen


def test_graph_lineage_links_run_to_rule() -> None:
    from atlas_kernel.api import graph_service

    project_id = _create_project()
    agent_id = _create_agent(project_id)

    rule = automation_engine.create_rule(
        name="graphed",
        description="",
        project_id=project_id,
        trigger=AutomationTrigger(type=AutomationTriggerType.MANUAL),
        actions=[AutomationAction(type="generate_image", payload={"prompt": "lineage"})],
    )
    assert graph_service.get_node(rule.id) is not None

    run = automation_engine.run_rule(rule.id, agent_id=agent_id)
    assert run.status is AutomationRunStatus.COMPLETED

    assert graph_service.get_node(run.id) is not None
    edges = graph_service.outgoing_edges(run.id)
    assert any(
        edge.to_node == rule.id and edge.relationship.value == "executed_by" for edge in edges
    )


def test_handle_event_dispatches_only_matching_enabled_rules() -> None:
    project_id = _create_project()

    matching = automation_engine.create_rule(
        name="on-workflow-completed",
        description="",
        project_id=project_id,
        trigger=AutomationTrigger(type=AutomationTriggerType.WORKFLOW_COMPLETED),
        actions=[AutomationAction(type="send_notification", payload={"message": "wf done"})],
    )
    other = automation_engine.create_rule(
        name="on-workflow-failed",
        description="",
        project_id=project_id,
        trigger=AutomationTrigger(type=AutomationTriggerType.WORKFLOW_FAILED),
        actions=[AutomationAction(type="send_notification", payload={"message": "wf failed"})],
    )

    runs = automation_engine.handle_event(
        AutomationTriggerType.WORKFLOW_COMPLETED, {"workflow_id": "wf-1"}
    )
    rule_ids = {run.rule_id for run in runs}
    assert matching.id in rule_ids
    assert other.id not in rule_ids


# ---------------------------------------------------------------------------
# Architecture contracts
# ---------------------------------------------------------------------------


def test_automation_engine_never_touches_providers() -> None:
    source = (KERNEL_ROOT / "automation_engine.py").read_text(encoding="utf-8")

    assert "ProviderManager" not in source
    assert "ProviderRouter" not in source
    assert "select_provider(" not in source
    assert "ExecutionPolicyEngine" not in source
    assert "from .providers" not in source


def test_automation_engine_only_enqueues_through_scheduler_and_runtime() -> None:
    tree = ast.parse((KERNEL_ROOT / "automation_engine.py").read_text(encoding="utf-8"))
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert "create_schedule" in called
    assert "start_schedule" in called
    # The engine must not reach into the worker or executor layers itself.
    assert "execute" not in called
    assert "run_job" not in called


def test_automation_engine_is_constructed_only_in_composition_root() -> None:
    for path in KERNEL_ROOT.glob("*.py"):
        if path.name in {"composition_root.py", "automation_engine.py"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "AutomationEngine"
            ):
                raise AssertionError(
                    f"{path.name} constructs AutomationEngine outside composition root"
                )
