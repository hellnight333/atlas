from atlas_kernel.composition_root import create_runtime
from atlas_kernel.models import JobStatus, RunCreate


def test_worker_transitions_run_status_on_job_completion():
    runtime = create_runtime()
    repository = runtime.repository
    orchestrator = runtime.orchestrator
    run = orchestrator.create_run(
        RunCreate(title="lifecycle test", description="test", studio="text")
    )

    worker = runtime.worker
    job = worker.poll_once()

    assert job is not None
    assert job.status == JobStatus.RUNNING

    result = worker.execute_job(job)
    assert result["status"] == "completed"

    run_after = repository.get_run(run.id)
    assert run_after is not None
    assert run_after.status == JobStatus.COMPLETED
