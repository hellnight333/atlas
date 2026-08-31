"""How many businesses publish an address we could read? Reads their sites only.

Run on the control-plane host. Fetches homepages through the same guarded
browser the audit uses — the audit is what will do this in the nightly pass, and
this measures the population before committing to email as a channel at all.

Writes nothing. Records no contactability. The point is to answer whether email
is a real channel for this population before DNS and SMTP are touched.
"""
from __future__ import annotations

import collections
import sys
import time

from sqlalchemy import text

from atlas_kernel.browser.failures import reachability
from atlas_kernel.browser.session import PlaywrightSession
from atlas_kernel.db import SessionLocal
from atlas_kernel.opportunity.contacts import (
    ContactType,
    contactable_at,
    observed,
)


def main(limit: int) -> int:
    with SessionLocal() as s:
        rows = s.execute(text("""
            SELECT b.id, b.name, b.website, b.phone
            FROM atlas_businesses b
            WHERE b.website IS NOT NULL AND b.website <> ''
              AND (b.email IS NULL OR b.email = '')
            ORDER BY b.name LIMIT :limit"""), {"limit": limit}).mappings().all()

    print("sampling %d businesses with a website and no address on file\n" % len(rows))

    kinds: collections.Counter = collections.Counter()
    presented: collections.Counter = collections.Counter()
    addresses: dict[str, set] = collections.defaultdict(set)
    per_business: dict[str, list] = collections.defaultdict(list)
    checked, failed_ours, failed_theirs = 0, 0, 0
    # The categories the funnel needs, kept apart rather than summed.
    by_business_email: set = set()
    by_individual: set = set()
    only_unusable: set = set()
    none_at_all: set = set()
    with_phone_too = 0
    provenance_named = 0

    session = PlaywrightSession(headless=True, viewport=(390, 844)).start()
    try:
        for row in rows:
            try:
                session.open(row["website"])
                html = session.extract("document.documentElement.outerHTML") or ""
            except Exception as failure:                  # noqa: BLE001
                answered, _ = reachability(str(failure))
                if answered is None:
                    failed_ours += 1
                else:
                    failed_theirs += 1
                continue
            checked += 1
            found = observed(html, url=row["website"])
            for one in found:
                kinds[one.contact_type.value] += 1
                presented[one.presented.value] += 1
                addresses[one.address].add(row["id"])
                per_business[row["id"]].append(one)
                if one.displayed_name or one.displayed_role:
                    provenance_named += 1
            usable = contactable_at(found)
            kinds_here = {one.contact_type for one in found}
            if not found:
                none_at_all.add(row["id"])
            elif ContactType.BUSINESS in kinds_here:
                by_business_email.add(row["id"])
            elif ContactType.INDIVIDUAL in kinds_here:
                by_individual.add(row["id"])
            else:
                only_unusable.add(row["id"])
            if usable:
                if (row["phone"] or "").strip():
                    with_phone_too += 1
                shown = next(o for o in found if o.usable)
                print("   %-30s %-30s %s%s" % (
                    row["name"][:30], usable, shown.contact_type.value[:12],
                    f"  [{shown.displayed_name} / {shown.displayed_role}]"
                    if shown.displayed_name or shown.displayed_role else ""))
            time.sleep(1.5)
    finally:
        session.close()

    shared = {a: ids for a, ids in addresses.items() if len(ids) > 1}
    several = {b: found for b, found in per_business.items() if len(found) > 1}
    contactable = len(by_business_email) + len(by_individual)

    print("\n--- of %d sampled ---" % len(rows))
    print("   pages read                     : %d" % checked)
    print("   our own failure                : %d" % failed_ours)
    print("   site did not answer            : %d" % failed_theirs)
    print()
    print("   1. business email              : %d" % len(by_business_email))
    print("   2. individual business contact : %d" % len(by_individual))
    print("   3. only ambiguous/personal     : %d" % len(only_unusable))
    print("   4. no address observed at all  : %d" % len(none_at_all))
    print("   ------------------------------")
    print("   email-contactable (1 + 2)      : %d" % contactable)
    if checked:
        print("   rate among pages read          : %.0f%%"
              % (100.0 * contactable / checked))
    print("   ...also reachable by phone     : %d  (overlap)" % with_phone_too)
    print()
    print("   distinct addresses seen        : %d" % len(addresses))
    print("   5. one address, >1 business    : %d" % len(shared))
    for address, ids in list(shared.items())[:5]:
        print("         %-34s %d businesses" % (address, len(ids)))
    print("   6. one business, >1 address    : %d" % len(several))
    print()
    print("   7. provenance: addresses with a displayed name or role: %d of %d"
          % (provenance_named, sum(len(v) for v in per_business.values())))
    print("      by type      : %s" % dict(kinds))
    print("      by how stated: %s" % dict(presented))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 40))
