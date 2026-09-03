"""The floor plan, and the two ways a picture of an office lies.

An office view is a marketing surface pretending to be an operations one unless
it holds two properties, and both are tested here:

1. **Every agent gets a seat, including the ones that cannot work.** The
   temptation is to draw the working agents and omit the blocked ones, which
   turns the most actionable fact in the company — five seats waiting on one
   credential — into a gap in a drawing nobody notices.
2. **An unreadable fleet is not an empty one.** `known: false` must render as
   `unknown`, never as `idle`. The mission API already refuses that conflation;
   an office that reintroduced it would tell an operator their cluster died.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from atlas_kernel.fabric.agents import AGENTS, Capability
from atlas_kernel.fabric.office import ROOMS, STATE_MEANING, floor
from atlas_kernel.qevik import Wiring, create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(Wiring(repository_root=tmp_path,
                            vault_path=tmp_path / "vault.json"))
    with TestClient(app) as test_client:
        yield test_client


# --- the floor plan itself -----------------------------------------------------

def test_every_capability_has_exactly_one_room() -> None:
    """A capability in two rooms draws an agent twice; in none, it vanishes.

    This caught `GENERATE_VIDEO` having no room the first time it ran — the
    video agents would have disappeared from the company that is supposed to be
    building video companies.
    """
    placed = [c for room in ROOMS for c in room["capabilities"]]
    for capability in Capability:
        assert placed.count(capability) == 1, capability.value


def test_every_agent_gets_a_desk() -> None:
    seated = {desk["agent"] for room in floor()["rooms"] for desk in room["desks"]}
    assert seated == {agent.id for agent in AGENTS}


def test_blocked_agents_are_seated_not_hidden() -> None:
    """The empty desks are the point.

    Six of twenty-one agents cannot run. Each keeps its seat, in its room, with
    the reason attached — so the floor shows what the company would be doing if
    the blockers were cleared.
    """
    desks = {d["agent"]: d for room in floor()["rooms"] for d in room["desks"]}
    blocked = [a for a in AGENTS if a.blocked_by]
    assert blocked, "this test is meaningless if nothing is blocked"
    for agent in blocked:
        desk = desks[agent.id]
        assert desk["state"] == "blocked"
        assert desk["detail"], f"{agent.id} is blocked with no reason a person can read"
        assert desk["blockers"]


def test_the_unlocks_are_grouped_by_blocker_not_by_agent() -> None:
    """One line per credential to obtain, not one per agent waiting on it."""
    waiting = floor()["waiting_on"]
    assert waiting, "nothing is reported as blocked"
    assert waiting == sorted(waiting, key=lambda w: (-w["seats"], w["blocker"]))
    top = waiting[0]
    assert top["seats"] == len(top["agents"]) >= 2
    assert top["agents"] == sorted(top["agents"])


# --- an unreadable fleet is not an empty one -----------------------------------

def test_no_fleet_reads_as_unknown_never_idle() -> None:
    result = floor(None)
    states = {d["state"] for room in result["rooms"] for d in room["desks"]}
    assert "unknown" in states
    assert "idle" not in states
    assert result["fleet"]["known"] is False


def test_an_unreadable_fleet_reads_as_unknown() -> None:
    result = floor({"known": False, "workers": [],
                    "detail": "the cluster could not be read"})
    unblocked = [d for room in result["rooms"] for d in room["desks"] if not d["blockers"]]
    assert unblocked and all(d["state"] == "unknown" for d in unblocked)


def test_a_readable_empty_fleet_reads_as_idle() -> None:
    """Known and empty is a real answer, and a different one."""
    result = floor({"known": True, "workers": [], "counts": {"total": 0}})
    unblocked = [d for room in result["rooms"] for d in room["desks"] if not d["blockers"]]
    assert unblocked and all(d["state"] == "idle" for d in unblocked)


# --- what a worker changes -----------------------------------------------------

def _fleet(*workers: dict) -> dict:
    return {"known": True, "workers": list(workers), "counts": {"total": len(workers)}}


def test_a_free_worker_makes_its_capability_ready() -> None:
    result = floor(_fleet({"name": "worker-research", "capabilities": ["research"],
                           "healthy": True, "available": True, "load": 0}))
    desks = {d["agent"]: d for room in result["rooms"] for d in room["desks"]}
    assert desks["researcher"]["state"] == "ready"
    assert desks["researcher"]["worker"] == "worker-research"
    # An agent whose capability nothing serves is idle, not ready.
    assert desks["planner"]["state"] == "idle"


def test_a_busy_worker_makes_its_capability_working() -> None:
    result = floor(_fleet({"name": "worker-1", "capabilities": ["verify"],
                           "healthy": True, "available": False, "load": 1}))
    desks = {d["agent"]: d for room in result["rooms"] for d in room["desks"]}
    assert desks["self-check"]["state"] == "working"
    assert "worker-1" in desks["self-check"]["detail"]


def test_a_free_worker_wins_over_a_busy_one_for_the_same_capability() -> None:
    """Two machines, one busy: the room reads ready, because work can start."""
    result = floor(_fleet(
        {"name": "busy", "capabilities": ["research"], "healthy": True, "available": False},
        {"name": "free", "capabilities": ["research"], "healthy": True, "available": True},
    ))
    desks = {d["agent"]: d for room in result["rooms"] for d in room["desks"]}
    assert desks["researcher"]["state"] == "ready"
    assert desks["researcher"]["worker"] == "free"


def test_a_stale_worker_serves_nothing() -> None:
    """Stale keeps the mission it holds and takes nothing new — so the desk it
    would have served is idle, not ready."""
    result = floor(_fleet({"name": "gone", "capabilities": ["research"],
                           "healthy": False, "available": True}))
    desks = {d["agent"]: d for room in result["rooms"] for d in room["desks"]}
    assert desks["researcher"]["state"] == "idle"
    assert desks["researcher"]["worker"] is None


def test_a_blocked_agent_stays_blocked_even_with_a_free_worker() -> None:
    """A machine cannot supply a credential.

    The correspondent has a worker that could run it and no key to send with;
    reporting that as `ready` is how an operator concludes outreach works.
    """
    result = floor(_fleet({"name": "any", "capabilities": ["correspond"],
                           "healthy": True, "available": True}))
    desks = {d["agent"]: d for room in result["rooms"] for d in room["desks"]}
    assert desks["correspondent"]["state"] == "blocked"


# --- what the floor tells an operator ------------------------------------------

def test_irreversible_desks_are_marked() -> None:
    """Blast radius is the field that decides approval, so it is on the desk."""
    desks = {d["agent"]: d for room in floor()["rooms"] for d in room["desks"]}
    assert desks["correspondent"]["irreversible"] is True
    assert desks["researcher"]["irreversible"] is False
    growth = next(r for r in floor()["rooms"] if r["id"] == "growth")
    assert all(d["irreversible"] for d in growth["desks"]), (
        "every desk in Growth reaches the outside world; if that stops being "
        "true the room's purpose line is wrong")


def test_counts_add_up_to_the_headcount() -> None:
    result = floor()
    assert sum(result["counts"].values()) == result["headcount"] == len(AGENTS)
    assert set(result["counts"]) == set(STATE_MEANING)


def test_every_state_the_floor_can_report_has_a_meaning() -> None:
    """A state with no sentence behind it is a colour nobody can act on."""
    seen = {d["state"] for room in floor()["rooms"] for d in room["desks"]}
    for state in seen:
        assert STATE_MEANING[state]


# --- the route -----------------------------------------------------------------

def test_the_office_route_is_mounted_and_authenticated(client) -> None:
    body = client.get("/api/fabric/office").json()
    assert {"rooms", "counts", "waiting_on", "headcount"} <= set(body)
    assert body["headcount"] == len(AGENTS)


@pytest.mark.real_auth
def test_the_office_is_not_public(client) -> None:
    assert client.get("/api/fabric/office").status_code == 401


# --- the floor is actually shipped ---------------------------------------------

def test_the_floor_is_staged_before_the_swap_that_promotes_it() -> None:
    """Order, not merely presence.

    The first version of this copied the floor *after* the console's
    `.incoming` → live swap, which creates a fresh staging directory nothing
    ever promotes: the deploy would have exited zero having shipped a floor
    nobody could reach. Both copies must land in the staging directory, and the
    swap must come after both.
    """
    from pathlib import Path

    deploy = (Path(__file__).resolve().parents[3] / "infra" / "deploy_console.sh"
              ).read_text(encoding="utf-8")
    console = deploy.index('scp $SSH_ID -q -r "$LOCAL"/*')
    floor = deploy.index("apps/office/index.html")
    swap = deploy.index("mv $REMOTE.incoming $REMOTE")
    assert console < floor < swap, (
        "the floor must be staged with the console and promoted by the same swap")


def test_the_floor_is_a_single_self_contained_file() -> None:
    """The production CSP allows 'self' and inline only.

    A stylesheet link, a CDN script or a font host would be silently blocked in
    production and only in production — the failure mode this whole
    no-build-step architecture exists to avoid.
    """
    from pathlib import Path

    page = (Path(__file__).resolve().parents[3] / "apps" / "office" / "index.html"
            ).read_text(encoding="utf-8")
    assert "<script" in page and "<style" in page
    for forbidden in ("src=\"http", "href=\"http", "cdn.", "fonts.googleapis", "unpkg"):
        assert forbidden not in page, f"the floor reaches outside its own origin: {forbidden}"


def test_the_floor_hardcodes_no_host() -> None:
    """It is served from the machine it reads, so a baked-in address is how a
    console ends up reporting another host's state as its own."""
    from pathlib import Path

    page = (Path(__file__).resolve().parents[3] / "apps" / "office" / "index.html"
            ).read_text(encoding="utf-8")
    assert "2.28.62.83" not in page and "91.107.244.253" not in page


def test_the_floor_keeps_the_session_off_disk() -> None:
    """sessionStorage, never localStorage — the console's own rule, and the
    floor shares its origin, so a divergence here would leave a bearer token on
    disk for the same operator."""
    from pathlib import Path

    page = (Path(__file__).resolve().parents[3] / "apps" / "office" / "index.html"
            ).read_text(encoding="utf-8")
    assert "sessionStorage" in page
    assert "localStorage" not in page
