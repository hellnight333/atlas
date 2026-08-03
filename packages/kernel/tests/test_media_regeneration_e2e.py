"""Partial regeneration, proved against real files (M013 step 5).

The graph tests show the right nodes go stale. These show the consequence that
actually matters: after a narration edit, the picture on disk is *the same
bytes*. Not "was not re-planned" -- not touched.

That is the difference between a design that saves GPU time and a design that
claims to.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest

from atlas_kernel import db
from atlas_kernel.composition_root import create_runtime
from atlas_kernel.dependency_store import DependencyStore
from atlas_kernel.media import capabilities, ffmpeg
from atlas_kernel.media.assembly.base import AssemblerRegistry
from atlas_kernel.media.assembly.video import VideoAssembler, VideoFormat
from atlas_kernel.media.assembly_service import AssemblyService, stored_path
from atlas_kernel.media.dependencies import MediaInputs, build_graph, speech_node, visual_node
from atlas_kernel.media.models import Episode, Rendition, Scene, Script, Series
from atlas_kernel.media.providers.mock import (
    MockMusicProvider,
    MockNarrationProvider,
    MockVideoProvider,
)
from atlas_kernel.media.recipes import RecipeRegistry, default_root
from atlas_kernel.media.regeneration import plan_regeneration
from atlas_kernel.media.registry import MediaProviderRegistry, ProviderRegistration
from atlas_kernel.media.render_service import SceneRenderService
from atlas_kernel.media.repository import MediaRepository

pytestmark = pytest.mark.skipif(
    not ffmpeg.available(), reason="ffmpeg and ffprobe are required for media tests"
)

db.init_db()

FAST = VideoFormat(width=320, height=180, fps=12, preset="ultrafast", crf=30)
VIDEO_RECIPE = "mock-slate-1080p"
SPEECH_RECIPE = "mock-narration"


@pytest.fixture
def world(tmp_path: Path):
    """A rendition that has been rendered and assembled once."""
    media = MediaRepository()
    runtime = create_runtime()
    store = DependencyStore()
    recipes = RecipeRegistry(default_root()).load()

    providers = MediaProviderRegistry()
    providers.register(
        ProviderRegistration(
            provider=MockVideoProvider(workspace=tmp_path / "v"),
            capability=capabilities.VIDEO_GENERATE,
        )
    )
    providers.register(
        ProviderRegistration(
            provider=MockNarrationProvider(workspace=tmp_path / "a"),
            capability=capabilities.SPEECH_GENERATE,
        )
    )
    providers.register(
        ProviderRegistration(
            provider=MockMusicProvider(workspace=tmp_path / "m"),
            capability=capabilities.MUSIC_GENERATE,
        )
    )

    series = media.create_series(Series(name=f"Series {uuid4().hex[:8]}"))
    episode = media.create_episode(Episode(series_id=series.id, brief="Explain Atlas."))
    script = media.create_script(Script(episode_id=episode.id, version=1))
    scenes = media.replace_scenes(
        script.id,
        [
            Scene(
                script_id=script.id,
                index=i,
                heading=f"Beat {i}",
                narration=f"Narration for beat {i}.",
                visual_direction=f"A shot, beat {i}.",
                target_seconds=1.0,
            )
            for i in range(3)
        ],
    )
    rendition = media.create_rendition(Rendition(episode_id=episode.id, script_id=script.id))

    renderer = SceneRenderService(
        media_repository=media,
        providers=providers,
        recipes=recipes,
        asset_service=runtime.asset_service,
        workspace=tmp_path / "renders",
        poll_interval=0.01,
    )
    assemblers = AssemblerRegistry()
    assemblers.register(VideoAssembler(FAST))
    assembler = AssemblyService(
        media_repository=media,
        assemblers=assemblers,
        asset_service=runtime.asset_service,
        workspace=tmp_path / "assembly",
        providers=providers,
        recipes=recipes,
    )

    def inputs(current_scenes: list[Scene]) -> MediaInputs:
        return MediaInputs(
            rendition=media.get_rendition(rendition.id),
            scenes=current_scenes,
            video_recipe=recipes.get(VIDEO_RECIPE),
            speech_recipe=recipes.get(SPEECH_RECIPE),
            music_key="none",
        )

    # First build.
    renderer.render_rendition(
        rendition, scenes, video_recipe_id=VIDEO_RECIPE, narration_recipe_id=SPEECH_RECIPE
    )
    assembler.assemble(media.get_rendition(rendition.id), scenes)
    store.record(rendition.id, build_graph(inputs(scenes)).snapshot())

    return {
        "media": media,
        "store": store,
        "renderer": renderer,
        "assembler": assembler,
        "recipes": recipes,
        "rendition_id": rendition.id,
        "script_id": script.id,
        "scenes": scenes,
        "inputs": inputs,
    }


def _digest_of(media: MediaRepository, rendition_id: str, scene_id: str, field: str) -> str:
    render = next(r for r in media.list_scene_renders(rendition_id) if r.scene_id == scene_id)
    asset_id = getattr(render, field)
    assert asset_id, f"{field} missing for scene {scene_id}"
    runtime = create_runtime()
    asset = runtime.asset_service.repository.get_asset(asset_id)
    return hashlib.sha256(stored_path(asset.uri).read_bytes()).hexdigest()


def test_a_narration_edit_leaves_the_picture_untouched_on_disk(world) -> None:
    """The claim, tested against bytes rather than intentions."""
    media, store = world["media"], world["store"]
    rendition_id, script_id = world["rendition_id"], world["script_id"]
    scenes = world["scenes"]
    target = scenes[1]

    before = _digest_of(media, rendition_id, target.id, "media_asset_id")
    voice_before = _digest_of(media, rendition_id, target.id, "audio_asset_id")

    media.update_scene(target.id, narration="An entirely rewritten line of narration.")
    current = media.list_scenes(script_id)

    graph = build_graph(world["inputs"](current))
    recorded = store.recorded(rendition_id)
    plan = plan_regeneration(
        graph,
        recorded,
        current,
        video_recipe=world["recipes"].get(VIDEO_RECIPE),
        speech_recipe=world["recipes"].get(SPEECH_RECIPE),
    )

    assert plan.scenes_to_revoice() == [target.id]
    assert plan.scenes_to_rerender() == []

    # Count provider calls rather than trusting byte equality. The mock is
    # deterministic, so an unnecessary re-render would produce identical bytes
    # and a digest comparison would pass while the GPU time was spent anyway.
    renderer = world["renderer"]
    video_provider = renderer.providers.resolve(capabilities.VIDEO_GENERATE).provider
    speech_provider = renderer.providers.resolve(capabilities.SPEECH_GENERATE).provider
    video_calls: list[str] = []
    speech_calls: list[str] = []
    real_video, real_speech = video_provider.submit, speech_provider.submit
    video_provider.submit = lambda r: (video_calls.append(r.prompt), real_video(r))[1]
    speech_provider.submit = lambda r: (speech_calls.append(r.prompt), real_speech(r))[1]

    # Execute exactly what the plan asked for, and nothing else.
    renderer.render_rendition(
        media.get_rendition(rendition_id),
        current,
        video_recipe_id=VIDEO_RECIPE,
        narration_recipe_id=SPEECH_RECIPE,
        render_visuals=plan.scenes_to_rerender(),
        render_narration=plan.scenes_to_revoice(),
    )

    assert video_calls == [], "the picture renderer was called for a text edit"
    assert len(speech_calls) == 1, "the narration was not re-rendered exactly once"

    after = _digest_of(media, rendition_id, target.id, "media_asset_id")
    voice_after = _digest_of(media, rendition_id, target.id, "audio_asset_id")
    assert after == before, "the stored picture changed"
    assert voice_after != voice_before, "the stored narration did not change"


def test_untouched_scenes_are_untouched(world) -> None:
    media, store = world["media"], world["store"]
    rendition_id, script_id = world["rendition_id"], world["script_id"]
    scenes = world["scenes"]

    others = {
        scene.id: _digest_of(media, rendition_id, scene.id, "media_asset_id")
        for scene in scenes
        if scene.id != scenes[2].id
    }

    media.update_scene(scenes[2].id, visual_direction="A completely different shot.")
    current = media.list_scenes(script_id)
    plan = plan_regeneration(
        build_graph(world["inputs"](current)), store.recorded(rendition_id), current
    )

    assert plan.scenes_to_rerender() == [scenes[2].id]

    world["renderer"].render_rendition(
        media.get_rendition(rendition_id),
        current,
        video_recipe_id=VIDEO_RECIPE,
        render_visuals=plan.scenes_to_rerender(),
        render_narration=[],
    )

    for scene_id, digest in others.items():
        assert _digest_of(media, rendition_id, scene_id, "media_asset_id") == digest


def test_a_rebuilt_rendition_stops_being_stale(world) -> None:
    """The loop closes: build, record, and nothing is outstanding."""
    media, store = world["media"], world["store"]
    rendition_id, script_id = world["rendition_id"], world["script_id"]

    media.update_scene(world["scenes"][0].id, narration="Changed.")
    current = media.list_scenes(script_id)

    graph = build_graph(world["inputs"](current))
    assert graph.stale(store.recorded(rendition_id))

    world["renderer"].render_rendition(
        media.get_rendition(rendition_id),
        current,
        video_recipe_id=VIDEO_RECIPE,
        narration_recipe_id=SPEECH_RECIPE,
        render_visuals=[],
        render_narration=[world["scenes"][0].id],
    )
    world["assembler"].assemble(media.get_rendition(rendition_id), current)
    store.record(rendition_id, graph.snapshot())

    assert build_graph(world["inputs"](current)).stale(store.recorded(rendition_id)) == set()


def test_nothing_is_stale_when_nothing_changed(world) -> None:
    media, store = world["media"], world["store"]
    current = media.list_scenes(world["script_id"])
    graph = build_graph(world["inputs"](current))
    assert graph.stale(store.recorded(world["rendition_id"])) == set()


def test_the_store_forgets_on_request(world) -> None:
    """ "Rebuild everything" has to be expressible, for when a fingerprint is
    wrong in a way nobody can see."""
    store, rendition_id = world["store"], world["rendition_id"]
    current = world["media"].list_scenes(world["script_id"])
    graph = build_graph(world["inputs"](current))

    store.forget(rendition_id)
    assert store.recorded(rendition_id) == {}
    assert graph.stale(store.recorded(rendition_id)) == {n.id for n in graph.nodes()}


def test_forgetting_one_node_rebuilds_only_it_and_its_dependents(world) -> None:
    store, rendition_id = world["store"], world["rendition_id"]
    scenes = world["scenes"]
    current = world["media"].list_scenes(world["script_id"])
    graph = build_graph(world["inputs"](current))

    store.forget(rendition_id, [visual_node(scenes[0].id)])
    stale = graph.stale(store.recorded(rendition_id))

    assert visual_node(scenes[0].id) in stale
    assert visual_node(scenes[1].id) not in stale
    assert speech_node(scenes[0].id) not in stale


def test_a_failed_render_is_not_recorded_as_fresh(world) -> None:
    """Recording a fingerprint for work that failed would make the failure
    permanent and invisible: the next run would skip it."""
    store, rendition_id = world["store"], world["rendition_id"]
    before = dict(store.recorded(rendition_id))

    store.record(rendition_id, {})

    assert store.recorded(rendition_id) == before
