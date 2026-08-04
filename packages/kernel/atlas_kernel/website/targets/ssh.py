"""A real box over SSH. The Hetzner target.

Identical in shape to ``LocalDirectoryTarget`` — versioned directories and an
atomic symlink swap — which is the point rather than a coincidence. The local
target is this one with the network removed, so anything proved against it holds
here, and the two together are why the interface can be trusted not to have
encoded one host's mechanics.

.. code-block:: text

    <root>/<site>/versions/<version-id>/index.html   published, serving nobody
    <root>/<site>/current -> versions/<version-id>    what visitors get

Uses ``ssh`` and a piped tar rather than a Python SSH library. That is a
deliberate choice and not laziness: it adds no dependency, it is exactly how a
person deploys to a box, and one piped tar is a single round trip where
file-by-file writes are one per file. A site with forty assets over a slow link
is the difference between one second and forty.

**Nothing here touches a web server's configuration.** Publishing and promoting
move files and a symlink; whatever serves ``<root>`` is somebody else's
concern and is expected to already exist. A deployment adapter that edited a
reverse proxy fronting other people's production sites would be a deployment
adapter with a blast radius.
"""

from __future__ import annotations

import hashlib
import io
import subprocess
import tarfile
from pathlib import Path

from .base import DeploymentError, PublishedVersion

#: Long enough for a slow link and a large-ish site, short enough that a hung
#: connection surfaces as an error rather than a stuck deployment.
SSH_TIMEOUT_SECONDS = 120


def _safe_relative(path: str) -> Path:
    """Reject anything that would escape the site directory.

    Matters more here than locally: these paths become arguments to commands
    running as root on a real server.
    """
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise DeploymentError(f"unsafe path in build: {path!r}")
    return candidate


def _version_id(files: dict[str, str]) -> str:
    """Content-addressed, so republishing an artifact lands on the same version.

    Identical to the local target's rule, so a build has the same version id
    wherever it goes — which makes "the same artifact is on both hosts"
    checkable rather than merely asserted.
    """
    material = "\x1f".join(f"{path}\x00{files[path]}" for path in sorted(files))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _tarball(files: dict[str, str]) -> bytes:
    """A deterministic tar of the build.

    Every timestamp, uid, gid and mode is fixed. An archive whose bytes depended
    on when it was made would break the one property this milestone rests on —
    that the same build produces the same artifact, verifiably, anywhere.
    """
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz", compresslevel=6) as archive:
        for path in sorted(files):
            body = files[path].encode("utf-8")
            info = tarfile.TarInfo(name=str(_safe_relative(path)))
            info.size = len(body)
            info.mtime = 0
            info.mode = 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            archive.addfile(info, io.BytesIO(body))
    return buffer.getvalue()


class SshDirectoryTarget:
    """Publishes to versioned directories on a remote host over SSH."""

    def __init__(
        self,
        *,
        host: str,
        root: str,
        base_url: str,
        user: str = "root",
        key_path: str | None = None,
        port: int = 22,
        name: str = "hetzner",
    ) -> None:
        self._host = host
        self._root = root.rstrip("/")
        self._base_url = base_url.rstrip("/")
        self._user = user
        self._key_path = key_path
        self._port = port
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def root(self) -> str:
        return self._root

    def _ssh_command(self) -> list[str]:
        command = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            f"ConnectTimeout={min(30, SSH_TIMEOUT_SECONDS)}",
            "-p",
            str(self._port),
        ]
        if self._key_path:
            command += ["-i", self._key_path]
        return [*command, f"{self._user}@{self._host}"]

    def _run(self, remote: str, stdin: bytes | None = None) -> str:
        try:
            completed = subprocess.run(  # noqa: S603 - fixed argv, no shell on our side
                [*self._ssh_command(), remote],
                input=stdin,
                capture_output=True,
                timeout=SSH_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise DeploymentError(f"ssh to {self._host} timed out: {error}") from error
        except OSError as error:
            raise DeploymentError(f"could not run ssh to {self._host}: {error}") from error

        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", "replace").strip()
            raise DeploymentError(
                f"ssh to {self._host} failed ({completed.returncode}): {detail[:400]}"
            )
        return completed.stdout.decode("utf-8", "replace")

    # -- the interface ----------------------------------------------------

    def publish(self, site_slug: str, files: dict[str, str]) -> PublishedVersion:
        slug = str(_safe_relative(site_slug))
        version_id = _version_id(files)
        directory = f"{self._root}/{slug}/versions/{version_id}"

        # Removed before extraction so a republish is a clean write rather than
        # a merge over whatever happened to be there. Rollback republishes from
        # Atlas's stored build, so this path runs often.
        self._run(f"rm -rf {directory!r} && mkdir -p {directory!r}")
        self._run(f"tar -xzf - -C {directory!r}", stdin=_tarball(files))

        return PublishedVersion(
            id=version_id,
            preview_url=f"{self._base_url}/{slug}/versions/{version_id}/",
            detail=f"published {len(files)} files to {self._host}:{directory}",
        )

    def promote(self, site_slug: str, version_id: str) -> str:
        slug = str(_safe_relative(site_slug))
        version = str(_safe_relative(version_id))
        site_dir = f"{self._root}/{slug}"

        # `ln -sfn` into a staging name then `mv -Tf` is the atomic swap. Doing
        # it as `rm current && ln -s` leaves a window where the site is a 404,
        # which is exactly the moment a visitor arrives.
        self._run(
            f"test -d {site_dir}/versions/{version} && "
            f"ln -sfn versions/{version} {site_dir}/.current.staging && "
            f"mv -Tf {site_dir}/.current.staging {site_dir}/current"
        )
        return f"{self._base_url}/{slug}/"

    def remove(self, site_slug: str, version_id: str) -> None:
        slug = str(_safe_relative(site_slug))
        version = str(_safe_relative(version_id))
        if self.live_version(site_slug) == version:
            raise DeploymentError(f"{version} is live for {slug}; promote another first")
        self._run(f"rm -rf {self._root}/{slug}/versions/{version}")

    # -- introspection ----------------------------------------------------

    def live_version(self, site_slug: str) -> str | None:
        slug = str(_safe_relative(site_slug))
        try:
            output = self._run(f"readlink {self._root}/{slug}/current || true")
        except DeploymentError:
            return None
        target = output.strip()
        return Path(target).name if target else None

    def read(self, site_slug: str, version_id: str, path: str = "index.html") -> str | None:
        slug = str(_safe_relative(site_slug))
        version = str(_safe_relative(version_id))
        target = f"{self._root}/{slug}/versions/{version}/{_safe_relative(path)}"
        try:
            return self._run(f"cat {target!r}")
        except DeploymentError:
            return None
