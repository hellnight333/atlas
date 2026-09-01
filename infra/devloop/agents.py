"""Invoking the two agents. Exit codes decide; prose never does.

Both are real CLIs on this machine, verified before this file existed:

    claude
    codex  codex-cli 0.144.1

## The rule that shapes everything here

**Codex is never told what Claude did.** It receives the repository and a git
diff, and nothing else — no task brief, no build report, no claim of
completion. That is not politeness about bias; it is the reason the reviewer
works. A reviewer handed the author's account of the change reviews the account.

Proved before this file was written: pointed at one file with no report, Codex
found two real defects in code that had passed 3964 tests and its author's own
review. `reviewer_prompt` therefore takes no arguments.

## Prose is not a result

`claude -p --output-format json` returns `is_error` and an exit code; `codex
exec` returns an exit code and writes its final message to a file. Those are the
signals. An agent that says "done" and changed nothing is a failure, and the
gates in `gates.py` decide that from git and pytest rather than from a sentence.

## Two constraints found by running it

Both cost a wasted run before they were understood:

* `~/.codex/config.toml` sets `model_reasoning_effort = "xhigh"`, under which a
  single-file review did not finish in **8m20s** and wrote no output. Every call
  here passes an explicit effort.
* A backgrounded `codex exec` reads stdin and waits. Every call redirects from
  `/dev/null`.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .queue import redact

HERE = Path(__file__).resolve().parent
SCHEMA = HERE / "review.schema.json"

#: Reasoning effort for the reviewer. `xhigh` — the machine's configured
#: default — did not return inside eight minutes on one file. `medium` returned
#: real findings in about ninety seconds.
REVIEW_EFFORT = "medium"


@dataclass
class Outcome:
    """What an agent invocation actually did."""

    ok: bool
    exit_code: int
    #: Whatever the agent produced, already redacted.
    output: str = ""
    #: Parsed structured result, when the invocation asked for one.
    data: dict = field(default_factory=dict)
    #: Set when the *tooling* failed rather than the work — a timeout, a
    #: missing binary, an auth expiry. The driver counts these separately and
    #: stops on a run of them, because retrying a broken reviewer forever is
    #: how a loop convinces itself the code is clean.
    infrastructure_failure: bool = False
    detail: str = ""
    #: The harness's own word for how the run ended — `subtype` in
    #: `claude -p --output-format json`: `success`, `error_max_turns`,
    #: `error_during_execution`. Empty when nothing readable was returned,
    #: which is itself an answer: an unexplained stop is not a known one.
    stop_reason: str = ""


def _git_in(cwd: Path, *args: str) -> tuple[int, str]:
    """Run git in a repository. Used to make and remove the review worktree."""
    done = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, stdin=subprocess.DEVNULL)
    return done.returncode, (done.stdout + done.stderr).strip()


def _run(argv: list[str], *, cwd: Path, timeout: int,
         env: dict | None = None) -> tuple[int, str, bool]:
    """Run a command with stdin closed. Returns (code, output, timed_out)."""
    try:
        done = subprocess.run(
            argv, cwd=str(cwd), stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=timeout,
            env={**os.environ, **(env or {})})
    except FileNotFoundError as missing:
        return 127, f"{argv[0]} is not installed: {missing}", False
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s", True
    return done.returncode, redact((done.stdout or "") + (done.stderr or "")), False


# ---------------------------------------------------------------- builder


def build(task: dict, *, cwd: Path, max_turns: int, timeout: int) -> Outcome:
    """Ask Claude to carry out one task, headless.

    It is given the task and the repository. **Not the roadmap**: an agent
    handed the whole roadmap optimises for the roadmap, and this loop exists to
    do one thing at a time and prove it.

    `--permission-mode acceptEdits` rather than bypassing permissions: the
    builder may edit and run, and the boundaries it must not cross are not
    enforced by a permission flag anyway — they are in the prompt and, where it
    matters, in what the driver refuses to do afterwards.
    """
    prompt = builder_prompt(task)
    code, out, timed_out = _run(
        ["claude", "-p", prompt, "--output-format", "json",
         "--permission-mode", "acceptEdits", "--max-turns", str(max_turns)],
        cwd=cwd, timeout=timeout)
    if timed_out or code == 127:
        return Outcome(ok=False, exit_code=code, output=out,
                       infrastructure_failure=True,
                       detail=f"the builder did not run: {out[:300]}")
    data: dict = {}
    for line in reversed(out.splitlines()):
        if line.strip().startswith("{"):
            try:
                data = json.loads(line)
                break
            except ValueError:
                continue
    # `is_error` is the agent's own report and the exit code is the process's.
    # Disagreement is treated as failure: a zero exit with `is_error` set is
    # exactly the shape of a harness that swallowed something.
    errored = bool(data.get("is_error")) or code != 0
    return Outcome(ok=not errored, exit_code=code, output=out[-4000:],
                   data=data, stop_reason=str(data.get("subtype") or ""),
                   detail="" if not errored else
                   f"builder reported an error (exit {code})"
                   + (f": {data['subtype']}" if data.get("subtype") else ""))


def builder_prompt(task: dict) -> str:
    """What the builder is told. One task, the boundaries, and nothing else."""
    return f"""Carry out exactly this task in the current repository.

TASK: {task['title']}

{task['brief']}

Rules for this run:
- Implement it fully. Do not write a plan and stop, and do not report progress
  you have not made — a later step checks the diff and the tests, not your
  summary.
- Add or update tests that would fail without your change.
- Run the relevant tests yourself before finishing.
- Do NOT commit. The loop commits, so that the reviewed diff is exactly the
  work of this task.
- Do NOT deploy, send anything to anybody, change DNS, create or use
  credentials, or take any irreversible external action.
- If the task turns out to need a human decision, a credential, physical
  access, or an irreversible action: change nothing, and say
  BLOCKED: <one line saying which boundary and why>.
Finish by stating what you changed in one or two sentences."""


def fix(task: dict, findings: list[dict], *, cwd: Path, max_turns: int,
        timeout: int) -> Outcome:
    """Ask Claude to answer a reviewer's findings.

    Fix or refute, and a refutation is a claim the reviewer sees again next
    round — the author does not get to dismiss a finding on their own
    authority, which is the failure mode that makes review theatre.
    """
    listed = "\n\n".join(
        f"[{f['severity']}] {f['file']}\n"
        f"  claim: {f['claim']}\n"
        f"  why it matters: {f['why_it_matters']}\n"
        f"  failure scenario: {f['failure_scenario']}"
        for f in findings)
    prompt = f"""An independent reviewer examined the diff you just produced and
raised the findings below. It did not see your report — only the code.

{listed}

For each one: fix it, or leave the code alone and write down why the finding is
wrong. Add a test for anything you fix. Do not commit.

A refutation is not a dismissal: the reviewer re-reads the code afterwards and
raises it again if it still stands."""
    code, out, timed_out = _run(
        ["claude", "-p", prompt, "--output-format", "json",
         "--permission-mode", "acceptEdits", "--max-turns", str(max_turns)],
        cwd=cwd, timeout=timeout)
    if timed_out or code == 127:
        return Outcome(ok=False, exit_code=code, output=out,
                       infrastructure_failure=True,
                       detail=f"the fixer did not run: {out[:300]}")
    return Outcome(ok=code == 0, exit_code=code, output=out[-4000:])


# --------------------------------------------------------------- reviewer


def reviewer_prompt() -> str:
    """The reviewer's instructions. Fixed, and takes no arguments.

    It cannot be given the task, the brief or the builder's output, because
    there is no parameter through which to pass them. A test asserts that.
    """
    return """Review this diff adversarially. You are the last check before it
reaches production, and its author believes it is correct.

Assume the author's tests pass and are insufficient. Look for what the tests do
not cover: a field read but never used, a condition that is true for the wrong
reason, a value that is correct in the case the test writes and wrong in the
case production holds, state that is not what the surrounding code assumes.

Report only defects you can name concretely, each with the input or state that
produces the wrong output. Do not report style, naming, or things you would
have done differently. If a change is correct, say so — a false finding costs
more than a missed one here, because it sends the author to rewrite working
code.

Return the structured result only."""


#: How `codex exec review` states a finding:
#:
#:     - [P1] Restore the budget comparison direction — /abs/path.py:3-3
#:       For normal nonnegative values, this now reports overspending as ...
#:
#: Parsed rather than schema-driven because **`codex exec review` ignores
#: `--output-schema`** — verified by running it: the flag is accepted, the
#: review is emitted in this format regardless, and `-o` receives the same
#: text. The purpose-built reviewer is worth more than the convenience of a
#: schema: pointed at a planted defect it named the reversed comparison at P1,
#: and `--base` makes the review unit a git range rather than a description of
#: one.
_FINDING = re.compile(
    r"^\s*-\s*\[(?P<severity>P[123])\]\s*(?P<claim>.+?)\s+[—-]\s+"
    r"(?P<file>\S+?):(?P<lines>[\d\-]+)\s*$")

#: P-levels to the severities the queue and the fixer speak in.
_SEVERITY = {"P1": "blocking", "P2": "major", "P3": "minor"}


#: Withheld from the reviewer at both commits.
#:
#: `.qevik/` is execution memory: `SESSION_LOG.md` narrates what the builder
#: did and `DECISION_QUEUE.md` carries earlier findings. Showing a reviewer the
#: author's account of a change is the one thing that stops it reviewing, and
#: it would arrive silently, as just another tracked file.
WITHHELD: tuple[str, ...] = (".qevik",)


def isolate(repo: Path, *, base_sha: str, into: Path) -> tuple[str, str]:
    """Build the repository the reviewer sees. Base, task diff, nothing else.

    Returns `(base_commit_in_the_new_repo, "")` or `("", why)`.

    Two commits, one branch, no remote, no earlier history, no other task's
    work, and no `.qevik` at either commit. The reviewer diffs the second
    against the first; there is no path from here to the builder's working
    tree, to an uncommitted file, or to anything the loop knows about itself.
    """
    into.mkdir(parents=True, exist_ok=True)
    signed = ("-c", "user.email=review@devloop", "-c", "user.name=devloop")
    started, why = _git_in(into, "init", "-q", "-b", "review")
    if started != 0:
        return "", why

    base_here = ""
    for label, sha in (("base", base_sha), ("task", "HEAD")):
        # `git archive` writes the tree at that commit and nothing about how it
        # came to be, so the new repository never learns the old one's history.
        bundle = into / "tree.tar"
        wrote, why = _git_in(repo, "archive", "--format=tar",
                             f"--output={bundle}", sha)
        if wrote != 0:
            return "", f"could not read {label}: {why}"
        for existing in into.iterdir():
            if existing.name in (".git", "tree.tar"):
                continue
            if existing.is_dir():
                shutil.rmtree(existing, ignore_errors=True)
            else:
                existing.unlink()
        unpacked = subprocess.run(["tar", "-xf", str(bundle)], cwd=str(into),
                                  capture_output=True, text=True)
        bundle.unlink(missing_ok=True)
        if unpacked.returncode != 0:
            return "", f"could not unpack {label}: {unpacked.stderr[:200]}"
        for withheld in WITHHELD:
            shutil.rmtree(into / withheld, ignore_errors=True)
        _git_in(into, "add", "-A")
        made, why = _git_in(into, *signed, "commit", "-q", "--allow-empty",
                            "-m", label)
        if made != 0:
            return "", f"could not commit {label}: {why}"
        if label == "base":
            base_here = _git_in(into, "rev-parse", "HEAD")[1]
    return base_here, ""


def parse_review(text: str, *, repo: Path) -> dict | None:
    """Turn one review message into findings. `None` when it cannot be read.

    Fails closed on purpose. A review whose shape is unrecognised has told us
    nothing, and returning `CLEAN` for it would be the exact failure this loop
    exists to prevent — shipping unreviewed code and reporting success.
    """
    if not text or not text.strip():
        return None
    summary = text.strip().splitlines()[0].strip()
    findings: list[dict] = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = _FINDING.match(line)
        if not match:
            continue
        body = []
        for following in lines[index + 1:]:
            if not following.strip() or _FINDING.match(following):
                break
            body.append(following.strip())
        path = match.group("file")
        try:
            path = str(Path(path).resolve().relative_to(repo.resolve()))
        except (ValueError, OSError):
            pass
        findings.append({
            "severity": _SEVERITY.get(match.group("severity"), "major"),
            "file": f"{path}:{match.group('lines')}",
            "claim": match.group("claim").strip(),
            # Both come from what the reviewer actually wrote. The summary is
            # its statement of consequence and the body is the case it made;
            # neither is composed here, because a field invented to satisfy a
            # schema is worse than an absent one.
            "why_it_matters": summary,
            "failure_scenario": " ".join(body) or summary,
        })
    if findings:
        return {"verdict": "DEFECTS_FOUND", "findings": findings}
    # No bullets. Whether that is clean is decided structurally, not by
    # matching phrases: `codex exec review` prints a "Review comment:" section
    # when it has something to say, so its absence is the reviewer stating it
    # found nothing.
    #
    # The first version listed the wordings it knew and failed closed on the
    # rest, which is the safe direction but wrong here — a real clean review
    # ("...without an evident regression") was rejected as unreadable and the
    # task was requeued. Failing closed on an unrecognised *shape* is right;
    # failing closed on an unrecognised *sentence* is a parser guessing at
    # prose.
    if re.search(r"(?im)^\s*review comments?\s*:", text):
        # It announced findings and none parsed. That is unreadable, and
        # reporting it clean is how unreviewed code ships.
        return None
    return {"verdict": "CLEAN", "findings": []}


def review(*, cwd: Path, base_sha: str, out_file: Path, timeout: int,
           effort: str = REVIEW_EFFORT) -> Outcome:
    """Have Codex review one immutable diff, read-only.

    `codex exec review --base <sha>` reviews `sha..HEAD` in the working
    repository, so the review unit is a git range rather than a description of
    one, and it cannot move under the reviewer.

    The invocation deliberately carries no information about who wrote the
    change or what they were trying to do — and here that is structural rather
    than disciplined: `--base` and a positional prompt are mutually exclusive,
    so there is no argument through which a builder's report could be passed
    even by mistake.
    """
    out_file.parent.mkdir(parents=True, exist_ok=True)

    # The reviewer is handed a repository built for it: **the base commit, the
    # task diff, and nothing else.**
    #
    # A `git worktree` was not enough, for a reason that matters more than
    # write access. It carries every tracked file — including
    # `.qevik/SESSION_LOG.md`, which is the builder's own narrative of what it
    # just did. A reviewer that can read that is no longer blind, and blindness
    # is the entire reason this reviewer finds anything. It also carries the
    # repository's whole history and every other task's branch.
    #
    # And the CLI flag is not a boundary: `codex exec review` has no
    # `--sandbox`, and `-c sandbox_mode="read-only"` was set while a real
    # review still wrote to the working tree. Isolation has to be a property of
    # what the reviewer is given, not of what it was asked to do.
    #
    # So: a fresh repository, two commits, one branch, no remote, no history
    # before the base, and no `.qevik` at either commit. Whatever the reviewer
    # writes is destroyed with it, and it can reach nothing that was not put
    # there on purpose.
    scratch = Path(tempfile.mkdtemp(prefix="devloop-review-"))
    tree = scratch / "review"
    try:
        prepared, why = isolate(cwd, base_sha=base_sha, into=tree)
        if not prepared:
            return Outcome(ok=False, exit_code=1, output=why,
                           infrastructure_failure=True,
                           detail=f"could not isolate the review: {why[:200]}")
        code, out, timed_out = _run(
            ["codex", "exec", "review", "--base", prepared, "--json",
             "-c", f"model_reasoning_effort={effort}"],
            cwd=tree, timeout=timeout)
    finally:
        # Nothing the reviewer did survives. The path is kept only so
        # `parse_review` can relativise the absolute paths it printed.
        shutil.rmtree(scratch, ignore_errors=True)
    if timed_out or code == 127:
        return Outcome(ok=False, exit_code=code, output=out,
                       infrastructure_failure=True,
                       detail=f"the reviewer did not run: {out[:300]}")

    message = ""
    for line in out.splitlines():
        if not line.strip().startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        item = event.get("item") or {}
        if item.get("type") == "agent_message" and item.get("text"):
            message = item["text"]
    if not message:
        # Exit zero with nothing to read is a broken reviewer, not a clean
        # review. Treating it as clean is how a loop ships unreviewed code all
        # night and reports success in the morning.
        return Outcome(ok=False, exit_code=code, output=out[-2000:],
                       infrastructure_failure=True,
                       detail="the reviewer produced no review message")

    out_file.write_text(message)
    parsed = parse_review(message, repo=cwd)
    if parsed is None:
        return Outcome(ok=False, exit_code=code, output=message[:2000],
                       infrastructure_failure=True,
                       detail="the review could not be read as findings or as "
                              "a clean verdict")
    return Outcome(ok=True, exit_code=code, output=message[:2000], data=parsed)


#: The one ending that says *the run was cut short*, rather than that
#: something went wrong inside it. `claude -p` reports `error_max_turns` when
#: the turn budget ran out, and that is the only stop under which a complete
#: change can plausibly be sitting in the tree — the builder is told to finish
#: and may have done so on its last turn.
#:
#: Everything else — `error_during_execution`, an unparseable result, a stop
#: with no `subtype` at all — is an *unexplained* stop. Nothing downstream can
#: recover the difference: the gates read git and pytest, so they establish
#: that the repository is consistent and never that the brief was carried out,
#: and the reviewer is deliberately blind to the brief. Treating those as
#: acceptable is how half-finished work reaches DONE and a deploy.
COMPLETION_LIKE_STOPS = frozenset({"error_max_turns"})


def stopped_short(outcome: Outcome) -> bool:
    """Whether a failed run ended in a way that may still hold finished work."""
    return not outcome.ok and outcome.stop_reason in COMPLETION_LIKE_STOPS


def blocking(findings: list[dict]) -> list[dict]:
    """Findings that must be answered before anything ships.

    `minor` is recorded and does not hold a task: a loop that blocks on every
    observation never finishes one, and the severity was the reviewer's own.
    """
    return [f for f in findings if f.get("severity") in ("blocking", "major")]


__all__ = ["Outcome", "REVIEW_EFFORT", "WITHHELD", "blocking", "build",
           "builder_prompt", "fix", "isolate", "parse_review", "review",
           "reviewer_prompt", "stopped_short"]
