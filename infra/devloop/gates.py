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
`scope`        every changed path is inside the task's allowed-path contract
`clean_tree`   the reviewer wrote nothing — proved, not configured
`deployed`     the deploy script exited zero, for one named commit
`provenance`   the host's own marker says it installed that commit
`in_production` a probe against the live system agrees

A task that requires deployment and does not pass `deployed` never reaches
`in_production`, and a task that fails any required gate does not become DONE.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .queue import redact
from .targets import control_plane, remote_python, ssh_argv

#: Where the deploy script records what the host holds. Read back, never
#: written from here.
MARKER = "/opt/qevik/atlas/DEPLOYED_SHA"

#: A full commit id and nothing else. A short sha, a branch name or an empty
#: string is not a commit to deploy.
_FULL_SHA = re.compile(r"\A[0-9a-f]{40}\Z")

#: A whole `key=value` line of the marker. Whole lines only: a marker is
#: parsed, never searched, so a sha appearing inside some other field can
#: never be mistaken for the authoritative one.
_MARKER_LINE = re.compile(r"\A([A-Za-z0-9_]+)=(.*)\Z")

#: How long to wait between provenance reads that could not reach the host.
_RETRY_PAUSE_S = 10


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
    #: What the gate measured, in a form a record can keep and a person can
    #: disagree with — lists of paths, not a sentence about them.
    evidence: dict = field(default_factory=dict)


def _sh(argv: list[str], *, cwd: Path, timeout: int,
        env: dict[str, str] | None = None) -> tuple[int, str, bool]:
    """Run a command and answer with its exit code, its output, and whether it
    ran out of time.

    `env` is not a merge into the operator's environment. When it is given the
    child gets this process's environment **with every `QEVIK_*` variable
    removed** and then `env` applied, so a test seam or a `QEVIK_TEST_HOST=1`
    left in the shell that started the driver cannot reach a production deploy.
    Omitted, the child inherits the environment unchanged.

    The child also runs in its own process group, and a timeout kills the whole
    group. `subprocess.run`'s timeout kills only the direct child, which for the
    deploy script leaves its `rsync`/`ssh` still writing to the host after the
    driver has given up and called the gate unmeasured.
    """
    child_env = None
    if env is not None:
        child_env = {name: value for name, value in os.environ.items()
                     if not name.startswith("QEVIK_")}
        child_env.update(env)
    try:
        proc = subprocess.Popen(argv, cwd=str(cwd), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, env=child_env, start_new_session=True)
    except FileNotFoundError as missing:
        return 127, str(missing), False
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        try:
            proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:                     # pragma: no cover
            proc.kill()
        return 124, f"timed out after {timeout}s", True
    return proc.returncode, redact((out or "") + (err or "")), False


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


#: What one bounded loop run can actually carry, calibrated on real outcomes.
#:
#: Measured across four tasks, counting the lines that are **not** tests:
#:
#:     404 page          3 files, 123 non-test lines  → landed
#:     web-server config 2 files,  82 non-test lines  → landed, clean first review
#:     unreviewed drafts 4 files, 605 non-test lines  → could not converge
#:     site routing     35 files, 1523 non-test lines → contested three times
#:
#: Non-test lines separate them cleanly and total lines do not: the two that
#: landed carried 181 and 216 lines of tests between them, and a limit counting
#: those would have refused exactly the work this project wants most. Tests are
#: not the cost a review round pays.
#:
#: Then 400 proved too tight, and the way it failed is the useful part. Split
#: to a single module and its tests — the smallest coherent unit there is — the
#: task still measured 468 non-test lines and was parked. Splitting a module
#: further would produce two halves of one idea, which is worse than a long
#: review: the limit had started refusing work rather than protecting it.
#:
#: This codebase writes long explanatory prose in its source, so line count
#: tracks style as much as scope. What actually discriminates is the number of
#: distinct concerns, and file count approximates that: thirty-five files was
#: many concerns, two modules with two concerns could not converge, one module
#: with one concern was never given the chance.
#:
#: So the line limit is set generously — high enough that no single coherent
#: module trips it — and the file count and the three-round cap do the real
#: work. There is no evidence that 468 lines in one module cannot converge, and
#: parking on an unvalidated threshold is guessing.
TOO_MANY_FILES = 14
TOO_MANY_LINES = 800


def _is_test(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return name.startswith("test_") or "/tests/" in path


def size(*, cwd: Path, base_sha: str) -> Gate:
    """Whether this change is small enough for one bounded run to finish.

    Checked against the diff rather than the brief, because a task's real size
    is only known once it is written — the routing task was scoped as one
    config change and arrived as thirty-eight files.

    `base_sha..HEAD` is the committed range: the unit the reviewer is shown and
    the squash would land. **The caller must therefore commit the round's work
    before asking.** Measured earlier, this range holds every round except the
    one just written — see the note in `driver.run_task`, and the empty-range
    refusal below, which is what stops that mistake from reading as a pass.

    Failing here is not a defect in the work. It means the task was drawn too
    wide, and the driver requeues it to be split rather than spending three
    review rounds discovering the same thing.
    """
    code, out, _ = _sh(["git", "diff", "--numstat", f"{base_sha}..HEAD"],
                       cwd=cwd, timeout=60)
    if code != 0:
        return Gate("size", False, f"git failed: {out[:200]}", unmeasured=True)
    files = changed = in_tests = 0
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        files += 1
        # A binary file reports "-"; it counts as a file and no lines.
        lines = ((int(parts[0]) if parts[0].isdigit() else 0)
                 + (int(parts[1]) if parts[1].isdigit() else 0))
        if _is_test(parts[2]):
            in_tests += lines
        else:
            changed += lines
    evidence = {"files": files, "non_test_lines": changed,
                "test_lines": in_tests}
    # An empty range is not a small change; it is a change this gate never
    # saw. Reporting it as a pass is how the gate satisfied itself with its own
    # absence — round one measured `base` against `base`, found nothing, and
    # said "small enough" about work that had not been committed yet.
    if not files:
        return Gate("size", False,
                    f"nothing is committed in {base_sha[:12]}..HEAD, so no "
                    f"size was measured. An empty range says nothing about how "
                    f"large this round is; commit the work before asking.",
                    unmeasured=True, evidence=evidence)
    if files > TOO_MANY_FILES or changed > TOO_MANY_LINES:
        return Gate("size", False,
                    f"{files} files and {changed} lines outside tests is more "
                    f"than one run can review and converge on (limits: "
                    f"{TOO_MANY_FILES} files, {TOO_MANY_LINES} non-test "
                    f"lines). Split it at a real boundary rather than spending "
                    f"rounds on it.", evidence=evidence)
    return Gate("size", True,
                f"{files} file(s), {changed} line(s) outside tests"
                + (f", {in_tests} in tests" if in_tests else ""),
                evidence=evidence)


def _glob(pattern: str) -> re.Pattern:
    """A contract glob as a regex. `*` stops at `/`; only `**` crosses it.

    `fnmatch` lets `*` run across directories, so `tests/test_*.py` would
    quietly cover `tests/deep/nested/test_x.py`. A contract should mean what
    it looks like it means, so directory-crossing is spelled `**` and nothing
    else does it.
    """
    out, i = [], 0
    while i < len(pattern):
        ch = pattern[i]
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif ch == "*":
            out.append("[^/]*")
            i += 1
        elif ch == "?":
            out.append("[^/]")
            i += 1
        elif ch == "[":
            end = pattern.find("]", i + 1)
            if end < 0:
                out.append(re.escape(ch))
                i += 1
            else:
                out.append(pattern[i:end + 1])
                i = end + 1
        else:
            out.append(re.escape(ch))
            i += 1
    return re.compile("".join(out) + r"\Z")


def within(path: str, pattern: str) -> bool:
    """Whether one changed path falls under one contract entry.

    Three spellings, on purpose kept apart: a trailing `/` is a directory and
    covers everything beneath it; a glob character makes it a glob, matched
    against the whole repo-relative path with `*` stopping at `/`; anything
    else is one exact file.
    """
    if pattern.endswith("/"):
        return path.startswith(pattern)
    if any(ch in pattern for ch in "*?["):
        return _glob(pattern).match(path) is not None
    return path == pattern


def scope(*, cwd: Path, base_sha: str, allowed: list[str]) -> Gate:
    """Every path the commits changed is one the task was allowed to change.

    Measured on the committed range, not the working tree, so the paths this
    gate examined are the paths the reviewer will see and the ones a squash
    would land: the record it leaves is about a commit that cannot change
    under it. Renames are not followed — a file moved out of the contract is a
    write outside it, and following the rename would report it as inside.

    The contract is compared against what was actually written, by the driver,
    which is the distinction that makes it enforcement. A brief that says
    "only the repository" is an instruction to the builder; this gate does not
    read the brief and does not ask the builder, it reads the diff.
    """
    code, out, _ = _sh(["git", "diff", "--name-only", "--no-renames",
                        f"{base_sha}..HEAD"], cwd=cwd, timeout=60)
    if code != 0:
        return Gate("scope", False, f"git failed: {out[:200]}", unmeasured=True,
                    evidence={"declared": list(allowed)})
    changed = [line.strip() for line in out.splitlines() if line.strip()]
    undeclared = [path for path in changed
                  if not any(within(path, one) for one in allowed)]
    evidence = {"declared": list(allowed), "changed": changed,
                "undeclared": undeclared,
                "verdict": "out_of_scope" if undeclared else "in_scope"}
    if undeclared:
        return Gate("scope", False,
                    f"{len(undeclared)} of {len(changed)} changed path(s) lie "
                    f"outside the allowed-path contract: "
                    + ", ".join(undeclared[:8])
                    + (" …" if len(undeclared) > 8 else ""),
                    evidence=evidence)
    return Gate("scope", True,
                f"{len(changed)} changed path(s), all inside the contract",
                evidence=evidence)


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
    if code != 0:
        return Gate("tests", False, tail[:300])

    # Exit zero is not the same as "something was checked".
    #
    # A narrowed run whose every selected test skipped exits zero and reports
    # `pass`, and nothing was asserted. It happened: a task added a page to the
    # site builder, its tests skipped because the artwork is gitignored and the
    # site cannot be built locally, the gate passed, and the page was never
    # produced by a real build. The tests were honest — their skip message says
    # "Nothing below is being asserted" — and the gate did not read it.
    #
    # Skips are legitimate in general, so this only fires when a run selected
    # tests and *none* of them ran.
    ran = re.search(r"(\d+)\s+passed", out)
    skipped = re.search(r"(\d+)\s+skipped", out)
    if not ran and skipped and int(skipped.group(1)):
        return Gate("tests", False,
                    f"every selected test skipped ({skipped.group(1)}); "
                    f"nothing was asserted about this change",
                    unmeasured=True)
    return Gate("tests", True, tail[:300])


def deployed(*, cwd: Path, sha: str, timeout: int = 3600) -> Gate:
    """The deploy script's own verdict, for one named commit.

    `deploy_control.sh` builds its payload from `QEVIK_DEPLOY_SHA` — never from
    the working tree — installs, restarts, waits for the service to answer and
    puts the previous tree back if it does not. Its exit code is therefore a
    real gate rather than a report that files were copied.

    The sha is checked here before anything runs, because a deploy script asked
    to ship nothing in particular is the failure this gate exists to prevent.

    3600 s is above the script's own worst case — twelve retries with their
    sleeps on every remote step plus both polls' full patience, about fifty
    minutes — and inside the lease the driver renews immediately before calling.
    A script still running after that is on a dead link: the answer is
    unmeasured, never a failed deploy.
    """
    if not _FULL_SHA.match(sha or ""):
        return Gate("deployed", False, "no commit to deploy",
                    evidence={"sha": sha})
    code, out, timed_out = _sh(["./infra/deploy_control.sh"], cwd=cwd,
                               timeout=timeout,
                               env={"QEVIK_DEPLOY_SHA": sha})
    if timed_out:
        return Gate("deployed", False, f"the deploy did not finish in {timeout}s",
                    unmeasured=True, evidence={"sha": sha, "exit": code})
    tail = "\n".join(out.strip().splitlines()[-3:])
    return Gate("deployed", code == 0, tail[:400],
                evidence={"sha": sha, "exit": code})


def _ssh_argv(remote: str) -> list[str]:
    """The one way this module reaches the control plane.

    Shared by `in_production` and `provenance` so the key, the host and the
    connection options are stated once. What either gate *runs* and how either
    one *decides* stays its own.
    """
    target = control_plane()
    if target is None:
        raise LookupError("no control-plane target is configured")
    return ssh_argv(target, remote, connect_timeout=20, attempts=4)


def provenance(*, sha: str, timeout: int = 120) -> Gate:
    """What the host says it is holding, read back from its own marker.

    The deploy gate answers "the script exited zero". That is not the same
    claim as "the host holds `S`": the marker is written when the content is
    installed and verified on disk, and only `state=installed` means it. So the
    driver reads the marker before any production verification is allowed to
    say anything about `S`.

    Parsed, never searched. Every whole `key=value` line is taken, and a key
    that appears more than once makes the gate **fail** — the marker has
    exactly one writer and never legitimately repeats a key, so a repetition is
    a malformed or tampered marker, and last-value-wins would let
    `state=rolled-back` followed by `state=installed` pass.

    A host that cannot be reached is unmeasured, never failed, and is retried
    twice before that is concluded.
    """
    if control_plane() is None:
        # Not a failure of the change: this machine has not been told which
        # production host to read. Raising here would take the driver down.
        return Gate("provenance", False,
                    "no control-plane target is configured (QEVIK_DEPLOY_TARGET), "
                    "or its key is missing here",
                    unmeasured=True)
    argv = _ssh_argv(f"cat {MARKER} 2>/dev/null || echo 'state=missing'")
    code, out = 0, ""
    for attempt in range(3):
        code, out, timed_out = _sh(argv, cwd=Path.home(), timeout=timeout)
        if not (timed_out or code in (255, 124, 127)):
            break
        if attempt < 2:
            time.sleep(_RETRY_PAUSE_S)
    else:
        return Gate("provenance", False,
                    f"could not reach the host: {out[:200]}", unmeasured=True,
                    evidence={"expected": sha, "marker": {}})
    if code != 0:
        return Gate("provenance", False,
                    f"no provenance recorded on the host ({code})",
                    evidence={"expected": sha, "marker": {}})

    pairs = []
    for line in out.splitlines():
        found = _MARKER_LINE.match(line.strip())
        if found:
            pairs.append((found.group(1), found.group(2).strip()))
    repeated = sorted({key for key, count in Counter(k for k, _ in pairs).items()
                       if count > 1})
    if repeated:
        # Fails closed, and before any comparison: a marker that says two
        # things has not said either of them.
        return Gate("provenance", False,
                    "malformed provenance: duplicate " + ", ".join(repeated),
                    evidence={"expected": sha, "duplicates": repeated,
                              "marker": {}})
    marker = dict(pairs)
    if marker.get("sha") == sha and marker.get("state") == "installed":
        return Gate("provenance", True,
                    f"the host holds {sha[:12]}, state=installed",
                    evidence={"expected": sha, "marker": marker})
    if not marker.get("sha") or marker.get("state") == "missing":
        detail = "no provenance recorded on the host"
    else:
        detail = (f"host holds sha={marker.get('sha', '')} "
                  f"state={marker.get('state', '')}, expected {sha} installed")
    return Gate("provenance", False, detail,
                evidence={"expected": sha, "marker": marker})


def in_production(*, cwd: Path, probe: str, timeout: int = 600) -> Gate:
    """A probe run against the live system, over the deploy script's own SSH.

    `probe` is a snippet run on the control-plane host with the service's
    environment. It must print `PROVED` for the gate to pass — a probe that
    prints anything else, or nothing, has not proved the thing it was written
    to prove.

    Nothing here may reach a business. Probes read; they do not send.
    """
    if control_plane() is None:
        return Gate("in_production", False,
                    "no control-plane target is configured (QEVIK_DEPLOY_TARGET), "
                    "or its key is missing here",
                    unmeasured=True)
    remote = remote_python(probe, heredoc="PROBE")
    code, out, timed_out = _sh(_ssh_argv(remote), cwd=cwd, timeout=timeout)
    if timed_out or code == 255:
        return Gate("in_production", False,
                    f"could not reach the host: {out[:200]}", unmeasured=True)
    # A line whose first word is exactly PROVED. **Not a substring search.**
    #
    # It was `"PROVED" in out`, and `"PROVED" in "NOT PROVED"` is True — so a
    # probe that correctly reported failure passed the gate, and a task whose
    # defect is still live on the public internet was marked DONE and
    # production-verified. The gate could not fail.
    #
    # Every other negation a probe might print — NOT PROVED, UNPROVED,
    # DISPROVED, NOT_PROVED — is caught by the same rule, because each puts
    # something other than `PROVED` first.
    proved = any(line.strip().split()[:1] == ["PROVED"]
                 for line in out.splitlines() if line.strip())
    return Gate("in_production", proved,
                out.strip().splitlines()[-1][:300] if out.strip() else "no output")


def host_reachable(*, timeout: int = 40) -> Gate:
    """Whether the control plane can be reached at all.

    Asked before a task starts rather than discovered by its deploy gate forty
    minutes later. The link to this host drops for long stretches — TCP
    connects and the SSH banner exchange times out — and a task that needs the
    host cannot finish while that lasts.

    An unreachable host is `unmeasured`, never a failure of the work: it says
    nothing about the change, and treating it as one would requeue good work
    with a misleading reason.
    """
    target = control_plane()
    if target is None:
        return Gate("host", False,
                    "no control-plane target is configured (QEVIK_DEPLOY_TARGET), "
                    "or its key is missing here",
                    unmeasured=True)
    code, out, timed_out = _sh(
        ssh_argv(target, "true", connect_timeout=15, attempts=2),
        cwd=Path.home(), timeout=timeout)
    if timed_out or code != 0:
        return Gate("host", False,
                    "the control plane is not reachable from here; work that "
                    "needs it cannot finish until the link returns",
                    unmeasured=True)
    return Gate("host", True, "reachable")


def required(task: dict) -> tuple[str, ...]:
    """Which gates this task must pass. Declared per task, never inferred."""
    names = ["changed", "tests", "scope", "review"]
    if task.get("requires_deploy"):
        names.append("deployed")
    if task.get("requires_prod_check"):
        names.append("in_production")
    return tuple(names)


def summarise(gates: list[Gate]) -> str:
    return " · ".join(
        f"{g.name}={'pass' if g.passed else ('unmeasured' if g.unmeasured else 'fail')}"
        for g in gates)


__all__ = ["Gate", "MARKER", "changed", "clean_tree", "deployed",
           "in_production", "provenance", "required", "scope", "size",
           "summarise", "tests", "within"]
