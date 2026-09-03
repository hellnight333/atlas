"""The floor plan: every agent as a desk, in a room, in a state you can see.

An operator asking "what is my company doing right now" gets, today, four
different answers from four pages: a worker fleet, a mission list, an agent
registry and a health endpoint. None of them says *who is working on what*, and
none of them shows the thing that actually blocks this business — that six of
the twenty-one agents cannot run at all because a credential was never issued.

This module answers that question once, as a floor: rooms, desks, and a state
per desk that an operator can act on. It is deliberately a **view**, not a
second registry:

* the desks are `AGENTS`, the same records the dispatcher routes through;
* the fleet is the scheduler's own snapshot, passed in;
* nothing here executes, claims, or decides.

## Why the empty desks matter most

The temptation with a picture of an office is to draw the agents that work and
quietly leave out the ones that do not. That inverts the value: an agent with
`blocked_by` is not a gap in the drawing, it is the most useful thing on the
screen — a named seat with a named reason, `PENDING_CREDENTIAL` at eye level
instead of buried in a registry nobody opens.

So a blocked agent gets a desk, in its room, with its reason attached. The floor
shows what the company *would* be doing if the blockers were cleared, which is
exactly the argument for clearing them.

## The state a desk is in

Five, and the distinction between the last two is the one that gets lost:

    working    a healthy worker serves this capability and is busy
    ready      no blocker, and a healthy worker could take the work
    idle       no blocker, but nothing on the fleet serves this capability
    blocked    the agent itself cannot run — credential, infrastructure, policy
    unknown    the fleet could not be read

`unknown` is not `idle`. A database that cannot be reached is not an empty
company, and a floor that draws it as one tells an operator their cluster died.
`mission.api.worker_fleet` already refuses that conflation; this preserves it.
"""

from __future__ import annotations

from typing import Any

from .agents import AGENTS, Agent, Capability

#: Rooms, in the order a floor plan reads them. Each names the work it is for,
#: not the technology behind it: an operator looks for "who writes things", not
#: for "which agents hold Capability.WRITE".
#:
#: Every capability appears in exactly one room, and a test asserts it — a
#: capability in two rooms draws one agent twice, and a capability in none makes
#: an agent vanish from its own company.
ROOMS: tuple[dict[str, Any], ...] = (
    {"id": "strategy", "name": "Strategy", "purpose": "Decide what to do, and whether it was any good",
     "capabilities": (Capability.PLAN, Capability.REVIEW, Capability.SUMMARISE, Capability.ANALYSE)},
    {"id": "engineering", "name": "Engineering", "purpose": "Build it, and check that it works",
     "capabilities": (Capability.IMPLEMENT, Capability.VERIFY)},
    {"id": "studio", "name": "Studio", "purpose": "Words, languages and pictures",
     "capabilities": (Capability.WRITE, Capability.TRANSLATE_CHECK,
                      Capability.GENERATE_IMAGE, Capability.GENERATE_VIDEO)},
    {"id": "field", "name": "Field research", "purpose": "Go and find out what is true",
     "capabilities": (Capability.RESEARCH, Capability.BROWSE)},
    {"id": "growth", "name": "Growth", "purpose": "Reach people and marketplaces — every desk here is irreversible",
     "capabilities": (Capability.CORRESPOND, Capability.PUBLISH_SOCIAL, Capability.MERCHANDISE)},
    {"id": "operations", "name": "Operations", "purpose": "Put it live and keep the lights on",
     "capabilities": (Capability.PUBLISH, Capability.ADMINISTER)},
)

#: What a desk's state means to a person, in the words they would use about it.
STATE_MEANING: dict[str, str] = {
    "working": "a worker is running this now",
    "ready": "a worker could take this now",
    "idle": "nothing on the fleet serves this capability",
    "blocked": "this agent cannot run at all until its blocker is cleared",
    "unknown": "the fleet could not be read, which is not the same as no workers",
}


def _room_of(capability: Capability) -> str:
    for room in ROOMS:
        if capability in room["capabilities"]:
            return str(room["id"])
    # Unreachable while the test below holds; a new capability with no room is a
    # missing decision, not a reason to hide an agent.
    return "unassigned"


def _desk(agent: Agent, *, fleet_known: bool, serving: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """One agent, as a seat on the floor."""
    blockers = [need.value for need in agent.blocked_by]
    node = serving.get(agent.capability.value)

    if blockers:
        state = "blocked"
        detail = agent.why_not_ready or "; ".join(blockers)
    elif not fleet_known:
        state = "unknown"
        detail = STATE_MEANING["unknown"]
    elif node is None:
        state = "idle"
        detail = STATE_MEANING["idle"]
    elif not node.get("available", False):
        state = "working"
        detail = f"{node.get('name', 'a worker')} is busy"
    else:
        state = "ready"
        detail = f"{node.get('name', 'a worker')} is free"

    return {
        "agent": agent.id,
        "name": agent.name,
        "capability": agent.capability.value,
        "room": _room_of(agent.capability),
        "blast": agent.blast.value,
        "placement": agent.placement.value,
        "tools": list(agent.tools),
        "credentials": list(agent.credentials),
        "state": state,
        "detail": detail,
        "blockers": blockers,
        # The seat is drawn whether or not a machine is behind it; this names
        # the machine when there is one.
        "worker": (node or {}).get("name"),
        "irreversible": agent.blast.value == "irreversible",
    }


def floor(fleet: dict[str, Any] | None = None,
          missions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The whole floor: rooms, desks, and what the company is short of.

    `fleet` is `mission.api.worker_fleet`'s payload — passed in rather than read
    here, so this module has no database and the office cannot disagree with the
    page the dispatcher uses. `None` means nobody asked the fleet, which is
    reported as `unknown` rather than as an empty one.
    """
    fleet = fleet or {"known": False, "workers": []}
    fleet_known = bool(fleet.get("known"))

    # Capability → the best node serving it. Prefer a free one, so a room with
    # one busy and one free worker reads "ready", not "working".
    serving: dict[str, dict[str, Any]] = {}
    for node in fleet.get("workers", []) if fleet_known else []:
        if not node.get("healthy"):
            continue  # stale: keeps its mission, takes nothing new
        for capability in node.get("capabilities", []):
            best = serving.get(capability)
            if best is None or (node.get("available") and not best.get("available")):
                serving[capability] = node

    desks = [_desk(agent, fleet_known=fleet_known, serving=serving) for agent in AGENTS]
    by_room: dict[str, list[dict[str, Any]]] = {}
    for desk in desks:
        by_room.setdefault(desk["room"], []).append(desk)

    rooms = [{
        "id": room["id"],
        "name": room["name"],
        "purpose": room["purpose"],
        "capabilities": [c.value for c in room["capabilities"]],
        "desks": by_room.get(str(room["id"]), []),
    } for room in ROOMS]

    counts: dict[str, int] = {state: 0 for state in STATE_MEANING}
    for desk in desks:
        counts[desk["state"]] += 1

    # What an operator would actually do next: the distinct blockers, each with
    # the seats waiting on it. One line per unlock, not one per agent.
    waiting: dict[str, list[str]] = {}
    for desk in desks:
        for blocker in desk["blockers"]:
            waiting.setdefault(blocker, []).append(desk["agent"])

    return {
        "rooms": rooms,
        "counts": counts,
        "state_meaning": STATE_MEANING,
        "fleet": {
            "known": fleet_known,
            "counts": fleet.get("counts", {}),
            "detail": fleet.get("detail", ""),
        },
        "waiting_on": [
            {"blocker": blocker, "agents": sorted(agents), "seats": len(agents)}
            for blocker, agents in sorted(waiting.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        ],
        "headcount": len(desks),
    }
