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
import os
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


#: Who the worker commits as. A `.local` address that cannot resolve, on
#: purpose: a commit from an automated worker must not look like it came from a
#: person, and must not reach a real mailbox if a host ever pushes.
COMMITTER_EMAIL = "agent@qevik.local"


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
             timeout: float = DEFAULT_TIMEOUT, identity: str = "") -> str:
        """Run one allow-listed git subcommand. No shell, ever.

        `identity` supplies the committer through the environment rather than
        through `-c user.email=…`, which would put a flag where the allow-list
        expects a subcommand — and that guard is worth more than the
        convenience.
        """
        if not args or args[0] not in ALLOWED:
            raise GitError(
                f"git {args[0] if args else '<nothing>'!r} is not permitted here. "
                f"Allowed: {', '.join(sorted(ALLOWED))}")
        for forbidden in ("--force", "-f", "--hard"):
            if forbidden in args:
                raise GitError(f"{forbidden} is never permitted: this module does "
                               "not rewrite or discard history")
        environment = dict(os.environ)
        if identity:
            environment.update({
                "GIT_AUTHOR_NAME": identity,
                "GIT_AUTHOR_EMAIL": COMMITTER_EMAIL,
                "GIT_COMMITTER_NAME": identity,
                "GIT_COMMITTER_EMAIL": COMMITTER_EMAIL,
            })
        completed = subprocess.run(
            ["git", *args], cwd=str(cwd or self.root), capture_output=True,
            text=True, timeout=timeout, check=False, env=environment)
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

        # A retry gets its own directory beside the previous attempt's.
        #
        # This refused outright, reasoning that "two missions chose one branch".
        # That is true of two *different* missions and the branch name already
        # prevents it — but a mission retried after a failure found its own
        # worktree and could never run again. Seen in production immediately
        # after the same bug was fixed one layer down in `scratch.prepare`: the
        # scratch clone was fresh and the worktree directory was not.
        #
        # The branch name is unchanged. Each attempt clones the origin afresh,
        # so `mission/<id>` does not exist in the new clone and there is nothing
        # to collide with. Only the directory is shared, and only across
        # attempts of one mission.
        #
        # The earlier attempt is kept. Its directory and diff are the evidence
        # for why it failed.
        root = Path(worktrees).resolve() / branch
        attempt = 1
        while root.exists():
            attempt += 1
            root = Path(worktrees).resolve() / f"{branch}-{attempt}"
            if attempt > 50:
                raise GitError(
                    f"{Path(worktrees).resolve() / branch} already has 50 "
                    "attempts. Something is retrying without ever succeeding, "
                    "and a 51st would hide that rather than surface it.")
        if attempt > 1:
            log.info("worktree for %s: attempt %d", branch, attempt)

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
        # The *committer* identity too, not only the author.
        #
        # `--author` sets who wrote the change; git still refuses without a
        # committer, which it takes from `user.email` in whoever's global config
        # happens to be present. On a developer machine that is set and this
        # worked; on the server it is not, and the first real mission run there
        # reached `committing` and died with "Committer identity unknown" after
        # doing all of the work.
        #
        # A worker's identity belongs to the worker, not to the shell it was
        # started from. Passed per-invocation rather than written to a config
        # file, so nothing about the host is modified.
        self._git("commit", "-m", message,
                  "--author", f"{author} <{COMMITTER_EMAIL}>",
                  identity=author)
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

    def discard(self) -> dict:
        """Remove a *committed* worktree directory. The branch survives it.

        Only safe once the work is committed: the commit lives on the branch and
        the directory is a checkout of it, so removing the directory loses
        nothing. Refuses while changes are uncommitted, because then the
        directory *is* the work — that is `keep()`'s job, not this one.

        Without this, every successful mission leaves a worktree behind and the
        disk fills with directories nobody will ever open.
        """
        outstanding = self.changed()
        if outstanding:
            raise GitError(
                f"{self.root} has {len(outstanding)} uncommitted change(s). "
                "Removing it now would destroy work that exists nowhere else; "
                "commit it or keep() it as failure evidence.")
        removed = subprocess.run(
            ["git", "worktree", "remove", str(self.root)],
            cwd=str(self.repository), capture_output=True, text=True, check=False)
        if removed.returncode != 0:
            raise GitError(
                f"could not remove worktree: {removed.stderr.strip()[:300]}")
        self.commands.append(f"git worktree remove {self.root}")
        log.info("removed mission worktree %s (branch %s kept)",
                 self.root, self.branch)
        return {"removed": True, "worktree": str(self.root),
                "branch": self.branch,
                "note": "the branch and its commits are untouched"}
