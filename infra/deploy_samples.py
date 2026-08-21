#!/usr/bin/env python3
"""Publish the portfolio samples.

Most are single self-contained files — that is the point of them, since a shared
generator is what made the first five look alike. AHS is the exception and for
the opposite reason: it mirrors a real business whose own site separates the
work, the services and the writing into pages, so it has its own generator
emitting ~100 routes in two languages. A generator per site does not converge
the way one generator across sites does.

Everything goes out through `PublicHostTarget`, so it is versioned and a bad one
can be rolled back like anything else.
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
    "carrot": "sample-carrot",
    "wordrush": "sample-wordrush",
    "kilo": "sample-kilo",
    "hire360": "sample-hire360",
    "foundry": "sample-foundry",
    "atelier": "sample-atelier",
}


#: directory -> published slug, for samples that build themselves.
GENERATED = {"ahs": "sample-ahs"}


def generated(directory: str) -> dict[str, str]:
    """Import that sample's own build module and ask it for its routes."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        f"{directory}_build", ROOT / directory / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build()


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
        for directory, slug in GENERATED.items():
            files = generated(directory)
            version = target.publish(slug, files)
            url = target.promote(slug, version.id)
            print(f"  {slug:<18} -> {url}  ({len(files)} files)")
    finally:
        target.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
