"""Does the /api/missions/actions route body serve what its producers make?

Reads only. Run on the control-plane host.

Written because testing the producers proved nothing about the endpoint: the
wiring that hands them to `controlplane.centre` was lost before it was
committed, and a production check that called `node_actions()` directly
reported success while the route served neither.

So this calls **the route's own function**, taken out of the deployed app's
router by path, against the real ledger. Not over HTTP: that would need a real
session, and the handler body is what was broken. Nothing here authenticates,
stores, or sends.
"""
from __future__ import annotations

from types import SimpleNamespace

from atlas_kernel.mission.api import build_router
from atlas_kernel.outreach import deliverability
from atlas_kernel.qevik.app import from_environment

TENANT = "qevik"


def _endpoint(routes, path: str, method: str = "GET"):
    for route in routes:
        if getattr(route, "path", None) == path and method in getattr(
                route, "methods", set()):
            return route.endpoint
    raise SystemExit(f"nothing serves {method} {path}")


def main() -> int:
    # The router the service installs, and the app it installs it into. Built
    # separately because `from_environment()` composes fewer routers than the
    # running process does, and this must exercise the handler that is actually
    # deployed rather than a smaller app that happens to import.
    app = from_environment()
    actions = _endpoint(build_router().routes, "/api/missions/actions")

    # The handler reads `request.app.state` and nothing else off the request.
    request = SimpleNamespace(app=app)
    operator = SimpleNamespace(username="verification", tenant_id=TENANT)

    body = actions(request=request, tenant=TENANT, _=operator)

    counts = body.get("counts", {})
    print("open actions: %d (%d blocking)" % (
        counts.get("total", 0), counts.get("blocking", 0)))
    for action in body.get("open", []):
        print("   [%-12s] %-18s blocking=%-5s %s" % (
            action["kind"], action["service"], action["blocking"],
            action["title"][:42]))

    served = {a["service"] for a in body.get("open", [])}
    machines = sorted(s for s in served if s.startswith("atlas-"))
    dns = sorted(s for s in served if s.startswith("dns:"))
    print("\nmachines still asked for : %s" % (machines or "none"))
    print("sending-identity action  : %s" % (dns or "none"))

    measured = deliverability.measure()
    print("\n%s, measured from this host" % measured.domain)
    for record in measured.records:
        print("   %-6s %-18s %s" % (
            record.name, record.state.value,
            (", ".join(record.values) or record.detail)[:50]))
    print("   ready_to_send=%s  can_receive_a_reply=%s  unreadable=%s" % (
        measured.ready_to_send, measured.can_receive_a_reply, measured.unreadable))

    # The route must agree with a direct measurement. Disagreement means the
    # endpoint serves something other than what the producers make, which is
    # the exact fault this exists to catch.
    if measured.unreadable and dns:
        print("\nMISMATCH: resolver unreadable yet a DNS action was served")
        return 1
    if measured.missing and not measured.unreadable and not dns:
        print("\nMISMATCH: records are missing and no DNS action was served")
        return 1
    print("\nthe route agrees with a direct measurement")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
