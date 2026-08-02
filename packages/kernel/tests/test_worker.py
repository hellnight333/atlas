from atlas_kernel.composition_root import create_runtime
from atlas_kernel.models import JobStatus, RunCreate


def test_worker_polls_and_completes_job():
    runtime = create_runtime()
    repository = runtime.repository
    orchestrator = runtime.orchestrator
    run = orchestrator.create_run(
        RunCreate(title="worker test", description="test", studio="image")
    )
    orchestrator.enqueue_job(run.id, "image.generate", {"prompt": "demo"})

    worker = runtime.worker
    job = worker.poll_once()

    assert job is not None
    assert job.action == "image.generate"

    jobs = repository.list_jobs()
    assert any(j.id == job.id and j.status == JobStatus.RUNNING for j in jobs)

    result = worker.execute_job(job)
    assert result["status"] == JobStatus.COMPLETED.value

    jobs_after = repository.list_jobs()
    assert any(j.id == job.id and j.execution_decision_id is not None for j in jobs_after)
