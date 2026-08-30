"""Does the deployed kernel answer the questions the console puts to it?

Run on the control-plane host, against the real ledger. Reads only.

Two claims are checked, both of which were wrong in production before the
change this verifies:

  - a failed mission reports *why* it failed, not the note of whichever event
    the worker happened to write last;
  - a machine that has joined the fleet is not still being asked for.
"""
from __future__ import annotations

import json

from sqlalchemy import text

from atlas_kernel.controlplane.actions import node_actions
from atlas_kernel.db import SessionLocal
from atlas_kernel.mission import service
from atlas_kernel.mission.nodes import snapshots


def main() -> int:
    with SessionLocal() as session:
        rows = [{"kind": kind,
                 "detail": json.loads(detail) if isinstance(detail, str) else detail}
                for kind, detail in session.execute(text(
                    "SELECT kind, detail FROM atlas_business_events "
                    "WHERE kind='mission_transition'"))]
    if not rows:
        print("no mission transitions on this deployment; nothing to check")
        return 0

    tenant = rows[0]["detail"].get("tenant_id")
    folded = service.fold(rows, tenant=tenant)
    print("missions: %d" % len(folded))

    ended = [m for m in folded if m["status"] in ("failed", "cancelled")]
    print("\nended badly: %d" % len(ended))
    for mission in ended:
        print("   %-10s because = %s" % (
            mission["status"], (mission.get("because") or "(none)")[:56]))
        print("   %-10s note    = %s" % (
            "", (mission.get("note") or "(none)")[:56]))

    # The exact symptom: every failed mission reporting the last note written.
    borrowed = [m for m in ended if m.get("because") == m.get("note")
                and (m.get("note") or "") == "report written"]
    print("\nreporting 'report written' as the reason: %d" % len(borrowed))

    known = snapshots()
    identifiers = None if known is None else tuple(n.node_id for n in known)
    print("\nfleet known: %s" % (
        "no - unreadable" if identifiers is None
        else "%d worker(s)" % len(identifiers)))
    outstanding = node_actions(identifiers, tenant=tenant)
    for action in outstanding:
        print("   %-16s blocking=%s | %s" % (
            action.service, action.blocking, action.verification[:50]))

    return 1 if borrowed else 0


if __name__ == "__main__":
    raise SystemExit(main())
