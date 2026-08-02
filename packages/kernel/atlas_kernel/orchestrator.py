from __future__ import annotations

import uuid
from typing import Any

from .event_bus import EventBus, JobQueued
from .models import (
    CapabilityRequest,
    Job,
    Project,
    ProjectCreate,
    Run,
    RunCreate,
    Step,
    Workflow,
    WorkflowCreate,
    Workspace,
    WorkspaceCreate,
    normalize_capability_request,
)
from .repository import AtlasRepository
from .state_machine import ExecutionStateMachine


class Orchestrator:
    def __init__(
        self,
        state_machine: ExecutionStateMachine,
        repository: AtlasRepository,
        event_bus: EventBus,
    ) -> None:
        self.state_machine = state_machine
        self.repository = repository
        self.bus = event_bus

    def create_workspace(self, request: WorkspaceCreate) -> Workspace:
        workspace_id = f"workspace-{uuid.uuid4().hex[:8]}"
        workspace = Workspace(id=workspace_id, name=request.name, description=request.description)
        return self.repository.create_workspace(workspace)

    def create_project(self, request: ProjectCreate) -> Project:
        project_id = f"project-{uuid.uuid4().hex[:8]}"
        project = Project(
            id=project_id,
            workspace_id=request.workspace_id,
            name=request.name,
            description=request.description,
        )
        return self.repository.create_project(project)

    def create_workflow(self, request: WorkflowCreate) -> Workflow:
        workflow_id = f"workflow-{uuid.uuid4().hex[:8]}"
        workflow = Workflow(
            id=workflow_id,
            project_id=request.project_id,
            name=request.name,
            description=request.description,
            studio=request.studio,
            default_action=request.default_action,
            capability_req=normalize_capability_request(
                request.capability_req,
                default_capability_id=self._default_capability_id_for_studio(request.studio),
            ),
        )
        return self.repository.create_workflow(workflow)

    def create_run(self, request: RunCreate) -> Run:
        run_id = f"run-{uuid.uuid4().hex[:8]}"
        workflow_id = getattr(request, "workflow_id", None)
        workspace_id = getattr(request, "workspace_id", None)
        project_id = getattr(request, "project_id", None)
        workflow = None
        if workflow_id is not None:
            workflow = self.repository.get_workflow(workflow_id)

        if workflow is not None:
            run = Run(
                id=run_id,
                title=request.title,
                description=request.description,
                studio=workflow.studio,
                workspace_id=workspace_id,
                project_id=workflow.project_id,
                workflow_id=workflow.id,
            )
            default_action = workflow.default_action or self._default_action_for_studio(
                workflow.studio
            )
            capability_req = normalize_capability_request(
                workflow.capability_req,
                default_capability_id=self._default_capability_id_for_studio(workflow.studio),
            )
        else:
            run = Run(
                id=run_id,
                title=request.title,
                description=request.description,
                studio=request.studio,
                workspace_id=workspace_id,
                project_id=project_id,
                workflow_id=workflow_id,
            )
            default_action = self._default_action_for_studio(request.studio)
            capability_req = self._default_capability_req(request.studio)

        self.state_machine.create_run(run.model_dump())
        self.repository.create_run(run)

        action = default_action
        payload = self._payload_for_action(run.title, action)
        self.add_step(run.id, action=action, payload=payload)
        self.enqueue_job(
            run.id,
            action=action,
            payload=payload,
            capability_req=capability_req,
        )
        return run

    def _default_action_for_studio(self, studio: str) -> str:
        if studio == "text":
            return "text.generate"
        if studio == "code":
            return "code.generate"
        return "image.generate"

    def _default_capability_id_for_studio(self, studio: str) -> str:
        if studio == "code":
            return "cap-code-generation"
        if studio == "text":
            return "cap-reasoning"
        return "cap-image-generation"

    def _default_capability_req(self, studio: str) -> CapabilityRequest:
        if studio == "text" or studio == "code":
            return CapabilityRequest(
                capability_id=self._default_capability_id_for_studio(studio),
                requirements={"required_vram_gb": 0},
            )
        return CapabilityRequest(
            capability_id=self._default_capability_id_for_studio(studio),
            requirements={"required_vram_gb": 24},
        )

    def _payload_for_action(self, title: str, action: str) -> dict[str, Any]:
        if action == "text.generate":
            return {"prompt": f"Run {title} text workflow"}
        if action == "code.generate":
            return {"prompt": f"Run {title} code workflow", "language": "python"}
        return {"prompt": f"Run {title} image workflow"}

    def add_step(
        self,
        run_id: str,
        action: str,
        payload: dict[str, Any] | None = None,
        depends_on: list[str] | None = None,
    ) -> Step:
        step_id = f"step-{uuid.uuid4().hex[:8]}"
        step = Step(
            id=step_id,
            run_id=run_id,
            action=action,
            payload=payload or {},
            depends_on=depends_on or [],
        )
        self.state_machine.create_step(step)
        self.repository.create_step(step)
        return step

    def enqueue_job(
        self,
        run_id: str,
        action: str,
        payload: dict[str, Any] | None = None,
        priority: int = 0,
        capability_req: CapabilityRequest | dict[str, Any] | None = None,
    ) -> Job:
        job_id = f"job-{uuid.uuid4().hex[:8]}"
        default_capability_id = "cap-image-generation"
        if action.startswith("text."):
            default_capability_id = "cap-reasoning"
        elif action.startswith("code."):
            default_capability_id = "cap-code-generation"
        job = Job(
            id=job_id,
            run_id=run_id,
            action=action,
            payload=payload or {},
            priority=priority,
            capability_req=normalize_capability_request(
                capability_req,
                default_capability_id=default_capability_id,
            ),
        )
        self.state_machine.create_job(job)
        self.repository.create_job(job)
        self.bus.publish(JobQueued(job_id=job.id, run_id=job.run_id, action=job.action))
        return job
