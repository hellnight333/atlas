"""Tests for the packaged-build entry point and packaging configuration.

The launcher is the code that runs on a machine with no Python, no database
and no shell. It is also the code least covered by every other test, because
every other test starts from an already-prepared database.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlas_kernel.launcher import (
    MAINTENANCE_DATABASE,
    _psycopg_dsn,
    _split_database_url,
    main,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


# --------------------------------------------------------------------------
# Database URL handling
# --------------------------------------------------------------------------


def test_maintenance_url_targets_the_always_present_database() -> None:
    maintenance, database = _split_database_url("postgresql+psycopg://atlas@127.0.0.1:5432/atlas")
    assert database == "atlas"
    assert maintenance.endswith(f"/{MAINTENANCE_DATABASE}")


def test_credentials_and_port_survive_the_rewrite() -> None:
    maintenance, database = _split_database_url(
        "postgresql+psycopg://someone:secret@db.internal:6543/atlas_prod"
    )
    assert database == "atlas_prod"
    assert "someone:secret@db.internal:6543" in maintenance
    assert maintenance.endswith("/postgres")


def test_a_url_without_a_database_name_is_rejected() -> None:
    with pytest.raises(ValueError, match="no database name"):
        _split_database_url("postgresql+psycopg://atlas@127.0.0.1:5432/")


def test_sqlalchemy_driver_prefix_is_stripped_for_psycopg() -> None:
    # psycopg does not understand SQLAlchemy's "+driver" notation.
    assert _psycopg_dsn("postgresql+psycopg://a@h:1/db") == "postgresql://a@h:1/db"


def test_a_plain_dsn_is_left_alone() -> None:
    assert _psycopg_dsn("postgresql://a@h:1/db") == "postgresql://a@h:1/db"


# --------------------------------------------------------------------------
# Entry point behaviour
# --------------------------------------------------------------------------


def test_missing_database_url_exits_with_a_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("ATLAS_DATABASE_URL", raising=False)
    assert main(["--prepare-only"]) == 2
    assert "ATLAS_DATABASE_URL is not set" in capsys.readouterr().err


def test_an_unreachable_database_fails_without_a_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A user sees a sentence, not a stack trace."""
    # Port 1 is reserved and nothing listens there.
    monkeypatch.setenv("ATLAS_DATABASE_URL", "postgresql+psycopg://atlas@127.0.0.1:1/atlas")
    assert main(["--prepare-only", "--db-timeout", "0.5"]) == 1
    err = capsys.readouterr().err
    assert "database not ready" in err
    assert "Traceback" not in err


# --------------------------------------------------------------------------
# Packaging configuration
# --------------------------------------------------------------------------

TAURI_CONF = REPO_ROOT / "apps" / "desktop" / "src-tauri" / "tauri.conf.json"


def test_tauri_config_is_valid_json() -> None:
    json.loads(TAURI_CONF.read_text(encoding="utf-8"))


def test_desktop_and_kernel_versions_agree() -> None:
    """Three files carry the version. They drift silently if untested."""
    from atlas_kernel.version import VERSION

    tauri = json.loads(TAURI_CONF.read_text(encoding="utf-8"))
    package = json.loads(
        (REPO_ROOT / "apps" / "desktop" / "package.json").read_text(encoding="utf-8")
    )
    assert tauri["version"] == VERSION
    assert package["version"] == VERSION

    cargo = (REPO_ROOT / "apps" / "desktop" / "src-tauri" / "Cargo.toml").read_text()
    assert f'version = "{VERSION}"' in cargo


def test_no_signing_identity_is_configured() -> None:
    """Alpha builds are unsigned, and no placeholder certificate is invented."""
    tauri = json.loads(TAURI_CONF.read_text(encoding="utf-8"))
    assert tauri["bundle"]["macOS"]["signingIdentity"] is None
    assert tauri["bundle"]["windows"]["certificateThumbprint"] is None


def test_installer_declares_the_licence() -> None:
    tauri = json.loads(TAURI_CONF.read_text(encoding="utf-8"))
    licence = (TAURI_CONF.parent / tauri["bundle"]["licenseFile"]).resolve()
    assert licence.exists(), f"{licence} referenced by tauri.conf.json is missing"
    assert "Business Source License" in licence.read_text(encoding="utf-8")


def test_packaging_artefacts_are_not_committed() -> None:
    """A 131 MB PostgreSQL tree must never reach git."""
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in (
        "apps/desktop/src-tauri/resources/postgres/",
        "apps/desktop/src-tauri/binaries/",
        "apps/desktop/src-tauri/target/",
    ):
        assert pattern in gitignore, f"{pattern} is not gitignored"


def test_release_workflow_builds_every_supported_platform() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    # Tauri cannot cross-compile, so each target needs its own native runner.
    for target in (
        "aarch64-apple-darwin",
        "x86_64-apple-darwin",
        "x86_64-unknown-linux-gnu",
        "x86_64-pc-windows-msvc",
    ):
        assert target in workflow, f"{target} is missing from the release matrix"
    assert "checksums.py generate" in workflow, "releases must publish checksums"
    assert "checksums.py verify" in workflow, "checksums must be verified before publishing"


def test_postgres_fetcher_pins_its_version() -> None:
    """An unpinned dependency makes a build unreproducible."""
    source = (REPO_ROOT / "infra" / "packaging" / "fetch_postgres.py").read_text(encoding="utf-8")
    assert 'POSTGRES_VERSION = "16.14.0"' in source


def test_pyinstaller_spec_copies_dependency_metadata() -> None:
    """Regression: without metadata a packaged Atlas reports itself degraded.

    The modules import and serve fine, but importlib.metadata cannot see them,
    so /health/report declares every dependency missing.
    """
    spec = (REPO_ROOT / "infra" / "packaging" / "atlas-kernel.spec").read_text(encoding="utf-8")
    assert "copy_metadata" in spec
    for distribution in ("fastapi", "sqlalchemy", "uvicorn", "httpx", "psycopg"):
        assert f'"{distribution}"' in spec
