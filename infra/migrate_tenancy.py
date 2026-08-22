#!/usr/bin/env python3
"""P1.1 — give the verified real businesses an owner.

Establishes the ownership chain and nothing else. It adds nullable columns,
indexes them, and assigns exactly the businesses that classification proved
real to the Qevik house organization.

What it deliberately does not do: touch the legacy test residue, classify or
assign the one ambiguous business, apply NOT NULL, reassign any existing
organization to the Qevik tenant, or clean anything up. Residue keeps a NULL
tenant because that is the honest record — those rows have no owner and no
`business_id` by which they could acquire one.

The classifier is imported from the quarantine tool rather than restated, so the
set assigned here is by construction the set that survived Phase 1a.

    migrate_tenancy.py            # dry run, changes nothing
    migrate_tenancy.py --apply
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "kernel"))

from sqlalchemy import text  # noqa: E402

from atlas_kernel.db import SessionLocal, engine  # noqa: E402

HOUSE_ORG = "org-a393025bd19e"
HOUSE_TENANT = "tenant-b9d7bfaa4fd8"

#: Columns are nullable on purpose. Legacy residue keeps NULL permanently, so a
#: NOT NULL here would either fail or force a fictional owner onto 8,000 rows.
COLUMNS = (
    ("atlas_businesses", "organization_id", "TEXT"),
    ("atlas_businesses", "tenant_id", "TEXT"),
    ("atlas_projects", "business_id", "TEXT"),
    ("atlas_projects", "tenant_id", "TEXT"),
    ("atlas_jobs", "project_id", "TEXT"),
    ("atlas_jobs", "tenant_id", "TEXT"),
)

INDEXES = (
    ("atlas_businesses_tenant_idx", "atlas_businesses", "tenant_id"),
    ("atlas_businesses_org_idx", "atlas_businesses", "organization_id"),
    ("atlas_projects_tenant_idx", "atlas_projects", "tenant_id"),
    ("atlas_projects_business_idx", "atlas_projects", "business_id"),
    ("atlas_jobs_tenant_idx", "atlas_jobs", "tenant_id"),
)

#: RESTRICT, never CASCADE. Deleting an organization must not silently delete a
#: customer's businesses; it should fail until somebody deals with the data.
FK = ("atlas_businesses_organization_fk", "atlas_businesses", "organization_id",
      "atlas_organizations", "id")


def load_classifier():
    """The Phase 1a classifier itself, not a copy of it."""
    path = Path(__file__).with_name("quarantine_business_fixtures.py")
    spec = importlib.util.spec_from_file_location("quarantine_business_fixtures", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.classify


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expect-real", type=int, default=352)
    parser.add_argument("--expect-ambiguous", type=int, default=1)
    args = parser.parse_args()

    classify = load_classifier()
    session = SessionLocal()
    try:
        house = session.execute(text(
            "SELECT id, name, slug, tenant_id FROM atlas_organizations WHERE id = :i"),
            {"i": HOUSE_ORG}).first()
        if house is None:
            print(f"STOP — house organization {HOUSE_ORG} does not exist.")
            return 2
        if house[3] != HOUSE_TENANT:
            print(f"STOP — tenant mismatch: expected {HOUSE_TENANT}, found {house[3]}.")
            return 2
        print(f"house organization : {house[0]}  {house[1]!r}  slug={house[2]!r}")
        print(f"tenant             : {house[3]}")

        buckets = classify(session)
        real = [b for b, _n, _e in buckets["REAL"]]
        fixture = buckets["FIXTURE"]
        ambiguous = buckets["AMBIGUOUS"]
        print(f"\nclassification     : REAL {len(real)}  "
              f"FIXTURE {len(fixture)}  AMBIGUOUS {len(ambiguous)}")
        for _b, name, ev in ambiguous:
            print(f"  excluded, untouched: {name!r} {ev['website']}")

        if len(real) != args.expect_real or len(ambiguous) != args.expect_ambiguous:
            print(f"\nSTOP — expected {args.expect_real} real and "
                  f"{args.expect_ambiguous} ambiguous; found {len(real)} and "
                  f"{len(ambiguous)}. Nothing was modified.")
            return 2
        if fixture:
            print(f"\nSTOP — {len(fixture)} fixtures are still present; Phase 1a should "
                  "have removed them. Nothing was modified.")
            return 2

        total = session.execute(text("SELECT COUNT(*) FROM atlas_businesses")).scalar()
        print(f"businesses total   : {total}  "
              f"({len(real)} to own, {len(ambiguous)} left unassigned)")

        if not args.apply:
            print("\nwould add columns :")
            for table, column, kind in COLUMNS:
                print(f"    {table}.{column} {kind} NULL")
            print("  would index (concurrently):")
            for name, table, column in INDEXES:
                print(f"    {name} on {table}({column})")
            print(f"  would add FK      : {FK[1]}.{FK[2]} -> {FK[3]}({FK[4]}) ON DELETE RESTRICT")
            print(f"  would backfill    : {len(real)} businesses -> {HOUSE_ORG}")
            print("\ndry run — nothing changed. Re-run with --apply.")
            return 0

        # -- step 2: columns, one transaction ---------------------------------
        for table, column, kind in COLUMNS:
            session.execute(text(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {kind}"))
        session.commit()
        print("\n  columns added")

        # -- step 3: indexes, outside any transaction -------------------------
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            for name, table, column in INDEXES:
                conn.execute(text(
                    f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {table} ({column})"))
        print("  indexes created concurrently")

        # -- step 4 and 5: backfill, then verify before committing ------------
        updated = session.execute(text(
            "UPDATE atlas_businesses SET organization_id = :o, tenant_id = :t "
            "WHERE id = ANY(:ids) AND organization_id IS NULL"),
            {"o": HOUSE_ORG, "t": HOUSE_TENANT, "ids": real}).rowcount
        owned = session.execute(text(
            "SELECT COUNT(*) FROM atlas_businesses WHERE organization_id = :o"),
            {"o": HOUSE_ORG}).scalar()
        unassigned = session.execute(text(
            "SELECT COUNT(*) FROM atlas_businesses WHERE organization_id IS NULL")).scalar()
        events = session.execute(text("SELECT COUNT(*) FROM atlas_business_events")).scalar()
        outreach = session.execute(text("SELECT COUNT(*) FROM atlas_outreach_messages")).scalar()
        residue = session.execute(text(
            "SELECT COUNT(*) FROM atlas_projects WHERE tenant_id IS NOT NULL")).scalar()

        print(f"  backfilled         : {updated}")
        print(f"  owned by Qevik     : {owned}   (expected {len(real)})")
        print(f"  left unassigned    : {unassigned}   (expected {len(ambiguous)})")
        print(f"  events / outreach  : {events} / {outreach}")
        print(f"  residue given a tenant: {residue}   (must be 0)")

        if owned != len(real) or unassigned != len(ambiguous) or residue:
            session.rollback()
            print("STOP — counts wrong after backfill. Rolled back.")
            return 2
        if events != 1301 or outreach != 16:
            session.rollback()
            print(f"STOP — commercial history moved: {events} events, {outreach} outreach. "
                  "Rolled back.")
            return 2

        # -- step 6: the foreign key ------------------------------------------
        session.execute(text(
            f"ALTER TABLE {FK[1]} ADD CONSTRAINT {FK[0]} FOREIGN KEY ({FK[2]}) "
            f"REFERENCES {FK[3]}({FK[4]}) ON DELETE RESTRICT"))
        session.commit()
        print("  foreign key added  : ON DELETE RESTRICT")
        print("\ncommitted.")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
