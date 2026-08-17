"""Jobs that outlive the connection that started them.

The constraint is not an unreliable server — it is an unreliable link to one.
Connections drop mid-command and recover minutes later, so any design where
losing SSH loses the work, or the record of the work, is wrong. These tests are
mostly about the second half: the record has to survive the process that made
it.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from atlas_kernel.jobs import JobError, JobRunner, JobState
from atlas_kernel.jobs.runner import EXIT_CODE, META

pytestmark = pytest.mark.integration


@pytest.fixture
def runner(tmp_path: Path) -> JobRunner:
    return JobRunner(tmp_path / "jobs")


def _finish(runner: JobRunner, job_id: str, timeout: float = 20.0):
    return runner.wait(job_id, timeout=timeout, poll=0.05)


class TestSurvivingTheCaller:
    def test_a_job_keeps_running_after_the_starter_stops_watching(self, runner: JobRunner) -> None:
        """The whole point. `start` returns immediately and the work continues
        with nothing holding it."""
        record = runner.start(["sh", "-c", "sleep 1; echo finished"], kind="slow")
        assert record.state is JobState.RUNNING
        assert runner.get(record.id).state is JobState.RUNNING
        assert _finish(runner, record.id).ok
        assert "finished" in runner.output(record.id)

    def test_the_job_is_in_its_own_session(self, runner: JobRunner) -> None:
        """Detached from the SSH session's process group, so a dropped
        connection cannot take it down with a signal to the group."""
        record = runner.start(["sh", "-c", "sleep 2"])
        assert os.getpgid(record.pid) != os.getpgid(os.getpid())
        runner.stop(record.id)

    def test_a_second_runner_reads_a_job_the_first_one_started(self, tmp_path: Path) -> None:
        """Reconnecting is a new process. If state lived in memory this would be
        the moment it was lost."""
        first = JobRunner(tmp_path / "jobs")
        record = first.start(["sh", "-c", "echo from the past; exit 0"], kind="handoff")

        reconnected = JobRunner(tmp_path / "jobs")
        final = reconnected.wait(record.id, timeout=20, poll=0.05)
        assert final.ok
        assert final.kind == "handoff"
        assert "from the past" in reconnected.output(record.id)


class TestStateIsDerivedNotAsserted:
    """A stored state is a claim by a process that may have died immediately
    afterwards, which is the failure this module is designed around."""

    def test_a_finished_job_reads_as_finished_even_though_meta_says_running(
        self, runner: JobRunner
    ) -> None:
        record = runner.start(["sh", "-c", "exit 0"])
        _finish(runner, record.id)
        stored = json.loads((runner.root / record.id / META).read_text())
        assert stored["state"] == "running", "meta is written once, at start"
        assert runner.get(record.id).state is JobState.SUCCEEDED

    def test_a_job_with_no_exit_code_and_no_process_is_lost_not_failed(
        self, runner: JobRunner
    ) -> None:
        """A reboot, the OOM killer, a cgroup limit or SIGKILL leaves no
        verdict. Reporting success or failure would be inventing one."""
        record = runner.start(["sh", "-c", "sleep 30"])
        os.killpg(os.getpgid(record.pid), 9)
        time.sleep(0.3)
        assert runner.get(record.id).state is JobState.LOST

    def test_an_unreadable_exit_code_is_a_failure_not_a_crash(self, runner: JobRunner) -> None:
        record = runner.start(["sh", "-c", "exit 0"])
        _finish(runner, record.id)
        (runner.root / record.id / EXIT_CODE).write_text("not-a-number")
        assert runner.get(record.id).state is JobState.FAILED


class TestOutcomes:
    def test_a_failing_job_keeps_its_exit_code_and_stderr(self, runner: JobRunner) -> None:
        record = runner.start(["sh", "-c", "echo bad >&2; exit 7"])
        final = _finish(runner, record.id)
        assert final.state is JobState.FAILED
        assert final.exit_code == 7
        assert "bad" in runner.output(record.id, stream="stderr")

    def test_both_streams_are_kept_separately(self, runner: JobRunner) -> None:
        record = runner.start(["sh", "-c", "echo out; echo err >&2"])
        _finish(runner, record.id)
        assert runner.output(record.id, stream="stdout").strip() == "out"
        assert runner.output(record.id, stream="stderr").strip() == "err"

    def test_timestamps_bracket_the_run(self, runner: JobRunner) -> None:
        record = runner.start(["sh", "-c", "sleep 0.4"])
        final = _finish(runner, record.id)
        assert final.ended_at is not None
        assert final.ended_at >= final.started_at
        assert final.duration_seconds >= 0.3

    def test_artifacts_have_a_declared_home(self, runner: JobRunner) -> None:
        record = runner.start(["sh", "-c", "exit 0"])
        _finish(runner, record.id)
        Path(record.artifacts_dir, "report.txt").write_text("evidence")
        assert runner.artifacts(record.id) == [str(Path(record.artifacts_dir, "report.txt"))]

    def test_the_tail_is_where_the_error_is(self, runner: JobRunner) -> None:
        record = runner.start(["sh", "-c", "for i in $(seq 1 50); do echo $i; done"])
        _finish(runner, record.id)
        assert runner.output(record.id, tail=3).split() == ["48", "49", "50"]


class TestListing:
    def test_newest_first(self, runner: JobRunner) -> None:
        ids = [runner.start(["sh", "-c", "exit 0"], job_id=f"job_{i}").id for i in range(3)]
        assert [j.id for j in runner.list()] == list(reversed(ids))

    def test_active_and_failed_are_separable(self, runner: JobRunner) -> None:
        bad = runner.start(["sh", "-c", "exit 3"], job_id="job_a")
        slow = runner.start(["sh", "-c", "sleep 5"], job_id="job_b")
        _finish(runner, bad.id)
        assert [j.id for j in runner.failed()] == [bad.id]
        assert [j.id for j in runner.active()] == [slow.id]
        runner.stop(slow.id)

    def test_last_completed_skips_what_is_still_running(self, runner: JobRunner) -> None:
        done = runner.start(["sh", "-c", "exit 0"], job_id="job_a")
        _finish(runner, done.id)
        running = runner.start(["sh", "-c", "sleep 5"], job_id="job_b")
        assert runner.last_completed().id == done.id
        runner.stop(running.id)

    def test_an_empty_store_is_not_an_error(self, tmp_path: Path) -> None:
        assert JobRunner(tmp_path / "empty").list() == []


class TestRefusals:
    def test_an_unknown_job_says_where_it_looked(self, runner: JobRunner) -> None:
        with pytest.raises(JobError, match="no job"):
            runner.get("job_that_never_was")

    def test_an_empty_command_is_refused(self, runner: JobRunner) -> None:
        with pytest.raises(JobError, match="no command"):
            runner.start([])

    def test_a_shell_string_is_never_accepted(self, runner: JobRunner) -> None:
        with pytest.raises(TypeError, match="never accepted"):
            runner.start("rm -rf /")  # type: ignore[arg-type]

    def test_reusing_a_job_id_is_refused(self, runner: JobRunner) -> None:
        """Silently reusing one would overwrite the record of what happened."""
        runner.start(["sh", "-c", "exit 0"], job_id="job_x")
        with pytest.raises(JobError, match="already exists"):
            runner.start(["sh", "-c", "exit 0"], job_id="job_x")

    def test_arguments_are_not_reinterpreted_by_the_shell(self, runner: JobRunner) -> None:
        """The shell owns redirection only; shlex quoting means an argument
        containing shell syntax stays an argument."""
        record = runner.start(["sh", "-c", 'printf "%s" "$1"', "_", "; touch /tmp/pwned ;"])
        _finish(runner, record.id)
        assert runner.output(record.id).strip() == "; touch /tmp/pwned ;"
        assert not Path("/tmp/pwned").exists()

    def test_waiting_gives_up_without_stopping_the_job(self, runner: JobRunner) -> None:
        record = runner.start(["sh", "-c", "sleep 5"])
        with pytest.raises(JobError, match="query it again later"):
            runner.wait(record.id, timeout=0.3, poll=0.05)
        assert runner.get(record.id).state is JobState.RUNNING
        runner.stop(record.id)


class TestStopping:
    def test_stopping_kills_the_whole_group(self, runner: JobRunner) -> None:
        """A job that spawned a browser or a build is not stopped by killing the
        shell that started it."""
        record = runner.start(["sh", "-c", "sleep 30 & sleep 30"])
        child_group = os.getpgid(record.pid)
        runner.stop(record.id)
        time.sleep(0.5)
        # ESRCH on Linux; macOS reports EPERM for a group that no longer has a
        # live member. Either answer means the group is gone, and asserting on
        # only one of them makes this pass on one platform and fail on the other.
        with pytest.raises((ProcessLookupError, PermissionError)):
            os.killpg(child_group, 0)

    def test_stopping_a_finished_job_is_harmless(self, runner: JobRunner) -> None:
        record = runner.start(["sh", "-c", "exit 0"])
        _finish(runner, record.id)
        assert runner.stop(record.id).state is JobState.SUCCEEDED
