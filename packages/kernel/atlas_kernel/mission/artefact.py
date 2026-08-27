"""Reading a delivered artefact out of the commit that holds it.

A delivery writes files into its mission's worktree and commits them to that
mission's own branch; the worktree is then removed, because the commit is what
is durable. That is the right design and it left the artefact reachable only by
somebody with SSH and git — which is not a review surface, it is a person with a
terminal doing the control plane's job.

## Read-only, and narrow on purpose

Two git subcommands, both of which only read: `ls-tree` to say what is in the
commit and `show` to hand back one blob. No checkout, no worktree, no fetch,
nothing that writes. `GitWorkspace` exists for work that changes a repository
and this deliberately does not reuse it — a reader that could commit is a
reader somebody will eventually commit with.

## Three boundaries, none of them cosmetic

**The repository must sit under the scratch root.** The workspace path comes
from the mission record, and the mission record is trusted — but "trusted"
should not be the only thing standing between a web request and an arbitrary
directory on the host. A path outside the configured root is refused.

**The path must be inside `artefact/`.** The commit also contains
`.qevik-scratch` and whatever else the origin carried. Only what the delivery
produced is a delivered artefact.

**Nothing escapes the tree.** Files are read with `git show <branch>:<path>`,
so the answer comes from the commit's object store rather than the filesystem.
A path with `..` in it cannot resolve to something outside the commit, because
there is no outside — but it is refused anyway, because a reader should not
depend on that argument being true of every future git.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

#: Where scratch clones live. One name, read by the control plane and settable
#: for a test, matching how the worker is configured.
ENVIRONMENT = "QEVIK_SCRATCH"
DEFAULT_ROOT = "/var/lib/qevik/scratch"

#: The only git subcommands this module runs. Both read; neither writes.
READABLE: frozenset[str] = frozenset({"ls-tree", "show"})

#: What a delivery produced, as opposed to what its workspace happened to hold.
PREFIX = "artefact/"

#: A single file is returned in full up to this. A site page is a few kilobytes;
#: anything approaching this is not something a person reviews in a browser.
MAX_BYTES = 512 * 1024

#: Where the build records what it was answering.
PROVENANCE = f"{PREFIX}provenance.json"

TIMEOUT = 20.0


class Unreadable(Exception):
    """This artefact cannot be read, and why."""


def root() -> Path:
    return Path(os.environ.get(ENVIRONMENT) or DEFAULT_ROOT)


@dataclass(frozen=True)
class Entry:
    """One file in the commit."""

    path: str
    size: int
    #: The git object id, so a reviewer looking twice can tell they saw the
    #: same bytes.
    blob: str

    def summary(self) -> dict:
        return {"path": self.path, "size": self.size, "blob": self.blob,
                "name": self.path[len(PREFIX):] or self.path}


def _git(repository: Path, *args: str) -> str:
    if not args or args[0] not in READABLE:
        raise Unreadable(
            f"git {args[0] if args else '<nothing>'!r} is not permitted here. "
            f"This reader runs {', '.join(sorted(READABLE))} and nothing else.")
    done = subprocess.run(["git", "-C", str(repository), *args],
                          capture_output=True, text=True, timeout=TIMEOUT,
                          check=False)
    if done.returncode != 0:
        raise Unreadable(
            f"git {args[0]} failed: {done.stderr.strip()[:200]}")
    return done.stdout


def _repository(workspace: str, *, scratch: Path | None = None) -> Path:
    if not workspace:
        raise Unreadable(
            "this mission recorded no workspace, so there is nowhere an "
            "artefact could be.")
    base = (scratch or root()).resolve()
    try:
        path = Path(workspace).resolve()
    except OSError as broken:                      # noqa: PERF203 - reported
        raise Unreadable(f"unreadable workspace path: {broken}") from broken
    if not path.is_relative_to(base):
        raise Unreadable(
            f"{workspace} is outside {base}. An artefact is read from the "
            "scratch area a mission was given, not from anywhere a path "
            "happens to point.")
    if not (path / ".git").exists():
        raise Unreadable(f"{workspace} is not a repository")
    return path


def branch_of(mission_id: str) -> str:
    """The branch a mission commits to. The worker's convention, stated once."""
    return f"mission/{mission_id}"


def files(mission_id: str, workspace: str, *,
          scratch: Path | None = None) -> list[Entry]:
    """Everything the delivery produced, from the commit."""
    repository = _repository(workspace, scratch=scratch)
    raw = _git(repository, "ls-tree", "-r", "--long", branch_of(mission_id))
    found: list[Entry] = []
    for line in raw.splitlines():
        # `<mode> <type> <blob> <size>\t<path>`
        head, _, path = line.partition("\t")
        parts = head.split()
        if len(parts) < 4 or not path.startswith(PREFIX):
            continue
        size = int(parts[3]) if parts[3].isdigit() else 0
        found.append(Entry(path=path, size=size, blob=parts[2]))
    return sorted(found, key=lambda e: e.path)


def read(mission_id: str, workspace: str, path: str, *,
         scratch: Path | None = None) -> str:
    """One file's text, or a refusal. Never a truncated file passed off as one."""
    if not path.startswith(PREFIX) or ".." in path.split("/"):
        raise Unreadable(
            f"{path!r} is not part of this delivery. Only files under "
            f"{PREFIX!r} are artefact.")
    repository = _repository(workspace, scratch=scratch)
    known = {entry.path: entry for entry in files(mission_id, workspace,
                                                  scratch=scratch)}
    entry = known.get(path)
    if entry is None:
        raise Unreadable(f"{path!r} is not in this mission's commit")
    if entry.size > MAX_BYTES:
        raise Unreadable(
            f"{path} is {entry.size} bytes, over the {MAX_BYTES} this returns. "
            "A reviewer reading it in a browser would be reading part of a "
            "file and could not tell.")
    return _git(repository, "show", f"{branch_of(mission_id)}:{path}")


def provenance(mission_id: str, workspace: str, *,
               scratch: Path | None = None) -> dict:
    """What the build says it answered, or `{}` when it recorded none."""
    try:
        return json.loads(read(mission_id, workspace, PROVENANCE,
                               scratch=scratch))
    except (Unreadable, json.JSONDecodeError) as missing:
        log.info("no provenance for %s: %s", mission_id, missing)
        return {}


def commit_of(mission_id: str, workspace: str, *,
              scratch: Path | None = None) -> str:
    """The object id of the commit under review, so two reads can be compared."""
    repository = _repository(workspace, scratch=scratch)
    # `show -s --format=%H` reads; it is the same allow-listed subcommand.
    return _git(repository, "show", "-s", "--format=%H",
                branch_of(mission_id)).strip()


__all__ = ["DEFAULT_ROOT", "ENVIRONMENT", "MAX_BYTES", "PREFIX", "PROVENANCE",
           "READABLE", "Entry", "Unreadable", "branch_of", "commit_of", "files",
           "provenance", "read", "root"]
