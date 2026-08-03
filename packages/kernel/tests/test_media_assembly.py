"""Assembly: generic layer, timeline, and the video implementation (M013 step 4).

The demo this step owes: rendered scenes become one watchable MP4 with
narration, captions, music and transitions.

The layering tests matter as much as the output ones. Assembly must not become
a video module wearing a general name, or podcasts and blog posts later arrive
to find "generic" code full of frame rates.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from uuid import uuid4

import pytest

from atlas_kernel import db
from atlas_kernel.composition_root import create_runtime
from atlas_kernel.media import capabilities, ffmpeg
from atlas_kernel.media.assembly import base as assembly_base
from atlas_kernel.media.assembly import timeline as assembly_timeline
from atlas_kernel.media.assembly.base import (
    AssemblerRegistry,
    AssemblyError,
    AssemblyRequest,
    AssemblyResult,
    NoAssemblerAvailable,
    SceneMaterial,
)
from atlas_kernel.media.assembly.timeline import (
    build_cues,
    build_segments,
    scene_duration,
    to_srt,
)
from atlas_kernel.media.assembly.video import VideoAssembler, VideoFormat
from atlas_kernel.media.assembly_service import AssemblyService
from atlas_kernel.media.models import Episode, Rendition, RenditionKind, Scene, Script, Series
from atlas_kernel.media.providers.base import RenderRequest
from atlas_kernel.media.providers.mock import (
    MockMusicProvider,
    MockNarrationProvider,
    MockVideoProvider,
)
from atlas_kernel.media.recipes import RecipeRegistry, default_root
from atlas_kernel.media.registry import MediaProviderRegistry, ProviderRegistration
from atlas_kernel.media.render_service import SceneRenderService
from atlas_kernel.media.repository import MediaRepository

pytestmark = pytest.mark.skipif(
    not ffmpeg.available(), reason="ffmpeg and ffprobe are required for media tests"
)

db.init_db()

FAST = VideoFormat(width=320, height=180, fps=12, preset="ultrafast", crf=30)


def _scene(index: int, narration: str = "", seconds: float = 1.0) -> Scene:
    return Scene(
        script_id="script",
        index=index,
        heading=f"Beat {index}",
        narration=narration,
        visual_direction=f"A shot, beat {index}.",
        target_seconds=seconds,
    )


@pytest.fixture
def clips(tmp_path: Path):
    """Real rendered scenes to assemble from."""
    video = MockVideoProvider(workspace=tmp_path / "v")
    speech = MockNarrationProvider(workspace=tmp_path / "a")

    def build(scenes: list[Scene], *, with_audio: bool = True) -> list[SceneMaterial]:
        out = []
        for scene in scenes:
            handle = video.submit(
                RenderRequest(
                    recipe_id="r",
                    prompt=scene.visual_direction,
                    duration_seconds=scene.target_seconds,
                    width=320,
                    height=180,
                    labels={"scene_index": str(scene.index), "heading": scene.heading},
                )
            )
            media = video.fetch(handle, tmp_path / f"clip{scene.index}.mp4")
            audio = None
            if with_audio and scene.narration:
                ah = speech.submit(RenderRequest(recipe_id="r", prompt=scene.narration))
                audio = speech.fetch(ah, tmp_path / f"clip{scene.index}.m4a")
            out.append(SceneMaterial(scene=scene, media_path=media, audio_path=audio))
        return out

    return build


# -- the generic layer stays generic --------------------------------------


def _executable_source(module) -> str:
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    node.body = body[1:]
    return ast.unparse(tree).lower()


@pytest.mark.parametrize("module", [assembly_base, assembly_timeline])
def test_the_generic_layer_never_mentions_video(module) -> None:
    """Assembly must not be a video module with a general name on it.

    Prose may explain the distinction; executable code may not depend on it.
    """
    code = _executable_source(module)
    for term in ("ffmpeg", "codec", "libx264", "mp4", "fps", "resolution", "subtitle"):
        assert term not in code, (
            f"{module.__name__} references {term!r} in executable code. That belongs in "
            "an assembler, not the layer every output form shares."
        )


def test_the_registry_dispatches_on_kind() -> None:
    """A caller says "assemble this rendition" and never asks what kind it is."""
    registry = AssemblerRegistry()

    class PodcastAssembler:
        kind = RenditionKind.PODCAST

        def assemble(self, request: AssemblyRequest) -> AssemblyResult:
            return AssemblyResult(output=request.output, metadata={"who": "podcast"})

    registry.register(VideoAssembler())
    registry.register(PodcastAssembler())

    assert registry.resolve(RenditionKind.VIDEO_1080P).kind is RenditionKind.VIDEO_1080P
    assert registry.resolve(RenditionKind.PODCAST).kind is RenditionKind.PODCAST
    assert RenditionKind.PODCAST in registry.kinds()


def test_an_unregistered_kind_is_a_configuration_error() -> None:
    with pytest.raises(NoAssemblerAvailable, match="text/blog"):
        AssemblerRegistry().resolve(RenditionKind.BLOG_POST)


def test_a_material_without_media_is_legitimate() -> None:
    """A blog assembler reads the scene and ignores the rest."""
    material = SceneMaterial(scene=_scene(0, "words"))
    assert material.media_path is None
    assert material.index == 0


# -- timeline -------------------------------------------------------------


def test_narration_decides_how_long_a_scene_runs() -> None:
    """Cutting a scene while someone is still speaking is the most obvious
    defect a viewer can hear."""
    material = SceneMaterial(scene=_scene(0, "words", seconds=2.0))
    assert scene_duration(material, media_seconds=2.0, audio_seconds=7.5) == 7.5
    assert scene_duration(material, media_seconds=9.0, audio_seconds=3.0) == 9.0
    assert scene_duration(material, media_seconds=None, audio_seconds=None) == 2.0


def test_transitions_shorten_the_timeline() -> None:
    """A crossfade overlaps its neighbours. Ignoring that drifts every later
    caption."""
    materials = [SceneMaterial(scene=_scene(i)) for i in range(3)]
    durations = {m.scene.id: 4.0 for m in materials}

    hard = build_segments(materials, durations, transition_seconds=0.0)
    assert [s.start for s in hard] == [0.0, 4.0, 8.0]

    faded = build_segments(materials, durations, transition_seconds=0.5)
    assert [s.start for s in faded] == [0.0, 3.5, 7.0]


def test_cues_belong_to_a_scene_not_a_time_window() -> None:
    """The defect this caught: with transitions, neighbouring scenes overlap by
    design, so selecting captions by overlap burns every scene's text onto all
    of them."""
    materials = [SceneMaterial(scene=_scene(i, f"Narration {i}.")) for i in range(3)]
    durations = {m.scene.id: 4.0 for m in materials}
    segments = build_segments(materials, durations, transition_seconds=0.5)
    cues = build_cues(segments)

    assert len(cues) == 3
    for material, cue in zip(materials, cues, strict=True):
        assert cue.scene_id == material.scene.id
        assert cue.text == material.scene.narration

    # Overlap really does exist -- which is why ownership is needed.
    assert cues[1].start < segments[0].end


def test_a_scene_without_narration_produces_no_cue() -> None:
    materials = [SceneMaterial(scene=_scene(0, "")), SceneMaterial(scene=_scene(1, "Words."))]
    durations = {m.scene.id: 3.0 for m in materials}
    cues = build_cues(build_segments(materials, durations))
    assert len(cues) == 1
    assert cues[0].scene_id == materials[1].scene.id


def test_long_narration_is_split_into_several_cues() -> None:
    """A caption nobody can read in the time available is not a caption."""
    long_text = (
        "Atlas bundles its own database. Installing Atlas installs nothing else. "
        "The kernel starts PostgreSQL on a free loopback port when it first runs."
    )
    materials = [SceneMaterial(scene=_scene(0, long_text, seconds=12.0))]
    cues = build_cues(build_segments(materials, {materials[0].scene.id: 12.0}))

    assert len(cues) > 1
    assert all(cue.scene_id == materials[0].scene.id for cue in cues)
    # The caption track ends with the scene, not before or after it.
    assert cues[-1].end == pytest.approx(12.0, abs=0.01)


def test_srt_is_well_formed() -> None:
    materials = [SceneMaterial(scene=_scene(0, "Hello there."))]
    srt = to_srt(build_cues(build_segments(materials, {materials[0].scene.id: 2.5})))
    assert srt.startswith("1\n00:00:00,000 --> 00:00:02,500\nHello there.")


# -- the video assembler --------------------------------------------------


def test_scenes_become_one_watchable_video(clips, tmp_path: Path) -> None:
    """The demo this step owes."""
    scenes = [
        _scene(0, "Atlas bundles its own database."),
        _scene(1, "Every render records how it was made."),
        _scene(2, "One scene failing is one scene failing."),
    ]
    materials = clips(scenes)

    result = VideoAssembler(FAST).assemble(
        AssemblyRequest(
            rendition=Rendition(episode_id="e", script_id="s"),
            materials=materials,
            output=tmp_path / "final.mp4",
        )
    )

    info = ffmpeg.probe(result.output)
    assert info.has_video and info.has_audio
    assert (info.width, info.height) == (320, 180)
    assert result.metadata["scenes"] == 3
    assert result.metadata["cue_count"] == 3


def test_the_finished_length_matches_the_timeline(clips, tmp_path: Path) -> None:
    """Transition arithmetic is silent when wrong -- it produces a video of the
    wrong length rather than an error."""
    scenes = [_scene(i, f"Narration number {i}.", seconds=2.0) for i in range(3)]
    materials = clips(scenes)

    assembler = VideoAssembler(FAST)
    result = assembler.assemble(
        AssemblyRequest(
            rendition=Rendition(episode_id="e", script_id="s"),
            materials=materials,
            output=tmp_path / "final.mp4",
            options={"transition_seconds": 0.5},
        )
    )

    durations = result.metadata["scene_durations"]
    expected = sum(durations.values()) - 0.5 * (len(durations) - 1)
    assert result.duration_seconds == pytest.approx(expected, abs=0.35)


def test_hard_cuts_are_supported(clips, tmp_path: Path) -> None:
    """Perfectly legitimate for a talking piece, and cheaper."""
    materials = clips([_scene(i, f"Line {i}.") for i in range(2)])
    result = VideoAssembler(FAST).assemble(
        AssemblyRequest(
            rendition=Rendition(episode_id="e", script_id="s"),
            materials=materials,
            output=tmp_path / "cuts.mp4",
            options={"transition_seconds": 0},
        )
    )
    assert result.metadata["transition_seconds"] == 0
    assert ffmpeg.probe(result.output).has_video


def test_a_transition_cannot_outlast_the_scenes_it_joins(clips, tmp_path: Path) -> None:
    """Otherwise ffmpeg produces a shorter piece than the timeline predicts and
    every caption after it drifts."""
    materials = clips([_scene(i, f"Line {i}.", seconds=1.0) for i in range(2)])
    result = VideoAssembler(FAST).assemble(
        AssemblyRequest(
            rendition=Rendition(episode_id="e", script_id="s"),
            materials=materials,
            output=tmp_path / "clamped.mp4",
            options={"transition_seconds": 30.0},
        )
    )
    shortest = min(result.metadata["scene_durations"].values())
    assert result.metadata["transition_seconds"] <= shortest / 2


def test_music_is_mixed_without_extending_the_video(clips, tmp_path: Path) -> None:
    """A bed longer than the piece must not leave a black tail with a
    soundtrack."""
    materials = clips([_scene(i, f"Line {i}.", seconds=1.5) for i in range(2)])

    music_provider = MockMusicProvider(workspace=tmp_path / "m")
    handle = music_provider.submit(
        RenderRequest(recipe_id="r", prompt="bed", duration_seconds=120.0)
    )
    music = music_provider.fetch(handle, tmp_path / "bed.m4a")

    assembler = VideoAssembler(FAST)
    without = assembler.assemble(
        AssemblyRequest(
            rendition=Rendition(episode_id="e", script_id="s"),
            materials=materials,
            output=tmp_path / "dry.mp4",
        )
    )
    with_music = assembler.assemble(
        AssemblyRequest(
            rendition=Rendition(episode_id="e", script_id="s"),
            materials=materials,
            output=tmp_path / "wet.mp4",
            music_path=music,
        )
    )

    assert with_music.metadata["music"] is True
    assert with_music.duration_seconds == pytest.approx(without.duration_seconds, abs=0.3)


def test_a_caption_sidecar_is_written(clips, tmp_path: Path) -> None:
    """YouTube takes one, and a sidecar beats burned text there -- it can be
    turned off, translated and read by search."""
    materials = clips([_scene(0, "Atlas bundles its own database.")])
    result = VideoAssembler(FAST).assemble(
        AssemblyRequest(
            rendition=Rendition(episode_id="e", script_id="s"),
            materials=materials,
            output=tmp_path / "final.mp4",
        )
    )
    sidecar = Path(result.metadata["subtitle_sidecar"])
    assert sidecar.exists()
    assert "Atlas bundles its own database." in sidecar.read_text()


def test_subtitles_can_be_left_unburned(clips, tmp_path: Path) -> None:
    materials = clips([_scene(0, "Words.")])
    result = VideoAssembler(FAST).assemble(
        AssemblyRequest(
            rendition=Rendition(episode_id="e", script_id="s"),
            materials=materials,
            output=tmp_path / "clean.mp4",
            options={"burn_subtitles": False},
        )
    )
    assert result.metadata["subtitles_burned"] is False
    # The sidecar is written regardless: the cues exist either way.
    assert Path(result.metadata["subtitle_sidecar"]).exists()


def test_a_scene_without_narration_still_assembles(clips, tmp_path: Path) -> None:
    """Silence rather than no track: a segment missing audio would
    desynchronise the join."""
    materials = clips([_scene(0, ""), _scene(1, "Only this one speaks.")], with_audio=False)
    result = VideoAssembler(FAST).assemble(
        AssemblyRequest(
            rendition=Rendition(episode_id="e", script_id="s"),
            materials=materials,
            output=tmp_path / "quiet.mp4",
        )
    )
    assert ffmpeg.probe(result.output).has_audio is True


def test_assembly_refuses_to_paper_over_a_missing_render(tmp_path: Path) -> None:
    """Assembly builds a cut from what exists; it does not render. Quietly
    dropping a scene would produce a video shorter than the script asked for."""
    materials = [SceneMaterial(scene=_scene(0, "words"))]
    with pytest.raises(AssemblyError, match="no rendered media"):
        VideoAssembler(FAST).assemble(
            AssemblyRequest(
                rendition=Rendition(episode_id="e", script_id="s"),
                materials=materials,
                output=tmp_path / "x.mp4",
            )
        )


def test_an_empty_rendition_is_refused(tmp_path: Path) -> None:
    with pytest.raises(AssemblyError, match="at least one scene"):
        VideoAssembler(FAST).assemble(
            AssemblyRequest(
                rendition=Rendition(episode_id="e", script_id="s"),
                materials=[],
                output=tmp_path / "x.mp4",
            )
        )


# -- the service ----------------------------------------------------------


def test_render_then_assemble_lands_a_finished_video_in_the_library(tmp_path: Path) -> None:
    """Script to scenes to renders to one finished asset, all real."""
    media = MediaRepository()
    runtime = create_runtime()

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
    recipes = RecipeRegistry(default_root()).load()

    SceneRenderService(
        media_repository=media,
        providers=providers,
        recipes=recipes,
        asset_service=runtime.asset_service,
        workspace=tmp_path / "renders",
        poll_interval=0.01,
    ).render_rendition(
        rendition,
        scenes,
        video_recipe_id="mock-slate-1080p",
        narration_recipe_id="mock-narration",
    )

    assemblers = AssemblerRegistry()
    assemblers.register(VideoAssembler(FAST))

    asset = AssemblyService(
        media_repository=media,
        assemblers=assemblers,
        asset_service=runtime.asset_service,
        workspace=tmp_path / "assembly",
        providers=providers,
        recipes=recipes,
    ).assemble(
        media.get_rendition(rendition.id),
        scenes,
        music_recipe_id="mock-music-bed",
        options={"transition_seconds": 0.25},
    )

    from atlas_kernel.media.assembly_service import stored_path

    info = ffmpeg.probe(stored_path(asset.uri))
    assert info.has_video and info.has_audio
    assert info.duration_seconds > 2.0

    finished = media.get_rendition(rendition.id)
    assert finished is not None
    assert finished.asset_id == asset.id
    assert finished.scene_fingerprint != ""
    assert finished.build_metadata["assembly"]["scenes"] == 3
    assert finished.build_metadata["assembler_kind"] == "video/1080p"
    assert finished.is_stale_against(scenes) is False


def test_missing_music_does_not_fail_an_assembly(tmp_path: Path) -> None:
    """A video without a bed is publishable. A video that does not exist is
    not."""
    media = MediaRepository()
    runtime = create_runtime()
    service = AssemblyService(
        media_repository=media,
        assemblers=AssemblerRegistry(),
        asset_service=runtime.asset_service,
        workspace=tmp_path,
        providers=MediaProviderRegistry(),  # nothing registered for music
        recipes=RecipeRegistry(default_root()).load(),
    )
    assert service._music("mock-music-bed", 10.0, tmp_path) is None  # noqa: SLF001
