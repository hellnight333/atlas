from __future__ import annotations

import json
import logging

from atlas_kernel.models import Job, JobStatus
from atlas_kernel.observability import Observability
from atlas_kernel.queue import Queue


class RecordingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def test_observability_emits_json_payload():
    logger = logging.getLogger("atlas-test-observability")
    logger.handlers = []
    logger.setLevel(logging.INFO)
    handler = RecordingHandler()
    logger.addHandler(handler)

    observability = Observability(logger=logger)
    observability.emit("job.started", run_id="run-1", job_id="job-1")

    assert len(handler.messages) == 1
    payload = json.loads(handler.messages[0])
    assert payload["event"] == "job.started"
    assert payload["run_id"] == "run-1"
    assert payload["job_id"] == "job-1"
    assert "timestamp" in payload


def test_queue_enqueue_dequeue_complete_and_fail_paths():
    queue = Queue()
    queued_job = Job(id="job-1", run_id="run-1", action="text.generate")
    running_job = Job(id="job-2", run_id="run-1", action="text.generate", status=JobStatus.RUNNING)
    queue.enqueue(queued_job)
    queue.enqueue(running_job)

    dequeued = queue.dequeue()
    assert dequeued is not None
    assert dequeued.id == "job-1"
    assert dequeued.status == JobStatus.RUNNING

    completed = queue.mark_completed("job-1")
    assert completed is not None
    assert completed.status == JobStatus.COMPLETED

    failed = queue.mark_failed("job-2")
    assert failed is not None
    assert failed.status == JobStatus.FAILED

    assert queue.mark_completed("missing") is None
    assert queue.mark_failed("missing") is None
