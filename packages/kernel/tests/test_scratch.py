"""The scratch clone, and the boundary it draws.

`infra/verify_scratch_isolation.py` proves the whole thing against a real
repository and a real mission. This pins the pieces — the classifier that
decides whether work is self-modification, and the refusals that stop a clone
from becoming a way around approval.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from atlas_kernel.mission import policy, scratch


def a_repo(where: Path) -> Path:
    where.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main", "."], cwd=where,
                   capture_output=True, check=True)
    (where / "file.txt").write_text("original\n")
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@q.local",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@q.local",
           "PATH": "/usr/bin:/bin:/usr/local/bin"}
    subprocess.run(["git", "add", "."], cwd=where, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=where, env=env,
                   capture_output=True, check=True)
    return where


# ------------------------------------------------------------- the classifier

def test_qeviks_own_repository_is_recognised_as_itself():
    """Derived from `__file__`, so there is no configuration that turns the
    self-modification rule off."""
    mine = scratch.running_from()
    assert mine is not None
    assert scratch.classify(mine) is scratch.Origin.QEVIK


def test_someone_elses_repository_is_external(tmp_path):
    assert scratch.classify(a_repo(tmp_path / "customer")) is scratch.Origin.EXTERNAL


def test_no_repository_is_empty():
    assert scratch.classify(None) is scratch.Origin.EMPTY


def test_a_clone_of_qevik_is_still_qevik(tmp_path):
    """Staging work somewhere else does not change what the work is."""
    area = scratch.Scratch(origin=scratch.running_from(),
                           path=tmp_path / "clone",
                           kind=scratch.classify(scratch.running_from()))
    assert area.modifies_qevik_itself


def test_an_empty_scratch_is_not_a_change_to_qevik(tmp_path):
    area = scratch.prepare(None, mission_id="m-1", root=tmp_path)
    assert not area.modifies_qevik_itself
    assert area.kind is scratch.Origin.EMPTY


# ----------------------------------------------------------------- preparing

def test_a_clone_carries_the_origins_content(tmp_path):
    origin = a_repo(tmp_path / "origin")
    area = scratch.prepare(origin, mission_id="m-1", root=tmp_path / "scratch")
    assert (area.path / "file.txt").read_text() == "original\n"
    assert area.path.resolve() != origin.resolve()


def test_writing_in_the_clone_does_not_reach_the_origin(tmp_path):
    origin = a_repo(tmp_path / "origin")
    before = scratch.fingerprint(origin)
    area = scratch.prepare(origin, mission_id="m-1", root=tmp_path / "scratch")
    (area.path / "file.txt").write_text("changed by a mission\n")
    (area.path / "new.txt").write_text("new\n")
    assert (origin / "file.txt").read_text() == "original\n"
    assert not (origin / "new.txt").exists()
    assert scratch.fingerprint(origin) == before


def test_an_empty_scratch_has_a_resolvable_head(tmp_path):
    """`GitWorkspace.create` resolves a base, and a repository with no commits
    has no HEAD to resolve."""
    area = scratch.prepare(None, mission_id="m-1", root=tmp_path)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=area.path,
                          capture_output=True, text=True, check=False)
    assert head.returncode == 0
    assert head.stdout.strip()


def test_two_missions_may_not_share_a_scratch(tmp_path):
    origin = a_repo(tmp_path / "origin")
    scratch.prepare(origin, mission_id="m-1", root=tmp_path / "scratch")
    with pytest.raises(scratch.ScratchError, match="already exists"):
        scratch.prepare(origin, mission_id="m-1", root=tmp_path / "scratch")


def test_a_scratch_must_belong_to_a_named_mission(tmp_path):
    with pytest.raises(scratch.ScratchError, match="named mission"):
        scratch.prepare(None, mission_id="  ", root=tmp_path)


def test_a_non_repository_origin_is_refused(tmp_path):
    (tmp_path / "not-a-repo").mkdir()
    with pytest.raises(scratch.ScratchError, match="not a git repository"):
        scratch.prepare(tmp_path / "not-a-repo", mission_id="m-1",
                        root=tmp_path / "scratch")


def test_the_clone_is_physical_not_shared(tmp_path):
    """`--shared` would leave the mission's objects reachable only through the
    origin, which is the isolation failure with extra steps."""
    origin = a_repo(tmp_path / "origin")
    area = scratch.prepare(origin, mission_id="m-1", root=tmp_path / "scratch")
    alternates = area.path / ".git" / "objects" / "info" / "alternates"
    assert not alternates.exists(), alternates.read_text() if alternates.exists() else ""


# ------------------------------------------------------------------ discarding

def test_discarding_removes_the_clone_and_nothing_else(tmp_path):
    origin = a_repo(tmp_path / "origin")
    before = scratch.fingerprint(origin)
    area = scratch.prepare(origin, mission_id="m-1", root=tmp_path / "scratch")
    assert area.discard()["deleted"]
    assert not area.path.exists()
    assert origin.is_dir()
    assert scratch.fingerprint(origin) == before


def test_discard_refuses_to_delete_the_origin(tmp_path):
    origin = a_repo(tmp_path / "origin")
    pinned = scratch.Scratch(origin=origin, path=origin,
                             kind=scratch.Origin.EXTERNAL)
    with pytest.raises(scratch.ScratchError, match="refusing to delete the origin"):
        pinned.discard()
    assert (origin / "file.txt").is_file()


# ---------------------------------------------------------------- the git guard

def test_the_allow_list_refuses_a_subcommand_nobody_listed(tmp_path):
    with pytest.raises(scratch.ScratchError, match="not permitted"):
        scratch._git("push", "origin", "main", cwd=tmp_path)


def test_the_allow_list_has_no_push_or_remote(tmp_path):
    assert "push" not in scratch.ALLOWED
    assert "remote" not in scratch.ALLOWED
    assert "reset" not in scratch.ALLOWED


# ------------------------------------------------------------ the second guard

def test_an_unapproved_qevik_mission_is_refused():
    never = [{"status": "planning"}, {"status": "queued"}]
    assert policy.refuse_unapproved_self_modification(never, origin_is_qevik=True)


def test_an_approved_qevik_mission_is_allowed():
    approved = [{"status": "planning"}, {"status": "awaiting_approval"},
                {"status": "queued"}]
    assert not policy.refuse_unapproved_self_modification(
        approved, origin_is_qevik=True)


def test_a_customer_repository_is_not_held_by_the_self_modification_guard():
    never = [{"status": "planning"}, {"status": "queued"}]
    assert not policy.refuse_unapproved_self_modification(
        never, origin_is_qevik=False)


def test_the_guard_reads_the_state_not_the_note():
    """A note saying "approved by operator" must not be enough on its own."""
    forged = [{"status": "queued", "note": "approved by operator"}]
    assert policy.refuse_unapproved_self_modification(forged, origin_is_qevik=True)


def test_a_requeued_mission_keeps_its_approval():
    """Stale release and retry both go back to QUEUED. The approval that got it
    there the first time is still in the history."""
    history = [{"status": "planning"}, {"status": "awaiting_approval"},
               {"status": "queued"}, {"status": "processing"},
               {"status": "queued"}]
    assert not policy.refuse_unapproved_self_modification(
        history, origin_is_qevik=True)


# --------------------------------------------------------------- fingerprinting

def test_the_fingerprint_notices_a_stray_branch(tmp_path):
    """The field that mattered. `HEAD`, `branch` and `status` were all unchanged
    by the old worktree-on-the-origin path — only refs, worktree metadata and
    the object count moved, so a fingerprint without them proves nothing."""
    origin = a_repo(tmp_path / "origin")
    before = scratch.fingerprint(origin)
    subprocess.run(["git", "branch", "someone-elses-work"], cwd=origin,
                   capture_output=True, check=True)
    after = scratch.fingerprint(origin)
    assert before != after
    assert before["head"] == after["head"], "the change was invisible to HEAD"
    assert before["status"] == after["status"], "and invisible to status"
    assert before["refs"] != after["refs"]
