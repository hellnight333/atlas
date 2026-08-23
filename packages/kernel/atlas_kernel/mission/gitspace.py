"""An isolated Git worktree per mission, so an agent never edits your checkout.

§5 is blunt about the risk: agents must not casually edit the user's main
working tree. A worktree gives each mission its own directory and its own
branch, sharing the object store, so the operator can keep working while a
mission runs and a failed mission leaves their files untouched.

Four refusals are structural rather than advisory:

**Never `main`.** A mission commits to its own branch. Promoting that branch is
a human decision made with a diff in front of them.
**Never force, never rewrite.** No `--force`, no `reset --hard`, no rebase.
**Never push.** This module has no push path at all — not a disabled one.
**Never commit an unscanned tree.** The secret scan runs before `git commit`,
and a hit aborts rather than warns.

A failed worktree is kept. The directory, the branch and the diff are the
evidence for why a mission failed, and removing them to tidy up destroys the
only record of what the agent actually did.
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

#: Branches a mission may never commit to. Promotion is a human decision.
PROTECTED: frozenset[str] = frozenset({"main", "master", "trunk", "production"})

#: Git subcommands this module will run. An allow-list rather than a deny-list:
#: a subcommand nobody listed cannot run, which is the safe direction to be
#: wrong in when the caller is a language model.
ALLOWED: frozenset[str] = frozenset({
    "worktree", "rev-parse", "status", "diff", "add", "commit", "branch",
    "checkout", "config", "show",
})

#: Credential shapes. Same list the publication Connection guard uses, for the
#: same reason — one definition of "this looks like a secret" is enough.
SECRET_SHAPED = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|\b(AKIA|ASIA)[0-9A-Z]{16}\b"
    r"|\bya29\.[A-Za-z0-9_\-]{10,}"
    r"|\bsk-(ant-)?[A-Za-z0-9_\-]{20,}"
    r"|\b(ghp|gho|ghs|ghu|ghr)_[A-Za-z0-9]{30,}\b"
    r"|\bxox[baprs]-[A-Za-z0-9\-]{10,}"
)

DEFAULT_TIMEOUT = 120.0


class GitError(RuntimeError):
    """A git command failed, or was not permitted."""


class SecretFound(GitError):
    """Something credential-shaped was about to be committed.

    Aborts rather than warns. A warning in a log nobody reads is how a key
    reaches a public repository.
    """


@dataclass
class Commit:
    """What was committed, and what it was built on."""

    sha: str
    branch: str
    base: str
    files: tuple[str, ...] = ()
    #: Always empty. Present so a report can state it rather than omit it.
    pushed: str = ""


@dataclass
class GitWorkspace:
    """One mission's worktree. Created isolated, kept on failure."""

    repository: Path
    branch: str
    root: Path
    base: str
    commands: list[str] = field(default_factory=list)

    # -- running git ------------------------------------------------------

    def _git(self, *args: str, cwd: Path | None = None,
             timeout: float = DEFAULT_TIMEOUT) -> str:
        """Run one allow-listed git subcommand. No shell, ever."""
        if not args or args[0] not in ALLOWED:
            raise GitError(
                f"git {args[0] if args else '<nothing>'!r} is not permitted here. "
                f"Allowed: {', '.join(sorted(ALLOWED))}")
        for forbidden in ("--force", "-f", "--hard"):
            if forbidden in args:
                raise GitError(f"{forbidden} is never permitted: this module does "
                               "not rewrite or discard history")
        completed = subprocess.run(
            ["git", *args], cwd=str(cwd or self.root), capture_output=True,
            text=True, timeout=timeout, check=False)
        self.commands.append("git " + " ".join(args))
        if completed.returncode != 0:
            raise GitError(f"git {args[0]} failed: {completed.stderr.strip()[:300]}")
        return completed.stdout.strip()

    # -- lifecycle --------------------------------------------------------

    @classmethod
    def create(cls, repository: Path | str, *, branch: str,
               worktrees: Path | str, base: str = "HEAD") -> GitWorkspace:
        """Add a worktree on a new branch. Refuses to touch a protected one."""
        repository = Path(repository).resolve()
        if branch in PROTECTED:
            raise GitError(
                f"{branch!r} is protected. A mission commits to its own branch; "
                "promoting it is a human decision made with a diff in view.")
        if not (repository / ".git").exists():
            raise GitError(f"{repository} is not a git repository")

        root = Path(worktrees).resolve() / branch
        if root.exists():
            raise GitError(
                f"{root} already exists. A collision means two missions chose "
                "one branch, and silently reusing it would mix their work.")

        resolved = subprocess.run(
            ["git", "rev-parse", base], cwd=str(repository), capture_output=True,
            text=True, check=False)
        if resolved.returncode != 0:
            raise GitError(f"cannot resolve {base!r} in {repository}")

        added = subprocess.run(
            ["git", "worktree", "add", "-b", branch, str(root), base],
            cwd=str(repository), capture_output=True, text=True, check=False)
        if added.returncode != 0:
            raise GitError(f"could not create worktree: {added.stderr.strip()[:300]}")

        log.info("mission worktree %s at %s", branch, root)
        return cls(repository=repository, branch=branch, root=root,
                   base=resolved.stdout.strip())

    def changed(self) -> tuple[str, ...]:
        """Paths differing from the base. The agent's own list is a claim."""
        out = self._git("status", "--porcelain")
        return tuple(line[3:].strip() for line in out.splitlines() if line.strip())

    def diff(self) -> str:
        return self._git("diff", "HEAD")

    def scan(self) -> tuple[str, ...]:
        """Files carrying something credential-shaped. Empty is the good case."""
        found: list[str] = []
        for relative in self.changed():
            path = self.root / relative
            if not path.is_file():
                continue
            try:
                body = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:                       # pragma: no cover - unreadable
                continue
            if SECRET_SHAPED.search(body):
                # The path only. Printing the match would put the secret in the
                # log this exists to keep it out of.
                found.append(relative)
        return tuple(found)

    def commit(self, message: str, *, author: str = "qevik-agent") -> Commit:
        """Commit the worktree, after scanning it. Never pushes."""
        if not message.strip():
            raise GitError("a commit needs a message")
        changed = self.changed()
        if not changed:
            raise GitError("nothing changed, so there is nothing to commit")

        leaking = self.scan()
        if leaking:
            raise SecretFound(
                "refusing to commit: credential-shaped content in "
                f"{', '.join(leaking)}. Remove it and retry — this aborts "
                "rather than warns, because a warning in a log nobody reads is "
                "how a key reaches a public repository.")

        self._git("add", "-A")
        self._git("commit", "-m", message,
                  "--author", f"{author} <agent@qevik.local>")
        sha = self._git("rev-parse", "HEAD")
        return Commit(sha=sha, branch=self.branch, base=self.base, files=changed)

    def keep(self, reason: str) -> dict:
        """Preserve a failed worktree and say where the evidence is.

        Not a cleanup path. The directory, the branch and the diff are why the
        mission failed, and tidying them away destroys the only record of what
        the agent actually did.
        """
        return {"kept": True, "reason": reason, "worktree": str(self.root),
                "branch": self.branch, "base": self.base,
                "changed": list(self.changed()),
                "note": "kept deliberately: this is the evidence for the failure"}
