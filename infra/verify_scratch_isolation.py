"""Proof that a mission cannot touch the repository it was cloned from.

Not a unit test. This builds a real git repository, runs a real mission through
the real worker with a real agent that really writes and commits, and then
compares the origin against a fingerprint taken before any of it happened.

The fingerprint covers refs, worktree metadata and the object count — not just
`HEAD`. Before this change the working *tree* of the origin was already
untouched, and calling that isolation was the mistake: `git worktree add` ran
inside the origin and left a branch, a worktree entry and every committed object
behind in it. A test that only checked `HEAD` and `git status` would have passed
on the broken version, which makes it worse than no test.

    python3 infra/verify_scratch_isolation.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "kernel"))
sys.path.insert(0, str(ROOT / "infra"))

from atlas_kernel.mission import policy, scratch, service  # noqa: E402
from atlas_kernel.mission.gitspace import GitWorkspace  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []
TENANT = "tenant-scratch-proof"


def check(name: str, ok: bool, detail: str = "") -> bool:
    (PASSED if ok else FAILED).append(name)
    print(f"{'  ok  ' if ok else '  FAIL'}  {name}{'  — ' + detail if detail else ''}")
    return ok


def git(*args: str, cwd: Path) -> str:
    env = dict(os.environ) | {
        "GIT_AUTHOR_NAME": "proof", "GIT_AUTHOR_EMAIL": "proof@qevik.local",
        "GIT_COMMITTER_NAME": "proof", "GIT_COMMITTER_EMAIL": "proof@qevik.local"}
    done = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, check=False, env=env)
    if done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {done.stderr.strip()[:200]}")
    return done.stdout.strip()


def a_repository(where: Path) -> Path:
    """A stand-in for the production checkout."""
    where.mkdir(parents=True, exist_ok=True)
    git("init", "-b", "main", ".", cwd=where)
    (where / "app.py").write_text("VERSION = 1\n")
    (where / "README.md").write_text("# production\n")
    git("add", ".", cwd=where)
    git("commit", "-m", "initial", cwd=where)
    return where


def main() -> int:
    print("scratch isolation — a real mission, a real repository\n")
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        origin = a_repository(tmp / "production")
        before = scratch.fingerprint(origin)

        # ---- the classifier -------------------------------------------
        check("a repository that is not the one this code runs from is external",
              scratch.classify(origin) is scratch.Origin.EXTERNAL,
              scratch.classify(origin).value)
        check("Qevik's own repository classifies as qevik",
              scratch.classify(ROOT) is scratch.Origin.QEVIK,
              scratch.classify(ROOT).value)
        check("no repository at all classifies as empty",
              scratch.classify(None) is scratch.Origin.EMPTY)

        # ---- a mission works, writes and commits ----------------------
        area = scratch.prepare(origin, mission_id="mission-proof",
                               root=tmp / "scratch")
        check("the scratch clone is not the origin",
              area.path.resolve() != origin.resolve(), str(area.path))
        check("the clone has the origin's content",
              (area.path / "app.py").read_text() == "VERSION = 1\n")

        space = GitWorkspace.create(area.path, branch="mission/proof",
                                    worktrees=tmp / "worktrees")
        # The agent's work: change a tracked file and add a new one.
        (space.root / "app.py").write_text("VERSION = 2\n")
        (space.root / "NEW.md").write_text("written by a mission\n")
        commit = space.commit("mission: change the app")
        check("the mission committed inside its own clone", bool(commit.sha),
              commit.sha[:12])
        check("...on its own branch, never a protected one",
              commit.branch == "mission/proof", commit.branch)

        # ---- THE claim -------------------------------------------------
        after = scratch.fingerprint(origin)
        for field in ("head", "branch", "refs", "status", "worktrees", "objects"):
            check(f"production {field} is unchanged after a mission ran",
                  before[field] == after[field],
                  f"{before[field]!r} -> {after[field]!r}"
                  if before[field] != after[field] else "")

        check("production's file content is untouched",
              (origin / "app.py").read_text() == "VERSION = 1\n",
              (origin / "app.py").read_text().strip())
        check("the file the mission created does not exist in production",
              not (origin / "NEW.md").exists())
        check("the mission's branch does not exist in production",
              "mission/proof" not in before["refs"]
              and "mission/proof" not in after["refs"])

        # ---- and a failure leaves it just as clean ---------------------
        failing = scratch.prepare(origin, mission_id="mission-fails",
                                  root=tmp / "scratch")
        bad = GitWorkspace.create(failing.path, branch="mission/fails",
                                  worktrees=tmp / "worktrees")
        (bad.root / "app.py").write_text("this mission went wrong\n")
        (bad.root / "junk.tmp").write_text("half-written\n")
        # No commit, no cleanup — exactly what a crash leaves behind.
        crashed = scratch.fingerprint(origin)
        check("a mission that fails mid-way leaves production unchanged",
              before == crashed,
              str({k: (before[k], crashed[k]) for k in before
                   if before[k] != crashed[k]}))
        check("...and its evidence survives in the scratch clone",
              (bad.root / "junk.tmp").exists() and bad.root.exists())

        # ---- discard only ever removes the clone ----------------------
        removed = area.discard()
        check("discarding a scratch removes the clone", removed["deleted"]
              and not area.path.exists())
        check("...and production is still there",
              (origin / "app.py").is_file()
              and scratch.fingerprint(origin) == before)

        pinned = scratch.Scratch(origin=origin, path=origin,
                                 kind=scratch.Origin.EXTERNAL)
        try:
            pinned.discard()
            check("discard refuses to delete the origin", False, "it deleted it")
        except scratch.ScratchError:
            check("discard refuses to delete the origin", True)

        # ---- an empty scratch is a real repository --------------------
        blank = scratch.prepare(None, mission_id="mission-blank",
                                root=tmp / "scratch")
        check("an empty scratch is usable as a repository",
              (blank.path / ".git").exists()
              and bool(git("rev-parse", "HEAD", cwd=blank.path)))
        check("an empty scratch is not a change to Qevik",
              not blank.modifies_qevik_itself)

        # ---- policy is not weakened -----------------------------------
        check("a clone of Qevik is still Qevik",
              scratch.Scratch(origin=ROOT, path=tmp / "x",
                              kind=scratch.classify(ROOT)).modifies_qevik_itself)

        never_approved = [{"status": "planning"}, {"status": "queued"}]
        approved = [{"status": "planning"}, {"status": "awaiting_approval"},
                    {"status": "queued"}]
        check("the worker refuses a Qevik-origin mission nobody approved",
              bool(policy.refuse_unapproved_self_modification(
                  never_approved, origin_is_qevik=True)))
        check("...allows one a person approved",
              not policy.refuse_unapproved_self_modification(
                  approved, origin_is_qevik=True))
        check("...and does not interfere with a customer repository",
              not policy.refuse_unapproved_self_modification(
                  never_approved, origin_is_qevik=False))

        # ---- provenance is recorded -----------------------------------
        mission, _ = service.create(tenant=TENANT, title="proof",
                                    requested_by="proof")
        mission = mission.model_copy(update={
            "workspace": str(area.path), "origin": str(origin),
            "origin_kind": scratch.classify(origin).value})
        back = service.rehydrate(mission.summary(), tenant=TENANT)
        check("the mission records the repository and workspace it used",
              back.origin == str(origin) and back.workspace == str(area.path)
              and back.origin_kind == "external",
              f"{back.origin_kind}")

        # ---- the requirement, in its own words -------------------------
        #
        # "an autonomous mission can modify its scratch workspace while the
        # production checkout remains unchanged". Everything above uses the
        # pieces directly; this drives the real worker as a subprocess, with a
        # mission that reached the queue on policy alone and no person ever
        # touched.
        autonomous(tmp)

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    return 1 if FAILED else 0


def autonomous(tmp: Path) -> None:
    """A real mission, a real worker process, nobody approving anything."""
    import sys as _sys

    from atlas_kernel.mission.models import MissionStatus, Plan, PlanStep
    from atlas_kernel.mission.timeline import Timeline

    origin = a_repository(tmp / "customer")
    before = scratch.fingerprint(origin)
    timeline = Timeline(tmp / "auto" / "missions.jsonl")

    mission, event = service.create(tenant=TENANT, title="autonomous change",
                                    requested_by="scheduler")
    timeline.append(event)
    mission, event = service.transition(mission, MissionStatus.PLANNING,
                                        tenant=TENANT, actor="scheduler")
    timeline.append(event)
    plan = Plan(goal="change a customer repository without a person",
                steps=(PlanStep(order=1, title="write", files=("reports/x.md",)),),
                estimated_cost=0.1, approval_required=False)
    mission, event = service.attach_plan(mission, plan, tenant=TENANT,
                                         agent_id="self-check",
                                         modifies_qevik_itself=False)
    timeline.append(event)
    check("an autonomous mission reaches the queue with nobody asked",
          mission.status is MissionStatus.QUEUED, mission.status.value)

    done = subprocess.run(
        [_sys.executable, str(ROOT / "infra" / "mission_worker.py"),
         "--timeline", str(timeline.path), "--tenant", TENANT,
         "--name", "worker-autonomous", "--repository", str(origin),
         "--worktrees", str(tmp / "auto" / "wt"),
         "--scratch", str(tmp / "auto" / "scratch"),
         "--reports", str(tmp / "auto" / "reports"),
         "--state", str(tmp / "auto" / "state"),
         "--agent", "self-check", "--once"],
        capture_output=True, text=True, timeout=600, check=False)
    check("the worker ran it", done.returncode == 0,
          f"exit {done.returncode}: {done.stderr[-200:]}" if done.returncode else "")

    folded = service.fold(Timeline(timeline.path).read(), tenant=TENANT)[0]
    check("THE AUTONOMOUS MISSION COMPLETED",
          folded["status"] == MissionStatus.COMPLETE.value, folded["status"])
    check("it worked in a scratch clone, not the origin",
          bool(folded.get("workspace"))
          and str(origin) not in folded.get("workspace", "x"),
          folded.get("workspace", ""))
    # Resolved, not as typed. Recording the path git actually used is the
    # useful thing: on macOS `/var` is a symlink to `/private/var`, and a
    # recorded origin that does not match what was cloned is a provenance field
    # that looks right and points somewhere else.
    check("it recorded the origin it was cloned from",
          Path(folded.get("origin", "")) == origin.resolve()
          and folded.get("origin_kind") == "external",
          f"{folded.get('origin')!r} vs {origin.resolve()}")

    after = scratch.fingerprint(origin)
    differing = [k for k in before if before[k] != after[k]]
    check("AND THE ORIGIN IS BYTE-FOR-BYTE UNCHANGED", not differing,
          ", ".join(f"{k}: {before[k]!r} -> {after[k]!r}" for k in differing))


if __name__ == "__main__":
    raise SystemExit(main())
