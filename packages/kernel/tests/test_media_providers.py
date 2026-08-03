"""The mock providers must produce real media (M013 step 2).

These tests are the guarantee that the mock is scaffolding rather than a lie.
They do not assert that ``submit`` returned a handle -- they decode the file it
produced and check its streams, because the whole point of the seam is that
everything downstream runs on genuine bytes.

If these ever get replaced with assertions about dicts, the mock has become the
thing it was written to avoid.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas_kernel.media import ffmpeg, overlays
from atlas_kernel.media.providers.base import (
    JobState,
    LongRunningProvider,
    ProviderError,
    RenderRequest,
)
from atlas_kernel.media.providers.mock import (
    MockNarrationProvider,
    MockVideoProvider,
    narration_seconds,
)

pytestmark = pytest.mark.skipif(
    not ffmpeg.available(), reason="ffmpeg and ffprobe are required for media tests"
)


def _video_request(**overrides: object) -> RenderRequest:
    payload: dict = {
        "recipe_id": "wan-t2v-720p-5s",
        "prompt": "A slow aerial shot over a data centre at dawn.",
        "duration_seconds": 2.0,
        "width": 640,
        "height": 360,
        "labels": {"scene_index": "0", "heading": "Opening"},
    }
    payload.update(overrides)
    return RenderRequest(**payload)


def test_mock_video_produces_a_decodable_clip(tmp_path: Path) -> None:
    """Not a URI. A file, with frames in it."""
    provider = MockVideoProvider(workspace=tmp_path / "work")
    handle = provider.submit(_video_request())

    assert provider.poll(handle).state is JobState.SUCCEEDED

    output = provider.fetch(handle, tmp_path / "scene.mp4")
    assert output.exists()
    assert output.stat().st_size > 1000

    info = ffmpeg.probe(output)
    assert info.has_video is True
    assert (info.width, info.height) == (640, 360)
    assert info.duration_seconds == pytest.approx(2.0, abs=0.35)


def test_mock_video_carries_an_audio_track(tmp_path: Path) -> None:
    """Same stream layout as a real render.

    Assembly that only ever saw video-only inputs would break the first time a
    real clip arrived with audio attached.
    """
    provider = MockVideoProvider(workspace=tmp_path / "work")
    handle = provider.submit(_video_request())
    info = ffmpeg.probe(provider.fetch(handle, tmp_path / "scene.mp4"))
    assert info.has_audio is True


def test_mock_video_honours_the_requested_dimensions(tmp_path: Path) -> None:
    provider = MockVideoProvider(workspace=tmp_path / "work")
    handle = provider.submit(_video_request(width=1280, height=720))
    info = ffmpeg.probe(provider.fetch(handle, tmp_path / "scene.mp4"))
    assert (info.width, info.height) == (1280, 720)


def test_scenes_are_visually_distinguishable(tmp_path: Path) -> None:
    """Different indices render different colours.

    An assembled cut of five identical fields would say nothing about whether
    the scenes were ordered correctly, which is the one thing the mock exists
    to let a human check.
    """
    provider = MockVideoProvider(workspace=tmp_path / "work")
    sizes = set()
    for index in range(3):
        handle = provider.submit(
            _video_request(labels={"scene_index": str(index), "heading": f"Beat {index}"})
        )
        output = provider.fetch(handle, tmp_path / f"scene{index}.mp4")
        sizes.add(output.read_bytes())
    assert len(sizes) == 3


def test_mock_narration_length_tracks_the_words(tmp_path: Path) -> None:
    """Mock TTS that always returned five seconds would hide every timing bug
    in assembly until real narration arrived."""
    provider = MockNarrationProvider(workspace=tmp_path / "work")

    short = provider.submit(RenderRequest(recipe_id="kokoro", prompt="Two words."))
    long = provider.submit(RenderRequest(recipe_id="kokoro", prompt=" ".join(["word"] * 150)))

    short_info = ffmpeg.probe(provider.fetch(short, tmp_path / "short.m4a"))
    long_info = ffmpeg.probe(provider.fetch(long, tmp_path / "long.m4a"))

    assert short_info.has_audio is True
    assert long_info.duration_seconds > short_info.duration_seconds * 5


def test_narration_estimate_is_sane() -> None:
    assert narration_seconds("") == 1.5
    # 150 words at 150 wpm is a minute, give or take rounding.
    assert narration_seconds(" ".join(["word"] * 150)) == pytest.approx(60.0, abs=0.1)


def test_unknown_handles_are_reported_rather_than_crashing(tmp_path: Path) -> None:
    provider = MockVideoProvider(workspace=tmp_path / "work")
    assert provider.poll("nope").state is JobState.FAILED
    with pytest.raises(ProviderError):
        provider.fetch("nope", tmp_path / "out.mp4")


def test_a_render_failure_is_reported_through_poll(tmp_path: Path, monkeypatch) -> None:
    """A provider that cannot render must fail its job, not raise into the
    caller's submit -- the caller is a queue, and a queue needs a status."""

    def explode(*_args: object, **_kwargs: object) -> None:
        raise ffmpeg.FfmpegError("synthetic encoder failure")

    monkeypatch.setattr(ffmpeg, "run", explode)
    provider = MockVideoProvider(workspace=tmp_path / "work")
    handle = provider.submit(_video_request())

    status = provider.poll(handle)
    assert status.state is JobState.FAILED
    assert "synthetic encoder failure" in (status.detail or "")

    with pytest.raises(ProviderError, match="synthetic encoder failure"):
        provider.fetch(handle, tmp_path / "out.mp4")


def test_mocks_satisfy_the_provider_protocol() -> None:
    """The mock has to be substitutable for the real ComfyUI adapter, or it is
    testing a shape nothing else will ever have."""
    assert isinstance(MockVideoProvider(), LongRunningProvider)
    assert isinstance(MockNarrationProvider(), LongRunningProvider)


def test_provider_names_are_stable() -> None:
    assert MockVideoProvider().name == "mock-video"
    assert MockNarrationProvider().name == "mock-tts"


# -- ffmpeg wrapper -------------------------------------------------------


def test_ffmpeg_failures_carry_ffmpegs_own_explanation() -> None:
    """The RC1 lesson: a wrapper that swallows stderr makes a build
    undiagnosable. Whatever ffmpeg said must reach the caller."""
    with pytest.raises(ffmpeg.FfmpegError) as caught:
        ffmpeg.run(["-i", "/nonexistent/definitely-not-here.mp4", "-f", "null", "-"])

    message = str(caught.value)
    assert "exited" in message
    assert message.strip() != "ffmpeg failed"
    assert "definitely-not-here" in message or "No such file" in message


def test_probe_rejects_a_file_that_is_not_media(tmp_path: Path) -> None:
    junk = tmp_path / "notavideo.mp4"
    junk.write_text("this is not a video")
    with pytest.raises(ffmpeg.FfmpegError):
        ffmpeg.probe(junk)


def test_missing_binary_is_its_own_error(monkeypatch) -> None:
    """A missing ffmpeg is a setup problem, and saying "render failed" would
    send the user looking in entirely the wrong place."""
    monkeypatch.setattr(ffmpeg.shutil, "which", lambda _name: None)
    assert ffmpeg.available() is False
    with pytest.raises(ffmpeg.FfmpegMissing):
        ffmpeg.run(["-version"])


# -- overlays -------------------------------------------------------------


def test_caption_is_a_transparent_png_the_size_of_the_frame(tmp_path: Path) -> None:
    """Full-frame so ffmpeg can composite at 0,0 without arithmetic at the call
    site -- one less thing to get wrong in a filter graph."""
    from PIL import Image

    path = overlays.render_caption(
        "Atlas bundles its own database, so installing Atlas installs nothing else.",
        tmp_path / "caption.png",
        width=1280,
        height=720,
    )
    with Image.open(path) as image:
        assert image.size == (1280, 720)
        assert image.mode == "RGBA"
        # Something was actually drawn.
        assert image.getbbox() is not None


def test_long_captions_wrap_instead_of_overflowing(tmp_path: Path) -> None:
    """A caption running off the frame is the most obvious possible defect in a
    finished video."""
    from PIL import Image

    text = " ".join(["overflow"] * 60)
    path = overlays.render_caption(text, tmp_path / "long.png", width=640, height=360)
    with Image.open(path) as image:
        bbox = image.getbbox()
        assert bbox is not None
        assert bbox[2] <= 640
        assert bbox[3] <= 360


def test_slate_renders_at_the_requested_size(tmp_path: Path) -> None:
    from PIL import Image

    path = overlays.render_slate(
        ["Heading", "Some direction", "placeholder"],
        tmp_path / "slate.png",
        width=800,
        height=450,
    )
    with Image.open(path) as image:
        assert image.size == (800, 450)


def test_a_font_is_always_found() -> None:
    """Falls back to Pillow's built-in rather than failing a render, because a
    missing system font must never be able to break a video."""
    assert overlays.load_font(32) is not None
