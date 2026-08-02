#!/usr/bin/env python3
"""Build a macOS .dmg from a built .app, without scripting the Finder.

Tauri's bundled `bundle_dmg.sh` drives Finder over AppleScript to set the
window background and icon positions. That needs an interactive GUI session
with Automation permission, and fails with `AppleEvent timed out (-1712)` on a
headless machine or a CI runner that has not granted it.

The prettiness is cosmetic. What a user needs is a disk image containing the
app and a shortcut to /Applications, and `hdiutil` produces that with no GUI
involvement at all. This trades a styled window for a build that works
everywhere, every time.

    python3 infra/packaging/make_dmg.py path/to/Atlas.app --output dist-release
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def run(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(
            f"{command[0]} failed ({result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result.stdout


def build_dmg(app: Path, output: Path, volume_name: str | None = None) -> Path:
    if not app.exists():
        raise SystemExit(f"{app} does not exist")
    if app.suffix != ".app":
        raise SystemExit(f"{app} is not a .app bundle")

    volume = volume_name or app.stem
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / "staging"
        staging.mkdir()

        print(f"  staging {app.name}")
        # copytree with symlinks=True: a .app contains symlinked frameworks,
        # and following them would both bloat the image and break signing.
        shutil.copytree(app, staging / app.name, symlinks=True)

        # The drag-to-install affordance. A plain symlink is exactly what the
        # styled installers create; only the background art is missing.
        (staging / "Applications").symlink_to("/Applications")

        print("  creating compressed image")
        run(
            [
                "hdiutil",
                "create",
                "-volname",
                volume,
                "-srcfolder",
                str(staging),
                "-ov",
                # UDZO is zlib-compressed and read-only, which is what a
                # distributed image should be.
                "-format",
                "UDZO",
                "-fs",
                "HFS+",
                str(output),
            ]
        )

    size_mb = output.stat().st_size / 1_048_576
    print(f"  built {output} ({size_mb:.0f} MB)")
    return output


def verify(dmg: Path) -> None:
    """Mount, confirm the app is inside, unmount. A DMG that will not attach
    is worse than no DMG, and that is only discoverable by attaching it."""
    print("  verifying")
    output = run(["hdiutil", "attach", str(dmg), "-nobrowse", "-readonly"])
    mount_point = None
    device = None
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[-1].strip().startswith("/Volumes/"):
            mount_point = Path(parts[-1].strip())
            device = parts[0].strip()
            break

    try:
        if mount_point is None:
            raise SystemExit("the image attached but no volume appeared")
        apps = list(mount_point.glob("*.app"))
        if not apps:
            raise SystemExit(f"no .app inside {mount_point}")
        if not (mount_point / "Applications").exists():
            raise SystemExit("the Applications shortcut is missing")
        print(f"  contains {apps[0].name} and an Applications shortcut")
    finally:
        if device:
            subprocess.run(
                ["hdiutil", "detach", device, "-force"],
                capture_output=True,
                check=False,
            )


def main() -> int:
    if sys.platform != "darwin":
        print("DMGs can only be built on macOS", file=sys.stderr)
        return 1

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path, help="Path to the built .app bundle")
    parser.add_argument("--output", type=Path, default=Path("dist-release"))
    parser.add_argument("--name", default=None, help="Output filename (without .dmg)")
    parser.add_argument("--volname", default=None)
    parser.add_argument("--skip-verify", action="store_true")
    args = parser.parse_args()

    name = args.name or args.app.stem
    destination = args.output if args.output.suffix == ".dmg" else args.output / f"{name}.dmg"

    dmg = build_dmg(args.app, destination, args.volname)
    if not args.skip_verify:
        verify(dmg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
