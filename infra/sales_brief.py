#!/usr/bin/env python3
"""Per-clinic comparison and sales brief, built only from stored evidence.

Two things a salesperson needs and cannot safely improvise:

**What their site does today versus what the demo does.** Joined per feature
from the audit that was actually run against their live homepage, so every claim
on the call traces to a fetch with a timestamp.

**What must not be said.** This is the half that gets skipped, and it is the half
that loses deals. Three separate reasons a claim is unsayable, and they are not
the same reason:

    their site HAS it        Saying "you're missing X" is contradicted by their
                             own homepage. The prospect knows their site better
                             than we do, and one wrong claim discredits the rest.

    we did NOT VERIFY it     The audit reads the homepage. A feature can live on
                             an inner page and be entirely present. Absent from
                             our sample is not absent from their site.

    the demo LACKS it        Claiming something the demo does not do is a promise
                             that breaks on the first click, in front of them.

Only `not_found` — asked for, fetched, and genuinely not there — becomes a
talking point. `unverified` never does.

    sales_brief.py                 # all clinics
    sales_brief.py --slug demo-x   # one
    sales_brief.py --json          # machine-readable
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

AUDITS = Path(os.environ.get("QEVIK_AUDITS", "/var/lib/qevik/audits"))
PROSPECTS = Path(os.environ.get("QEVIK_PROSPECTS", "/var/lib/qevik/prospects"))

#: What the generated site does, stated once. Anything not listed here is not a
#: capability of the demo, and the brief will refuse to let it be claimed.
#:
#: `False` entries are deliberate and are the honest half of the pitch. The
#: appointment form in particular renders but does not submit, which is a fact
#: the salesperson must carry into the room rather than discover in it.
DEMO_PROVIDES: dict[str, bool] = {
    "arabic": True,
    "click_to_call": True,
    "google_maps": True,
    "opening_hours": True,
    "structured_data": True,
    "https": True,
    "viewport_meta": True,
    "h1": True,
    "page_title": True,
    "meta_description": True,
    "services_navigation": True,
    "image_alt_text": True,  # no images at all; nothing lacking alt text
    "page_weight": True,
    "contact_form": True,
    # Present only where the clinic publishes a WhatsApp-capable mobile.
    "whatsapp": False,
    # The form renders and states plainly that it does not submit.
    "booking_link": False,
    # Never generated: we do not know their doctors, their insurers, or what
    # patients have said, and inventing any of it is the one unrecoverable
    # mistake in front of the person who does know.
    "doctors_team": False,
    "insurance_info": False,
    "social_proof": False,
    "emergency_info": False,
}

#: Human phrasing for the report.
LABEL = {
    "arabic": "Arabic version",
    "booking_link": "Online booking route",
    "click_to_call": "Tap-to-call link",
    "contact_form": "Contact form",
    "doctors_team": "Doctor profiles",
    "emergency_info": "Emergency information",
    "google_maps": "Map / directions",
    "h1": "Page heading",
    "https": "HTTPS",
    "image_alt_text": "Image alt text",
    "insurance_info": "Insurance information",
    "meta_description": "Meta description",
    "opening_hours": "Opening hours",
    "page_title": "Page title",
    "page_weight": "Page weight",
    "services_navigation": "Services navigation",
    "social_proof": "Reviews / social proof",
    "structured_data": "Structured data",
    "viewport_meta": "Mobile viewport",
    "whatsapp": "WhatsApp",
}

#: Ordered by how much a Dubai clinic's enquiry volume actually moves.
WEIGHT = {
    "arabic": 5,
    "whatsapp": 5,
    "click_to_call": 5,
    "google_maps": 4,
    "opening_hours": 4,
    "structured_data": 3,
    "https": 3,
    "booking_link": 3,
    "viewport_meta": 3,
    "contact_form": 2,
    "meta_description": 2,
    "h1": 2,
    "image_alt_text": 1,
    "services_navigation": 1,
    "page_title": 1,
    "page_weight": 1,
}


def latest(directory: Path, prefix: str) -> Path:
    files = sorted(directory.glob(f"{prefix}-*.json"))
    if not files:
        raise SystemExit(f"no {prefix} records under {directory}")
    return files[-1]


#: Measurements, not features. "Their site has no page weight" is not a claim
#: anyone would make, and listing it as forbidden buries the fourteen lines that
#: matter under noise. A DO_NOT_SAY list is only read if every line earns its
#: place.
NOT_A_CLAIM = frozenset({"page_weight"})


def brief_for(audit: dict, record: dict | None) -> dict:
    findings = {f["feature"]: f for f in audit.get("findings", [])}

    talking_points: list[dict] = []
    do_not_say: list[dict] = []

    for feature, finding in sorted(findings.items()):
        if feature in NOT_A_CLAIM:
            continue
        status = finding["status"]
        label = LABEL.get(feature, feature)
        demo_has = DEMO_PROVIDES.get(feature, False)

        if status == "present":
            do_not_say.append(
                {
                    "claim": f"Their site has no {label.lower()}",
                    "reason": "THEIR_SITE_HAS_IT",
                    "evidence": finding.get("evidence", ""),
                }
            )
            continue

        if status == "unverified":
            do_not_say.append(
                {
                    "claim": f"Their site has no {label.lower()}",
                    "reason": "NOT_VERIFIED",
                    "evidence": "not on the homepage we fetched; may exist on an inner page",
                }
            )
            continue

        # status == not_found: fetched, and genuinely not there.
        if not demo_has:
            do_not_say.append(
                {
                    "claim": f"We will give you {label.lower()}",
                    "reason": "DEMO_DOES_NOT_HAVE_IT",
                    "evidence": "the generated site does not provide this",
                }
            )
            continue

        talking_points.append(
            {
                "feature": feature,
                "label": label,
                "weight": WEIGHT.get(feature, 1),
                "their_site": "NOT_FOUND",
                "demo": "PRESENT",
                "evidence": finding.get("evidence", ""),
                "why": finding.get("note", ""),
            }
        )

    talking_points.sort(key=lambda p: (-p["weight"], p["label"]))

    # Things the demo has that were never audited on their side are not claims
    # about them, so they belong in neither list. The one exception worth
    # stating is the appointment form, because it is what they will click.
    caveats = [
        "The appointment form on the demo renders but does NOT submit anywhere. "
        "It says so on the page. Do not describe it as working booking.",
    ]
    if record and not (record.get("hours_status") == "CONFIRMED_PRESENT"):
        caveats.append("Opening hours were not confirmed for this clinic; the demo omits them.")

    return {
        "clinic": audit["clinic"],
        "their_url": audit.get("url", ""),
        "audited": {
            "reachable": audit.get("reachable"),
            "http_status": audit.get("http_status"),
            "load_ms": audit.get("load_ms"),
            "page_bytes": audit.get("page_bytes"),
            "is_https": audit.get("is_https"),
        },
        "demo_url": (record or {}).get("demo_url", ""),
        "score": sum(p["weight"] for p in talking_points),
        "talking_points": talking_points,
        "do_not_say": do_not_say,
        "caveats": caveats,
    }


def render(brief: dict) -> str:
    lines = [
        "=" * 78,
        brief["clinic"],
        "=" * 78,
        f"  their site : {brief['their_url']}",
        f"  demo       : {brief['demo_url'] or '(not deployed)'}",
        f"  measured   : HTTP {brief['audited']['http_status']}, "
        f"{brief['audited']['load_ms']} ms, "
        f"{(brief['audited']['page_bytes'] or 0) / 1000:.0f} kB, "
        f"{'HTTPS' if brief['audited']['is_https'] else 'NO HTTPS'}",
        f"  score      : {brief['score']}",
        "",
        f"  SAY — verified gaps their site has and the demo closes ({len(brief['talking_points'])})",
    ]
    if not brief["talking_points"]:
        lines.append("    (none — this clinic's site covers everything we audited)")
    for point in brief["talking_points"]:
        lines.append(f"    [{point['weight']}] {point['label']}")
        lines.append(f"         theirs: NOT_FOUND — {point['evidence']}")
        lines.append(f"         why   : {point['why']}")

    lines.append("")
    lines.append(f"  DO NOT SAY ({len(brief['do_not_say'])})")
    for item in sorted(brief["do_not_say"], key=lambda d: d["reason"]):
        lines.append(f"    x {item['claim']}")
        lines.append(f"      {item['reason']}: {item['evidence'][:90]}")

    lines.append("")
    lines.append("  CARRY INTO THE ROOM")
    for caveat in brief["caveats"]:
        lines.append(f"    ! {caveat}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--top", type=int, default=0, help="only the N highest-scoring")
    args = parser.parse_args(argv)

    audits = json.loads(latest(AUDITS, "audits").read_text(encoding="utf-8"))
    records = json.loads(latest(PROSPECTS, "prospects").read_text(encoding="utf-8"))
    by_name = {r["name"]: r for r in records}

    briefs = [brief_for(audit, by_name.get(audit["clinic"])) for audit in audits]
    briefs.sort(key=lambda b: -b["score"])

    if args.slug:
        briefs = [b for b in briefs if args.slug in (b["demo_url"] or "")]
    if args.top:
        briefs = briefs[: args.top]

    if args.json:
        print(json.dumps(briefs, indent=2, ensure_ascii=False))
        return 0

    for brief in briefs:
        print(render(brief))
        print()

    print("=" * 78)
    print(f"{len(briefs)} clinics, ranked by verified closeable gaps")
    for brief in briefs:
        say = len(brief["talking_points"])
        never = len(brief["do_not_say"])
        print(f"  {brief['score']:>3}  {brief['clinic'][:46]:<48} say {say:>2} / never {never:>2}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
