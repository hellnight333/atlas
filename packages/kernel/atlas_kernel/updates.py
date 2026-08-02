"""Update checking -- informative, never coercive.

Atlas tells you an update exists and where to get it. It does not download,
install, restart, or nag. There is no auto-updater and no silent update
channel, because an AI operating system that can replace its own code without
being asked is a security property nobody agreed to.

:class:`UpdateService` exposes the hooks a future auto-updater would need
(:meth:`UpdateService.check`, :meth:`UpdateService.download_url_for`) without
implementing one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from atlas_kernel.logging_setup import get_logger
from atlas_kernel.version import CHANNEL, VERSION, SemanticVersion, parse_version

logger = get_logger("updates")

#: Where releases are published. Read-only, unauthenticated, and only ever
#: contacted when the operator asks for a check.
RELEASE_FEED_URL = "https://api.github.com/repos/hellnight333/atlas/releases"

#: Where a human goes to read about and download a release.
RELEASE_PAGE_URL = "https://github.com/hellnight333/atlas/releases"


@dataclass(frozen=True)
class Release:
    """One published release."""

    version: str
    name: str
    url: str
    published_at: str | None = None
    prerelease: bool = False
    notes: str | None = None
    assets: tuple[dict[str, Any], ...] = ()

    def parsed(self) -> SemanticVersion | None:
        try:
            return parse_version(self.version)
        except ValueError:
            # A tag that is not a semantic version is not a release we can
            # reason about. Ignoring it beats crashing the update check.
            return None


@dataclass(frozen=True)
class UpdateCheck:
    """The result of asking whether an update exists."""

    current_version: str
    latest_version: str | None
    update_available: bool
    checked_at: str
    channel: str
    release: Release | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_version": self.current_version,
            "latest_version": self.latest_version,
            "update_available": self.update_available,
            "checked_at": self.checked_at,
            "channel": self.channel,
            "release_page": RELEASE_PAGE_URL,
            "mandatory": False,
            "auto_update": False,
            "error": self.error,
            "release": (
                {
                    "version": self.release.version,
                    "name": self.release.name,
                    "url": self.release.url,
                    "published_at": self.release.published_at,
                    "prerelease": self.release.prerelease,
                    "notes": self.release.notes,
                    "assets": [
                        {
                            "name": a.get("name"),
                            "url": a.get("browser_download_url"),
                            "size": a.get("size"),
                        }
                        for a in self.release.assets
                    ],
                }
                if self.release
                else None
            ),
        }


class ReleaseFeed(Protocol):
    """Supplies published releases. Injected so a check is testable offline."""

    def fetch(self) -> list[Release]: ...


class StaticFeed:
    """A fixed list. The default, so no network call happens unasked."""

    def __init__(self, releases: list[Release] | None = None) -> None:
        self._releases = releases or []

    def fetch(self) -> list[Release]:
        return list(self._releases)


class GitHubReleaseFeed:
    """Reads the public GitHub releases API.

    Constructed only when the operator has asked for an online check.
    """

    def __init__(self, url: str = RELEASE_FEED_URL, timeout: float = 10.0) -> None:
        self.url = url
        self.timeout = timeout

    def fetch(self) -> list[Release]:
        import httpx

        response = httpx.get(
            self.url,
            timeout=self.timeout,
            headers={"Accept": "application/vnd.github+json"},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("release feed did not return a list")
        return [
            Release(
                version=str(item.get("tag_name", "")),
                name=str(item.get("name") or item.get("tag_name") or ""),
                url=str(item.get("html_url", RELEASE_PAGE_URL)),
                published_at=item.get("published_at"),
                prerelease=bool(item.get("prerelease", False)),
                notes=item.get("body"),
                assets=tuple(item.get("assets") or ()),
            )
            for item in payload
            if not item.get("draft", False)
        ]


class UpdateService:
    """Answers 'is there a newer Atlas?' and nothing more."""

    def __init__(
        self,
        feed: ReleaseFeed | None = None,
        current_version: str = VERSION,
        channel: str = CHANNEL,
    ) -> None:
        self._feed = feed or StaticFeed()
        self._current = current_version
        self._channel = channel

    @property
    def accepts_prereleases(self) -> bool:
        """A stable install ignores pre-releases; alpha and beta see them."""
        return self._channel in ("alpha", "beta")

    def _candidates(self, releases: list[Release]) -> list[tuple[SemanticVersion, Release]]:
        out: list[tuple[SemanticVersion, Release]] = []
        for release in releases:
            parsed = release.parsed()
            if parsed is None:
                continue
            if parsed.is_prerelease and not self.accepts_prereleases:
                continue
            out.append((parsed, release))
        return sorted(out, key=lambda pair: pair[0])

    def check(self, now: datetime | None = None) -> UpdateCheck:
        """Look for a newer release. Never raises."""
        checked_at = (now or datetime.now(UTC)).isoformat()
        try:
            current = parse_version(self._current)
        except ValueError as exc:
            return UpdateCheck(
                current_version=self._current,
                latest_version=None,
                update_available=False,
                checked_at=checked_at,
                channel=self._channel,
                error=f"current version is unparseable: {exc}",
            )

        try:
            releases = self._feed.fetch()
        except Exception as exc:  # noqa: BLE001 - an update check reports, never crashes
            logger.warning("update check failed", extra={"reason": str(exc)})
            return UpdateCheck(
                current_version=self._current,
                latest_version=None,
                update_available=False,
                checked_at=checked_at,
                channel=self._channel,
                error=str(exc),
            )

        candidates = self._candidates(releases)
        if not candidates:
            return UpdateCheck(
                current_version=self._current,
                latest_version=None,
                update_available=False,
                checked_at=checked_at,
                channel=self._channel,
            )

        latest_parsed, latest_release = candidates[-1]
        return UpdateCheck(
            current_version=self._current,
            latest_version=str(latest_parsed),
            update_available=latest_parsed > current,
            checked_at=checked_at,
            channel=self._channel,
            release=latest_release,
        )

    def download_url_for(self, platform_key: str, result: UpdateCheck | None = None) -> str | None:
        """The asset URL for a platform, or None.

        A future auto-updater would call this. Today it exists so the UI can
        offer the right download instead of a generic releases page.
        """
        check = result or self.check()
        if check.release is None:
            return None
        needle = platform_key.lower()
        for asset in check.release.assets:
            name = str(asset.get("name", "")).lower()
            if needle in name:
                url = asset.get("browser_download_url")
                return str(url) if url else None
        return None
