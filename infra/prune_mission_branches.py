"""Remove mission branches that are provably nobody's, and nothing else.

`/opt/qevik/atlas` carries `mission/*` branches and stale `.git/worktrees`
entries left by harness runs against the pre-scratch-clone code. They are
harmless — the worker no longer touches that repository — but they are also
exactly the contamination the scratch clone exists to prevent, and leaving them
makes "is production clean" a question nobody can answer with yes.

**Deleting them is not obviously safe**, which is why this is a program rather
than a shell one-liner. A mission's commits now live *only* on its branch: the
scratch clone is the sole copy, so a branch is not clutter, it is an artefact
awaiting promotion. Deleting one belonging to a live mission destroys work
somebody is waiting to review.

So the rule is inverted from the usual cleanup:

    delete nothing unless it can be **proven** stale

and proof means: the branch names a mission that appears in **none** of the
timelines it was checked against, and in no report. Anything else — a mission
that is still running, a mission whose report cites its commit, a branch that is
not a mission branch at all, a timeline that could not be read — is protected,
and the reason is printed.

A timeline that cannot be read makes every branch protected, deliberately. Not
knowing which missions exist is not the same as knowing there are none, and the
optimistic reading of that difference deletes somebody's work.

    python3 infra/prune_mission_branches.py --repository /opt/qevik/atlas \
        --timeline /var/lib/qevik/control/missions.jsonl \
        --reports /var/lib/qevik/control/reports

Dry run by default. `--apply` performs the deletions it just listed.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

#: Only these are ever candidates. A branch outside this shape is not something
#: this program has an opinion about.
BRANCH = re.compile(r"^mission/(?P<mission>mission-[0-9a-f]{6,})$")

#: Git subcommands this program may run. `push` is absent, as is anything that
#: rewrites history: the worst outcome here should be "a branch is gone", never
#: "the repository is different".
ALLOWED = frozenset({"for-each-ref", "branch", "worktree", "rev-parse",
                     "show-ref", "cat-file", "log"})


class PruneError(RuntimeError):
    """Something could not be established, so nothing is deleted."""


def git(repository: Path, *args: str, check: bool = True) -> str:
    if not args or args[0] not in ALLOWED:
        raise PruneError(f"git {args[0] if args else '<nothing>'!r} is not "
                         f"permitted here. Allowed: {', '.join(sorted(ALLOWED))}")
    done = subprocess.run(
        ["git", "-c", f"safe.directory={repository}", *args],
        cwd=str(repository), capture_output=True, text=True, check=False)
    if done.returncode != 0 and check:
        raise PruneError(f"git {args[0]} failed: {done.stderr.strip()[:200]}")
    return done.stdout.strip()


@dataclass
class Verdict:
    """One branch, and whether it can be proven stale."""

    branch: str
    mission_id: str
    sha: str
    stale: bool
    because: str
    #: Where this mission's worktree was registered, if it still says. Reported
    #: as **corroboration, never as a rule**: a worktree under /tmp says the
    #: mission almost certainly came from a harness run, which is useful to the
    #: person deciding and is not proof of anything on its own. Turning it into
    #: a deletion rule would mean guessing from a path, which is how a cleanup
    #: removes something that mattered.
    hint: str = ""

    def line(self) -> str:
        mark = "STALE    " if self.stale else "PROTECTED"
        extra = f"  [{self.hint}]" if self.hint else ""
        return f"  {mark}  {self.branch:<40} {self.because}{extra}"


@dataclass
class Known:
    """Every mission id anything still refers to."""

    ids: set[str] = field(default_factory=set)
    sources: list[str] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)

    @property
    def trustworthy(self) -> bool:
        """Whether "this mission is unknown" means anything.

        False when a source could not be read *or* when there were no sources at
        all — an empty set of known missions makes every branch look stale,
        which is the most dangerous possible reading of "I found nothing".
        """
        return not self.unreadable and bool(self.sources)


def known_missions(timelines: list[Path], reports: list[Path]) -> Known:
    """Mission ids from every timeline and report given."""
    found = Known()
    for path in timelines:
        if not path.is_file():
            found.unreadable.append(f"{path} (missing)")
            continue
        try:
            for line in path.read_text().splitlines():
                if not line.strip():
                    continue
                detail = (json.loads(line).get("detail") or {})
                mission_id = detail.get("mission_id")
                if mission_id:
                    found.ids.add(mission_id)
        except (OSError, json.JSONDecodeError) as broken:
            found.unreadable.append(f"{path} ({broken})")
            continue
        found.sources.append(str(path))

    for root in reports:
        if not root.is_dir():
            found.unreadable.append(f"{root} (missing)")
            continue
        for report in root.rglob("*.md"):
            for match in re.finditer(r"mission-[0-9a-f]{6,}", report.read_text()):
                found.ids.add(match.group(0))
        found.sources.append(str(root))
    return found


def worktree_hints(repository: Path) -> dict[str, str]:
    """Where each mission's worktree was, from `.git/worktrees`, if recorded."""
    hints: dict[str, str] = {}
    registered = repository / ".git" / "worktrees"
    if not registered.is_dir():
        return hints
    for entry in registered.iterdir():
        gitdir = entry / "gitdir"
        if not gitdir.is_file():
            continue
        try:
            path = Path(gitdir.read_text().strip()).parent
        except OSError:
            continue
        match = re.search(r"mission-[0-9a-f]{6,}", str(path))
        if match:
            temp = str(path).startswith(("/tmp/", "/var/folders/"))
            hints[match.group(0)] = (
                f"worktree was {path}"
                + (" — a temporary directory, so a harness run" if temp else ""))
    return hints


def assess(repository: Path, known: Known) -> list[Verdict]:
    """Every mission branch, with a verdict and the reason for it."""
    hints = worktree_hints(repository)
    raw = git(repository, "for-each-ref", "--format=%(refname:short) %(objectname)",
              "refs/heads/mission/")
    verdicts: list[Verdict] = []
    for line in (r for r in raw.splitlines() if r.strip()):
        name, _, sha = line.partition(" ")
        match = BRANCH.match(name)
        if not match:
            verdicts.append(Verdict(name, "", sha.strip(), False,
                                    "not a mission branch by name; not this "
                                    "program's business"))
            continue
        mission_id = match.group("mission")

        if not known.trustworthy:
            verdicts.append(Verdict(
                name, mission_id, sha.strip(), False,
                "no readable source of live missions, so 'unknown' proves "
                "nothing", hints.get(mission_id, "")))
            continue

        if mission_id in known.ids:
            verdicts.append(Verdict(
                name, mission_id, sha.strip(), False,
                "a live mission or report still refers to this; its commits are "
                "the artefact awaiting promotion", hints.get(mission_id, "")))
            continue

        verdicts.append(Verdict(
            name, mission_id, sha.strip(), True,
            f"no timeline or report mentions {mission_id}",
            hints.get(mission_id, "")))
    return verdicts


def stale_worktrees(repository: Path) -> list[str]:
    """Worktree entries whose directory is gone.

    `git worktree prune` already refuses to remove one that still exists, so
    this reports rather than decides — but reporting first is the difference
    between a cleanup somebody reviewed and one they ran.
    """
    listing = git(repository, "worktree", "list", "--porcelain", check=False)
    gone: list[str] = []
    current = ""
    for line in listing.splitlines():
        if line.startswith("worktree "):
            current = line.split(" ", 1)[1]
        elif line.strip() == "prunable" and current:
            gone.append(current)
    registered = repository / ".git" / "worktrees"
    if registered.is_dir():
        for entry in sorted(registered.iterdir()):
            gitdir = entry / "gitdir"
            if gitdir.is_file():
                target = Path(gitdir.read_text().strip()).parent
                if not target.exists() and str(target) not in gone:
                    gone.append(str(target))
    return gone


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--timeline", action="append", default=[],
                        help="a mission timeline to check against. Repeatable. "
                             "With none given, nothing is ever deleted")
    parser.add_argument("--reports", action="append", default=[],
                        help="a reports directory to scan. Repeatable")
    parser.add_argument("--apply", action="store_true",
                        help="perform the deletions. Without it, this only says "
                             "what it would do")
    args = parser.parse_args(argv)

    repository = Path(args.repository).resolve()
    if not (repository / ".git").exists():
        print(f"{repository} is not a git repository", file=sys.stderr)
        return 2

    known = known_missions([Path(t) for t in args.timeline],
                           [Path(r) for r in args.reports])
    print(f"repository: {repository}")
    print(f"live missions known from: "
          f"{', '.join(known.sources) if known.sources else 'nothing'}")
    if known.unreadable:
        print(f"COULD NOT READ: {', '.join(known.unreadable)}")
        print("  Nothing will be deleted. Not knowing which missions exist is "
              "not the same as knowing there are none.")
    print(f"{len(known.ids)} mission id(s) still referred to\n")

    verdicts = assess(repository, known)
    if not verdicts:
        print("no mission branches. Nothing to do.")
    for verdict in verdicts:
        print(verdict.line())

    gone = stale_worktrees(repository)
    print(f"\nworktree entries whose directory no longer exists: {len(gone)}")
    for path in gone:
        print(f"  {path}")

    stale = [v for v in verdicts if v.stale]
    print(f"\n{len(stale)} branch(es) provably stale, "
          f"{len(verdicts) - len(stale)} protected")

    if not args.apply:
        print("\nDRY RUN. Nothing was changed. Re-run with --apply to delete "
              "the branches listed as STALE and prune the worktree entries.")
        return 0

    if not stale and not gone:
        print("\nnothing to apply")
        return 0

    for verdict in stale:
        # -D rather than -d: these branches are not merged anywhere and never
        # will be, so -d would refuse every one of them. The safety here is the
        # proof above, not git's own reachability check.
        git(repository, "branch", "-D", verdict.branch)
        print(f"  deleted {verdict.branch} ({verdict.sha[:12]})")
    if gone:
        git(repository, "worktree", "prune")
        print(f"  pruned {len(gone)} worktree entr(ies)")
    print("\ndone")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
