#!/usr/bin/env python3
"""Move test-suite residue out of the business tables, reversibly.

The production database accumulated fixtures from before the test suite was
isolated. They are indistinguishable from real prospects by name — one is called
"Al Noor Dental Clinic" — so classification uses facts rather than appearances:

* a website on an RFC 2606/6761 reserved TLD (`.test`, `.example`, `.invalid`,
  `.localhost`) can never be a real business address;
* a generated hostname (`tl-c2a8712423.ae`) whose host does not resolve;
* and in either case, **zero commercial history** — no audit, screenshot,
  research, verification, or outreach.

A row is only a fixture when a conclusive signal *and* the absence of history
agree. Anything else is AMBIGUOUS and is never touched.

Quarantine, not deletion. Every row is copied whole into
`atlas_quarantined_fixtures` with its source table, primary key, the reason and
the evidence, so restoring it is an INSERT … SELECT. `atlas_quarantined_fixtures`
is an operational archive: it holds no business identity, nothing joins to it,
and nothing reads it except a human asking what was moved.

    quarantine_business_fixtures.py                 # dry run, changes nothing
    quarantine_business_fixtures.py --apply
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "kernel"))

from sqlalchemy import text  # noqa: E402

from atlas_kernel.db import SessionLocal  # noqa: E402

RESERVED = re.compile(r"\.(test|example|invalid|localhost)(/|$|:)", re.I)
GENERATED_HOST = re.compile(r"-[0-9a-f]{8,}\.", re.I)

#: Evidence that real work happened for this business. A row carrying any of
#: these is never a fixture, whatever its address looks like.
COMMERCIAL_KINDS = ("website_audited", "screenshot_captured", "researched",
                    "claims_verified", "experiment_sent", "experiment_response")

#: Children first — a business row is removed only once nothing references it.
CHILD_TABLES = ("atlas_findings", "atlas_opportunities", "atlas_proposals",
                "atlas_outreach_messages", "atlas_business_events")

#: The archive already exists from an earlier quarantine and holds 189 rows,
#: with `id` carrying the *original* primary key — the same thing this tool
#: needs. So it is extended rather than replaced: three additive columns, no
#: existing row touched, one archive rather than two.
QUARANTINE_DDL = (
    """CREATE TABLE IF NOT EXISTS atlas_quarantined_fixtures (
        id             TEXT,
        source_table   TEXT NOT NULL,
        reason         TEXT NOT NULL,
        row            JSONB NOT NULL,
        quarantined_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    "ALTER TABLE atlas_quarantined_fixtures ADD COLUMN IF NOT EXISTS business_id TEXT",
    "ALTER TABLE atlas_quarantined_fixtures ADD COLUMN IF NOT EXISTS "
    "evidence JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE atlas_quarantined_fixtures ADD COLUMN IF NOT EXISTS run_id TEXT",
)


def host_of(url: str) -> str:
    match = re.match(r"https?://([^/:]+)", url or "")
    return match.group(1).lower() if match else ""


def resolves(host: str) -> bool:
    try:
        socket.getaddrinfo(host, None)
        return True
    except Exception:                            # noqa: BLE001
        return False


def classify(session) -> dict[str, list[tuple[str, str, dict]]]:
    """Re-derive the classification from live data. Never trusts a cached list."""
    rows = list(session.execute(text(
        "SELECT id, name, website FROM atlas_businesses")))
    history = dict(session.execute(text(
        "SELECT business_id, COUNT(*) FROM atlas_business_events "
        f"WHERE kind IN {COMMERCIAL_KINDS} GROUP BY 1")).all())
    outreach = dict(session.execute(text(
        "SELECT business_id, COUNT(*) FROM atlas_outreach_messages GROUP BY 1")).all())

    testable = {host_of(r[2]) for r in rows
                if host_of(r[2]) and not RESERVED.search(r[2] or "")}
    with ThreadPoolExecutor(max_workers=24) as pool:
        dns = dict(zip(testable, pool.map(resolves, testable)))

    out: dict[str, list] = {"REAL": [], "FIXTURE": [], "AMBIGUOUS": []}
    for business_id, name, website in rows:
        site = website or ""
        host = host_of(site)
        commercial = history.get(business_id, 0) + outreach.get(business_id, 0)
        evidence = {"website": site, "host": host, "resolves": dns.get(host),
                    "reserved_tld": bool(RESERVED.search(site)) or not site,
                    "generated_host": bool(GENERATED_HOST.search(host)),
                    "commercial_records": commercial}
        if evidence["reserved_tld"]:
            bucket = "FIXTURE" if commercial == 0 else "AMBIGUOUS"
            reason = ("website on an RFC-reserved TLD, or no website, and no history"
                      if commercial == 0 else
                      f"reserved TLD but {commercial} commercial records — not classified")
        elif dns.get(host):
            bucket = "REAL" if commercial else "AMBIGUOUS"
            reason = ("host resolves and carries commercial history" if commercial
                      else "host resolves but carries no history — not classified")
        elif evidence["generated_host"]:
            bucket = "FIXTURE" if commercial == 0 else "AMBIGUOUS"
            reason = ("generated hostname that does not resolve, and no history"
                      if commercial == 0 else
                      f"generated hostname but {commercial} commercial records — not classified")
        else:
            bucket = "AMBIGUOUS"
            reason = "does not resolve, hostname not obviously generated"
        out[bucket].append((business_id, name, {**evidence, "reason": reason}))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expect-real", type=int, default=352)
    parser.add_argument("--expect-fixture", type=int, default=747)
    parser.add_argument("--expect-ambiguous", type=int, default=1)
    args = parser.parse_args()

    run_id = f"quarantine-{datetime.now(UTC):%Y%m%d-%H%M%S}"
    session = SessionLocal()
    try:
        buckets = classify(session)
        real = [b for b, _n, _e in buckets["REAL"]]
        fixture = [(b, n, e) for b, n, e in buckets["FIXTURE"]]
        ambiguous = buckets["AMBIGUOUS"]

        print(f"run {run_id}")
        print(f"  REAL       {len(real):>5}")
        print(f"  FIXTURE    {len(fixture):>5}")
        print(f"  AMBIGUOUS  {len(ambiguous):>5}")
        for _b, name, ev in ambiguous:
            print(f"    untouched: {name!r} {ev['website']} — {ev['reason']}")

        # --- gate: the counts must be the ones that were approved -----------
        actual = (len(real), len(fixture), len(ambiguous))
        expected = (args.expect_real, args.expect_fixture, args.expect_ambiguous)
        if actual != expected:
            print(f"\nSTOP — counts changed. expected {expected}, observed {actual}. "
                  "Nothing was modified.")
            return 2

        fixture_ids = [b for b, _n, _e in fixture]

        # --- gate: fixtures must carry no commercial history ---------------
        leaking = session.execute(text(
            "SELECT COUNT(*) FROM atlas_business_events WHERE business_id = ANY(:i) "
            f"AND kind IN {COMMERCIAL_KINDS}"), {"i": fixture_ids}).scalar()
        outreach = session.execute(text(
            "SELECT COUNT(*) FROM atlas_outreach_messages WHERE business_id = ANY(:i)"),
            {"i": fixture_ids}).scalar()
        print(f"\n  commercial events on the fixture set : {leaking} (must be 0)")
        print(f"  outreach on the fixture set          : {outreach} (must be 0)")
        if leaking or outreach:
            print("STOP — a fixture carries commercial history. Nothing was modified.")
            return 2

        related = {}
        for table in CHILD_TABLES:
            related[table] = session.execute(text(
                f"SELECT COUNT(*) FROM {table} WHERE business_id = ANY(:i)"),
                {"i": fixture_ids}).scalar()
        print("\n  rows that would move with them:")
        for table, count in related.items():
            print(f"    {table:<28}{count}")
        print(f"    {'atlas_businesses':<28}{len(fixture_ids)}")
        total = sum(related.values()) + len(fixture_ids)
        print(f"    {'TOTAL':<28}{total}")

        before = {t: session.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
                  for t in (*CHILD_TABLES, "atlas_businesses")}
        real_history_before = session.execute(text(
            "SELECT COUNT(*) FROM atlas_business_events WHERE business_id = ANY(:i)"),
            {"i": real}).scalar()

        if not args.apply:
            print("\ndry run — nothing changed. Re-run with --apply.")
            return 0

        # --- the mutation, one transaction --------------------------------
        for statement in QUARANTINE_DDL:
            session.execute(text(statement))
        session.execute(text(
            "CREATE TEMP TABLE _classified (business_id TEXT PRIMARY KEY, "
            "reason TEXT NOT NULL, evidence JSONB NOT NULL) ON COMMIT DROP"))
        session.execute(
            text("INSERT INTO _classified (business_id, reason, evidence) "
                 "VALUES (:b, :r, CAST(:e AS jsonb))"),
            [{"b": b, "r": e["reason"], "e": json.dumps(e)} for b, _n, e in fixture])
        moved = 0
        for table in (*CHILD_TABLES, "atlas_businesses"):
            key = "id" if table == "atlas_businesses" else "id"
            owner = "t.id" if table == "atlas_businesses" else "t.business_id"
            copied = session.execute(text(f"""
                INSERT INTO atlas_quarantined_fixtures
                    (id, source_table, business_id, reason, evidence, row, run_id)
                SELECT t.{key}::text, :t, {owner}::text, c.reason, c.evidence,
                       to_jsonb(t), :run
                FROM {table} t
                JOIN _classified c ON c.business_id = {owner}"""),
                {"t": table, "run": run_id}).rowcount
            removed = session.execute(text(
                f"DELETE FROM {table} WHERE "
                f"{'id' if table == 'atlas_businesses' else 'business_id'} = ANY(:ids)"),
                {"ids": fixture_ids}).rowcount
            print(f"    {table:<28}copied {copied:>5}   removed {removed:>5}")
            if copied != removed:
                session.rollback()
                print(f"STOP — {table}: copied {copied} but removed {removed}. Rolled back.")
                return 2
            moved += removed

        # --- gates after the mutation, before commit ----------------------
        after_real = session.execute(text("SELECT COUNT(*) FROM atlas_businesses")).scalar()
        real_history_after = session.execute(text(
            "SELECT COUNT(*) FROM atlas_business_events WHERE business_id = ANY(:i)"),
            {"i": real}).scalar()
        orphans = session.execute(text(
            "SELECT COUNT(*) FROM atlas_business_events e WHERE NOT EXISTS "
            "(SELECT 1 FROM atlas_businesses b WHERE b.id = e.business_id)")).scalar()

        print(f"\n  businesses remaining        : {after_real} "
              f"(expected {len(real) + len(ambiguous)})")
        print(f"  real commercial history     : {real_history_before} -> {real_history_after}")
        print(f"  orphaned events             : {orphans}")

        if after_real != len(real) + len(ambiguous):
            session.rollback()
            print("STOP — business count wrong after removal. Rolled back.")
            return 2
        if real_history_after != real_history_before:
            session.rollback()
            print("STOP — real commercial history changed. Rolled back.")
            return 2
        if orphans:
            session.rollback()
            print(f"STOP — {orphans} orphaned events. Rolled back.")
            return 2

        session.commit()
        print(f"\ncommitted. {moved} rows quarantined under run {run_id}.")
        print("restore with:  INSERT INTO <table> SELECT (row).* FROM "
              f"atlas_quarantined_fixtures WHERE run_id = '{run_id}'")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
