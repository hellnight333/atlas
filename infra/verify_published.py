"""What Qevik has published, and whether it is still up. Reads only.

Run on the control-plane host. Calls the route's own function, for the same
reason `verify_action_centre.py` does: a check that calls the producers proves
nothing about what the endpoint serves.

The commercial point of this: a demo address travels inside an approved outreach
message. If one is dead, an approved message points a stranger at nothing.
"""
from __future__ import annotations

from types import SimpleNamespace

from atlas_kernel.mission.api import build_router

TENANT = "qevik"


def _endpoint(routes, path: str, method: str = "GET"):
    for route in routes:
        if getattr(route, "path", None) == path and method in getattr(
                route, "methods", set()):
            return route.endpoint
    raise SystemExit(f"nothing serves {method} {path}")


def main() -> int:
    from atlas_kernel.qevik.app import from_environment

    app = from_environment()
    published = _endpoint(build_router().routes, "/api/missions/published")
    request = SimpleNamespace(app=app)
    operator = SimpleNamespace(username="verification", tenant_id=TENANT)

    listing = published(request=request, limit=500, check=False, _=operator)
    counts = listing["counts"]
    print("published addresses on the timeline: %d (%d demos)" % (
        counts["total"], counts["demos"]))
    if not counts["total"]:
        print("nothing published; nothing to check")
        return 0

    print("\nasking each one...")
    checked = published(request=request, limit=500, check=True, _=operator)
    c = checked["counts"]
    print("live=%d  down=%d  could-not-check=%d" % (
        c["live"], c["down"], c["unchecked"]))

    bad = [r for r in checked["published"]
           if r["liveness"] == "CONFIRMED_DOWN"]
    unknown = [r for r in checked["published"]
               if r["liveness"] == "NOT_CHECKED"]

    for row in bad:
        print("   DOWN   %-52s %s" % (row["url"][:52], row["detail"][:34]))
    for row in unknown:
        print("   ?      %-52s %s" % (row["url"][:52], row["detail"][:34]))

    dead_demos = [r for r in bad if r["is_demo"]]
    if dead_demos:
        print("\n%d demo address(es) are down. Each one may be inside an "
              "approved outreach message." % len(dead_demos))
        return 1
    print("\nno demo address is down")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
