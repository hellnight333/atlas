"""Scene renders through the kernel, with real assets and real provenance
(M013 step 3).

The demo this step owes: five scenes go in, five playable files land in the
Library, each carrying enough provenance to be made again.

Nothing here names a provider. The service asks for a capability and the
registry answers, which is the property that keeps ComfyUI, Wan, Seedance, Veo
and anything not yet written interchangeable.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from atlas_kernel import db
from atlas_kernel.composition_root import create_runtime
from atlas_kernel.media import ffmpeg
from atlas_kernel.media.models import (
    Episode,
    Rendition,
    Scene,
    Script,
    Series,
    WorkStatus,
)
from atlas_kernel.media.provenance import RenderProvenance
from atlas_kernel.media.providers.base import JobState, ProviderJobStatus, RenderRequest
from atlas_kernel.media.providers.mock import MockNarrationProvider, MockVideoProvider
from atlas_kernel.media.recipes import RecipeRegistry, default_root
from atlas_kernel.media.registry import (
    MediaProviderRegistry,
    NoProviderAvailable,
    ProviderRegistration,
)
from atlas_kernel.media.render_service import (
    NARRATION_CAPABILITY,
    VIDEO_CAPABILITY,
    SceneRenderService,
)
from atlas_kernel.media.repository import MediaRepository

pytestmark = pytest.mark.skipif(
    not ffmpeg.available(), reason="ffmpeg and ffprobe are required for media tests"
)

db.init_db()


@pytest.fixture
def media() -> MediaRepository:
    return MediaRepository()


@pytest.fixture
def recipes() -> RecipeRegistry:
    return RecipeRegistry(default_root()).load()


@pytest.fixture
def providers(tmp_path: Path) -> MediaProviderRegistry:
    registry = MediaProviderRegistry()
    registry.register(
        ProviderRegistration(
            provider=MockVideoProvider(workspace=tmp_path / "video"),
            capability=VIDEO_CAPABILITY,
            is_local=True,
        )
    )
    registry.register(
        ProviderRegistration(
            provider=MockNarrationProvider(workspace=tmp_path / "audio"),
            capability=NARRATION_CAPABILITY,
            is_local=True,
        )
    )
    return registry


@pytest.fixture
def service(
    media: MediaRepository,
    providers: MediaProviderRegistry,
    recipes: RecipeRegistry,
    tmp_path: Path,
) -> SceneRenderService:
    runtime = create_runtime()
    return SceneRenderService(
        media_repository=media,
        providers=providers,
        recipes=recipes,
        asset_service=runtime.asset_service,
        workspace=tmp_path / "renders",
        poll_interval=0.01,
    )


def _stored_path(uri: str) -> Path:
    """Where a stored asset actually lives.

    The storage backend returns a ``file:`` URI, not a bare path -- so that the
    same field can point at object storage later without every reader changing.
    """
    return Path(uri.removeprefix("file://").removeprefix("file:"))


def _episode_with_scenes(media: MediaRepository, count: int = 5):
    series = media.create_series(Series(name=f"Series {uuid4().hex[:8]}"))
    episode = media.create_episode(Episode(series_id=series.id, brief="Explain the Atlas kernel."))
    script = media.create_script(Script(episode_id=episode.id, version=1, authored_by="test"))
    scenes = media.replace_scenes(
        script.id,
        [
            Scene(
                script_id=script.id,
                index=i,
                heading=f"Beat {i}",
                narration=f"This is the narration for beat number {i}.",
                visual_direction=f"A wide establishing shot, beat {i}.",
                target_seconds=1.5,
            )
            for i in range(count)
        ],
    )
    rendition = media.create_rendition(Rendition(episode_id=episode.id, script_id=script.id))
    return episode, script, scenes, rendition


# -- the step 3 demo ------------------------------------------------------


def test_five_scenes_become_five_playable_assets(
    service: SceneRenderService, media: MediaRepository
) -> None:
    """The demo this step owes."""
    _episode, _script, scenes, rendition = _episode_with_scenes(media, count=5)

    outcomes = service.render_rendition(
        rendition,
        scenes,
        video_recipe_id="mock-slate-1080p",
        narration_recipe_id="mock-narration",
    )

    assert len(outcomes) == 5
    assert all(outcome.succeeded for outcome in outcomes)

    for outcome in outcomes:
        assert outcome.media_asset is not None
        stored = _stored_path(outcome.media_asset.uri)
        assert stored.exists(), "the asset must point at a file that is really there"
        info = ffmpeg.probe(stored)
        assert info.has_video is True
        assert info.duration_seconds > 0

    reloaded = media.get_rendition(rendition.id)
    assert reloaded is not None
    assert reloaded.status is WorkStatus.READY
    assert reloaded.scene_fingerprint != ""


def test_renders_keep_their_scene_order(
    service: SceneRenderService, media: MediaRepository
) -> None:
    _e, _s, scenes, rendition = _episode_with_scenes(media, count=4)
    service.render_rendition(rendition, scenes, video_recipe_id="mock-slate-1080p")
    assert [r.index for r in media.list_scene_renders(rendition.id)] == [0, 1, 2, 3]


def test_narration_is_rendered_alongside_the_picture(
    service: SceneRenderService, media: MediaRepository
) -> None:
    _e, _s, scenes, rendition = _episode_with_scenes(media, count=2)
    outcomes = service.render_rendition(
        rendition,
        scenes,
        video_recipe_id="mock-slate-1080p",
        narration_recipe_id="mock-narration",
    )
    for outcome in outcomes:
        assert outcome.audio_asset is not None
        assert ffmpeg.probe(_stored_path(outcome.audio_asset.uri)).has_audio is True


# -- provenance -----------------------------------------------------------


def test_every_render_records_how_to_make_it_again(
    service: SceneRenderService, media: MediaRepository
) -> None:
    """Provenance not captured at render time cannot be reconstructed later at
    any price."""
    _e, _s, scenes, rendition = _episode_with_scenes(media, count=2)
    service.render_rendition(rendition, scenes, video_recipe_id="mock-slate-1080p")

    for render in media.list_scene_renders(rendition.id):
        recorded = RenderProvenance(**render.provenance)
        assert recorded.provider == "mock-video"
        assert recorded.recipe_id == "mock-slate-1080p"
        assert recorded.recipe_version == "1.0.0"
        assert recorded.prompt
        assert recorded.parameters["width"] == 1920
        assert recorded.render_ms is not None and recorded.render_ms >= 0
        assert recorded.reproduction_key()


def test_provenance_travels_with_the_asset_too(
    service: SceneRenderService, media: MediaRepository
) -> None:
    """So an asset found in the Library, years later, explains itself without
    needing the render row it came from."""
    _e, _s, scenes, rendition = _episode_with_scenes(media, count=1)
    outcomes = service.render_rendition(rendition, scenes, video_recipe_id="mock-slate-1080p")

    metadata = outcomes[0].media_asset.metadata
    assert metadata["provenance"]["recipe_id"] == "mock-slate-1080p"
    assert metadata["reproduction_key"]
    assert metadata["scene_id"] == scenes[0].id


def test_reproduction_key_ignores_what_it_cost() -> None:
    """Two renders of the same request are the same render, even if one was
    slower."""
    base = RenderProvenance(provider="p", recipe_id="r", prompt="a cat", seed=7)
    slower = base.model_copy(update={"render_ms": 99_000, "cost_usd": 1.23})
    assert base.reproduction_key() == slower.reproduction_key()

    different = base.model_copy(update={"seed": 8})
    assert different.reproduction_key() != base.reproduction_key()


def test_reproducibility_is_reported_honestly() -> None:
    """A render without a seed is not reproducible, and Atlas says so rather
    than implying otherwise."""
    incomplete = RenderProvenance(provider="p", recipe_id="r", prompt="x")
    ok, missing = incomplete.is_reproducible()
    assert ok is False
    assert "seed" in missing and "model" in missing

    complete = RenderProvenance(provider="p", recipe_id="r", prompt="x", model="m", seed=1)
    assert complete.is_reproducible() == (True, [])


def test_a_pinned_workflow_without_a_hash_is_not_reproducible() -> None:
    """A graph edited in the ComfyUI GUI keeps its filename. Only the hash
    notices."""
    provenance = RenderProvenance(
        provider="p", recipe_id="r", model="m", seed=1, workflow="graph.json"
    )
    ok, missing = provenance.is_reproducible()
    assert ok is False
    assert "workflow_hash" in missing


# -- providers stay disposable -------------------------------------------


def test_the_service_never_names_a_provider() -> None:
    """Enforced mechanically, because this is a rule a plausible change would
    quietly break.

    Checks executable code only. Prose explaining *why* the kernel is
    vendor-agnostic necessarily names vendors, and a test that forbade the
    explanation as well as the coupling would be pressure to delete the
    explanation.
    """
    import ast
    import inspect

    from atlas_kernel.media import render_service

    tree = ast.parse(inspect.getsource(render_service))
    # Strip docstrings; keep every other string literal, identifier and import.
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    node.body = body[1:]

    code = ast.unparse(tree).lower()
    for vendor in ("comfy", "wan2", "seedance", "veo", "kling", "ltx", "mock-video", "mock-tts"):
        assert vendor not in code, (
            f"render_service names {vendor!r} in executable code. It must ask for a "
            "capability and let the registry answer."
        )


def test_resolution_is_local_first(tmp_path: Path) -> None:
    """Cloud is a fallback, never the default."""
    registry = MediaProviderRegistry()
    cloud = MockVideoProvider(workspace=tmp_path / "cloud")
    cloud.name = "cloud-video"  # type: ignore[misc]
    local = MockVideoProvider(workspace=tmp_path / "local")
    local.name = "local-video"  # type: ignore[misc]

    registry.register(
        ProviderRegistration(
            provider=cloud, capability=VIDEO_CAPABILITY, is_local=False, cost_per_second=0.0
        )
    )
    registry.register(
        ProviderRegistration(
            provider=local, capability=VIDEO_CAPABILITY, is_local=True, cost_per_second=0.5
        )
    )

    # Local wins even though it is nominally more expensive.
    assert registry.resolve(VIDEO_CAPABILITY).name == "local-video"


def test_cloud_can_be_disabled_entirely(tmp_path: Path) -> None:
    registry = MediaProviderRegistry(allow_cloud=False)
    cloud = MockVideoProvider(workspace=tmp_path / "cloud")
    cloud.name = "cloud-video"  # type: ignore[misc]
    registry.register(
        ProviderRegistration(provider=cloud, capability=VIDEO_CAPABILITY, is_local=False)
    )
    with pytest.raises(NoProviderAvailable, match="cloud providers are disabled"):
        registry.resolve(VIDEO_CAPABILITY)


def test_a_recipe_naming_a_missing_provider_still_renders(
    service: SceneRenderService, media: MediaRepository, recipes: RecipeRegistry
) -> None:
    """Recipes outlive the providers they were written against.

    ``provider`` in a recipe is a preference. A recipe pinned to hardware that
    has since been replaced must not become unusable.
    """
    _e, _s, scenes, rendition = _episode_with_scenes(media, count=1)
    recipe = recipes.get("mock-slate-1080p")
    recipes._by_id["mock-slate-1080p"] = recipe.model_copy(  # noqa: SLF001
        update={"provider": "a-provider-that-was-decommissioned"}
    )

    outcomes = service.render_rendition(rendition, scenes, video_recipe_id="mock-slate-1080p")
    assert outcomes[0].succeeded


def test_no_provider_for_a_capability_is_a_configuration_error() -> None:
    registry = MediaProviderRegistry()
    with pytest.raises(NoProviderAvailable, match="video.generate"):
        registry.resolve(VIDEO_CAPABILITY)


# -- nothing assumes one machine -----------------------------------------


def test_the_provider_handle_is_persisted_before_polling(
    service: SceneRenderService, media: MediaRepository
) -> None:
    """So a poll can happen in a different process than the submit.

    If the handle only ever lived in memory, Atlas would be pinned to one
    worker and one GPU forever.
    """
    _e, _s, scenes, rendition = _episode_with_scenes(media, count=1)
    service.render_rendition(rendition, scenes, video_recipe_id="mock-slate-1080p")

    render = media.list_scene_renders(rendition.id)[0]
    assert render.provider_handle
    assert render.provider_handle.startswith("mock-video-")


# -- failure is contained -------------------------------------------------


def test_one_failing_scene_does_not_kill_the_others(
    service: SceneRenderService, media: MediaRepository, providers: MediaProviderRegistry
) -> None:
    """One scene failing is one scene failing, not a dead video."""
    _e, _s, scenes, rendition = _episode_with_scenes(media, count=3)
    registration = providers.resolve(VIDEO_CAPABILITY)
    real_submit = registration.provider.submit

    def fail_scene_one(request: RenderRequest) -> str:
        if request.labels.get("scene_index") == "1":
            handle = "broken-handle"
            registration.provider._failures[handle] = "synthetic GPU fault"  # noqa: SLF001
            return handle
        return real_submit(request)

    registration.provider.submit = fail_scene_one  # type: ignore[method-assign]

    outcomes = service.render_rendition(rendition, scenes, video_recipe_id="mock-slate-1080p")

    assert [o.succeeded for o in outcomes] == [True, False, True]
    statuses = [r.status for r in media.list_scene_renders(rendition.id)]
    assert statuses == [WorkStatus.READY, WorkStatus.FAILED, WorkStatus.READY]

    reloaded = media.get_rendition(rendition.id)
    assert reloaded is not None
    assert reloaded.status is WorkStatus.FAILED
    # No fingerprint claimed, because there is no complete cut to claim one for.
    assert reloaded.scene_fingerprint == ""


def test_a_failed_render_records_why(
    service: SceneRenderService, media: MediaRepository, providers: MediaProviderRegistry
) -> None:
    _e, _s, scenes, rendition = _episode_with_scenes(media, count=1)
    registration = providers.resolve(VIDEO_CAPABILITY)

    def always_fail(_request: RenderRequest) -> str:
        registration.provider._failures["h"] = "the GPU fell over"  # noqa: SLF001
        return "h"

    registration.provider.submit = always_fail  # type: ignore[method-assign]
    service.render_rendition(rendition, scenes, video_recipe_id="mock-slate-1080p")

    render = media.list_scene_renders(rendition.id)[0]
    assert render.status is WorkStatus.FAILED
    assert "the GPU fell over" in (render.error or "")


def test_a_render_that_never_finishes_times_out(
    service: SceneRenderService, media: MediaRepository, providers: MediaProviderRegistry
) -> None:
    """A provider that accepts work and then goes quiet must not hang the
    pipeline forever."""
    _e, _s, scenes, rendition = _episode_with_scenes(media, count=1)
    registration = providers.resolve(VIDEO_CAPABILITY)
    registration.provider.poll = lambda handle: ProviderJobStatus(  # type: ignore[method-assign]
        handle=handle, state=JobState.RUNNING
    )
    service.timeout_seconds = 0

    service.render_rendition(rendition, scenes, video_recipe_id="mock-slate-1080p")
    render = media.list_scene_renders(rendition.id)[0]
    assert render.status is WorkStatus.FAILED
    assert "did not finish" in (render.error or "")


def test_narration_failure_does_not_discard_a_good_picture(
    service: SceneRenderService, media: MediaRepository, providers: MediaProviderRegistry
) -> None:
    """Failing a whole scene over a missing voice would throw away GPU time
    that was already spent."""
    _e, _s, scenes, rendition = _episode_with_scenes(media, count=1)
    narration = providers.resolve(NARRATION_CAPABILITY)

    def explode(_request: RenderRequest) -> str:
        raise RuntimeError("tts unavailable")

    narration.provider.submit = explode  # type: ignore[method-assign]

    outcomes = service.render_rendition(
        rendition,
        scenes,
        video_recipe_id="mock-slate-1080p",
        narration_recipe_id="mock-narration",
    )
    assert outcomes[0].media_asset is not None
    render = media.list_scene_renders(rendition.id)[0]
    assert render.status is WorkStatus.READY
    assert "narration failed" in (render.error or "")


# -- planning is idempotent ----------------------------------------------


def test_planning_twice_does_not_double_the_work(
    service: SceneRenderService, media: MediaRepository
) -> None:
    """A retry re-plans, and must not create a second render per scene."""
    _e, _s, scenes, rendition = _episode_with_scenes(media, count=3)
    service.plan(rendition, scenes)
    service.plan(rendition, scenes)
    assert len(media.list_scene_renders(rendition.id)) == 3


def test_stale_renders_are_identified_individually(
    service: SceneRenderService, media: MediaRepository
) -> None:
    """What partial regeneration will act on in step 5."""
    _e, script, scenes, rendition = _episode_with_scenes(media, count=3)
    service.render_rendition(rendition, scenes, video_recipe_id="mock-slate-1080p")

    media.update_scene(scenes[1].id, visual_direction="A totally different shot.")
    current = media.list_scenes(script.id)

    stale = service.stale_renders(rendition, current)
    assert [render.index for render in stale] == [1]
