"""The Hetzner target (M015 Phase A).

Proven end to end against a real box; these cover the parts that should not need
a server to check, and one that should not need a server to *fail*.

The property worth defending hardest is the one linking the two adapters: **a
build has the same version id wherever it goes.** That is what turns "the same
artifact is on both hosts" from an assertion into something checkable, and it is
the mechanism behind moving a customer between providers without a migration.
"""

from __future__ import annotations

import io
import subprocess
import tarfile

import pytest

from atlas_kernel.website.targets.base import DeploymentError
from atlas_kernel.website.targets.local import _version_id as local_version_id
from atlas_kernel.website.targets.ssh import (
    SshDirectoryTarget,
    _tarball,
    _version_id,
)

FILES = {
    "index.html": "<!doctype html><title>T</title><h1>T</h1>",
    "styles.css": "body{margin:0}",
    "about/index.html": "<!doctype html><title>About</title><h1>About</h1>",
}


def _target(**overrides) -> SshDirectoryTarget:
    payload = {
        "host": "box.test",
        "root": "/opt/atlas-sites/root",
        "base_url": "https://box.test:8791",
        "key_path": "/dev/null",
    }
    payload.update(overrides)
    return SshDirectoryTarget(**payload)


class TestVersionIdentityIsShared:
    def test_the_same_build_has_the_same_version_id_on_both_hosts(self) -> None:
        """Not a coincidence — it is the mechanism. Without it, "the same
        artifact is on Cloudflare and Hetzner" could only ever be asserted."""
        assert _version_id(FILES) == local_version_id(FILES)

    def test_a_different_build_has_a_different_id(self) -> None:
        changed = {**FILES, "styles.css": "body{margin:1px}"}
        assert _version_id(FILES) != _version_id(changed)

    def test_file_order_does_not_change_the_id(self) -> None:
        reordered = dict(reversed(list(FILES.items())))
        assert _version_id(reordered) == _version_id(FILES)


class TestTheArchiveIsDeterministic:
    def test_the_same_build_produces_identical_bytes(self) -> None:
        """An archive whose bytes depended on when it was made would break the
        one property this milestone rests on."""
        assert _tarball(FILES) == _tarball(FILES)

    def test_nothing_records_when_it_was_built(self) -> None:
        with tarfile.open(fileobj=io.BytesIO(_tarball(FILES)), mode="r:gz") as archive:
            members = archive.getmembers()
        assert members, "the archive is empty"
        assert all(member.mtime == 0 for member in members)
        assert all(member.uid == 0 and member.gid == 0 for member in members)
        assert all(member.mode == 0o644 for member in members)

    def test_every_file_survives_including_nested_ones(self) -> None:
        with tarfile.open(fileobj=io.BytesIO(_tarball(FILES)), mode="r:gz") as archive:
            names = sorted(member.name for member in archive.getmembers())
            extracted = {
                member.name: archive.extractfile(member).read().decode()  # type: ignore[union-attr]
                for member in archive.getmembers()
            }
        assert names == sorted(FILES)
        assert extracted == FILES


class TestPathSafety:
    """These paths become arguments to commands running as root on a real box."""

    @pytest.mark.parametrize(
        "path", ["../../etc/nginx/nginx.conf", "/etc/passwd", "a/../../b", "../"]
    )
    def test_a_build_cannot_escape_its_directory(self, path: str) -> None:
        with pytest.raises(DeploymentError, match="unsafe path"):
            _tarball({path: "x"})

    def test_a_slug_cannot_escape_either(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(subprocess, "run", _never_called)
        with pytest.raises(DeploymentError, match="unsafe path"):
            _target().publish("../elsewhere", FILES)


def _never_called(*args, **kwargs):  # pragma: no cover - the point is not reaching it
    raise AssertionError("ssh was invoked despite an unsafe path")


class _Completed:
    def __init__(self, returncode: int = 0, stdout: bytes = b"", stderr: bytes = b"") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestRemoteFailuresAreReported:
    def test_a_failing_command_becomes_a_deployment_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: _Completed(returncode=1, stderr=b"Permission denied (publickey)."),
        )
        with pytest.raises(DeploymentError, match="Permission denied"):
            _target().publish("site-x", FILES)

    def test_a_timeout_says_so_rather_than_hanging_forever(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="ssh", timeout=120)

        monkeypatch.setattr(subprocess, "run", timeout)
        with pytest.raises(DeploymentError, match="timed out"):
            _target().publish("site-x", FILES)

    def test_a_missing_ssh_binary_is_a_deployment_error_not_a_crash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def missing(*args, **kwargs):
            raise OSError("No such file or directory: 'ssh'")

        monkeypatch.setattr(subprocess, "run", missing)
        with pytest.raises(DeploymentError, match="could not run ssh"):
            _target().publish("site-x", FILES)

    def test_an_unreadable_version_reads_as_absent_rather_than_raising(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A missing file is a normal answer. Only a broken connection is an
        error, and `read` is used for inspection where None is meaningful."""
        monkeypatch.setattr(
            subprocess, "run", lambda *a, **k: _Completed(returncode=1, stderr=b"No such file")
        )
        assert _target().read("site-x", "v1") is None
        assert _target().live_version("site-x") is None


class TestTheCommandsAreTheRightShape:
    """The remote commands, without a remote.

    Checking the shape matters because the atomic swap is the difference between
    a visitor seeing the old site and seeing a 404.
    """

    def _capture(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        seen: list[str] = []

        def record(argv, **kwargs):
            seen.append(argv[-1])
            return _Completed()

        monkeypatch.setattr(subprocess, "run", record)
        return seen

    def test_publish_clears_the_directory_before_extracting(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = self._capture(monkeypatch)
        _target().publish("site-x", FILES)
        assert any("rm -rf" in command and "mkdir -p" in command for command in seen)
        assert any("tar -xzf -" in command for command in seen)

    def test_promotion_swaps_the_link_atomically(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen = self._capture(monkeypatch)
        _target().promote("site-x", "v1")
        command = " ".join(seen)
        assert "ln -sfn" in command
        assert "mv -Tf" in command
        assert "rm -f" not in command, "removing the link first leaves a 404 window"

    def test_promotion_checks_the_version_exists_first(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = self._capture(monkeypatch)
        _target().promote("site-x", "v1")
        assert any("test -d" in command for command in seen)

    def test_the_urls_follow_the_published_then_promoted_split(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._capture(monkeypatch)
        target = _target()
        published = target.publish("site-x", FILES)
        live = target.promote("site-x", published.id)
        assert published.preview_url == f"https://box.test:8791/site-x/versions/{published.id}/"
        assert live == "https://box.test:8791/site-x/"
        assert published.preview_url != live

    def test_removing_the_live_version_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Completed(stdout=b"versions/v1\n"))
        with pytest.raises(DeploymentError, match="is live"):
            _target().remove("site-x", "v1")
