from atlas_kernel.models import JobStatus
from atlas_kernel.orchestrator import Orchestrator
from atlas_kernel.repository import AtlasRepository
from atlas_kernel.state_machine import ExecutionStateMachine
from atlas_kernel.models import RunCreate
from atlas_kernel.worker import Worker


def test_worker_polls_and_completes_job():
    repository = AtlasRepository()
    state_machine = ExecutionStateMachine()
    orchestrator = Orchestrator(state_machine, repository)
    run = orchestrator.create_run(RunCreate(title='worker test', description='test', studio='image'))
    orchestrator.enqueue_job(run.id, 'image.generate', {'prompt': 'demo'})

    worker = Worker(repository)
    job = worker.poll_once()

    assert job is not None
    assert job.action == 'image.generate'

    jobs = repository.list_jobs()
    assert any(j.id == job.id and j.status == JobStatus.RUNNING for j in jobs)
