"""An isolated place to build something, and a record of everything done to it.

The execution layer could route jobs to providers and generate text, but it
could not write a file or run a command. Steps 7 through 13 of the autonomous
loop — write code, run tools, run tests, diagnose, fix, re-run, build — were
therefore not merely unimplemented, they were unreachable. This package is the
missing floor under all of them.

Four rules are enforced by the types rather than by discipline.

**Commands are argv lists, never shell strings.** A shell string built from a
model's output is an injection waiting to happen, and it is also unauditable:
`sh -c "..."` records one opaque command where a list records the real one.

**Every command has a timeout.** A hung build on a 4-vCPU box does not fail, it
occupies. The whole factory then stops for a reason that never appears in any
log.

**Every path is confined to the workspace.** An agent writing outside its own
directory is the single most damaging thing a coding capability can do, and it
happens through ordinary carelessness — a `..` in a generated path — far more
often than through malice.

**Output is captured and capped.** A build that prints half a gigabyte must not
take the control plane down with it; the box has 8 GB and Postgres is on it.
"""

from __future__ import annotations

import shlex
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

#: The capability. Asked for by name; never a runtime.
CODE_EXECUTE = "code.execute"

#: Beyond this a stream is truncated. Generous enough for a real test run,
#: small enough that a runaway loop cannot exhaust an 8 GB box.
MAX_CAPTURED_BYTES = 512_000

#: No command may run forever, and a default that is merely large is the same
#: as no default at all once something hangs.
DEFAULT_TIMEOUT_SECONDS = 300.0


def _now() -> datetime:
    return datetime.now(UTC)


class WorkspaceError(RuntimeError):
    """Something about the workspace itself is wrong."""


class PathEscape(WorkspaceError):
    """A path pointed outside the workspace.

    Its own type because it is the failure that matters most: everything else
    here damages a project, and this one damages the host.
    """


class CommandResult(BaseModel):
    """What a command did. The unit of the audit trail.

    Kept whether the command succeeded or failed, because a factory that only
    records its successes cannot diagnose anything.
    """

    model_config = ConfigDict(frozen=True)

    argv: list[str]
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
    timed_out: bool = False
    truncated: bool = False
    cwd: str = ""
    at: datetime = Field(default_factory=_now)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    @property
    def command(self) -> str:
        """The command as a human would type it. For reports, never for running —
        rebuilding a shell string and executing it is the injection this design
        exists to avoid."""
        return shlex.join(self.argv)

    def tail(self, lines: int = 20) -> str:
        """The end of the output, which is where the error usually is."""
        combined = (self.stdout + ("\n" + self.stderr if self.stderr else "")).strip()
        return "\n".join(combined.splitlines()[-lines:])

    def __str__(self) -> str:
        state = "timed out" if self.timed_out else f"exit {self.exit_code}"
        return f"{self.command} — {state} in {self.duration_seconds:.1f}s"


class FileWrite(BaseModel):
    """A file Qevik created or changed. Part of the lineage."""

    model_config = ConfigDict(frozen=True)

    path: str
    bytes_written: int
    at: datetime = Field(default_factory=_now)


class WorkspaceRecord(BaseModel):
    """The durable identity of a project, and everything done to it.

    Separate from the directory on disk so a workspace survives being inspected,
    reported on, or resumed. The id is immutable for the same reason a Business
    id is: other records point at it.
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: f"ws_{uuid4().hex[:12]}")
    name: str
    root: str
    created_at: datetime = Field(default_factory=_now)


def safe_join(root: Path, relative: str) -> Path:
    """Resolve `relative` inside `root`, or refuse.

    Checked after resolution rather than by inspecting the string, because
    `a/../../b`, a symlink and an absolute path are three different ways to
    leave a directory and only one of them is visible in the text.
    """
    root = root.resolve()
    candidate = (root / relative).resolve()
    if candidate != root and root not in candidate.parents:
        raise PathEscape(
            f"{relative!r} resolves to {candidate}, which is outside the workspace at {root}"
        )
    return candidate
