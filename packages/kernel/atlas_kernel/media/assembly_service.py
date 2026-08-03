"""From rendered scenes to one finished rendition in the Library.

Deliberately free of any notion of video. It gathers what exists for each scene,
asks the registry which assembler builds this *kind* of rendition, and stores
whatever comes back. Adding podcasts, thumbnails or blog posts later is a
registration and a recipe, not a change here.

The one thing it will not do is render. Assembly builds a cut from what exists;
if a scene has no media, that is a rendering problem and it says so rather than
quietly producing a shorter video than the script asked for.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ..models import Asset
from . import capabilities
from .assembly.base import (
    AssemblerRegistry,
    AssemblyError,
    AssemblyRequest,
    AssemblyResult,
    SceneMaterial,
)
from .models import Rendition, Scene, WorkStatus, fingerprint_scenes
from .providers.base import RenderRequest
from .recipes import RecipeRegistry
from .registry import MediaProviderRegistry, NoProviderAvailable
from .repository import MediaRepository

if TYPE_CHECKING:
    from ..asset_system import AssetService


def stored_path(uri: str) -> Path:
    """Where an asset actually lives.

    The storage backend returns a ``file:`` URI so the same field can point at
    object storage later without every reader changing.
    """
    return Path(uri.removeprefix("file://").removeprefix("file:"))


class AssemblyService:
    def __init__(
        self,
        *,
        media_repository: MediaRepository,
        assemblers: AssemblerRegistry,
        asset_service: AssetService,
        workspace: Path,
        providers: MediaProviderRegistry | None = None,
        recipes: RecipeRegistry | None = None,
        project_id: str = "project-unassigned",
    ) -> None:
        self.media = media_repository
        self.assemblers = assemblers
        self.assets = asset_service
        self.workspace = workspace
        self.providers = providers
        self.recipes = recipes
        self.project_id = project_id

    def materials(self, rendition: Rendition, scenes: list[Scene]) -> list[SceneMaterial]:
        """Pair each scene with whatever has been rendered for it."""
        renders = {r.scene_id: r for r in self.media.list_scene_renders(rendition.id)}
        out: list[SceneMaterial] = []
        for scene in sorted(scenes, key=lambda s: s.index):
            render = renders.get(scene.id)
            media_path = audio_path = None
            if render and render.media_asset_id:
                asset = self.assets.repository.get_asset(render.media_asset_id)
                media_path = stored_path(asset.uri) if asset else None
            if render and render.audio_asset_id:
                asset = self.assets.repository.get_asset(render.audio_asset_id)
                audio_path = stored_path(asset.uri) if asset else None
            out.append(
                SceneMaterial(
                    scene=scene, render=render, media_path=media_path, audio_path=audio_path
                )
            )
        return out

    def assemble(
        self,
        rendition: Rendition,
        scenes: list[Scene],
        *,
        music_recipe_id: str | None = None,
        options: dict | None = None,
    ) -> Asset:
        """Build the rendition and put the result in the Library."""
        materials = self.materials(rendition, scenes)
        assembler = self.assemblers.resolve(rendition.kind)

        target = self.workspace / rendition.id / f"{rendition.id}.mp4"
        target.parent.mkdir(parents=True, exist_ok=True)

        music = None
        if music_recipe_id:
            total = sum(material.scene.target_seconds for material in materials)
            music = self._music(music_recipe_id, total, target.parent)

        try:
            result = assembler.assemble(
                AssemblyRequest(
                    rendition=rendition,
                    materials=materials,
                    output=target,
                    music_path=music,
                    options=options or {},
                )
            )
        except AssemblyError as error:
            self.media.update_rendition(rendition.id, status=WorkStatus.FAILED, error=str(error))
            raise

        asset = self._store(result, rendition)
        # The caption sidecar is an artefact in its own right, not a file that
        # happens to sit beside the video. Storing it means it survives the
        # workspace being cleaned up, and the publisher can find it without
        # guessing at paths -- which it could not, because the asset store
        # renames what it keeps.
        captions_asset = self._store_captions(result, rendition)
        if captions_asset is not None:
            result.metadata["captions_asset_id"] = captions_asset.id

        self.media.update_rendition(
            rendition.id,
            status=WorkStatus.READY,
            asset_id=asset.id,
            scene_fingerprint=fingerprint_scenes(scenes),
            error=None,
            build_metadata={
                **(rendition.build_metadata or {}),
                "assembly": result.metadata,
                "assembler_kind": rendition.kind.value,
            },
        )
        return asset

    def _music(self, recipe_id: str, seconds: float, workspace: Path) -> Path | None:
        """A bed track, if one can be had.

        Missing music is not a reason to fail an assembly: a video without a
        bed is publishable, and a video that does not exist is not.
        """
        if not (self.providers and self.recipes):
            return None
        try:
            recipe = self.recipes.get(recipe_id)
            registration = self.providers.resolve(
                capabilities.MUSIC_GENERATE, preferred=recipe.provider
            )
        except (NoProviderAvailable, Exception):  # noqa: BLE001
            return None

        handle = registration.provider.submit(
            RenderRequest(
                recipe_id=recipe.id,
                prompt=recipe.render_prompt(recipe.description or "background bed"),
                duration_seconds=max(seconds, 1.0),
                parameters=dict(recipe.parameters),
            )
        )
        if registration.provider.poll(handle).state.value != "succeeded":
            return None
        return registration.provider.fetch(handle, workspace / "music.m4a")

    def _store_captions(self, result: AssemblyResult, rendition: Rendition) -> Asset | None:
        sidecar = result.metadata.get("subtitle_sidecar")
        if not sidecar:
            return None
        path = Path(sidecar)
        if not path.exists():
            return None
        payload = path.read_bytes()
        return self.assets.create_asset(
            Asset(
                type="document",
                project_id=self.project_id,
                uri=path.name,
                mime_type="application/x-subrip",
                file_size=len(payload),
                tags=["captions", "rendition"],
                metadata={
                    "rendition_id": rendition.id,
                    "episode_id": rendition.episode_id,
                    "cue_count": result.metadata.get("cue_count"),
                },
            ),
            payload=payload,
        )

    def _store(self, result: AssemblyResult, rendition: Rendition) -> Asset:
        payload = result.output.read_bytes()
        return self.assets.create_asset(
            Asset(
                type="video" if rendition.kind.value.startswith("video/") else "document",
                project_id=self.project_id,
                uri=result.output.name,
                mime_type="video/mp4" if rendition.kind.value.startswith("video/") else None,
                file_size=len(payload),
                tags=["rendition", rendition.kind.value],
                metadata={
                    "rendition_id": rendition.id,
                    "episode_id": rendition.episode_id,
                    "script_id": rendition.script_id,
                    "kind": rendition.kind.value,
                    "duration_seconds": result.duration_seconds,
                    **result.metadata,
                },
            ),
            payload=payload,
        )
