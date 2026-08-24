"""Qevik, run against Qevik, through the pipeline it sells.

§15. The point is not to produce a report about ourselves — it is to find out
what the engine says when the business it is describing is one we cannot be
wrong about. Every other subject is a stranger whose site we half-understand;
here the gap between what the evidence shows and what is true is visible.

Nothing is faked and nothing is fetched. The observations below are what the
engine has actually established about qevik.ai, recorded honestly including the
ones that are `unverified` — and the interesting output is what the readiness
model and the roadmap do with a business that has almost nothing.

    python3 infra/run_qevik_self_use.py

Run offline on purpose. Crawling our own site would work, and it would mean this
script produces different output depending on whether the network is up, which
makes it useless as a record.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "kernel"))

from atlas_kernel.opportunity.tenancy import TenantId  # noqa: E402
from atlas_kernel.outreach import opportunity as opp  # noqa: E402
from atlas_kernel.recommendation import service as rec_service  # noqa: E402
from atlas_kernel.roadmap import assess, generate  # noqa: E402
from atlas_kernel.roadmap.lifecycle import facts_for  # noqa: E402
from atlas_kernel.website import seo  # noqa: E402

#: The house organisation. Qevik is a tenant like any other, deliberately: a
#: system with a privileged path for its own data has a path nobody tests.
TENANT: TenantId = "tenant-qevik"
BUSINESS = "qevik"
WEBSITE = "https://qevik.ai"

#: What the engine has established about qevik.ai. `unverified` where nothing
#: has been checked — which is most of it, and saying so is the point. A
#: self-assessment padded with assumed strengths would be exactly the flattery
#: the three-state model exists to prevent.
OBSERVATIONS = [
    {"feature": "website", "status": "unverified"},
    {"feature": "https", "status": "unverified"},
    {"feature": "page_speed", "status": "unverified"},
    {"feature": "page_title", "status": "unverified"},
    {"feature": "meta_description", "status": "unverified"},
    {"feature": "h1", "status": "unverified"},
    {"feature": "structured_data", "status": "unverified"},
    {"feature": "sitemap", "status": "unverified"},
    {"feature": "robots", "status": "unverified"},
    # Confirmed absent: there is no public Qevik site to carry these, which is
    # a fact about the business and not a gap in our checking.
    {"feature": "blog", "status": "not_found"},
    {"feature": "blog_cadence", "status": "not_found"},
    {"feature": "social_proof", "status": "not_found"},
    {"feature": "click_to_call", "status": "not_found"},
    {"feature": "contact_form", "status": "not_found"},
    {"feature": "arabic", "status": "not_found"},
    {"feature": "ai_visibility", "status": "unverified"},
]


def _statuses(observations: list[dict]) -> tuple[frozenset[str], frozenset[str],
                                                 frozenset[str]]:
    absent = frozenset(o["feature"] for o in observations
                       if o["status"] == "not_found")
    present = frozenset(o["feature"] for o in observations
                        if o["status"] == "present")
    unverified = frozenset(o["feature"] for o in observations
                           if o["status"] == "unverified")
    return absent, present, unverified


def main() -> int:
    absent, present, unverified = _statuses(OBSERVATIONS)

    print("=" * 72)
    print("QEVIK, ASSESSED BY QEVIK")
    print("=" * 72)
    print(f"  business   {BUSINESS}   tenant {TENANT}   website {WEBSITE}")
    print(f"  confirmed present {len(present)} · confirmed absent {len(absent)} "
          f"· never checked {len(unverified)}")

    # 1. Readiness ---------------------------------------------------------
    readiness = assess(business_id=BUSINESS, observations=OBSERVATIONS,
                       business_model="SERVICES")
    print()
    print("1. READINESS")
    # Per dimension with a confidence, not one number. A single score would
    # average a dimension we checked with one we never looked at, and the
    # result would read as knowledge.
    for dimension in readiness.dimensions:
        # `score is None` where nothing in that dimension was ever checked, and
        # that is the architecture rather than a gap: a dimension with no
        # evidence has no score. Printing 0.0 would put Qevik at the bottom of
        # a scale it was never measured on, which is precisely the mistake the
        # three-state model exists to stop us making about other people.
        shown = f"{dimension.score:>5.1f}" if dimension.score is not None else "    —"
        bar = "#" * int(dimension.score / 10) if dimension.score else ""
        print(f"   {dimension.dimension:<20} {shown}  "
              f"confidence {dimension.confidence.value:<9} "
              f"({dimension.confirmed} checked, "
              f"{dimension.unverified} not)  {bar}")
    unmeasured = [d.dimension for d in readiness.dimensions if d.score is None]
    print(f"   actionable now: {len(readiness.actionable)}")
    if unmeasured:
        print(f"   no score at all for: {', '.join(unmeasured)} "
              "— never measured, not zero")

    # 2. Opportunities -----------------------------------------------------
    ranked = opp.for_host(WEBSITE, category="services", absent=absent,
                          present=present)
    print()
    print(f"2. OPPORTUNITIES  {len(ranked)}")
    for item in ranked[:8]:
        print(f"   priority {item.priority:<3} {item.key:<20} {item.name}")

    # 3. Recommendations ---------------------------------------------------
    # `unverified` is passed through deliberately. The recommender has to know
    # which features were never checked so it can refuse to sell against them —
    # an offer justified by a gap nobody looked for is the failure the whole
    # evidence model exists to prevent, and it is invisible unless the list
    # reaches this call.
    recommendations = rec_service.propose(
        business_id=BUSINESS, tenant_id=str(TENANT), opportunities=ranked,
        business_model="SERVICES", plan="ADVANCED", unverified=unverified)
    print()
    print(f"3. RECOMMENDATIONS  {len(recommendations)}")
    for entry in recommendations[:8]:
        print(f"   {entry.offer_id:<22} {entry.title[:44]:<44} "
              f"{entry.estimated_units:>5} units")

    # 4. Roadmap -----------------------------------------------------------
    roadmap = generate(business_id=BUSINESS, tenant_id=str(TENANT),
                       observations=OBSERVATIONS,
                       recommendations=recommendations,
                       business_model="SERVICES")
    facts = facts_for(roadmap, completed_task_ids=frozenset())
    ours = [t for t in roadmap.tasks if t.kind.value != "customer_task"]
    theirs = [t for t in roadmap.tasks if t.kind.value == "customer_task"]
    print()
    print(f"4. ROADMAP  {len(roadmap.tasks)} tasks "
          f"({len(ours)} Qevik, {len(theirs)} customer)")
    for task in roadmap.tasks[:8]:
        print(f"   [{task.kind.value:<14}] {task.task.title}")

    # 5. What our own generator would ship ---------------------------------
    # The engine's opinion of the artefact it would produce for us, run through
    # the same audit it runs on a stranger's site.
    from atlas_kernel.website.content import (
        ContactDetails,
        Fact,
        FactSource,
        Prose,
        Service,
        SiteContent,
    )
    from atlas_kernel.website.generation import generate as build

    def fact(value: str) -> Fact:
        return Fact(value=value, source=FactSource.OPERATOR)

    content = SiteContent(
        business_name=fact("Qevik"),
        tagline=fact("Evidence-based digital work for businesses in the UAE"),
        about=Prose(text=(
            "Qevik researches a business's digital presence, establishes what "
            "is actually there, and proposes only work that the evidence "
            "supports. Every finding is confirmed present, confirmed absent, or "
            "recorded as unverified — never assumed."), source=FactSource.OPERATOR),
        services=[
            Service(name=fact("Website audit"),
                    description=Prose(text="What is on your site now, checked "
                                           "rather than guessed.",
                                      source=FactSource.OPERATOR)),
            Service(name=fact("Website build"),
                    description=Prose(text="A fast, indexable site generated "
                                           "from facts you supplied.",
                                      source=FactSource.OPERATOR)),
            Service(name=fact("Search visibility"),
                    description=Prose(text="Technical SEO and measurement of "
                                           "what actually changed.",
                                      source=FactSource.OPERATOR)),
        ],
        contact=ContactDetails(email=fact("hello@qevik.ai")),
        location=fact("Dubai"))

    files, provenance = build(content, website=WEBSITE, published=False)
    inspection = seo.audit(files, website=WEBSITE)
    print()
    print(f"5. OUR OWN ARTEFACT  {len(files)} files: {', '.join(sorted(files))}")
    print(f"   audit: {inspection['statement']}")
    print(f"   indexable: {provenance['seo']['indexable']} "
          "(no domain agreed for publication, so robots disallows everything)")

    # 6. What the engine will not say --------------------------------------
    print()
    print("6. WHAT IT REFUSES TO CLAIM")
    print(f"   {len(unverified)} feature(s) were never checked. None of them "
          "appears as a strength")
    print("   or as a weakness — they are absent from both lists, which is the "
          "whole point.")
    for feature in sorted(unverified):
        assert feature not in {o.key for o in ranked}, (
            f"{feature} was never checked and became an opportunity")
    print("   Verified: no unverified feature reached the opportunity list.")

    report = {
        "business_id": BUSINESS, "tenant_id": str(TENANT), "website": WEBSITE,
        "at": datetime.now(UTC).isoformat(),
        "counts": {"present": len(present), "absent": len(absent),
                   "unverified": len(unverified)},
        "readiness": [{"dimension": d.dimension, "score": d.score,
                       "confidence": d.confidence.value,
                       "confirmed": d.confirmed, "unverified": d.unverified}
                      for d in readiness.dimensions],
        "opportunities": [{"key": o.key, "name": o.name,
                           "priority": o.priority} for o in ranked],
        "recommendations": [r.offer_id for r in recommendations],
        "roadmap": {"total": len(roadmap.tasks), "qevik": len(ours),
                    "customer": len(theirs),
                    "blocked": len(facts.blocked) if hasattr(facts, "blocked") else 0},
        "own_artefact": {"files": sorted(files),
                         "audit_clean": inspection["clean"],
                         "indexable": provenance["seo"]["indexable"]},
    }
    destination = ROOT / "docs/qevik-docs/autonomous/reports/qevik_self_assessment.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print()
    print(f"Written: {destination.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
