"""What decides that a task is done. None of it is an agent's opinion.

Every gate here reads something the agents cannot write: a process exit code, a
git diff, an HTTP status, a row count. That separation is the whole design, and
it comes from watching the alternative fail — six missions in one session each
reported ending because a "report written", and a verification pass this week
reported failure *after* its audits, findings and signals had already landed.
Prose and outcome are independent variables.

## The gates

`changed`      the intended diff is not empty
`tests`        the relevant tests pass, by exit code
`clean_tree`   the reviewer wrote nothing — proved, not configured
`deployed`     the deploy script exited zero
`in_production` a probe against the live system agrees

A task that requires deployment and does not pass `deployed` never reaches
`in_production`, and a task that fails any required gate does not become DONE.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .queue import redact


@dataclass
class Gate:
    """One objective check, and the evidence for its answer."""

    name: str
    passed: bool
    detail: str = ""
    #: True when the check itself could not run — a missing binary, a timeout,
    #: an unreachable host. Never the same as failing: a gate that could not be
    #: measured has established nothing, and treating it as a pass is how
    #: unverified work ships.
    unmeasured: bool = False


def _sh(argv: list[str], *, cwd: Path, timeout: int) -> tuple[int, str, bool]:
    try:
        done = subprocess.run(argv, cwd=str(cwd), stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as missing:
        return 127, str(missing), False
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s", True
    return done.returncode, redact((done.stdout or "") + (done.stderr or "")), False


def changed(*, cwd: Path, base_sha: str | None = None) -> Gate:
    """Something was actually written.

    An agent that reports success having changed nothing is the commonest
    silent failure, and it is invisible to a test suite that was already green.
    """
    if base_sha:
        code, out, _ = _sh(["git", "diff", "--stat", f"{base_sha}..HEAD"],
                           cwd=cwd, timeout=60)
    else:
        code, out, _ = _sh(["git", "status", "--porcelain"], cwd=cwd, timeout=60)
    if code != 0:
        return Gate("changed", False, f"git failed: {out[:200]}", unmeasured=True)
    if not out.strip():
        return Gate("changed", False,
                    "nothing was changed. A task that reports success and "
                    "leaves no diff has not been carried out.")
    return Gate("changed", True, out.strip().splitlines()[-1][:200])


def clean_tree(*, cwd: Path) -> Gate:
    """The reviewer wrote nothing.

    Asserted by looking rather than by trusting `--sandbox read-only`: a flag
    says what was requested and this says what happened. If a review ever does
    modify the tree, the diff under review is no longer the diff that was
    built, and every conclusion after it is about something else.
    """
    code, out, _ = _sh(["git", "status", "--porcelain"], cwd=cwd, timeout=60)
    if code != 0:
        return Gate("clean_tree", False, f"git failed: {out[:200]}",
                    unmeasured=True)
    if out.strip():
        return Gate("clean_tree", False,
                    f"the working tree changed during review: {out.strip()[:300]}")
    return Gate("clean_tree", True, "the reviewer changed nothing")


def tests(*, cwd: Path, selector: str = "", timeout: int = 2400) -> Gate:
    """The gate, by exit code.

    `selector` narrows to the tests a task touches; empty runs the whole suite.
    A narrowed run is a real gate for a narrow change and is stated as such —
    the full suite still runs before anything is deployed.
    """
    argv = ["python3", "-m", "pytest", "packages/kernel/tests/", "-q",
            "-p", "no:cacheprovider", "--no-cov"]
    if selector:
        argv += ["-k", selector]
    code, out, timed_out = _sh(argv, cwd=cwd, timeout=timeout)
    tail = out.strip().splitlines()[-1] if out.strip() else ""
    if timed_out:
        return Gate("tests", False, f"the suite did not finish in {timeout}s",
                    unmeasured=True)
    return Gate("tests", code == 0, tail[:300])


def deployed(*, cwd: Path, timeout: int = 900) -> Gate:
    """The deploy script's own verdict.

    `deploy_control.sh` installs, restarts, waits for the service to answer and
    puts the previous tree back if it does not. Its exit code is therefore a
    real gate rather than a report that files were copied.
    """
    code, out, timed_out = _sh(["./infra/deploy_control.sh"], cwd=cwd,
                               timeout=timeout)
    if timed_out:
        return Gate("deployed", False, f"the deploy did not finish in {timeout}s",
                    unmeasured=True)
    tail = "\n".join(out.strip().splitlines()[-3:])
    return Gate("deployed", code == 0, tail[:400])


def in_production(*, cwd: Path, probe: str, timeout: int = 600) -> Gate:
    """A probe run against the live system, over the deploy script's own SSH.

    `probe` is a snippet run on the control-plane host with the service's
    environment. It must print `PROVED` for the gate to pass — a probe that
    prints anything else, or nothing, has not proved the thing it was written
    to prove.

    Nothing here may reach a business. Probes read; they do not send.
    """
    key = Path.home() / ".ssh" / "naml_hetzner"
    if not key.exists():
        return Gate("in_production", False, "no key to reach the host",
                    unmeasured=True)
    remote = ("cd /opt/qevik/atlas && set -a && . /opt/qevik/atlas.env && "
              "set +a && PYTHONPATH=packages/kernel .venv/bin/python - <<'PROBE'\n"
              f"{probe}\nPROBE")
    code, out, timed_out = _sh(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20",
         "-o", "ConnectionAttempts=4", "-i", str(key),
         "root@2.28.62.83", remote], cwd=cwd, timeout=timeout)
    if timed_out or code == 255:
        return Gate("in_production", False,
                    f"could not reach the host: {out[:200]}", unmeasured=True)
    proved = "PROVED" in out
    return Gate("in_production", proved,
                out.strip().splitlines()[-1][:300] if out.strip() else "no output")


def required(task: dict) -> tuple[str, ...]:
    """Which gates this task must pass. Declared per task, never inferred."""
    names = ["changed", "tests", "review"]
    if task.get("requires_deploy"):
        names.append("deployed")
    if task.get("requires_prod_check"):
        names.append("in_production")
    return tuple(names)


def summarise(gates: list[Gate]) -> str:
    return " · ".join(
        f"{g.name}={'pass' if g.passed else ('unmeasured' if g.unmeasured else 'fail')}"
        for g in gates)


__all__ = ["Gate", "changed", "clean_tree", "deployed", "in_production",
           "required", "summarise", "tests"]
