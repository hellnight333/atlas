"""Missions on the event timeline, so a restart loses nothing.

Every transition is an append-only `BusinessEvent` and the mission is folded
from them. That is the whole persistence story: no table, no migration, and no
way to quietly rewrite what happened — which matters more here than elsewhere,
because a mission is the record of what an autonomous agent did on somebody's
repository.

**Resume is the point.** A worker that dies mid-mission leaves the mission in a
non-terminal state with `claimed_by` still set. `stale()` finds exactly those,
and `release()` returns them to the queue with the reason recorded. Nothing is
lost and nothing is silently retried.

**One honest limitation, stated rather than papered over.** `claim()` is atomic
only against a single writer, because folding events cannot compare-and-set. A
second worker on another process could claim the same mission. Making that safe
needs a database row with `SELECT … FOR UPDATE SKIP LOCKED`, which is a genuine
schema addition, and it is recorded as PENDING_INFRASTRUCTURE rather than
pretended away. Single-worker operation is safe today; multi-worker is not.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta, timedelta
from uuid import uuid4

from ..opportunity.models import BusinessEvent
from ..opportunity.tenancy import TenantId, owns
from ..opportunity.tenancy import require as _require_tenant
from . import policy
from .models import (
    CLAIMABLE,
    AgentInvocation,
    Mission,
    MissionStatus,
    Plan,
)

log = logging.getLogger(__name__)

FACTORY = "mission"
KIND = "mission_transition"

#: How long a claim may be held before a worker is presumed dead. Long enough
#: that a slow implementation is not stolen mid-write.
CLAIM_TIMEOUT = timedelta(hours=2)


class NotPermitted(Exception):
    """The transition asked for is not one this mission may make."""


#: Which transitions are legitimate. Written out rather than left implicit,
#: because "queued straight to complete" is exactly the shortcut an agent under
#: pressure would take, and it would skip the tests and the review.
ALLOWED: dict[MissionStatus, frozenset[MissionStatus]] = {
    MissionStatus.DRAFT: frozenset({MissionStatus.PLANNING, MissionStatus.CANCELLED}),
    MissionStatus.PLANNING: frozenset({MissionStatus.AWAITING_APPROVAL,
                                       MissionStatus.QUEUED, MissionStatus.BLOCKED,
                                       MissionStatus.FAILED, MissionStatus.CANCELLED}),
    MissionStatus.AWAITING_APPROVAL: frozenset({MissionStatus.QUEUED,
                                                MissionStatus.CANCELLED,
                                                MissionStatus.BLOCKED}),
    MissionStatus.QUEUED: frozenset({MissionStatus.PROCESSING, MissionStatus.BLOCKED,
                                     MissionStatus.CANCELLED}),
    MissionStatus.PROCESSING: frozenset({MissionStatus.TESTING, MissionStatus.FAILED,
                                         MissionStatus.BLOCKED,
                                         MissionStatus.QUEUED}),
    MissionStatus.TESTING: frozenset({MissionStatus.REVIEWING, MissionStatus.FAILED,
                                      MissionStatus.PROCESSING}),
    MissionStatus.REVIEWING: frozenset({MissionStatus.COMMITTING,
                                        MissionStatus.PROCESSING,
                                        MissionStatus.FAILED}),
    MissionStatus.COMMITTING: frozenset({MissionStatus.COMPLETE, MissionStatus.FAILED}),
    MissionStatus.BLOCKED: frozenset({MissionStatus.QUEUED, MissionStatus.PLANNING,
                                      MissionStatus.CANCELLED}),
    MissionStatus.COMPLETE: frozenset(),
    MissionStatus.FAILED: frozenset({MissionStatus.QUEUED}),
    MissionStatus.CANCELLED: frozenset(),
}


#: The last ordering stamp this process issued. See `_stamp`.
_last_stamp = datetime.min.replace(tzinfo=UTC)


def _stamp() -> datetime:
    """A moment strictly later than the last one this process issued.

    `datetime.now` alone is not enough. Two calls can land in the same
    microsecond, and a tie in this field is not cosmetic: `fold` resolves ties
    by iteration order, so two events claiming the same moment make the folded
    mission depend on the order a store happens to return rows in.

    Per-process, and honestly so. Events for one mission come from one process
    at a time — a mission is claimed by a single worker — so a cross-process
    collision would need two processes writing about the same mission in the
    same microsecond, which the claim already prevents.
    """
    global _last_stamp
    now = datetime.now(UTC)
    if now <= _last_stamp:
        now = _last_stamp + timedelta(microseconds=1)
    _last_stamp = now
    return now


def _event(mission: Mission, *, actor: str, note: str = "",
           extra: dict | None = None,
           at: datetime | None = None) -> BusinessEvent:
    """One event about a mission, stamped with when **the event** happened.

    It used to inherit `mission.updated_at`, which only `transition` maintains.
    Anything that recorded an event without transitioning — the worker's cost,
    scratch and report notes, six call sites — therefore reused the previous
    transition's timestamp, and four events could claim one moment.

    That was invisible while the ledger was a file, because a file has an
    implicit total order and the last line won. Moving the ledger to a database
    removed that accident and the missing `report_path` appeared.

    So an event records its own moment. `mission.updated_at` still means what it
    meant; this is the *event's* time, which is what an append-only log orders
    by, and it makes a tie impossible rather than unlikely.

    `at` overrides the stamp for a caller that genuinely knows when the event
    happened — replaying, or reconstructing an abandoned mission whose last
    event really is six hours old. It cannot be used to win a fold: an older
    stamp loses, so backdating an event only makes it count for less.
    """
    detail = {**mission.summary(), "note": note, **(extra or {})}
    detail["updated_at"] = (at or _stamp()).isoformat()
    return BusinessEvent(business_id=mission.tenant_id, factory=FACTORY,
                         kind=KIND, actor=actor, detail=detail)


def create(*, tenant: TenantId | None, title: str, description: str = "",
           requested_by: str = "", priority: int = 0, occurrence: str = "",
           origin_name: str = "", recipe: str = "", signal_id: str = "",
           approved_scope: str = "",
           evidence_fingerprints: tuple[str, ...] = (),
           publishes: str = ""
           ) -> tuple[Mission, BusinessEvent]:
    """A new request, in DRAFT. Nothing runs from this."""
    tenant = _require_tenant(tenant, method="mission.create")
    if not title.strip():
        raise NotPermitted("a mission needs a title; a request nobody can read "
                           "is one nobody can approve")
    mission = Mission(id=f"mission-{uuid4().hex[:12]}", tenant_id=str(tenant),
                      title=title.strip(), description=description,
                      requested_by=requested_by, priority=priority,
                      occurrence=occurrence, origin_name=origin_name,
                      recipe=recipe, signal_id=signal_id,
                      approved_scope=approved_scope,
                      evidence_fingerprints=tuple(evidence_fingerprints),
                      publishes=publishes)
    return mission, _event(mission, actor=requested_by or "operator",
                           note="created")


def transition(mission: Mission, to: MissionStatus, *, tenant: TenantId | None,
               actor: str = "system", note: str = "",
               **changes: object) -> tuple[Mission, BusinessEvent]:
    """Move a mission, or refuse.

    Refuses a transition that is not in `ALLOWED`, which is what stops a mission
    going from queued straight to complete and skipping its tests.
    """
    tenant = _require_tenant(tenant, method="mission.transition")
    if not owns(mission.tenant_id, tenant):
        raise NotPermitted("this mission belongs to a different tenant")
    if to not in ALLOWED[mission.status]:
        raise NotPermitted(
            f"{mission.id}: {mission.status.value} cannot become {to.value}. "
            f"Allowed: {', '.join(sorted(s.value for s in ALLOWED[mission.status])) or 'nothing'}")
    moved = mission.model_copy(update={"status": to,
                                       "updated_at": datetime.now(UTC), **changes})
    return moved, _event(moved, actor=actor, note=note or to.value)


def attach_plan(mission: Mission, plan: Plan, *, tenant: TenantId | None,
                actor: str = "agent", agent_id: str = "",
                modifies_qevik_itself: bool = True
                ) -> tuple[Mission, BusinessEvent]:
    """Record a proposed plan and route it by what **policy** decides.

    The plan is the safety boundary: arbitrary text never becomes execution, it
    becomes something a person can read first. A plan whose own analysis found
    blockers goes to BLOCKED rather than to a queue.

    This routed on `plan.approval_required` — a field set by whatever produced
    the plan. `FakeCodingAgent` sets it to `False`, so its plans went straight to
    QUEUED with no approval at all, and an LLM emitting the same value would
    have been obeyed identically. That is the model authorising its own work.

    `mission.policy.decide()` now answers instead: deterministic, deny by
    default, and able only to be *raised* by the planner's request. The verdict
    is recorded on the transition so "why did this need a person" has an answer
    somebody can check.
    """
    if plan.blockers:
        return transition(mission, MissionStatus.BLOCKED, tenant=tenant,
                          actor=actor, plan=plan, blockers=plan.blockers,
                          note="planning found blockers")

    # `modifies_qevik_itself` defaults to True and is passed through unchanged,
    # so every existing caller keeps the behaviour it had. Only a caller that
    # can *state* the work is not a change to Qevik's own source may lower it —
    # and stating it is what makes unattended recurring work possible at all,
    # because a mission that edits Qevik is one policy will never run without a
    # person, at three in the morning least of all.
    verdict = policy.decide(plan, agent_id=agent_id,
                            modifies_qevik_itself=modifies_qevik_itself)
    destination = (MissionStatus.AWAITING_APPROVAL if verdict.needs_a_person
                   else MissionStatus.QUEUED)
    # The agent is recorded here, not merely passed to `decide`. Without it the
    # scheduler had no idea which agent a queued mission needed, so it could not
    # tell that the mission required a credential nobody had configured — and
    # offered it for dispatch. Storing what policy was told keeps the blast
    # radius somebody approved and the one read later the same value.
    return transition(mission, destination, tenant=tenant, actor=actor, plan=plan,
                      agent_id=agent_id or mission.agent_id,
                      note=f"plan attached; policy: {verdict.because}")


def claim(mission: Mission, *, worker: str, tenant: TenantId | None
          ) -> tuple[Mission, BusinessEvent]:
    """Take a queued mission for one worker.

    See the module note: atomic against a single writer only.
    """
    tenant = _require_tenant(tenant, method="mission.claim")
    if not worker.strip():
        raise NotPermitted("a claim must name the worker holding it, or a "
                           "crashed mission cannot be told from an idle one")
    # Held first: both refusals are true of an already-claimed mission, and
    # "already held by w1" tells the caller who has it, where "not claimable"
    # only tells them it is busy.
    if mission.claimed_by:
        raise NotPermitted(f"{mission.id} is already held by {mission.claimed_by}")
    if mission.status not in CLAIMABLE:
        raise NotPermitted(f"{mission.id} is {mission.status.value}, not claimable")
    # A deferral is enforced here rather than trusted to the scheduler. A worker
    # that takes the oldest queued mission — which is exactly what the worker
    # does — would otherwise run work somebody deliberately moved to tonight,
    # and the deferral would be a suggestion.
    if mission.not_before and datetime.now(UTC) < mission.not_before:
        raise NotPermitted(
            f"{mission.id} is held until "
            f"{mission.not_before.isoformat(timespec='minutes')}")
    return transition(mission, MissionStatus.PROCESSING, tenant=tenant,
                      actor=worker, claimed_by=worker, note=f"claimed by {worker}")


def defer(mission: Mission, *, until: datetime, tenant: TenantId | None,
          reason: str, actor: str = "scheduler"
          ) -> tuple[Mission, BusinessEvent]:
    """Hold a mission until a chosen moment, with the reason recorded.

    Not a status change: the mission stays queued, because it is still work
    somebody wants done. What changes is when it may start, and that is durable
    — folded from the timeline like everything else — so a restart does not
    forget the window and start a night job at eleven in the morning.

    Refuses a moment in the past. "Deferred until yesterday" reads as a decision
    while behaving as no decision at all.
    """
    tenant = _require_tenant(tenant, method="mission.defer")
    if not owns(mission.tenant_id, tenant):
        raise NotPermitted("this mission belongs to a different tenant")
    if mission.terminal:
        raise NotPermitted(f"{mission.id} is {mission.status.value}; there is "
                           "nothing left to defer")
    if not reason.strip():
        raise NotPermitted("a deferral must say why, or nobody can tell it from "
                           "a queue that is simply long")
    if until <= datetime.now(UTC):
        raise NotPermitted("a deferral must point at a future moment")
    updated = mission.model_copy(update={"not_before": until,
                                         "updated_at": datetime.now(UTC)})
    return updated, _event(updated, actor=actor,
                           note=f"deferred until "
                                f"{until.isoformat(timespec='minutes')}: {reason}")


def release(mission: Mission, *, tenant: TenantId | None, reason: str,
            actor: str = "supervisor") -> tuple[Mission, BusinessEvent]:
    """Return a mission whose worker died. Nothing is retried silently."""
    if mission.terminal:
        raise NotPermitted(f"{mission.id} is {mission.status.value}; there is "
                           "nothing to release")
    return transition(mission, MissionStatus.QUEUED, tenant=tenant, actor=actor,
                      claimed_by="", note=f"released: {reason}")


def stale(missions: list[Mission], *, now: datetime | None = None,
          timeout: timedelta = CLAIM_TIMEOUT) -> tuple[Mission, ...]:
    """Missions held by a worker that has not reported for too long."""
    at = now or datetime.now(UTC)
    return tuple(m for m in missions
                 if m.claimed_by and not m.terminal
                 and at - m.updated_at > timeout)


def record_invocation(mission: Mission, invocation: AgentInvocation, *,
                      tenant: TenantId | None) -> tuple[Mission, BusinessEvent]:
    """Append what an agent call cost. Never replaces an earlier one."""
    tenant = _require_tenant(tenant, method="mission.record_invocation")
    if not owns(mission.tenant_id, tenant):
        raise NotPermitted("this mission belongs to a different tenant")
    updated = mission.model_copy(update={
        "invocations": (*mission.invocations, invocation),
        "updated_at": datetime.now(UTC)})
    return updated, _event(updated, actor=invocation.provider,
                           note=f"{invocation.provider}/{invocation.model}")


def fold(events: list, *, tenant: TenantId | None = None) -> list[dict]:
    """TENANT_SCOPED. The current state of every mission, newest first.

    The **latest** event wins, by its own `updated_at` — not the last one in the
    list. Position and time are the same thing only when nothing ever writes out
    of order, and the first real run of the worker did exactly that: the sink
    persisted the worker's events as they happened while the caller appended the
    earlier create/plan/approve events afterwards, so a completed mission folded
    back to `awaiting_approval`.

    A log that must be replayed in the order it was written is not really an
    append-only log; it is a log with a hidden ordering requirement. This has no
    such requirement.
    """
    tenant = _require_tenant(tenant, method="mission.fold")
    current: dict[str, dict] = {}
    for event in events:
        kind = getattr(event, "kind", None) or event.get("kind")
        if kind != KIND:
            continue
        detail = getattr(event, "detail", None) or event.get("detail") or {}
        if not owns(detail.get("tenant_id"), tenant):
            continue
        mission_id = detail.get("mission_id")
        if not mission_id:
            continue
        seen = current.get(mission_id)
        if seen is None or detail.get("updated_at", "") >= seen.get("updated_at", ""):
            current[mission_id] = dict(detail)
    return sorted(current.values(), key=lambda d: d.get("updated_at", ""),
                  reverse=True)


def history(events: list, mission_id: str, *, tenant: TenantId | None = None
            ) -> list[dict]:
    """Every transition of one mission, oldest first. Never collapsed."""
    tenant = _require_tenant(tenant, method="mission.history")
    found = []
    for event in events:
        kind = getattr(event, "kind", None) or event.get("kind")
        if kind != KIND:
            continue
        detail = getattr(event, "detail", None) or event.get("detail") or {}
        if detail.get("mission_id") != mission_id:
            continue
        if not owns(detail.get("tenant_id"), tenant):
            continue
        found.append(dict(detail))
    # By time, not by position, for the same reason as `fold`. A history shown
    # in arrival order would read as though the mission went backwards.
    return sorted(found, key=lambda d: d.get("updated_at", ""))


def rehydrate(summary: dict, *, tenant: TenantId | None = None) -> Mission:
    """A folded mission back into a `Mission`, so a surface can act on it.

    `fold()` returns dicts because a read model should not force a caller to
    import the model layer. But approving a mission means calling `transition()`,
    which needs the object — so the round trip has to be lossless, or an approval
    made from the mission control would silently drop the plan it approved.

    Refuses a summary belonging to another tenant rather than reconstructing it:
    the caller has already been scoped, and a mismatch here means the summary
    came from somewhere it should not have.
    """
    tenant = _require_tenant(tenant, method="mission.rehydrate")
    if not owns(summary.get("tenant_id"), tenant):
        raise NotPermitted("that mission belongs to another tenant")
    fields = {k: v for k, v in summary.items()
              if k in Mission.model_fields and k != "id"}
    return Mission.model_validate({**fields, "id": summary.get("mission_id", "")})
