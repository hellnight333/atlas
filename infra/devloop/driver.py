#!/usr/bin/env python3
"""The development loop. Neither agent drives it.

    driver.py status                 what the queue holds
    driver.py enqueue --title ... --brief ... --path ... [--path ...]
    driver.py declare-paths <task> --path ... [--path ...]   contract for a legacy row
    driver.py declare-deploy-only <task>   its whole content is the deploy
    driver.py requeue <task>         a task that ended, back on the queue
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
                     commit, then every changed path is
                     inside the contract                 (objective)
                     outside it → CONTESTED, unreviewed
      → REVIEWING    Codex on base..HEAD                 (read-only, blind)
          findings → FIXING → GATING → REVIEWING  (at most three rounds)
          three rounds and still contested → CONTESTED
      → DEPLOYING    where the task declares it          (objective)
      → VERIFYING    where the task declares it          (objective)
      → DONE

A task that only deploys takes the same last three steps with nothing in front
of them. The builder is told never to deploy and to change nothing it cannot do
inside its paths, so a task whose whole content is "put what `main` already
carries on the host" correctly leaves no diff — and the `changed` gate failed it
for that, which is how t-4f02ee7a36c0 deployed nothing and verified nothing.
Such a task **declares itself deploy-only** (`enqueue --deploy-only`, or
`declare-deploy-only` on a row that predates the flag); the driver then records
the `main` sha it is deploying and runs exactly the gates the merged path runs:
the whole suite, the deploy script's exit code, the production probe. There is
no review and no scope check, because a review of nothing and a contract
measured against nothing are both vacuous — and there is no second deploy
mechanism: both routes run the same `_finish`.

The declaration is required and is never inferred from the diff. "Nothing
changed" is also exactly what a builder that silently did nothing leaves behind,
and `requires_deploy` is carried by every task that must build something and
*then* deploy it — including every task production inspection enqueues. Reading
those two facts as "there was nothing to do" would deploy unchanged code and
write DONE against work nobody did, which is the failure the `changed` gate
exists for. An undeclared task with an empty diff keeps failing, with the
declaration named in its reason so a person can correct it and requeue.

Correcting it takes both commands, because `claim` runs on the state and the
declaration does not change it: `declare-deploy-only` says what the task is,
and `requeue` makes it runnable. The task this whole path was written for was
already FAILED when it was declared, and a declaration alone would have left it
exactly as unreachable as it was.

`requeue` also refuses a condition no state names: work that `main` already
carries. A task that built something, was reviewed clean and then failed its
deploy or its production probe is FAILED with the work *already* squash-merged
into `main` and its branch gone — and a full suite that fails after that merge
is CONTESTED the same way. Restarting either would hand a builder a `main` that
already carries the work, so it correctly writes nothing and the `changed` gate
ends the task before the deploy it was put back for. The landing is measured
from git rather than assumed: the squash commit carries `queue.landing_marker`,
and a task found on `main` is refused with the sha named. Redeploying what
`main` carries is what a deploy-only task is, so that is what such a retry is
enqueued as. What is measured is the present tense — a landing that was later
reverted is not one, and that task is put back like any other.

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
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from devloop import agents, boundary, gates, projection  # noqa: E402
from devloop.queue import (Queue, State, allowed_paths,  # noqa: E402
                           declares_deploy_only, landing_marker, redact)

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
            # The tree first, and then the range, because the question is
            # "does this task have work" and a clean tree only answers it for
            # a task that starts from nothing.
            #
            # A resumed task has already committed its rounds to its branch —
            # `_commit` runs before every review, and an out-of-scope task is
            # contested *after* that commit. So the repair the out-of-scope
            # ledger entry prescribes — widen the contract with
            # `declare-paths`, put the task back with `requeue` — comes back to
            # a branch that carries the work and a tree that is clean, and a
            # builder that correctly writes nothing more would have been failed
            # here for "nothing changed": the requeue could only succeed if the
            # builder edited something it had no reason to edit.
            #
            # So the fallback measures the review unit itself, `base..HEAD` —
            # the same range the size gate bounds, the scope gate reads, the
            # reviewer is shown and the squash would take. For a fresh branch
            # `base` is HEAD and the range is empty, so a builder that did
            # nothing still fails exactly as before; nothing that had work is
            # failed for not having written it twice.
            diff = gates.changed(cwd=self.repo)
            if not diff.passed and not diff.unmeasured:
                diff = gates.changed(cwd=self.repo, base_sha=base)
            if not diff.passed:
                # A task that only deploys has nothing to write, and failing it
                # for that is exactly what stopped t-4f02ee7a36c0: the builder
                # is told never to deploy and to change nothing it cannot do
                # inside its paths, so it correctly left the tree as it found
                # it, and "nothing changed" ended a task whose whole content
                # was the deploy.
                #
                # Three conditions, and the first is the one that matters: the
                # task must have *declared* itself deploy-only. `requires_deploy`
                # cannot stand in for it — every task that builds something and
                # then deploys it carries that flag too, including every task
                # production inspection enqueues — so classifying on the flag
                # plus an empty diff would read "the builder silently did
                # nothing" as "there was nothing to do", deploy unchanged code
                # and record an unimplemented task as DONE — which is the exact
                # failure this gate was written to catch, arriving through the
                # exemption meant to spare one legitimate task from it.
                #
                # The other two are measured rather than assumed. The gate must
                # have *measured* an empty diff — an unreadable repository has
                # established nothing and stays a failure — and the branch must
                # carry nothing beyond `main` either, so a deploy-only task that
                # did build something still goes through review, scope and the
                # squash-merge exactly as it does today.
                if declares_deploy_only(task) and not diff.unmeasured:
                    carried = gates.changed(cwd=self.repo, base_sha="main")
                    if not carried.passed and not carried.unmeasured:
                        return self._deploy_only(task, started)
                # What the builder said, kept with the failure. Without it
                # "nothing changed" is undiagnosable: a refusal, a crash, a
                # boundary it did not phrase as one, and an agent that simply
                # did nothing all look identical afterwards.
                said = " ".join((built.output or "").split())[-600:]
                # And, for the one case that is not a defect: a task whose whole
                # content really is the deploy says so with `declare-deploy-only`
                # and is requeued. A person decides that, not the driver — the
                # driver cannot see the difference, which is the reason it asks.
                #
                # Both commands are named because both are needed. This row is
                # about to become FAILED, `claim` reads the state and the
                # declaration does not change it, so declaring alone leaves the
                # task exactly as unreachable as this failure left it.
                hint = ("" if declares_deploy_only(task) else
                        " | if this task's whole content is the deploy, "
                        "declare it and put it back: declare-deploy-only "
                        "<task>, then requeue <task>")
                self.q.move(ident, State.FAILED,
                            reason=f"{diff.detail} | builder said: {said}{hint}")
                log("FAILED", task=ident, why="nothing changed",
                    builder_said=said[-300:])
                return State.FAILED
            # Narrowed to what the task touched. Measured: the full suite is
            # about eleven minutes a round against a two-minute review, so
            # running all of it every round spent roughly a third of each cycle
            # re-proving code the task never went near. `_finish` still runs
            # the whole suite before anything deploys, which is where that
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

            # Too large to finish, before a reviewer spends rounds proving it.
            bounded = gates.size(cwd=self.repo, base_sha=base)
            if not bounded.passed and not bounded.unmeasured:
                self.q.move(ident, State.CONTESTED,
                            reason=f"oversized: {bounded.detail}",
                            head_sha=head_sha(self.repo))
                projection.park_oversized(self.repo, task, bounded.detail)
                log("OVERSIZED", task=ident, detail=bounded.detail[:160])
                _git("checkout", "-q", "main", cwd=self.repo)
                return State.CONTESTED

            # -- the immutable review unit --------------------------------
            # Committed *before* review so the diff cannot move under the
            # reviewer, and so a finding names a sha somebody can check out.
            self._commit(task, round_no)
            sha = head_sha(self.repo)

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
        _git("checkout", "-q", "main", cwd=self.repo)
        merged, out = _git("merge", "--squash", branch, cwd=self.repo)
        if merged != 0:
            self.q.move(ident, State.CONTESTED,
                        reason=f"the reviewed work would not land: {out[:300]}")
            return State.CONTESTED
        # `landing_marker`, not a second copy of the same words. This message is
        # the record that `main` carries this task, and `queue.landed_sha` reads
        # it back to refuse a requeue that would start a run with nothing left
        # to build. Two spellings of it drifting apart would disable that guard
        # silently, so there is one spelling and both ends use it.
        _git("commit", "-q", "-m",
             f"{task['title']}\n\n{task['brief'][:900]}\n\n"
             f"{landing_marker(ident)}; reviewer clean after "
             f"{task.get('review_rounds') or 1} round(s).\n\n"
             "Co-Authored-By: Claude Opus 5 (1M context) "
             "<noreply@anthropic.com>", cwd=self.repo)
        _git("branch", "-D", branch, cwd=self.repo)
        landed = head_sha(self.repo)
        log("LANDED", task=ident, sha=landed[:12])
        # The four gates this route ran before it got here, named rather than
        # copied from `gates.required`: what a task *requires* and what a given
        # route actually ran are the same list on this path and are not on the
        # other one, and the DONE record has to say what happened.
        return self._finish(task, started, sha=landed,
                            passed=("changed", "tests", "scope", "review"))

    def _deploy_only(self, task: dict, started: float) -> str:
        """A task whose whole content is the deploy. There is no diff to review.

        t-4f02ee7a36c0 asked for the unreviewed-drafts surface to be deployed
        and verified in production. The builder is told never to deploy and to
        change nothing it cannot do inside its paths, so it changed nothing —
        correctly — and the `changed` gate ended the task FAILED. Nothing was
        deployed and nothing was verified. Every DONE task before it declared
        `requires_deploy=0`, which is why the hole stayed invisible: the deploy
        gates could only be reached by squash-merging a diff, and a deploy of
        what `main` already carries has no diff to merge.

        So the diff is replaced by the one fact a person needs afterwards —
        which `main` sha went to the host — and the gates that follow are the
        same ones, in the same order, run by the same `_finish`. There is no
        review and no scope check because there is nothing to review and
        nothing to measure: both would be vacuous, and a vacuous pass recorded
        against a head is worse than no record at all.

        Which tasks may come here is a declaration on the task row, not
        something read off the diff. An empty diff is equally what a builder
        that silently did nothing leaves behind, and `requires_deploy` is
        carried by every task that must build something and *then* deploy it —
        so inferring it would deploy unchanged code for tasks whose work was
        never done, and write DONE against them.
        """
        ident = task["id"]
        branch = f"devloop/{ident}"

        # Structural, not incidental. This is the one path that deploys without
        # a review, so it must be impossible to reach it while anything a
        # reviewer has not seen exists — or for a task that never said its
        # content was the deploy. The caller established all three before
        # delegating here, and all three are asked again — of the row and of
        # git, not of the caller — for the same reason `_ship` re-asks the
        # review record before it merges: "only reachable from" is a property of
        # today's control flow, and the guard has to live in the code that acts.
        if not declares_deploy_only(task):
            self.q.move(ident, State.FAILED,
                        reason="refused to deploy without a review: this task "
                               "does not declare that its whole content is the "
                               "deploy, so an empty diff is a build that did "
                               "not happen")
            log("REFUSED_TO_DEPLOY", task=ident, why="not declared deploy-only")
            _git("checkout", "-q", "main", cwd=self.repo)
            return State.FAILED
        pending = gates.changed(cwd=self.repo)
        carried = gates.changed(cwd=self.repo, base_sha="main")
        if (pending.passed or carried.passed
                or pending.unmeasured or carried.unmeasured):
            self.q.move(ident, State.CONTESTED,
                        reason="refused to deploy without a review: this task "
                               "branch is not identical to main "
                               f"({pending.detail[:120]} | "
                               f"{carried.detail[:120]})")
            log("REFUSED_TO_DEPLOY", task=ident)
            _git("checkout", "-q", "main", cwd=self.repo)
            return State.CONTESTED

        # `deploy_control.sh` copies the working tree and refuses to run from
        # anywhere but a clean `main` — so this is not merely tidy, it is what
        # makes the deploy possible at all.
        _git("checkout", "-q", "main", cwd=self.repo)
        # `-d`, not `-D`: an empty branch deletes and a branch holding anything
        # unmerged refuses to, so this cannot be the line that throws work away.
        _git("branch", "-d", branch, cwd=self.repo)
        sha = head_sha(self.repo)
        self.q.move(ident, State.GATING, head_sha=sha,
                    reason=f"nothing to build: this task deploys what main "
                           f"already carries, at {sha}")
        log("DEPLOY_ONLY", task=ident, sha=sha[:12],
            note="no diff to review; deploying what main already carries")
        # Nothing is claimed as already passed. Three of this task's required
        # gates do not run on this route — the first of them is how the task
        # arrived here, having failed it — and `_finish` records them as not
        # run rather than writing a pass against a check nobody performed.
        return self._finish(task, started, sha=sha, passed=())

    def _finish(self, task: dict, started: float, *, sha: str,
                passed: tuple[str, ...] = ()) -> str:
        """The gates that run on `main`, and the state they leave a task in.

        One deploy mechanism, reached two ways: work that was reviewed and
        squash-merged, and a task that had nothing to merge because `main`
        already carries what it deploys. Both run the whole suite, then the
        deploy script's own exit code, then the production probe — in that
        order, each recorded against the sha that is going to the host.

        `passed` is what the caller ran and passed on the way here, and the
        DONE record is built from it plus what this method runs — never from
        `gates.required`, which is what a task *demands* and not what happened
        to it. The two lists are identical on the merged route and are not on
        the other one: `changed`, `scope` and `review` are required of every
        task and none of the three runs on a deploy with no diff, `changed`
        having failed on the way in. Copying the requirement into the record
        would write "review passed" against a review nobody performed, on the
        one route that deliberately has none — so the record names what ran,
        and names separately what did not.
        """
        ident = task["id"]
        needed = gates.required(task)
        ran = list(passed)
        if "deployed" in needed:
            # The whole suite before anything leaves this machine. A narrowed
            # run is a real gate for a narrow change and is not enough to
            # deploy on.
            whole = gates.tests(cwd=self.repo)
            if whole.unmeasured:
                return self._infra(ident, f"full suite unmeasured: {whole.detail}")
            if not whole.passed:
                self.q.move(ident, State.CONTESTED,
                            reason=f"full suite fails: {whole.detail}")
                return State.CONTESTED
            # Once, however many times it ran. The merged route already passed
            # a narrowed suite under the same gate's name.
            if "tests" not in ran:
                ran.append("tests")
            self.q.move(ident, State.DEPLOYING,
                        reason=f"{sha[:12]}: full suite {whole.detail}")
            log("DEPLOYING", task=ident, sha=sha[:12])
            shipped = gates.deployed(cwd=self.repo)
            if shipped.unmeasured:
                return self._infra(ident, shipped.detail)
            if not shipped.passed:
                self.q.move(ident, State.FAILED,
                            reason=f"{sha[:12]}: the deploy failed: "
                                   f"{shipped.detail}")
                log("FAILED", task=ident, why="deploy failed")
                return State.FAILED
            ran.append("deployed")

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
            self.q.move(ident, State.VERIFYING,
                        reason=f"probing {sha[:12]} in production")
            log("VERIFYING", task=ident, sha=sha[:12])
            live = gates.in_production(cwd=self.repo, probe=probe)
            if live.unmeasured:
                return self._infra(ident, live.detail)
            if not live.passed:
                self.q.move(ident, State.FAILED,
                            reason=f"{sha[:12]}: production did not agree: "
                                   f"{live.detail}")
                log("FAILED", task=ident, why="production did not agree")
                return State.FAILED
            ran.append("in_production")

        # What this task required and nothing on its route ran. Empty on the
        # merged path; on a deploy with no diff it is the three gates there was
        # nothing to run them against, and saying so is the whole difference
        # between a record and a claim.
        skipped = [name for name in needed if name not in ran]
        self.q.move(ident, State.DONE,
                    reason=f"gates: {', '.join(ran)} at {sha}"
                           + (f" | not run on this route: {', '.join(skipped)}"
                              if skipped else ""),
                    detail=f"completed in {int(time.monotonic() - started)}s")
        log("DONE", task=ident, sha=sha[:12],
            seconds=int(time.monotonic() - started))
        return State.DONE

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

        Built from the changed paths rather than guessed. Empty when nothing
        recognisable changed, and empty means the whole suite — the safe
        direction, since a selector matching nothing would pass silently.
        """
        names = set()
        for path in self._touched():
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
    add.add_argument("--deploy-only", action="store_true",
                     help="this task's whole content is the deploy: main "
                          "already carries what goes to the host, so there is "
                          "nothing to build and nothing to review. Implies "
                          "--deploy. Without it a task that changes nothing "
                          "fails, which is what catches a builder that did "
                          "nothing.")
    add.add_argument("--verify-production", action="store_true")
    add.add_argument("--path", action="append", default=[], required=True,
                     help="a path, directory (trailing /) or glob the task "
                          "may change; repeatable, at least one")

    declare = sub.add_parser("declare-paths")
    declare.add_argument("task")
    declare.add_argument("--path", action="append", default=[], required=True)
    declare.add_argument("--reason", default="")
    declare.add_argument("--actor", default=os.environ.get("USER", "person"))

    only = sub.add_parser("declare-deploy-only")
    only.add_argument("task")
    only.add_argument("--no", dest="deploy_only", action="store_false",
                      help="withdraw the declaration: this task must build "
                           "something before it deploys")
    only.add_argument("--reason", default="")
    only.add_argument("--actor", default=os.environ.get("USER", "person"))

    # The other half of every repair made on a task that already ended.
    # Declaring paths or a classification changes the row and leaves the state
    # alone, and `claim` reads the state — so without this the correction lands
    # on a task nothing will ever pick up again.
    # Refused for a task whose work `main` already carries: it has nothing left
    # to build, so the run it would start cannot reach the deploy it failed.
    again = sub.add_parser("requeue")
    again.add_argument("task")
    again.add_argument("--reason", default="")
    again.add_argument("--actor", default=os.environ.get("USER", "person"))

    show = sub.add_parser("scope")
    show.add_argument("task")

    run = sub.add_parser("run")
    run.add_argument("--once", action="store_true")
    run.add_argument("--max-tasks", type=int, default=1)

    args = parser.parse_args(argv)
    # The repository, explicitly. `requeue` refuses a task whose work `main`
    # already carries, and it measures that from git — so the queue is told
    # which tree to ask rather than left to infer it.
    q = Queue(REPO / ".qevik" / "devloop" / "state.db", repo=REPO)

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
                      requires_prod_check=args.verify_production,
                      deploy_only=args.deploy_only)
        print(ident)
        return 0

    if args.command == "declare-paths":
        declared = q.declare_paths(args.task, args.path, actor=args.actor,
                                   reason=args.reason)
        print(f"{args.task} may change: {', '.join(declared)}")
        return 0

    if args.command == "declare-deploy-only":
        set_to = q.declare_deploy_only(args.task, actor=args.actor,
                                       deploy_only=args.deploy_only,
                                       reason=args.reason)
        print(f"{args.task} "
              + ("deploys what main already carries; it builds nothing and is "
                 "not reviewed" if set_to else
                 "must build something before it deploys"))
        # The declaration says what the task is; it does not make it runnable.
        # The row this command exists for was already FAILED when it was
        # declared, so the next step is named here rather than left to be
        # discovered by watching a queue that never picks the task up.
        ended = (q.get(args.task) or {}).get("state")
        if ended in State.RETRYABLE:
            print(f"  it ended {ended}, so nothing will claim it until it is "
                  f"put back:\n    driver.py requeue {args.task}")
        return 0

    if args.command == "requeue":
        try:
            moved = q.requeue(args.task, actor=args.actor, reason=args.reason)
        except KeyError:
            print(f"no task {args.task}")
            return 1
        except ValueError as refused:
            print(refused)
            return 1
        print(f"{args.task} is queued again" if moved
              else f"{args.task} was already queued")
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
