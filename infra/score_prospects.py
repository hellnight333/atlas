#!/usr/bin/env python3
"""Score every audited business on commercial opportunity, and keep the reasoning.

Reads the timeline each business already has — no new table, no prospect list,
no status column. The latest `website_audited` event is the evidence; the score
and every component's reasoning go back onto the same timeline as a
`prospect_scored` event, so a ranking can be argued with a week later instead of
believed.

Scores are deliberately *not* stored on the business row. A score is a reading
taken at a moment from evidence that will be re-collected; folding it into the
entity would lose the fact that it changed and why.

    score_prospects.py                    # rank, print, change nothing
    score_prospects.py --top 15
    score_prospects.py --category dental
    score_prospects.py --record           # also write prospect_scored events
    score_prospects.py --explain <name>   # one business, every component
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "kernel"))

from atlas_kernel.opportunity.models import BusinessEvent  # noqa: E402
from atlas_kernel.opportunity.repository import OpportunityRepository  # noqa: E402
from atlas_kernel.outreach import demos, scoring  # noqa: E402

FACTORY = "sales_experiment"

#: Businesses invented by the test suite before test isolation landed. They have
#: generated domains and no phone, and they are not prospects.
_FIXTURE_HOST = re.compile(r"-[0-9a-f]{8,}\.(ae|com)\b|(^|\.)example\.|(^|\.)test\.")


def _detail(raw) -> dict:
    return raw if isinstance(raw, dict) else json.loads(raw or "{}")


def load() -> list[dict]:
    """Every business with an audit, carrying its latest evidence."""
    from sqlalchemy import text

    from atlas_kernel.db import SessionLocal

    with SessionLocal() as connection:
        businesses = {
            row[0]: dict(id=row[0], name=row[1], website=row[2] or "",
                         email=row[3] or "", phone=row[4] or "", geography=row[5] or "")
            for row in connection.execute(text(
                "select id, name, website, email, phone, geography from atlas_businesses"))
        }
        rows = list(connection.execute(text(
            "select business_id, kind, detail, at from atlas_business_events "
            "where kind in ('website_audited', 'website_demo_published', 'claims_verified') "
            "order by at")))

    audits: dict[str, dict] = {}
    counts: dict[str, int] = {}
    demos: dict[str, str] = {}
    verified: dict[str, dict] = {}
    live: dict[str, dict] = {}
    for business_id, kind, detail, _ in rows:
        data = _detail(detail)
        if kind == "website_audited":
            audits[business_id] = data          # last one wins; the list is ordered
            counts[business_id] = counts.get(business_id, 0) + 1
        elif kind == "claims_verified":
            # Merged, not replaced. A later run only re-tests what is still
            # flagged, so treating the newest event as the whole truth silently
            # forgets earlier refutations — AHS Catering's HTTPS was refuted in
            # one round and reappeared as a live weakness in the next, which
            # would have opened a message to them with a false sentence.
            verified.setdefault(business_id, {}).update(
                {c["feature"]: c["verdict"] for c in data.get("claims", [])})
            live[business_id] = data
        else:
            demos[business_id] = data.get("demo_url", "")

    out = []
    for business_id, audit in audits.items():
        business = businesses.get(business_id)
        if not business:
            continue
        if _FIXTURE_HOST.search(business["website"]):
            continue                            # test fixture, not a prospect
        category = audit.get("category") or ("dental" if demos.get(business_id) else "")
        checks = verified.get(business_id, {})
        if checks:
            audit = {**audit,
                     "live_load_ms": live[business_id].get("load_ms"),
                     "live_http_status": live[business_id].get("http_status")}
            audit = scoring.apply_verification(audit, checks)
        out.append({
            **business,
            "category": category,
            "verified": bool(checks),
            "audit": audit,
            "audit_count": counts[business_id],
            "demo_url": demos.get(business_id, ""),
        })
    return out


def _slug(candidate: dict) -> str:
    """The sample this prospect would actually be shown, or nothing.

    Chosen by `outreach.demos`, which is the only place demo relevance is
    decided. The scorer used to keep its own category->sample map beside two
    others; they drifted, and professional services ended up pointed at the
    real-estate sample.
    """
    selection = demos.select(candidate["category"])
    return selection.demo.slug if selection.demo else ""


def scored(candidates: list[dict]) -> list[scoring.Score]:
    return sorted(
        (
            scoring.score(
                business_id=c["id"], name=c["name"], website=c["website"],
                phone=c["phone"], email=c["email"], category=c["category"],
                audit=c["audit"], audit_count=c["audit_count"],
                demo_url=c["demo_url"], sample_slug=_slug(c),
            )
            for c in candidates
        ),
        key=lambda s: -s.total,
    )


def explain(score: scoring.Score) -> None:
    print(f"\n{score.name}")
    print(f"  {score.contact or 'no contact'}  ({score.contact_kind})")
    print(f"  TOTAL {score.total}/100")
    if not score.audit_complete:
        print("  !! AUDIT DID NOT COMPLETE — this score describes our failure to look,")
        print("     not their website. Re-verify before any claim is made about it.")
    print()
    for component in score.components:
        print(f"  {component.name:<14} {component.points:>3}/{component.out_of:<3} {component.reason}")
        for line in component.evidence:
            print(f"                     · {line}")
    if score.speakable:
        print(f"\n  MAY RAISE     : {', '.join(score.speakable)}")
    if score.unfixable:
        print(f"  MUST NOT RAISE: {', '.join(score.unfixable)}  (Qevik does not build these)")
    if score.unverified:
        print(f"  NOT_VERIFIED  : {', '.join(score.unverified)}  (never call these missing)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--category", default="")
    parser.add_argument("--explain", default="")
    parser.add_argument("--record", action="store_true",
                        help="write prospect_scored events to the timeline")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--verified-only", action="store_true",
                        help="rank only prospects whose claims were re-checked live")
    args = parser.parse_args(argv)

    repo = OpportunityRepository()
    try:
        candidates = load()
        if args.category:
            candidates = [c for c in candidates if c["category"] == args.category]
        ranked = scored(candidates)
        if args.verified_only:
            ranked = [s for s in ranked if s.verified]

        if args.explain:
            needle = args.explain.lower()
            hits = [s for s in ranked if needle in s.name.lower()]
            if not hits:
                print(f"no business matching {args.explain!r}")
                return 1
            for hit in hits:
                explain(hit)
            return 0

        if args.json:
            print(json.dumps([{"name": s.name, **s.as_event_detail()} for s in ranked], indent=2))
            return 0

        print(f"scored {len(ranked)} audited businesses "
              f"(fixtures excluded) · scorer {scoring.VERSION}\n")
        print(f"{'#':>3} {'tot':>4} {'rch':>4} {'wk':>3} {'imp':>4} {'ql':>3} {'cf':>3} {'rl':>3}  "
              f"{'business':<38} {'contact':<15} may raise")
        print("-" * 132)
        for index, s in enumerate(ranked[: args.top], 1):
            parts = {c.name: c.points for c in s.components}
            print(
                f"{index:>3} {s.total:>4} {parts['reachability']:>4} {parts['weakness']:>3} "
                f"{parts['improvement']:>4} {parts['quality']:>3} {parts['confidence']:>3} "
                f"{parts['relevance']:>3} {'v' if s.verified else ' '} {s.name[:34]:<36} {s.contact[:13]:<15} "
                f"{', '.join(s.speakable[:3]) or ('!! audit did not complete' if not s.audit_complete else '— nothing we fix')}"
            )

        if args.record:
            written = 0
            for s in ranked:
                repo.record_event(BusinessEvent(
                    business_id=s.business_id, factory=FACTORY, kind="prospect_scored",
                    actor="score_prospects.py", detail=s.as_event_detail(),
                ))
                written += 1
            print(f"\nrecorded {written} prospect_scored events on the existing timeline")
        else:
            print("\n(nothing written — pass --record to persist the scores as events)")
    except Exception:
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
