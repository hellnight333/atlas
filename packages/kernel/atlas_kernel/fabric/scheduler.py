"""When work runs, where, and in what order. Never *whether*.

The worker takes one queued mission per pass, oldest first. That is correct and
it is not an operations department: it cannot tell urgent from routine, cannot
defer expensive work to a cheaper hour, cannot notice that a mission needs a
credential nobody has entered, and cannot decline to start something whose budget
would run out halfway.

This decides **order and placement**. Policy already decided whether — `ALLOWED`
refuses illegal transitions, `EXECUTORS` refuses unbackable promises,
`REQUIRES_CUSTOMER_INPUT` refuses work waiting on the customer, the approval
boundaries refuse unapproved work. The scheduler never overrides any of them, and
a test asserts it does not import them to try.

## Five queues, and two of them must never merge

    NOW         dispatch immediately
    NEXT        ready, waiting only for capacity
    SCHEDULED   deliberately later — a window was chosen
    WAITING     a dependency, or a person who has been asked
    BLOCKED     cannot proceed; the reason is named

`WAITING` resolves by itself. `BLOCKED` never will. Merging them produces a queue
where half the entries are progressing and half are dead, and nobody can tell
which by looking — so the operator either chases things that were fine or ignores
things that were stuck.

One deliberate divergence from section L of the fabric architecture, which files
a missing credential under `WAITING`: it is `BLOCKED` here. Nothing resolves it
but a person typing a key, which is the definition of the other queue — and a
credential sitting in `WAITING` looks like it is on its way.

## Deferring is a decision, not a delay

Work moved to a night window is `SCHEDULED` **with the window recorded**, so
"why has this not run" has an answer that is not "the queue is long".
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ..mission.models import TERMINAL, MissionStatus
from ..opportunity.tenancy import TenantId, owns
from ..opportunity.tenancy import require as _require_tenant
from .agents import Agent, Placement, Registry, UnknownAgent


class Queue(StrEnum):
    NOW = "NOW"
    NEXT = "NEXT"
    SCHEDULED = "SCHEDULED"
    WAITING = "WAITING"
    BLOCKED = "BLOCKED"


class Priority(StrEnum):
    """Why this should go before that.

    Named rather than numeric. A number invites arithmetic — "priority 7 beats
    priority 5" — and nobody can say what 7 means six months later. A name has
    to be argued for.
    """

    #: A person is waiting for this answer right now.
    INTERACTIVE = "interactive"
    #: It unblocks something a person is waiting on.
    UNBLOCKING = "unblocking"
    #: Ordinary work with a deadline.
    NORMAL = "normal"
    #: Useful, no deadline. The natural candidate for a night window.
    BACKGROUND = "background"

ORDER: dict[Priority, int] = {
    Priority.INTERACTIVE: 0, Priority.UNBLOCKING: 1,
    Priority.NORMAL: 2, Priority.BACKGROUND: 3,
}

#: When deferred work runs. Local to the deployment's clock, and chosen because
#: providers are cheaper and quieter then — not because anything is hidden.
NIGHT_START, NIGHT_END = time(1, 0), time(6, 0)

#: Above this estimated cost, work with no deadline waits for the night window.
#: Named so it can be argued with rather than discovered.
EXPENSIVE_UNITS = 50.0

#: Headroom an *unpriced* mission needs before it may start.
#:
#: Deliberately not `EXPENSIVE_UNITS`. Those are two different questions —
#: "is this expensive enough to run at night" and "can we start something we
#: cannot price" — and answering the second with the first blocks every
#: unestimated mission on a small plan for ever, which is a wall rather than a
#: budget. This says: we will attempt work of unknown cost while there is real
#: headroom, and stop attempting it when there is not.
UNPRICED_NEEDS = 5.0


class Demand(BaseModel):
    """What one mission needs before it can run.

    Assembled by the caller from things that already exist — the mission, the
    agent record, the credential store, the roadmap — rather than gathered here.
    The scheduler is a decision procedure over stated facts; if it went looking
    for facts it would become a second place that decides what is true.
    """

    model_config = ConfigDict(frozen=True)

    mission_id: str
    tenant_id: str
    title: str = ""
    status: MissionStatus = MissionStatus.QUEUED
    priority: Priority = Priority.NORMAL
    #: Missions that must complete first. Named, so a cycle is detectable.
    depends_on: tuple[str, ...] = ()
    #: Units this is expected to consume. `None` is UNKNOWN, and is treated as
    #: expensive rather than free — an unmetered provider is not a cheap one.
    estimated_units: float | None = None
    #: Units left in the tenant's allowance.
    remaining_units: float | None = None
    #: Where this has to run.
    placement: Placement = Placement.EITHER
    #: Credentials the work needs and does not have. Named, not counted.
    missing_credentials: tuple[str, ...] = ()
    #: True when a person must act before this can proceed.
    needs_human: bool = False
    #: Set when policy has already refused it.
    blocked_because: str = ""
    deadline: datetime | None = None
    #: A window the operator chose. Overrides the scheduler's own judgement,
    #: because a person deciding "run this tonight" is a decision, not a hint.
    not_before: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Decision(BaseModel):
    """Which queue a demand lands in, and why."""

    model_config = ConfigDict(frozen=True)

    mission_id: str
    queue: Queue
    #: A sentence a person can act on. Never "queued" — that is the outcome, not
    #: the reason.
    why: str
    priority: Priority = Priority.NORMAL
    runs_after: datetime | None = None
    placement: Placement = Placement.EITHER

    def summary(self) -> dict:
        return {"mission_id": self.mission_id, "queue": self.queue.value,
                "why": self.why, "priority": self.priority.value,
                "runs_after": self.runs_after.isoformat() if self.runs_after else "",
                "placement": self.placement.value}


def _is_night(at: datetime) -> bool:
    return NIGHT_START <= at.timetz().replace(tzinfo=None) < NIGHT_END


def next_night(at: datetime) -> datetime:
    """The start of the next night window. Deterministic, never 'later'."""
    tonight = at.replace(hour=NIGHT_START.hour, minute=NIGHT_START.minute,
                         second=0, microsecond=0)
    return tonight if at < tonight else tonight + timedelta(days=1)


def decide(demand: Demand, *, done: frozenset[str] = frozenset(),
           local_worker: bool = False, now: datetime | None = None,
           capacity: bool = True) -> Decision:
    """Which queue this belongs in.

    The order of the checks is the policy. Blocked before waiting before
    scheduled before ready, because each earlier answer makes the later ones
    irrelevant — asking "is there capacity" about work that cannot run at all
    produces a queue full of things that look imminent.
    """
    at = now or datetime.now(UTC)

    # 1. Policy already refused it. Nothing here reconsiders that.
    if demand.blocked_because:
        return Decision(mission_id=demand.mission_id, queue=Queue.BLOCKED,
                        why=demand.blocked_because, priority=demand.priority)

    # 2. A credential nobody has entered. Blocked rather than waiting: it will
    #    not resolve on its own, and a person has to do something specific.
    if demand.missing_credentials:
        return Decision(
            mission_id=demand.mission_id, queue=Queue.BLOCKED,
            priority=demand.priority,
            why=("needs " + ", ".join(demand.missing_credentials)
                 + " in the Credential Centre"))

    # 3. Placement it cannot have. Also blocked — an operator must attach a
    #    worker, and silently queueing it forever is the failure this prevents.
    if demand.placement is Placement.LOCAL and not local_worker:
        return Decision(mission_id=demand.mission_id, queue=Queue.BLOCKED,
                        priority=demand.priority, placement=demand.placement,
                        why="needs a worker on your own machine, and none is "
                            "attached")

    # 4. Budget. Refused *before* dispatch rather than discovered halfway: a
    #    mission stopped mid-flight has spent the money and produced nothing.
    #
    #    Priced and unpriced work are judged separately — "can we afford the
    #    estimate" and "should we start something nobody priced" are different
    #    questions, and answering the second with the first walls off every
    #    unestimated mission on a small plan for ever.
    if demand.remaining_units is not None:
        if demand.estimated_units is None:
            if demand.remaining_units < UNPRICED_NEEDS:
                return Decision(
                    mission_id=demand.mission_id, queue=Queue.BLOCKED,
                    priority=demand.priority,
                    why=("nothing estimated what this costs and only "
                         f"{demand.remaining_units:g} units remain. Add an "
                         "estimate to the plan, or top up — starting work "
                         "nobody can price on the last of an allowance is how "
                         "it runs out mid-mission"))
        elif demand.estimated_units > demand.remaining_units:
            return Decision(
                mission_id=demand.mission_id, queue=Queue.BLOCKED,
                priority=demand.priority,
                why=(f"would need about {demand.estimated_units:g} units and "
                     f"{demand.remaining_units:g} remain; stopping halfway "
                     "spends the money and produces nothing"))

    # 5. Waiting on a person or on other work. These resolve by themselves,
    #    which is why they are not BLOCKED.
    if demand.needs_human:
        return Decision(mission_id=demand.mission_id, queue=Queue.WAITING,
                        priority=demand.priority,
                        why="waiting for a person to approve or supply something")
    outstanding = tuple(m for m in demand.depends_on if m not in done)
    if outstanding:
        return Decision(mission_id=demand.mission_id, queue=Queue.WAITING,
                        priority=demand.priority,
                        why=f"waiting on {', '.join(outstanding)}")

    # 6. A window somebody chose. A person's decision outranks the scheduler's.
    if demand.not_before and at < demand.not_before:
        return Decision(mission_id=demand.mission_id, queue=Queue.SCHEDULED,
                        priority=demand.priority, runs_after=demand.not_before,
                        placement=demand.placement,
                        why="held until the window you chose")

    # 7. Expensive and unhurried: move it to the night. Interactive work is
    #    never deferred — somebody is waiting, and cheapness is not the point.
    deferrable = (demand.priority is Priority.BACKGROUND
                  and demand.deadline is None
                  and (demand.estimated_units is None
                       or demand.estimated_units >= EXPENSIVE_UNITS))
    if deferrable and not _is_night(at):
        window = next_night(at)
        return Decision(mission_id=demand.mission_id, queue=Queue.SCHEDULED,
                        priority=demand.priority, runs_after=window,
                        placement=demand.placement,
                        why=("expensive and not urgent, so it runs in the night "
                             f"window from {window.isoformat(timespec='minutes')}"))

    # 8. Ready. NOW if there is room, NEXT if there is not — and NEXT is not a
    #    problem, so it says so.
    if capacity:
        return Decision(mission_id=demand.mission_id, queue=Queue.NOW,
                        priority=demand.priority, placement=demand.placement,
                        why="ready, and there is capacity")
    return Decision(mission_id=demand.mission_id, queue=Queue.NEXT,
                    priority=demand.priority, placement=demand.placement,
                    why="ready, waiting only for a free worker")


def plan(demands: tuple[Demand, ...], *, tenant: TenantId | None,
         done: frozenset[str] = frozenset(), local_worker: bool = False,
         now: datetime | None = None, concurrency: int = 1) -> dict:
    """Sort a tenant's work into the five queues, in order.

    `concurrency` is how many missions may be dispatched at once. Work beyond it
    lands in NEXT rather than NOW, so the answer to "why is this not running" is
    "there is no free worker" rather than silence.
    """
    tenant = _require_tenant(tenant, method="scheduler.plan")
    mine = [d for d in demands if owns(d.tenant_id, tenant)]

    decisions: list[Decision] = []
    dispatched = 0
    # Highest priority first, then oldest — so a long-waiting mission is not
    # starved every time a newer one of equal priority arrives.
    for demand in sorted(mine, key=lambda d: (ORDER[d.priority], d.created_at)):
        decision = decide(demand, done=done, local_worker=local_worker, now=now,
                          capacity=dispatched < concurrency)
        if decision.queue is Queue.NOW:
            dispatched += 1
        decisions.append(decision)

    by_queue: dict[str, list[dict]] = {q.value: [] for q in Queue}
    for decision in decisions:
        by_queue[decision.queue.value].append(decision.summary())

    return {
        "queues": by_queue,
        "counts": {q.value: len(by_queue[q.value]) for q in Queue},
        "dispatchable": [d.mission_id for d in decisions if d.queue is Queue.NOW],
        "note": ("WAITING resolves on its own; BLOCKED never will. They are "
                 "separate queues because an operator who cannot tell them "
                 "apart chases the wrong half."),
    }


def demands_from(folded: list[dict], *, agents: Registry | None = None,
                 connected: frozenset[str] = frozenset(),
                 remaining_units: float | None = None,
                 agent_for: dict[str, str] | None = None) -> tuple[Demand, ...]:
    """Turn folded missions into demands, using what the caller already knows.

    A bridge, not a discovery step. Everything it consults — the fold, the
    connected credentials, the allowance — was determined somewhere that owns
    that question. If the scheduler went looking for these itself it would
    become a second place that decides what is true, and the two would disagree
    on the day it mattered.
    """
    registry = agents or Registry()
    routes = agent_for or {}
    out: list[Demand] = []
    for row in folded:
        status = MissionStatus(row.get("status", "queued"))
        if status in TERMINAL:
            continue
        agent = None
        route = routes.get(str(row.get("mission_id", "")))
        if route:
            try:
                agent = registry.get(route)
            except UnknownAgent:
                agent = None
        blockers = row.get("blockers") or []
        out.append(Demand(
            mission_id=str(row.get("mission_id", "")),
            tenant_id=str(row.get("tenant_id", "")),
            title=str(row.get("title", "")),
            status=status,
            priority=_priority_of(row),
            estimated_units=_estimate(row),
            remaining_units=remaining_units,
            placement=agent.placement if agent else Placement.EITHER,
            missing_credentials=(unmet_credentials(agent, connected=connected)
                                 if agent else ()),
            needs_human=status is MissionStatus.AWAITING_APPROVAL,
            blocked_because=(_first_blocker(blockers)
                             if status is MissionStatus.BLOCKED else ""),
            not_before=_moment(row.get("not_before")),
            created_at=_moment(row.get("created_at")) or datetime.now(UTC),
        ))
    return tuple(out)


def _priority_of(row: dict) -> Priority:
    """A mission's integer priority, read as a name.

    `Mission.priority` is an int that predates this module and is still the
    field operators set. Rather than add a second field that would drift from
    it, the int is interpreted here — in one place, stated rather than scattered
    through comparisons.
    """
    raw = row.get("priority")
    value = raw if isinstance(raw, int) else 0
    if value >= 2:
        return Priority.INTERACTIVE
    if value == 1:
        return Priority.UNBLOCKING
    if value < 0:
        return Priority.BACKGROUND
    return Priority.NORMAL


def _estimate(row: dict) -> float | None:
    """What the plan expects this to cost, or UNKNOWN.

    `None` when no plan estimated it — and `decide()` treats UNKNOWN as
    expensive, never as free.
    """
    plan = row.get("plan")
    if not isinstance(plan, dict):
        return None
    cost = plan.get("estimated_cost")
    return float(cost) if isinstance(cost, int | float) else None


def _first_blocker(blockers: list) -> str:
    for blocker in blockers:
        if isinstance(blocker, dict):
            kind, detail = blocker.get("kind", ""), blocker.get("detail", "")
            if kind or detail:
                return f"{kind}: {detail}".strip(": ")
    return "blocked, and the reason was not recorded"


def _moment(value: object) -> datetime | None:
    """An ISO string from a folded event back into a moment.

    The fold returns JSON, so every datetime arrives as text. Parsing it in one
    place is what stops a naive datetime reaching a comparison against an
    aware one, which raises rather than misbehaving — but only at the moment a
    deferral is checked, which is the worst time to find out.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def unmet_credentials(agent: Agent, *, connected: frozenset[str]) -> tuple[str, ...]:
    """Which of an agent's credentials are missing.

    An agent listing three interchangeable providers needs *one* of them, so any
    connected provider satisfies it. Requiring all three would block work that
    could run perfectly well.
    """
    if not agent.credentials:
        return ()
    if any(c in connected for c in agent.credentials):
        return ()
    return agent.credentials
