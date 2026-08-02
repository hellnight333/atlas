from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import uuid4

from .agents.plan_models import PlanStep
from .agents.runtime import AgentRuntime
from .agents.schedule_models import (
    RuntimeRetryPolicy,
    SchedulerPriority,
    SchedulerRequest,
)
from .agents.scheduler import AgentScheduler
from .event_bus import (
    AutomationCompleted,
    AutomationFailed,
    AutomationRuleCreated,
    AutomationRuleDeleted,
    AutomationRuleDisabled,
    AutomationRuleEnabled,
    AutomationRuleUpdated,
    AutomationSkipped,
    AutomationStarted,
    AutomationTriggered,
    EventBus,
)
from .graph_service import GraphService
from .models import (
    AutomationAction,
    AutomationCondition,
    AutomationLog,
    AutomationLogLevel,
    AutomationRule,
    AutomationRun,
    AutomationRunStatus,
    AutomationSchedule,
    AutomationState,
    AutomationTrigger,
    AutomationTriggerType,
    KnowledgeEdge,
    KnowledgeNode,
    RelationshipType,
)
from .repository import AtlasRepository


class AutomationActionKind(StrEnum):
    """Executable work leaves the engine via Scheduler -> Runtime -> Worker.
    State work only mutates kernel records and never reaches a provider."""

    EXECUTABLE = "executable"
    STATE = "state"


@dataclass(frozen=True)
class AutomationActionSpec:
    kind: AutomationActionKind
    kernel_action: str = ""
    capability: str = ""


ACTION_CATALOG: dict[str, AutomationActionSpec] = {
    "run_planner": AutomationActionSpec(AutomationActionKind.EXECUTABLE, "text.generate", "planning"),
    "queue_workflow": AutomationActionSpec(AutomationActionKind.EXECUTABLE, "text.generate", "workflow"),
    "start_runtime": AutomationActionSpec(AutomationActionKind.EXECUTABLE, "text.generate", "workflow"),
    "generate_asset": AutomationActionSpec(AutomationActionKind.EXECUTABLE, "text.generate", "text"),
    "generate_image": AutomationActionSpec(AutomationActionKind.EXECUTABLE, "image.generate", "image"),
    "generate_video": AutomationActionSpec(AutomationActionKind.EXECUTABLE, "video.generate", "media"),
    "run_review": AutomationActionSpec(AutomationActionKind.STATE),
    "send_notification": AutomationActionSpec(AutomationActionKind.STATE),
    "create_task": AutomationActionSpec(AutomationActionKind.STATE),
    "create_report": AutomationActionSpec(AutomationActionKind.STATE),
    "archive_asset": AutomationActionSpec(AutomationActionKind.STATE),
    "publish_asset": AutomationActionSpec(AutomationActionKind.STATE),
    "update_metadata": AutomationActionSpec(AutomationActionKind.STATE),
}


EVENT_TRIGGER_TYPES: frozenset[AutomationTriggerType] = frozenset(
    {
        AutomationTriggerType.ASSET_IMPORTED,
        AutomationTriggerType.ASSET_UPDATED,
        AutomationTriggerType.ASSET_PUBLISHED,
        AutomationTriggerType.REVIEW_APPROVED,
        AutomationTriggerType.REVIEW_REJECTED,
        AutomationTriggerType.WORKFLOW_COMPLETED,
        AutomationTriggerType.WORKFLOW_FAILED,
        AutomationTriggerType.AGENT_COMPLETED,
        AutomationTriggerType.PROJECT_CREATED,
        AutomationTriggerType.PROJECT_OPENED,
        AutomationTriggerType.RESEARCH_COMPLETED,
        AutomationTriggerType.IMAGE_GENERATED,
        AutomationTriggerType.VIDEO_GENERATED,
    }
)


class AutomationEngine:
    """Deterministic rule engine. Never selects a provider and never executes one.
    Executable actions are handed to the scheduler; the runtime owns execution."""

    def __init__(
        self,
        repository: AtlasRepository,
        event_bus: EventBus,
        scheduler: AgentScheduler,
        runtime: AgentRuntime,
        graph_service: GraphService | None = None,
    ) -> None:
        self.repository = repository
        self.event_bus = event_bus
        self.scheduler = scheduler
        self.runtime = runtime
        self.graph_service = graph_service

    # ------------------------------------------------------------------
    # Rule lifecycle
    # ------------------------------------------------------------------

    def create_rule(
        self,
        *,
        name: str,
        description: str,
        trigger: AutomationTrigger,
        conditions: list[AutomationCondition] | None = None,
        actions: list[AutomationAction] | None = None,
        project_id: str | None = None,
        workspace_id: str | None = None,
        schedule: dict[str, Any] | None = None,
        priority: int = 0,
        dry_run: bool = False,
        actor: str = "system",
    ) -> AutomationRule:
        actions = actions or []
        for action in actions:
            if action.type not in ACTION_CATALOG:
                raise ValueError(f"Unsupported automation action: {action.type}")

        now = datetime.now(UTC)
        rule = AutomationRule(
            id=f"automation-{uuid4().hex[:12]}",
            project_id=project_id,
            workspace_id=workspace_id,
            name=name,
            description=description,
            trigger=trigger,
            conditions=conditions or [],
            actions=actions,
            schedule=schedule,
            priority=priority,
            dry_run=dry_run,
            created_at=now,
            updated_at=now,
        )
        self.repository.create_automation_rule(rule)
        self._audit(rule.id, f"Rule '{rule.name}' created", actor)
        self._register_schedule(rule)
        self._graph_rule_node(rule)
        self.event_bus.publish(
            AutomationRuleCreated(rule_id=rule.id, name=rule.name, project_id=rule.project_id)
        )
        return rule

    def get_rule(self, rule_id: str) -> AutomationRule | None:
        return self.repository.get_automation_rule(rule_id)

    def list_rules(
        self, project_id: str | None = None, workspace_id: str | None = None
    ) -> list[AutomationRule]:
        rules = self.repository.list_automation_rules(
            project_id=project_id, workspace_id=workspace_id
        )
        return sorted(rules, key=lambda rule: (-rule.priority, rule.created_at, rule.id))

    def update_rule(self, rule_id: str, changes: dict[str, Any], actor: str = "system") -> AutomationRule:
        rule = self._require_rule(rule_id)
        for action in changes.get("actions", []) or []:
            action_type = action.type if isinstance(action, AutomationAction) else action.get("type")
            if action_type not in ACTION_CATALOG:
                raise ValueError(f"Unsupported automation action: {action_type}")

        updated = rule.model_copy(update={**changes, "updated_at": datetime.now(UTC)})
        self.repository.update_automation_rule(updated)
        self._audit(rule_id, f"Rule '{updated.name}' updated", actor, context={"fields": sorted(changes)})
        self._register_schedule(updated)
        self.event_bus.publish(AutomationRuleUpdated(rule_id=updated.id, name=updated.name))
        return updated

    def delete_rule(self, rule_id: str, actor: str = "system") -> None:
        rule = self._require_rule(rule_id)
        self.repository.delete_automation_rule(rule_id)
        self.repository.delete_automation_schedules_for_rule(rule_id)
        self._audit(rule_id, f"Rule '{rule.name}' deleted", actor)
        self.event_bus.publish(AutomationRuleDeleted(rule_id=rule_id))

    def enable_rule(self, rule_id: str, actor: str = "system") -> AutomationRule:
        rule = self._require_rule(rule_id)
        updated = rule.model_copy(
            update={"enabled": True, "disabled_at": None, "updated_at": datetime.now(UTC)}
        )
        self.repository.update_automation_rule(updated)
        self._audit(rule_id, f"Rule '{updated.name}' enabled", actor)
        self.event_bus.publish(AutomationRuleEnabled(rule_id=rule_id))
        return updated

    def disable_rule(self, rule_id: str, actor: str = "system") -> AutomationRule:
        rule = self._require_rule(rule_id)
        now = datetime.now(UTC)
        updated = rule.model_copy(update={"enabled": False, "disabled_at": now, "updated_at": now})
        self.repository.update_automation_rule(updated)
        self._audit(rule_id, f"Rule '{updated.name}' disabled", actor)
        self.event_bus.publish(AutomationRuleDisabled(rule_id=rule_id))
        return updated

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate_trigger(
        self,
        rule: AutomationRule,
        trigger_type: AutomationTriggerType | None = None,
        trigger_data: dict[str, Any] | None = None,
    ) -> bool:
        if trigger_type is not None and rule.trigger.type != trigger_type:
            return False
        if rule.trigger.type == AutomationTriggerType.MANUAL:
            return True
        if rule.trigger.type == AutomationTriggerType.TIMER:
            return bool(rule.trigger.timer_seconds)
        if rule.trigger.type == AutomationTriggerType.CRON:
            return bool(rule.trigger.cron_expression)
        if rule.trigger.type in EVENT_TRIGGER_TYPES:
            return trigger_data is not None
        return False

    def evaluate_conditions(self, rule: AutomationRule, context: dict[str, Any] | None = None) -> bool:
        context = context or {}
        return all(self._evaluate_condition(condition, context) for condition in rule.conditions)

    def _evaluate_condition(self, condition: AutomationCondition, context: dict[str, Any]) -> bool:
        operator = condition.operator
        if operator == "graph_relationship_exists":
            return self._graph_relationship_exists(condition, context)

        present = condition.type in context
        value = context.get(condition.type)

        if operator == "exists":
            return present and value is not None
        if operator == "not_exists":
            return not present or value is None
        if operator == "equals":
            return value == condition.value
        if operator == "not_equals":
            return value != condition.value
        if operator == "in":
            return value in (condition.value or [])
        if operator == "contains":
            return value is not None and condition.value in value
        if operator == "not_contains":
            return value is None or condition.value not in value
        if operator == "greater_than":
            return value is not None and value > condition.value
        if operator == "less_than":
            return value is not None and value < condition.value
        if operator == "between":
            low, high = condition.value
            return value is not None and low <= value <= high
        raise ValueError(f"Unsupported condition operator: {operator}")

    def _graph_relationship_exists(
        self, condition: AutomationCondition, context: dict[str, Any]
    ) -> bool:
        if self.graph_service is None:
            return False
        node_id = context.get(condition.type)
        if not node_id:
            return False
        edges = self.graph_service.outgoing_edges(str(node_id))
        return any(edge.relationship.value == condition.value for edge in edges)

    def detect_conflicts(
        self, project_id: str | None = None, workspace_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Two enabled rules sharing a trigger and priority have no deterministic order."""
        conflicts: list[dict[str, Any]] = []
        buckets: dict[tuple[str, int], list[AutomationRule]] = {}
        for rule in self.list_rules(project_id=project_id, workspace_id=workspace_id):
            if not rule.enabled:
                continue
            buckets.setdefault((rule.trigger.type.value, rule.priority), []).append(rule)
        for (trigger_type, priority), rules in buckets.items():
            if len(rules) > 1:
                conflicts.append(
                    {
                        "trigger": trigger_type,
                        "priority": priority,
                        "rule_ids": [rule.id for rule in rules],
                    }
                )
        return conflicts

    # ------------------------------------------------------------------
    # Dispatch and execution
    # ------------------------------------------------------------------

    def handle_event(
        self,
        trigger_type: AutomationTriggerType,
        trigger_data: dict[str, Any] | None = None,
        *,
        agent_id: str | None = None,
    ) -> list[AutomationRun]:
        """Entry point for event-driven triggers. Rules fire in deterministic priority order."""
        runs: list[AutomationRun] = []
        for rule in self.list_rules():
            if rule.trigger.type != trigger_type:
                continue
            if not rule.enabled:
                self.event_bus.publish(AutomationSkipped(rule_id=rule.id, reason="rule disabled"))
                continue
            runs.append(self.run_rule(rule.id, trigger_data=trigger_data, agent_id=agent_id))
        return runs

    def run_rule(
        self,
        rule_id: str,
        *,
        trigger_data: dict[str, Any] | None = None,
        dry_run: bool = False,
        agent_id: str | None = None,
        actor: str = "system",
        timeout_seconds: float = 30.0,
    ) -> AutomationRun:
        rule = self._require_rule(rule_id)
        effective_dry_run = dry_run or rule.dry_run

        run = AutomationRun(
            id=f"automation-run-{uuid4().hex[:12]}",
            rule_id=rule.id,
            triggered_by=rule.trigger.type.value,
            status=AutomationRunStatus.PENDING,
            start_time=datetime.now(UTC),
            trigger_data=trigger_data or {},
        )
        self.repository.create_automation_run(run)
        self.event_bus.publish(
            AutomationTriggered(
                rule_id=rule.id, run_id=run.id, trigger_type=rule.trigger.type.value
            )
        )

        if not rule.enabled:
            return self._skip(run, rule, "rule disabled")
        # Passed through un-normalized: an event trigger with no payload must not fire.
        if not self.evaluate_trigger(rule, rule.trigger.type, trigger_data):
            return self._skip(run, rule, "trigger not satisfied")
        if not self.evaluate_conditions(rule, run.trigger_data):
            return self._skip(run, rule, "conditions not met")

        run.status = AutomationRunStatus.RUNNING
        self.repository.update_automation_run(run)
        self.event_bus.publish(AutomationStarted(run_id=run.id, rule_id=rule.id))
        self._audit(rule.id, f"Rule '{rule.name}' execution started", actor, run_id=run.id)

        try:
            outputs = self._execute_actions(
                rule,
                run,
                dry_run=effective_dry_run,
                agent_id=agent_id,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001 - recorded on the run, never raised to the trigger
            return self._fail(run, rule, str(exc))

        run.status = AutomationRunStatus.COMPLETED
        run.outputs = outputs
        run.end_time = datetime.now(UTC)
        run.duration_ms = int((run.end_time - run.start_time).total_seconds() * 1000)
        self.repository.update_automation_run(run)
        self._mark_schedule_ran(rule)
        self.event_bus.publish(
            AutomationCompleted(run_id=run.id, rule_id=rule.id, duration_ms=run.duration_ms)
        )
        return run

    def dry_run(self, rule_id: str, trigger_data: dict[str, Any] | None = None) -> AutomationRun:
        return self.run_rule(rule_id, trigger_data=trigger_data, dry_run=True)

    def _execute_actions(
        self,
        rule: AutomationRule,
        run: AutomationRun,
        *,
        dry_run: bool,
        agent_id: str | None,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        executable: list[AutomationAction] = []
        state_results: list[dict[str, Any]] = []

        for action in rule.actions:
            spec = ACTION_CATALOG[action.type]
            if spec.kind is AutomationActionKind.EXECUTABLE:
                executable.append(action)
            else:
                state_results.append(self._apply_state_action(rule, run, action, dry_run=dry_run))

        outputs: dict[str, Any] = {"state_actions": state_results, "dry_run": dry_run}

        if not executable:
            return outputs

        steps = [self._plan_step_for(action) for action in executable]
        outputs["planned_steps"] = [
            {"id": step.id, "action": step.action, "capability": step.capability} for step in steps
        ]

        if dry_run:
            self._log(
                run,
                rule,
                f"[dry-run] {len(steps)} step(s) would be submitted to the scheduler",
                context={"steps": outputs["planned_steps"]},
            )
            return outputs

        resolved_agent_id = agent_id or self._resolve_agent_id(rule)
        if resolved_agent_id is None:
            raise ValueError("No agent available to own automation execution")

        schedule = self.scheduler.create_schedule(
            SchedulerRequest(
                plan_id=f"automation-plan-{run.id}",
                agent_id=resolved_agent_id,
                steps=steps,
                priority=self._scheduler_priority(rule),
                workspace_state={"automation_rule_id": rule.id, "automation_run_id": run.id},
                available_executors=["local"],
                execution_policy={},
            )
        )
        outputs["schedule_id"] = schedule.schedule_id
        self._log(run, rule, f"Submitted schedule {schedule.schedule_id}")

        retry_policy = RuntimeRetryPolicy(**(rule.schedule or {}).get("retry_policy", {}))
        executions = self.runtime.start_schedule(
            schedule.schedule_id,
            retry_policy=retry_policy,
            timeout_seconds=timeout_seconds,
        )
        outputs["execution_ids"] = [execution.execution_id for execution in executions]
        run.retries = sum(max(0, execution.attempts - 1) for execution in executions)

        failed = [e for e in executions if e.status.value in {"failed", "timed_out"}]
        if failed:
            reasons = "; ".join(f"{e.execution_id}: {e.error or e.timeout_reason}" for e in failed)
            raise RuntimeError(f"Runtime execution failed: {reasons}")

        self._graph_execution_lineage(rule, run, schedule.schedule_id, executions)
        return outputs

    def _plan_step_for(self, action: AutomationAction) -> PlanStep:
        spec = ACTION_CATALOG[action.type]
        return PlanStep(
            description=f"Automation action: {action.type}",
            capability=spec.capability,
            action=spec.kernel_action,
            payload=dict(action.payload),
            expected_output=str(action.metadata.get("expected_output", action.type)),
        )

    def _apply_state_action(
        self, rule: AutomationRule, run: AutomationRun, action: AutomationAction, *, dry_run: bool
    ) -> dict[str, Any]:
        prefix = "[dry-run] " if dry_run else ""
        result: dict[str, Any] = {"type": action.type, "applied": not dry_run}

        if not dry_run and action.type in {"archive_asset", "publish_asset", "update_metadata"}:
            asset_id = action.payload.get("asset_id")
            if not asset_id:
                raise ValueError(f"{action.type} requires asset_id")
            asset = self.repository.get_asset(str(asset_id))
            if asset is None:
                raise ValueError(f"Asset not found: {asset_id}")
            metadata = dict(asset.metadata)
            if action.type == "archive_asset":
                metadata["archived"] = True
            elif action.type == "publish_asset":
                metadata["published"] = True
            else:
                metadata.update(action.payload.get("metadata", {}))
            self.repository.update_asset(asset.model_copy(update={"metadata": metadata}))
            result["asset_id"] = asset_id

        self._log(run, rule, f"{prefix}{action.type}", context=dict(action.payload))
        return result

    def _resolve_agent_id(self, rule: AutomationRule) -> str | None:
        agents = self.repository.list_agents(project_id=rule.project_id)
        if not agents:
            agents = self.repository.list_agents()
        return agents[0].id if agents else None

    def _scheduler_priority(self, rule: AutomationRule) -> SchedulerPriority:
        if rule.priority >= 100:
            return SchedulerPriority.IMMEDIATE
        if rule.priority >= 50:
            return SchedulerPriority.HIGH
        if rule.priority <= -50:
            return SchedulerPriority.BACKGROUND
        if rule.priority < 0:
            return SchedulerPriority.LOW
        return SchedulerPriority.NORMAL

    # ------------------------------------------------------------------
    # History and state
    # ------------------------------------------------------------------

    def list_runs(self, rule_id: str | None = None) -> list[AutomationRun]:
        return self.repository.list_automation_runs(rule_id=rule_id)

    def list_logs(self, run_id: str | None = None, rule_id: str | None = None) -> list[AutomationLog]:
        return self.repository.list_automation_logs(run_id=run_id, rule_id=rule_id)

    def get_state(self, rule_id: str) -> AutomationState:
        rule = self._require_rule(rule_id)
        runs = self.repository.list_automation_runs(rule_id=rule_id)
        schedule = self.repository.get_automation_schedule_for_rule(rule_id)
        latest = runs[0] if runs else None
        return AutomationState(
            rule_id=rule_id,
            enabled=rule.enabled,
            last_run_id=latest.id if latest else None,
            last_status=latest.status if latest else None,
            last_run_at=latest.start_time if latest else None,
            next_run_at=schedule.next_run if schedule else None,
            total_runs=len(runs),
            failure_count=sum(1 for r in runs if r.status is AutomationRunStatus.FAILED),
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _require_rule(self, rule_id: str) -> AutomationRule:
        rule = self.repository.get_automation_rule(rule_id)
        if rule is None:
            raise ValueError(f"Automation rule not found: {rule_id}")
        return rule

    def _skip(self, run: AutomationRun, rule: AutomationRule, reason: str) -> AutomationRun:
        run.status = AutomationRunStatus.SKIPPED
        run.end_time = datetime.now(UTC)
        run.duration_ms = int((run.end_time - run.start_time).total_seconds() * 1000)
        run.outputs = {"skip_reason": reason}
        self.repository.update_automation_run(run)
        self._log(run, rule, f"Skipped: {reason}", level=AutomationLogLevel.WARNING)
        self.event_bus.publish(AutomationSkipped(rule_id=rule.id, reason=reason))
        return run

    def _fail(self, run: AutomationRun, rule: AutomationRule, reason: str) -> AutomationRun:
        run.status = AutomationRunStatus.FAILED
        run.error = reason
        run.end_time = datetime.now(UTC)
        run.duration_ms = int((run.end_time - run.start_time).total_seconds() * 1000)
        self.repository.update_automation_run(run)
        self._log(run, rule, f"Failed: {reason}", level=AutomationLogLevel.ERROR)
        self.event_bus.publish(AutomationFailed(run_id=run.id, rule_id=rule.id, reason=reason))
        return run

    def _log(
        self,
        run: AutomationRun,
        rule: AutomationRule,
        message: str,
        *,
        level: AutomationLogLevel = AutomationLogLevel.INFO,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.repository.create_automation_log(
            AutomationLog(
                run_id=run.id,
                rule_id=rule.id,
                level=level,
                message=message,
                context=context or {},
            )
        )

    def _audit(
        self,
        rule_id: str,
        message: str,
        actor: str,
        *,
        run_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.repository.create_automation_log(
            AutomationLog(
                run_id=run_id,
                rule_id=rule_id,
                level=AutomationLogLevel.INFO,
                message=message,
                actor=actor,
                context=context or {},
            )
        )

    def _register_schedule(self, rule: AutomationRule) -> None:
        if rule.trigger.type not in {AutomationTriggerType.TIMER, AutomationTriggerType.CRON}:
            return
        existing = self.repository.get_automation_schedule_for_rule(rule.id)
        next_run = None
        if rule.trigger.type is AutomationTriggerType.TIMER and rule.trigger.timer_seconds:
            next_run = datetime.now(UTC) + timedelta(seconds=rule.trigger.timer_seconds)
        record = AutomationSchedule(
            id=existing.id if existing else f"automation-schedule-{uuid4().hex[:12]}",
            rule_id=rule.id,
            next_run=next_run,
            last_run=existing.last_run if existing else None,
            updated_at=datetime.now(UTC),
        )
        self.repository.upsert_automation_schedule(record)

    def _mark_schedule_ran(self, rule: AutomationRule) -> None:
        existing = self.repository.get_automation_schedule_for_rule(rule.id)
        if existing is None:
            return
        now = datetime.now(UTC)
        next_run = None
        if rule.trigger.type is AutomationTriggerType.TIMER and rule.trigger.timer_seconds:
            next_run = now + timedelta(seconds=rule.trigger.timer_seconds)
        self.repository.upsert_automation_schedule(
            existing.model_copy(update={"last_run": now, "next_run": next_run, "updated_at": now})
        )

    def _graph_rule_node(self, rule: AutomationRule) -> None:
        if self.graph_service is None:
            return
        self.graph_service.create_node(
            KnowledgeNode(
                id=rule.id,
                node_type="automation_rule",
                label=rule.name,
                project_id=rule.project_id,
                workspace_id=rule.workspace_id,
                source_id=rule.id,
                metadata={"trigger": rule.trigger.type.value},
            )
        )

    def _graph_execution_lineage(
        self,
        rule: AutomationRule,
        run: AutomationRun,
        schedule_id: str,
        executions: list[Any],
    ) -> None:
        if self.graph_service is None:
            return
        self.graph_service.create_node(
            KnowledgeNode(
                id=run.id,
                node_type="automation_run",
                label=f"{rule.name} run",
                project_id=rule.project_id,
                workspace_id=rule.workspace_id,
                source_id=run.id,
                metadata={"schedule_id": schedule_id},
            )
        )
        self.graph_service.create_edge(
            KnowledgeEdge(
                relationship=RelationshipType.EXECUTED_BY,
                from_node=run.id,
                to_node=rule.id,
            )
        )
        for execution in executions:
            if execution.asset_id:
                self.graph_service.create_edge(
                    KnowledgeEdge(
                        relationship=RelationshipType.GENERATED_FROM,
                        from_node=execution.asset_id,
                        to_node=run.id,
                    )
                )
