from __future__ import annotations

import time
from typing import Any

from .models import Job, JobStatus, ProviderSpec
from .providers import LocalFluxProvider, LocalTextProvider, ProviderManager
from .repository import AtlasRepository
from .registry import Registry
from .router import ProviderRouter


class Worker:
    def __init__(
        self,
        repository: AtlasRepository | None = None,
        router: ProviderRouter | None = None,
        provider_manager: ProviderManager | None = None,
    ) -> None:
        self.repository = repository or AtlasRepository()
        if router is None:
            registry = Registry()
            registry.register_provider(ProviderSpec(name=LocalFluxProvider.name, kind="image", is_local=True, vram_gb=24))
            registry.register_provider(ProviderSpec(name=LocalTextProvider.name, kind="llm", is_local=True, vram_gb=0))
            router = ProviderRouter(registry)
        self.router = router
        if provider_manager is None:
            provider_manager = ProviderManager()
            provider_manager.register_adapter(LocalFluxProvider.name, LocalFluxProvider())
            provider_manager.register_adapter(LocalTextProvider.name, LocalTextProvider())
        self.provider_manager = provider_manager

    def poll_once(self) -> Job | None:
        jobs = self.repository.list_jobs()
        for job in jobs:
            if job.status == JobStatus.QUEUED:
                self.repository.update_job_status(job.id, JobStatus.RUNNING)
                job.status = JobStatus.RUNNING
                return job
        return None

    def execute_job(self, job: Job) -> dict[str, Any]:
        capability_req = job.capability_req or {}
        required_vram = int(capability_req.get("required_vram_gb", 0))
        required_kind = capability_req.get("kind")
        provider = self.router.select_provider(required_kind=required_kind, required_vram_gb=required_vram)
        if provider is None:
            self.repository.update_job_status(job.id, JobStatus.FAILED)
            return {"job_id": job.id, "status": "failed", "reason": "no eligible provider"}

        adapter = self.provider_manager.get_adapter(provider.name)
        if adapter is None:
            self.repository.update_job_status(job.id, JobStatus.FAILED)
            return {"job_id": job.id, "status": "failed", "reason": "provider adapter missing", "provider": provider.name}

        try:
            output = adapter.execute(job.action, job.payload)
            self.repository.update_job_status(job.id, JobStatus.COMPLETED, provider_name=provider.name, output=output)
            self.repository.update_run_status(job.run_id, JobStatus.COMPLETED)
            return {"job_id": job.id, "status": "completed", "provider": provider.name, "output": output}
        except Exception as exc:
            self.repository.update_job_status(job.id, JobStatus.FAILED, provider_name=provider.name, output={"error": str(exc)})
            self.repository.update_run_status(job.run_id, JobStatus.FAILED)
            return {"job_id": job.id, "status": "failed", "provider": provider.name, "error": str(exc)}

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
