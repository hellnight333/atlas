#!/usr/bin/env python3
"""The development loop. Neither agent drives it.

    driver.py status                 what the queue holds
    driver.py enqueue --title ... --brief ... --path ... [--path ...]
    driver.py declare-paths <task> --path ... [--path ...]   contract for a legacy row
    driver.py scope <task>           the scope checks a task was measured by
    driver.py inspect                ask production what is worth doing
    driver.py health                 reviewer negative control
    driver.py run --once             one task, then stop
    driver.py run --max-tasks 6      unattended, bounded

## Why a dumb driver

Both agents lose context, stop early, and write confident reports about work
they did not finish. So neither is allowed to hold the state machine. This
process owns it, verifies every claim against git, pytest, a deploy exit code
and a production probe, and treats the agents as stateless workers with bounded
turns. An agent that dies loses its task's lease and the work becomes runnable
again; it does not become lost.

**This is not a second Qevik orchestrator.** Qevik's mission engine runs
declared recipes through registered tools and refuses anything else, which is
exactly why it cannot host freeform development. This orchestrates development
agents and knows nothing about businesses, signals or outreach.

## The state machine

    QUEUED         only with an allowed-path contract; none → BLOCKED
      → BUILDING     Claude, bounded turns, no commit
      → GATING       diff non-empty, tests pass          (objective)
                     commit, then the committed range is
                     small enough to converge on, and
                     every changed path is inside the
                     contract                            (objective)
                     too large, or outside it → CONTESTED, unreviewed
      → REVIEWING    Codex on base..HEAD                 (read-only, blind)
          findings → FIXING → GATING → REVIEWING  (at most three rounds)
          three rounds and still contested → CONTESTED
      → DEPLOYING    where the task declares it          (objective)
      → VERIFYING    where the task declares it          (objective)
      → DONE

`BLOCKED` is not a failure. A task that reaches a credential, a decision, a
machine or an irreversible action is parked with its boundary written into
`.qevik/HUMAN_ACTIONS.md` or `.qevik/DECISION_QUEUE.md`, and the loop continues
with independent work.

## The scope contract

Every task carries the list of paths it may change. The driver compares the
committed diff against it — after the commit, so the record names an
immutable sha, and before the review, so no round is spent on work the task
was not allowed to do — and stores what it declared, what changed, what was
outside, and the verdict. Landing asks that record the way it asks the review
record: a head with no in-scope verdict does not merge. The builder is shown
the list, but the builder is not what enforces it; a diff outside the
contract is contested whatever the builder said about it.

The size gate is measured at the same point, for the same reason. A round's
work is not in `base..HEAD` until it is committed, so a size check that runs
earlier measures the *previous* round, and on round one measures nothing at
all. Both gates answer about the range that would land, or they answer about
the wrong thing.

## What stops it

Not "I could not think of anything". An empty queue runs the production
inspection and enqueues what real data supports; if that finds nothing, the
loop stops and says so with the evidence. The other stops are hard limits: a
run of infrastructure failures, a reviewer that failed its own negative
control, a task budget, or a signal.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import stat
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from devloop import agents, boundary, gates, projection  # noqa: E402
from devloop.queue import Queue, State, allowed_paths, redact  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
LOG = REPO / ".qevik" / "devloop" / "driver.log"


@dataclass(frozen=True)
class Limits:
    """Hard bounds. Every one of them has a failure it exists to stop."""

    #: One task may not run for ever. A build that has not finished in this
    #: long has stopped making progress.
    #: Both proving runs died here rather than on anything conceptual, so the
    #: bound is set from what the work actually took: a real task ran three
    #: review rounds and was still going at 3600s.
    task_runtime_s: int = 9000
    #: A builder given unbounded turns explores instead of finishing — but 60
    #: was under what a real task needs, and every run ended `error_max_turns`
    #: with the work incomplete.
    claude_turns: int = 220
    build_timeout_s: int = 3600
    review_timeout_s: int = 1200
    #: Requirement, and a real bound: after three rounds the disagreement is
    #: not going to resolve itself, and a person should read it.
    review_rounds: int = 3
    #: A run of tooling failures means the tooling is broken. Continuing past
    #: it produces "clean review" results that mean nothing.
    consecutive_infra_failures: int = 3
    #: How much autonomous work one invocation may do.
    max_tasks: int = 1
    #: How often to prove the reviewer still detects a planted defect.
    health_every_tasks: int = 5


class Stopped(Exception):
    """A signal arrived. Release the lease and exit cleanly."""


def log(message: str, **fields) -> None:
    """One line per state transition, redacted, to stdout and to the file."""
    entry = {"at": datetime.now(UTC).isoformat(), "message": message, **fields}
    line = json.dumps({k: redact(v) if isinstance(v, str) else v
                       for k, v in entry.items()})
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as handle:
        handle.write(line + "\n")
    print(f"  {message}" + (f"  {fields}" if fields else ""), flush=True)


def _git(*args: str, cwd: Path = REPO) -> tuple[int, str]:
    done = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, stdin=subprocess.DEVNULL)
    return done.returncode, (done.stdout + done.stderr).strip()


def _git_raw(*args: str, cwd: Path = REPO) -> tuple[int, str]:
    """`_git` without the strip, for output whose first column is a space.

    `git status --porcelain` prints two status characters then a space, and
    `_git`'s strip removes the leading space of the **first line only** — the
    bug documented on `_touched`, which cost three runs there. Status is parsed
    by column below, so it is read with the columns intact.
    """
    done = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, stdin=subprocess.DEVNULL)
    return done.returncode, done.stdout + done.stderr


def _porcelain(text: str) -> list[tuple[str, str]]:
    """`(XY, path)` for each entry of `git status --porcelain` output."""
    entries = []
    for line in text.splitlines():
        if len(line) > 3 and line[2] == " ":
            entries.append((line[:2], line[3:]))
    return entries


def _tree_entry(text: str) -> tuple[str, str]:
    """`(mode, blob)` for a one-path `git ls-tree`, `("", "")` for no entry.

    A line is `<mode> SP <type> SP <sha> TAB <path>`; the path is split off
    first so a quoted or space-bearing name cannot shift the columns. Anything
    that is not a plain blob — a submodule gitlink, a subtree — reads as absent,
    which is the conservative answer: the caller then has to prove the path is
    gone from the worktree, and a submodule directory is not.
    """
    lines = text.splitlines()
    left = lines[0].split("\t", 1)[0].split() if lines else []
    return (left[0], left[2]) if len(left) == 3 and left[1] == "blob" else ("", "")


def _worktree_mode(path: Path) -> str:
    """The git tree mode a worktree path would be recorded with.

    Git stores one bit of permission, from the owner's execute bit, and it is
    tracked: a `chmod +x` with no content change is a real edit that shows up in
    `git status` and survives a commit. `""` for anything git would not record
    as a file here — absent, a directory, a device.
    """
    try:
        st = path.lstat()
    except OSError:
        return ""
    if stat.S_ISLNK(st.st_mode):
        return "120000"
    if not stat.S_ISREG(st.st_mode):
        return ""
    return "100755" if st.st_mode & stat.S_IXUSR else "100644"


def head_sha(cwd: Path = REPO) -> str:
    return _git("rev-parse", "HEAD", cwd=cwd)[1]


# ------------------------------------------------------------------ one task


class Driver:
    def __init__(self, queue: Queue, limits: Limits, *, repo: Path = REPO):
        self.q = queue
        self.limits = limits
        self.repo = repo
        self.owner = f"driver-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self.infra_failures = 0
        self.run_id = ""
        self._stop = False
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._catch)

    def _catch(self, *_: object) -> None:
        # Clean shutdown: finish the phase, release the lease, exit. Killing
        # mid-write is what the lease exists to survive, but exiting tidily
        # means the next run starts immediately rather than after a timeout.
        self._stop = True
        print("\n  stop requested — finishing the current phase", flush=True)

    def _check_stop(self) -> None:
        if self._stop:
            raise Stopped()

    # -- the phases ---------------------------------------------------

    def run_task(self, task: dict) -> str:
        """One task through the machine. Returns its terminal state."""
        started = time.monotonic()
        ident = task["id"]
        # No contract, no run. The scope gate compares the diff against the
        # task's allowed paths, and a task with none would either pass
        # vacuously or be judged against a list the driver invented; both are
        # the unenforced scope this gate replaced. A person declares one and
        # requeues — `devloop declare-paths` — which is a decision about where
        # the work is allowed to go, and not the driver's to make.
        allowed = allowed_paths(task)
        if not allowed:
            self.q.move(ident, State.BLOCKED,
                        reason="no allowed-path contract: the task predates "
                               "the contract or was enqueued without one; "
                               "declare the paths it may change and requeue")
            log("BLOCKED", task=ident, why="no allowed-path contract")
            return State.BLOCKED
        # A dirty tree would be committed under this task's name and reviewed
        # as its work. Refused rather than adopted: the review unit has to be
        # the task's diff and nothing else.
        readable, dirty = _git("status", "--porcelain", cwd=self.repo)
        # Only when starting fresh. A resumed task's uncommitted work is its
        # own — left behind when a round was interrupted — and refusing it
        # would strand every task that stopped mid-edit, which is precisely the
        # case the branch and the lease exist to recover.
        resuming = _git("rev-parse", "--verify", "--quiet",
                        f"devloop/{ident}", cwd=self.repo)[0] == 0
        # Only when git actually answered. An unreadable status has not shown
        # the tree is dirty, and the `changed` gate already reports a repo it
        # cannot read as unmeasured rather than as a pass.
        if readable == 0 and dirty and not resuming:
            self.q.move(ident, State.QUEUED,
                        reason="the working tree was not clean when the task "
                               "was claimed; the review unit must contain only "
                               "this task's work")
            log("REFUSED", task=ident, why="working tree not clean",
                files=len(dirty.splitlines()))
            return State.FAILED
        # One branch per task, and `main` only when the reviewer is clean.
        #
        # The second proving run showed why. Each round commits, because the
        # review unit has to be an immutable range — and committing to `main`
        # put rounds one and two there, including a round the reviewer then
        # raised three blocking findings against. Work under review is not work
        # that has passed, and `main` should not hold it.
        branch = f"devloop/{ident}"
        # Reuse the branch when it exists. `-B` resets it to HEAD, which would
        # discard the work of a task that was parked, requeued or interrupted —
        # the exact case a resumable queue exists to serve.
        if _git("rev-parse", "--verify", "--quiet", branch, cwd=self.repo)[0] == 0:
            _git("checkout", "-q", branch, cwd=self.repo)
            # Bring `main` in first. Without it the branch is behind, and
            # `base..HEAD` presents every commit `main` gained while the task
            # was parked as though this task had *deleted* it — the reviewer
            # would be handed a diff that reverses unrelated work.
            merged, out = _git("merge", "-q", "--no-edit", "main", cwd=self.repo)
            if merged != 0:
                _git("merge", "--abort", cwd=self.repo)
                _git("checkout", "-q", "main", cwd=self.repo)
                self.q.move(ident, State.CONTESTED,
                            reason=f"the parked branch will not take main: "
                                   f"{out[:300]}")
                log("CONTESTED", task=ident, why="branch conflicts with main")
                return State.CONTESTED
            log("RESUMING", task=ident, branch=branch,
                at=head_sha(self.repo)[:12])
        else:
            _git("checkout", "-q", "-b", branch, cwd=self.repo)

        # Where this task's work begins, asked of git rather than remembered.
        # For a fresh branch that is `main`'s tip; for a resumed one it is the
        # point the branch and `main` share, so **every round the task has ever
        # produced is in the review unit** — including rounds interrupted
        # before anything reviewed them.
        base = _git("merge-base", "main", "HEAD", cwd=self.repo)[1] or head_sha(self.repo)
        self.q.move(ident, State.BUILDING, reason=f"base {base[:12]} on {branch}",
                    base_sha=base)
        log("BUILDING", task=ident, title=task["title"][:60], base=base[:12])

        built = agents.build(task, cwd=self.repo,
                             max_turns=self.limits.claude_turns,
                             timeout=self.limits.build_timeout_s)
        if built.infrastructure_failure:
            return self._infra(ident, built.detail)
        # A builder that hit a human boundary says so and changes nothing.
        stopped_at = _boundary_in(built.output)
        if stopped_at:
            # Parked, not failed. A request is raised in the one inbox a person
            # reads, the task keeps everything needed to resume, and the loop
            # goes on to independent work rather than stopping the project.
            request_id = boundary.raise_for(task, stopped_at)
            marker = projection.park_boundary(self.repo, task, stopped_at)
            self.q.park(ident, request_id=request_id or marker,
                        stage=State.BUILDING, sha=base, reason=stopped_at,
                        run_id=self.run_id)
            log("WAITING_FOR_HUMAN", task=ident, request=request_id or marker,
                boundary=stopped_at[:120])
            return State.WAITING_FOR_HUMAN
        if not built.ok:
            if not agents.stopped_short(built):
                # An unexplained stop is a failure, and stays one. Nothing
                # after this point can tell finished work from half-finished:
                # the gates read git and pytest, so they establish that the
                # repository is consistent and never that *this task* was
                # carried out, and the reviewer is blind to the brief by
                # design. Falling through on every non-infrastructure error
                # would let a builder that died mid-edit reach DONE and deploy.
                self.q.move(ident, State.FAILED,
                            reason=built.detail or "build failed")
                log("FAILED", task=ident, why=built.detail[:120])
                return State.FAILED
            # The one exception, and it is a known ending rather than a guess:
            # the builder ran out of turns. It is told to finish the work and
            # may have done so on its last one, so discarding the tree because
            # the process ended untidily throws away exactly what the gates
            # exist to judge. The gates still decide; they are simply allowed
            # to look.
            log("BUILDER_STOPPED", task=ident, why=built.detail[:120],
                stop_reason=built.stop_reason,
                note="turn limit reached — falling through to the gates")

        self.q.renew(ident)
        for round_no in range(1, self.limits.review_rounds + 1):
            self._check_stop()
            if time.monotonic() - started > self.limits.task_runtime_s:
                self.q.move(ident, State.FAILED,
                            reason=f"exceeded {self.limits.task_runtime_s}s")
                log("FAILED", task=ident, why="task runtime limit")
                return State.FAILED

            # -- objective gate, before anybody is asked an opinion --------
            self.q.move(ident, State.GATING, reason=f"round {round_no}")
            diff = gates.changed(cwd=self.repo)
            if not diff.passed:
                # What the builder said, kept with the failure. Without it
                # "nothing changed" is undiagnosable: a refusal, a crash, a
                # boundary it did not phrase as one, and an agent that simply
                # did nothing all look identical afterwards.
                said = " ".join((built.output or "").split())[-600:]
                self.q.move(ident, State.FAILED,
                            reason=f"{diff.detail} | builder said: {said}")
                log("FAILED", task=ident, why="nothing changed",
                    builder_said=said[-300:])
                return State.FAILED
            # Narrowed to what the task touched. Measured: the full suite is
            # about eleven minutes a round against a two-minute review, so
            # running all of it every round spent roughly a third of each cycle
            # re-proving code the task never went near. `_ship` still runs the
            # whole suite before anything deploys, which is where that
            # guarantee belongs — this narrows the loop, not the evidence.
            suite = gates.tests(cwd=self.repo,
                                selector=task.get("test_selector")
                                or self._selector())
            log("GATING", task=ident, round=round_no,
                gates=gates.summarise([diff, suite]))
            if suite.unmeasured:
                return self._infra(ident, f"tests unmeasured: {suite.detail}")
            if not suite.passed:
                if round_no >= self.limits.review_rounds:
                    self.q.move(ident, State.CONTESTED,
                                reason=f"tests still failing: {suite.detail}")
                    return State.CONTESTED
                fixed = agents.fix(task, [{
                    "severity": "blocking", "file": "(test suite)",
                    "claim": "the tests do not pass",
                    "why_it_matters": "the change is not correct yet",
                    "failure_scenario": suite.detail}],
                    cwd=self.repo, max_turns=self.limits.claude_turns,
                    timeout=self.limits.build_timeout_s)
                if fixed.infrastructure_failure:
                    return self._infra(ident, fixed.detail)
                continue

            # -- the immutable review unit --------------------------------
            # Committed *before* review so the diff cannot move under the
            # reviewer, and so a finding names a sha somebody can check out.
            self._commit(task, round_no)
            sha = head_sha(self.repo)

            # Too large to finish, before a reviewer spends rounds proving it —
            # and measured on the committed range, for the same reason the
            # scope gate below is.
            #
            # It ran before the commit, so `base..HEAD` held every round
            # *except* the one just written: the gate was one round stale, and
            # on round one it compared `base` with itself and could not fail at
            # all. Measured on t-7f9d5d633396, whose rounds saw 0, then 715,
            # then 788 non-test lines while the diff that actually landed was
            # 812 — past the limit, and never measured by anything.
            bounded = gates.size(cwd=self.repo, base_sha=base)
            if bounded.unmeasured:
                # A gate that measured nothing has established nothing — the
                # same refusal `tests` and `scope` make. It is also the guard
                # that keeps the mistake above from ever being silent again: an
                # empty range is unmeasured, never "small enough".
                return self._infra(ident, f"size unmeasured: {bounded.detail}")
            if not bounded.passed:
                self.q.move(ident, State.CONTESTED,
                            reason=f"oversized: {bounded.detail}",
                            head_sha=sha)
                projection.park_oversized(self.repo, task, bounded.detail)
                log("OVERSIZED", task=ident, detail=bounded.detail[:160])
                _git("checkout", "-q", "main", cwd=self.repo)
                return State.CONTESTED

            # -- the contract, measured on the unit that would land --------
            # After the commit and before the review, on `base..HEAD`: the
            # same range the reviewer is shown and the squash would take.
            # Recorded against the sha whatever the verdict, so the landing
            # gate can ask whether *this* head was measured — the same
            # question it asks of the review. A diff outside the contract is
            # contested at once; no round is spent reviewing work the task was
            # not allowed to do, and no finding could make it landable.
            kept = gates.scope(cwd=self.repo, base_sha=base, allowed=allowed)
            if kept.unmeasured:
                return self._infra(ident, f"scope unmeasured: {kept.detail}")
            self.q.record_scope(ident, round=round_no, sha=sha,
                                declared=kept.evidence["declared"],
                                changed=kept.evidence["changed"],
                                undeclared=kept.evidence["undeclared"])
            if not kept.passed:
                self.q.move(ident, State.CONTESTED,
                            reason=f"out of scope: {kept.detail}",
                            head_sha=sha, review_rounds=round_no)
                projection.park_out_of_scope(self.repo, task, kept.evidence)
                log("OUT_OF_SCOPE", task=ident, round=round_no,
                    undeclared=kept.evidence["undeclared"][:8])
                _git("checkout", "-q", "main", cwd=self.repo)
                return State.CONTESTED
            log("SCOPE", task=ident, round=round_no, detail=kept.detail[:160])

            self.q.move(ident, State.REVIEWING,
                        reason=f"round {round_no} at {sha[:12]}",
                        head_sha=sha, review_rounds=round_no)
            log("REVIEWING", task=ident, round=round_no, unit=f"{base[:12]}..{sha[:12]}")

            out = self.repo / ".qevik" / "devloop" / f"review-{ident}-{round_no}.json"
            reviewed = agents.review(cwd=self.repo, base_sha=base,
                                     out_file=out,
                                     timeout=self.limits.review_timeout_s)
            if reviewed.infrastructure_failure:
                return self._infra(ident, reviewed.detail)
            untouched = gates.clean_tree(cwd=self.repo)
            if not untouched.passed:
                return self._infra(ident, untouched.detail)

            found = reviewed.data.get("findings") or []
            # The review itself, then its findings. A clean review records no
            # findings, so without the first the landing gate cannot tell "the
            # reviewer looked and found nothing" from "nobody looked".
            self.q.record_review(ident, round=round_no, sha=sha,
                                 verdict=str(reviewed.data.get("verdict", "")),
                                 findings=len(found))
            self.q.record_findings(ident, round=round_no, sha=sha,
                                   findings=found)
            must = agents.blocking(found)
            log("REVIEWED", task=ident, round=round_no,
                verdict=reviewed.data.get("verdict"), findings=len(found),
                blocking=len(must))
            if not must:
                return self._ship(task, started)

            if round_no == self.limits.review_rounds:
                # The branch stays. A person reading a contested task needs the
                # rounds, and `main` never saw them.
                _git("checkout", "-q", "main", cwd=self.repo)
                self.q.move(ident, State.CONTESTED,
                            reason=f"{len(must)} finding(s) after "
                                   f"{round_no} rounds")
                projection.park_contested(self.repo, task,
                                          self.q.findings(ident))
                log("CONTESTED", task=ident, findings=len(must))
                return State.CONTESTED

            self.q.move(ident, State.FIXING, reason=f"{len(must)} finding(s)")
            log("FIXING", task=ident, round=round_no, findings=len(must))
            fixed = agents.fix(task, must, cwd=self.repo,
                               max_turns=self.limits.claude_turns,
                               timeout=self.limits.build_timeout_s)
            if fixed.infrastructure_failure:
                return self._infra(ident, fixed.detail)
            self.q.renew(ident)

        self.q.move(ident, State.CONTESTED, reason="rounds exhausted")
        return State.CONTESTED

    def _ship(self, task: dict, started: float) -> str:
        """Review is clean. Land it, run the remaining gates, then finish."""
        ident = task["id"]
        needed = gates.required(task)
        # Only now does it reach `main` — as one commit, so the history says
        # "this task, reviewed clean" rather than replaying the argument the
        # builder and the reviewer had on the way there.
        branch = f"devloop/{ident}"
        # The gate that makes main protection structural rather than a promise.
        #
        # `_ship` is only reachable from a clean review, but "only reachable"
        # is a property of today's control flow and a future edit could add a
        # second caller. This asks the record instead: the newest review round
        # for this task must exist and must have left no blocking finding.
        # A task with no recorded review has not been reviewed, and that is
        # refused rather than assumed.
        #
        # The same question is asked of the scope record, for the same reason:
        # the head about to land must have been measured against the task's
        # allowed paths and found inside them. A missing record is a refusal,
        # so no route to this line — today's or a later one — can land a diff
        # the contract was never compared with.
        if not self.q.review_was_clean(ident):
            self.q.move(ident, State.CONTESTED,
                        reason="refused to land: the recorded review for this "
                               "task is missing or left blocking findings")
            log("REFUSED_TO_LAND", task=ident)
            _git("checkout", "-q", "main", cwd=self.repo)
            return State.CONTESTED
        if not self.q.scope_was_kept(ident):
            self.q.move(ident, State.CONTESTED,
                        reason="refused to land: no scope check found this "
                               "head inside the task's allowed-path contract")
            log("REFUSED_TO_LAND", task=ident, why="scope not kept")
            _git("checkout", "-q", "main", cwd=self.repo)
            return State.CONTESTED
        # The exit code of the checkout, which used to be ignored. A checkout
        # that failed leaves the branch tip as HEAD, and everything below —
        # including the sha this task would deploy — would then be about the
        # unlanded branch rather than about `main`.
        moved, out = _git("checkout", "-q", "main", cwd=self.repo)
        if moved != 0:
            self.q.move(ident, State.CONTESTED,
                        reason=f"refused to land: could not check out main: "
                               f"{out[:300]}")
            log("REFUSED_TO_LAND", task=ident, why="checkout main failed")
            return State.CONTESTED
        # A clean `main` before the squash is what makes "the task's own squash
        # state" a well-defined set of paths. It is not a lock, and it is not
        # claimed as one: it is the baseline the settlement below compares
        # against. Anything already here belongs to somebody else and this task
        # will not commit on top of it.
        readable, dirty = _git("status", "--porcelain", cwd=self.repo)
        if readable != 0 or dirty:
            self.q.move(ident, State.CONTESTED,
                        reason=f"refused to land: main was not clean before the "
                               f"squash: {dirty[:300]}")
            log("REFUSED_TO_LAND", task=ident, why="main not clean")
            return State.CONTESTED
        # `main`'s tip before the squash: the state a proven cleanup restores.
        landing_base = head_sha(self.repo)
        merged, out = _git("merge", "--squash", branch, cwd=self.repo)
        if merged != 0:
            return self._settle_failed_landing(ident, branch, landing_base,
                                               output=out)
        committed, out = _git(
            "commit", "-q", "-m",
            f"{task['title']}\n\n{task['brief'][:900]}\n\n"
            f"devloop task {ident}; reviewer clean after "
            f"{task.get('review_rounds') or 1} round(s).\n\n"
            "Co-Authored-By: Claude Opus 5 (1M context) "
            "<noreply@anthropic.com>", cwd=self.repo)
        if committed != 0:
            return self._settle_failed_landing(ident, branch, landing_base,
                                               output=out)
        on = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=self.repo)[1]
        if on != "main":
            self.q.move(ident, State.CONTESTED,
                        reason=f"refused to land: HEAD is on {on}, not main, so "
                               f"the commit that was just made is not what "
                               f"would deploy")
            log("REFUSED_TO_LAND", task=ident, why=f"HEAD on {on}")
            return State.CONTESTED
        # S — the immutable commit that passed gates and review, and the only
        # thing that may be deployed. Captured once, here, and carried through
        # every gate below rather than re-read from a tree that can move.
        shipping = head_sha(self.repo)
        _git("branch", "-D", branch, cwd=self.repo)
        log("LANDED", task=ident, sha=shipping)

        if "deployed" in needed:
            # The whole suite before anything leaves this machine. A narrowed
            # run is a real gate for a narrow change and is not enough to
            # deploy on.
            self.q.renew(ident)
            drift = self._tree_is(shipping)
            if drift:
                return self._refuse_to_deploy(ident, drift)
            whole = gates.tests(cwd=self.repo)
            # Asked immediately, before the suite's own verdict is read: a
            # suite that ran against something other than S has not measured S,
            # whatever it concluded.
            drift = self._tree_is(shipping)
            if drift:
                return self._refuse_to_deploy(ident, drift)
            if whole.unmeasured:
                return self._infra(ident, f"full suite unmeasured: {whole.detail}")
            if not whole.passed:
                self.q.move(ident, State.CONTESTED,
                            reason=f"full suite fails: {whole.detail}")
                return State.CONTESTED
            self.q.move(ident, State.DEPLOYING,
                        reason=f"deploying {shipping}; {whole.detail}")
            log("DEPLOYING", task=ident, sha=shipping)
            self.q.renew(ident)
            drift = self._tree_is(shipping)
            if drift:
                return self._refuse_to_deploy(ident, drift)
            shipped = gates.deployed(cwd=self.repo, sha=shipping)
            if shipped.unmeasured:
                return self._blocked_after_landing(ident, shipping, "the deploy",
                                                   shipped.detail)
            if not shipped.passed:
                self.q.move(ident, State.FAILED, reason=shipped.detail)
                log("FAILED", task=ident, why="deploy failed")
                return State.FAILED
            # What the script exited is not what the host holds. The marker is
            # written only when the content is installed and verified on disk,
            # so it is read back before production verification is allowed to
            # say anything about S.
            live = gates.provenance(sha=shipping)
            if live.unmeasured:
                return self._blocked_after_landing(ident, shipping,
                                                   "the host's provenance",
                                                   live.detail)
            if not live.passed:
                self.q.move(ident, State.FAILED,
                            reason=f"deployed but the host's provenance does not "
                                   f"say {shipping}: {live.detail}")
                log("FAILED", task=ident, why="provenance disagrees")
                return State.FAILED
            log("PROVENANCE", task=ident, sha=shipping, state="installed")

        if "in_production" in needed:
            probe = (json.loads(task.get("evidence") or "{}")
                     .get("production_probe", ""))
            if not probe:
                # Declared but not supplied: the task asked to be verified in
                # production and gave nothing to verify with. That is a defect
                # in the task, not a pass.
                self.q.move(ident, State.CONTESTED,
                            reason="production verification required and no "
                                   "probe was supplied")
                return State.CONTESTED
            self.q.move(ident, State.VERIFYING)
            log("VERIFYING", task=ident)
            proved = gates.in_production(cwd=self.repo, probe=probe)
            if proved.unmeasured:
                # BLOCKED, not requeued, for the same reason as the two gates
                # above: this is after the landing, the branch is gone, and
                # `_infra` would send the task back to QUEUED to be rebuilt
                # from scratch on a new branch over work that is already on
                # `main`.
                return self._blocked_after_landing(ident, shipping,
                                                   "production verification",
                                                   proved.detail)
            if "deployed" in needed:
                # The probe is bracketed the way the suite is, and for the same
                # reason. The marker was read *before* the probe started, so on
                # its own it proves the host held S at that moment and nothing
                # about what answered the probe: a deploy or a rollback landing
                # in the window would have the probe measure other bytes, and
                # its verdict — passing or failing — would then be recorded
                # against S. So the marker is read again, before the verdict is
                # read, and must still name S installed.
                #
                # Only when this task deployed. A task that requires production
                # verification without a deploy never established provenance
                # for S, and the marker names whatever the host was already
                # holding; there is nothing to bracket and its answer would be
                # a refusal for an unrelated reason.
                still = gates.provenance(sha=shipping)
                if still.unmeasured:
                    return self._blocked_after_landing(
                        ident, shipping, "the host's provenance after the probe",
                        still.detail)
                if not still.passed:
                    return self._blocked_after_landing(
                        ident, shipping, "production verification",
                        f"the probe ran but the host no longer holds "
                        f"{shipping}: {still.detail}")
                log("PROVENANCE", task=ident, sha=shipping, state="probed")
            if not proved.passed:
                self.q.move(ident, State.FAILED, reason=proved.detail)
                log("FAILED", task=ident, why="production did not agree")
                return State.FAILED

        # The sha lives in the transition record, not in `tasks.head_sha` —
        # that column is the key the review and scope records are looked up by,
        # and overwriting it would make the landed commit look unreviewed.
        landed = (f"gates: {', '.join(needed)}; deployed {shipping}; "
                  f"provenance installed" if "deployed" in needed
                  else f"gates: {', '.join(needed)}")
        self.q.move(ident, State.DONE, reason=landed,
                    detail=f"completed in {int(time.monotonic() - started)}s")
        log("DONE", task=ident, seconds=int(time.monotonic() - started))
        return State.DONE

    def _settle_failed_landing(self, ident: str, branch: str, base: str, *,
                               output: str = "") -> str:
        """The squash merge or the squash commit failed. Settle `main` — or
        preserve it and stop.

        Governed by **DQ-013** (owner, 2026-09-02), quoted because the diff is
        reviewed without the brief:

          (1) The DevLoop is a single-driver, serial executor. Do not introduce
              a repository lock to defend against a hypothetical second driver;
              a lock is outside the execution model and does not protect
              against a human edit anyway.
          (2) The shipping path never automatically runs `git reset --hard` —
              or any equivalent destructive reset (`checkout -- .`, `clean -f`,
              `restore --worktree` over paths it has not proven) — against
              `main` as recovery from a failed squash/commit.
          (3) Preservation of unknown work takes priority over automatic loop
              liveness. If, after a failed squash or commit, the repository
              state cannot be PROVEN to contain only DevLoop-generated squash
              state, nothing is destroyed: preserve the state, move the task to
              BLOCKED, and emit explicit evidence of what remains and why a
              person is required.
          (4) A non-destructive cleanup proven safe and limited strictly to
              DevLoop-generated squash state may be used; otherwise BLOCKED is
              the correct terminal outcome.

        **The proof is content-based, not time-based**, and that is what makes
        it safe without a lock. A `status` check taken before the squash proves
        nothing about the tree afterwards — an edit landing in the window
        between the two would be destroyed by a cleanup that trusted it. So
        nothing here trusts a moment: every path that would be touched is
        compared with what the task branch holds *now* — content and mode both,
        since a `chmod` is tracked work a blob comparison cannot see. An edit
        either touches a path outside the squash set — not provable, BLOCKED —
        or moves a squash path's content or mode away from the branch's — not
        provable, BLOCKED — or leaves the file identical to what the branch
        holds, in which case restoring it loses nothing.

        **The remaining window, stated rather than papered over.** Each path is
        re-proved immediately before it is written, not once for all paths up
        front, so an edit arriving *during* the cleanup is caught and the
        cleanup stops where it stands (BLOCKED, saying how far it had got)
        rather than being overwritten by a proof that has gone stale behind it.
        What is left is the gap between a path's last check and its own write.
        Closing that needs exclusive access to the working tree, which is the
        repository lock DQ-013 §1 rules out — and which would not bind an
        operator's editor in any case, since a lock only binds processes that
        agree to take it. The narrowing is real; the claim is not that the gap
        is zero.

        The branch is never deleted on this path: it holds the reviewed work,
        and it is the only place that still does.
        """
        proof = ""                       # the first thing that failed to prove
        code, listed = _git("diff", "--name-only", "--no-renames",
                            f"{base}..{branch}", cwd=self.repo)
        squashed = [line.strip() for line in listed.splitlines() if line.strip()]
        if code != 0:
            proof = f"the squash set could not be read from git: {listed[:160]}"

        # A moved HEAD is not provable: `base` is no longer what a restore
        # would restore to.
        if not proof:
            at = head_sha(self.repo)
            if at != base:
                proof = f"HEAD is at {at[:12]}, not {base[:12]}"

        # Renames are switched off so this list is drawn the same way the
        # squash set is: a rename is a delete and an add, and both must prove.
        seen, status = _git_raw("status", "--porcelain", "--untracked-files=all",
                                "--no-renames", cwd=self.repo)
        if not proof and seen != 0:
            proof = f"the working tree could not be read: {status.strip()[:160]}"
        if not proof:
            inside = set(squashed)
            for mark, path in _porcelain(status):
                if "U" in mark or mark in ("AA", "DD"):
                    proof = f"{path}: conflicted"
                    break
                if path not in inside:
                    proof = f"{path}: outside the squash"
                    break

        # Every path the cleanup would touch, against what the branch holds.
        modes = _git("config", "--get", "core.fileMode",
                     cwd=self.repo)[1].strip().lower() != "false"
        if not proof:
            for path in squashed:
                proof = self._not_the_branchs(path, branch, modes=modes)
                if proof:
                    break

        restored = 0
        if not proof:
            # Proven, so the cleanup is allowed — and it is limited to the
            # squash set, path by path, from `base`'s own content. No
            # `reset --hard`, no `checkout -- .`, no `clean`: those act on
            # everything, including whatever nobody here has proved anything
            # about.
            for path in squashed:
                # Re-proved here, immediately before the write, and not left to
                # the pass above: that pass finishes before the first path is
                # touched, so by the time the loop reaches path N its proof is
                # as old as every restore that came before it. Anything that
                # changes during the cleanup's own run is caught rather than
                # overwritten, and the cleanup stops where it is.
                proof = self._not_the_branchs(path, branch, modes=modes)
                if proof:
                    proof += " (it changed while the cleanup was running)"
                    break
                if _git("rev-parse", "--verify", "--quiet", f"{base}:{path}",
                        cwd=self.repo)[0] == 0:
                    _git("checkout", base, "--", path, cwd=self.repo)
                else:
                    _git("rm", "-q", "--cached", "--", path, cwd=self.repo)
                    try:
                        os.remove(self.repo / path)
                    except OSError:
                        pass
                restored += 1
            seen, status = _git_raw("status", "--porcelain",
                                    "--untracked-files=all", "--no-renames",
                                    cwd=self.repo)
            if not proof and seen == 0 and not status.strip():
                self.q.move(ident, State.CONTESTED,
                            reason=f"refused to land: the squash would not "
                                   f"commit: {output[:300]}; main restored to "
                                   f"{base} from the branch's own content "
                                   f"({len(squashed)} path(s))")
                log("REFUSED_TO_LAND", task=ident, why="commit failed")
                return State.CONTESTED
            proof = proof or "the cleanup did not settle the tree"

        # Not provable, or the cleanup stopped part-way, or it left something
        # behind. Nothing is discarded: what is here may be somebody's only copy.
        remaining = status.strip()
        head = _git("rev-parse", branch, cwd=self.repo)[1]
        part = (f"; the cleanup had already restored the first {restored} of "
                f"{len(squashed)} path(s) from {base} before it stopped"
                if restored else "")
        self.q.move(ident, State.BLOCKED,
                    reason=f"landing failed and main is not provably only the "
                           f"squash: {proof}{part}; remaining: {remaining[:600]}; "
                           f"the task branch {branch} holds the reviewed work at "
                           f"{head}; a person must inspect main (expected tip "
                           f"{base}), keep or discard the remaining changes by "
                           f"hand, and re-enqueue or supersede this task")
        log("BLOCKED", task=ident, why="failed landing preserved on main",
            remaining=len(_porcelain(status)))
        return State.BLOCKED

    def _not_the_branchs(self, path: str, branch: str, *, modes: bool) -> str:
        """Why `path` is not, *right now*, exactly what `branch` holds — empty
        when it is. One line, naming the path, for the BLOCKED reason.

        "Exactly" is content **and** mode. Git records one permission bit, from
        the owner's execute bit, and it is tracked work: `chmod +x` with no edit
        to a byte is a change `git status` reports, a commit keeps, and
        `git checkout <base> -- <path>` silently reverts. A proof that compared
        blobs alone would accept such a path — the blob is unchanged, that being
        the whole point — and the restore would then discard the one thing that
        had actually changed. So the branch's tree mode is compared against both
        the index and the file on disk; the index alone would not do it, because
        a bare `chmod` never reaches the index.

        `modes` is false only where git itself is configured not to trust the
        filesystem's permission bits (`core.fileMode=false`), where a `chmod` is
        not an edit git would have kept either.
        """
        want, blob = _tree_entry(_git("ls-tree", branch, "--", path,
                                      cwd=self.repo)[1])
        on_disk = self.repo / path
        staged = _git("ls-files", "-s", "--", path, cwd=self.repo)[1].split()
        if blob:
            if not on_disk.is_file():
                return f"{path}: content differs from the branch (absent)"
            if _git("hash-object", "--", path, cwd=self.repo)[1] != blob:
                return f"{path}: content differs from the branch"
            if len(staged) < 3 or staged[1] != blob or staged[2] != "0":
                return f"{path}: index disagrees"
            if staged[0] != want:
                return (f"{path}: index disagrees (mode {staged[0]}, "
                        f"not the branch's {want})")
            found = _worktree_mode(on_disk)
            if modes and found != want:
                return (f"{path}: mode differs from the branch "
                        f"({found or 'unreadable'}, not {want})")
        elif on_disk.exists() or on_disk.is_symlink():
            return (f"{path}: content differs from the branch "
                    f"(the branch deleted it and it is still here)")
        elif staged:
            return f"{path}: index disagrees"
        return ""

    def _tree_is(self, sha: str) -> str:
        """Whether the repository still holds exactly the commit that was tested.

        Empty when everything agrees. Otherwise one line naming what does not —
        which is the whole answer the caller needs, because every disagreement
        means the same thing: what is about to deploy is not what was measured.
        """
        code, at = _git("rev-parse", "HEAD", cwd=self.repo)
        if code != 0:
            return f"git could not read HEAD: {at[:200]}"
        if at != sha:
            return f"HEAD is {at[:12]}, not the landed commit {sha[:12]}"
        code, dirty = _git("status", "--porcelain", cwd=self.repo)
        if code != 0:
            return f"git could not read the working tree: {dirty[:200]}"
        if dirty:
            return f"the working tree is not clean: {dirty[:200]}"
        if _git("merge-base", "--is-ancestor", sha, "main", cwd=self.repo)[0] != 0:
            return f"{sha[:12]} is no longer an ancestor of main"
        return ""

    def _refuse_to_deploy(self, task_id: str, why: str) -> str:
        """The tree drifted from the commit that was tested. Never a deploy."""
        self.q.move(task_id, State.CONTESTED,
                    reason=f"refused to deploy: {why}"[:500])
        log("REFUSED_TO_DEPLOY", task=task_id, why=why[:200])
        return State.CONTESTED

    def _blocked_after_landing(self, task_id: str, sha: str, gate: str,
                               detail: str) -> str:
        """A gate that could not be measured *after* the work landed.

        `_infra` requeues, and requeuing here is a rebuild: `_ship` has already
        deleted the branch, so the next run would build the same task again
        from scratch on top of the commit that already holds it. What is
        actually unknown is narrow and a person can settle it in a minute, so
        the reason says exactly what is known and what to check.
        """
        self.q.move(task_id, State.BLOCKED,
                    reason=f"landed as {sha}; {gate} could not be measured: "
                           f"{detail}; the branch is gone and the work is on "
                           f"main — a person checks {gates.MARKER} and "
                           f"redeploys with QEVIK_DEPLOY_SHA={sha} if needed")
        log("BLOCKED", task=task_id, why="post-landing gate unmeasured")
        return State.BLOCKED

    def _commit(self, task: dict, round_no: int) -> None:
        """Commit the task's work, and only the task's work.

        `git add -A` swept whatever else was in the tree into the review unit,
        and the proving run showed exactly what that costs: edits made by hand
        while the loop was running were committed under the task's name and
        reviewed as though the builder had written them. The reviewer then
        raised findings against work the task never touched.

        So the tree is required to be clean before a task starts, and anything
        present at that point is the caller's to deal with rather than the
        loop's to adopt.
        """
        # `git add -A` is the uncontrolled staging that put another task's
        # edits into a review unit. Paths are staged explicitly, and anything
        # the task did not touch stays where it is.
        for path in self._touched():
            _git("add", "--", path, cwd=self.repo)
        code, out = _git("diff", "--cached", "--quiet", cwd=self.repo)
        if code == 0:
            return                       # nothing staged; nothing to commit
        message = (f"{task['title']}\n\n{task['brief'][:1200]}\n\n"
                   f"devloop task {task['id']}, round {round_no}.\n\n"
                   "Co-Authored-By: Claude Opus 5 (1M context) "
                   "<noreply@anthropic.com>")
        _git("commit", "-q", "-m", message, cwd=self.repo)

    def _selector(self) -> str:
        """A `-k` expression covering the modules this task changed.

        Built from the changed **Python** paths rather than guessed. Empty when
        nothing recognisable changed, and empty means the whole suite — the safe
        direction, since a selector matching nothing would pass silently.

        Python only, because every touched path used to feed it. A task that
        changed only `docs/qevik-docs/00_PROJECT_STATE.md` produced
        `-k "00_PROJECT_STATE"`, which deselects the entire suite, and pytest
        exits 5 when it selected nothing: measured on 2026-09-02, "4306
        deselected, 1 warning in 1.97s", exit=5. `gates.tests` reads any
        non-zero exit as a failed gate, so a docs-only change went to the fixer
        with a deselection count as its failure scenario and burned its rounds
        on work that has no tests. That is the opposite of the failure this
        docstring promises: not matching nothing and passing silently, but
        matching nothing and failing loudly.

        A change touching both docs and code still narrows to the code.
        """
        names = set()
        for path in self._touched():
            if Path(path).suffix != ".py":
                continue
            stem = Path(path).stem
            if stem.startswith("test_"):
                stem = stem[len("test_"):]
            if stem and stem not in ("__init__", "conftest"):
                names.add(stem)
        return " or ".join(sorted(names))

    def _touched(self) -> list[str]:
        """Paths this task changed, from git rather than from an agent's word.

        Deliberately not `git status --porcelain`. Its output is column-aligned
        — two status characters then a space — and `_git` strips the combined
        stdout, which removes the leading space from the **first line only**.
        So the first changed file came back missing its first character:
        `.qevik/CAPABILITY_LEDGER.md` became `qevik/CAPABILITY_LEDGER.md`, git
        could not stage a path that does not exist, and the file stayed dirty
        through the commit. `clean_tree` then reported it as the reviewer
        writing to the tree, and three runs were spent isolating a reviewer
        that had never touched anything.

        These two commands print one path per line with no columns, so there is
        nothing to mis-slice.
        """
        tracked = _git("diff", "--name-only", "HEAD", cwd=self.repo)
        untracked = _git("ls-files", "--others", "--exclude-standard",
                         cwd=self.repo)
        found: list[str] = []
        for code, out in (tracked, untracked):
            if code != 0:
                continue
            found.extend(line.strip() for line in out.splitlines()
                         if line.strip())
        return found

    def _infra(self, task_id: str, detail: str) -> str:
        """The tooling failed, not the work. Requeue and count it."""
        self.infra_failures += 1
        self.q.move(task_id, State.QUEUED,
                    reason=f"infrastructure failure: {detail}"[:500])
        log("INFRA_FAILURE", task=task_id, detail=detail[:200],
            consecutive=self.infra_failures)
        return State.FAILED

    # -- the loop -----------------------------------------------------

    def loop(self, *, max_tasks: int, stop_after_one: bool = False) -> str:
        run_id = self.run_id = self.q.start_run()
        completed = 0
        because = "finished"
        log("RUN_START", run=run_id, owner=self.owner, max_tasks=max_tasks)
        try:
            while completed < max_tasks:
                self._check_stop()
                if self.infra_failures >= self.limits.consecutive_infra_failures:
                    because = (f"{self.infra_failures} consecutive "
                               "infrastructure failures — the tooling is "
                               "broken and a review it cannot run is not a "
                               "clean review")
                    break
                if completed and completed % self.limits.health_every_tasks == 0:
                    if not self.reviewer_healthy():
                        because = ("the reviewer failed its negative control; "
                                   "it no longer detects a planted defect")
                        break

                # A person may have answered while this loop was working. Freed
                # first, so a resolved boundary is picked up before anything
                # new is started.
                freed = boundary.release_resolved(self.q)
                if freed:
                    log("UNPARKED", tasks=freed)

                # Asked once per turn of the loop, not per task: the answer
                # is about the link, not about any one piece of work.
                link = gates.host_reachable()
                if not link.passed:
                    log("HOST_UNREACHABLE", detail=link.detail[:120])

                task = self.q.claim(owner=self.owner,
                                    host_reachable=link.passed)
                if task is None and not link.passed:
                    because = ("the control plane is unreachable and every "
                               "remaining task needs it to deploy or to be "
                               "verified in production")
                    break
                if task is None:
                    found = self.replenish()
                    if not found:
                        because = ("the queue is empty and production "
                                   "inspection found nothing actionable")
                        break
                    continue

                outcome = self.run_task(task)
                projection.write(self.repo, self.q)
                # Accounted for first, and stopped afterwards. `--once` is a
                # bound on how much work an invocation does, not a reason for
                # the run to have no record of what it did: returning from here
                # left a completed task counted as zero, an infrastructure
                # failure uncounted, and `finished` written as the reason.
                if outcome == State.DONE:
                    completed += 1
                    self.infra_failures = 0
                    self.q.bump_run(run_id, completed=1)
                elif outcome == State.FAILED:
                    self.q.bump_run(run_id, infra_failures=1)
                else:
                    # WAITING_FOR_HUMAN, BLOCKED or CONTESTED: parked, and the
                    # loop continues with independent work rather than stopping
                    # the project. This is §17 of the directive: the loop never
                    # halts merely because a human request exists.
                    self.infra_failures = 0
                if stop_after_one:
                    because = f"one task attempted, ending {outcome}"
                    break
        except Stopped:
            because = "stopped by signal"
        finally:
            # Back to `main`, always. The driver used to leave its task branch
            # checked out whenever a run ended badly, and three infrastructure
            # commits were made onto a task branch by somebody who did not
            # re-check — including the fix for the very bug those runs were
            # chasing. `main` never had it.
            on = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=self.repo)[1]
            if on != "main":
                _git("checkout", "-q", "main", cwd=self.repo)
                log("RETURNED_TO_MAIN", was=on)
            self.q.finish_run(run_id, because=because)
            projection.write(self.repo, self.q)
            log("RUN_END", run=run_id, completed=completed, because=because)
        return because

    def replenish(self) -> int:
        """Empty queue: ask production, not the human, and not an agent.

        Requirement, and the lesson of the last three sessions: "nothing to do"
        reached by asking which tracks are open was wrong every time, while
        reading what the running system was actually producing found a defect
        that had dropped 16% of the audited population from the funnel.
        """
        log("REPLENISH", reason="queue empty; inspecting production")
        from devloop import inspection

        found = inspection.enqueue_from_production(self.q, repo=self.repo)
        log("REPLENISHED", enqueued=found)
        return found

    def reviewer_healthy(self) -> bool:
        from devloop import negative_control

        result = negative_control.run(repo=self.repo,
                                      timeout=self.limits.review_timeout_s)
        self.q.record_reviewer_health(detected=result.detected,
                                      detail=result.detail)
        log("REVIEWER_HEALTH", detected=result.detected,
            detail=result.detail[:160])
        return result.detected


def _boundary_in(output: str) -> str:
    """A builder's declaration that it hit a human boundary."""
    for line in (output or "").splitlines():
        text = line.strip().strip('",')
        if text.upper().startswith("BLOCKED:"):
            return text[len("BLOCKED:"):].strip()[:400]
    return ""


# ------------------------------------------------------------------- cli


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status")
    sub.add_parser("inspect")
    sub.add_parser("health")

    add = sub.add_parser("enqueue")
    add.add_argument("--title", required=True)
    add.add_argument("--brief", required=True)
    add.add_argument("--origin", default="human")
    add.add_argument("--priority", type=int, default=50)
    add.add_argument("--evidence", default="{}")
    add.add_argument("--deploy", action="store_true")
    add.add_argument("--verify-production", action="store_true")
    add.add_argument("--path", action="append", default=[], required=True,
                     help="a path, directory (trailing /) or glob the task "
                          "may change; repeatable, at least one")

    declare = sub.add_parser("declare-paths")
    declare.add_argument("task")
    declare.add_argument("--path", action="append", default=[], required=True)
    declare.add_argument("--reason", default="")
    declare.add_argument("--actor", default=os.environ.get("USER", "person"))

    show = sub.add_parser("scope")
    show.add_argument("task")

    run = sub.add_parser("run")
    run.add_argument("--once", action="store_true")
    run.add_argument("--max-tasks", type=int, default=1)

    args = parser.parse_args(argv)
    q = Queue(REPO / ".qevik" / "devloop" / "state.db")

    if args.command == "status":
        rows = q.tasks()
        print(f"{len(rows)} task(s)")
        for t in rows:
            print(f"  {t['state']:<10} {t['priority']:>3}  {t['id']}  "
                  f"{t['title'][:58]}")
            if t["detail"]:
                print(f"             {t['detail'][:70]}")
        health = q.last_reviewer_health()
        print(f"\nreviewer: {'healthy' if (health or {}).get('detected') else 'unproven'}"
              f" ({(health or {}).get('at', 'never checked')})")
        evals = q.evaluations()
        if evals:
            print(f"\nevaluation queue: {len(evals)} unassessed project(s)")
        return 0

    if args.command == "enqueue":
        ident = q.add(title=args.title, brief=args.brief, origin=args.origin,
                      paths=args.path, priority=args.priority,
                      evidence=json.loads(args.evidence),
                      requires_deploy=args.deploy,
                      requires_prod_check=args.verify_production)
        print(ident)
        return 0

    if args.command == "declare-paths":
        declared = q.declare_paths(args.task, args.path, actor=args.actor,
                                   reason=args.reason)
        print(f"{args.task} may change: {', '.join(declared)}")
        return 0

    if args.command == "scope":
        task = q.get(args.task)
        if task is None:
            print(f"no task {args.task}")
            return 1
        print(f"declared: {allowed_paths(task) or '(none)'}")
        checks = q.scope_checks(args.task)
        if not checks:
            print("no scope check has measured this task")
        for one in checks:
            print(f"round {one['round']} at {one['sha'][:12]} ({one['at'][:19]}):"
                  f" {one['verdict']}")
            print(f"  changed:    {one['changed']}")
            print(f"  undeclared: {one['undeclared']}")
        return 0

    if args.command == "inspect":
        from devloop import inspection
        print(f"enqueued {inspection.enqueue_from_production(q, repo=REPO)}")
        return 0

    if args.command == "health":
        from devloop import negative_control
        result = negative_control.run(repo=REPO, timeout=1200)
        q.record_reviewer_health(detected=result.detected, detail=result.detail)
        print(("DETECTED — the reviewer is working" if result.detected
               else "NOT DETECTED — autonomous execution must not run"))
        print(f"  {result.detail}")
        return 0 if result.detected else 1

    limits = Limits(max_tasks=1 if args.once else args.max_tasks)
    driver = Driver(q, limits)
    because = driver.loop(max_tasks=limits.max_tasks,
                          stop_after_one=bool(args.once))
    print(f"\nstopped: {because}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
