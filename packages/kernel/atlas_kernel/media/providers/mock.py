"""Stand-in providers that produce real media.

The GPU worker is not here yet, so generation has to be mocked. *Where* the
mock sits decides whether it is useful or a lie, and the seam is the provider
boundary: everything downstream -- assembly, subtitles, the approval gate, the
YouTube upload -- then runs as production code on production bytes. When the Z8
arrives, one provider is swapped and nothing else changes.

A mock returning ``{"uri": "https://example.com/..."}`` would prove nothing.
That is exactly the trap ``local-flux`` fell into, and why Atlas has a complete
orchestration layer that has never moved a single byte.

So these render actual files with ffmpeg: a real MP4 with real frames, a real
audio track of a plausible length. They are slow-ish and they use real disk,
because real work does.

**These are scaffolding, not deliverables. M013 is not complete while either is
in the path.**
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

from .. import ffmpeg, overlays
from .base import JobState, ProviderError, ProviderJobStatus, RenderRequest

#: Words per minute for a measured narrator. Used to give mock narration a
#: duration that tracks the script, so scene timing behaves like the real thing
#: rather than every scene being suspiciously identical.
SPEAKING_RATE_WPM = 150.0

#: Distinct per scene index so an assembled video can be checked for ordering
#: at a glance -- the reason the mock draws anything at all.
SLATE_COLOURS = (
    (28, 42, 74),
    (74, 28, 42),
    (28, 74, 52),
    (74, 62, 28),
    (52, 28, 74),
    (28, 66, 74),
)


def narration_seconds(text: str, *, minimum: float = 1.5) -> float:
    """How long these words would take to say.

    Mock TTS that always returned five seconds would hide every timing bug in
    assembly until real narration arrived.
    """
    words = len(text.split())
    if not words:
        return minimum
    return max(minimum, round(words / SPEAKING_RATE_WPM * 60.0, 2))


class _CompletedOnSubmit:
    """Shared behaviour for mocks that finish during ``submit``.

    The protocol is still honoured -- submit, poll, fetch -- because the point
    of the mock is to exercise the calling code, and the calling code must work
    against a provider that takes four minutes. Pretending to be asynchronous
    while actually being synchronous keeps the caller honest without inventing
    a thread pool that the real adapter will replace anyway.
    """

    name: str = "mock"

    def __init__(self, workspace: Path | None = None) -> None:
        self._root = workspace or Path(tempfile.gettempdir()) / "atlas-mock-provider"
        self._root.mkdir(parents=True, exist_ok=True)
        self._results: dict[str, Path] = {}
        self._failures: dict[str, str] = {}

    def poll(self, handle: str) -> ProviderJobStatus:
        if handle in self._failures:
            return ProviderJobStatus(
                handle=handle,
                state=JobState.FAILED,
                progress=1.0,
                detail=self._failures[handle],
            )
        if handle in self._results:
            return ProviderJobStatus(handle=handle, state=JobState.SUCCEEDED, progress=1.0)
        return ProviderJobStatus(handle=handle, state=JobState.FAILED, detail="unknown handle")

    def fetch(self, handle: str, destination: Path) -> Path:
        if handle in self._failures:
            raise ProviderError(self._failures[handle])
        source = self._results.get(handle)
        if source is None:
            raise ProviderError(f"unknown handle {handle}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        return destination


class MockVideoProvider(_CompletedOnSubmit):
    """A stand-in for ComfyUI + Wan that renders a real, playable clip.

    Each clip is a coloured slate carrying the scene index and its visual
    direction. That is deliberate: reviewing an assembled cut of five identical
    colour fields would tell you nothing about whether the scenes were ordered
    or timed correctly, which is precisely what needs checking before a GPU
    exists.
    """

    name = "mock-video"

    def submit(self, request: RenderRequest) -> str:
        handle = f"mock-video-{uuid4().hex[:12]}"
        target = self._root / f"{handle}.mp4"

        try:
            self._render(request, target)
        except ffmpeg.FfmpegError as error:
            self._failures[handle] = str(error)
            return handle

        self._results[handle] = target
        return handle

    def _render(self, request: RenderRequest, target: Path) -> None:
        index = int(request.labels.get("scene_index", "0"))
        colour = SLATE_COLOURS[index % len(SLATE_COLOURS)]
        duration = max(0.5, request.duration_seconds)
        fps = int(request.parameters.get("fps", 24))

        slate = self._root / f"{target.stem}-slate.png"
        overlays.render_slate(
            [
                request.labels.get("heading") or f"Scene {index + 1}",
                request.prompt,
                "placeholder render — no GPU provider configured",
            ],
            slate,
            width=request.width,
            height=request.height,
            background=colour,
        )

        # A still image driven for `duration`, with silent audio so every clip
        # has the same stream layout as a real render. Assembly that only ever
        # saw video-only inputs would break the first time real narration
        # arrived with an audio track attached.
        ffmpeg.run(
            [
                "-loop",
                "1",
                "-framerate",
                str(fps),
                "-t",
                f"{duration}",
                "-i",
                str(slate),
                "-f",
                "lavfi",
                "-t",
                f"{duration}",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-r",
                str(fps),
                "-c:a",
                "aac",
                "-shortest",
                "-y",
                str(target),
            ]
        )
        slate.unlink(missing_ok=True)


class MockNarrationProvider(_CompletedOnSubmit):
    """A stand-in for Kokoro/F5 that produces a real audio file.

    The audio is a quiet tone rather than speech -- synthesising speech is the
    real provider's job. What matters for everything downstream is that the file
    exists, decodes, and lasts as long as the words would take to say, so mixing
    and timing are exercised for real.
    """

    name = "mock-tts"

    def submit(self, request: RenderRequest) -> str:
        handle = f"mock-tts-{uuid4().hex[:12]}"
        target = self._root / f"{handle}.m4a"
        duration = narration_seconds(request.prompt)

        try:
            ffmpeg.run(
                [
                    "-f",
                    "lavfi",
                    "-i",
                    f"sine=frequency=220:duration={duration}:sample_rate=48000",
                    "-af",
                    "volume=0.05",
                    "-ac",
                    "2",
                    "-c:a",
                    "aac",
                    "-y",
                    str(target),
                ]
            )
        except ffmpeg.FfmpegError as error:
            self._failures[handle] = str(error)
            return handle

        self._results[handle] = target
        return handle


class MockMusicProvider(_CompletedOnSubmit):
    """A stand-in for a music provider or a licensed library.

    Produces a real, quiet bed track of the requested length so mixing, gain
    and fades are exercised against genuine audio. A soft two-tone pad rather
    than silence, because a bed that cannot be heard proves nothing about
    whether it was mixed correctly.
    """

    name = "mock-music"

    def submit(self, request: RenderRequest) -> str:
        handle = f"mock-music-{uuid4().hex[:12]}"
        target = self._root / f"{handle}.m4a"
        duration = max(1.0, request.duration_seconds)

        try:
            ffmpeg.run(
                [
                    "-f",
                    "lavfi",
                    "-i",
                    f"sine=frequency=196:duration={duration}:sample_rate=48000",
                    "-f",
                    "lavfi",
                    "-i",
                    f"sine=frequency=294:duration={duration}:sample_rate=48000",
                    "-filter_complex",
                    "[0:a][1:a]amix=inputs=2,volume=0.25[a]",
                    "-map",
                    "[a]",
                    "-ac",
                    "2",
                    "-c:a",
                    "aac",
                    "-y",
                    str(target),
                ]
            )
        except ffmpeg.FfmpegError as error:
            self._failures[handle] = str(error)
            return handle

        self._results[handle] = target
        return handle
