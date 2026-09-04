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


def test_a_free_worker_makes_the_agent_it_serves_ready() -> None:
    """The shape production actually publishes: a `serves` field and tool ids."""
    result = floor(_fleet({"name": "worker-research", "serves": "researcher",
                           "capabilities": ["dns", "http-fetch"],
                           "healthy": True, "available": True, "load": 0}))
    desks = {d["agent"]: d for room in result["rooms"] for d in room["desks"]}
    assert desks["researcher"]["state"] == "ready"
    assert desks["researcher"]["worker"] == "worker-research"
    # An agent nothing serves is idle, not ready.
    assert desks["planner"]["state"] == "idle"


def test_a_worker_is_matched_by_its_tools_as_well_as_by_serves() -> None:
    """One machine started for one agent can still run another whose tools it
    has — the website builders all need `website-generator`."""
    result = floor(_fleet({"name": "worker-delivery", "serves": "website-builder",
                           "capabilities": ["website-generator"],
                           "healthy": True, "available": True}))
    desks = {d["agent"]: d for room in result["rooms"] for d in room["desks"]}
    assert desks["website-builder"]["state"] == "ready"      # by serves
    assert desks["portfolio-builder"]["state"] == "ready"    # by tools
    assert desks["site-publisher"]["state"] == "idle"        # needs site-publish


def test_an_agent_with_no_tools_is_not_served_by_everything() -> None:
    """"needs nothing" is not "runs anywhere".

    The planner declares no tools. Matching it on an empty subset would draw it
    ready on a machine that can only publish sites.
    """
    result = floor(_fleet({"name": "publisher", "serves": "site-publisher",
                           "capabilities": ["site-publish"],
                           "healthy": True, "available": True}))
    desks = {d["agent"]: d for room in result["rooms"] for d in room["desks"]}
    assert desks["planner"]["state"] == "idle"
    assert desks["site-publisher"]["state"] == "ready"


def test_a_worker_speaking_the_agent_vocabulary_matches_nothing() -> None:
    """The bug this join replaced.

    Workers publish tools and a `serves` role; nothing anywhere publishes a
    `Capability`. Joining on one produced a floor where five ready workers drew
    twenty-one idle desks — which looked plausible, and was wrong.
    """
    result = floor(_fleet({"name": "wrong-vocabulary", "capabilities": ["research"],
                           "healthy": True, "available": True}))
    desks = {d["agent"]: d for room in result["rooms"] for d in room["desks"]}
    assert desks["researcher"]["state"] == "idle"


def test_a_busy_worker_makes_the_desk_working() -> None:
    result = floor(_fleet({"name": "worker-1", "serves": "self-check",
                           "capabilities": ["filesystem", "shell"],
                           "healthy": True, "available": False, "load": 1}))
    desks = {d["agent"]: d for room in result["rooms"] for d in room["desks"]}
    assert desks["self-check"]["state"] == "working"
    assert "worker-1" in desks["self-check"]["detail"]


def test_a_free_worker_wins_over_a_busy_one_serving_the_same_agent() -> None:
    """Two machines, one busy: the room reads ready, because work can start."""
    result = floor(_fleet(
        {"name": "busy", "serves": "researcher", "capabilities": ["dns", "http-fetch"],
         "healthy": True, "available": False},
        {"name": "free", "serves": "researcher", "capabilities": ["dns", "http-fetch"],
         "healthy": True, "available": True},
    ))
    desks = {d["agent"]: d for room in result["rooms"] for d in room["desks"]}
    assert desks["researcher"]["state"] == "ready"
    assert desks["researcher"]["worker"] == "free"


def test_a_stale_worker_serves_nothing() -> None:
    """Stale keeps the mission it holds and takes nothing new — so the desk it
    would have served is idle, not ready."""
    result = floor(_fleet({"name": "gone", "serves": "researcher",
                           "capabilities": ["dns", "http-fetch"],
                           "healthy": False, "available": True}))
    desks = {d["agent"]: d for room in result["rooms"] for d in room["desks"]}
    assert desks["researcher"]["state"] == "idle"
    assert desks["researcher"]["worker"] is None


def test_a_blocked_agent_stays_blocked_even_with_a_free_worker() -> None:
    """A machine cannot supply a credential.

    The correspondent has a worker that could run it and no key to send with;
    reporting that as `ready` is how an operator concludes outreach works.
    """
    result = floor(_fleet({"name": "any", "serves": "correspondent",
                           "capabilities": ["smtp"],
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
#
# Every path below is derived from the kernel's own `CONSOLE`, never written out
# again. These four tests spelled `apps/office/index.html` themselves and passed
# for as long as the floor sat in a directory `deploy_control.sh` — the script
# that actually runs — did not ship. A test that repeats a path cannot notice
# the path is wrong; it can only notice the file is missing from where the test
# thinks it lives, which was true and useless.


def _floor_path():
    from atlas_kernel.qevik.app import CONSOLE

    return CONSOLE / "office" / "index.html"


def _floor() -> str:
    return _floor_path().read_text(encoding="utf-8")


def test_the_floor_is_inside_the_bundle_every_deploy_copies() -> None:
    """Not "a deploy mentions it" — inside the directory both deploys carry.

    This replaces a test that checked `deploy_console.sh` copied the floor in a
    step of its own, between the console copy and the atomic swap. It did, and
    the floor still never reached the host, because there are two deploy scripts
    and the other one ships a fixed list of prefixes that did not include it.
    Checking one script's steps proved something about that script rather than
    about the host.
    """
    from pathlib import Path

    from atlas_kernel.qevik.app import CONSOLE

    root = Path(__file__).resolve().parents[3]
    relative = CONSOLE.resolve().relative_to(root).as_posix()

    assert _floor_path().is_file(), f"there is no floor at {_floor_path()}"
    assert _floor_path().resolve().is_relative_to(CONSOLE.resolve())

    control = (root / "infra" / "deploy_control.sh").read_text(encoding="utf-8")
    assert f"{relative}/" in control, "deploy_control.sh does not ship the console bundle"

    console = (root / "infra" / "deploy_console.sh").read_text(encoding="utf-8")
    copy = console.index('scp $SSH_ID -q -r "$LOCAL"/*')
    swap = console.index("mv $REMOTE.incoming $REMOTE")
    assert copy < swap, "the console is promoted before it is staged"
    assert "apps/office/index.html" not in console, (
        "a step of its own for the floor is what made two locations possible")


def test_the_floor_is_a_single_self_contained_file() -> None:
    """The production CSP allows 'self' and inline only.

    A stylesheet link, a CDN script or a font host would be silently blocked in
    production and only in production — the failure mode this whole
    no-build-step architecture exists to avoid.
    """
    page = _floor()
    assert "<script" in page and "<style" in page
    for forbidden in ('src="http', 'href="http', "cdn.", "fonts.googleapis", "unpkg"):
        assert forbidden not in page, f"the floor reaches outside its own origin: {forbidden}"


def test_the_floor_hardcodes_no_host() -> None:
    """It is served from the machine it reads, so a baked-in address is how a
    console ends up reporting another host's state as its own.

    The addresses come from the deployment registry rather than being written
    here. Spelling them out made this file the thing that put a production IP in
    the source tree, which is the rule the registry exists to keep.
    """
    from pathlib import Path

    registry = (Path(__file__).resolve().parents[3] / "infra" / "deploy_targets.conf"
                ).read_text(encoding="utf-8")
    hosts = [line.split("|")[1].split("@")[-1]
             for line in registry.splitlines()
             if line.strip() and not line.startswith("#") and "|" in line]
    assert hosts, "the target registry named no host, so this test checks nothing"

    page = _floor()
    for host in hosts:
        assert host not in page, f"the floor names a deployment host: {host}"


def test_the_floor_keeps_the_session_off_disk() -> None:
    """sessionStorage, never localStorage — the console's own rule, and the
    floor shares its origin, so a divergence here would leave a bearer token on
    disk for the same operator."""
    page = _floor()
    assert "sessionStorage" in page
    assert "localStorage" not in page


# --- every unit can find the kernel --------------------------------------------

def test_every_python_unit_says_where_the_kernel_is() -> None:
    """The payload ships the package, not the project.

    `deploy_control.sh` sends `packages/kernel/atlas_kernel` and deliberately not
    `pyproject.toml`, so nothing installs the kernel into the venv and every unit
    has to import it from PYTHONPATH. `qevik-api.service` was the one that did
    not say so, and it survived only because the old host had the project
    installed editable from a git clone — the provisioning route that
    `install_qevik_runtime.sh` replaces. On the first properly provisioned host
    it failed with `ModuleNotFoundError: No module named 'atlas_kernel'`.
    """
    from pathlib import Path

    infra = Path(__file__).resolve().parents[3] / "infra"
    for unit in sorted(infra.glob("qevik-*.service")):
        text = unit.read_text(encoding="utf-8")
        if ".venv/bin/python" not in text:
            continue  # not a Python service (the failure-marker template)
        assert "PYTHONPATH=" in text, (
            f"{unit.name} runs the kernel without saying where it is; it will "
            "start only on a host that happens to have the project installed")


@pytest.mark.real_auth
def test_the_floor_shell_is_reachable_but_its_data_is_not(client) -> None:
    """The shell is a console page like any other; the numbers on it are not.

    A signed-out visitor should get the page and then be told to sign in, rather
    than a 401 on an HTML file — while `/api/fabric/office` stays closed, because
    it reports which agents exist and what blocks them.
    """
    from atlas_kernel.auth.api import CONSOLE_PATHS

    # Every spelling a browser can produce. The trailing-slash form was missing
    # and returned 401 on an HTML page from a plain link.
    for spelling in ("/office", "/office/", "/office/index.html"):
        assert spelling in CONSOLE_PATHS, spelling
    assert client.get("/api/fabric/office").status_code == 401
