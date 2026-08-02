from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .event_bus import (
    CheckpointCreated,
    EventBus,
    ExecutionPaused,
    ExecutionResumed,
    NodeCompleted,
    NodeFailed,
    NodeStarted,
    WorkflowCompleted,
    WorkflowFailed,
    WorkflowStarted,
)
from .models import CapabilityRequest, normalize_capability_request
from .orchestrator import Orchestrator
from .worker import Worker


class ExecutionState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class FailureStrategy(StrEnum):
    FAIL_FAST = "fail_fast"
    CONTINUE = "continue"


class RetryPolicy(BaseModel):
    max_retries: int = 0
    retry_delay_seconds: float = 0.0
    failure_strategy: FailureStrategy = FailureStrategy.FAIL_FAST


class Condition(BaseModel):
    expression: str | None = None


class WorkflowNode(BaseModel):
    id: str
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    input_asset_ids: list[str] = Field(default_factory=list)
    output_labels: list[str] = Field(default_factory=list)
    capability_req: CapabilityRequest = Field(default_factory=CapabilityRequest)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    condition: Condition | None = None


class WorkflowDefinition(BaseModel):
    id: str
    name: str
    project_id: str = "project-unassigned"
    workflow_id: str | None = None
    nodes: list[WorkflowNode]


class ExecutionPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    workflow_definition_id: str
    node_ids: tuple[str, ...]
    levels: tuple[tuple[str, ...], ...]
    edges: tuple[tuple[str, str], ...]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class NodeExecutionRecord(BaseModel):
    node_id: str
    state: ExecutionState = ExecutionState.PENDING
    attempts: int = 0
    job_id: str | None = None
    produced_asset_ids: list[str] = Field(default_factory=list)
    error: str | None = None


class Checkpoint(BaseModel):
    id: str
    execution_id: str
    state: ExecutionState
    snapshot: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WorkflowExecution(BaseModel):
    id: str
    workflow_definition_id: str
    run_id: str
    project_id: str
    workflow_id: str | None = None
    state: ExecutionState = ExecutionState.PENDING
    plan: ExecutionPlan
    nodes: dict[str, NodeExecutionRecord]
    checkpoints: list[Checkpoint] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class NodeExecutionResult(BaseModel):
    status: ExecutionState
    job_id: str | None = None
    produced_asset_ids: list[str] = Field(default_factory=list)
    error: str | None = None


class WorkflowValidationResult(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    plan: ExecutionPlan | None = None


class WorkflowNodeDelegate:
    def execute_node(
        self,
        node: WorkflowNode,
        run_id: str,
        project_id: str,
        workflow_id: str | None,
        input_asset_ids: list[str],
    ) -> NodeExecutionResult:
        raise NotImplementedError()


class KernelWorkflowNodeDelegate(WorkflowNodeDelegate):
    def __init__(self, orchestrator: Orchestrator, worker: Worker) -> None:
        self.orchestrator = orchestrator
        self.worker = worker

    def execute_node(
        self,
        node: WorkflowNode,
        run_id: str,
        project_id: str,
        workflow_id: str | None,
        input_asset_ids: list[str],
    ) -> NodeExecutionResult:
        if node.action == "asset.import":
            return NodeExecutionResult(
                status=ExecutionState.COMPLETED,
                job_id=None,
                produced_asset_ids=list(input_asset_ids),
            )

        if node.action in {"asset.save", "workflow.end"}:
            return NodeExecutionResult(
                status=ExecutionState.COMPLETED,
                job_id=None,
                produced_asset_ids=list(input_asset_ids),
            )

        payload = dict(node.payload)
        if input_asset_ids:
            payload["input_asset_ids"] = input_asset_ids
        payload.setdefault("project_id", project_id)
        if workflow_id is not None:
            payload.setdefault("workflow_id", workflow_id)

        job = self.orchestrator.enqueue_job(
            run_id=run_id,
            action=node.action,
            payload=payload,
            capability_req=node.capability_req,
        )
        result = self.worker.execute_job(job)
        status = (
            ExecutionState.COMPLETED
            if result.get("status") == "completed"
            else ExecutionState.FAILED
        )
        produced_asset_ids: list[str] = []
        asset_id = result.get("asset_id")
        if isinstance(asset_id, str) and asset_id:
            produced_asset_ids.append(asset_id)
        return NodeExecutionResult(
            status=status,
            job_id=job.id,
            produced_asset_ids=produced_asset_ids,
            error=result.get("error") if status == ExecutionState.FAILED else None,
        )


class WorkflowEngine:
    def __init__(self, delegate: WorkflowNodeDelegate, bus: EventBus) -> None:
        self.delegate = delegate
        self.bus = bus
        self._definitions: dict[str, WorkflowDefinition] = {}
        self._executions: dict[str, WorkflowExecution] = {}

    def create_workflow(self, definition: WorkflowDefinition) -> WorkflowDefinition:
        validation = self.validate_workflow(definition)
        if not validation.valid:
            raise ValueError("; ".join(validation.errors))
        self._definitions[definition.id] = definition
        return definition

    def get_workflow(self, workflow_definition_id: str) -> WorkflowDefinition | None:
        return self._definitions.get(workflow_definition_id)

    def list_workflows(self) -> list[WorkflowDefinition]:
        return list(self._definitions.values())

    def validate_workflow(self, definition: WorkflowDefinition) -> WorkflowValidationResult:
        errors: list[str] = []
        node_ids = [node.id for node in definition.nodes]
        if len(node_ids) != len(set(node_ids)):
            errors.append("duplicate node ids are not allowed")

        node_map = {node.id: node for node in definition.nodes}
        for node in definition.nodes:
            for dep in node.depends_on:
                if dep not in node_map:
                    errors.append(f"node {node.id} depends on unknown node {dep}")
            capability_request = normalize_capability_request(node.capability_req)
            if not capability_request.capability_id:
                errors.append(f"node {node.id} must define capability_id")

        if errors:
            return WorkflowValidationResult(valid=False, errors=errors)

        try:
            plan = self._build_execution_plan(definition)
        except ValueError as exc:
            return WorkflowValidationResult(valid=False, errors=[str(exc)])

        return WorkflowValidationResult(valid=True, plan=plan)

    def execute_workflow(self, workflow_definition_id: str, run_id: str) -> WorkflowExecution:
        definition = self._definitions.get(workflow_definition_id)
        if definition is None:
            raise ValueError("workflow definition not found")

        validation = self.validate_workflow(definition)
        if not validation.valid or validation.plan is None:
            raise ValueError("invalid workflow definition")

        plan = validation.plan
        execution_id = str(uuid4())
        records = {node.id: NodeExecutionRecord(node_id=node.id) for node in definition.nodes}
        execution = WorkflowExecution(
            id=execution_id,
            workflow_definition_id=workflow_definition_id,
            run_id=run_id,
            project_id=definition.project_id,
            workflow_id=definition.workflow_id,
            state=ExecutionState.RUNNING,
            plan=plan,
            nodes=records,
        )
        self._executions[execution.id] = execution

        self.bus.publish(
            WorkflowStarted(
                workflow_id=definition.workflow_id or workflow_definition_id, run_id=run_id
            )
        )
        self._create_checkpoint(execution, label="start")

        node_map = {node.id: node for node in definition.nodes}
        completed: set[str] = set()
        failed = False

        for level in plan.levels:
            if execution.state in {ExecutionState.CANCELLED, ExecutionState.PAUSED}:
                break

            runnable_nodes = [
                node_map[node_id]
                for node_id in level
                if self._dependencies_satisfied(node_map[node_id], completed)
            ]
            if not runnable_nodes:
                continue

            with ThreadPoolExecutor(max_workers=max(1, len(runnable_nodes))) as pool:
                futures = {}
                for node in runnable_nodes:
                    record = execution.nodes[node.id]
                    record.state = ExecutionState.RUNNING
                    self.bus.publish(
                        NodeStarted(
                            workflow_id=definition.workflow_id or workflow_definition_id,
                            run_id=run_id,
                            node_id=node.id,
                        )
                    )
                    upstream_assets = self._collect_input_assets(execution, node)
                    futures[
                        pool.submit(
                            self._execute_with_retry, definition, node, run_id, upstream_assets
                        )
                    ] = node

                for future in as_completed(futures):
                    node = futures[future]
                    record = execution.nodes[node.id]
                    result = future.result()
                    record.attempts += 1
                    record.job_id = result.job_id
                    record.produced_asset_ids = result.produced_asset_ids
                    record.error = result.error

                    if result.status == ExecutionState.COMPLETED:
                        record.state = ExecutionState.COMPLETED
                        completed.add(node.id)
                        self.bus.publish(
                            NodeCompleted(
                                workflow_id=definition.workflow_id or workflow_definition_id,
                                run_id=run_id,
                                node_id=node.id,
                                asset_ids=result.produced_asset_ids,
                            )
                        )
                    else:
                        record.state = ExecutionState.FAILED
                        failed = True
                        self.bus.publish(
                            NodeFailed(
                                workflow_id=definition.workflow_id or workflow_definition_id,
                                run_id=run_id,
                                node_id=node.id,
                                reason=result.error or "node execution failed",
                            )
                        )
                        if node.retry_policy.failure_strategy == FailureStrategy.FAIL_FAST:
                            execution.state = ExecutionState.FAILED
                            break

            if execution.state == ExecutionState.FAILED:
                break

        if execution.state not in {
            ExecutionState.PAUSED,
            ExecutionState.CANCELLED,
            ExecutionState.FAILED,
        }:
            blocked_nodes = [
                node.id
                for node in definition.nodes
                if execution.nodes[node.id].state == ExecutionState.PENDING
                and any(
                    execution.nodes[dep].state == ExecutionState.FAILED for dep in node.depends_on
                )
            ]
            for node_id in blocked_nodes:
                execution.nodes[node_id].state = ExecutionState.SKIPPED

            if failed:
                execution.state = ExecutionState.FAILED
            else:
                execution.state = ExecutionState.COMPLETED

        execution.updated_at = datetime.now(UTC)
        self._create_checkpoint(execution, label="end")

        if execution.state == ExecutionState.COMPLETED:
            self.bus.publish(
                WorkflowCompleted(
                    workflow_id=definition.workflow_id or workflow_definition_id, run_id=run_id
                )
            )
        elif execution.state == ExecutionState.FAILED:
            self.bus.publish(
                WorkflowFailed(
                    workflow_id=definition.workflow_id or workflow_definition_id,
                    run_id=run_id,
                    reason="workflow execution failed",
                )
            )

        return execution

    def pause_execution(self, execution_id: str) -> WorkflowExecution:
        execution = self._require_execution(execution_id)
        execution.state = ExecutionState.PAUSED
        execution.updated_at = datetime.now(UTC)
        self._create_checkpoint(execution, label="paused")
        self.bus.publish(
            ExecutionPaused(
                workflow_id=execution.workflow_id or execution.workflow_definition_id,
                run_id=execution.run_id,
            )
        )
        return execution

    def resume_execution(self, execution_id: str) -> WorkflowExecution:
        execution = self._require_execution(execution_id)
        execution.state = ExecutionState.RUNNING
        execution.updated_at = datetime.now(UTC)
        self._create_checkpoint(execution, label="resumed")
        self.bus.publish(
            ExecutionResumed(
                workflow_id=execution.workflow_id or execution.workflow_definition_id,
                run_id=execution.run_id,
            )
        )
        return execution

    def cancel_execution(self, execution_id: str) -> WorkflowExecution:
        execution = self._require_execution(execution_id)
        execution.state = ExecutionState.CANCELLED
        execution.updated_at = datetime.now(UTC)
        self._create_checkpoint(execution, label="cancelled")
        return execution

    def inspect_execution_plan(self, execution_id: str) -> ExecutionPlan:
        execution = self._require_execution(execution_id)
        return execution.plan

    def get_execution(self, execution_id: str) -> WorkflowExecution | None:
        return self._executions.get(execution_id)

    def list_executions(self) -> list[WorkflowExecution]:
        return list(self._executions.values())

    def get_execution_timeline(self, execution_id: str) -> list[dict[str, Any]]:
        execution = self._require_execution(execution_id)
        timeline: list[dict[str, Any]] = []

        for checkpoint in execution.checkpoints:
            timeline.append(
                {
                    "id": checkpoint.id,
                    "type": "checkpoint",
                    "state": checkpoint.state.value,
                    "label": checkpoint.snapshot.get("label", "checkpoint"),
                    "created_at": checkpoint.created_at.isoformat(),
                    "nodes": checkpoint.snapshot.get("nodes", {}),
                }
            )

        for record in execution.nodes.values():
            timeline.append(
                {
                    "id": f"node-{record.node_id}",
                    "type": "node",
                    "node_id": record.node_id,
                    "state": record.state.value,
                    "attempts": record.attempts,
                    "job_id": record.job_id,
                    "produced_asset_ids": list(record.produced_asset_ids),
                    "error": record.error,
                }
            )

        return timeline

    def _execute_with_retry(
        self,
        definition: WorkflowDefinition,
        node: WorkflowNode,
        run_id: str,
        input_asset_ids: list[str],
    ) -> NodeExecutionResult:
        attempts = 0
        while True:
            result = self.delegate.execute_node(
                node=node,
                run_id=run_id,
                project_id=definition.project_id,
                workflow_id=definition.workflow_id,
                input_asset_ids=input_asset_ids,
            )
            if result.status == ExecutionState.COMPLETED:
                return result
            attempts += 1
            if attempts > node.retry_policy.max_retries:
                return result
            if node.retry_policy.retry_delay_seconds > 0:
                time.sleep(node.retry_policy.retry_delay_seconds)

    def _build_execution_plan(self, definition: WorkflowDefinition) -> ExecutionPlan:
        node_ids = [node.id for node in definition.nodes]
        deps = {node.id: set(node.depends_on) for node in definition.nodes}
        children: dict[str, set[str]] = {node.id: set() for node in definition.nodes}
        for node in definition.nodes:
            for dep in node.depends_on:
                children[dep].add(node.id)

        indegree = {node_id: len(dep_set) for node_id, dep_set in deps.items()}
        queue = [node_id for node_id, degree in indegree.items() if degree == 0]
        levels: list[list[str]] = []
        visited = 0

        while queue:
            current_level = sorted(queue)
            levels.append(current_level)
            next_queue: list[str] = []
            for node_id in current_level:
                visited += 1
                for child in children[node_id]:
                    indegree[child] -= 1
                    if indegree[child] == 0:
                        next_queue.append(child)
            queue = next_queue

        if visited != len(node_ids):
            raise ValueError("workflow graph contains a cycle")

        edges = [(dep, node.id) for node in definition.nodes for dep in node.depends_on]
        return ExecutionPlan(
            id=str(uuid4()),
            workflow_definition_id=definition.id,
            node_ids=tuple(node_ids),
            levels=tuple(tuple(level) for level in levels),
            edges=tuple(edges),
        )

    def _dependencies_satisfied(self, node: WorkflowNode, completed: set[str]) -> bool:
        return all(dep in completed for dep in node.depends_on)

    def _collect_input_assets(self, execution: WorkflowExecution, node: WorkflowNode) -> list[str]:
        collected = list(node.input_asset_ids)
        for dep in node.depends_on:
            for asset_id in execution.nodes[dep].produced_asset_ids:
                if asset_id not in collected:
                    collected.append(asset_id)
        return collected

    def _create_checkpoint(self, execution: WorkflowExecution, label: str) -> None:
        snapshot = {
            "label": label,
            "execution_state": execution.state.value,
            "nodes": {node_id: record.state.value for node_id, record in execution.nodes.items()},
        }
        checkpoint = Checkpoint(
            id=str(uuid4()),
            execution_id=execution.id,
            state=execution.state,
            snapshot=snapshot,
        )
        execution.checkpoints.append(checkpoint)
        self.bus.publish(
            CheckpointCreated(
                workflow_id=execution.workflow_id or execution.workflow_definition_id,
                run_id=execution.run_id,
                checkpoint_id=checkpoint.id,
            )
        )

    def _require_execution(self, execution_id: str) -> WorkflowExecution:
        execution = self._executions.get(execution_id)
        if execution is None:
            raise ValueError("execution not found")
        return execution
