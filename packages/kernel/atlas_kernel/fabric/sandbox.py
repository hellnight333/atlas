"""Where a coding agent is allowed to exist.

A CLI coding agent is not a model call. It is a process with its own tool loop
that reads files, writes files, runs commands and calls the network, deciding as
it goes. A worktree is version control, not containment: a process in one can
still read `~/.ssh`, `POST` to anywhere, and write to the vault.

So the isolation is a **container, not a permission** — and this module never
pretends to provide one it cannot. `NoSandbox` refuses to run rather than
quietly executing unconfined, for the same reason `PostgresClaims` refused to
construct unverified: the failure mode of a fake is not an exception, it is a
process that looks contained and is not.

## What is actually enforced

    filesystem   one writable directory. Everything else read-only or absent.
    network      off, unless the work genuinely needs it and says so.
    environment  an allow-list. A credential that is not in the environment
                 cannot be exfiltrated by a process that goes wrong.
    time         a wall clock. A loop that never finishes is killed.

The environment rule is the one people skip. Passing the parent's environment
hands every API key in it to a process whose next action was chosen by a
language model.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

#: Variables a build genuinely needs. Everything else is dropped — including,
#: deliberately, every `*_API_KEY`, `*_TOKEN` and `AWS_*` in the parent.
SAFE_ENVIRONMENT: frozenset[str] = frozenset({
    "PATH", "HOME", "LANG", "LC_ALL", "TERM", "TZ", "SHELL", "USER", "TMPDIR",
})

#: Read-only paths a toolchain needs to exist at all. Nothing under `/home`,
#: nothing under `/root`, nothing under `/etc/ssl/private`.
SYSTEM_PATHS: tuple[str, ...] = ("/usr", "/bin", "/sbin", "/lib", "/lib64",
                                 "/etc/alternatives", "/etc/ssl/certs",
                                 "/etc/ca-certificates")

#: What name resolution needs, bound **only when the network is on**.
#:
#: Found by verification rather than by reading: with an empty tmpfs root and
#: only `SYSTEM_PATHS` mounted, a process with `network=True` still could not
#: resolve `localhost` — `/etc/resolv.conf` and friends were simply absent. An
#: agent asking for the network would have got a confusing DNS failure and
#: concluded the host was broken.
#:
#: Bound only with the network on, so a sandbox that is meant to be offline does
#: not carry the host's resolver configuration into it for no reason.
RESOLVER_PATHS: tuple[str, ...] = ("/etc/resolv.conf", "/etc/hosts",
                                   "/etc/nsswitch.conf", "/etc/services",
                                   "/etc/host.conf", "/etc/gai.conf")


class Confinement(StrEnum):
    """How much of the isolation a host can actually enforce.

    Three values rather than a boolean, because "we could not isolate it" and
    "we chose not to" are different facts and only one of them is a decision.
    """

    #: Filesystem, network, environment and time, all enforced by the kernel.
    FULL = "FULL"
    #: The process is limited by what it is given, not by what it can reach.
    #: Honest, and not sufficient for an agent that writes files.
    PARTIAL = "PARTIAL"
    #: Nothing. Running here is refused.
    NONE = "NONE"


class NotIsolated(RuntimeError):
    """Asked to run an agent where nothing would contain it.

    Raised rather than running unconfined. A caller that would rather proceed
    can catch it and say so in the record; what must not happen is that the
    decision is made silently by the absence of a tool.
    """


@dataclass(frozen=True)
class Isolation:
    """What one run may reach.

    Constructed by the caller, never inferred. A default that guessed would be a
    default that guessed wrong on the machine where it mattered.
    """

    #: The only writable directory. Usually a git worktree.
    workspace: Path
    #: Off unless the work genuinely needs it. `pip install` does; "implement
    #: this function" does not, and leaving it on is how an agent that goes
    #: wrong reaches an API.
    network: bool = False
    #: Extra read-only paths — a shared cache, a toolchain outside `/usr`.
    readable: tuple[Path, ...] = ()
    #: Variables to pass through, on top of `SAFE_ENVIRONMENT`. Named
    #: individually so adding one is a visible act.
    environment: dict[str, str] = field(default_factory=dict)
    seconds: int = 900

    def env(self) -> dict[str, str]:
        """The environment the process actually gets.

        An allow-list, not a deny-list. A deny-list is a promise to have thought
        of every secret anybody will ever put in the parent environment, and the
        one that gets missed is the one that leaks.
        """
        passed = {k: v for k, v in os.environ.items() if k in SAFE_ENVIRONMENT}
        return {**passed, **self.environment}


@dataclass(frozen=True)
class Outcome:
    """What happened, including the honest 'it was killed'."""

    ran: bool
    exit_code: int | None
    stdout: str
    stderr: str
    #: True when the wall clock ran out. Distinct from a non-zero exit: one
    #: means the work failed, the other means nobody knows.
    timed_out: bool = False
    confinement: Confinement = Confinement.NONE
    detail: str = ""


class Bubblewrap:
    """Real isolation, via `bwrap` and unprivileged user namespaces.

    Refuses to construct where `bwrap` is absent rather than degrading to a
    plain `subprocess.run`, which is the same shape of lie as a claim
    implementation that has never seen a database.
    """

    confinement = Confinement.FULL

    def __init__(self, binary: str = "") -> None:
        # An explicit path is checked too. Trusting it because the caller
        # supplied it would move the failure from construction — where it says
        # "there is no sandbox here" — to the first run, where it would look
        # like the agent's command failing.
        found = binary or shutil.which("bwrap") or ""
        if not found or not Path(found).is_file():
            raise NotIsolated(
                f"bwrap is not installed{f' at {binary}' if binary else ''}, so "
                "nothing here would contain a coding agent. Install "
                "bubblewrap, or run the agent on a host that has it — running "
                "unconfined is not the fallback.")
        self._bwrap = found

    def argv(self, command: list[str], isolation: Isolation) -> list[str]:
        """The full `bwrap` invocation.

        Built as a list and returned so it can be read in a test and in a
        report. An isolation whose actual flags nobody can see is one nobody can
        review.
        """
        workspace = isolation.workspace.resolve()
        args = [self._bwrap,
                # A fresh user, pid, ipc and uts namespace. `--die-with-parent`
                # so a killed supervisor does not leave the agent running.
                "--unshare-user", "--unshare-pid", "--unshare-ipc",
                "--unshare-uts", "--die-with-parent", "--new-session",
                # An empty root. Everything reachable is mounted explicitly
                # below, so the default is "absent" rather than "present but
                # hopefully not writable".
                "--tmpfs", "/", "--proc", "/proc", "--dev", "/dev",
                "--tmpfs", "/tmp"]
        for path in SYSTEM_PATHS:
            if Path(path).exists():
                args += ["--ro-bind", path, path]
        for extra in isolation.readable:
            resolved = extra.resolve()
            args += ["--ro-bind", str(resolved), str(resolved)]
        # The one writable place, and the working directory.
        args += ["--bind", str(workspace), str(workspace), "--chdir",
                 str(workspace)]
        if isolation.network:
            for path in RESOLVER_PATHS:
                if Path(path).exists():
                    args += ["--ro-bind", path, path]
        else:
            args.append("--unshare-net")
        return [*args, "--", *command]

    def run(self, command: list[str], isolation: Isolation) -> Outcome:
        try:
            finished = subprocess.run(  # noqa: S603 - argv list, never a shell
                self.argv(command, isolation), capture_output=True, text=True,
                timeout=isolation.seconds, env=isolation.env(), check=False)
        except subprocess.TimeoutExpired as expired:
            return Outcome(
                ran=True, exit_code=None, timed_out=True,
                confinement=self.confinement,
                stdout=_text(expired.stdout), stderr=_text(expired.stderr),
                detail=(f"killed after {isolation.seconds}s. A non-zero exit "
                        "means the work failed; this means nobody knows how "
                        "far it got"))
        return Outcome(ran=True, exit_code=finished.returncode,
                       stdout=finished.stdout, stderr=finished.stderr,
                       confinement=self.confinement,
                       detail="bwrap: filesystem, network, environment and time")


class NoSandbox:
    """The absence, made explicit. Refuses to run.

    Deliberately not a `subprocess.run` passthrough. A passthrough would make
    every test of "the agent cannot read `~/.ssh`" fail loudly on a machine with
    a sandbox and pass silently on one without — which is precisely backwards.
    """

    confinement = Confinement.NONE

    def __init__(self, why: str = "") -> None:
        self.why = why or "no sandbox is available on this host"

    def argv(self, command: list[str], isolation: Isolation) -> list[str]:
        raise NotIsolated(self.why)

    def run(self, command: list[str], isolation: Isolation) -> Outcome:
        raise NotIsolated(
            f"{self.why}. A coding agent writes files and runs commands with "
            "its own tool loop, so running it here would put an unconfined "
            "process on this machine. Refused.")


def available() -> object:
    """The best isolation this host can actually provide.

    Returns `NoSandbox` rather than raising, so a deployment can *report* what
    it has. Running is what refuses.
    """
    try:
        return Bubblewrap()
    except NotIsolated as absent:
        return NoSandbox(str(absent).split(".")[0])


def describe(sandbox: object) -> dict:
    """What this host enforces, in the words a report needs."""
    confinement = getattr(sandbox, "confinement", Confinement.NONE)
    return {
        "implementation": type(sandbox).__name__,
        "confinement": confinement.value,
        "can_run_coding_agents": confinement is Confinement.FULL,
        "detail": (
            "Filesystem, network, environment and wall clock are enforced by "
            "the kernel." if confinement is Confinement.FULL else
            "A coding agent would run unconfined here, so it is refused. "
            "Install bubblewrap, or route this work to a host that has it."),
    }


def _text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value if isinstance(value, str) else ""
