from atlas_kernel.composition_root import create_runtime
from atlas_kernel.event_bus import (
    AssetCreated,
    EventBus,
    JobCompleted,
    JobFailed,
    JobQueued,
    JobStarted,
    RunCompleted,
    RunFailed,
    RunStarted,
    WorkflowCompleted,
    WorkflowStarted,
)
from atlas_kernel.models import JobStatus, RunCreate, WorkflowCreate


def test_worker_publishes_success_lifecycle_events():
    bus = EventBus()
    runtime = create_runtime(event_bus=bus)

    queued_events: list[JobQueued] = []
    job_started_events: list[JobStarted] = []
    job_completed_events: list[JobCompleted] = []
    run_started_events: list[RunStarted] = []
    run_completed_events: list[RunCompleted] = []
    workflow_started_events: list[WorkflowStarted] = []
    workflow_completed_events: list[WorkflowCompleted] = []

    bus.subscribe(JobQueued, lambda event: queued_events.append(event))
    bus.subscribe(JobStarted, lambda event: job_started_events.append(event))
    bus.subscribe(JobCompleted, lambda event: job_completed_events.append(event))
    bus.subscribe(RunStarted, lambda event: run_started_events.append(event))
    bus.subscribe(RunCompleted, lambda event: run_completed_events.append(event))
    bus.subscribe(WorkflowStarted, lambda event: workflow_started_events.append(event))
    bus.subscribe(WorkflowCompleted, lambda event: workflow_completed_events.append(event))

    orchestrator = runtime.orchestrator
    workflow = orchestrator.create_workflow(WorkflowCreate(name="workflow-a", studio="text"))
    run = orchestrator.create_run(
        RunCreate(title="event success", studio="text", workflow_id=workflow.id)
    )

    worker = runtime.worker
    job = worker.poll_once()
    assert job is not None

    result = worker.execute_job(job)
    assert result["status"] == "completed"

    assert any(event.run_id == run.id for event in queued_events)
    assert any(event.job_id == job.id for event in job_started_events)
    assert any(event.job_id == job.id for event in job_completed_events)
    assert any(event.run_id == run.id for event in run_started_events)
    assert any(event.run_id == run.id for event in run_completed_events)
    assert any(event.workflow_id == workflow.id for event in workflow_started_events)
    assert any(event.workflow_id == workflow.id for event in workflow_completed_events)


def test_worker_publishes_failure_events_when_no_provider_matches():
    bus = EventBus()
    runtime = create_runtime(event_bus=bus)

    job_failed_events: list[JobFailed] = []
    run_failed_events: list[RunFailed] = []

    bus.subscribe(JobFailed, lambda event: job_failed_events.append(event))
    bus.subscribe(RunFailed, lambda event: run_failed_events.append(event))

    orchestrator = runtime.orchestrator
    run = orchestrator.create_run(RunCreate(title="event failure", studio="text"))
    failed_job = orchestrator.enqueue_job(
        run.id,
        "text.generate",
        {"prompt": "no provider path"},
        capability_req={"capability_id": "cap-audio", "requirements": {"required_vram_gb": 0}},
    )

    worker = runtime.worker

    # Drain jobs until the intentionally unmatched job is picked.
    current = worker.poll_once()
    while current is not None and current.id != failed_job.id:
        worker.execute_job(current)
        current = worker.poll_once()

    assert current is not None
    result = worker.execute_job(current)
    assert result["status"] == "failed"

    assert any(event.job_id == failed_job.id for event in job_failed_events)
    assert any(event.run_id == run.id for event in run_failed_events)


def test_worker_emits_asset_created_for_image_outputs():
    bus = EventBus()
    runtime = create_runtime(event_bus=bus)
    repository = runtime.repository
    asset_events: list[AssetCreated] = []
    bus.subscribe(AssetCreated, lambda event: asset_events.append(event))

    orchestrator = runtime.orchestrator
    run = orchestrator.create_run(RunCreate(title="image output", studio="image"))

    worker = runtime.worker
    job = worker.poll_once()
    assert job is not None

    result = worker.execute_job(job)
    assert result["status"] == JobStatus.COMPLETED.value
    assert len(asset_events) >= 1
    assert any(event.run_id == run.id for event in asset_events)

    run_after = repository.get_run(run.id)
    assert run_after is not None
    assert len(run_after.produced_asset_ids) >= 1

    jobs = repository.list_jobs_by_run(run.id)
    assert len(jobs) >= 1
    assert any(len(item.produced_asset_ids) >= 1 for item in jobs)
