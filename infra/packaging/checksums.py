#!/usr/bin/env python3
"""Generate and verify SHA-256 checksums for release artifacts.

Alpha builds are unsigned, so a checksum is the only integrity signal a user
has. This produces the same `sha256sum`-compatible format CI publishes, so a
locally built artifact can be checked the same way as a downloaded one.

    python3 infra/packaging/checksums.py generate dist-release/
    python3 infra/packaging/checksums.py verify dist-release/
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

CHECKSUM_FILE = "SHA256SUMS.txt"
CHUNK = 1024 * 1024

#: Not artifacts. Including the checksum file in its own manifest is a
#: chicken-and-egg problem, and macOS drops .DS_Store into everything.
SKIP = {CHECKSUM_FILE, ".DS_Store"}


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            sha.update(chunk)
    return sha.hexdigest()


def artifacts(directory: Path) -> list[Path]:
    return sorted(p for p in directory.iterdir() if p.is_file() and p.name not in SKIP)


def generate(directory: Path) -> int:
    files = artifacts(directory)
    if not files:
        print(f"no artifacts in {directory}", file=sys.stderr)
        return 1

    lines = []
    for path in files:
        value = digest(path)
        size_mb = path.stat().st_size / 1_048_576
        # Two spaces then the bare filename: the sha256sum format, so
        # `sha256sum -c SHA256SUMS.txt` works unmodified.
        lines.append(f"{value}  {path.name}")
        print(f"  {value}  {path.name}  ({size_mb:.0f} MB)")

    (directory / CHECKSUM_FILE).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nwrote {directory / CHECKSUM_FILE} ({len(files)} artifacts)")
    return 0


def verify(directory: Path) -> int:
    manifest = directory / CHECKSUM_FILE
    if not manifest.exists():
        print(f"{manifest} not found", file=sys.stderr)
        return 1

    expected: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value, _, name = line.partition("  ")
        expected[name.strip()] = value.strip()

    failures = 0
    for name, want in expected.items():
        path = directory / name
        if not path.exists():
            print(f"  MISSING  {name}")
            failures += 1
            continue
        got = digest(path)
        if got == want:
            print(f"  OK       {name}")
        else:
            print(f"  MISMATCH {name}\n           expected {want}\n           actual   {got}")
            failures += 1

    # An artifact present but unlisted is also a problem: it means the manifest
    # was generated before the build finished.
    for path in artifacts(directory):
        if path.name not in expected:
            print(f"  UNLISTED {path.name}")
            failures += 1

    print(f"\n{len(expected) - failures} of {len(expected)} verified")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("generate", "verify"))
    parser.add_argument("directory", type=Path, nargs="?", default=Path("dist-release"))
    args = parser.parse_args()

    if not args.directory.is_dir():
        print(f"{args.directory} is not a directory", file=sys.stderr)
        return 1

    return generate(args.directory) if args.action == "generate" else verify(args.directory)


if __name__ == "__main__":
    raise SystemExit(main())
