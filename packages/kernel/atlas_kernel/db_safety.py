"""Refuse to let a test process open the production database.

The suite already redirects `ATLAS_DATABASE_URL` to a `_test` database in
`conftest.py`, and that redirect worked — but it protects only code that loads
that conftest. A script run from `infra/`, a test in another directory, a doctest,
a notebook, or a future conftest that stops importing first, all bypass it. The
evidence that this is not hypothetical is in the production database: 1,431
organizations, 2,475 projects and 4,947 assets written by the suite before the
redirect existed, plus 747 fake businesses that had to be quarantined.

So the enforcement moves to the one place every caller passes through — the
engine — and it **refuses** rather than redirects. A redirect that computes the
wrong name silently uses production; a refusal cannot.

Fail closed: when the process looks like a test and the URL does not clearly
name a test database, connecting raises. Being unable to tell is treated as
production, because that is the safe direction to be wrong in.
"""

from __future__ import annotations

import os
import re
import sys

#: Set deliberately, per-process, by something that genuinely must read
#: production from inside a test — currently one guard test that verifies
#: production stayed clean. Deliberately verbose: nobody sets this by accident.
ESCAPE_HATCH = "QEVIK_ALLOW_PRODUCTION_DB_IN_TESTS"

#: Names that unambiguously identify a throwaway database.
_TEST_DB = re.compile(r"(^|[_\-/])test($|[_\-])|_test$|^test_|(^|/)tmp", re.I)


class ProductionDatabaseRefused(RuntimeError):
    """A test process tried to open a database that is not a test database."""


def in_test_process() -> bool:
    """Whether this interpreter is running tests.

    Two signals because either alone is defeatable: the variable pytest sets per
    test, and pytest being imported at all — which covers collection, fixtures
    and module import, before any test has started running.
    """
    return bool(os.environ.get("PYTEST_CURRENT_TEST")) or "pytest" in sys.modules


def database_name(url: str) -> str:
    """The database a URL points at, without its credentials or query string."""
    tail = (url or "").rsplit("/", 1)[-1]
    return tail.split("?", 1)[0].strip()


def looks_like_test_database(url: str) -> bool:
    """True only when the name says so. Anything unclear is treated as production."""
    name = database_name(url)
    if not name:
        return False
    if name.startswith(":memory:") or url.startswith("sqlite"):
        return True
    return bool(_TEST_DB.search(name))


def redacted(url: str) -> str:
    return re.sub(r"//[^@/]+@", "//<redacted>@", url or "")


def check(url: str, *, testing: bool | None = None) -> None:
    """Raise if a test process is about to open a non-test database.

    Called at engine construction, so there is no path to a connection that
    skips it.
    """
    testing = in_test_process() if testing is None else testing
    if not testing:
        return
    if os.environ.get(ESCAPE_HATCH) == "1":
        return
    if looks_like_test_database(url):
        return
    raise ProductionDatabaseRefused(
        f"refusing to open {redacted(url)!r} from a test process: the database "
        f"{database_name(url)!r} is not named as a test database. Point "
        f"ATLAS_DATABASE_URL at a database whose name ends in '_test', or set "
        f"{ESCAPE_HATCH}=1 for the rare case that genuinely must read production."
    )
