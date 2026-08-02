"""Version metadata.

One place defines what version Atlas is. Everything else -- the API, the
diagnostics export, the desktop title bar, the update check, the telemetry
ping -- reads it from here. A release is cut by editing ``VERSION`` and
nothing else.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import date
from typing import Any

#: The single source of truth. Semantic version, optionally with a pre-release
#: suffix. Update this and only this to cut a release.
VERSION = "0.12.0-alpha.1"

#: Human name for the release, shown in the welcome screen and release notes.
RELEASE_NAME = "Public Alpha"

#: Release channel. "alpha" and "beta" tell the update checker to consider
#: pre-releases; "stable" tells it to ignore them.
CHANNEL = "alpha"

#: The Business Source License change date, mirrored from LICENSE so the
#: application can state it without parsing a text file.
LICENSE_ID = "BUSL-1.1"
LICENSE_CHANGE_DATE = date(2030, 8, 3)
LICENSE_CHANGE_TO = "Apache-2.0"

_SEMVER = re.compile(
    r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:-(?P<pre>[0-9A-Za-z.-]+))?(?:\+(?P<build>[0-9A-Za-z.-]+))?$"
)


@dataclass(frozen=True)
class SemanticVersion:
    """A parsed version that can be compared with another."""

    major: int
    minor: int
    patch: int
    prerelease: tuple[str | int, ...] = field(default=())

    @property
    def is_prerelease(self) -> bool:
        return bool(self.prerelease)

    def _key(self) -> tuple[Any, ...]:
        # A release outranks any pre-release of the same numbers, so the
        # absence of a pre-release sorts *higher*: 1.0.0 > 1.0.0-rc.1.
        return (
            self.major,
            self.minor,
            self.patch,
            1 if not self.prerelease else 0,
            self.prerelease,
        )

    def __lt__(self, other: SemanticVersion) -> bool:
        return self._key() < other._key()

    def __le__(self, other: SemanticVersion) -> bool:
        return self._key() <= other._key()

    def __gt__(self, other: SemanticVersion) -> bool:
        return self._key() > other._key()

    def __ge__(self, other: SemanticVersion) -> bool:
        return self._key() >= other._key()

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            base += "-" + ".".join(str(p) for p in self.prerelease)
        return base


def parse_version(value: str) -> SemanticVersion:
    """Parse a semantic version string.

    Raises ``ValueError`` on anything unparseable rather than guessing, so a
    malformed version from an update feed is rejected instead of silently
    comparing as zero.
    """
    match = _SEMVER.match(value.strip().lstrip("v"))
    if match is None:
        raise ValueError(f"not a semantic version: {value!r}")
    pre_raw = match.group("pre")
    pre: tuple[str | int, ...] = ()
    if pre_raw:
        # Numeric identifiers compare numerically, so rc.9 precedes rc.10.
        pre = tuple(int(p) if p.isdigit() else p for p in pre_raw.split("."))
    return SemanticVersion(
        major=int(match.group("major")),
        minor=int(match.group("minor")),
        patch=int(match.group("patch")),
        prerelease=pre,
    )


def build_commit() -> str | None:
    """The commit this build came from, or None if it cannot be determined.

    Release builds get it from ``ATLAS_BUILD_COMMIT``, injected by CI. A
    developer running from a checkout gets it from git. A user running an
    installed copy has neither, and None is the honest answer.
    """
    injected = os.environ.get("ATLAS_BUILD_COMMIT", "").strip()
    if injected:
        return injected
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    commit = result.stdout.strip()
    return commit if result.returncode == 0 and commit else None


def build_date() -> str | None:
    """Build date as an ISO string, injected by CI. None outside a release."""
    return os.environ.get("ATLAS_BUILD_DATE", "").strip() or None


def version_report() -> dict[str, Any]:
    """Everything about this build, for /version and diagnostics."""
    parsed = parse_version(VERSION)
    return {
        "version": VERSION,
        "release_name": RELEASE_NAME,
        "channel": CHANNEL,
        "is_prerelease": parsed.is_prerelease,
        "major": parsed.major,
        "minor": parsed.minor,
        "patch": parsed.patch,
        "build_commit": build_commit(),
        "build_date": build_date(),
        "license": LICENSE_ID,
        "license_change_date": LICENSE_CHANGE_DATE.isoformat(),
        "license_change_to": LICENSE_CHANGE_TO,
    }
