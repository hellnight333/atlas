#!/usr/bin/env python3
"""Publish the hand-built portfolio samples.

These are single self-contained files rather than generated sites — that is the
point of them, since a shared generator is what made the first five look alike.
They still go out through `PublicHostTarget`, so they are versioned and a bad
one can be rolled back like anything else.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "kernel"))

from atlas_kernel.website.targets.public_host import PublicHostTarget  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "apps" / "samples"
SITES = Path(os.environ.get("QEVIK_SITES_ROOT", "/srv/sites"))
BASE = os.environ.get("QEVIK_SITES_BASE_URL", "https://sites.qevik.ai")

#: directory -> published slug
PORTFOLIO = {
    "pulse": "sample-pulse",
    "nar": "sample-nar",
    "apex": "sample-apex",
    "verdant": "sample-verdant",
    "homefix": "sample-homefix",
    "ledgerloop": "sample-ledgerloop",
    "meridian": "sample-meridian",
}


def main() -> int:
    target = PublicHostTarget(SITES, base_url=BASE)
    try:
        for directory, slug in PORTFOLIO.items():
            source = ROOT / directory / "index.html"
            if not source.exists():
                print(f"  missing: {source}")
                continue
            version = target.publish(slug, {"index.html": source.read_text(encoding="utf-8")})
            print(f"  {slug:<18} -> {target.promote(slug, version.id)}")
    finally:
        target.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
