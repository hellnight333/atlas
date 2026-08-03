"""Assembling scenes into a finished video.

The only module in the media package that knows what a codec is. Everything it
imports from ``base`` and ``timeline`` is medium-agnostic; everything
video-specific stops here.

Two passes, deliberately, rather than one heroic filter graph:

1. Each scene becomes a normalised segment on disk -- same resolution, frame
   rate, pixel format and sample rate, with its narration laid in and its
   captions burned on.
2. The segments are joined, transitions applied, and the music bed mixed under.

It is slower than doing it all at once and far easier to diagnose: when a video
comes out wrong, the intermediate for the offending scene is sitting on disk to
be looked at. That is worth more than the seconds it costs. Normalising first
also makes ``xfade`` safe, which refuses inputs that disagree about format.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from .. import ffmpeg, overlays
from ..models import RenditionKind
from .base import AssemblyError, AssemblyRequest, AssemblyResult, SceneMaterial
from .timeline import Cue, Segment, build_cues, build_segments, scene_duration, to_srt


@dataclass(frozen=True)
class VideoFormat:
    width: int = 1920
    height: int = 1080
    fps: int = 30
    sample_rate: int = 48000
    #: Constant Rate Factor. 20 is visually clean at 1080p without producing a
    #: file that takes an hour to upload.
    crf: int = 20
    preset: str = "medium"


class VideoAssembler:
    """Scenes to one MP4, with narration, captions, music and transitions."""

    kind = RenditionKind.VIDEO_1080P

    def __init__(self, video_format: VideoFormat | None = None) -> None:
        self.format = video_format or VideoFormat()

    def assemble(self, request: AssemblyRequest) -> AssemblyResult:
        materials = request.ordered()
        if not materials:
            raise AssemblyError("a rendition needs at least one scene to assemble")

        missing = [m.index for m in materials if m.media_path is None]
        if missing:
            raise AssemblyError(
                f"scenes {missing} have no rendered media. Assembly builds a cut from "
                "what exists; it does not render."
            )

        options = request.options
        transition = float(options.get("transition_seconds", 0.5))
        burn_subtitles = bool(options.get("burn_subtitles", True))
        music_gain = float(options.get("music_gain", 0.12))

        durations = {m.scene.id: self._duration_for(m) for m in materials}
        # A transition cannot be longer than the scenes it joins, or ffmpeg
        # produces a shorter piece than the timeline predicts and every later
        # caption drifts.
        shortest = min(durations.values())
        transition = max(0.0, min(transition, round(shortest / 2, 3)))

        segments = build_segments(materials, durations, transition_seconds=transition)
        cues = build_cues(segments)

        with tempfile.TemporaryDirectory(prefix="atlas-assembly-") as scratch:
            workspace = Path(scratch)
            normalised = [
                self._normalise(segment, workspace, cues if burn_subtitles else [])
                for segment in segments
            ]
            joined = self._join(normalised, segments, workspace, transition)
            final = self._mix_music(joined, request.music_path, request.output, music_gain)

        info = ffmpeg.probe(final)
        sidecar = request.output.with_suffix(".srt")
        sidecar.write_text(to_srt(cues), encoding="utf-8")

        return AssemblyResult(
            output=final,
            duration_seconds=info.duration_seconds,
            metadata={
                "scenes": len(materials),
                "transition_seconds": transition,
                "subtitles_burned": burn_subtitles,
                "subtitle_sidecar": str(sidecar),
                "cue_count": len(cues),
                "music": request.music_path is not None,
                "format": {
                    "width": self.format.width,
                    "height": self.format.height,
                    "fps": self.format.fps,
                    "crf": self.format.crf,
                },
                "scene_durations": {str(m.index): durations[m.scene.id] for m in materials},
            },
        )

    # -- pass 1 -----------------------------------------------------------

    def _duration_for(self, material: SceneMaterial) -> float:
        media = ffmpeg.probe(material.media_path).duration_seconds if material.media_path else None
        audio = ffmpeg.probe(material.audio_path).duration_seconds if material.audio_path else None
        return scene_duration(material, media_seconds=media, audio_seconds=audio)

    def _normalise(self, segment: Segment, workspace: Path, cues: list[Cue]) -> Path:
        """One scene, at the target format, exactly as long as the timeline says.

        The picture is stretched by holding its last frame rather than by
        slowing it down: a clip that runs short next to its narration should
        settle, not go into slow motion.
        """
        material = segment.material
        target = workspace / f"segment-{material.index:03d}.mp4"
        duration = segment.duration

        # By ownership, never by time overlap: a crossfade makes neighbouring
        # scenes overlap by design, and overlap-based selection burns every
        # scene's captions onto all of them.
        scene_cues = [c for c in cues if c.scene_id == material.scene.id]
        caption_images = [(self._caption_image(cue, segment, workspace), cue) for cue in scene_cues]

        args: list[str] = ["-i", str(material.media_path)]
        if material.audio_path:
            args += ["-i", str(material.audio_path)]
        for image, _cue in caption_images:
            args += ["-i", str(image)]

        video_chain = (
            f"[0:v]scale={self.format.width}:{self.format.height}:"
            "force_original_aspect_ratio=decrease,"
            f"pad={self.format.width}:{self.format.height}:(ow-iw)/2:(oh-ih)/2,"
            f"fps={self.format.fps},format=yuv420p,"
            f"tpad=stop_mode=clone:stop_duration={duration},"
            f"trim=duration={duration},setpts=PTS-STARTPTS"
        )

        if caption_images:
            # One overlay per cue, each enabled only for its own stretch of the
            # scene, so the caption changes with the narration instead of
            # standing still for the whole scene. Times are relative to the
            # segment, which starts at zero once it is cut out on its own.
            first_input = 2 if material.audio_path else 1
            video_chain += "[base0]"
            for position, (_image, cue) in enumerate(caption_images):
                start = max(0.0, round(cue.start - segment.start, 3))
                end = max(start, round(cue.end - segment.start, 3))
                label = "v" if position == len(caption_images) - 1 else f"base{position + 1}"
                video_chain += (
                    f";[base{position}][{first_input + position}:v]"
                    f"overlay=0:0:enable='between(t,{start},{end})'[{label}]"
                )
        else:
            video_chain += "[v]"

        if material.audio_path:
            audio_chain = (
                f"[1:a]aresample={self.format.sample_rate},"
                f"apad=whole_dur={duration},atrim=duration={duration},"
                "asetpts=PTS-STARTPTS[a]"
            )
        else:
            # Silence rather than no track at all: a segment without audio
            # would desynchronise the concat that follows.
            audio_chain = (
                f"anullsrc=channel_layout=stereo:sample_rate={self.format.sample_rate},"
                f"atrim=duration={duration},asetpts=PTS-STARTPTS[a]"
            )

        ffmpeg.run(
            [
                *args,
                "-filter_complex",
                f"{video_chain};{audio_chain}",
                "-map",
                "[v]",
                "-map",
                "[a]",
                "-c:v",
                "libx264",
                "-preset",
                self.format.preset,
                "-crf",
                str(self.format.crf),
                "-c:a",
                "aac",
                "-ar",
                str(self.format.sample_rate),
                "-t",
                f"{duration}",
                "-y",
                str(target),
            ]
        )
        return target

    def _caption_image(self, cue: Cue, segment: Segment, workspace: Path) -> Path:
        """One transparent image per cue."""
        return overlays.render_caption(
            cue.text,
            workspace / f"caption-{segment.material.index:03d}-{cue.index:03d}.png",
            width=self.format.width,
            height=self.format.height,
        )

    # -- pass 2 -----------------------------------------------------------

    def _join(
        self, segments: list[Path], laid_out: list[Segment], workspace: Path, transition: float
    ) -> Path:
        target = workspace / "joined.mp4"
        if len(segments) == 1:
            return segments[0]

        inputs: list[str] = []
        for path in segments:
            inputs += ["-i", str(path)]

        if transition <= 0:
            # Hard cuts. Cheaper and perfectly legitimate for a talking piece.
            streams = "".join(f"[{i}:v][{i}:a]" for i in range(len(segments)))
            graph = f"{streams}concat=n={len(segments)}:v=1:a=1[v][a]"
        else:
            graph = self._crossfade_graph(laid_out, transition)

        ffmpeg.run(
            [
                *inputs,
                "-filter_complex",
                graph,
                "-map",
                "[v]",
                "-map",
                "[a]",
                "-c:v",
                "libx264",
                "-preset",
                self.format.preset,
                "-crf",
                str(self.format.crf),
                "-c:a",
                "aac",
                "-ar",
                str(self.format.sample_rate),
                "-y",
                str(target),
            ]
        )
        return target

    def _crossfade_graph(self, laid_out: list[Segment], transition: float) -> str:
        """Chain xfade/acrossfade across every pair.

        The offset is cumulative and each fade overlaps its neighbours, so the
        running total shrinks by one transition per join. Getting this wrong
        does not error -- it silently produces a video of the wrong length, so
        the arithmetic is kept in one place and mirrored by ``build_segments``.
        """
        parts: list[str] = []
        video_label = "0:v"
        audio_label = "0:a"
        running = laid_out[0].duration

        for position in range(1, len(laid_out)):
            offset = round(running - transition, 3)
            next_video, next_audio = f"v{position}", f"a{position}"
            parts.append(
                f"[{video_label}][{position}:v]"
                f"xfade=transition=fade:duration={transition}:offset={offset}[{next_video}]"
            )
            parts.append(f"[{audio_label}][{position}:a]acrossfade=d={transition}[{next_audio}]")
            video_label, audio_label = next_video, next_audio
            running = round(running + laid_out[position].duration - transition, 3)

        parts.append(f"[{video_label}]null[v]")
        parts.append(f"[{audio_label}]anull[a]")
        return ";".join(parts)

    def _mix_music(self, joined: Path, music: Path | None, output: Path, gain: float) -> Path:
        """Lay a bed track under the narration.

        Mixed at a low gain and faded at both ends. ``duration=first`` matters:
        without it a music file longer than the piece extends the video past its
        own ending, leaving a black tail with a soundtrack.
        """
        output.parent.mkdir(parents=True, exist_ok=True)
        if music is None:
            (
                joined.replace(output)
                if joined.parent == output.parent
                else output.write_bytes(joined.read_bytes())
            )
            return output

        length = ffmpeg.probe(joined).duration_seconds
        fade = min(2.0, max(0.5, length / 10))

        ffmpeg.run(
            [
                "-i",
                str(joined),
                "-i",
                str(music),
                "-filter_complex",
                (
                    f"[1:a]volume={gain},afade=t=in:st=0:d={fade},"
                    f"afade=t=out:st={max(0.0, length - fade)}:d={fade},"
                    f"aresample={self.format.sample_rate}[bed];"
                    "[0:a][bed]amix=inputs=2:duration=first:dropout_transition=0[a]"
                ),
                "-map",
                "0:v",
                "-map",
                "[a]",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-ar",
                str(self.format.sample_rate),
                "-y",
                str(output),
            ]
        )
        return output
