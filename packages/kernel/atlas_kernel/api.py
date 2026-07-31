from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .db import init_db
from .models import ActionSpec, ProviderSpec, RunCreate
from .orchestrator import Orchestrator
from .providers import LocalFluxProvider, LocalTextProvider, ProviderManager
from .registry import Registry
from .repository import AtlasRepository
from .router import ProviderRouter
from .state_machine import ExecutionStateMachine

app = FastAPI(title="Atlas Kernel")
init_db()
state_machine = ExecutionStateMachine()
registry = Registry()
registry.register_action(ActionSpec(name="image.generate", description="Generate an image from a prompt"))
registry.register_action(ActionSpec(name="text.generate", description="Generate text output from a prompt"))
registry.register_action(ActionSpec(name="code.generate", description="Generate code from a prompt"))
registry.register_provider(ProviderSpec(name="local-flux", kind="image", is_local=True, vram_gb=24))
registry.register_provider(ProviderSpec(name="local-text", kind="llm", is_local=True, vram_gb=0))
router = ProviderRouter(registry)
provider_manager = ProviderManager()
provider_manager.register_adapter(LocalFluxProvider.name, LocalFluxProvider())
provider_manager.register_adapter(LocalTextProvider.name, LocalTextProvider())
repository = AtlasRepository()
orchestrator = Orchestrator(state_machine, repository)


class RunRequest(BaseModel):
    title: str
    description: str = ""
    studio: str = "image"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/runs")
def create_run(request: RunRequest) -> dict[str, object]:
    run = orchestrator.create_run(RunCreate(title=request.title, description=request.description, studio=request.studio))
    return {"run_id": run.id, "status": run.status.value, "studio": run.studio}


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, object]:
    run = repository.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    jobs = repository.list_jobs_by_run(run_id)
    return {
        "id": run.id,
        "title": run.title,
        "description": run.description,
        "studio": run.studio,
        "status": run.status.value,
        "created_at": run.created_at.isoformat(),
        "job_count": len(jobs),
        "jobs": [
            {
                "id": job.id,
                "action": job.action,
                "status": job.status.value,
                "payload": job.payload,
                "provider_name": job.provider_name,
                "output": job.output,
            }
            for job in jobs
        ],
    }


@app.get("/providers")
def providers() -> list[dict[str, object]]:
    return [provider.model_dump() for provider in registry.list_providers()]


@app.get("/actions")
def actions() -> list[dict[str, object]]:
    return [action.model_dump() for action in registry.list_actions()]


@app.get("/runs")
def list_runs() -> list[dict[str, object]]:
    runs = repository.list_runs()
    return [
        {
            "id": run.id,
            "title": run.title,
            "description": run.description,
            "studio": run.studio,
            "status": run.status.value,
        }
        for run in runs
    ]


@app.get("/runs/{run_id}/jobs")
def list_jobs(run_id: str) -> list[dict[str, object]]:
    jobs = repository.list_jobs_by_run(run_id)
    return [
        {
            "id": job.id,
            "run_id": job.run_id,
            "action": job.action,
            "status": job.status.value,
            "payload": job.payload,
            "provider_name": job.provider_name,
            "output": job.output,
        }
        for job in jobs
    ]
