"""Mission Control's read model, tested on the mission that gets buried.

§12's real risk is not a missing field, it is an ordering that hides work. A
list sorted by timestamp puts a blocked mission under a week of completed ones,
and nobody sees the thing that needs them. So the ordering is the first thing
tested here, and the derivations second — because a UI that computes `status`
itself is a second answer that will eventually disagree with this one.
"""

from __future__ import annotations

import pytest

from atlas_kernel.controlplane.missions import attention, board, detail
from atlas_kernel.mission import (
    AgentInvocation,
    Blocker,
    MissionStatus,
    Plan,
    PlanStep,
    attach_plan,
    claim,
    create,
    record_invocation,
    transition,
)
from atlas_kernel.opportunity.tenancy import TenantRequired

A, B = "tenant-alpha", "tenant-beta"


def _mission(title: str, tenant=A, *, approval_required=False):
    """A queued mission, reached through approval rather than around it.

    Policy, not the plan's own flag, decides whether a person is needed — so
    this approves what policy holds instead of relying on a planner that used to
    be able to authorise itself.
    """
    mission, first = create(tenant=tenant, title=title, requested_by="ayoub")
    mission, second = transition(mission, MissionStatus.PLANNING, tenant=tenant)
    plan = Plan(goal=f"goal for {title}", approval_required=approval_required,
                steps=(PlanStep(order=1, title="step"),))
    mission, third = attach_plan(mission, plan, tenant=tenant)
    events = [first, second, third]
    if not approval_required and mission.status is MissionStatus.AWAITING_APPROVAL:
        mission, fourth = transition(mission, MissionStatus.QUEUED, tenant=tenant,
                                     actor="ayoub", note="approved by a person")
        events.append(fourth)
    return mission, events


# ============================================ ordering surfaces the blocked

def test_work_needing_a_person_sorts_above_finished_work() -> None:
    """A blocked mission sorted by timestamp disappears under completed ones."""
    events = []

    done, made = _mission("finished work")
    events += made
    done, event = claim(done, worker="w1", tenant=A)
    events.append(event)
    for step in (MissionStatus.TESTING, MissionStatus.REVIEWING,
                 MissionStatus.COMMITTING, MissionStatus.COMPLETE):
        done, event = transition(done, step, tenant=A)
        events.append(event)

    blocked, made = _mission("blocked work")
    events += made
    blocked, event = transition(
        blocked, MissionStatus.BLOCKED, tenant=A,
        blockers=(Blocker(kind="PENDING_CREDENTIAL", detail="no token",
                          action="Add it"),))
    events.append(event)

    listed = board(events, tenant=A)["missions"]
    assert listed[0]["title"] == "blocked work"
    assert listed[-1]["title"] == "finished work"


def test_awaiting_approval_is_flagged_as_needing_a_person() -> None:
    mission, events = _mission("needs approval", approval_required=True)
    assert mission.status is MissionStatus.AWAITING_APPROVAL

    listed = board(events, tenant=A)
    assert listed["counts"]["needs_human"] == 1
    assert listed["needs_human"][0]["title"] == "needs approval"
    assert attention(events, tenant=A)[0]["needs_human"] is True


def test_a_queued_mission_is_not_waiting_on_a_person() -> None:
    """It is waiting on a worker, which is the system's problem, not theirs."""
    _mission_obj, events = _mission("queued work")
    listed = board(events, tenant=A)
    assert listed["counts"]["needs_human"] == 0


def test_running_work_is_separated_from_waiting_work() -> None:
    mission, events = _mission("running work")
    mission, event = claim(mission, worker="w1", tenant=A)
    events.append(event)

    listed = board(events, tenant=A)
    assert listed["counts"]["running"] == 1
    assert listed["running"][0]["claimed_by"] == "w1"


# ============================================ the client computes nothing

def test_the_summary_states_rather_than_implies() -> None:
    """A UI inferring `needs_human` from a status string is a second answer."""
    mission, events = _mission("x", approval_required=True)
    row = board(events, tenant=A)["missions"][0]

    for field in ("status", "needs_human", "blockers", "commits", "cost",
                  "goal", "steps", "claimed_by", "updated_at"):
        assert field in row, field


def test_a_mission_with_no_reported_cost_shows_none_not_zero() -> None:
    mission, events = _mission("x")
    mission, event = record_invocation(
        mission, AgentInvocation(provider="scripted", model="deterministic"),
        tenant=A)
    events.append(event)

    row = board(events, tenant=A)["missions"][0]
    assert row["cost"] is None, "a free-looking mission and an unmeasured one differ"
    assert row["invocations"] == 1


def test_a_blocker_is_carried_with_its_action() -> None:
    mission, events = _mission("blocked")
    mission, event = transition(
        mission, MissionStatus.BLOCKED, tenant=A,
        blockers=(Blocker(kind="PENDING_CREDENTIAL", detail="no Cloudflare token",
                          action="Add QEVIK_CLOUDFLARE_API_TOKEN"),))
    events.append(event)

    row = board(events, tenant=A)["missions"][0]
    assert row["blockers"][0]["action"] == "Add QEVIK_CLOUDFLARE_API_TOKEN"


# ============================================ detail and timeline

def test_detail_carries_the_whole_timeline() -> None:
    mission, events = _mission("traceable")
    mission, event = claim(mission, worker="w1", tenant=A)
    events.append(event)

    found = detail(events, mission.id, tenant=A)
    assert found is not None
    # `awaiting_approval` is in the timeline now: policy decides whether a
    # person is needed, so approval is a step the record shows rather than one
    # the planner skipped by setting a flag on its own plan.
    assert [entry["status"] for entry in found["timeline"]] == [
        "draft", "planning", "awaiting_approval", "queued", "processing"]
    assert found["plan"]["goal"] == "goal for traceable"


def test_detail_of_an_unknown_mission_is_absent() -> None:
    _mission_obj, events = _mission("x")
    assert detail(events, "mission-does-not-exist", tenant=A) is None


def test_agent_calls_are_shown_in_full_not_just_counted() -> None:
    """Cost provenance is what a person checks when a number looks wrong."""
    mission, events = _mission("x")
    mission, event = record_invocation(
        mission, AgentInvocation(provider="qwen", model="qwen-plus",
                                 input_tokens=100, output_tokens=50,
                                 cost=0.001, cost_status="ESTIMATED"),
        tenant=A)
    events.append(event)

    found = detail(events, mission.id, tenant=A)
    assert found["agent_calls"][0]["cost_status"] == "ESTIMATED"
    assert found["agent_calls"][0]["input_tokens"] == 100


# ============================================ tenancy

def test_one_tenant_never_sees_anothers_missions() -> None:
    _a, events_a = _mission("alpha work", tenant=A)
    _b, events_b = _mission("beta work", tenant=B)
    everything = events_a + events_b

    titles_a = {m["title"] for m in board(everything, tenant=A)["missions"]}
    titles_b = {m["title"] for m in board(everything, tenant=B)["missions"]}
    assert titles_a == {"alpha work"}
    assert titles_b == {"beta work"}


def test_another_tenants_mission_is_absent_from_detail() -> None:
    mission, events = _mission("alpha work", tenant=A)
    assert detail(events, mission.id, tenant=A) is not None
    assert detail(events, mission.id, tenant=B) is None


def test_every_read_requires_a_tenant() -> None:
    _m, events = _mission("x")
    for call in (lambda: board(events, tenant=None),
                 lambda: detail(events, "m", tenant=None),
                 lambda: attention(events, tenant=None)):
        with pytest.raises(TenantRequired):
            call()


def test_the_board_survives_an_empty_log() -> None:
    listed = board([], tenant=A)
    assert listed["missions"] == []
    assert listed["counts"]["total"] == 0
