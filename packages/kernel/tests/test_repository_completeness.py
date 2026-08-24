"""Every source file the tests import is actually in the repository.

This exists because it already failed. The credential vault — five modules and
the subject of forty-one security tests — sat untracked for two commits while
every test passed, because `.gitignore` carried a sensible generic rule
(`credentials/`, for directories secrets get stored in) that also matched a
source package sharing the name. The tests were committed. The code was not.

Nothing catches that from inside the process: the files are on disk, imports
resolve, the suite is green, and the commit reports success. It only shows up
when somebody clones the repository and the imports fail. So the check has to
ask git, not the filesystem.

The same shape of mistake is available to any future rule — `keys/`, `certs/`,
`private/` are all plausible additions and all plausible package names.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "packages" / "kernel" / "atlas_kernel"


def _tracked() -> set[Path]:
    listed = subprocess.run(["git", "ls-files", "-z", "--", str(SOURCE)],
                            cwd=ROOT, capture_output=True, text=True, check=True)
    return {ROOT / name for name in listed.stdout.split("\0") if name}


@pytest.mark.integration
def test_every_kernel_module_is_tracked_by_git() -> None:
    """A module on disk but not in git is a module nobody else has.

    Asks git rather than looking at the filesystem, because the filesystem is
    exactly what makes this invisible from inside a test run.
    """
    if not (ROOT / ".git").exists():                # pragma: no cover
        pytest.skip("not a git checkout")

    on_disk = {p for p in SOURCE.rglob("*.py")
               if "__pycache__" not in p.parts}
    missing = sorted(str(p.relative_to(ROOT)) for p in on_disk - _tracked())
    assert not missing, (
        "these modules exist locally but are not in the repository, so a clone "
        f"would not have them: {missing}. Check .gitignore for a rule matching "
        "a directory name that is also a package name.")


@pytest.mark.integration
def test_the_negative_control_would_notice() -> None:
    """The checker must be capable of failing.

    A completeness check that passes because it found nothing to look at is the
    same failure it exists to prevent, one level up.
    """
    if not (ROOT / ".git").exists():                # pragma: no cover
        pytest.skip("not a git checkout")

    tracked = _tracked()
    assert tracked, "git reported no tracked kernel files at all"
    assert any(p.suffix == ".py" for p in tracked)
    # An invented path is not tracked, so set difference does discriminate.
    assert (SOURCE / "definitely_not_a_real_module.py") not in tracked
