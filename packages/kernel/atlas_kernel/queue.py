from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import Job, JobStatus


@dataclass
class Queue:
    jobs: list[Job] = field(default_factory=list)

    def enqueue(self, job: Job) -> None:
        self.jobs.append(job)

    def dequeue(self) -> Job | None:
        for job in self.jobs:
            if job.status == JobStatus.QUEUED:
                job.status = JobStatus.RUNNING
                return job
        return None

    def mark_completed(self, job_id: str) -> Job | None:
        for job in self.jobs:
            if job.id == job_id:
                job.status = JobStatus.COMPLETED
                return job
        return None

    def mark_failed(self, job_id: str) -> Job | None:
        for job in self.jobs:
            if job.id == job_id:
                job.status = JobStatus.FAILED
                return job
        return None
