"""A repository a mission may ruin, cloned from one it may not.

## What was actually wrong

`GitWorkspace` was described as isolation, and for the operator's *files* it
was: a worktree gives the agent its own directory, so nobody's edits are
disturbed. But `git worktree add` runs **inside the origin repository**, and it
writes there — a new ref under `.git/refs/heads`, metadata under
`.git/worktrees`, and every object the mission commits lands in the origin's
object store. On this deployment the origin is `/opt/qevik/atlas`: the
production checkout.

So "the worker does not modify production" was true of the working tree and
false of the repository. A mission that failed halfway left a branch and its
objects behind in the thing Qevik runs from.

## The shape now

    /opt/qevik/atlas              production. Read, never written.
        │  git clone --no-hardlinks
        ▼
    <scratch>/<mission>/repo      the mission's own repository
        │  git worktree add
        ▼
    <worktrees>/<branch>          where the agent works

The clone is a physical copy, not `--shared` and not hardlinked. `--shared`
would leave the mission's objects reachable only through the origin, which is
the isolation failure with extra steps; hardlinks are *probably* fine, since git
never rewrites an object in place, and "probably fine" is the wrong standard for
the file the business runs on. At 21 MB the copy costs a second.

`GitWorkspace` is unchanged and unaware. It is handed a repository path and
behaves exactly as before — which is the point: this adds a step to the pipeline
rather than a second pipeline.

## Promotion is the boundary, and it is still human

Nothing here merges, pushes, or touches the origin after the clone. A mission's
commits live in a directory that can be deleted without consequence. Getting
them into production is a separate, explicit, human act — the same act it was
before, now with the guarantee that *not* performing it leaves production
untouched.

## Cloning Qevik does not stop it being Qevik

A clone of Qevik's own source is still Qevik's own source: the work is intended
to become the running system, and where it is staged does not change that.
`modifies_qevik_itself` is therefore decided by the **origin**, not by the
workspace, and self-modification stays approval-gated exactly as before.

What the clone does change is narrower and worth stating precisely: a mission
with **no source repository at all** (`Origin.EMPTY`) now has somewhere real to
work. That mission genuinely does not modify Qevik, and can say so honestly —
which is what unattended recurring work was waiting for.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

log = logging.getLogger(__name__)

#: Git subcommands this module may run. Its own allow-list rather than a share
#: of `gitspace.ALLOWED`, because the two need different things and widening one
#: list to serve both would hand `clone` to the agent-facing surface.
ALLOWED: frozenset[str] = frozenset({"clone", "init", "add", "commit",
                                     "rev-parse", "config", "symbolic-ref"})

DEFAULT_TIMEOUT = 300.0

#: What an empty scratch repository starts with, so `rev-parse HEAD` resolves.
#: A repository with no commits has no HEAD, and `GitWorkspace.create` would
#: fail on a base it cannot name.
SEED_FILE = ".qevik-scratch"


class ScratchError(RuntimeError):
    """A scratch repository could not be prepared."""


class Origin(StrEnum):
    """Where a mission's starting point came from. Decides policy, not layout."""

    #: A clone of the repository this very code is running from. Self-modification.
    QEVIK = "qevik"
    #: Somebody else's repository — a customer, a business. Normal path.
    EXTERNAL = "external"
    #: No source at all. A fresh repository, nothing at risk.
    EMPTY = "empty"


def running_from() -> Path | None:
    """The repository this process's kernel was imported from, if it is one.

    Deliberately derived from `__file__` rather than passed in. "Is this Qevik's
    own source" is the question the whole self-modification rule rests on, and a
    configurable answer is one somebody can set to `false` — by mistake or
    otherwise — and thereby switch the rule off from a config file.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".git").exists():
            return parent
    return None


def classify(origin: Path | None) -> Origin:
    """What kind of starting point this is. Pure, and not overridable."""
    if origin is None:
        return Origin.EMPTY
    mine = running_from()
    resolved = Path(origin).resolve()
    if mine is not None and resolved == mine.resolve():
        return Origin.QEVIK
    return Origin.EXTERNAL


@dataclass
class Scratch:
    """One mission's private repository, and where it came from."""

    #: The repository cloned, or None for an empty scratch.
    origin: Path | None
    #: The clone. Safe to delete; nothing outside depends on it.
    path: Path
    kind: Origin
    commands: list[str] = field(default_factory=list)

    @property
    def modifies_qevik_itself(self) -> bool:
        """Whether work here is a change to Qevik's own source.

        A clone of Qevik is still Qevik. See the module note.
        """
        return self.kind is Origin.QEVIK

    def summary(self) -> dict:
        return {"origin": str(self.origin) if self.origin else "",
                "workspace": str(self.path), "kind": self.kind.value,
                "modifies_qevik_itself": self.modifies_qevik_itself}

    def discard(self) -> dict:
        """Delete the clone. Only ever the clone — never the origin."""
        if self.origin is not None and self.path.resolve() == Path(self.origin).resolve():
            raise ScratchError(
                "refusing to delete the origin: this is the scratch clone's "
                "whole purpose and deleting the source would invert it")
        existed = self.path.exists()
        shutil.rmtree(self.path, ignore_errors=True)
        return {"deleted": existed, "path": str(self.path)}


def _git(*args: str, cwd: Path, timeout: float = DEFAULT_TIMEOUT) -> str:
    if not args or args[0] not in ALLOWED:
        raise ScratchError(
            f"git {args[0] if args else '<nothing>'!r} is not permitted here. "
            f"Allowed: {', '.join(sorted(ALLOWED))}")
    completed = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                               text=True, timeout=timeout, check=False)
    if completed.returncode != 0:
        raise ScratchError(f"git {args[0]} failed: {completed.stderr.strip()[:300]}")
    return completed.stdout.strip()


def prepare(origin: Path | str | None, *, mission_id: str,
            root: Path | str) -> Scratch:
    """Clone `origin` into a directory belonging to this mission alone.

    `origin=None` produces an empty repository with one seed commit rather than
    an error: work that needs nowhere to start from still needs somewhere to
    write, and giving it a clone of Qevik "because that is what we have" is how
    unrelated work ends up classified as self-modification.
    """
    if not mission_id.strip():
        raise ScratchError("a scratch repository must belong to a named mission")

    path = Path(root).resolve() / mission_id / "repo"
    if path.exists():
        raise ScratchError(
            f"{path} already exists. Two missions sharing one scratch repository "
            "would mix their commits, which is the thing this prevents.")
    path.parent.mkdir(parents=True, exist_ok=True)

    kind = classify(Path(origin) if origin is not None else None)

    if origin is None:
        _git("init", "-b", "main", str(path), cwd=path.parent)
        (path / SEED_FILE).write_text(
            "This repository was created for one mission and may be deleted.\n")
        _git("add", SEED_FILE, cwd=path)
        _seed_commit(path)
        log.info("scratch repository for %s at %s (empty)", mission_id, path)
        return Scratch(origin=None, path=path, kind=kind)

    source = Path(origin).resolve()
    if not (source / ".git").exists():
        raise ScratchError(f"{source} is not a git repository")

    # --no-hardlinks: a physical copy. See the module note on why "probably
    # fine" is not the standard here.
    _git("clone", "--no-hardlinks", "--quiet", str(source), str(path),
         cwd=path.parent)
    log.info("scratch clone of %s for %s at %s", source, mission_id, path)
    return Scratch(origin=source, path=path, kind=kind)


def _seed_commit(path: Path) -> None:
    """One commit, so HEAD resolves. Identity through the environment, for the
    same reason `gitspace` does it: a flag where a subcommand is expected walks
    straight past the allow-list."""
    import os
    environment = dict(os.environ) | {
        "GIT_AUTHOR_NAME": "qevik", "GIT_AUTHOR_EMAIL": "agent@qevik.local",
        "GIT_COMMITTER_NAME": "qevik", "GIT_COMMITTER_EMAIL": "agent@qevik.local"}
    done = subprocess.run(["git", "commit", "-m", "scratch repository"],
                          cwd=str(path), capture_output=True, text=True,
                          check=False, env=environment)
    if done.returncode != 0:
        raise ScratchError(f"could not seed the scratch repository: "
                           f"{done.stderr.strip()[:200]}")


def fingerprint(repository: Path | str) -> dict:
    """Everything about a repository that a mission must not change.

    Used by the acceptance test to prove production came through untouched, and
    written here rather than in the test so the thing being asserted is defined
    once. Covers refs and objects, not just `HEAD` — a mission that leaves a
    stray branch behind has changed the repository even though `HEAD` is where
    it was, and that is precisely the failure this module exists to remove.
    """
    repo = Path(repository).resolve()
    def run(*args: str) -> str:
        done = subprocess.run(["git", *args], cwd=str(repo), capture_output=True,
                              text=True, check=False)
        return done.stdout.strip() if done.returncode == 0 else f"<error {args}>"

    worktrees = repo / ".git" / "worktrees"
    return {
        "head": run("rev-parse", "HEAD"),
        "branch": run("rev-parse", "--abbrev-ref", "HEAD"),
        "refs": run("show-ref"),
        "status": run("status", "--porcelain"),
        "worktrees": sorted(p.name for p in worktrees.iterdir()) if worktrees.is_dir() else [],
        "objects": len(list((repo / ".git" / "objects").rglob("*")))
        if (repo / ".git" / "objects").is_dir() else 0,
    }


__all__ = ["ALLOWED", "Origin", "Scratch", "ScratchError", "classify",
           "fingerprint", "prepare", "running_from"]
