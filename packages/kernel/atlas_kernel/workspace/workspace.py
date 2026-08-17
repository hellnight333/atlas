"""The workspace itself: write files, run commands, serve what was built.

`serve()` deserves a word. Verifying a website means running it and opening it,
which needs a process that outlives a single command and is guaranteed to die
afterwards. A background process that survives its verification is a port leak
on a shared box, and after a few runs nothing can bind anything — so it is a
context manager, it waits for the port rather than sleeping a hopeful two
seconds, and it kills the whole process group because a dev server that spawns
children is not stopped by killing the parent.
"""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

from .models import (
    DEFAULT_TIMEOUT_SECONDS,
    MAX_CAPTURED_BYTES,
    CommandResult,
    FileWrite,
    WorkspaceError,
    WorkspaceRecord,
    safe_join,
)


def _truncate(raw: bytes) -> tuple[str, bool]:
    text = raw.decode("utf-8", errors="replace")
    if len(text) <= MAX_CAPTURED_BYTES:
        return text, False
    half = MAX_CAPTURED_BYTES // 2
    return f"{text[:half]}\n... [truncated] ...\n{text[-half:]}", True


def free_port() -> int:
    """A port the OS says is free.

    Racy in principle — something could take it between here and the bind — but
    the alternative is a hard-coded port that collides with the previous run
    every time, which is not a race but a certainty.
    """
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def wait_for_port(port: int, *, timeout: float = 30.0, host: str = "127.0.0.1") -> bool:
    """Block until something is listening, or give up.

    Polling the port is the only honest signal that a server is ready. Sleeping
    a fixed interval instead produces a test that passes on a fast machine and
    fails on a loaded one, which is worse than no test.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as s:
            s.settimeout(0.5)
            if s.connect_ex((host, port)) == 0:
                return True
        time.sleep(0.1)
    return False


class Workspace:
    """An isolated project directory Qevik may write to and run things in."""

    def __init__(self, record: WorkspaceRecord) -> None:
        self.record = record
        self.root = Path(record.root)
        #: Everything done here, in order. The execution lineage.
        self.history: list[CommandResult | FileWrite] = []

    # -- lifecycle -------------------------------------------------------

    @classmethod
    def create(cls, base: Path | str, name: str) -> Workspace:
        """Make a new project directory under `base`.

        Refuses to reuse an existing directory. Silently adopting one would let
        a new project inherit a previous failure's half-written files, and the
        resulting bug looks like the generator being wrong.
        """
        base = Path(base)
        root = base / name
        if root.exists():
            raise WorkspaceError(
                f"{root} already exists. Workspaces are never silently reused — "
                "pick another name or remove it deliberately."
            )
        root.mkdir(parents=True)
        return cls(WorkspaceRecord(name=name, root=str(root.resolve())))

    @classmethod
    def open(cls, root: Path | str, name: str = "") -> Workspace:
        """Adopt an existing directory — resuming a project, not starting one."""
        root = Path(root)
        if not root.is_dir():
            raise WorkspaceError(f"{root} is not a directory")
        return cls(WorkspaceRecord(name=name or root.name, root=str(root.resolve())))

    def destroy(self) -> None:
        """Remove the directory. Only ever the workspace's own root."""
        shutil.rmtree(self.root, ignore_errors=True)

    # -- files -----------------------------------------------------------

    def write(self, relative: str, content: str) -> FileWrite:
        path = safe_join(self.root, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode("utf-8")
        path.write_bytes(data)
        entry = FileWrite(path=relative, bytes_written=len(data))
        self.history.append(entry)
        return entry

    def read(self, relative: str) -> str:
        return safe_join(self.root, relative).read_text(encoding="utf-8")

    def exists(self, relative: str) -> bool:
        return safe_join(self.root, relative).exists()

    def files(self) -> list[str]:
        """Every file in the project, relative and sorted. What was built."""
        return sorted(
            str(p.relative_to(self.root))
            for p in self.root.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and ".git" not in p.parts
        )

    # -- commands --------------------------------------------------------

    def run(
        self,
        argv: list[str],
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        cwd: str = "",
        env: dict[str, str] | None = None,
        check: bool = False,
    ) -> CommandResult:
        """Run a command inside the workspace and record what happened.

        `argv` is a list. There is no shell, and no overload that accepts a
        string: a shell string assembled from generated text is both an
        injection and an unauditable log line.
        """
        if not argv:
            raise ValueError("no command given")
        if isinstance(argv, str):  # pragma: no cover - defended by the type
            raise TypeError("argv must be a list; a shell string is never accepted")

        working = safe_join(self.root, cwd) if cwd else self.root
        environment = {**os.environ, **(env or {})}
        started = time.monotonic()
        timed_out = False

        try:
            completed = subprocess.run(
                argv,
                cwd=working,
                env=environment,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
            out, err, code = completed.stdout, completed.stderr, completed.returncode
        except subprocess.TimeoutExpired as expired:
            timed_out = True
            out = expired.stdout or b""
            err = expired.stderr or b""
            code = -1
        except FileNotFoundError as missing:
            # A missing tool is a configuration problem, not a failed build, and
            # saying so saves the next person reading a build log for an error
            # that is not in it.
            raise WorkspaceError(
                f"{argv[0]!r} is not installed on this machine ({missing})"
            ) from missing

        stdout, cut_out = _truncate(out)
        stderr, cut_err = _truncate(err)
        result = CommandResult(
            argv=list(argv),
            exit_code=code,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=round(time.monotonic() - started, 3),
            timed_out=timed_out,
            truncated=cut_out or cut_err,
            cwd=str(working),
        )
        self.history.append(result)

        if check and not result.ok:
            raise WorkspaceError(f"{result}\n{result.tail()}")
        return result

    # -- serving ---------------------------------------------------------

    @contextmanager
    def serve(self, argv: list[str], *, port: int, ready_timeout: float = 30.0):
        """Run a server for the duration of the block, then stop it for certain.

        Started in its own process group so the kill reaches children too; a dev
        server that forks a worker is not stopped by killing the parent, and the
        orphan holds the port until the box is rebooted.
        """
        process = subprocess.Popen(
            argv,
            cwd=self.root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            if not wait_for_port(port, timeout=ready_timeout):
                process.terminate()
                output = b""
                try:
                    output = process.communicate(timeout=5)[0] or b""
                except subprocess.TimeoutExpired:  # pragma: no cover
                    pass
                raise WorkspaceError(
                    f"nothing was listening on port {port} after {ready_timeout:g}s.\n"
                    f"{_truncate(output)[0][-2000:]}"
                )
            yield process
        finally:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):  # pragma: no cover
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)

    # -- reporting -------------------------------------------------------

    @property
    def commands(self) -> list[CommandResult]:
        return [h for h in self.history if isinstance(h, CommandResult)]

    @property
    def writes(self) -> list[FileWrite]:
        return [h for h in self.history if isinstance(h, FileWrite)]

    def lineage(self) -> str:
        """Everything done here, in order, as a person would read it."""
        lines = [f"workspace {self.record.id} ({self.record.name}) at {self.root}"]
        for entry in self.history:
            if isinstance(entry, FileWrite):
                lines.append(f"  wrote {entry.path} ({entry.bytes_written} bytes)")
            else:
                lines.append(f"  ran   {entry}")
        return "\n".join(lines)
