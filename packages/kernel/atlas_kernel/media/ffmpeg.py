"""The one place Atlas shells out to ffmpeg.

Everything that touches media files goes through here, so there is exactly one
answer to "is ffmpeg present", "what went wrong" and "how long is this file".

Two rules this module exists to enforce:

* **A failure names itself.** ffmpeg writes its real diagnosis to stderr and
  then exits 1. Swallowing that leaves "assembly failed" in a log and nothing
  to act on, which is the same mistake that made the RC1 AppImage undiagnosable
  for two days.
* **No text filters.** ``drawtext`` needs ffmpeg built against libfreetype and
  ``subtitles`` needs libass; Homebrew's build has neither. Text is rendered to
  a transparent PNG by ``overlays.py`` and composited with ``overlay``, which
  works on every build there is.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

#: Long enough for a real assembly, short enough that a hung ffmpeg is noticed.
DEFAULT_TIMEOUT_SECONDS = 600


class FfmpegError(RuntimeError):
    """ffmpeg failed, with its own explanation attached."""


class FfmpegMissing(FfmpegError):
    """No ffmpeg on this machine.

    Its own type because it is a setup problem, not a media problem, and the
    caller should say so rather than reporting a broken video.
    """


@dataclass(frozen=True)
class MediaInfo:
    """What ffprobe says about a file that already exists."""

    duration_seconds: float
    width: int | None
    height: int | None
    has_video: bool
    has_audio: bool


def _binary(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise FfmpegMissing(
            f"{name} was not found on PATH. Atlas does not bundle it: install it "
            "with your package manager (`brew install ffmpeg`, `apt install ffmpeg`)."
        )
    return found


def available() -> bool:
    """True when both ffmpeg and ffprobe are usable."""
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def run(args: list[str], *, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> None:
    """Run ffmpeg with the given arguments.

    ``-nostdin`` matters: without it a failing ffmpeg can sit waiting on a
    prompt nobody will ever answer, and the caller sees a hang rather than an
    error.
    """
    command = [_binary("ffmpeg"), "-nostdin", "-hide_banner", "-loglevel", "error", *args]
    try:
        completed = subprocess.run(  # noqa: S603 - fixed binary, list form, no shell
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise FfmpegError(f"ffmpeg did not finish within {timeout}s") from error

    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        tail = "\n".join(stderr.splitlines()[-12:]) or "(no output)"
        raise FfmpegError(f"ffmpeg exited {completed.returncode}.\n{tail}")


def probe(path: Path) -> MediaInfo:
    """Ask ffprobe what a file actually contains.

    Used to verify output rather than trust it. A render that produced a
    zero-length file or dropped its audio track should fail loudly at the point
    it happened, not silently three stages later during assembly.
    """
    command = [
        _binary("ffprobe"),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    completed = subprocess.run(  # noqa: S603 - fixed binary, list form, no shell
        command, capture_output=True, text=True, timeout=60, check=False
    )
    if completed.returncode != 0:
        raise FfmpegError(f"ffprobe could not read {path.name}: {(completed.stderr or '').strip()}")

    payload = json.loads(completed.stdout or "{}")
    streams = payload.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    duration = payload.get("format", {}).get("duration")
    # Some containers only carry duration on the stream, not the format.
    if duration is None and video is not None:
        duration = video.get("duration")
    if duration is None and audio is not None:
        duration = audio.get("duration")

    return MediaInfo(
        duration_seconds=float(duration) if duration is not None else 0.0,
        width=int(video["width"]) if video and "width" in video else None,
        height=int(video["height"]) if video and "height" in video else None,
        has_video=video is not None,
        has_audio=audio is not None,
    )
