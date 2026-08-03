"""Putting a finished rendition somewhere real.

The seam between "Atlas made a video" and "the world can see it". A publisher
takes a finished file and some metadata and hands back a receipt; it does not
know what a scene is, how the video was assembled, or that a dependency graph
exists.

One rule is enforced here rather than left to callers: **Atlas will not publish
publicly.** Not as a default that a config typo can flip -- as a refusal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .models import Visibility


class PublishError(RuntimeError):
    """A publication could not be completed."""


class PublicVisibilityRefused(PublishError):
    """Someone asked for a public upload.

    Its own type, and a refusal rather than a clamp. Silently downgrading to
    private would be worse: the caller would believe it had published, and the
    disagreement would only surface when an audience did not arrive.
    """


def assert_not_public(visibility: Visibility) -> None:
    """The guard, in one place so no publisher can forget it."""
    if visibility is Visibility.PUBLIC:
        raise PublicVisibilityRefused(
            "Atlas does not publish publicly. The milestone publishes to a private "
            "test channel, and making something public is a decision a person takes "
            "on the platform, not one Atlas takes on their behalf."
        )


@dataclass
class PublishRequest:
    """A finished artefact and how it should appear."""

    media_path: Path
    title: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    visibility: Visibility = Visibility.PRIVATE
    thumbnail_path: Path | None = None
    #: Timed text, when the platform accepts a sidecar. A caption track that can
    #: be turned off, translated and read by search beats burned-in pixels.
    captions_path: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PublishReceipt:
    """What the platform said."""

    remote_id: str
    remote_url: str | None = None
    visibility: Visibility = Visibility.PRIVATE
    #: Whatever the platform reported back, kept verbatim for diagnosis.
    raw: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Publisher(Protocol):
    platform: str

    def publish(self, request: PublishRequest) -> PublishReceipt: ...


class RecordingPublisher:
    """A publisher that records what it was asked to do and uploads nothing.

    Used until real credentials exist, and in tests. It still enforces the
    visibility refusal and still requires the file to be there, so the code path
    exercised is the real one minus the network.
    """

    platform = "recording"

    def __init__(self) -> None:
        self.published: list[PublishRequest] = []

    def publish(self, request: PublishRequest) -> PublishReceipt:
        assert_not_public(request.visibility)
        if not request.media_path.exists():
            raise PublishError(f"nothing to publish at {request.media_path}")

        self.published.append(request)
        identifier = f"recorded-{len(self.published):04d}"
        return PublishReceipt(
            remote_id=identifier,
            remote_url=None,
            visibility=request.visibility,
            raw={"recorded": True, "title": request.title},
        )
