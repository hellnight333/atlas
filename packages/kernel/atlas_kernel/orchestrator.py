from __future__ import annotations

import uuid
from typing import Any

from .models import Job, Run, RunCreate, Step
from .repository import AtlasRepository
from .state_machine import ExecutionStateMachine


class Orchestrator:
    def __init__(self, state_machine: ExecutionStateMachine, repository: AtlasRepository | None = None) -> None:
        self.state_machine = state_machine
        self.repository = repository or AtlasRepository()

    def create_run(self, request: RunCreate) -> Run:
        run_id = f"run-{uuid.uuid4().hex[:8]}"
        run = Run(id=run_id, title=request.title, description=request.description, studio=request.studio)
        self.state_machine.create_run(run.model_dump())
        self.repository.create_run(run)

        # Create a default step and queued job for the new run.
        if request.studio == "text":
            action = "text.generate"
            payload = {"prompt": f"Run {run.title} text workflow"}
            capability_req = {"kind": "llm", "required_vram_gb": 0}
        elif request.studio == "code":
            action = "code.generate"
            payload = {"prompt": f"Run {run.title} code workflow", "language": "python"}
            capability_req = {"kind": "llm", "required_vram_gb": 0}
        else:
            action = "image.generate"
            payload = {"prompt": f"Run {run.title} image workflow"}
            capability_req = {"kind": "image", "required_vram_gb": 24}

        self.add_step(run.id, action=action, payload=payload)
        self.enqueue_job(
            run.id,
            action=action,
            payload=payload,
            capability_req=capability_req,
        )
        return run

    def add_step(self, run_id: str, action: str, payload: dict[str, Any] | None = None, depends_on: list[str] | None = None) -> Step:
        step_id = f"step-{uuid.uuid4().hex[:8]}"
        step = Step(id=step_id, run_id=run_id, action=action, payload=payload or {}, depends_on=depends_on or [])
        self.state_machine.create_step(step)
        self.repository.create_step(step)
        return step

    def enqueue_job(
        self,
        run_id: str,
        action: str,
        payload: dict[str, Any] | None = None,
        priority: int = 0,
        capability_req: dict[str, Any] | None = None,
    ) -> Job:
        job_id = f"job-{uuid.uuid4().hex[:8]}"
        job = Job(
            id=job_id,
            run_id=run_id,
            action=action,
            payload=payload or {},
            priority=priority,
            capability_req=capability_req or {},
        )
        self.state_machine.create_job(job)
        self.repository.create_job(job)
        return job
