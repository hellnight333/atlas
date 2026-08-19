#!/usr/bin/env python3
"""Re-render and re-publish every demo from the prospect records already on disk.

`prospect_pipeline.py` discovers *and* renders, which means re-running it to pick
up a template change re-queries Google Places — money spent to receive facts that
are already stored, and a fresh discovery whose result may differ from the one the
existing demos were built from. That makes it the wrong tool for a template
change: the thing under test would move at the same time as the thing being fixed.

This reads the most recent prospect file, re-renders each clinic from exactly the
stored facts, publishes a new version and promotes it. Rollback is ordinary — the
previous version is still on disk and `promote()` takes an id.

    regenerate_demos.py                 # dry run: report what would change
    regenerate_demos.py --deploy        # publish and promote
    regenerate_demos.py --records FILE  # a specific prospect file
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "kernel"))

from atlas_kernel.website.targets.public_host import PublicHostTarget  # noqa: E402
from atlas_kernel.website.verticals import dental  # noqa: E402

SITES_ROOT = Path(os.environ.get("QEVIK_SITES_ROOT", "/srv/sites"))
PUBLIC_BASE = os.environ.get("QEVIK_SITES_BASE_URL", "https://sites.qevik.ai")
PROSPECTS = Path(os.environ.get("QEVIK_PROSPECTS", "/var/lib/qevik/prospects"))


def parse_hours(lines: list[str]) -> list[tuple[str, str]] | None:
    """Google's "Monday: 11:00 AM – 8:00 PM" into (day, time) pairs.

    Splits on the first colon and nothing else. No normalising of times, no
    merging of identical days into ranges, no filling of a missing day — each of
    those is a small step from "tidier" to "a time this clinic never gave us",
    and the reader of that time is a patient deciding when to turn up.

    A line that does not split is dropped rather than guessed at.
    """
    pairs: list[tuple[str, str]] = []
    for line in lines:
        day, sep, hours = line.partition(":")
        if sep and day.strip() and hours.strip():
            pairs.append((day.strip(), hours.strip()))
    return pairs or None


def latest_records() -> Path:
    files = sorted(PROSPECTS.glob("prospects-*.json"))
    if not files:
        raise SystemExit(f"no prospect records under {PROSPECTS}")
    return files[-1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, default=None)
    parser.add_argument("--deploy", action="store_true")
    args = parser.parse_args(argv)

    source = args.records or latest_records()
    records = json.loads(source.read_text(encoding="utf-8"))
    print(f"records : {source}  ({len(records)} clinics)")
    print(f"mode    : {'deploy' if args.deploy else 'dry run — nothing is published'}")
    print()

    target = PublicHostTarget(SITES_ROOT, base_url=PUBLIC_BASE) if args.deploy else None
    year = datetime.now(UTC).year
    changed = 0

    try:
        for record in records:
            slug = record["slug"]
            # Only hours that were actually confirmed reach the page. A record
            # marked NOT_VERIFIED has empty hours for a different reason than one
            # marked CONFIRMED_ABSENT, and neither may be rendered as a schedule.
            hours = None
            if record.get("hours_status") == "CONFIRMED_PRESENT":
                hours = parse_hours(record.get("opening_hours") or [])

            files = dental.render_site(
                name=record["name"],
                phone=record["phone"],
                address=record["address"],
                area=record["area"],
                base_url=f"{PUBLIC_BASE}/{slug}",
                year=year,
                hours=hours,
            )

            # Compare against what is actually live, so a dry run reports a real
            # difference rather than asserting one.
            live = SITES_ROOT / slug / "current" / "index.html"
            differs = (not live.exists()) or live.read_text(encoding="utf-8") != files["index.html"]
            live_ar = SITES_ROOT / slug / "current" / "ar" / "index.html"
            differs = differs or (not live_ar.exists()) or live_ar.read_text(
                encoding="utf-8"
            ) != files["ar/index.html"]

            if differs:
                changed += 1

            if target is None:
                print(f"  {record['name'][:44]:<46} {'CHANGED' if differs else 'unchanged'}")
                continue

            version = target.publish(slug, files)
            url = target.promote(slug, version.id)
            record["demo_url"] = url
            record["version_id"] = version.id
            record["regenerated_at"] = datetime.now(UTC).isoformat()
            print(f"  {record['name'][:44]:<46} -> {url}")
    finally:
        if target is not None:
            target.close()

    print()
    if target is None:
        print(f"{changed} of {len(records)} would change. Re-run with --deploy to publish.")
        return 0

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    out = PROSPECTS / f"prospects-{stamp}.json"
    out.write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"republished {len(records)} demos; records: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
