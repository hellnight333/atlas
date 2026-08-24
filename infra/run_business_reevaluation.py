"""Re-evaluate the businesses already researched, against the engine as it is now.

§16. Not a re-run of the old research — a comparison. The old evidence stays
exactly as recorded; the new engine reads the same observations and says what it
says today; and the difference is reported in two separate columns that must
never be merged: what changed about the business, and what changed about our
ability to check.

The subjects are the five prospects in `73_FIRST_COMMERCIAL_TEST.md`, with the
scores and the confirmed claims that were actually used to contact them. That
document is the record of what Qevik told real people.

Offline and deterministic. Re-crawling would answer a different question — "what
do their sites look like today" — and would make this script's output depend on
the network, which makes it useless as a record of what the *engine* changed.

    python3 infra/run_business_reevaluation.py
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "kernel"))

from atlas_kernel.execution.capabilities import (  # noqa: E402
    EXECUTORS,
    REQUIRES_CUSTOMER_INPUT,
)
from atlas_kernel.mission.reevaluation import compare  # noqa: E402
from atlas_kernel.outreach import opportunity as opp  # noqa: E402
from atlas_kernel.recommendation import service as rec_service  # noqa: E402
from atlas_kernel.roadmap import generate  # noqa: E402

TENANT = "tenant-qevik"

#: The five from `73_FIRST_COMMERCIAL_TEST.md`, with the claim each was actually
#: contacted about. `then` is what the audit recorded at the time; `now` is the
#: same evidence read by the current engine — identical, because nothing
#: re-crawled. Any difference in the output is therefore a change in *Qevik*,
#: which is the only question this script asks.
PROSPECTS = [
    {"id": "malabar-dental", "name": "Malabar Dental Clinic", "score": 78,
     "category": "dental", "website": "https://malabardental.ae",
     "claim": "no Arabic version",
     "then": [("arabic", "not_found"), ("https", "present"),
              ("click_to_call", "present"), ("page_title", "present"),
              ("social_proof", "unverified"), ("blog", "not_found")]},
    {"id": "topdent", "name": "The TopDent", "score": 69,
     "category": "dental", "website": "https://thetopdent.com",
     "claim": "no Arabic version",
     "then": [("arabic", "not_found"), ("https", "present"),
              ("click_to_call", "present"), ("page_speed", "unverified"),
              ("blog", "not_found")]},
    {"id": "pearl-dental", "name": "Pearl Dental Implants & Aligners", "score": 67,
     "category": "dental", "website": "https://pearldentaldubai.com",
     "claim": "no Arabic version",
     "then": [("arabic", "not_found"), ("https", "present"),
              ("click_to_call", "not_found"), ("contact_form", "not_found"),
              ("blog", "not_found")]},
    {"id": "360-agency", "name": "360 Agency / StaffFinder.io", "score": 86,
     "category": "staffing", "website": "https://stafffinder.io",
     "claim": "number not tappable on mobile",
     "then": [("click_to_call", "not_found"), ("arabic", "not_found"),
              ("https", "present"), ("contact_form", "present"),
              ("page_speed", "unverified")]},
    {"id": "ahs", "name": "AHS Catering & Events", "score": 83,
     "category": "food", "website": "https://ahscatering.com",
     "claim": "number not tappable on mobile",
     "then": [("click_to_call", "not_found"), ("arabic", "not_found"),
              ("portfolio_depth", "present"), ("social_proof", "present"),
              ("blog", "present"), ("blog_cadence", "not_found"),
              ("https", "present")]},
]


def _observations(pairs: list[tuple[str, str]]) -> list[dict]:
    return [{"feature": feature, "status": status} for feature, status in pairs]


def _engine(prospect: dict) -> dict:
    """What the engine says about this business today."""
    observations = _observations(prospect["then"])
    absent = frozenset(o["feature"] for o in observations
                       if o["status"] == "not_found")
    present = frozenset(o["feature"] for o in observations
                        if o["status"] == "present")
    unverified = frozenset(o["feature"] for o in observations
                           if o["status"] == "unverified")

    ranked = opp.for_host(prospect["website"], category=prospect["category"],
                          absent=absent, present=present)
    recommendations = rec_service.propose(
        business_id=prospect["id"], tenant_id=TENANT, opportunities=ranked,
        business_model=prospect["category"].upper(), plan="ADVANCED",
        unverified=unverified)
    roadmap = generate(business_id=prospect["id"], tenant_id=TENANT,
                       observations=observations,
                       recommendations=recommendations,
                       business_model=prospect["category"].upper())
    executable = [t for t in roadmap.tasks
                  if t.executability.value == "qevik_can_execute"]
    return {"opportunities": ranked, "recommendations": recommendations,
            "roadmap": roadmap, "executable": executable}


def main() -> int:
    print("=" * 78)
    print("RE-EVALUATION OF THE FIVE PROSPECTS QEVIK ACTUALLY CONTACTED")
    print("=" * 78)
    print("Source: docs/qevik-docs/73_FIRST_COMMERCIAL_TEST.md")
    print("Nothing was re-crawled. The evidence is unchanged, so every "
          "difference below is\na change in Qevik rather than in them.")

    rows = []
    for prospect in PROSPECTS:
        observations = _observations(prospect["then"])
        # The §18 comparison, old against new. Identical inputs by design:
        # it establishes that no evidence moved, so the engine's output is the
        # only variable — and it exercises the same code a real re-check uses.
        delta = compare(business_id=prospect["id"], tenant=TENANT,
                        previous=observations, current=observations)
        assert not delta.anything_changed, "the evidence must be unchanged"

        result = _engine(prospect)
        offers = {r.offer_id for r in result["recommendations"]}
        needs_customer = sorted(o for o in offers if o in REQUIRES_CUSTOMER_INPUT)
        # Runnable *today*, which excludes anything waiting on the customer.
        # Listing an offer under both is the contradiction `_executable` exists
        # to prevent, and the first version of this script printed it.
        deliverable = sorted(o for o in offers
                             if o in EXECUTORS and o not in REQUIRES_CUSTOMER_INPUT)
        undeliverable = sorted(o for o in offers if o not in EXECUTORS)

        # The claim they were actually contacted about, and whether anything
        # could have performed the fix at the time.
        claim_offer = ("offer-arabic-experience" if "Arabic" in prospect["claim"]
                       else "offer-one-tap-contact")

        print()
        print(f"{prospect['name']}  (score {prospect['score']})")
        print(f"  contacted about : {prospect['claim']}")
        print(f"  opportunities   : {len(result['opportunities'])}")
        print(f"  recommendations : {len(result['recommendations'])}")
        print(f"  Qevik can run   : {', '.join(deliverable) or 'nothing yet'}")
        if needs_customer:
            print(f"  needs them first: {', '.join(needs_customer)}")
        if undeliverable:
            print(f"  no executor     : {', '.join(undeliverable)}")

        rows.append({
            "business_id": prospect["id"], "name": prospect["name"],
            "score_then": prospect["score"], "claim_used": prospect["claim"],
            "evidence_unchanged": True,
            "comparison": delta.summary(),
            "opportunities": [o.key for o in result["opportunities"]],
            "recommendations": sorted(offers),
            "executable_now": deliverable,
            "requires_customer_input": needs_customer,
            "no_executor": undeliverable,
            "claim_offer": claim_offer,
            "claim_deliverable_now": claim_offer in EXECUTORS,
        })

    # ---------------------------------------------------------------- finding
    arabic_pitched = [r for r in rows if r["claim_offer"] == "offer-arabic-experience"]
    contact_pitched = [r for r in rows if r["claim_offer"] == "offer-one-tap-contact"]

    print()
    print("=" * 78)
    print("WHAT THE RE-EVALUATION FOUND")
    print("=" * 78)
    print(f"  {len(arabic_pitched)} of {len(rows)} were contacted about a "
          "missing Arabic version.")
    print("  Until this session there was no executor for "
          "`offer-arabic-experience`, so")
    print("  Qevik pitched work it could not perform. There is one now, and it "
          "requires")
    print("  Arabic copy the customer supplies — which is a task for them, "
          "stated up front,")
    print("  rather than a promise that fails at execution.")
    print()
    print(f"  {len(contact_pitched)} were contacted about a phone number not "
          "being tappable.")
    print("  `offer-one-tap-contact` still has no executor: the theme already "
          "renders a")
    print("  `tel:` link, so the fix is inside `offer-website` rather than a "
          "capability of")
    print("  its own. Recorded as such rather than counted as a gap.")
    print()
    print("  This is the useful kind of re-evaluation: the businesses did not "
          "change and")
    print("  the evidence did not change. What changed is what Qevik can "
          "honestly offer.")

    report = {
        "at": datetime.now(UTC).isoformat(),
        "source": "docs/qevik-docs/73_FIRST_COMMERCIAL_TEST.md",
        "recrawled": False,
        "tenant_id": TENANT,
        "prospects": rows,
        "finding": {
            "pitched_arabic": len(arabic_pitched),
            "pitched_contact": len(contact_pitched),
            "arabic_deliverable_now": "offer-arabic-experience" in EXECUTORS,
            "arabic_requires_customer_input":
                "offer-arabic-experience" in REQUIRES_CUSTOMER_INPUT,
            "statement": ("Nothing about these businesses changed and no "
                          "evidence moved. What changed is that the work Qevik "
                          "pitched to three of them now has an executor, and "
                          "that it is correctly presented as requiring "
                          "something from the customer first."),
        },
    }
    destination = (ROOT / "docs/qevik-docs/autonomous/reports"
                   / "business_reevaluation.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, default=str) + "\n",
                           encoding="utf-8")
    print()
    print(f"Written: {destination.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
