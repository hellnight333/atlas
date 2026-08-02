from __future__ import annotations

from typing import Any

from atlas_kernel.asset_system import AssetService
from atlas_kernel.event_bus import EventBus
from atlas_kernel.executor import (
    ExecutionLocationExecutor,
    JobExecutor,
    LocalExecutor,
    RemoteExecutor,
)
from atlas_kernel.models import ExecutionDecision, Job, JobStatus
from atlas_kernel.providers import ProviderAdapter


class StubProvider(ProviderAdapter):
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((action, payload))
        return {"result": "ok", "action": action, "payload": payload}


class StubProviderManager:
    def __init__(self, adapter: ProviderAdapter | None) -> None:
        self.adapter = adapter

    def get_adapter(self, name: str) -> ProviderAdapter | None:
        return self.adapter


class StubRepository:
    def __init__(self) -> None:
        self.job_updates: list[tuple[str, JobStatus]] = []
        self.run_updates: list[tuple[str, JobStatus]] = []
        self.decisions: dict[str, ExecutionDecision] = {}

    def get_run(self, run_id: str):
        return None

    def update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        provider_name: str | None = None,
        output: dict[str, Any] | None = None,
    ) -> None:
        self.job_updates.append((job_id, status))

    def update_run_status(self, run_id: str, status: JobStatus) -> None:
        self.run_updates.append((run_id, status))

    def create_asset(self, asset):
        return asset

    def create_execution_decision(self, decision: ExecutionDecision) -> ExecutionDecision:
        self.decisions[decision.decision_id] = decision
        return decision

    def get_execution_decision(self, decision_id: str) -> ExecutionDecision | None:
        return self.decisions.get(decision_id)


class StubAssetService(AssetService):
    def __init__(self) -> None:
        pass

    def create_asset_for_job(self, job: Job, output: dict[str, Any]):
        return None


class SpyLocationExecutor(ExecutionLocationExecutor):
    name = "spy"

    def __init__(self) -> None:
        self.called = False

    def execute(
        self, provider: ProviderAdapter, action: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self.called = True
        result = provider.execute(action, payload)
        result["via"] = "spy"
        return result


def test_local_executor_calls_provider_directly():
    provider = StubProvider()
    executor = LocalExecutor()

    output = executor.execute(provider, "text.generate", {"prompt": "hello"})

    assert provider.calls == [("text.generate", {"prompt": "hello"})]
    assert output["result"] == "ok"


def test_remote_executor_keeps_provider_location_agnostic():
    provider = StubProvider()
    executor = RemoteExecutor()

    output = executor.execute(provider, "code.generate", {"prompt": "build"})

    assert provider.calls == [("code.generate", {"prompt": "build"})]
    assert output["action"] == "code.generate"


def test_job_executor_uses_injected_location_executor():
    provider = StubProvider()
    repository = StubRepository()
    location = SpyLocationExecutor()
    decision = repository.create_execution_decision(
        ExecutionDecision(
            decision_id="decision-1",
            capability_id="cap-reasoning",
            recipe_id="recipe-reasoning-default",
            executor_id="local",
            provider_id="stub",
            model_id="qwen-local",
            reason={"score_breakdown": {"quality": 10}},
            confidence=0.9,
        )
    )

    job_executor = JobExecutor(
        repository=repository,
        provider_manager=StubProviderManager(provider),
        location_executor=location,
        bus=EventBus(),
        asset_service=StubAssetService(),
    )

    job = Job(
        id="job-1",
        run_id="run-1",
        action="text.generate",
        payload={"prompt": "hello"},
        capability_req={"capability_id": "cap-reasoning", "requirements": {"required_vram_gb": 0}},
        execution_decision_id=decision.decision_id,
        provider_name="stub",
    )
    result = job_executor.execute(job)

    assert location.called is True
    assert result.status == JobStatus.COMPLETED
    assert result.output is not None
    assert result.output.get("via") == "spy"


def test_job_executor_fails_without_preselected_provider():
    repository = StubRepository()
    job_executor = JobExecutor(
        repository=repository,
        provider_manager=StubProviderManager(adapter=None),
        location_executor=SpyLocationExecutor(),
        bus=EventBus(),
        asset_service=StubAssetService(),
    )

    job = Job(
        id="job-2",
        run_id="run-2",
        action="text.generate",
        payload={"prompt": "hello"},
        capability_req={"capability_id": "cap-reasoning", "requirements": {}},
    )
    result = job_executor.execute(job)

    assert result.status == JobStatus.FAILED
    assert result.error == "execution decision missing"


def test_job_executor_does_not_route_from_capability_metadata():
    provider = StubProvider()
    repository = StubRepository()
    location = SpyLocationExecutor()
    decision = repository.create_execution_decision(
        ExecutionDecision(
            decision_id="decision-2",
            capability_id="cap-image-generation",
            recipe_id="recipe-image-fast-draft",
            executor_id="local",
            provider_id="stub",
            model_id="flux-dev",
            reason={"score_breakdown": {"vram": -1}},
            confidence=0.5,
        )
    )
    job_executor = JobExecutor(
        repository=repository,
        provider_manager=StubProviderManager(provider),
        location_executor=location,
        bus=EventBus(),
        asset_service=StubAssetService(),
    )

    job = Job(
        id="job-3",
        run_id="run-3",
        action="text.generate",
        payload={"prompt": "hello"},
        capability_req={
            "capability_id": "cap-image-generation",
            "requirements": {"required_vram_gb": 999},
        },
        execution_decision_id=decision.decision_id,
        provider_name="stub",
    )
    result = job_executor.execute(job)

    assert result.status == JobStatus.COMPLETED
    assert result.provider_name == "stub"
