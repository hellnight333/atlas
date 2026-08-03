"""When each scene happens, and what is said while it does.

Timing is not a video concept. A podcast has chapters, a blog post has sections,
a video has subtitles -- all three are "this scene occupies this stretch of the
piece", so it is computed once here and each assembler uses it as it needs.

Subtitles are derived from the script rather than transcribed back out of the
audio. Atlas already knows the exact words: transcribing them would introduce
errors into text it authored, and would cost a model call to get a worse answer.
The ``subtitle.generate`` capability exists for the cases the script cannot
serve -- translation, or media Atlas did not write.
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import SceneMaterial

#: Below this, a caption is gone before it can be read.
MIN_CUE_SECONDS = 1.2

#: Roughly the longest line that reads comfortably at a glance. Beyond this a
#: cue is split rather than shrunk, because shrinking is what makes captions
#: unreadable on a phone.
MAX_CUE_CHARACTERS = 84


@dataclass(frozen=True)
class Cue:
    """One stretch of the piece, and the words belonging to it.

    ``scene_id`` is not decoration. Selecting a scene's captions by time
    overlap looks correct until transitions exist: a crossfade makes adjacent
    scenes overlap *by design*, so every scene picks up its neighbours' text.
    Ownership is exact; overlap is a guess.
    """

    index: int
    start: float
    end: float
    text: str
    scene_id: str = ""

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 3)


@dataclass(frozen=True)
class Segment:
    """One scene's place in the finished piece."""

    material: SceneMaterial
    start: float
    duration: float

    @property
    def end(self) -> float:
        return round(self.start + self.duration, 3)


def scene_duration(
    material: SceneMaterial,
    *,
    media_seconds: float | None,
    audio_seconds: float | None,
) -> float:
    """How long this scene should actually run.

    The longest of what was asked for and what exists. Narration decides in
    practice: cutting a scene while someone is still speaking is the most
    obvious defect a viewer can hear, and it is not recoverable by trimming
    elsewhere.
    """
    candidates = [material.scene.target_seconds]
    if media_seconds:
        candidates.append(media_seconds)
    if audio_seconds:
        candidates.append(audio_seconds)
    return round(max(candidates), 3)


def build_segments(
    materials: list[SceneMaterial],
    durations: dict[str, float],
    *,
    transition_seconds: float = 0.0,
) -> list[Segment]:
    """Lay the scenes out on a timeline.

    A crossfade overlaps its neighbours, so each transition shortens the piece
    by its own length. Ignoring that would drift every cue after the first
    transition -- subtitles sliding progressively later, which reads as sloppy
    long before anyone works out why.
    """
    segments: list[Segment] = []
    cursor = 0.0
    for position, material in enumerate(sorted(materials, key=lambda m: m.index)):
        duration = durations[material.scene.id]
        segments.append(Segment(material=material, start=round(cursor, 3), duration=duration))
        cursor += duration
        if transition_seconds and position < len(materials) - 1:
            cursor -= transition_seconds
    return segments


def build_cues(segments: list[Segment]) -> list[Cue]:
    """Subtitle cues from the script, aligned to the timeline.

    A scene with a lot to say is split across several cues, divided in
    proportion to their length so the text tracks the speech. This is an
    approximation -- real alignment needs the speech timings -- but a wrong
    guess here is a caption that lingers, not one that says the wrong thing.
    """
    cues: list[Cue] = []
    index = 0
    for segment in segments:
        text = segment.material.scene.narration.strip()
        if not text:
            continue

        for chunk_text, chunk_start, chunk_end in _split(text, segment.start, segment.duration):
            cues.append(
                Cue(
                    index=index,
                    start=round(chunk_start, 3),
                    end=round(chunk_end, 3),
                    text=chunk_text,
                    scene_id=segment.material.scene.id,
                )
            )
            index += 1
    return cues


def _split(text: str, start: float, duration: float) -> list[tuple[str, float, float]]:
    if len(text) <= MAX_CUE_CHARACTERS:
        return [(text, start, start + duration)]

    # Split on sentences first: a caption that breaks mid-clause reads badly
    # even when the timing is perfect.
    parts = _sentences(text)
    total = sum(len(part) for part in parts) or 1

    chunks: list[tuple[str, float, float]] = []
    cursor = start
    for part in parts:
        share = duration * (len(part) / total)
        share = max(share, MIN_CUE_SECONDS) if duration >= MIN_CUE_SECONDS else share
        end = min(cursor + share, start + duration)
        chunks.append((part, cursor, end))
        cursor = end
    # The last cue owns any rounding left over, so the caption track and the
    # picture end together.
    if chunks:
        text_part, chunk_start, _ = chunks[-1]
        chunks[-1] = (text_part, chunk_start, start + duration)
    return chunks


def _sentences(text: str) -> list[str]:
    out: list[str] = []
    current = ""
    for word in text.split():
        current = f"{current} {word}".strip()
        if word.endswith((".", "!", "?")) or len(current) >= MAX_CUE_CHARACTERS:
            out.append(current)
            current = ""
    if current:
        out.append(current)
    return out or [text]


def to_srt(cues: list[Cue]) -> str:
    """SubRip, for platforms that accept a caption sidecar.

    YouTube takes one, and a sidecar beats burned-in text there: it can be
    turned off, translated, and read by search.
    """
    blocks = []
    for cue in cues:
        blocks.append(
            f"{cue.index + 1}\n{_timestamp(cue.start)} --> {_timestamp(cue.end)}\n{cue.text}\n"
        )
    return "\n".join(blocks)


def _timestamp(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"
