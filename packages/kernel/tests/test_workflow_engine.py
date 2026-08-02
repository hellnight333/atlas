from __future__ import annotations

from typing import Any

from atlas_kernel.event_bus import (
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
from atlas_kernel.workflow_engine import (
    ExecutionState,
    FailureStrategy,
    NodeExecutionResult,
    RetryPolicy,
    WorkflowDefinition,
    WorkflowEngine,
    WorkflowNode,
    WorkflowNodeDelegate,
)


class RecordingDelegate(WorkflowNodeDelegate):
    def __init__(
        self, fail_once_for: set[str] | None = None, always_fail_for: set[str] | None = None
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self._attempts: dict[str, int] = {}
        self.fail_once_for = fail_once_for or set()
        self.always_fail_for = always_fail_for or set()

    def execute_node(
        self,
        node: WorkflowNode,
        run_id: str,
        project_id: str,
        workflow_id: str | None,
        input_asset_ids: list[str],
    ) -> NodeExecutionResult:
        attempt = self._attempts.get(node.id, 0) + 1
        self._attempts[node.id] = attempt
        self.calls.append(
            {
                "node_id": node.id,
                "run_id": run_id,
                "project_id": project_id,
                "workflow_id": workflow_id,
                "input_asset_ids": list(input_asset_ids),
                "attempt": attempt,
            }
        )

        if node.id in self.always_fail_for:
            return NodeExecutionResult(status=ExecutionState.FAILED, error="always fail")

        if node.id in self.fail_once_for and attempt == 1:
            return NodeExecutionResult(status=ExecutionState.FAILED, error="first attempt failure")

        return NodeExecutionResult(
            status=ExecutionState.COMPLETED,
            job_id=f"job-{node.id}-{attempt}",
            produced_asset_ids=[f"asset-{node.id}-{attempt}"],
        )


def test_graph_validation_rejects_cycles():
    engine = WorkflowEngine(delegate=RecordingDelegate(), bus=EventBus())
    definition = WorkflowDefinition(
        id="wf-cycle",
        name="cycle",
        nodes=[
            WorkflowNode(id="A", action="image.generate", depends_on=["B"]),
            WorkflowNode(id="B", action="text.generate", depends_on=["A"]),
        ],
    )

    result = engine.validate_workflow(definition)

    assert result.valid is False
    assert any("cycle" in err for err in result.errors)


def test_parallel_scheduling_levels_are_detected():
    engine = WorkflowEngine(delegate=RecordingDelegate(), bus=EventBus())
    definition = WorkflowDefinition(
        id="wf-parallel",
        name="parallel",
        nodes=[
            WorkflowNode(id="A", action="image.generate"),
            WorkflowNode(id="B", action="audio.generate"),
            WorkflowNode(id="C", action="video.generate", depends_on=["A", "B"]),
        ],
    )

    result = engine.validate_workflow(definition)

    assert result.valid is True
    assert result.plan is not None
    assert result.plan.levels[0] == ("A", "B")
    assert result.plan.levels[1] == ("C",)


def test_execution_order_and_asset_flow():
    delegate = RecordingDelegate()
    engine = WorkflowEngine(delegate=delegate, bus=EventBus())
    definition = WorkflowDefinition(
        id="wf-order",
        name="order",
        project_id="project-1",
        workflow_id="workflow-1",
        nodes=[
            WorkflowNode(id="A", action="image.generate"),
            WorkflowNode(id="B", action="audio.generate"),
            WorkflowNode(
                id="C",
                action="video.generate",
                depends_on=["A", "B"],
                input_asset_ids=["asset-input"],
            ),
        ],
    )
    engine.create_workflow(definition)

    execution = engine.execute_workflow(workflow_definition_id="wf-order", run_id="run-1")

    assert execution.state == ExecutionState.COMPLETED
    calls_by_node = {item["node_id"]: item for item in delegate.calls}
    assert "A" in calls_by_node
    assert "B" in calls_by_node
    assert "C" in calls_by_node
    assert set(calls_by_node["C"]["input_asset_ids"]) >= {"asset-input", "asset-A-1", "asset-B-1"}


def test_retry_policy_placeholder_retries_node():
    delegate = RecordingDelegate(fail_once_for={"A"})
    engine = WorkflowEngine(delegate=delegate, bus=EventBus())
    definition = WorkflowDefinition(
        id="wf-retry",
        name="retry",
        nodes=[
            WorkflowNode(
                id="A",
                action="code.generate",
                retry_policy=RetryPolicy(max_retries=1, failure_strategy=FailureStrategy.FAIL_FAST),
            )
        ],
    )
    engine.create_workflow(definition)

    execution = engine.execute_workflow(workflow_definition_id="wf-retry", run_id="run-retry")

    assert execution.state == ExecutionState.COMPLETED
    attempts = [item for item in delegate.calls if item["node_id"] == "A"]
    assert len(attempts) == 2


def test_event_publishing_and_pause_resume_cancel():
    bus = EventBus()
    delegate = RecordingDelegate(always_fail_for={"A"})
    engine = WorkflowEngine(delegate=delegate, bus=bus)

    workflow_started: list[WorkflowStarted] = []
    workflow_failed: list[WorkflowFailed] = []
    workflow_completed: list[WorkflowCompleted] = []
    node_started: list[NodeStarted] = []
    node_failed: list[NodeFailed] = []
    node_completed: list[NodeCompleted] = []
    checkpoints: list[CheckpointCreated] = []
    paused: list[ExecutionPaused] = []
    resumed: list[ExecutionResumed] = []

    bus.subscribe(WorkflowStarted, lambda event: workflow_started.append(event))
    bus.subscribe(WorkflowFailed, lambda event: workflow_failed.append(event))
    bus.subscribe(WorkflowCompleted, lambda event: workflow_completed.append(event))
    bus.subscribe(NodeStarted, lambda event: node_started.append(event))
    bus.subscribe(NodeFailed, lambda event: node_failed.append(event))
    bus.subscribe(NodeCompleted, lambda event: node_completed.append(event))
    bus.subscribe(CheckpointCreated, lambda event: checkpoints.append(event))
    bus.subscribe(ExecutionPaused, lambda event: paused.append(event))
    bus.subscribe(ExecutionResumed, lambda event: resumed.append(event))

    definition = WorkflowDefinition(
        id="wf-events",
        name="events",
        nodes=[WorkflowNode(id="A", action="text.generate")],
    )
    engine.create_workflow(definition)

    execution = engine.execute_workflow(workflow_definition_id="wf-events", run_id="run-events")
    assert execution.state == ExecutionState.FAILED
    assert len(workflow_started) == 1
    assert len(workflow_failed) == 1
    assert len(workflow_completed) == 0
    assert len(node_started) == 1
    assert len(node_failed) == 1
    assert len(node_completed) == 0
    assert len(checkpoints) >= 2

    paused_execution = engine.pause_execution(execution.id)
    assert paused_execution.state == ExecutionState.PAUSED
    resumed_execution = engine.resume_execution(execution.id)
    assert resumed_execution.state == ExecutionState.RUNNING
    cancelled_execution = engine.cancel_execution(execution.id)
    assert cancelled_execution.state == ExecutionState.CANCELLED
    assert len(paused) == 1
    assert len(resumed) == 1


def test_workflow_nodes_reference_capability_identifiers():
    engine = WorkflowEngine(delegate=RecordingDelegate(), bus=EventBus())
    definition = WorkflowDefinition(
        id="wf-capability-ref",
        name="capability reference",
        nodes=[
            WorkflowNode(
                id="A",
                action="text.generate",
                capability_req={"kind": "llm", "required_vram_gb": 0},
            )
        ],
    )

    result = engine.validate_workflow(definition)

    assert result.valid is True
    assert definition.nodes[0].capability_req.capability_id == "cap-reasoning"
