"""What every assembler has in common, which is less than it looks.

An assembler takes an ordered set of scenes, each with whatever was rendered for
it, and produces one finished artefact. That sentence is true of a video, a
podcast episode, a thumbnail set, a blog post and a landing page, which is
exactly why nothing here mentions frames, codecs, resolution or ffmpeg.

The rule that keeps it that way: **a field only one output form needs does not
belong in this module.** It goes in that assembler's ``options``, which nothing
else reads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ..models import Rendition, RenditionKind, Scene, SceneRender


class AssemblyError(RuntimeError):
    """A rendition could not be assembled from what it was given."""


class NoAssemblerAvailable(AssemblyError):
    """Nothing is registered for this rendition kind.

    Its own type because it is a configuration gap rather than a media failure:
    "no assembler for text/blog" is actionable, "assembly failed" is not.
    """


@dataclass(frozen=True)
class SceneMaterial:
    """One scene, and whatever exists for it so far.

    Both paths are optional on purpose. An assembler that needs a picture says
    so; one that only needs the words -- a blog post, a newsletter -- reads the
    scene and ignores the rest.
    """

    scene: Scene
    render: SceneRender | None = None
    #: The primary rendered artefact for this scene, if there is one.
    media_path: Path | None = None
    #: Spoken narration for this scene, if there is any.
    audio_path: Path | None = None

    @property
    def index(self) -> int:
        return self.scene.index


@dataclass
class AssemblyRequest:
    rendition: Rendition
    materials: list[SceneMaterial]
    output: Path
    #: A bed track for the whole piece, when one applies.
    music_path: Path | None = None
    #: Assembler-specific settings. Deliberately opaque here: this is where
    #: "burn subtitles" or "crossfade for 0.5s" lives, and where a future blog
    #: assembler will put "heading level", without either learning about the
    #: other.
    options: dict[str, Any] = field(default_factory=dict)

    def ordered(self) -> list[SceneMaterial]:
        return sorted(self.materials, key=lambda material: material.index)


@dataclass
class AssemblyResult:
    output: Path
    #: Meaningful for time-based output; None for a blog post or a thumbnail.
    duration_seconds: float | None = None
    #: How it was built, for reproducibility. Lands on Rendition.build_metadata.
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Assembler(Protocol):
    """Turns scenes into one finished rendition."""

    kind: RenditionKind

    def assemble(self, request: AssemblyRequest) -> AssemblyResult: ...


class AssemblerRegistry:
    """Which assembler builds which kind of rendition.

    The point of the indirection: a caller says "assemble this rendition" and
    never asks what kind it is. Adding podcasts later is a registration, not a
    branch in a service.
    """

    def __init__(self) -> None:
        self._by_kind: dict[RenditionKind, Assembler] = {}

    def register(self, assembler: Assembler) -> Assembler:
        self._by_kind[assembler.kind] = assembler
        return assembler

    def resolve(self, kind: RenditionKind) -> Assembler:
        assembler = self._by_kind.get(kind)
        if assembler is None:
            known = ", ".join(sorted(k.value for k in self._by_kind)) or "none registered"
            raise NoAssemblerAvailable(
                f"no assembler is registered for {kind.value!r}. Registered: {known}"
            )
        return assembler

    def kinds(self) -> list[RenditionKind]:
        return sorted(self._by_kind, key=lambda kind: kind.value)
