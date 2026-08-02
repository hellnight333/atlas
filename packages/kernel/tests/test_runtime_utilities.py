from __future__ import annotations

from atlas_kernel.composition_root import create_runtime
from atlas_kernel.models import Step, StepStatus
from atlas_kernel.providers import LocalFluxProvider, LocalTextProvider, ProviderManager
from atlas_kernel.state_machine import ExecutionStateMachine
from atlas_kernel.storage import PassthroughStorageBackend


def test_router_prefers_local_and_handles_no_candidate():
    runtime = create_runtime()
    router = runtime.router

    selected = router.select_provider(required_kind="image", required_vram_gb=24)
    assert selected is not None
    assert selected.name == "local-flux"

    missing = router.select_provider(required_kind="image", required_vram_gb=10_000)
    assert missing is None


def test_provider_manager_and_provider_outputs():
    manager = ProviderManager()
    manager.register_adapter("local-flux", LocalFluxProvider())
    manager.register_adapter("local-text", LocalTextProvider())

    image_provider = manager.get_adapter("local-flux")
    text_provider = manager.get_adapter("local-text")
    assert image_provider is not None
    assert text_provider is not None

    image_output = image_provider.execute("image.generate", {"prompt": "hello"})
    assert image_output["result"] == "image_generated"

    text_output = text_provider.execute("text.generate", {"prompt": "hello"})
    assert text_output["result"] == "text_generated"

    code_output = text_provider.execute("code.generate", {"prompt": "hello", "language": "python"})
    assert code_output["result"] == "code_generated"


def test_state_machine_step_transitions_and_run_storage():
    state = ExecutionStateMachine()
    run = state.create_run({"id": "run-1", "title": "demo"})
    assert state.runs["run-1"] == run

    step = Step(id="step-1", run_id="run-1", action="text.generate")
    state.create_step(step)
    transitioned = state.transition_step("step-1", StepStatus.RUNNING)
    assert transitioned.status == StepStatus.RUNNING
    completed = state.transition_step("step-1", StepStatus.COMPLETED)
    assert completed.status == StepStatus.COMPLETED


def test_worker_run_loop_exits_when_idle():
    runtime = create_runtime()
    runtime.worker.run_loop(interval_seconds=0.0, stop_after=1)


def test_storage_backend_passthrough_metadata():
    backend = PassthroughStorageBackend()
    stored = backend.store("atlas://asset/path")
    assert stored.uri == "atlas://asset/path"
    assert stored.file_size is None or stored.file_size >= 0
