#!/usr/bin/env python3
"""Turn audits into a ranked list of who is worth contacting, and why.

    rank_prospects.py [--top 5]

Ranks on **improvement potential**, not on how dated a site looks. A clinic with
a good website and one expensive gap is a better conversation than one with a
bad website and no budget — and a clinic with nothing missing is not a prospect
at all, however tempting it is to count it as one.

Only confirmed absences count against a site. Anything the audit could not
verify is excluded from scoring entirely, so no pitch rests on a claim that
would collapse the moment the owner opened their own menu.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

AUDITS = Path(os.environ.get("QEVIK_AUDITS", "/var/lib/qevik/audits"))
PROSPECTS = Path(os.environ.get("QEVIK_PROSPECTS", "/var/lib/qevik/prospects"))
BRIEFS = Path(os.environ.get("QEVIK_BRIEFS", "/var/lib/qevik/briefs"))

#: What a missing feature is worth as an opportunity, 0-10. Weighted by what it
#: costs a dental practice in patients, not by how hard it is to build.
WEIGHT: dict[str, int] = {
    "booking_link": 9,      # the single clearest path from visitor to revenue
    "whatsapp": 9,          # how UAE patients actually enquire
    "click_to_call": 9,     # a patient in pain phones
    "https": 8,             # browsers warn on forms; it undermines everything else
    "opening_hours": 7,     # the most-checked fact on a clinic site
    "google_maps": 6,       # patients choose what they can find
    "structured_data": 6,   # local search and map packs
    "contact_form": 5,      # the non-urgent enquiry route
    "arabic": 5,            # a large share of Dubai patients
    "meta_description": 4,  # controls the search snippet
    "h1": 3,
    "image_alt_text": 2,
    "services_navigation": 6,
    "page_weight": 4,
    "viewport_meta": 8,     # without it a phone shows a zoomed-out desktop page
}


def latest(directory: Path, prefix: str) -> list[dict]:
    files = sorted(directory.glob(f"{prefix}-*.json"))
    if not files:
        raise SystemExit(f"no {prefix} records under {directory}")
    return json.loads(files[-1].read_text(encoding="utf-8"))


def score(audit: dict) -> dict:
    """Opportunity, and the evidence behind it."""
    missing = [f for f in audit["findings"] if f["status"] == "not_found"]
    present = [f for f in audit["findings"] if f["status"] == "present"]

    opportunity = sum(WEIGHT.get(f["feature"], 3) for f in missing)
    # Slow sites are a real, measurable weakness a patient feels immediately.
    if audit.get("load_ms", 0) > 4000:
        opportunity += 6

    ranked = sorted(missing, key=lambda f: -WEIGHT.get(f["feature"], 3))
    return {
        "clinic": audit["clinic"],
        "url": audit["url"],
        "load_ms": audit.get("load_ms", 0),
        "opportunity": opportunity,
        "present_count": len(present),
        "missing_count": len(missing),
        "unverified_count": len([f for f in audit["findings"] if f["status"] == "unverified"]),
        "top_gaps": ranked[:4],
        "strengths": [f["feature"] for f in present][:8],
    }


def brief(entry: dict, prospect: dict) -> str:
    """What a human needs in front of them before they send anything."""
    gaps = entry["top_gaps"]
    if not gaps:
        return (
            f"PROSPECT: {entry['clinic']}\n"
            "WHY CONTACT: nothing confirmed missing on their homepage. Not a prospect "
            "on this evidence — do not invent a reason.\n"
        )
    strongest = gaps[0]
    slow = f" Their homepage took {entry['load_ms']}ms to load." if entry["load_ms"] > 4000 else ""
    return "\n".join(
        [
            f"PROSPECT: {entry['clinic']}",
            f"CURRENT SITE: {entry['url']}",
            f"DEMO: {prospect.get('demo_url') or '(not deployed)'}",
            "",
            f"STRONGEST WEAKNESS: {strongest['feature']} — {strongest['evidence']}",
            f"WHY IT MATTERS: {strongest['note']}",
            f"OTHER CONFIRMED GAPS: {', '.join(g['feature'] for g in gaps[1:]) or 'none'}",
            f"THEY ALREADY DO WELL: {', '.join(entry['strengths'][:5])}",
            f"OPPORTUNITY SCORE: {entry['opportunity']}",
            "",
            f"PITCH: Their site is solid on {entry['strengths'][0] if entry['strengths'] else 'basics'},"
            f" but {strongest['feature'].replace('_', ' ')} is missing.{slow}"
            " Show them the demo side by side and ask what that gap costs them in a month.",
            "",
            "DO NOT SAY: anything about pages this audit did not open — "
            f"{entry['unverified_count']} feature(s) were unverified, not absent.",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args(argv)

    audits = latest(AUDITS, "audits")
    prospects = {p["name"]: p for p in latest(PROSPECTS, "prospects")}

    scored = sorted(
        (score(a) for a in audits if a.get("reachable")),
        key=lambda e: -e["opportunity"],
    )

    print(f"{'clinic':<42} {'opp':>4} {'have':>5} {'gaps':>5} {'unver':>6}  load")
    print("-" * 78)
    for entry in scored:
        print(
            f"{entry['clinic'][:40]:<42} {entry['opportunity']:>4} "
            f"{entry['present_count']:>5} {entry['missing_count']:>5} "
            f"{entry['unverified_count']:>6}  {entry['load_ms']}ms"
        )

    BRIEFS.mkdir(parents=True, exist_ok=True)
    for entry in scored[: args.top]:
        name = entry["clinic"].lower().replace(" ", "-")[:50]
        text = brief(entry, prospects.get(entry["clinic"], {}))
        (BRIEFS / f"{name}.txt").write_text(text, encoding="utf-8")

    print()
    print(f"top {args.top} briefs written to {BRIEFS}")
    print()
    for entry in scored[: args.top]:
        print(brief(entry, prospects.get(entry["clinic"], {})))
        print("-" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
