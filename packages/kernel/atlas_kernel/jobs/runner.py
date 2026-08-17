"""Starting jobs that survive the connection, and reading them back later.

The mechanism is deliberately dull: a detached `sh` runs the command, redirects
both streams to files, and writes the exit code to a file when it finishes.
There is no daemon, no queue and no supervisor process to reattach to.

That dullness is the feature. Every clever version of this depends on something
staying alive — and the thing that keeps not staying alive here is the link
between the operator and the machine. A directory of files needs nothing to
stay alive; it only needs to be read.

**The exit code is written by the same shell that ran the command.** Any design
where the *starting* process records the outcome loses that outcome exactly when
SSH drops, which is the case this is for.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .models import JobRecord, JobState, default_root

META = "meta.json"
PID = "pid"
STDOUT = "stdout.log"
STDERR = "stderr.log"
EXIT_CODE = "exit_code"
ARTIFACTS = "artifacts"


class JobError(RuntimeError):
    """A job could not be started or read."""


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Alive, owned by someone else. Rare here (everything runs as root) but
        # reporting "dead" because we may not signal it would be wrong.
        return True
    return True


class JobRunner:
    """Starts detached jobs and reads their state from disk."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root or default_root())
        self.root.mkdir(parents=True, exist_ok=True)

    # -- starting ---------------------------------------------------------

    def start(
        self,
        argv: list[str],
        *,
        kind: str = "command",
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        note: str = "",
        job_id: str | None = None,
    ) -> JobRecord:
        """Run `argv` detached and return its record immediately.

        Returns as soon as the job is launched, not when it finishes. Waiting
        here would reintroduce the exact coupling this removes.
        """
        if not argv:
            raise JobError("no command given")
        if isinstance(argv, str):
            raise TypeError("argv must be a list; a shell string is never accepted")

        job_id = job_id or f"job_{datetime.now(UTC):%Y%m%dT%H%M%S}_{uuid4().hex[:6]}"
        directory = self.root / job_id
        if directory.exists():
            raise JobError(f"job {job_id} already exists")
        (directory / ARTIFACTS).mkdir(parents=True)

        # The command is quoted by shlex, so the shell below cannot be made to
        # interpret anything the caller did not intend. The shell exists only to
        # own the redirection and to write the exit code after the command ends.
        inner = (
            f"{shlex.join(argv)} > {shlex.quote(str(directory / STDOUT))} "
            f"2> {shlex.quote(str(directory / STDERR))}; "
            f"printf %s $? > {shlex.quote(str(directory / EXIT_CODE))}"
        )
        # The outer shell backgrounds the real work, records its pid and exits
        # at once. That second fork is what makes the job an orphan, reparented
        # to init.
        #
        # Without it the work stays a direct child of whatever called `start`.
        # When it finished, nobody would reap it, so it would linger as a zombie
        # — and a zombie answers kill(pid, 0), so a dead job with no exit code
        # would report as RUNNING forever. Exactly the wrong answer for the one
        # state this module exists to detect.
        script = f"{{ {inner} ; }} & printf %s $! > {shlex.quote(str(directory / PID))}"

        # A job cannot be told where to put its artifacts before it exists, so
        # it is told through the environment instead. Without this every caller
        # invents its own convention and the artifacts end up somewhere the job
        # record does not point at.
        environment = {
            **os.environ,
            "QEVIK_JOB_ID": job_id,
            "QEVIK_JOB_ARTIFACTS": str(directory / ARTIFACTS),
            "QEVIK_JOB_DIR": str(directory),
            **(env or {}),
        }

        # start_new_session=True calls setsid(2), detaching from the SSH
        # session's process group so a dropped connection cannot signal it.
        launcher = subprocess.Popen(
            ["sh", "-c", script],
            cwd=str(cwd or Path.cwd()),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        # Reaped immediately: it does nothing but fork and exit. Leaving it
        # unwaited would recreate the zombie this design avoids.
        launcher.wait(timeout=10)

        pid_file = directory / PID
        for _ in range(100):
            if pid_file.is_file() and pid_file.read_text(encoding="utf-8").strip():
                break
            time.sleep(0.01)
        try:
            job_pid = int(pid_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError) as error:
            raise JobError(f"job {job_id} did not report a pid: {error}") from error

        record = JobRecord(
            id=job_id,
            kind=kind,
            argv=list(argv),
            cwd=str(cwd or Path.cwd()),
            pid=job_pid,
            stdout_path=str(directory / STDOUT),
            stderr_path=str(directory / STDERR),
            artifacts_dir=str(directory / ARTIFACTS),
            note=note,
        )
        self._write_meta(directory, record)
        return record

    def _write_meta(self, directory: Path, record: JobRecord) -> None:
        # Written through a temporary name so a reader never sees half a file.
        # A status query racing a job start is the normal case, not the corner
        # case, once anything polls.
        payload = record.model_dump(mode="json")
        temporary = directory / f".{META}.tmp"
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(directory / META)

    # -- reading ----------------------------------------------------------

    def get(self, job_id: str) -> JobRecord:
        directory = self.root / job_id
        meta = directory / META
        if not meta.is_file():
            raise JobError(f"no job {job_id!r} under {self.root}")
        stored = JobRecord.model_validate_json(meta.read_text(encoding="utf-8"))
        return self._observe(directory, stored)

    def _observe(self, directory: Path, stored: JobRecord) -> JobRecord:
        """Derive the current state from the filesystem.

        Never trusts the stored `state`. A stored state is a claim made by a
        process that may have died immediately afterwards, which is the failure
        this whole module is designed around.
        """
        exit_file = directory / EXIT_CODE
        if exit_file.is_file():
            raw = exit_file.read_text(encoding="utf-8").strip()
            try:
                code = int(raw)
            except ValueError:
                code = -1
            ended = datetime.fromtimestamp(exit_file.stat().st_mtime, tz=UTC)
            return stored.model_copy(
                update={
                    "exit_code": code,
                    "ended_at": ended,
                    "state": JobState.SUCCEEDED if code == 0 else JobState.FAILED,
                }
            )

        if _pid_alive(stored.pid):
            return stored.model_copy(update={"state": JobState.RUNNING})

        # No exit code and no process. Something removed it without letting it
        # record a verdict — a reboot, the OOM killer, a cgroup limit, SIGKILL.
        # Reporting success or failure would be inventing one.
        return stored.model_copy(update={"state": JobState.LOST})

    def list(self, *, limit: int = 50) -> list[JobRecord]:
        """Newest first. Directory names sort chronologically by construction."""
        if not self.root.is_dir():
            return []
        jobs: list[JobRecord] = []
        for directory in sorted(self.root.iterdir(), reverse=True):
            if not (directory / META).is_file():
                continue
            try:
                jobs.append(self.get(directory.name))
            except JobError:  # pragma: no cover - a partially written job
                continue
            if len(jobs) >= limit:
                break
        return jobs

    def active(self) -> list[JobRecord]:
        return [job for job in self.list() if job.state is JobState.RUNNING]

    def failed(self) -> list[JobRecord]:
        return [job for job in self.list() if job.state in (JobState.FAILED, JobState.LOST)]

    def last_completed(self) -> JobRecord | None:
        for job in self.list():
            if job.finished:
                return job
        return None

    def output(self, job_id: str, *, stream: str = "stdout", tail: int = 40) -> str:
        """The end of a stream. The end is where the error is."""
        record = self.get(job_id)
        path = Path(record.stdout_path if stream == "stdout" else record.stderr_path)
        if not path.is_file():
            return ""
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-tail:] if tail else lines)

    def artifacts(self, job_id: str) -> list[str]:
        directory = Path(self.get(job_id).artifacts_dir)
        if not directory.is_dir():
            return []
        return sorted(str(p) for p in directory.rglob("*") if p.is_file())

    def wait(self, job_id: str, *, timeout: float = 3600.0, poll: float = 2.0) -> JobRecord:
        """Block until the job finishes, or give up saying so.

        Convenience for a caller that happens to still be connected. Nothing
        depends on anyone calling it — that is the point.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            record = self.get(job_id)
            if record.finished:
                return record
            time.sleep(poll)
        raise JobError(
            f"{job_id} still running after {timeout:g}s. It has not been stopped; "
            f"query it again later."
        )

    def stop(self, job_id: str) -> JobRecord:
        """Terminate a running job and its children.

        The whole process group, because a job that spawned a browser or a build
        is not stopped by killing the shell that started it.
        """
        record = self.get(job_id)
        if record.state is not JobState.RUNNING:
            return record
        try:
            os.killpg(os.getpgid(record.pid), 15)
        except (ProcessLookupError, PermissionError) as error:  # pragma: no cover
            raise JobError(f"could not stop {job_id}: {error}") from error
        return self.get(job_id)
