"""Turning scenes into rendered media.

One ``SceneRender`` is one unit of work: submitted, polled and collected on its
own, so a single scene can be re-rendered without touching its siblings. That is
what makes partial regeneration real rather than aspirational.

Three things this module is careful about:

* **It never names a provider.** It asks the registry for a capability. Whether
  ComfyUI, Wan, Seedance or something not yet written answers is invisible here.
* **It never assumes one machine.** The provider's handle is written to the
  database before polling begins, so the poll can happen in a different process
  than the submit. Nothing holds a GPU in memory.
* **It records how, not just what.** Provenance is written with the render, in
  the same transaction of thought, because a seed that was not captured at
  render time cannot be recovered later at any price.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ..models import Asset
from .models import Rendition, Scene, SceneRender, WorkStatus, fingerprint_scenes
from .provenance import RenderProvenance
from .providers.base import JobState, ProviderError, RenderRequest
from .recipes import Recipe, RecipeRegistry
from .registry import MediaProviderRegistry
from .repository import MediaRepository

if TYPE_CHECKING:
    from ..asset_system import AssetService

#: How long to wait for one scene before giving up. Generous: a 720p Wan render
#: on a busy worker is minutes, and a queue behind it can be longer.
DEFAULT_RENDER_TIMEOUT_SECONDS = 1800

#: Gap between polls. Long enough not to hammer a provider, short enough that a
#: quick render is not held up by the polling interval itself.
POLL_INTERVAL_SECONDS = 1.0

VIDEO_CAPABILITY = "video.generate"
NARRATION_CAPABILITY = "audio.narrate"


@dataclass
class RenderOutcome:
    """What happened to one scene."""

    scene_render: SceneRender
    media_asset: Asset | None = None
    audio_asset: Asset | None = None
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None and self.media_asset is not None


class SceneRenderService:
    def __init__(
        self,
        *,
        media_repository: MediaRepository,
        providers: MediaProviderRegistry,
        recipes: RecipeRegistry,
        asset_service: AssetService,
        workspace: Path,
        project_id: str = "project-unassigned",
        timeout_seconds: int = DEFAULT_RENDER_TIMEOUT_SECONDS,
        poll_interval: float = POLL_INTERVAL_SECONDS,
    ) -> None:
        self.media = media_repository
        self.providers = providers
        self.recipes = recipes
        self.assets = asset_service
        self.workspace = workspace
        self.project_id = project_id
        self.timeout_seconds = timeout_seconds
        self.poll_interval = poll_interval

    # -- planning ---------------------------------------------------------

    def plan(self, rendition: Rendition, scenes: list[Scene]) -> list[SceneRender]:
        """Create one ``SceneRender`` per scene, or return what already exists.

        Idempotent, because planning twice is a normal consequence of a retry
        and must not double the work.
        """
        existing = {
            render.scene_id: render for render in self.media.list_scene_renders(rendition.id)
        }
        planned: list[SceneRender] = []
        for scene in sorted(scenes, key=lambda s: s.index):
            if scene.id in existing:
                planned.append(existing[scene.id])
                continue
            planned.append(
                self.media.create_scene_render(
                    SceneRender(
                        rendition_id=rendition.id,
                        scene_id=scene.id,
                        index=scene.index,
                        source_fingerprint=scene.content_fingerprint(),
                    )
                )
            )
        return planned

    def stale_renders(self, rendition: Rendition, scenes: list[Scene]) -> list[SceneRender]:
        """Renders whose scene has changed since they were made.

        The basis of partial regeneration: this is how Atlas answers "which
        scenes actually need doing again" instead of rebuilding everything.
        """
        by_id = {scene.id: scene for scene in scenes}
        stale: list[SceneRender] = []
        for render in self.media.list_scene_renders(rendition.id):
            scene = by_id.get(render.scene_id)
            if scene is None:
                continue
            if render.status is not WorkStatus.READY:
                continue
            if render.source_fingerprint != scene.content_fingerprint():
                stale.append(render)
        return stale

    # -- rendering --------------------------------------------------------

    def render_scene(
        self,
        scene_render: SceneRender,
        scene: Scene,
        *,
        video_recipe_id: str,
        narration_recipe_id: str | None = None,
    ) -> RenderOutcome:
        """Render one scene: picture, then narration.

        Failure is contained here. One scene failing is one scene failing, and
        the rendition survives to be retried or partially rebuilt.
        """
        self.media.update_scene_render(scene_render.id, status=WorkStatus.RUNNING, error=None)

        try:
            recipe = self.recipes.get(video_recipe_id)
            media_asset, provenance = self._render_visual(scene_render, scene, recipe)
        except (ProviderError, Exception) as error:  # noqa: BLE001 - recorded, not swallowed
            message = f"{type(error).__name__}: {error}"
            self.media.update_scene_render(scene_render.id, status=WorkStatus.FAILED, error=message)
            return RenderOutcome(scene_render=scene_render, error=message)

        audio_asset: Asset | None = None
        if narration_recipe_id and scene.narration.strip():
            try:
                audio_asset = self._render_narration(
                    scene_render, scene, self.recipes.get(narration_recipe_id)
                )
            except Exception as error:  # noqa: BLE001
                # Deliberately not fatal. A scene with a picture and no voice is
                # reviewable and fixable; failing the whole scene for it would
                # throw away a render that already cost GPU time.
                self.media.update_scene_render(scene_render.id, error=f"narration failed: {error}")

        updated = self.media.update_scene_render(
            scene_render.id,
            status=WorkStatus.READY,
            media_asset_id=media_asset.id,
            audio_asset_id=audio_asset.id if audio_asset else None,
            provider=provenance.provider,
            recipe_id=provenance.recipe_id,
            provenance=provenance.model_dump(mode="json"),
            render_ms=provenance.render_ms,
            cost_usd=provenance.cost_usd,
            duration_seconds=scene.target_seconds,
            source_fingerprint=scene.content_fingerprint(),
        )
        return RenderOutcome(
            scene_render=updated or scene_render,
            media_asset=media_asset,
            audio_asset=audio_asset,
        )

    def _render_visual(
        self, scene_render: SceneRender, scene: Scene, recipe: Recipe
    ) -> tuple[Asset, RenderProvenance]:
        registration = self.providers.resolve(VIDEO_CAPABILITY, preferred=recipe.provider)
        request = RenderRequest(
            recipe_id=recipe.id,
            prompt=recipe.render_prompt(scene.visual_direction or scene.heading),
            duration_seconds=scene.target_seconds,
            width=int(recipe.parameters.get("width", 1920)),
            height=int(recipe.parameters.get("height", 1080)),
            parameters=dict(recipe.parameters),
            labels={"scene_index": str(scene.index), "heading": scene.heading},
        )

        started = time.monotonic()
        handle = registration.provider.submit(request)
        # Written before the first poll so another worker could take over. The
        # provider's handle is the only thing that makes a render resumable.
        self.media.update_scene_render(scene_render.id, provider_handle=handle)

        status = self._await(registration, handle)
        elapsed_ms = int((time.monotonic() - started) * 1000)

        if status.state is JobState.FAILED:
            raise ProviderError(status.detail or f"{registration.name} failed without a reason")

        destination = self.workspace / scene_render.rendition_id / f"scene-{scene.index:03d}.mp4"
        destination.parent.mkdir(parents=True, exist_ok=True)
        registration.provider.fetch(handle, destination)

        provenance = RenderProvenance(
            provider=registration.name,
            model=recipe.model,
            model_version=status.metadata.get("model_version"),
            recipe_id=recipe.id,
            recipe_version=recipe.version,
            workflow=recipe.workflow,
            workflow_hash=recipe.workflow_sha256,
            prompt=request.prompt,
            negative_prompt=recipe.negative_prompt,
            seed=recipe.seed if recipe.seed is not None else status.metadata.get("seed"),
            loras=list(recipe.loras),
            parameters=request.parameters,
            render_ms=elapsed_ms,
            cost_usd=(
                round(registration.cost_per_second * scene.target_seconds, 4)
                if registration.cost_per_second
                else 0.0
            ),
            provider_extra=dict(status.metadata),
        )

        asset = self._store(
            destination,
            asset_type="video",
            mime_type="video/mp4",
            tags=["scene", "video", f"scene-{scene.index}"],
            metadata={
                "scene_id": scene.id,
                "scene_index": scene.index,
                "rendition_id": scene_render.rendition_id,
                "heading": scene.heading,
                "provenance": provenance.model_dump(mode="json"),
                "reproduction_key": provenance.reproduction_key(),
            },
        )
        return asset, provenance

    def _render_narration(self, scene_render: SceneRender, scene: Scene, recipe: Recipe) -> Asset:
        registration = self.providers.resolve(NARRATION_CAPABILITY, preferred=recipe.provider)
        request = RenderRequest(
            recipe_id=recipe.id,
            prompt=recipe.render_prompt(scene.narration),
            duration_seconds=scene.target_seconds,
            parameters=dict(recipe.parameters),
            labels={"scene_index": str(scene.index)},
        )
        handle = registration.provider.submit(request)
        status = self._await(registration, handle)
        if status.state is JobState.FAILED:
            raise ProviderError(status.detail or f"{registration.name} failed without a reason")

        destination = self.workspace / scene_render.rendition_id / f"scene-{scene.index:03d}.m4a"
        destination.parent.mkdir(parents=True, exist_ok=True)
        registration.provider.fetch(handle, destination)

        return self._store(
            destination,
            asset_type="audio",
            mime_type="audio/mp4",
            tags=["scene", "narration", f"scene-{scene.index}"],
            metadata={
                "scene_id": scene.id,
                "scene_index": scene.index,
                "rendition_id": scene_render.rendition_id,
                "narration": scene.narration,
                "provider": registration.name,
                "recipe_id": recipe.id,
            },
        )

    def _await(self, registration, handle: str):  # type: ignore[no-untyped-def]
        """Poll until the provider finishes or we run out of patience."""
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            status = registration.provider.poll(handle)
            if status.finished:
                return status
            if time.monotonic() > deadline:
                raise ProviderError(
                    f"{registration.name} did not finish {handle} within "
                    f"{self.timeout_seconds}s"
                )
            time.sleep(self.poll_interval)

    def _store(
        self,
        path: Path,
        *,
        asset_type: str,
        mime_type: str,
        tags: list[str],
        metadata: dict,
    ) -> Asset:
        payload = path.read_bytes()
        return self.assets.create_asset(
            Asset(
                type=asset_type,
                project_id=self.project_id,
                uri=path.name,
                mime_type=mime_type,
                file_size=len(payload),
                tags=tags,
                metadata=metadata,
            ),
            payload=payload,
        )

    # -- rendition-level --------------------------------------------------

    def render_rendition(
        self,
        rendition: Rendition,
        scenes: list[Scene],
        *,
        video_recipe_id: str,
        narration_recipe_id: str | None = None,
        only: list[str] | None = None,
    ) -> list[RenderOutcome]:
        """Render every scene, or only the ones named.

        ``only`` is what partial regeneration passes: the scene ids that
        actually changed. Everything else keeps the render it already has.
        """
        planned = self.plan(rendition, scenes)
        by_id = {scene.id: scene for scene in scenes}
        self.media.update_rendition(rendition.id, status=WorkStatus.RUNNING, error=None)

        outcomes: list[RenderOutcome] = []
        for scene_render in planned:
            scene = by_id.get(scene_render.scene_id)
            if scene is None:
                continue
            if only is not None and scene.id not in only:
                outcomes.append(RenderOutcome(scene_render=scene_render))
                continue
            outcomes.append(
                self.render_scene(
                    scene_render,
                    scene,
                    video_recipe_id=video_recipe_id,
                    narration_recipe_id=narration_recipe_id,
                )
            )

        current = self.media.list_scene_renders(rendition.id)
        failed = [r for r in current if r.status is WorkStatus.FAILED]
        ready = all(r.status is WorkStatus.READY for r in current)

        self.media.update_rendition(
            rendition.id,
            status=WorkStatus.READY if ready else WorkStatus.FAILED,
            scene_fingerprint=fingerprint_scenes(scenes) if ready else "",
            error=None if ready else f"{len(failed)} of {len(current)} scenes failed",
            build_metadata={
                "video_recipe": video_recipe_id,
                "narration_recipe": narration_recipe_id,
                "rendered_at": datetime.now(UTC).isoformat(),
            },
        )
        return outcomes
