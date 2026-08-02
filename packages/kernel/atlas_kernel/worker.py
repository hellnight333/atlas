from __future__ import annotations

import time
from typing import Any

from .event_bus import EventBus, JobFailed, ProviderLoaded, RunFailed
from .execution_policy import ExecutionPolicyEngine
from .executor import Executor
from .models import Job, JobStatus, RuntimeContext
from .providers import ProviderManager
from .repository import AtlasRepository
from .router import ProviderRouter


class Worker:
    def __init__(
        self,
        repository: AtlasRepository,
        router: ProviderRouter,
        provider_manager: ProviderManager,
        event_bus: EventBus,
        execution_policy: ExecutionPolicyEngine,
        executor: Executor,
    ) -> None:
        self.repository = repository
        self.bus = event_bus
        self.router = router
        self.provider_manager = provider_manager
        self.execution_policy = execution_policy
        for provider in self.router.registry.list_providers():
            self.bus.publish(ProviderLoaded(provider_name=provider.name, kind=provider.kind))
        self.executor = executor

    def poll_once(self) -> Job | None:
        jobs = self.repository.list_jobs()
        for job in jobs:
            if job.status == JobStatus.QUEUED:
                self.repository.update_job_status(job.id, JobStatus.RUNNING)
                job.status = JobStatus.RUNNING
                return job
        return None

    def execute_job(self, job: Job) -> dict[str, Any]:
        capability = self.router.registry.get_capability(job.capability_req.capability_id)
        if capability is None:
            self.repository.update_job_status(job.id, JobStatus.FAILED)
            self.repository.update_run_status(job.run_id, JobStatus.FAILED)
            self.bus.publish(
                JobFailed(
                    job_id=job.id,
                    run_id=job.run_id,
                    reason=f"unknown capability_id: {job.capability_req.capability_id}",
                )
            )
            self.bus.publish(
                RunFailed(
                    run_id=job.run_id,
                    reason=f"unknown capability_id: {job.capability_req.capability_id}",
                )
            )
            return {
                "job_id": job.id,
                "status": JobStatus.FAILED.value,
                "provider": None,
                "output": {},
                "error": f"unknown capability_id: {job.capability_req.capability_id}",
                "asset_id": None,
            }

        try:
            decision = self.execution_policy.evaluate(
                capability_request=job.capability_req,
                runtime_context=RuntimeContext(
                    available_gpu_vram_gb=max(
                        (provider.vram_gb for provider in self.router.registry.list_providers()),
                        default=0,
                    ),
                    queue_length=len(
                        [
                            item
                            for item in self.repository.list_jobs()
                            if item.status == JobStatus.QUEUED
                        ]
                    ),
                    provider_availability={
                        provider.name: True for provider in self.router.registry.list_providers()
                    },
                    executor_health={
                        executor.id: executor.health
                        for executor in self.router.registry.list_executors()
                    },
                ),
            )
        except ValueError as exc:
            self.repository.update_job_status(job.id, JobStatus.FAILED)
            self.repository.update_run_status(job.run_id, JobStatus.FAILED)
            self.bus.publish(JobFailed(job_id=job.id, run_id=job.run_id, reason=str(exc)))
            self.bus.publish(RunFailed(run_id=job.run_id, reason=str(exc)))
            return {
                "job_id": job.id,
                "status": JobStatus.FAILED.value,
                "provider": None,
                "output": {},
                "error": str(exc),
                "asset_id": None,
            }

        self.repository.assign_execution_decision(job.id, decision)
        job.execution_decision_id = decision.decision_id
        job.provider_name = decision.provider_id
        result = self.executor.execute(job)
        return {
            "job_id": result.job_id,
            "status": result.status.value,
            "provider": result.provider_name,
            "output": result.output,
            "error": result.error,
            "asset_id": result.asset_id,
        }

    def execute(self, job: Job, cancellation_token: Any | None = None) -> dict[str, Any]:
        if cancellation_token is not None and getattr(cancellation_token, "cancelled", False):
            return {
                "job_id": job.id,
                "status": JobStatus.CANCELLED.value,
                "provider": job.provider_name,
                "output": {},
                "error": "cancelled before execution",
                "asset_id": None,
            }
        return self.execute_job(job)

    def run_loop(self, interval_seconds: float = 1.0, stop_after: int | None = None) -> None:
        iterations = 0
        while stop_after is None or iterations < stop_after:
            job = self.poll_once()
            if job is None:
                time.sleep(interval_seconds)
                iterations += 1
                continue
            self.execute_job(job)
            iterations += 1
