"""Proving the reviewer still reviews.

A reviewer that has quietly stopped finding things looks exactly like a
codebase that has quietly become correct, and the loop cannot tell them apart
from the outside. So it is told: a defect is planted in an isolated worktree,
the real reviewer is pointed at it, and if it comes back clean the loop stops.

This is the repository's own doctrine turned on the checker — every guard here
is negative-controlled, and the reviewer is a guard.

## Why a worktree

The defect must never touch the tree the driver is building in. `git worktree`
gives a real repository at a real commit that the reviewer can diff against,
and removing it afterwards leaves nothing behind. The mission engine already
isolates this way, for the same reason.

The planted defect is deliberately of the kind that matters here: not a syntax
error, which anything would catch, but a plausible-looking off-by-one that
passes a reading and is wrong on the boundary.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import agents

#: A file that exists in the repository and is small enough to review quickly.
PLANTED_INTO = "infra/devloop/_canary.py"

CLEAN = '''"""A tiny module the reviewer's negative control edits. Not imported."""


def within_budget(spent: float, budget: float) -> bool:
    """Whether spending stays inside the budget. Equal is inside."""
    return spent <= budget
'''

#: Reversed comparison: `>=` returns True for everything at or above the
#: budget, so a run that has spent twice its budget reports as within it. It
#: reads almost right, which is the point — a reviewer that only catches
#: obvious breakage is not a reviewer.
DEFECTIVE = CLEAN.replace("return spent <= budget", "return spent >= budget")


@dataclass(frozen=True)
class Health:
    detected: bool
    detail: str


def _git(*args: str, cwd: Path) -> tuple[int, str]:
    done = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, stdin=subprocess.DEVNULL)
    return done.returncode, (done.stdout + done.stderr).strip()


def run(*, repo: Path, timeout: int = 1200) -> Health:
    """Plant a defect in a scratch worktree and see whether Codex finds it."""
    scratch = Path(tempfile.mkdtemp(prefix="devloop-canary-"))
    tree = scratch / "wt"
    try:
        code, out = _git("worktree", "add", "--detach", str(tree), "HEAD",
                         cwd=repo)
        if code != 0:
            return Health(False, f"could not create the worktree: {out[:200]}")

        target = tree / PLANTED_INTO
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(CLEAN)
        _git("add", "-A", cwd=tree)
        _git("-c", "user.email=devloop@qevik", "-c", "user.name=devloop",
             "commit", "-q", "-m", "canary baseline", cwd=tree)
        base = _git("rev-parse", "HEAD", cwd=tree)[1]

        target.write_text(DEFECTIVE)
        _git("add", "-A", cwd=tree)
        _git("-c", "user.email=devloop@qevik", "-c", "user.name=devloop",
             "commit", "-q", "-m", "canary change", cwd=tree)

        result = agents.review(cwd=tree, base_sha=base,
                               out_file=scratch / "review.json",
                               timeout=timeout)
        if result.infrastructure_failure:
            # The reviewer could not run. That is not "failed to detect" — it
            # is unmeasured, and the driver must treat it as a reason to stop
            # rather than as a verdict either way.
            return Health(False, f"the reviewer could not run: {result.detail}")

        findings = result.data.get("findings") or []
        hit = [f for f in findings
               if "_canary" in (f.get("file") or "")
               or "budget" in (f.get("claim", "") + f.get("failure_scenario", "")).lower()]
        if hit:
            return Health(True,
                          f"detected the planted defect: {hit[0]['claim'][:160]}")
        return Health(False,
                      f"verdict {result.data.get('verdict')} with "
                      f"{len(findings)} finding(s), none about the planted "
                      f"comparison")
    finally:
        _git("worktree", "remove", "--force", str(tree), cwd=repo)
        shutil.rmtree(scratch, ignore_errors=True)


__all__ = ["CLEAN", "DEFECTIVE", "Health", "PLANTED_INTO", "run"]
