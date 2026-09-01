"""Every source file the tests import will actually reach the repository.

This exists because it already failed. The credential vault — five modules and
the subject of forty-one security tests — sat untracked for two commits while
every test passed, because `.gitignore` carried a sensible generic rule
(`credentials/`, for directories secrets get stored in) that also matched a
source package sharing the name. The tests were committed. The code was not.

Nothing catches that from inside the process: the files are on disk, imports
resolve, the suite is green, and the commit reports success. It only shows up
when somebody clones the repository and the imports fail. So the check has to
ask git, not the filesystem.

The same shape of mistake is available to any future rule, and two already in
`.gitignore` would do it today: `assets/` and `models/` are excluded tree-wide,
and both are plausible names for a kernel package.

## What "git does not have this file" is allowed to mean

Two different facts wear that appearance and only one of them is a defect:

* **A rule hides it.** Git will never take the file — `git add` on it prints
  "The following paths are ignored" and does nothing. No amount of committing
  repairs that, and a clone will not have it. This is the vault incident.
* **Nobody has staged it yet.** The file is one `git add` away, and the process
  about to run that `git add` is usually the one running these tests.

The second is the ordinary state of every new file, and `infra/devloop` makes it
the *guaranteed* state: `driver.run_task` runs `gates.tests` before `_commit`,
so a task that adds a kernel module is always judged against a tree where that
module is untracked. Comparing the disk against `git ls-files` alone read that
as "the repository is missing a module" and failed the gate for the very change
that added it — a blocking failure with no action behind it, on a file the next
step commits. It stayed hidden this long only because `_selector` builds `-k`
from the stems of the changed paths, so this file is selected only when a task
also touches something else named `repository`.

So the question asked here is what a commit of *this* tree will contain: what
git already has, plus what git would accept. A module in neither is a module git
has been told to refuse, and that is the one worth failing over.

That is narrower than before, and one case is deliberately given up: a person
who stages paths by hand, commits, and leaves a module behind that git would
have taken. Nothing here can tell that from a module about to be staged — the
two differ only in what somebody intends to do next — and the version that
caught it also failed every task that added a file. What would catch it is a
different question, asked of `HEAD` rather than of the working tree: whether a
*committed* module imports one git does not have. That is the vault's actual
symptom, and it is not built here.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "packages" / "kernel" / "atlas_kernel"


def _ls_files(*flags: str) -> set[Path]:
    listed = subprocess.run(["git", "ls-files", "-z", *flags, "--", str(SOURCE)],
                            cwd=ROOT, capture_output=True, text=True, check=True)
    return {ROOT / name for name in listed.stdout.split("\0") if name}


def _tracked() -> set[Path]:
    """What git already has — committed, or staged and about to be."""
    return _ls_files()


def _addable() -> set[Path]:
    """Untracked files git would take, which is `git add`'s own answer.

    `--exclude-standard` applies exactly the exclusions `git add` applies:
    `.gitignore` at every level, `.git/info/exclude`, and `core.excludesFile`.
    Asking git rather than reading `.gitignore` matters here — the rule that
    decides may be a re-inclusion of an excluded parent
    (`!packages/kernel/atlas_kernel/credentials/` is one, and is the only reason
    the vault is in the repository today), and precedence between the patterns is
    git's to settle, not a regex's.

    So `_tracked() | _addable()` is what a commit of this tree will contain, and
    a file on disk in neither is one git has been told to refuse.
    """
    return _ls_files("--others", "--exclude-standard")


def _modules() -> set[Path]:
    return {p for p in SOURCE.rglob("*.py") if "__pycache__" not in p.parts}


@pytest.mark.integration
def test_no_kernel_module_is_hidden_from_git_by_an_ignore_rule() -> None:
    """A module git refuses is a module nobody else will ever have.

    Asks git rather than looking at the filesystem, because the filesystem is
    exactly what makes this invisible from inside a test run.
    """
    if not (ROOT / ".git").exists():                # pragma: no cover
        pytest.skip("not a git checkout")

    hidden = sorted(str(p.relative_to(ROOT))
                    for p in _modules() - _tracked() - _addable())
    assert not hidden, (
        "git has been told to refuse these modules, so a clone would not have "
        f"them and no commit will fix it: {hidden}. Check .gitignore for a rule "
        "matching a directory name that is also a package name, and re-include "
        "the package the way `!packages/kernel/atlas_kernel/credentials/` does.")


@pytest.mark.integration
def test_a_module_only_waiting_to_be_staged_is_not_reported_as_missing() -> None:
    """The false positive that failing over `git ls-files` alone produced.

    A new module is untracked at the moment the devloop's round gate judges it,
    every time, because the gate runs before the commit. Reading that as an
    absent module blocks the task that adds one on a fact that is true of every
    new file and actionable for none of them.
    """
    if not (ROOT / ".git").exists():                # pragma: no cover
        pytest.skip("not a git checkout")

    pending = _modules() - _tracked()
    assert pending <= _addable(), (
        "these modules are on disk, unstaged, and git will not take them: "
        f"{sorted(str(p.relative_to(ROOT)) for p in pending - _addable())}")


@pytest.mark.integration
def test_the_negative_control_would_notice() -> None:
    """The checker must be capable of failing.

    A completeness check that passes because it found nothing to look at is the
    same failure it exists to prevent, one level up. Both halves are exercised:
    the sets have to be real, and neither may be so broad that it absolves
    everything.
    """
    if not (ROOT / ".git").exists():                # pragma: no cover
        pytest.skip("not a git checkout")

    tracked = _tracked()
    assert tracked, "git reported no tracked kernel files at all"
    assert any(p.suffix == ".py" for p in tracked)
    assert _modules(), "no kernel modules were found on disk to check"

    # An invented module is in neither set, so a module git refused would be
    # reported rather than absolved. Without this, `_addable()` returning
    # everything would make the check above pass on any repository at all.
    invented = SOURCE / "definitely_not_a_real_module.py"
    assert invented not in tracked
    assert invented not in _addable()

    # And `--exclude-standard` is doing the excluding: bytecode caches are on
    # disk and untracked, and git offers to take none of them. Skipped rather
    # than asserted on a tree that has not imported anything yet.
    caches = {p for p in SOURCE.rglob("*.pyc")}
    if caches:
        assert not (caches & _addable()), (
            "git offered to take an ignored file, so `_addable()` is not "
            "applying the exclusions and absolves every module")
