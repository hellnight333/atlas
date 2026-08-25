"""Missions, tested on the shortcuts an agent under pressure would take.

The dangerous transition is queued straight to complete: it skips the tests and
the review, and it is exactly what a system optimising for a green report would
do. The state machine refuses it, and that refusal is the first test here.

The second concern is resume. A worker that dies must leave a mission
recoverable, not silently retried and not lost.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from atlas_kernel.mission import (
    AgentInvocation,
    Blocker,
    MissionStatus,
    Plan,
    PlanStep,
    attach_plan,
    claim,
    create,
    fold,
    history,
    record_invocation,
    release,
    stale,
    transition,
)
from atlas_kernel.mission.service import NotPermitted
from atlas_kernel.opportunity.tenancy import TenantRequired

A, B = "tenant-alpha", "tenant-beta"


def _queued(tenant=A):
    """A queued mission, reached through approval rather than around it.

    `attach_plan` used to honour `approval_required=False` and queue directly.
    Policy decides now and holds this plan — it is unpriced, names no agent and
    writes to `themes/clean.py`. So a person approves it, which is the path
    production actually has.
    """
    mission, first = create(tenant=tenant, title="Build multi-page support",
                            requested_by="ayoub")
    mission, second = transition(mission, MissionStatus.PLANNING, tenant=tenant)
    plan = Plan(goal="Multi-page", approval_required=False,
                steps=(PlanStep(order=1, title="Add nav", files=("themes/clean.py",)),))
    mission, third = attach_plan(mission, plan, tenant=tenant)
    events = [first, second, third]
    if mission.status is MissionStatus.AWAITING_APPROVAL:
        mission, fourth = transition(mission, MissionStatus.QUEUED, tenant=tenant,
                                     actor="ayoub", note="approved by a person")
        events.append(fourth)
    return mission, events


# ============================================ the shortcut is refused

def test_a_mission_cannot_skip_testing_and_review() -> None:
    mission, _ = _queued()
    mission, _ = claim(mission, worker="w1", tenant=A)
    with pytest.raises(NotPermitted, match="cannot become complete"):
        transition(mission, MissionStatus.COMPLETE, tenant=A)


def test_the_full_path_to_complete_passes_through_tests_and_review() -> None:
    mission, _ = _queued()
    mission, _ = claim(mission, worker="w1", tenant=A)
    for step in (MissionStatus.TESTING, MissionStatus.REVIEWING,
                 MissionStatus.COMMITTING, MissionStatus.COMPLETE):
        mission, _ = transition(mission, step, tenant=A)
    assert mission.status is MissionStatus.COMPLETE
    assert mission.terminal


def test_a_complete_mission_cannot_move_again() -> None:
    mission, _ = _queued()
    mission, _ = claim(mission, worker="w1", tenant=A)
    for step in (MissionStatus.TESTING, MissionStatus.REVIEWING,
                 MissionStatus.COMMITTING, MissionStatus.COMPLETE):
        mission, _ = transition(mission, step, tenant=A)
    with pytest.raises(NotPermitted):
        transition(mission, MissionStatus.QUEUED, tenant=A)


def test_a_failed_mission_may_be_requeued_but_not_completed() -> None:
    mission, _ = _queued()
    mission, _ = claim(mission, worker="w1", tenant=A)
    mission, _ = transition(mission, MissionStatus.FAILED, tenant=A)
    with pytest.raises(NotPermitted):
        transition(mission, MissionStatus.COMPLETE, tenant=A)
    mission, _ = transition(mission, MissionStatus.QUEUED, tenant=A)
    assert mission.status is MissionStatus.QUEUED


# ============================================ the plan is the boundary

def test_a_plan_requiring_approval_does_not_reach_the_queue() -> None:
    """Arbitrary text never becomes execution; it becomes something readable."""
    mission, _ = create(tenant=A, title="Connect Cloudflare")
    mission, _ = transition(mission, MissionStatus.PLANNING, tenant=A)
    mission, _ = attach_plan(mission, Plan(goal="x", approval_required=True),
                             tenant=A)
    assert mission.status is MissionStatus.AWAITING_APPROVAL
    assert not mission.claimable


def test_a_plan_that_found_blockers_is_blocked_not_queued() -> None:
    mission, _ = create(tenant=A, title="Connect Cloudflare")
    mission, _ = transition(mission, MissionStatus.PLANNING, tenant=A)
    plan = Plan(goal="x", approval_required=False,
                blockers=(Blocker(kind="PENDING_CREDENTIAL",
                                  detail="no Cloudflare token",
                                  action="Add QEVIK_CLOUDFLARE_API_TOKEN"),))
    mission, _ = attach_plan(mission, plan, tenant=A)
    assert mission.status is MissionStatus.BLOCKED
    assert mission.blockers[0].kind == "PENDING_CREDENTIAL"
    assert mission.blockers[0].action


def test_a_mission_needs_a_title() -> None:
    with pytest.raises(NotPermitted, match="nobody can read"):
        create(tenant=A, title="   ")


# ============================================ claim and resume

def test_only_a_queued_mission_can_be_claimed() -> None:
    mission, _ = create(tenant=A, title="x")
    with pytest.raises(NotPermitted, match="not claimable"):
        claim(mission, worker="w1", tenant=A)


def test_a_mission_cannot_be_claimed_twice() -> None:
    mission, _ = _queued()
    mission, _ = claim(mission, worker="w1", tenant=A)
    with pytest.raises(NotPermitted, match="already held"):
        claim(mission, worker="w2", tenant=A)


def test_a_claim_must_name_its_worker() -> None:
    """Or a crashed mission cannot be told from an idle one."""
    mission, _ = _queued()
    with pytest.raises(NotPermitted, match="name the worker"):
        claim(mission, worker="", tenant=A)


def test_a_dead_workers_mission_is_found_and_returned() -> None:
    mission, _ = _queued()
    mission, _ = claim(mission, worker="w1", tenant=A)
    old = mission.model_copy(update={
        "updated_at": datetime.now(UTC) - timedelta(hours=5)})

    assert stale([old]) == (old,)
    released, event = release(old, tenant=A, reason="worker died")
    assert released.status is MissionStatus.QUEUED
    assert released.claimed_by == ""
    assert "worker died" in event.detail["note"], "the reason is recorded"


def test_a_healthy_claim_is_not_stolen() -> None:
    mission, _ = _queued()
    mission, _ = claim(mission, worker="w1", tenant=A)
    assert stale([mission]) == ()


def test_a_finished_mission_is_not_released() -> None:
    mission, _ = _queued()
    mission, _ = claim(mission, worker="w1", tenant=A)
    for step in (MissionStatus.TESTING, MissionStatus.REVIEWING,
                 MissionStatus.COMMITTING, MissionStatus.COMPLETE):
        mission, _ = transition(mission, step, tenant=A)
    with pytest.raises(NotPermitted, match="nothing to release"):
        release(mission, tenant=A, reason="x")


# ============================================ cost is labelled or absent

def test_a_cost_must_say_where_it_came_from() -> None:
    """An unlabelled figure reads as authoritative and cannot be checked."""
    with pytest.raises(ValueError, match="without saying where it came from"):
        AgentInvocation(provider="claude", model="opus", cost=1.23)


def test_a_provider_that_reports_nothing_yields_no_total() -> None:
    mission, _ = _queued()
    mission, _ = record_invocation(
        mission, AgentInvocation(provider="local", model="fake"), tenant=A)
    assert mission.total_cost is None, "None, never 0.0"


def test_costs_accumulate_only_over_what_was_reported() -> None:
    mission, _ = _queued()
    for cost in (1.5, 2.5):
        mission, _ = record_invocation(
            mission, AgentInvocation(provider="claude", model="opus", cost=cost,
                                     cost_status="REPORTED"), tenant=A)
    mission, _ = record_invocation(
        mission, AgentInvocation(provider="local", model="fake"), tenant=A)
    assert mission.total_cost == 4.0


# ============================================ tenancy and history

def test_a_mission_belongs_to_one_tenant() -> None:
    mission, _ = _queued()
    with pytest.raises(NotPermitted, match="different tenant"):
        transition(mission, MissionStatus.PROCESSING, tenant=B)
    with pytest.raises(NotPermitted, match="different tenant"):
        record_invocation(mission, AgentInvocation(provider="p", model="m"),
                          tenant=B)


def test_missions_are_read_only_by_their_tenant() -> None:
    _mission, events = _queued()
    assert fold(events, tenant=A)
    assert fold(events, tenant=B) == []


def test_every_read_requires_a_tenant() -> None:
    _mission, events = _queued()
    for call in (lambda: fold(events, tenant=None),
                 lambda: history(events, "m", tenant=None),
                 lambda: create(tenant=None, title="x")):
        with pytest.raises(TenantRequired):
            call()


def test_history_keeps_every_transition() -> None:
    """A completed mission must remain inspectable, never collapsed."""
    mission, events = _queued()
    mission, claimed = claim(mission, worker="w1", tenant=A)
    events.append(claimed)

    entries = history(events, mission.id, tenant=A)
    # `awaiting_approval` is in the record now because approval is a real step:
    # policy decides whether a person is needed, and the plan no longer
    # authorises itself straight into the queue.
    assert [e["status"] for e in entries] == ["draft", "planning",
                                              "awaiting_approval", "queued",
                                              "processing"]
    # And folding gives the current state without losing the log.
    assert fold(events, tenant=A)[0]["status"] == "processing"
    assert len(history(events, mission.id, tenant=A)) == 5


def test_the_fold_is_the_current_state_not_the_first_one() -> None:
    mission, events = _queued()
    mission, claimed = claim(mission, worker="w1", tenant=A)
    events.append(claimed)
    current = fold(events, tenant=A)
    assert len(current) == 1, "one mission, not one row per transition"
    assert current[0]["claimed_by"] == "w1"


# ============================================ no second job registry

def test_missions_do_not_duplicate_job_status() -> None:
    from atlas_kernel.models import JobStatus

    mission_values = {s.value for s in MissionStatus}
    job_values = {s.value for s in JobStatus}
    # They may overlap in ordinary English words, but a Mission is a request and
    # a Job is a unit of work — the two vocabularies must not be identical.
    assert mission_values != job_values
    assert "awaiting_approval" in mission_values and "awaiting_approval" not in job_values
    # And a mission references jobs rather than replacing them.
    mission, _ = _queued()
    assert hasattr(mission, "job_ids")


# ============================================ out-of-order replay

def test_the_latest_event_wins_regardless_of_arrival_order() -> None:
    """A log that must be replayed in write order is not an append-only log,
    it is a log with a hidden ordering requirement.

    The first real worker run wrote the worker's events through a sink as they
    happened while its caller appended the earlier create/plan/approve events
    afterwards. Folding by position reported a completed mission as still
    awaiting approval.
    """
    mission, events = _queued()
    mission, claimed = claim(mission, worker="w1", tenant=A)
    mission, done = transition(mission, MissionStatus.TESTING, tenant=A)

    forwards = fold([*events, claimed, done], tenant=A)
    backwards = fold([claimed, done, *events], tenant=A)
    shuffled = fold([done, *events, claimed], tenant=A)

    assert forwards[0]["status"] == "testing"
    assert backwards[0]["status"] == "testing"
    assert shuffled[0]["status"] == "testing"


def test_history_reads_forwards_whatever_order_it_arrived_in() -> None:
    """Shown in arrival order it would read as though the mission went
    backwards."""
    mission, events = _queued()
    mission, claimed = claim(mission, worker="w1", tenant=A)

    entries = history([claimed, *events], mission.id, tenant=A)
    # `awaiting_approval` is in the record now because approval is a real step:
    # policy decides whether a person is needed, and the plan no longer
    # authorises itself straight into the queue.
    assert [e["status"] for e in entries] == ["draft", "planning",
                                              "awaiting_approval", "queued",
                                              "processing"]
