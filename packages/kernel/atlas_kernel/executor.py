from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from .asset_system import AssetService
from .event_bus import (
    EventBus,
    JobCompleted,
    JobFailed,
    JobStarted,
    RunCompleted,
    RunFailed,
    RunStarted,
    WorkflowCompleted,
    WorkflowStarted,
)
from .models import Job, JobStatus
from .providers import ProviderAdapter, ProviderManager
from .repository import AtlasRepository


@dataclass
class JobExecutionResult:
    job_id: str
    status: JobStatus
    provider_name: str | None = None
    output: dict[str, Any] | None = None
    error: str | None = None
    asset_id: str | None = None


class Executor(ABC):
    @abstractmethod
    def execute(self, job: Job) -> JobExecutionResult:
        pass


class ExecutionLocationExecutor(ABC):
    name: str = "base"

    @abstractmethod
    def execute(
        self, provider: ProviderAdapter, action: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        pass


class LocalExecutor(ExecutionLocationExecutor):
    name = "local"

    def execute(
        self, provider: ProviderAdapter, action: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return provider.execute(action, payload)


class DockerExecutor(LocalExecutor):
    name = "docker"


class RemoteExecutor(LocalExecutor):
    name = "remote"


class ClusterExecutor(LocalExecutor):
    name = "cluster"


class CloudExecutor(LocalExecutor):
    name = "cloud"


class ComfyExecutor(LocalExecutor):
    name = "comfy"


class OllamaExecutor(LocalExecutor):
    name = "ollama"


class JobExecutor(Executor):
    def __init__(
        self,
        repository: AtlasRepository,
        provider_manager: ProviderManager,
        location_executor: ExecutionLocationExecutor,
        bus: EventBus,
        asset_service: AssetService,
    ) -> None:
        self.repository = repository
        self.provider_manager = provider_manager
        self.location_executor = location_executor
        self.bus = bus
        self.asset_service = asset_service

    def execute(self, job: Job) -> JobExecutionResult:
        run = self.repository.get_run(job.run_id)
        self.repository.update_job_status(job.id, JobStatus.RUNNING)
        self.repository.update_run_status(job.run_id, JobStatus.RUNNING)
        self.bus.publish(JobStarted(job_id=job.id, run_id=job.run_id, action=job.action))
        if run is not None:
            self.bus.publish(
                RunStarted(run_id=run.id, studio=run.studio, workflow_id=run.workflow_id)
            )
            if run.workflow_id is not None:
                self.bus.publish(WorkflowStarted(workflow_id=run.workflow_id, run_id=run.id))

        if not job.execution_decision_id:
            result = JobExecutionResult(
                job_id=job.id, status=JobStatus.FAILED, error="execution decision missing"
            )
            self.repository.update_job_status(job.id, JobStatus.FAILED)
            self.repository.update_run_status(job.run_id, JobStatus.FAILED)
            self.bus.publish(
                JobFailed(job_id=job.id, run_id=job.run_id, reason="execution decision missing")
            )
            self.bus.publish(RunFailed(run_id=job.run_id, reason="execution decision missing"))
            return result

        decision = self.repository.get_execution_decision(job.execution_decision_id)
        if decision is None:
            result = JobExecutionResult(
                job_id=job.id,
                status=JobStatus.FAILED,
                provider_name=job.provider_name,
                error="execution decision not found",
            )
            self.repository.update_job_status(
                job.id, JobStatus.FAILED, provider_name=job.provider_name
            )
            self.repository.update_run_status(job.run_id, JobStatus.FAILED)
            self.bus.publish(
                JobFailed(
                    job_id=job.id,
                    run_id=job.run_id,
                    reason="execution decision not found",
                    provider_name=job.provider_name,
                )
            )
            self.bus.publish(RunFailed(run_id=job.run_id, reason="execution decision not found"))
            return result

        provider_name = decision.provider_id

        adapter = self.provider_manager.get_adapter(provider_name)
        if adapter is None:
            result = JobExecutionResult(
                job_id=job.id,
                status=JobStatus.FAILED,
                provider_name=provider_name,
                error="provider adapter missing",
            )
            self.repository.update_job_status(job.id, JobStatus.FAILED, provider_name=provider_name)
            self.repository.update_run_status(job.run_id, JobStatus.FAILED)
            self.bus.publish(
                JobFailed(
                    job_id=job.id,
                    run_id=job.run_id,
                    reason="provider adapter missing",
                    provider_name=provider_name,
                )
            )
            self.bus.publish(RunFailed(run_id=job.run_id, reason="provider adapter missing"))
            return result

        try:
            output = self.location_executor.execute(adapter, job.action, job.payload)
            self.repository.update_job_status(
                job.id, JobStatus.COMPLETED, provider_name=provider_name, output=output
            )
            self.repository.update_run_status(job.run_id, JobStatus.COMPLETED)
            asset = self.asset_service.create_asset_for_job(job, output)
            self.bus.publish(
                JobCompleted(
                    job_id=job.id,
                    run_id=job.run_id,
                    provider_name=provider_name,
                    asset_id=asset.id if asset else None,
                )
            )
            self.bus.publish(RunCompleted(run_id=job.run_id))
            if run is not None and run.workflow_id is not None:
                self.bus.publish(WorkflowCompleted(workflow_id=run.workflow_id, run_id=run.id))
            return JobExecutionResult(
                job_id=job.id,
                status=JobStatus.COMPLETED,
                provider_name=provider_name,
                output=output,
                asset_id=asset.id if asset else None,
            )
        except Exception as exc:
            output = {"error": str(exc)}
            self.repository.update_job_status(
                job.id, JobStatus.FAILED, provider_name=provider_name, output=output
            )
            self.repository.update_run_status(job.run_id, JobStatus.FAILED)
            self.bus.publish(
                JobFailed(
                    job_id=job.id, run_id=job.run_id, reason=str(exc), provider_name=provider_name
                )
            )
            self.bus.publish(RunFailed(run_id=job.run_id, reason=str(exc)))
            return JobExecutionResult(
                job_id=job.id,
                status=JobStatus.FAILED,
                provider_name=provider_name,
                error=str(exc),
                output=output,
            )
