"""Git isolation, tested against a real repository.

§5 says agents must not casually edit the user's working tree. These tests build
an actual git repo in a temp directory and prove the worktree keeps the
operator's checkout untouched — and that the four structural refusals are
refusals rather than conventions: never a protected branch, never a rewrite,
never a push, never an unscanned commit.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from atlas_kernel.mission.gitspace import (
    ALLOWED,
    PROTECTED,
    GitError,
    GitWorkspace,
    SecretFound,
)


@pytest.fixture
def repo(tmp_path) -> Path:
    """A real repository with one commit on main."""
    root = tmp_path / "repo"
    root.mkdir()

    def run(*args: str) -> None:
        subprocess.run(args, cwd=str(root), capture_output=True, check=True)

    run("git", "init", "-q", "-b", "main")
    run("git", "config", "user.email", "t@example.test")
    run("git", "config", "user.name", "Test")
    (root / "README.md").write_text("hello\n")
    run("git", "add", "-A")
    run("git", "commit", "-q", "-m", "first")
    return root


@pytest.fixture
def workspace(repo, tmp_path) -> GitWorkspace:
    return GitWorkspace.create(repo, branch="mission-1",
                               worktrees=tmp_path / "worktrees")


# ============================================ the operator's tree is untouched

def test_a_mission_works_in_its_own_directory(repo, workspace) -> None:
    (workspace.root / "NEW.md").write_text("added by the agent\n")

    assert workspace.changed() == ("NEW.md",)
    assert not (repo / "NEW.md").exists(), "the operator's checkout is untouched"
    assert (repo / "README.md").read_text() == "hello\n"


def test_a_commit_lands_on_the_mission_branch_only(repo, workspace) -> None:
    (workspace.root / "NEW.md").write_text("work\n")
    commit = workspace.commit("agent work")

    assert commit.sha and commit.branch == "mission-1"
    assert commit.files == ("NEW.md",)
    on_main = subprocess.run(["git", "log", "--oneline", "main"], cwd=str(repo),
                             capture_output=True, text=True, check=True).stdout
    assert "agent work" not in on_main, "main did not move"


def test_the_base_commit_is_recorded(repo, workspace) -> None:
    """A change is only reviewable against what it started from."""
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo),
                          capture_output=True, text=True, check=True).stdout.strip()
    assert workspace.base == head


# ============================================ the four refusals

def test_a_protected_branch_is_refused(repo, tmp_path) -> None:
    for branch in PROTECTED:
        with pytest.raises(GitError, match="protected"):
            GitWorkspace.create(repo, branch=branch,
                                worktrees=tmp_path / f"wt-{branch}")


def test_history_rewriting_flags_are_refused(workspace) -> None:
    for flag in ("--force", "--hard"):
        with pytest.raises(GitError, match="never permitted"):
            workspace._git("commit", flag)


def test_there_is_no_push_path_at_all(workspace) -> None:
    """Not a disabled one — `push` is not in the allow-list."""
    assert "push" not in ALLOWED
    with pytest.raises(GitError, match="not permitted"):
        workspace._git("push")


def test_an_unlisted_subcommand_cannot_run(workspace) -> None:
    """Allow-list, not deny-list: the safe direction when the caller is a model."""
    for command in ("reset", "rebase", "clean", "remote", "fetch"):
        with pytest.raises(GitError, match="not permitted"):
            workspace._git(command)


def test_a_commit_is_scanned_before_it_is_made(workspace) -> None:
    (workspace.root / "config.py").write_text(
        'TOKEN = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz012345"\n')

    with pytest.raises(SecretFound, match="credential-shaped"):
        workspace.commit("adds a token")

    log = subprocess.run(["git", "log", "--oneline"], cwd=str(workspace.root),
                         capture_output=True, text=True, check=True).stdout
    assert "adds a token" not in log, "the commit was aborted, not warned about"


def test_the_scan_names_the_file_and_never_the_secret(workspace) -> None:
    """Printing the match would put the secret in the log it exists to protect."""
    secret = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"
    (workspace.root / "leak.py").write_text(f'KEY = "{secret}"\n')

    assert workspace.scan() == ("leak.py",)
    with pytest.raises(SecretFound) as raised:
        workspace.commit("x")
    assert secret not in str(raised.value)
    assert "leak.py" in str(raised.value)


def test_ordinary_content_is_not_flagged(workspace) -> None:
    """A scanner that refuses everything is not a scanner."""
    (workspace.root / "notes.md").write_text(
        "We store the key under QEVIK_API_TOKEN, never inline.\n")
    assert workspace.scan() == ()
    assert workspace.commit("notes").sha


# ============================================ collisions and evidence

def test_two_missions_cannot_share_a_worktree(repo, tmp_path) -> None:
    """Silently reusing one would mix their work."""
    GitWorkspace.create(repo, branch="mission-x", worktrees=tmp_path / "wt")
    with pytest.raises(GitError, match="already exists"):
        GitWorkspace.create(repo, branch="mission-x", worktrees=tmp_path / "wt")


def test_a_failed_worktree_is_kept_as_evidence(workspace) -> None:
    """Tidying it away destroys the only record of what the agent did."""
    (workspace.root / "half-done.py").write_text("incomplete\n")
    kept = workspace.keep("tests failed")

    assert kept["kept"] is True
    assert kept["reason"] == "tests failed"
    assert Path(kept["worktree"]).exists()
    assert kept["changed"] == ["half-done.py"]
    assert kept["branch"] == workspace.branch


def test_an_empty_commit_is_refused(workspace) -> None:
    with pytest.raises(GitError, match="nothing to commit"):
        workspace.commit("nothing happened")


def test_a_commit_needs_a_message(workspace) -> None:
    (workspace.root / "x.md").write_text("x\n")
    with pytest.raises(GitError, match="needs a message"):
        workspace.commit("   ")


def test_a_directory_that_is_not_a_repository_is_refused(tmp_path) -> None:
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    with pytest.raises(GitError, match="not a git repository"):
        GitWorkspace.create(plain, branch="m", worktrees=tmp_path / "wt")


def test_every_git_command_is_recorded(workspace) -> None:
    """The command list is the audit trail for what touched the repository."""
    (workspace.root / "x.md").write_text("x\n")
    workspace.commit("work")
    assert any(c.startswith("git commit") for c in workspace.commands)
    assert any(c.startswith("git add") for c in workspace.commands)
