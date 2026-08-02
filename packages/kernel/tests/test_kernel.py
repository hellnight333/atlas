from atlas_kernel.composition_root import create_runtime
from atlas_kernel.models import JobStatus, ProviderSpec
from atlas_kernel.queue import Queue
from atlas_kernel.registry import Registry
from atlas_kernel.router import ProviderRouter
from atlas_kernel.state_machine import ExecutionStateMachine


def test_orchestrator_creates_run_and_job():
    runtime = create_runtime()
    orchestrator = runtime.orchestrator
    run = orchestrator.create_run(
        type("Req", (), {"title": "demo", "description": "", "studio": "image"})()
    )
    step = orchestrator.add_step(run.id, "image.generate")
    job = orchestrator.enqueue_job(run.id, "image.generate", {"prompt": "A test"})

    assert run.title == "demo"
    assert step.action == "image.generate"
    assert job.status == JobStatus.QUEUED


def test_queue_and_router_work():
    queue = Queue()
    registry = Registry()
    registry.register_provider(
        ProviderSpec(name="local-flux", kind="image", is_local=True, vram_gb=24)
    )
    registry.register_provider(
        ProviderSpec(
            name="cloud-claude",
            kind="llm",
            is_local=False,
            cost_per_unit=0.3,
            p50_latency_ms=500,
            quality_score=0.9,
            vram_gb=0,
        )
    )
    router = ProviderRouter(registry)

    job = type("Job", (), {"id": "j1", "status": JobStatus.QUEUED})()
    queue.enqueue(job)
    dequeued = queue.dequeue()
    provider = router.select_provider(required_vram_gb=24)

    assert dequeued is not None
    assert provider is not None
    assert provider.name == "local-flux"


def test_state_machine_rejects_illegal_transition():
    state = ExecutionStateMachine()
    job = state.create_job(
        type(
            "Job",
            (),
            {
                "id": "j1",
                "run_id": "r1",
                "action": "demo",
                "payload": {},
                "status": JobStatus.QUEUED,
                "attempts": 0,
                "priority": 0,
                "capability_req": {},
                "created_at": None,
            },
        )()
    )
    state.transition_job(job.id, JobStatus.RUNNING)

    try:
        state.transition_job(job.id, JobStatus.QUEUED)
    except ValueError:
        assert True
    else:
        assert False
