"""Text rendered to transparent images, for ffmpeg to composite.

ffmpeg can draw text itself, but only when it was built against libfreetype,
and it can burn subtitles only with libass. Homebrew's ffmpeg has neither, and
a pipeline that works on CI and silently loses its captions on a developer's
machine is worse than one that never had them.

So text is rendered here, with Pillow, and composited with the ``overlay``
filter -- which every build of ffmpeg has. One code path, and exact control
over typography.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

#: Tried in order. The first that exists wins; the last resort is Pillow's own
#: bitmap font, which is ugly but always present, so a missing font can never
#: fail a render.
FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "C:\\Windows\\Fonts\\arialbd.ttf",
)


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _wrap(
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
    draw: ImageDraw.ImageDraw,
) -> list[str]:
    """Greedy wrap on width rather than character count.

    Character counts guess; measuring does not. A caption that overflows the
    frame is the most obvious possible defect in a finished video.
    """
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def render_caption(
    text: str,
    output: Path,
    *,
    width: int,
    height: int,
    font_size: int | None = None,
    margin_ratio: float = 0.06,
) -> Path:
    """A subtitle strip: centred text on a translucent band, transparent elsewhere.

    Sized to the full frame so ffmpeg can composite it at 0,0 without arithmetic
    at the call site -- one less thing to get wrong in a filter graph.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    size = font_size or max(18, height // 22)
    font = load_font(size)

    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    margin = int(width * margin_ratio)
    lines = _wrap(text, font, width - 2 * margin, draw)
    line_height = int(size * 1.35)
    block_height = line_height * len(lines)

    bottom = height - int(height * 0.07)
    top = bottom - block_height - size // 2

    # A band behind the text, because white-on-white is unreadable and a video
    # frame can be any colour.
    draw.rectangle(
        [(0, top - size // 3), (width, bottom + size // 3)],
        fill=(0, 0, 0, 150),
    )

    y = top
    for line in lines:
        line_width = draw.textlength(line, font=font)
        draw.text(
            ((width - line_width) / 2, y),
            line,
            font=font,
            fill=(255, 255, 255, 255),
        )
        y += line_height

    canvas.save(output, "PNG")
    return output


def render_slate(
    lines: list[str],
    output: Path,
    *,
    width: int,
    height: int,
    background: tuple[int, int, int] = (18, 22, 30),
) -> Path:
    """A full-frame card.

    Used by the mock provider so a placeholder scene is visually identifiable --
    which is the entire reason the mock draws anything at all. Reviewing an
    assembled video of five identical colour fields tells you nothing about
    whether the scenes were ordered correctly.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(canvas)

    title_size = max(24, height // 12)
    body_size = max(16, height // 26)

    y = height // 4
    for position, line in enumerate(lines):
        font = load_font(title_size if position == 0 else body_size)
        for wrapped in _wrap(line, font, int(width * 0.8), draw):
            line_width = draw.textlength(wrapped, font=font)
            draw.text(
                ((width - line_width) / 2, y),
                wrapped,
                font=font,
                fill=(235, 240, 250) if position == 0 else (150, 165, 190),
            )
            y += int((title_size if position == 0 else body_size) * 1.4)
        y += body_size // 2

    canvas.save(output, "PNG")
    return output
