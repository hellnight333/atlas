"""Measure which niche and geography Qevik should target. Run daily.

    python infra/market_scan.py                  # all niches, Dubai
    python infra/market_scan.py --area sharjah   # somewhere else
    python infra/market_scan.py --sample 20      # inspect more per niche

Answers "which niche, which geography" from live data instead of from an
opinion, so the answer stays current without anyone being asked for it.

Contacts nobody. It discovers businesses and inspects public web pages, which is
what any visitor does. Nothing here sends, proposes or writes to anyone.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "kernel"))

from atlas_kernel.opportunity.detectors.base import DetectorRegistry  # noqa: E402
from atlas_kernel.opportunity.detectors.website import WebsiteDetector  # noqa: E402
from atlas_kernel.opportunity.market import MarketScan, render_report  # noqa: E402
from atlas_kernel.opportunity.profiles import EXAMPLE_PROFILE  # noqa: E402
from atlas_kernel.opportunity.sources import NICHES, OverpassSource  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--area", default="dubai")
    parser.add_argument("--niches", nargs="*", default=sorted(NICHES))
    parser.add_argument("--sample", type=int, default=12)
    parser.add_argument("--limit", type=int, default=400)
    parser.add_argument("--json", type=Path, help="also write the raw rows here")
    args = parser.parse_args(argv)

    registry = DetectorRegistry()
    registry.register_detector(WebsiteDetector())
    scan = MarketScan(detectors=registry, sample_size=args.sample, discover_limit=args.limit)

    results = []
    for niche in args.niches:
        source = OverpassSource(area=args.area, niche=niche)
        try:
            print(f"scanning {args.area}/{niche} ...", file=sys.stderr)
            results.append(scan.measure(source, EXAMPLE_PROFILE, area=args.area, niche=niche))
        finally:
            source.close()

    ranked = scan.rank(results)
    failed = [r for r in results if r.error]

    print()
    print(render_report(ranked + failed))

    if ranked:
        best = ranked[0]
        print()
        print(f"Best market now: {best.area}/{best.niche}")
        print(
            f"  ~{best.estimated_prospects:.0f} workable prospects "
            f"({best.qualified_rate * 100:.0f}% of inspected sites had real defects, "
            f"{best.reachable_rate * 100:.0f}% are contactable)"
        )
    if failed:
        # Stated rather than swallowed: a scan that silently covered half the
        # niches would rank the ones it managed and look complete.
        print(f"\n{len(failed)} niche(s) could not be scanned — ranking is incomplete.")

    if args.json:
        args.json.write_text(json.dumps([r.as_row() for r in results], indent=2))
        print(f"\nraw rows -> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
