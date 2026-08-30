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
from . import recipes
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


class NodeSnapshot(BaseModel):
    """One worker, as the scheduler is told about it.

    A value object, not a registry. Assembled by the caller from the cluster
    rows it already reads, exactly as `connected` credentials and
    `remaining_units` are -- the scheduler decides over stated facts, and going
    to look for them itself would make it a second place that decides what is
    true.

    `fabric` therefore gains no import from `cluster`, and no second store of
    node state exists.
    """

    model_config = ConfigDict(frozen=True)

    #: The name a claim is taken under (`worker-research`), not the node
    #: identity (`qevik-core-01:worker-research`). Selection has to name the
    #: thing that claims, or the two could never be compared.
    worker_name: str
    #: The registered agent this worker runs as.
    serves: str = ""
    #: Tool ids it advertises, derived at registration from the agent's declared
    #: tools. The same vocabulary a recipe's steps use.
    capabilities: frozenset[str] = frozenset()
    #: Placements this machine can satisfy.
    placements: frozenset[str] = frozenset()
    #: Heartbeat within the cluster timeout. Liveness, never ownership: a stale
    #: node keeps any claim it holds and is simply not given new work.
    fresh: bool = True
    #: `current_load < max_concurrency`.
    free: bool = True
    #: For the load tie-break, and only that.
    load: int = 0
    #: Stable identity, for a deterministic last resort.
    node_id: str = ""


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
    #: The agent that would carry this out, resolved against the registry by
    #: the caller. Empty means **no agent could be resolved** -- either the
    #: mission records none, or it names one the registry does not have.
    #:
    #: Empty is not "any agent will do". A mission nobody routed used to be
    #: offered to every worker, and the worker that asked first carried out work
    #: whose blast radius nobody had recorded. The absence of a requirement is
    #: not permission to run anywhere.
    agent_id: str = ""
    #: The tools this mission's recipe uses, derived from its steps. Empty when
    #: it names no recipe -- a plan-based mission is real work that declares no
    #: tools, and empty here is **not** a wildcard: `agent_id` still binds it to
    #: one agent, so eligibility narrows rather than opening up.
    required_tools: tuple[str, ...] = ()
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
    #: Which worker may run it, when the caller supplied nodes and one was
    #: chosen. Empty when nothing was selected -- either no node information was
    #: given, or the mission is not going anywhere. This is the "to whom" half
    #: of the question, and it is answered here so that nothing downstream has
    #: to guess it.
    worker: str = ""

    def summary(self) -> dict:
        return {"mission_id": self.mission_id, "queue": self.queue.value,
                "why": self.why, "priority": self.priority.value,
                "runs_after": self.runs_after.isoformat() if self.runs_after else "",
                "placement": self.placement.value, "worker": self.worker}


def _is_night(at: datetime) -> bool:
    return NIGHT_START <= at.timetz().replace(tzinfo=None) < NIGHT_END


def next_night(at: datetime) -> datetime:
    """The start of the next night window. Deterministic, never 'later'."""
    tonight = at.replace(hour=NIGHT_START.hour, minute=NIGHT_START.minute,
                         second=0, microsecond=0)
    return tonight if at < tonight else tonight + timedelta(days=1)


#: The tag a node must carry to be offered Qevik mission work.
#:
#: An allow-list, not a filter. The cluster registry holds Atlas workers and
#: test fixtures too -- five of them online in production -- and excluding by
#: recognising what is bad would have to anticipate every kind of node that
#: might ever appear. Admitting only what declares itself excludes the rest by
#: default, including kinds nobody has invented yet.
MISSION_WORKER_TAG = "qevik-mission-worker"


def eligible(demand: Demand,
             nodes: tuple[NodeSnapshot, ...]) -> tuple[NodeSnapshot, ...]:
    """The workers that may run this mission, best first.

    Every clause narrows; none widens. A node earns work by declaring what it
    is and what it holds, never by an absence of information about it.
    """
    fit = [n for n in nodes
           if n.serves == demand.agent_id
           and set(demand.required_tools) <= n.capabilities
           and _placed(demand.placement, n)
           and n.fresh
           and n.free]

    # Most specific first: a node advertising exactly what is needed is
    # preferred over one that also does other things, so a generalist is left
    # free for work only it can take. Then least loaded. Then node id, which is
    # a tie-break for determinism and never a reason on its own -- sorting by id
    # alone is what put a Qevik worker ahead of `worker-local` for `filesystem`.
    return tuple(sorted(fit, key=lambda n: (len(n.capabilities), n.load, n.node_id)))


def _placed(placement: Placement, node: NodeSnapshot) -> bool:
    """Whether this machine can satisfy where the work has to happen."""
    if placement is Placement.EITHER:
        return True
    return placement.value in node.placements


def _no_node_reason(demand: Demand, nodes: tuple[NodeSnapshot, ...]) -> str:
    """Which clause emptied the list. The first one that did, so the operator is
    told what to fix rather than that something, somewhere, did not match."""
    mine = [n for n in nodes if n.serves == demand.agent_id]
    if not mine:
        return (f"no worker runs {demand.agent_id!r}; "
                f"registered: {', '.join(sorted({n.serves for n in nodes})) or 'none'}")
    capable = [n for n in mine if set(demand.required_tools) <= n.capabilities]
    if not capable:
        missing = sorted(set(demand.required_tools)
                         - set.union(*[set(n.capabilities) for n in mine]))
        return (f"no worker running {demand.agent_id!r} advertises "
                f"{', '.join(missing)}")
    placed = [n for n in capable if _placed(demand.placement, n)]
    if not placed:
        return (f"no worker running {demand.agent_id!r} can run "
                f"{demand.placement.value} work")
    fresh = [n for n in placed if n.fresh]
    if not fresh:
        return (f"every worker running {demand.agent_id!r} has stopped "
                "reporting; it keeps any claim it holds and takes nothing new")
    return f"every worker running {demand.agent_id!r} is busy"


def decide(demand: Demand, *, done: frozenset[str] = frozenset(),
           local_worker: bool = False, now: datetime | None = None,
           capacity: bool = True,
           nodes: tuple[NodeSnapshot, ...] | None = None) -> Decision:
    """Which queue this belongs in.

    The order of the checks is the policy. Blocked before waiting before
    scheduled before ready, because each earlier answer makes the later ones
    irrelevant — asking "is there capacity" about work that cannot run at all
    produces a queue full of things that look imminent.
    """
    at = now or datetime.now(UTC)
    #: `None` means the caller told us nothing about workers, so no worker is
    #: chosen and the decision is about the queue alone -- what every caller got
    #: before this existed. An **empty tuple** is different and means the caller
    #: looked and there are none, which is a reason to block rather than an
    #: absence of information. Collapsing the two would have a caller that
    #: forgot to pass nodes silently dispatching to nobody.
    chosen = ""

    # 1. Policy already refused it. Nothing here reconsiders that.
    if demand.blocked_because:
        return Decision(mission_id=demand.mission_id, queue=Queue.BLOCKED,
                        why=demand.blocked_because, priority=demand.priority)

    # 2. Nobody to run it. Blocked, and *before* the credential check, because
    #    every fact below this line is derived from the agent: with none
    #    resolved, `missing_credentials` is empty and `placement` is EITHER, so
    #    an unrouted mission would sail past both and be reported ready.
    #
    #    This is what made the contract untruthful. The scheduler called such a
    #    mission dispatchable while the worker declined it, so the only thing
    #    keeping unrouted work from running anywhere was a filter in the worker
    #    -- and a view that reads `dispatchable` showed work that would never
    #    start. Eligibility belongs here; the worker's check stays as a
    #    defensive narrowing, not as the authority.
    if not demand.agent_id:
        return Decision(mission_id=demand.mission_id, queue=Queue.BLOCKED,
                        priority=demand.priority, placement=demand.placement,
                        why=("no agent is recorded for this mission, so no "
                             "worker may run it"))

    # 3. A credential nobody has entered. Blocked rather than waiting: it will
    #    not resolve on its own, and a person has to do something specific.
    if demand.missing_credentials:
        return Decision(
            mission_id=demand.mission_id, queue=Queue.BLOCKED,
            priority=demand.priority,
            why=("needs " + ", ".join(demand.missing_credentials)
                 + " in the Credential Centre"))

    # 4. Placement it cannot have. Also blocked — an operator must attach a
    #    worker, and silently queueing it forever is the failure this prevents.
    if demand.placement is Placement.LOCAL and not local_worker:
        return Decision(mission_id=demand.mission_id, queue=Queue.BLOCKED,
                        priority=demand.priority, placement=demand.placement,
                        why="needs a worker on your own machine, and none is "
                            "attached")

    # 5. Somewhere to run it. Selection, not merely feasibility -- this is the
    #    "to whom" half, and answering it here is what stops the worker from
    #    being a second authority on eligibility.
    if nodes is not None:
        fit = eligible(demand, nodes)
        if not fit:
            return Decision(mission_id=demand.mission_id, queue=Queue.BLOCKED,
                            priority=demand.priority, placement=demand.placement,
                            why=_no_node_reason(demand, nodes))
        chosen = fit[0].worker_name

    # 6. Budget. Refused *before* dispatch rather than discovered halfway: a
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

    # 7. Waiting on a person or on other work. These resolve by themselves,
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

    # 8. A window somebody chose. A person's decision outranks the scheduler's.
    if demand.not_before and at < demand.not_before:
        return Decision(mission_id=demand.mission_id, queue=Queue.SCHEDULED,
                        priority=demand.priority, runs_after=demand.not_before,
                        placement=demand.placement,
                        why="held until the window you chose")

    # 9. Expensive and unhurried: move it to the night. Interactive work is
    #    never deferred — somebody is waiting, and cheapness is not the point.
    deferrable = (demand.priority is Priority.BACKGROUND
                  and demand.deadline is None
                  and (demand.estimated_units is None
                       or demand.estimated_units >= EXPENSIVE_UNITS))
    if deferrable and not _is_night(at):
        window = next_night(at)
        return Decision(mission_id=demand.mission_id, queue=Queue.SCHEDULED,
                        priority=demand.priority, runs_after=window,
                        placement=demand.placement, worker=chosen,
                        why=("expensive and not urgent, so it runs in the night "
                             f"window from {window.isoformat(timespec='minutes')}"))

    # 10. Ready. NOW if there is room, NEXT if there is not — and NEXT is not a
    #    problem, so it says so.
    if capacity:
        return Decision(mission_id=demand.mission_id, queue=Queue.NOW,
                        priority=demand.priority, placement=demand.placement,
                        worker=chosen,
                        why=("ready, and there is capacity"
                             + (f"; {chosen} may run it" if chosen else "")))
    return Decision(mission_id=demand.mission_id, queue=Queue.NEXT,
                    priority=demand.priority, placement=demand.placement,
                    worker=chosen,
                    why="ready, waiting only for a free worker")


def plan(demands: tuple[Demand, ...], *, tenant: TenantId | None,
         done: frozenset[str] = frozenset(), local_worker: bool = False,
         now: datetime | None = None, concurrency: int = 1,
         nodes: tuple[NodeSnapshot, ...] | None = None) -> dict:
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
                          capacity=dispatched < concurrency, nodes=nodes)
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
        # Who may run each dispatchable mission. Empty when the caller supplied
        # no nodes. A worker reads its own name here rather than deciding for
        # itself, which is what keeps eligibility in one place.
        "assigned": {d.mission_id: d.worker for d in decisions
                     if d.queue is Queue.NOW and d.worker},
        "note": ("WAITING resolves on its own; BLOCKED never will. They are "
                 "separate queues because an operator who cannot tell them "
                 "apart chases the wrong half."),
    }


def _tools_for(recipe_id: str) -> tuple[str, ...]:
    """The tools a recipe's steps use, or none when it names no recipe.

    One derivation over one registry: `Recipe.tools` is itself computed from the
    steps, so a recipe cannot need a tool it does not use nor hide one it does.
    Nothing here is hand-maintained, and an unknown recipe requires nothing
    rather than guessing -- the worker refuses it by name when it tries to run.
    """
    if not recipe_id:
        return ()
    try:
        return recipes.get(recipe_id).tools
    except recipes.UnknownRecipe:
        return ()


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
        # The caller's route map first, then the mission's own recorded agent.
        #
        # The fallback matters now that an unresolved agent blocks: a mission
        # that records `researcher` is routed, and a caller that passed no map
        # would otherwise have it reported as having nobody to run it -- false,
        # and blocking. Both production callers build their map from this very
        # field, so for them nothing changes; this only stops the fact being
        # lost when it was never overridden.
        route = (routes.get(str(row.get("mission_id", "")))
                 or str(row.get("agent_id", "")))
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
            required_tools=_tools_for(str(row.get("recipe", ""))),
            # The route as recorded, not the registry's opinion of it.
            #
            # "Unrouted" means nobody was named. It does not mean "named
            # somebody `fabric.agents` has not heard of": `fake` is deliberately
            # not a registered agent and is still a real thing a worker runs, and
            # a mission naming an agent that no longer exists is a mismatch for
            # the worker to refuse after claiming -- which it already does --
            # rather than work the scheduler pretends was never routed.
            agent_id=route,
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
