"""A job that outlives the connection that started it.

The operating constraint is not that the server is unreliable — it demonstrably
is not — but that the *link to it* is. Connections from the operator's network
drop mid-command, complete a TCP handshake and then carry no data, and recover
minutes later. Any design where losing SSH loses the work, or loses the record
of the work, is wrong here.

So a job is a **directory on the server**, not a process handle. Everything
needed to answer "what happened" is written there as it happens: the command, a
state, timestamps, the exit code, both output streams, and where any artifacts
landed. Reconnecting and reading that directory is the whole recovery
procedure — there is no supervisor to reattach to and nothing held in memory.

**State is derived, never asserted.** A job is running because its process is
alive, and finished because an exit code was written. A `state` field that a
supervisor updates is a lie the moment the supervisor dies, and the supervisor
dying is precisely the case this exists for.
"""

from __future__ import annotations

import shlex
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class JobState(StrEnum):
    """Where a job is. Derived from the filesystem, never stored."""

    #: The process is alive.
    RUNNING = "running"
    #: Exit code 0.
    SUCCEEDED = "succeeded"
    #: Exit code non-zero.
    FAILED = "failed"
    #: No live process and no exit code. The machine restarted under it, or it
    #: was killed by something that does not run handlers — the OOM killer, a
    #: cgroup limit, SIGKILL. Distinct from failure because nothing recorded a
    #: verdict, and treating it as success or failure would be inventing one.
    LOST = "lost"


def _now() -> datetime:
    return datetime.now(UTC)


class JobRecord(BaseModel):
    """Everything known about one job, reconstructable from disk alone."""

    model_config = ConfigDict(frozen=True)

    id: str
    #: What it is, for a human scanning a list: "pytest", "e2e", "plan".
    kind: str = "command"
    argv: list[str] = Field(default_factory=list)
    cwd: str = ""
    pid: int = 0
    started_at: datetime = Field(default_factory=_now)
    #: Written when the job ends. Absent while it runs.
    ended_at: datetime | None = None
    exit_code: int | None = None
    state: JobState = JobState.RUNNING
    #: Paths, not contents. A job that captures a gigabyte of build output must
    #: not put that gigabyte in a status response.
    stdout_path: str = ""
    stderr_path: str = ""
    artifacts_dir: str = ""
    note: str = ""

    @property
    def command(self) -> str:
        """For display only. Never re-executed — rebuilding a shell string and
        running it is the injection the argv-only rule exists to prevent."""
        return shlex.join(self.argv)

    @property
    def duration_seconds(self) -> float:
        end = self.ended_at or _now()
        return round((end - self.started_at).total_seconds(), 2)

    @property
    def finished(self) -> bool:
        return self.state is not JobState.RUNNING

    @property
    def ok(self) -> bool:
        return self.state is JobState.SUCCEEDED

    def __str__(self) -> str:
        detail = {
            JobState.RUNNING: f"running for {self.duration_seconds:.0f}s (pid {self.pid})",
            JobState.SUCCEEDED: f"succeeded in {self.duration_seconds:.0f}s",
            JobState.FAILED: f"failed (exit {self.exit_code}) after {self.duration_seconds:.0f}s",
            JobState.LOST: "lost — no exit code and no live process",
        }[self.state]
        return f"{self.id}  {self.kind:<10} {detail}"


class HealthReport(BaseModel):
    """What an operator needs on reconnecting, in one answer.

    Assembled from the machine rather than from memory, because the process that
    would have remembered may not have survived the disconnection either.
    """

    model_config = ConfigDict(frozen=True)

    hostname: str = ""
    uptime: str = ""
    checked_at: datetime = Field(default_factory=_now)

    services: dict[str, str] = Field(default_factory=dict)
    api_healthy: bool = False
    site_host_status: int = 0

    memory_used_mb: int = 0
    memory_total_mb: int = 0
    load_1min: float = 0.0
    disk_used_percent: int = 0
    process_count: int = 0
    browser_count: int = 0

    active_jobs: list[JobRecord] = Field(default_factory=list)
    failed_jobs: list[JobRecord] = Field(default_factory=list)
    last_completed: JobRecord | None = None

    @property
    def site_host_responding(self) -> bool:
        """Whether the site host answered at all.

        Any HTTP status counts, including 404. The root path has no site on it
        by design — sites live at /<slug>/ — so demanding 200 reports a healthy
        web server as down, and a monitor that cries wolf is worse than none.
        Only silence (status 0) means it is not serving.
        """
        return self.site_host_status > 0

    @property
    def healthy(self) -> bool:
        """Every service active, both HTTP surfaces answering, nothing lost."""
        return (
            self.api_healthy
            and self.site_host_responding
            and all(state == "active" for state in self.services.values())
            and not any(job.state is JobState.LOST for job in self.failed_jobs)
        )

    def render(self) -> str:
        lines = [
            f"{self.hostname or 'host'} — {'healthy' if self.healthy else 'DEGRADED'}"
            f"  ({self.uptime})",
            "",
            "services:",
        ]
        for name, state in sorted(self.services.items()):
            mark = "ok " if state == "active" else "DOWN"
            lines.append(f"  {mark} {name:<24} {state}")
        lines += [
            f"  {'ok ' if self.api_healthy else 'DOWN'} api /health",
            f"  {'ok ' if self.site_host_responding else 'DOWN'} site host "
            f"(HTTP {self.site_host_status or 'no response'})",
            "",
            f"resources: {self.memory_used_mb}/{self.memory_total_mb} MB, "
            f"load {self.load_1min}, disk {self.disk_used_percent}%, "
            f"{self.process_count} procs, {self.browser_count} browsers",
            "",
        ]
        if self.active_jobs:
            lines.append(f"running ({len(self.active_jobs)}):")
            lines += [f"  {job}" for job in self.active_jobs]
        else:
            lines.append("running: nothing")
        if self.failed_jobs:
            lines.append(f"failed or lost ({len(self.failed_jobs)}):")
            lines += [f"  {job}" for job in self.failed_jobs]
        if self.last_completed:
            lines.append(f"last completed: {self.last_completed}")
        return "\n".join(lines)


def default_root() -> Path:
    """Where jobs live.

    Under /var/lib rather than /tmp: a job record that a reboot erases cannot
    answer the one question it exists for, which is what happened while nobody
    was watching.
    """
    return Path("/var/lib/qevik/jobs")
