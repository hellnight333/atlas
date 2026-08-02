#!/usr/bin/env python3
"""Generate the Atlas icon set from one vector-ish definition.

Run this rather than hand-editing PNGs, so every size stays consistent and a
change to the mark propagates everywhere.

    python3 infra/packaging/make_icons.py

Produces everything ``tauri.conf.json`` references, plus the favicon and
social-preview assets the website needs.

The mark: a bright kernel at the centre, three satellites on a ring, joined by
spokes. It is the architecture diagram reduced until it still reads at 16px --
everything flows through the middle.
"""

from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parents[2]
TAURI_ICONS = REPO / "apps" / "desktop" / "src-tauri" / "icons"
WEB_ASSETS = REPO / "website" / "assets"

#: Rendered at 8x then downsampled -- PIL has no anti-aliased vector drawing,
#: so supersampling is what keeps the curves clean.
SUPERSAMPLE = 8

BACKGROUND_TOP = (18, 20, 28)
BACKGROUND_BOTTOM = (30, 34, 51)
CORE = (245, 247, 250)
SATELLITE = (255, 180, 84)
SPOKE = (110, 122, 158)


def _gradient(size: int) -> Image.Image:
    """Vertical gradient background."""
    image = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / max(size - 1, 1)
        image.putpixel(
            (0, y),
            tuple(
                round(BACKGROUND_TOP[i] + (BACKGROUND_BOTTOM[i] - BACKGROUND_TOP[i]) * t)
                for i in range(3)
            ),
        )
    return image.resize((size, size), Image.Resampling.NEAREST)


def _rounded_mask(size: int, radius_ratio: float = 0.225) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=int(size * radius_ratio), fill=255
    )
    return mask


def render(size: int, rounded: bool = True) -> Image.Image:
    """Render the Atlas mark at ``size`` pixels."""
    s = size * SUPERSAMPLE
    canvas = _gradient(s).convert("RGBA")
    draw = ImageDraw.Draw(canvas)

    centre = s / 2
    ring_radius = s * 0.255
    core_radius = s * 0.105
    satellite_radius = s * 0.062
    spoke_width = max(int(s * 0.018), 1)

    # Three satellites, first one pointing straight up.
    angles = [-90, 30, 150]
    points = [
        (
            centre + ring_radius * math.cos(math.radians(a)),
            centre + ring_radius * math.sin(math.radians(a)),
        )
        for a in angles
    ]

    # Spokes first so the nodes sit on top of them.
    for x, y in points:
        draw.line((centre, centre, x, y), fill=SPOKE + (255,), width=spoke_width)

    for x, y in points:
        draw.ellipse(
            (
                x - satellite_radius,
                y - satellite_radius,
                x + satellite_radius,
                y + satellite_radius,
            ),
            fill=SATELLITE + (255,),
        )

    draw.ellipse(
        (
            centre - core_radius,
            centre - core_radius,
            centre + core_radius,
            centre + core_radius,
        ),
        fill=CORE + (255,),
    )

    canvas = canvas.resize((size, size), Image.Resampling.LANCZOS)
    if rounded:
        canvas.putalpha(
            _rounded_mask(size * SUPERSAMPLE).resize((size, size), Image.Resampling.LANCZOS)
        )
    return canvas


def write_png(path: Path, size: int, rounded: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    render(size, rounded=rounded).save(path, "PNG")
    print(f"  {path.relative_to(REPO)}  {size}x{size}")


def build_icns(destination: Path) -> bool:
    """macOS .icns via iconutil. Returns False when not on macOS."""
    if sys.platform != "darwin":
        return False
    iconset = destination.parent / "atlas.iconset"
    iconset.mkdir(parents=True, exist_ok=True)
    for size in (16, 32, 128, 256, 512):
        render(size).save(iconset / f"icon_{size}x{size}.png", "PNG")
        render(size * 2).save(iconset / f"icon_{size}x{size}@2x.png", "PNG")
    subprocess.run(
        ["iconutil", "-c", "icns", str(iconset), "-o", str(destination)],
        check=True,
        capture_output=True,
    )
    for child in iconset.iterdir():
        child.unlink()
    iconset.rmdir()
    print(f"  {destination.relative_to(REPO)}")
    return True


def build_ico(destination: Path) -> None:
    """Windows .ico — a multi-resolution PNG container."""
    sizes = [16, 24, 32, 48, 64, 128, 256]
    render(256).save(destination, format="ICO", sizes=[(s, s) for s in sizes])
    print(f"  {destination.relative_to(REPO)}")


def main() -> int:
    print("Application icons:")
    for size in (32, 128, 256, 512):
        write_png(TAURI_ICONS / f"{size}x{size}.png", size)
    write_png(TAURI_ICONS / "128x128@2x.png", 256)
    write_png(TAURI_ICONS / "icon.png", 512)

    build_ico(TAURI_ICONS / "icon.ico")
    if not build_icns(TAURI_ICONS / "icon.icns"):
        print("  icon.icns skipped — requires macOS (iconutil). CI builds it on macos-latest.")

    print("Web assets:")
    write_png(WEB_ASSETS / "favicon-32.png", 32)
    write_png(WEB_ASSETS / "favicon-180.png", 180)
    write_png(WEB_ASSETS / "logo-512.png", 512)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
