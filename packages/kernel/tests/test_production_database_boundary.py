"""The test suite must not be able to open the production database.

Not a hypothetical. Before the redirect existed the suite wrote 1,431
organizations, 2,475 projects and 4,947 assets into production, plus 747 fake
businesses that had to be quarantined and 108 outreach rows that made "how many
businesses have we contacted" unanswerable.

The redirect in `conftest.py` fixed that for code which loads that conftest. This
covers everything else, by refusing at the engine instead of redirecting before
it — a redirect that computes the wrong name silently uses production, while a
refusal cannot.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from atlas_kernel import db_safety

KERNEL = str(Path(__file__).resolve().parents[1])


# --- what counts as a test database ---------------------------------------

@pytest.mark.parametrize("url", [
    "postgresql+psycopg://u:p@h:5432/qevik_test",
    "postgresql+psycopg://u:p@h:5432/atlas_test",
    "postgresql+psycopg://u:p@h:5432/test_atlas",
    "postgresql+psycopg://u:p@h:5432/qevik-test-1",
    "sqlite:///:memory:",
])
def test_a_test_database_is_allowed(url) -> None:
    db_safety.check(url, testing=True)


@pytest.mark.parametrize("url", [
    "postgresql+psycopg://u:p@h:5432/qevik",
    "postgresql+psycopg://u:p@h:5432/atlas",
    "postgresql+psycopg://u:p@h:5432/production",
    "postgresql+psycopg://u:p@h:5432/qevik_prod",
    "postgresql+psycopg://u:p@h:5432/",
    "",
])
def test_anything_not_clearly_a_test_database_is_refused(url) -> None:
    """Fail closed: unable to tell is treated as production."""
    with pytest.raises(db_safety.ProductionDatabaseRefused):
        db_safety.check(url, testing=True)


def test_production_code_is_unaffected() -> None:
    """The guard exists for test processes only; the product must still run."""
    db_safety.check("postgresql+psycopg://u:p@h/qevik", testing=False)


# --- the escape hatch must be deliberate -----------------------------------

def test_the_escape_hatch_works_and_is_explicit(monkeypatch) -> None:
    monkeypatch.setenv(db_safety.ESCAPE_HATCH, "1")
    db_safety.check("postgresql+psycopg://u:p@h/qevik", testing=True)


@pytest.mark.parametrize("value", ["0", "true", "yes", "", "TRUE"])
def test_only_an_exact_1_opens_the_hatch(monkeypatch, value) -> None:
    """A hatch that opens on any truthy string opens by accident."""
    monkeypatch.setenv(db_safety.ESCAPE_HATCH, value)
    with pytest.raises(db_safety.ProductionDatabaseRefused):
        db_safety.check("postgresql+psycopg://u:p@h/qevik", testing=True)


def test_the_refusal_never_leaks_credentials() -> None:
    with pytest.raises(db_safety.ProductionDatabaseRefused) as raised:
        db_safety.check("postgresql+psycopg://user:hunter2@host/qevik", testing=True)
    assert "hunter2" not in str(raised.value)
    assert "<redacted>" in str(raised.value)


# --- detecting a test process ----------------------------------------------

def test_a_running_pytest_is_detected() -> None:
    assert db_safety.in_test_process(), "pytest is importing this file right now"


def test_detection_does_not_depend_on_one_variable(monkeypatch) -> None:
    """PYTEST_CURRENT_TEST alone is defeatable; the import check backs it up."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert db_safety.in_test_process(), "pytest in sys.modules must still catch it"


# --- the regression: a real process, a real import -------------------------

def _run(url: str, *, under_pytest: bool, extra: dict | None = None) -> tuple[int, str]:
    """Import atlas_kernel.db in a fresh interpreter and report what happened."""
    env = {**os.environ, "ATLAS_DATABASE_URL": url, "PYTHONPATH": KERNEL}
    env.pop("PYTEST_CURRENT_TEST", None)
    env.pop(db_safety.ESCAPE_HATCH, None)
    env.update(extra or {})
    script = textwrap.dedent(f"""
        import sys
        {'import pytest' if under_pytest else ''}
        try:
            import atlas_kernel.db  # noqa: F401
            print("CONNECTED")
        except Exception as error:
            print(type(error).__name__)
    """)
    done = subprocess.run([sys.executable, "-c", script], env=env,
                          capture_output=True, text=True, timeout=120)
    return done.returncode, (done.stdout + done.stderr).strip()


def test_a_test_process_cannot_open_production() -> None:
    """The regression. A process that has imported pytest is refused."""
    _code, out = _run("postgresql+psycopg://u:p@127.0.0.1:5432/qevik", under_pytest=True)
    assert "ProductionDatabaseRefused" in out, out
    assert "CONNECTED" not in out


def test_a_test_process_may_open_a_test_database() -> None:
    _code, out = _run("postgresql+psycopg://u:p@127.0.0.1:5432/qevik_test",
                      under_pytest=True)
    assert "ProductionDatabaseRefused" not in out, out


def test_production_processes_are_not_blocked() -> None:
    """The guard must not be able to take the product down."""
    _code, out = _run("postgresql+psycopg://u:p@127.0.0.1:5432/qevik", under_pytest=False)
    assert "ProductionDatabaseRefused" not in out, out


def test_the_escape_hatch_works_in_a_real_process() -> None:
    _code, out = _run("postgresql+psycopg://u:p@127.0.0.1:5432/qevik", under_pytest=True,
                      extra={db_safety.ESCAPE_HATCH: "1"})
    assert "ProductionDatabaseRefused" not in out, out


# --- the guard has to be wired in, not merely present ----------------------

def test_the_engine_module_actually_calls_the_guard() -> None:
    """A guard nothing calls is a guard nobody knows is missing."""
    source = (Path(KERNEL) / "atlas_kernel" / "db.py").read_text(encoding="utf-8")
    assert "db_safety" in source
    assert source.index("_refuse_production_in_tests(") < source.index("create_engine(")


def test_this_very_suite_is_pointed_at_a_test_database() -> None:
    """Whatever the harness did, the result must be a test database."""
    url = os.environ.get("ATLAS_DATABASE_URL", "")
    if not url:
        pytest.skip("no database configured")
    assert db_safety.looks_like_test_database(url), \
        f"the suite is pointed at {db_safety.database_name(url)!r}"


def test_the_conftest_redirect_is_still_in_place() -> None:
    """Belt and braces: the redirect and the refusal are independent."""
    conftest = (Path(__file__).parent / "conftest.py").read_text(encoding="utf-8")
    assert "ATLAS_DATABASE_URL" in conftest
    assert "_test" in conftest
