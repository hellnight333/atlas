#!/usr/bin/env python3
"""The ten-field dossier for the prospects worth calling first.

`sales_brief.py` answers "what may I say". This answers "who do I call, and what
is the whole picture" — including the part a pitch normally omits: **what they
already do well.** That section is not politeness. Walking into a clinic and
listing only faults, when their site does eleven things correctly, tells the
owner you did not really look. Naming what works is what makes the one criticism
credible.

Everything comes from stored evidence: the audit of their live homepage, the
Places listing, and the demo that was built and deployed. Nothing is inferred
about a business beyond what was fetched.

    prospect_dossier.py                 # top 5
    prospect_dossier.py --top 20        # all of them
    prospect_dossier.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sales_brief import (  # noqa: E402
    AUDITS,
    LABEL,
    PROSPECTS,
    brief_for,
    latest,
)

#: A UAE mobile — the only kind of number WhatsApp can reach. 16 of the 20
#: clinics publish a landline or a toll-free line, on which `wa.me/` is a dead
#: link, so this decides the recommended first contact method.
UAE_MOBILE = re.compile(r"^(?:971)?0?5[024568]\d{7}$")


def digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def contact_method(record: dict, audit: dict) -> tuple[str, str]:
    """How to reach them first, and why that channel rather than another."""
    phone = digits(record.get("phone", ""))
    if UAE_MOBILE.match(phone):
        return (
            "WhatsApp",
            f"{record['phone']} is a UAE mobile, so WhatsApp reaches it. In Dubai "
            "most clinic enquiries arrive that way, and a link to the demo is one "
            "tap from the message.",
        )

    wa = next(
        (f for f in audit.get("findings", []) if f["feature"] == "whatsapp"), None
    )
    if wa and wa.get("status") == "present":
        target = wa.get("evidence", "")
        # Their site publishing a wa.me link does not mean the link works. Most
        # of these wrap the clinic's landline, which WhatsApp cannot deliver to
        # — the identical dead-link fault the demo refuses to reproduce. Only
        # recommend the channel when the number behind it can actually receive.
        wa_number = digits(target)
        if UAE_MOBILE.match(wa_number.removeprefix("00")):
            return (
                "WhatsApp — the number on their own site",
                f"Their listed number is a landline, but their site publishes a "
                f"reachable WhatsApp mobile ({wa_number}). That is the channel "
                "they chose to publish, so it is the one to use.",
            )
        return (
            "Phone call",
            f"Careful here: their site shows a WhatsApp button, but it points at "
            f"{wa_number or 'a non-mobile number'} — a landline, which WhatsApp "
            "cannot deliver to. Their own WhatsApp link is broken. Call instead, "
            "and note this is itself worth raising once you are talking.",
        )

    return (
        "Phone call",
        f"{record.get('phone', 'their listed number')} is a landline or toll-free "
        "line, so WhatsApp cannot reach it and a message would silently go "
        "nowhere. Call the clinic and ask for whoever handles the website.",
    )


def strengths(audit: dict) -> list[str]:
    """What their site already gets right, in plain words.

    Empty for a site that never loaded — and the caller must treat that as *not
    observed* rather than *nothing good*. Telling an owner their site does zero
    things correctly, when the truth is it did not answer in time to be read, is
    the same collapse of NOT_VERIFIED into CONFIRMED_ABSENT that the whole
    pipeline exists to avoid.
    """
    present = [
        LABEL.get(f["feature"], f["feature"])
        for f in audit.get("findings", [])
        if f.get("status") == "present" and f["feature"] != "page_weight"
    ]
    return sorted(present)


def outreach_angle(brief: dict, audit: dict, record: dict) -> str:
    """One sentence of approach, derived from the strongest finding."""
    if not brief["talking_points"]:
        return (
            "No angle on defects — their site covers everything audited. Approach "
            "only on Arabic reach or speed of turnaround, or deprioritise them."
        )

    top = brief["talking_points"][0]

    if not audit.get("reachable"):
        # No strengths were observed because nothing could be read, which is not
        # the same as no strengths existing. Opening with "the 0 things your site
        # does correctly" would be an insult built on a measurement we never took.
        return (
            "Their homepage never loaded for us, so we know nothing about what it "
            "does well — do not imply it does nothing well. Lead with the single "
            "measured fact: it did not finish loading in 30 seconds. Offer the "
            "demo as something they can open immediately and compare."
        )

    strong = len(strengths(audit))
    lead = (
        f"Open by acknowledging the {strong} things their site already does "
        f"correctly, then raise one measured gap: {top['label'].lower()}."
    )
    if top["feature"] == "arabic":
        return (
            f"{lead} Their site is English-only; the demo is bilingual with a "
            "proper RTL Arabic page at its own indexable URL. Lead with reach, "
            "not with criticism."
        )
    if top["feature"] == "https":
        return (
            f"{lead} Browsers now warn on forms served over plain HTTP, which is "
            "visible to their patients. The demo is HTTPS by default."
        )
    return (
        f"{lead} Send the demo URL and let it make the argument — it is their own "
        "name, number, address and hours, so the comparison is immediate."
    )


def dossier(brief: dict, audit: dict, record: dict) -> dict:
    top = brief["talking_points"][0] if brief["talking_points"] else None
    method, why = contact_method(record, audit)

    return {
        "name": brief["clinic"],
        "existing_website": record.get("existing_website") or audit.get("url", ""),
        "strongest_weakness": top["label"] if top else "none confirmed",
        "weakness_detail": top["why"] if top else "",
        "qevik_improvement": (
            "The demo loads in well under a second and is verified live."
            if top and top["feature"] == "reachable"
            else f"The demo provides {top['label'].lower()}, verified live on the "
            "deployed page."
            if top
            else "Bilingual EN/AR pages and Dentist structured data, on HTTPS."
        ),
        "already_good": strengths(audit),
        "evidence": top["evidence"] if top else "",
        "measured": brief["audited"],
        "do_not_say": brief["do_not_say"],
        "caveats": brief["caveats"],
        "angle": outreach_angle(brief, audit, record),
        "contact_method": method,
        "contact_rationale": why,
        "phone": record.get("phone", ""),
        "demo_url": brief["demo_url"],
        "score": brief["score"],
    }


def render(d: dict, index: int) -> str:
    lines = [
        "=" * 78,
        f"#{index}   {d['name']}      (score {d['score']})",
        "=" * 78,
        f"  1. Business          {d['name']}",
        f"  2. Existing website  {d['existing_website'] or '(none on their listing)'}",
        f"  3. Strongest gap     {d['strongest_weakness']}",
        f"                       {d['weakness_detail']}",
        f"  4. Qevik improves    {d['qevik_improvement']}",
        "  5. Already good      "
        + (
            ", ".join(d["already_good"]) + f"  ({len(d['already_good'])} verified)"
            if d["already_good"]
            else "NOT OBSERVED — their homepage never loaded, so nothing could be "
            "checked. This is not a finding that they do nothing well."
        ),
        f"  6. Evidence          {d['evidence']}",
        f"                       measured: HTTP {d['measured']['http_status']}, "
        f"{d['measured']['load_ms']} ms, "
        f"{'HTTPS' if d['measured']['is_https'] else 'no HTTPS'}",
        "  7. DO NOT SAY",
    ]
    for item in sorted(d["do_not_say"], key=lambda x: x["reason"])[:8]:
        lines.append(f"       x [{item['reason']}] {item['claim']}")
    if len(d["do_not_say"]) > 8:
        lines.append(f"       ... and {len(d['do_not_say']) - 8} more (--json for all)")
    for caveat in d["caveats"]:
        lines.append(f"       ! {caveat}")
    lines += [
        f"  8. Angle             {d['angle']}",
        f"  9. First contact     {d['contact_method']}  ({d['phone']})",
        f"                       {d['contact_rationale']}",
        f" 10. Demo             {d['demo_url']}",
    ]
    return "\n".join(lines)


def build(top: int = 5) -> list[dict]:
    audits = json.loads(latest(AUDITS, "audits").read_text(encoding="utf-8"))
    records = json.loads(latest(PROSPECTS, "prospects").read_text(encoding="utf-8"))
    by_name = {r["name"]: r for r in records}

    rows = []
    for audit in audits:
        record = by_name.get(audit["clinic"])
        if record is None:
            continue
        rows.append(dossier(brief_for(audit, record), audit, record))

    rows.sort(key=lambda d: -d["score"])
    return rows[:top]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    rows = build(args.top)
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0
    for index, row in enumerate(rows, 1):
        print(render(row, index))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
