"""Content and rendering entities for the Media Factory.

Read ``docs/VIDEO_FACTORY.md`` before changing anything here. The split between
the content layer and the rendering layer is load-bearing, and the cheapest time
to get it wrong is now.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid4())


# ---------------------------------------------------------------------------
# Shared status
# ---------------------------------------------------------------------------


class WorkStatus(StrEnum):
    """Lifecycle shared by anything that is produced rather than authored."""

    PENDING = "pending"
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"
    STALE = "stale"


# ---------------------------------------------------------------------------
# Content layer — medium-agnostic
#
# Nothing below this heading may reference video, audio, resolution, codecs,
# providers, recipes or assets. If a field only makes sense for one output form,
# it belongs on a Rendition or a SceneRender instead.
# ---------------------------------------------------------------------------


class Series(BaseModel):
    """A long-lived body of related episodes. Every episode belongs to one.

    Named ``Series`` rather than ``Campaign`` because Atlas is meant to run
    media properties for years, and a campaign is by definition something that
    ends. ``Series``/``Episode`` is also the pairing every reader already knows.

    Not called ``Studio``: that word is taken by Atlas's own architecture, where
    a studio is one of the six capability plugins. Not called ``Channel``
    either -- a series *has* a channel (below) and may eventually publish the
    same episode to several, so the two are not the same thing.

    If a brand ever needs to own several series, ``Brand`` becomes a parent of
    this. That is an additive change; renaming this later would not be.

    Milestone 013 creates exactly one implicitly and offers no way to manage
    them. It exists so an episode has somewhere to belong other than nowhere.
    """

    id: str = Field(default_factory=_new_id)
    name: str
    description: str = ""
    #: Where episodes in this series publish by default. A platform handle,
    #: not credentials -- secrets never live in the domain model.
    default_channel: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)


class Episode(BaseModel):
    """One unit of content: the thing a person would name."""

    id: str = Field(default_factory=_new_id)
    series_id: str
    #: What was asked for, in the operator's own words.
    brief: str
    title: str = ""
    summary: str = ""
    status: WorkStatus = WorkStatus.PENDING
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class Script(BaseModel):
    """A written treatment of an episode, at a point in time.

    Versioned because rewriting is normal, and because a rendition has to be
    able to say which version it was built from. Superseding a script must never
    silently invalidate a video that already shipped.
    """

    id: str = Field(default_factory=_new_id)
    episode_id: str
    version: int = 1
    #: How this script came to exist -- recipe name, model id, or "human".
    authored_by: str = "human"
    notes: str = ""
    created_at: datetime = Field(default_factory=_now)

    @field_validator("version")
    @classmethod
    def _version_starts_at_one(cls, value: int) -> int:
        if value < 1:
            raise ValueError("script version starts at 1")
        return value


class Scene(BaseModel):
    """A narrative beat. The unit of *authoring*.

    Deliberately free of media fields. A scene says what happens and what is
    said; it does not know whether it will become a video, a paragraph or a
    podcast segment. The rendered artefact for a scene is a ``SceneRender``.
    """

    id: str = Field(default_factory=_new_id)
    script_id: str
    #: Zero-based position in the script.
    index: int
    heading: str = ""
    #: The words to be spoken. Narration for video, body text for a post.
    narration: str = ""
    #: What should be seen or evoked. A prompt for a renderer that wants one;
    #: art direction for a human. Not a provider payload.
    visual_direction: str = ""
    #: Roughly how long this beat should run. Renderers may round to their own
    #: frame or sample boundaries.
    target_seconds: float = 5.0
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("index")
    @classmethod
    def _index_is_not_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("scene index is zero-based and cannot be negative")
        return value

    @field_validator("target_seconds")
    @classmethod
    def _duration_is_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("target_seconds must be positive")
        return value

    def content_fingerprint(self) -> str:
        """Identity of what this scene *says*, for staleness checks.

        Only authored content participates. Editing the narration should
        invalidate a cut; renaming metadata should not.
        """
        material = f"{self.index}\x1f{self.heading}\x1f{self.narration}\x1f{self.visual_direction}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Rendering layer — medium-specific
# ---------------------------------------------------------------------------


class RenditionKind(StrEnum):
    """Output forms.

    Only ``VIDEO_1080P`` is implemented in M013. The others are named because
    naming them costs nothing and proves the seam holds -- not because anything
    builds them. Do not implement one without a milestone that asks for it.
    """

    VIDEO_1080P = "video/1080p"
    VIDEO_SHORT = "video/short"
    THUMBNAIL_SET = "image/thumbnails"
    BLOG_POST = "text/blog"
    PODCAST = "audio/podcast"


class Rendition(BaseModel):
    """One rendered form of an episode.

    ``scene_fingerprint`` records the content this cut was assembled from. When
    it stops matching the script's current scenes the cut is stale, and Atlas
    says so rather than shipping a video that no longer matches its own script.
    """

    id: str = Field(default_factory=_new_id)
    episode_id: str
    script_id: str
    kind: RenditionKind = RenditionKind.VIDEO_1080P
    status: WorkStatus = WorkStatus.PENDING
    #: The assembled artefact, once there is one.
    asset_id: str | None = None
    #: Fingerprint of the scene content this cut was built from.
    scene_fingerprint: str = ""
    #: How it was made, for reproducibility: ffmpeg arguments, recipe ids.
    build_metadata: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    def is_stale_against(self, scenes: list[Scene]) -> bool:
        """True when the scenes have moved on since this cut was built."""
        if not self.scene_fingerprint:
            return False
        return self.scene_fingerprint != fingerprint_scenes(scenes)


class SceneRender(BaseModel):
    """The rendered media for one scene, within one rendition.

    The unit of *work*: one job, retried on its own. Partial regeneration
    re-runs one of these and leaves its ``Scene`` and every sibling untouched.
    """

    id: str = Field(default_factory=_new_id)
    rendition_id: str
    scene_id: str
    #: Denormalised so renders can be ordered without loading the script.
    index: int
    status: WorkStatus = WorkStatus.PENDING
    provider: str | None = None
    recipe_id: str | None = None
    #: The visual for this scene.
    media_asset_id: str | None = None
    #: The narration for this scene, rendered separately so a re-voice does not
    #: force a re-render of the picture.
    audio_asset_id: str | None = None
    duration_seconds: float | None = None
    #: The scene content this render was produced from, so a single stale scene
    #: can be identified rather than invalidating the whole rendition.
    source_fingerprint: str = ""
    job_id: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


# ---------------------------------------------------------------------------
# Publishing layer
# ---------------------------------------------------------------------------


class Visibility(StrEnum):
    """Publication visibility.

    ``PUBLIC`` is defined because the platform has it and refusing to name it
    would not make it go away. Atlas will not select it: see
    ``publish.assert_not_public``. The MVP publishes private or unlisted only.
    """

    PRIVATE = "private"
    UNLISTED = "unlisted"
    PUBLIC = "public"


class PublicationStatus(StrEnum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    UPLOADING = "uploading"
    PUBLISHED = "published"
    REJECTED = "rejected"
    FAILED = "failed"


class Publication(BaseModel):
    """One attempt to put a rendition somewhere real.

    Separate from ``Rendition`` because uploads are retried, and because the
    approval that authorised a specific upload has to remain auditable long
    after the upload itself succeeded or failed.
    """

    model_config = ConfigDict(use_enum_values=False)

    id: str = Field(default_factory=_new_id)
    rendition_id: str
    platform: str = "youtube"
    #: The approval that authorised this upload. Re-read and re-checked at
    #: upload time; never inferred from control flow.
    approval_id: str | None = None
    visibility: Visibility = Visibility.PRIVATE
    title: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    thumbnail_asset_id: str | None = None
    #: Set once the platform has accepted it.
    remote_id: str | None = None
    remote_url: str | None = None
    status: PublicationStatus = PublicationStatus.PENDING_APPROVAL
    error: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


# ---------------------------------------------------------------------------


def fingerprint_scenes(scenes: list[Scene]) -> str:
    """A stable identity for an ordered set of scene *contents*.

    Used to tell a current cut from a stale one. Ordering is normalised on the
    scene index so that a reordering is a real change while a database returning
    rows in a different order is not.
    """
    ordered = sorted(scenes, key=lambda scene: scene.index)
    joined = "\x1e".join(scene.content_fingerprint() for scene in ordered)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]
