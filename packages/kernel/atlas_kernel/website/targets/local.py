"""A directory a web server serves. The Hetzner shape.

Versioned directories and a ``current`` symlink is how a site is deployed to a
box, and it is the model this adapter implements literally:

.. code-block:: text

    <root>/<site>/versions/<version-id>/index.html   published, serving nobody
    <root>/<site>/current -> versions/<version-id>    what visitors get

Promotion is a symlink swap, which is atomic on POSIX — a visitor mid-request
gets the old version or the new one and never a half-written directory. That
property is the reason this shape is worth copying rather than replacing with
"delete and re-upload".

The adapter assumes **a web server is in front of the root**, because that is
what a real deployment is. It does not start one: a target that ran its own
HTTP server would be a different thing in production than in a test, and the
whole value of a local target is that it is the same thing.

Deliberately no cleanup policy. Old versions are what rollback promotes, and a
target that decided retention for itself would put a policy in an adapter.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from .base import DeploymentError, PublishedVersion

#: Directory holding every published version of a site.
VERSIONS_DIR = "versions"
#: Symlink pointing at whichever version is live.
CURRENT_LINK = "current"


def _safe_relative(path: str) -> Path:
    """Reject anything that would escape the site directory.

    A build's file paths are data, and data that becomes a filesystem path is
    worth checking however trusted the source feels: ``../../etc/nginx`` is a
    valid dictionary key.
    """
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise DeploymentError(f"unsafe path in build: {path!r}")
    return candidate


class LocalDirectoryTarget:
    """Publishes to versioned directories under a root.

    ``base_url`` is where the web server in front of ``root`` serves from. It is
    configuration rather than something the adapter can discover, and getting it
    wrong means the gate inspects the wrong thing — so it is required rather
    than defaulted.
    """

    def __init__(self, root: Path, *, base_url: str, name: str = "local") -> None:
        self._root = Path(root)
        self._base_url = base_url.rstrip("/")
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def root(self) -> Path:
        return self._root

    # -- paths ------------------------------------------------------------

    def _site_dir(self, site_slug: str) -> Path:
        return self._root / _safe_relative(site_slug)

    def _version_dir(self, site_slug: str, version_id: str) -> Path:
        return self._site_dir(site_slug) / VERSIONS_DIR / _safe_relative(version_id)

    def _current_link(self, site_slug: str) -> Path:
        return self._site_dir(site_slug) / CURRENT_LINK

    # -- the interface ----------------------------------------------------

    def publish(self, site_slug: str, files: dict[str, str]) -> PublishedVersion:
        version_id = _version_id(files)
        directory = self._version_dir(site_slug, version_id)

        # Republishing an identical artifact is not an error. Rollback works by
        # republishing from Atlas's stored build, so this path runs often and
        # must be idempotent rather than clever.
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True, exist_ok=True)

        for path, body in files.items():
            destination = directory / _safe_relative(path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(body, encoding="utf-8")

        return PublishedVersion(
            id=version_id,
            preview_url=f"{self._base_url}/{site_slug}/{VERSIONS_DIR}/{version_id}/",
            detail=f"published {len(files)} files to {directory}",
        )

    def promote(self, site_slug: str, version_id: str) -> str:
        directory = self._version_dir(site_slug, version_id)
        if not directory.is_dir():
            raise DeploymentError(
                f"version {version_id} is not published for {site_slug}; publish before promoting"
            )

        link = self._current_link(site_slug)
        # Swap through a temporary name so the switch is atomic. Removing the
        # old link first would leave a window where the site is a 404, which is
        # exactly the moment a visitor arrives.
        staging = link.with_name(f".{CURRENT_LINK}.staging")
        if staging.exists() or staging.is_symlink():
            staging.unlink()
        staging.symlink_to(Path(VERSIONS_DIR) / version_id, target_is_directory=True)
        os.replace(staging, link)

        return f"{self._base_url}/{site_slug}/"

    def remove(self, site_slug: str, version_id: str) -> None:
        """Delete a published version.

        Refuses to remove the live one. Atlas can always republish from its own
        stored build, so this is not data loss — but a site going dark because
        of a cleanup pass is an outage, and outages during housekeeping are the
        avoidable kind.
        """
        if self.live_version(site_slug) == version_id:
            raise DeploymentError(f"{version_id} is live for {site_slug}; promote another first")
        directory = self._version_dir(site_slug, version_id)
        if directory.is_dir():
            shutil.rmtree(directory)

    # -- introspection, for tests and diagnostics -------------------------

    def live_version(self, site_slug: str) -> str | None:
        link = self._current_link(site_slug)
        if not link.is_symlink():
            return None
        return Path(os.readlink(link)).name

    def read(self, site_slug: str, version_id: str, path: str = "index.html") -> str | None:
        destination = self._version_dir(site_slug, version_id) / _safe_relative(path)
        if not destination.is_file():
            return None
        return destination.read_text(encoding="utf-8")


def _version_id(files: dict[str, str]) -> str:
    """Content-addressed, so publishing the same artifact twice is the same version.

    Matters for rollback: republishing a build Atlas already holds must land on
    the version that is already there rather than accumulating a new directory
    every time someone reverts.
    """
    import hashlib

    material = "\x1f".join(f"{path}\x00{files[path]}" for path in sorted(files))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
