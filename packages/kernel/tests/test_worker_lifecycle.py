from atlas_kernel.models import JobStatus
from atlas_kernel.orchestrator import Orchestrator
from atlas_kernel.repository import AtlasRepository
from atlas_kernel.state_machine import ExecutionStateMachine
from atlas_kernel.models import RunCreate
from atlas_kernel.worker import Worker


def test_worker_transitions_run_status_on_job_completion():
    repository = AtlasRepository()
    state_machine = ExecutionStateMachine()
    orchestrator = Orchestrator(state_machine, repository)
    run = orchestrator.create_run(RunCreate(title='lifecycle test', description='test', studio='text'))

    worker = Worker(repository)
    job = worker.poll_once()

    assert job is not None
    assert job.status == JobStatus.RUNNING

    result = worker.execute_job(job)
    assert result['status'] == 'completed'

    run_after = repository.get_run(run.id)
    assert run_after is not None
    assert run_after.status == JobStatus.COMPLETED
