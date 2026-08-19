#!/usr/bin/env python3
"""Rank the audited market by commercial value, and compare industries.

The dental scoring counted findings. That is the wrong unit: a missing meta
description and a homepage that will not load on a phone are one point each, and
only one of them costs the business money. Here every weakness carries what it is
actually worth to fix, so a broken enquiry path outranks a pile of metadata.

Two rules the scoring exists to enforce:

- **`unverified` scores nothing.** The audit reads one homepage. A feature can
  live on an inner page; absent from our sample is not absent from their site,
  and a score that treats the two alike produces a pitch we cannot defend.
- **Contactability gates everything.** A perfect opportunity at a business we
  cannot reach is worth zero, so it multiplies rather than adds.

    rank_market.py                 # the whole market, by industry
    rank_market.py --top 25
    rank_market.py --category food
    rank_market.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import defaultdict
from pathlib import Path

PROSPECTS = Path(os.environ.get("QEVIK_PROSPECTS", "/var/lib/qevik/prospects"))

#: What fixing this is worth commercially, not how hard it is to detect.
#:
#: Arabic and mobile sit at the top because they decide whether a share of the
#: market can use the site at all. Metadata sits at the bottom because it moves
#: a ranking slightly and a visitor never sees it.
WEIGHT: dict[str, int] = {
    "arabic": 26,
    "click_to_call": 22,
    "viewport_meta": 22,
    "whatsapp": 18,
    "google_maps": 14,
    "opening_hours": 13,
    "contact_form": 12,
    "https": 12,
    "structured_data": 9,
    "booking_link": 8,
    "h1": 5,
    "services_navigation": 5,
    "meta_description": 3,
    "image_alt_text": 2,
    "page_title": 2,
    "page_weight": 1,
}

#: Qevik builds these today. A weakness it cannot fix is a fact about the
#: market, not an opportunity — scoring it would rank prospects by problems we
#: would have to decline.
FIXABLE = frozenset(
    {
        "arabic", "click_to_call", "viewport_meta", "whatsapp", "google_maps",
        "opening_hours", "contact_form", "https", "structured_data", "h1",
        "services_navigation", "meta_description", "image_alt_text", "page_title",
    }
)

#: The demo that best answers each category's objection.
SAMPLE_FOR = {
    "food": ("sample-nar", "editorial restaurant with a table request"),
    "beauty": ("sample-salon", "treatment list with durations"),
    "health": ("sample", "clinic with verified hours and tap-to-call"),
    "automotive": ("sample-apex", "four-step quote configurator"),
    "home": ("sample-apex", "service area, FAQ and quote request"),
    "professional": ("sample-property", "service pages, FAQ, call-back"),
    "retail": ("sample-verdant", "filterable catalogue and basket"),
}

_UAE_MOBILE = re.compile(r"^(?:971)?0?5[024568]\d{7}$")

#: A homepage this slow loses visitors before it renders. Measured, not guessed.
SLOW_MS = 6000
VERY_SLOW_MS = 12000


def digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def latest(prefix: str) -> Path:
    files = sorted(PROSPECTS.glob(f"{prefix}-*.json"))
    if not files:
        raise SystemExit(f"no {prefix} records under {PROSPECTS}")
    return files[-1]


def score(audit: dict) -> dict:
    """Commercial value of this prospect, and why."""
    reasons: list[tuple[int, str, str]] = []

    if not audit.get("reachable"):
        reasons.append((40, "site did not load", audit.get("error", "")[:90]))
    else:
        for finding in audit.get("findings", []):
            feature = finding.get("feature", "")
            if finding.get("status") != "not_found":
                continue  # present, or unverified — neither is an opportunity
            if feature not in FIXABLE:
                continue
            reasons.append(
                (WEIGHT.get(feature, 1), f"no {feature}", finding.get("evidence", "")[:80])
            )

        load = audit.get("load_ms") or 0
        if load >= VERY_SLOW_MS:
            reasons.append((24, f"homepage took {load / 1000:.1f}s", "measured once"))
        elif load >= SLOW_MS:
            reasons.append((12, f"homepage took {load / 1000:.1f}s", "measured once"))

    raw = sum(weight for weight, _, _ in reasons)

    # Contactability multiplies. An opportunity we cannot act on is worth
    # nothing, however large — and a mobile is worth more than a landline
    # because it can receive the demo link where the owner reads it.
    phone = digits(audit.get("phone", ""))
    if not phone:
        reach, reach_note = 0.0, "no phone on the listing"
    elif _UAE_MOBILE.match(phone):
        reach, reach_note = 1.0, "mobile — WhatsApp reaches it"
    else:
        reach, reach_note = 0.65, "landline only — phone call"

    reasons.sort(key=lambda r: -r[0])
    return {
        "business_id": audit["business_id"],
        "name": audit["name"],
        "category": audit["category"],
        "url": audit["url"],
        "phone": audit.get("phone", ""),
        "reachable": audit.get("reachable"),
        "load_ms": audit.get("load_ms"),
        "is_https": audit.get("is_https"),
        "score": round(raw * reach),
        "raw": raw,
        "reach": reach,
        "reach_note": reach_note,
        "top_weakness": reasons[0][1] if reasons else "nothing confirmed",
        "evidence": reasons[0][2] if reasons else "",
        "reasons": [{"weight": w, "what": t, "evidence": e} for w, t, e in reasons[:6]],
        "strengths": sorted(
            f.get("feature", "")
            for f in audit.get("findings", [])
            if f.get("status") == "present"
        ),
        "unverified": sorted(
            f.get("feature", "")
            for f in audit.get("findings", [])
            if f.get("status") == "unverified"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audits", type=Path, default=None)
    parser.add_argument("--top", type=int, default=25)
    parser.add_argument("--category", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    source = args.audits or latest("multi-audits")
    audits = json.loads(source.read_text(encoding="utf-8"))
    ranked = sorted((score(a) for a in audits), key=lambda r: -r["score"])
    if args.category:
        ranked = [r for r in ranked if r["category"] == args.category]

    if args.json:
        print(json.dumps(ranked, indent=2, ensure_ascii=False))
        return 0

    # --- industry comparison, which is what the discovery was for -----------
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for row in ranked:
        by_cat[row["category"]].append(row)

    print(f"audits : {source}  ({len(ranked)} businesses)\n")
    print(f"{'industry':<14} {'n':>4} {'median':>7} {'best':>6} {'mobile':>7} "
          f"{'no arabic':>10} {'slow/down':>10}")
    print("-" * 72)
    for cat, rows in sorted(by_cat.items(), key=lambda kv: -_median([r["score"] for r in kv[1]])):
        scores = sorted(r["score"] for r in rows)
        mobile = sum(1 for r in rows if r["reach"] == 1.0)
        arabic = sum(1 for r in rows if any("arabic" in x["what"] for x in r["reasons"]))
        slow = sum(1 for r in rows if not r["reachable"] or (r["load_ms"] or 0) >= SLOW_MS)
        print(f"{cat:<14} {len(rows):>4} {_median(scores):>7.0f} {scores[-1]:>6} "
              f"{mobile:>6}/{len(rows):<3} {arabic:>9}/{len(rows):<3} {slow:>9}/{len(rows)}")

    print(f"\n\nTOP {args.top} OVERALL\n" + "=" * 72)
    print(f"{'#':>3} {'score':>5}  {'industry':<12} {'business':<34} weakness")
    print("-" * 100)
    for index, row in enumerate(ranked[: args.top], 1):
        print(f"{index:>3} {row['score']:>5}  {row['category']:<12} "
              f"{row['name'][:32]:<34} {row['top_weakness']}")

    for cat in sorted(by_cat):
        rows = by_cat[cat][:5]
        print(f"\n\nTOP 5 — {cat.upper()}\n" + "-" * 72)
        for index, row in enumerate(rows, 1):
            sample, why = SAMPLE_FOR.get(cat, ("sample", ""))
            print(f"{index}. [{row['score']:>3}] {row['name'][:44]}")
            print(f"        {row['url'][:66]}")
            print(f"        weakness : {row['top_weakness']} — {row['evidence'][:56]}")
            print(f"        contact  : {row['phone'] or 'none'} ({row['reach_note']})")
            print(f"        show them: {sample} — {why}")
    return 0


def _median(values: list[int]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    return (
        ordered[middle]
        if len(ordered) % 2
        else (ordered[middle - 1] + ordered[middle]) / 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
