"""Recurring work, and the three ways a schedule goes wrong quietly.

The behaviours pinned here are the ones that are invisible until they matter:
a missed week producing a week of missions, one occurrence producing two, and a
slow run stacking on itself. Each is fine in every test that runs on a healthy
host at a convenient hour, which is why they are asserted directly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from atlas_kernel.mission import origins, policy, recurrence, service
from atlas_kernel.mission.models import MissionStatus, Plan, PlanStep

TENANT = "tenant-recurrence"
DAY = timedelta(days=1)
ANCHOR = datetime(2026, 8, 1, 2, 0, tzinfo=UTC)


def a_plan(*, files=("reports/scan.md",), cost=0.5) -> Plan:
    return Plan(goal="check something that should be checked every day",
                steps=(PlanStep(order=1, title="run the check", files=files),),
                test_plan="the check reports what it found",
                estimated_cost=cost, approval_required=False)


def a_recurrence(**over) -> recurrence.Recurrence:
    fields = dict(id="rec-daily", tenant_id=TENANT, title="Daily check",
                  plan=a_plan(), agent_id="self-check", every=DAY,
                  anchor=ANCHOR, origin_name=origins.EMPTY_NAME)
    fields.update(over)
    return recurrence.Recurrence(**fields)


REGISTRY = origins.Registry.build()


def enqueue(rule: recurrence.Recurrence, firing: recurrence.Firing):
    """`enqueue` with the origin resolved the way the worker resolves it."""
    return recurrence.enqueue(rule, firing, tenant=TENANT,
                              origin=REGISTRY.resolve(rule.origin_name))


def summary_of(mission, *, status=None, occurrence=None) -> dict:
    out = mission.summary()
    if status is not None:
        out["status"] = status.value
    if occurrence is not None:
        out["occurrence"] = occurrence
    return out


# ---------------------------------------------------------------- the series

def test_the_series_is_a_pure_function_of_anchor_and_period():
    rec = a_recurrence()
    assert recurrence.latest_due(rec, at=ANCHOR) == ANCHOR
    assert recurrence.latest_due(rec, at=ANCHOR + timedelta(hours=23)) == ANCHOR
    assert recurrence.latest_due(rec, at=ANCHOR + DAY) == ANCHOR + DAY
    assert recurrence.latest_due(rec, at=ANCHOR + DAY * 30) == ANCHOR + DAY * 30


def test_nothing_is_due_before_the_anchor():
    rec = a_recurrence()
    assert recurrence.latest_due(rec, at=ANCHOR - timedelta(seconds=1)) is None
    firing = recurrence.assess(rec, at=ANCHOR - DAY, missions=[])
    assert not firing.fires
    assert firing.hold is recurrence.Hold.NOT_STARTED


def test_the_series_does_not_drift():
    """`anchor + n * every`, never `now + every` accumulated.

    A schedule that adds a period to the moment it happened to run slides later
    every day by however long the run took.
    """
    rec = a_recurrence(every=timedelta(hours=6))
    at = ANCHOR + timedelta(days=90, minutes=17)
    due = recurrence.latest_due(rec, at=at)
    assert (due - rec.anchor) % rec.every == timedelta(0)
    assert due <= at < due + rec.every


def test_a_missed_week_produces_one_mission_not_seven():
    """The rule the module is most likely to be "fixed" into breaking."""
    rec = a_recurrence()
    firing = recurrence.assess(rec, at=ANCHOR + DAY * 7 + timedelta(hours=3),
                               missions=[])
    assert firing.fires
    assert firing.occurrence == ANCHOR + DAY * 7
    # And the six occurrences in between are not offered by any means.
    assert recurrence.latest_due(rec, at=ANCHOR + DAY * 7) == ANCHOR + DAY * 7


def test_next_after_answers_when_nothing_is_happening():
    rec = a_recurrence()
    assert recurrence.next_after(rec, at=ANCHOR - DAY) == ANCHOR
    assert recurrence.next_after(rec, at=ANCHOR + timedelta(hours=1)) == ANCHOR + DAY


# ------------------------------------------------------------------ identity

def test_the_occurrence_key_is_the_same_in_every_process():
    one = recurrence.key_for("rec-daily", ANCHOR)
    two = recurrence.key_for("rec-daily", ANCHOR.astimezone(
        __import__("datetime").timezone(timedelta(hours=4))))
    assert one == two == "rec-daily@2026-08-01T02:00:00Z"


def test_different_occurrences_have_different_keys():
    assert (recurrence.key_for("r", ANCHOR)
            != recurrence.key_for("r", ANCHOR + DAY))
    assert (recurrence.key_for("r1", ANCHOR)
            != recurrence.key_for("r2", ANCHOR))


# -------------------------------------------------------------------- guards

def test_a_disabled_recurrence_holds_and_says_so():
    firing = recurrence.assess(a_recurrence(enabled=False),
                               at=ANCHOR + DAY, missions=[])
    assert firing.hold is recurrence.Hold.DISABLED
    assert not firing.fires


def test_an_occurrence_that_already_has_a_mission_does_not_fire_again():
    rec = a_recurrence()
    at = ANCHOR + DAY
    first = recurrence.assess(rec, at=at, missions=[])
    assert first.fires

    mission, _ = enqueue(rec, first)
    again = recurrence.assess(
        rec, at=at + timedelta(hours=2),
        missions=[summary_of(mission, status=MissionStatus.COMPLETE)])
    assert again.hold is recurrence.Hold.ALREADY_CREATED
    assert not again.fires


def test_a_completed_occurrence_does_not_block_the_next_one():
    rec = a_recurrence()
    mission, _ = enqueue(rec, recurrence.assess(rec, at=ANCHOR, missions=[]))
    done = [summary_of(mission, status=MissionStatus.COMPLETE)]
    tomorrow = recurrence.assess(rec, at=ANCHOR + DAY, missions=done)
    assert tomorrow.fires
    assert tomorrow.occurrence == ANCHOR + DAY


@pytest.mark.parametrize("status", [MissionStatus.QUEUED, MissionStatus.PROCESSING,
                                    MissionStatus.TESTING, MissionStatus.REVIEWING,
                                    MissionStatus.AWAITING_APPROVAL])
def test_a_slow_run_does_not_stack(status):
    """Yesterday still going means today does not start."""
    rec = a_recurrence()
    mission, _ = enqueue(rec, recurrence.assess(rec, at=ANCHOR, missions=[]))
    live = [summary_of(mission, status=status)]
    tomorrow = recurrence.assess(rec, at=ANCHOR + DAY, missions=live)
    assert not tomorrow.fires
    assert tomorrow.hold is recurrence.Hold.PREVIOUS_UNFINISHED
    assert "still" in tomorrow.detail


def test_a_blocked_occurrence_does_not_end_the_series():
    """The failure this module exists to prevent, in its own shape.

    A blocked mission never finishes on its own. Treating it as a live run
    would stop the recurrence for good and say nothing — a schedule dying in
    silence, which is how eight days of backups went missing.
    """
    rec = a_recurrence()
    mission, _ = enqueue(rec, recurrence.assess(rec, at=ANCHOR, missions=[]))
    blocked = [summary_of(mission, status=MissionStatus.BLOCKED)]
    tomorrow = recurrence.assess(rec, at=ANCHOR + DAY, missions=blocked)
    assert tomorrow.fires


def test_another_recurrences_missions_are_not_confused_with_this_one():
    """The prefix match must not treat `rec-daily-extra` as `rec-daily`."""
    rec = a_recurrence()
    other = a_recurrence(id="rec-daily-extra")
    theirs, _ = enqueue(other, recurrence.assess(other, at=ANCHOR, missions=[]))
    firing = recurrence.assess(
        rec, at=ANCHOR, missions=[summary_of(theirs, status=MissionStatus.PROCESSING)])
    assert firing.fires, "another recurrence's live mission held this one"


# -------------------------------------------------------- policy is not bypassed

def test_a_recurring_mission_goes_through_the_same_policy():
    """Cheap, reversible, confined, non-self-modifying: it reaches the queue."""
    rec = a_recurrence()
    mission, events = enqueue(rec, recurrence.assess(rec, at=ANCHOR, missions=[]))
    assert mission.status is MissionStatus.QUEUED
    assert mission.occurrence == recurrence.key_for(rec.id, ANCHOR)
    assert len(events) == 3      # created, planning, planned


def test_a_recurrence_that_touches_qeviks_source_can_never_run_unattended():
    """A schedule is not a person, at three in the morning least of all."""
    rec = a_recurrence(origin_name="qevik")
    mission, _ = enqueue(rec, recurrence.assess(rec, at=ANCHOR, missions=[]))
    assert mission.status is MissionStatus.AWAITING_APPROVAL


def test_an_expensive_recurrence_still_needs_a_person():
    rec = a_recurrence(plan=a_plan(cost=policy.COSTLY_UNITS + 1))
    mission, _ = enqueue(rec, recurrence.assess(rec, at=ANCHOR, missions=[]))
    assert mission.status is MissionStatus.AWAITING_APPROVAL


def test_a_recurrence_writing_outside_the_reviewed_free_paths_needs_a_person():
    rec = a_recurrence(plan=a_plan(files=("packages/kernel/atlas_kernel/api.py",)))
    mission, _ = enqueue(rec, recurrence.assess(rec, at=ANCHOR, missions=[]))
    assert mission.status is MissionStatus.AWAITING_APPROVAL


def test_an_undeclared_agent_is_treated_as_the_worst_case():
    """`policy` gives an unknown agent an unbounded blast radius. Unattended
    work by something nobody declared must not slip past that."""
    rec = a_recurrence(agent_id="nobody-declared-this")
    mission, _ = enqueue(rec, recurrence.assess(rec, at=ANCHOR, missions=[]))
    assert mission.status is MissionStatus.AWAITING_APPROVAL


def test_enqueue_refuses_a_firing_that_is_not_firing():
    rec = a_recurrence(enabled=False)
    held = recurrence.assess(rec, at=ANCHOR, missions=[])
    with pytest.raises(ValueError, match="not firing"):
        enqueue(rec, held)


# ------------------------------------------------------------- the declaration

def test_a_recurrence_may_not_fire_faster_than_the_minimum():
    with pytest.raises(ValueError, match="flood"):
        a_recurrence(every=timedelta(seconds=30))


def test_a_naive_anchor_is_refused():
    with pytest.raises(ValueError, match="timezone"):
        a_recurrence(anchor=datetime(2026, 8, 1, 2, 0))


def test_a_recurrence_needs_an_agent():
    with pytest.raises(ValueError):
        a_recurrence(agent_id="  ")


def test_an_unknown_field_is_refused():
    """`extra="forbid"`, for the reason `Agent(ready=False)` needed it: a
    silently ignored field reads as a setting that was applied."""
    with pytest.raises(ValueError):
        a_recurrence(run_immediately=True)


def test_the_declared_set_is_code_controlled_and_tenant_scoped():
    assert isinstance(recurrence.RECURRENCES, tuple)
    for declared in recurrence.RECURRENCES:
        assert isinstance(declared, recurrence.Recurrence)
    assert recurrence.declared(tenant="no-such-tenant") == ()


def test_describe_says_when_each_one_next_fires():
    for entry in recurrence.describe(at=ANCHOR):
        assert entry["next_at"]
        assert entry["origin_name"]


def test_the_settled_set_agrees_with_the_canonical_terminal_set():
    """Guards against the two lists drifting apart, which they did once."""
    from atlas_kernel.mission.models import TERMINAL
    assert {s.value for s in TERMINAL} <= recurrence._SETTLED
    assert MissionStatus.PROCESSING.value not in recurrence._SETTLED


def test_a_recurring_mission_is_not_claimable_before_it_is_queued():
    rec = a_recurrence(origin_name="qevik")
    mission, _ = enqueue(rec, recurrence.assess(rec, at=ANCHOR, missions=[]))
    with pytest.raises(service.NotPermitted, match="not claimable"):
        service.claim(mission, worker="w-1", tenant=TENANT)


# ------------------------------------------- the origin decides, not a boolean

def test_a_recurrence_cannot_be_given_an_origin_it_did_not_declare():
    """The gap the boolean left.

    `modifies_qevik_itself` was a field on the recurrence, so a declaration
    saying "this is not a change to Qevik" could be handed a clone of Qevik
    anyway — the mission would record one repository and use another. The name
    and the resolved origin are now checked against each other.
    """
    rec = a_recurrence(origin_name=origins.EMPTY_NAME)
    firing = recurrence.assess(rec, at=ANCHOR, missions=[])
    with pytest.raises(ValueError, match="declares origin"):
        recurrence.enqueue(rec, firing, tenant=TENANT,
                           origin=REGISTRY.resolve("qevik"))


def test_the_empty_origin_is_what_makes_unattended_work_possible():
    rec = a_recurrence(origin_name=origins.EMPTY_NAME)
    mission, _ = enqueue(rec, recurrence.assess(rec, at=ANCHOR, missions=[]))
    assert mission.status is MissionStatus.QUEUED
    assert mission.origin_name == origins.EMPTY_NAME


def test_the_same_plan_against_qevik_waits_for_a_person():
    """Identical plan, identical agent, identical cost. Only the origin differs."""
    unattended = a_recurrence(id="rec-a", origin_name=origins.EMPTY_NAME)
    gated = a_recurrence(id="rec-b", origin_name="qevik")
    assert unattended.plan == gated.plan

    a, _ = enqueue(unattended, recurrence.assess(unattended, at=ANCHOR, missions=[]))
    b, _ = enqueue(gated, recurrence.assess(gated, at=ANCHOR, missions=[]))
    assert a.status is MissionStatus.QUEUED
    assert b.status is MissionStatus.AWAITING_APPROVAL


def test_a_recurrence_naming_an_unregistered_origin_cannot_be_enqueued():
    rec = a_recurrence(origin_name="acme-web")
    with pytest.raises(origins.UnknownOrigin):
        REGISTRY.resolve(rec.origin_name)


# ------------------------------------------------- the declared canary is real

def test_the_declared_recurrences_are_all_resolvable_and_honest():
    """Every entry in RECURRENCES must name an origin the built-in registry has,
    or the worker creates nothing and logs an error nobody reads."""
    registry = origins.Registry.build()
    for rule in recurrence.RECURRENCES:
        origin = registry.resolve(rule.origin_name)
        assert origin.name == rule.origin_name
        # An entry that runs unattended must be EMPTY. Anything else reaching a
        # queue without a person would be a policy hole shaped like a schedule.
        if not origin.modifies_qevik_itself:
            assert origin.may_run_unattended, (
                f"{rule.id} names {origin.name!r}, which is neither Qevik nor "
                "empty; it would run unattended against somebody's repository")


def test_the_canary_actually_reaches_the_queue_unattended():
    canary = next(r for r in recurrence.RECURRENCES
                  if r.id == "rec-execution-canary")
    registry = origins.Registry.build()
    firing = recurrence.assess(canary, at=canary.anchor, missions=[])
    assert firing.fires
    mission, events = recurrence.enqueue(
        canary, firing, tenant=canary.tenant_id,
        origin=registry.resolve(canary.origin_name))
    assert mission.status is MissionStatus.QUEUED, (
        "the canary is the first unattended recurrence; if it needs a person "
        "then nothing recurring runs overnight")
    assert len(events) == 3
    assert mission.occurrence.startswith("rec-execution-canary@")


def test_the_canary_is_scheduled_inside_the_night_window():
    from atlas_kernel.fabric import scheduler
    canary = next(r for r in recurrence.RECURRENCES
                  if r.id == "rec-execution-canary")
    at = canary.anchor.timetz().replace(tzinfo=None)
    assert scheduler.NIGHT_START <= at < scheduler.NIGHT_END


def test_the_canary_only_writes_to_reviewed_free_paths():
    """What lets it clear policy without a person. If a future edit adds a step
    that writes elsewhere, this fails rather than the mission silently starting
    to wait for approval every night."""
    canary = next(r for r in recurrence.RECURRENCES
                  if r.id == "rec-execution-canary")
    for path in canary.plan.files:
        assert path.startswith(policy.SAFE_PREFIXES), path
