from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import Job, JobStatus, Step, StepStatus


@dataclass
class ExecutionStateMachine:
    runs: dict[str, dict[str, Any]] = field(default_factory=dict)
    jobs: dict[str, Job] = field(default_factory=dict)
    steps: dict[str, Step] = field(default_factory=dict)

    def create_run(self, run: dict[str, Any]) -> dict[str, Any]:
        self.runs[run["id"]] = run
        return run

    def create_job(self, job: Job) -> Job:
        self.jobs[job.id] = job
        return job

    def create_step(self, step: Step) -> Step:
        self.steps[step.id] = step
        return step

    def transition_job(self, job_id: str, new_status: JobStatus) -> Job:
        job = self.jobs[job_id]
        allowed = {
            JobStatus.QUEUED: {JobStatus.RUNNING, JobStatus.CANCELLED},
            JobStatus.RUNNING: {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.PAUSED},
            JobStatus.PAUSED: {JobStatus.RUNNING, JobStatus.CANCELLED},
            JobStatus.FAILED: {JobStatus.RUNNING},
            JobStatus.COMPLETED: set(),
            JobStatus.CANCELLED: set(),
        }
        if new_status not in allowed.get(job.status, set()):
            raise ValueError(f"Illegal transition {job.status} -> {new_status}")
        job.status = new_status
        return job

    def transition_step(self, step_id: str, new_status: StepStatus) -> Step:
        step = self.steps[step_id]
        allowed = {
            StepStatus.PENDING: {StepStatus.RUNNING, StepStatus.CANCELLED},
            StepStatus.RUNNING: {StepStatus.COMPLETED, StepStatus.FAILED, StepStatus.CANCELLED},
            StepStatus.COMPLETED: set(),
            StepStatus.FAILED: set(),
            StepStatus.CANCELLED: set(),
        }
        if new_status not in allowed.get(step.status, set()):
            raise ValueError(f"Illegal transition {step.status} -> {new_status}")
        step.status = new_status
        return step
