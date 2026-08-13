"""How Google credentials are resolved, and how they are kept out of logs.

Two properties, and the second is the one that actually leaks in practice.

**Credentials are configured, never committed.** They resolve from the
environment or from a path outside the working tree. The default location is
deliberately not inside the repository: a secret stored in the repo is one
``git add -A`` away from being published, and that command gets run by tired
people at the end of long days.

**A secret must not be printable.** ``ClientSecrets`` is a dataclass, and a
dataclass prints its fields — so the default ``repr`` puts a live client secret
into every traceback, log line and debugger session that touches one. Exception
text is the most common way a secret escapes, and it escapes into exactly the
places people paste into issues and chat.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlas_kernel.media.publishers.google_oauth import (
    ClientSecrets,
    OAuthError,
    default_client_secrets_path,
)

INSTALLED = {"installed": {"client_id": "id-from-file", "client_secret": "secret-from-file"}}


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch):
    """No inherited configuration.

    Without this, a developer who has the real credentials exported would run a
    different test from CI — and the one that passes locally is the one nobody
    investigates.
    """
    for prefix in ("QEVIK_", "ATLAS_"):
        for name in (
            "GOOGLE_CLIENT_ID",
            "GOOGLE_CLIENT_SECRET",
            "GOOGLE_CLIENT_SECRETS_FILE",
        ):
            monkeypatch.delenv(f"{prefix}{name}", raising=False)


class TestResolutionOrder:
    def test_direct_environment_values_win(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("QEVIK_GOOGLE_CLIENT_ID", "id-from-env")
        monkeypatch.setenv("QEVIK_GOOGLE_CLIENT_SECRET", "secret-from-env")
        secrets = ClientSecrets.from_environment()
        assert secrets.client_id == "id-from-env"
        assert secrets.client_secret == "secret-from-env"

    def test_a_configured_path_is_read(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path = tmp_path / "client_secret.json"
        path.write_text(json.dumps(INSTALLED))
        monkeypatch.setenv("QEVIK_GOOGLE_CLIENT_SECRETS_FILE", str(path))
        assert ClientSecrets.from_environment().client_id == "id-from-file"

    def test_direct_values_beat_a_configured_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The most explicit source wins, so a container's env overrides a file
        that happens to be mounted."""
        path = tmp_path / "client_secret.json"
        path.write_text(json.dumps(INSTALLED))
        monkeypatch.setenv("QEVIK_GOOGLE_CLIENT_SECRETS_FILE", str(path))
        monkeypatch.setenv("QEVIK_GOOGLE_CLIENT_ID", "id-from-env")
        monkeypatch.setenv("QEVIK_GOOGLE_CLIENT_SECRET", "secret-from-env")
        assert ClientSecrets.from_environment().client_id == "id-from-env"

    def test_the_old_prefix_still_works(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The rename must not break a machine that is already configured."""
        monkeypatch.setenv("ATLAS_GOOGLE_CLIENT_ID", "id-legacy")
        monkeypatch.setenv("ATLAS_GOOGLE_CLIENT_SECRET", "secret-legacy")
        assert ClientSecrets.from_environment().client_id == "id-legacy"

    def test_the_new_prefix_wins_over_the_old(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ATLAS_GOOGLE_CLIENT_ID", "id-legacy")
        monkeypatch.setenv("ATLAS_GOOGLE_CLIENT_SECRET", "secret-legacy")
        monkeypatch.setenv("QEVIK_GOOGLE_CLIENT_ID", "id-new")
        monkeypatch.setenv("QEVIK_GOOGLE_CLIENT_SECRET", "secret-new")
        assert ClientSecrets.from_environment().client_id == "id-new"

    def test_an_exported_but_blank_variable_counts_as_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The usual result of a half-finished shell profile. Honouring it
        produces an authentication error that points at Google rather than at
        the shell, which is a long afternoon."""
        monkeypatch.setenv("QEVIK_GOOGLE_CLIENT_ID", "  ")
        monkeypatch.setenv("QEVIK_GOOGLE_CLIENT_SECRET", "")
        with pytest.raises(OAuthError, match="no Google client secrets configured"):
            ClientSecrets.from_environment()


class TestTheDefaultIsOutsideTheRepository:
    def test_the_default_path_is_not_in_the_working_tree(self) -> None:
        """The property that makes accidental commits impossible rather than
        merely discouraged."""
        default = default_client_secrets_path()
        repo = Path(__file__).resolve().parents[3]
        assert not default.resolve().is_relative_to(repo)
        assert ".qevik" in default.parts

    def test_a_missing_credential_says_what_to_do(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """An unconfigured credential should stop the caller with something
        actionable, not surface three frames later as an auth failure."""
        monkeypatch.setenv("QEVIK_GOOGLE_CLIENT_SECRETS_FILE", str(tmp_path / "absent.json"))
        with pytest.raises(OAuthError) as raised:
            ClientSecrets.from_environment()
        message = str(raised.value)
        assert "QEVIK_GOOGLE_CLIENT_ID" in message
        assert "QEVIK_GOOGLE_CLIENT_SECRETS_FILE" in message
        assert "Do not put it inside the repository" in message


class TestSecretsDoNotPrint:
    """The fixture value is deliberately not shaped like a real Google secret.

    Using Google's real live-secret prefix would prove nothing extra — redaction
    does not inspect the value — while permanently tripping GitHub push
    protection and every credential scanner pointed at this repository. The
    prefix is deliberately not written out anywhere in this file, including
    here. A test that blocks its own push is a test that gets deleted.
    """

    def test_repr_hides_the_secret(self) -> None:
        secrets = ClientSecrets(client_id="an-id", client_secret="fake-secret-must-not-be-printed")
        assert "fake-secret-must-not-be-printed" not in repr(secrets)
        assert "***" in repr(secrets)

    def test_str_hides_the_secret(self) -> None:
        secrets = ClientSecrets(client_id="an-id", client_secret="fake-secret-must-not-be-printed")
        assert "fake-secret-must-not-be-printed" not in str(secrets)

    def test_the_client_id_is_still_visible(self) -> None:
        """It is not a secret, and hiding it would make a misconfigured client
        undiagnosable — which is how a redaction rule gets removed."""
        assert "an-id" in repr(ClientSecrets(client_id="an-id", client_secret="s"))

    def test_a_secret_inside_an_exception_does_not_leak(self) -> None:
        """The path that actually leaks: something raises, the object is in the
        frame, and the traceback is pasted into an issue."""
        secrets = ClientSecrets(client_id="an-id", client_secret="fake-secret-must-not-be-printed")
        message = f"authentication failed for {secrets}"
        assert "fake-secret-must-not-be-printed" not in message

    def test_the_value_is_still_reachable_for_use(self) -> None:
        """Redaction must not make the credential unusable — a defence that
        breaks the feature gets deleted."""
        secrets = ClientSecrets(client_id="an-id", client_secret="real-value")
        assert secrets.client_secret == "real-value"


class TestGitIgnoresTheRealFilename:
    """A test rather than a note, because the filename Google issues is long,
    unusual, and easy to write a pattern that nearly matches."""

    def test_the_ignore_file_covers_googles_download_name(self) -> None:
        repo = Path(__file__).resolve().parents[3]
        patterns = (repo / ".gitignore").read_text()
        for pattern in ("client_secret*.json", "*.apps.googleusercontent.com.json", "*token.json"):
            assert pattern in patterns, f"{pattern} missing from .gitignore"
