"""The scheduler, tested on the things that make a queue lie to its operator.

A queue is honest when the reason a mission is not running is written next to
it and is true. The failures this file guards against are all versions of the
same dishonesty: work that looks imminent and is dead, work that looks stuck and
is fine, work deferred to a window nothing enforces, and money spent halfway
through a mission that could never have finished.

The scheduler decides **order and placement**. It never decides *whether* — and
an AST test reads the source to keep it that way, because "just check the
approval here too" is a one-line change that would put a second, untested copy
of policy in the hot path.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import textwrap
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from atlas_kernel.fabric import Priority, Queue, decide, plan
from atlas_kernel.fabric.agents import Placement, Registry
from atlas_kernel.fabric.scheduler import (
    EXPENSIVE_UNITS,
    UNPRICED_NEEDS,
    Demand,
    NodeSnapshot,
    demands_from,
    eligible,
    next_night,
    unmet_credentials,
)
from atlas_kernel.mission import service
from atlas_kernel.mission.models import Mission, MissionStatus
from atlas_kernel.mission.timeline import Timeline
from atlas_kernel.opportunity.tenancy import TenantRequired

TENANT = "tenant-a"
NOON = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)


def _demand(**over: object) -> Demand:
    """A demand for routed work, unless a test says otherwise.

    `agent_id` is in the base because every test here is about something else --
    ordering, budgets, night windows, placement -- and an unrouted demand is now
    blocked before any of those are reached. `self-check` needs no credentials. Omitting it would have each of
    those tests silently asserting the unrouted rule instead of its own subject.
    Tests that mean unrouted pass `agent_id=""` explicitly.
    """
    base: dict = {"mission_id": "m1", "tenant_id": TENANT, "title": "a mission",
                  "agent_id": "implementer"}
    return Demand(**{**base, **over})


# ============================================ the distinction that carries it all

def test_waiting_and_blocked_are_different_queues() -> None:
    """One resolves by itself; the other never will.

    Merged, they produce a queue where half the entries are progressing and
    half are dead, and nobody can tell which by looking — so the operator
    either chases things that were fine or ignores things that were stuck.
    """
    waiting = decide(_demand(needs_human=True), now=NOON)
    blocked = decide(_demand(blocked_because="the host refused the domain"),
                     now=NOON)
    assert waiting.queue is Queue.WAITING
    assert blocked.queue is Queue.BLOCKED
    assert waiting.queue is not blocked.queue


def test_a_missing_credential_is_blocked_rather_than_waiting() -> None:
    """Nothing resolves it but a person typing a key, so it is not "waiting"."""
    decision = decide(_demand(missing_credentials=("smtp", "resend")), now=NOON)
    assert decision.queue is Queue.BLOCKED
    assert "smtp" in decision.why and "resend" in decision.why
    assert "Credential Centre" in decision.why, (
        "the reason must name where to fix it, or it is a status not an action")


def test_every_queue_says_why_in_a_sentence_a_person_can_act_on() -> None:
    """"Queued" is the outcome, not the reason. A queue whose explanation is
    its own name explains nothing."""
    for demand in (_demand(), _demand(needs_human=True),
                   _demand(blocked_because="no worker"),
                   _demand(missing_credentials=("smtp",)),
                   _demand(depends_on=("m0",))):
        decision = decide(demand, now=NOON)
        assert decision.why.strip()
        assert decision.why.lower() != decision.queue.value.lower()


# ============================================ placement is a requirement

def test_work_needing_a_local_worker_is_blocked_when_there_is_none() -> None:
    """Silently queueing it forever is the failure this prevents: a mission
    that looks imminent for a week because nothing ever says what it needs."""
    decision = decide(_demand(placement=Placement.LOCAL), local_worker=False,
                      now=NOON)
    assert decision.queue is Queue.BLOCKED
    assert "your own machine" in decision.why


def test_the_same_work_runs_once_a_local_worker_is_attached() -> None:
    """The negative control. If it blocked either way the check would be
    measuring nothing."""
    decision = decide(_demand(placement=Placement.LOCAL), local_worker=True,
                      now=NOON)
    assert decision.queue is Queue.NOW


# ============================================ money, before the fact

def test_a_mission_that_cannot_afford_to_finish_never_starts() -> None:
    """Discovering it halfway spends the money and produces nothing."""
    decision = decide(_demand(estimated_units=120.0, remaining_units=40.0),
                      now=NOON)
    assert decision.queue is Queue.BLOCKED
    assert "120" in decision.why and "40" in decision.why


def test_unpriced_work_does_not_start_on_the_last_of_an_allowance() -> None:
    """Treating UNKNOWN as zero is how a budget is spent entirely by the calls
    nobody could price."""
    decision = decide(_demand(estimated_units=None,
                              remaining_units=UNPRICED_NEEDS - 1), now=NOON)
    assert decision.queue is Queue.BLOCKED
    assert "nothing estimated what this costs" in decision.why
    assert "Add an estimate" in decision.why, (
        "the reason must name the fix; the problem is a missing estimate, not "
        "a large one")


def test_unpriced_work_still_runs_while_there_is_real_headroom() -> None:
    """The negative control: UNKNOWN must not mean "never". This is the failure
    that shipped and was caught — using the night-window threshold here blocked
    every unestimated mission on the smallest plan for ever."""
    decision = decide(_demand(estimated_units=None,
                              remaining_units=UNPRICED_NEEDS * 2), now=NOON)
    assert decision.queue is Queue.NOW


def test_the_smallest_plan_can_still_run_an_unestimated_mission() -> None:
    """Pinned against the real allowance rather than an abstract number: the
    LIST plan includes 40 units, and the night-window threshold is 50."""
    from atlas_kernel.credits.models import INCLUDED, Plan

    assert INCLUDED[Plan.LIST] < EXPENSIVE_UNITS, (
        "if this stops being true the test below proves nothing")
    decision = decide(_demand(estimated_units=None,
                              remaining_units=INCLUDED[Plan.LIST]), now=NOON)
    assert decision.queue is Queue.NOW


def test_an_unmetered_tenant_is_not_blocked_by_a_budget_it_does_not_have() -> None:
    """`remaining_units=None` is "no allowance configured", not "no allowance"."""
    assert decide(_demand(estimated_units=9999.0, remaining_units=None),
                  now=NOON).queue is Queue.NOW


# ============================================ deferring is a decision

def test_expensive_unhurried_work_moves_to_the_night_window() -> None:
    decision = decide(_demand(priority=Priority.BACKGROUND,
                              estimated_units=EXPENSIVE_UNITS + 1), now=NOON)
    assert decision.queue is Queue.SCHEDULED
    assert decision.runs_after == next_night(NOON)
    assert "night window" in decision.why


def test_a_deferral_records_the_window_rather_than_just_a_delay() -> None:
    """So "why has this not run" has an answer that is not "the queue is
    long"."""
    decision = decide(_demand(priority=Priority.BACKGROUND,
                              estimated_units=EXPENSIVE_UNITS + 1), now=NOON)
    assert decision.runs_after is not None
    assert decision.runs_after.isoformat(timespec="minutes") in decision.why


def test_work_someone_is_waiting_for_is_never_deferred_to_be_cheaper() -> None:
    """Cheapness is not the point when a person is sitting there."""
    decision = decide(_demand(priority=Priority.INTERACTIVE,
                              estimated_units=EXPENSIVE_UNITS * 5), now=NOON)
    assert decision.queue is Queue.NOW


def test_a_deadline_defeats_the_night_window() -> None:
    """Background work with a deadline is still work with a deadline."""
    decision = decide(_demand(priority=Priority.BACKGROUND,
                              estimated_units=EXPENSIVE_UNITS + 1,
                              deadline=NOON + timedelta(hours=2)), now=NOON)
    assert decision.queue is Queue.NOW


def test_cheap_background_work_is_not_held_back_for_no_reason() -> None:
    """The negative control on deferral: if everything background were
    deferred, the night window would be the whole queue."""
    assert decide(_demand(priority=Priority.BACKGROUND, estimated_units=1.0),
                  now=NOON).queue is Queue.NOW


def test_work_already_in_the_night_window_runs_now() -> None:
    """Otherwise deferral would push it to the *next* night, every night."""
    at_night = NOON.replace(hour=2)
    assert decide(_demand(priority=Priority.BACKGROUND,
                          estimated_units=EXPENSIVE_UNITS + 1),
                  now=at_night).queue is Queue.NOW


def test_next_night_is_deterministic_rather_than_eventually() -> None:
    assert next_night(NOON) == NOON.replace(hour=1, minute=0)  + timedelta(days=1)
    early = NOON.replace(hour=0, minute=30)
    assert next_night(early) == early.replace(hour=1, minute=0)


def test_a_window_a_person_chose_outranks_the_schedulers_own_judgement() -> None:
    """A person deciding "run this tonight" is a decision, not a hint."""
    chosen = NOON + timedelta(hours=6)
    decision = decide(_demand(not_before=chosen), now=NOON)
    assert decision.queue is Queue.SCHEDULED
    assert decision.runs_after == chosen
    assert "you chose" in decision.why


def test_a_window_that_has_passed_stops_holding_the_work() -> None:
    assert decide(_demand(not_before=NOON - timedelta(minutes=1)),
                  now=NOON).queue is Queue.NOW


# ============================================ dependencies

def test_outstanding_dependencies_are_named_not_counted() -> None:
    """"waiting on 2 things" cannot be acted on; "waiting on m0" can."""
    decision = decide(_demand(depends_on=("m0", "m9")),
                      done=frozenset({"m9"}), now=NOON)
    assert decision.queue is Queue.WAITING
    assert "m0" in decision.why
    assert "m9" not in decision.why, "a finished dependency is not a reason"


def test_a_satisfied_dependency_releases_the_work() -> None:
    assert decide(_demand(depends_on=("m0",)), done=frozenset({"m0"}),
                  now=NOON).queue is Queue.NOW


# ============================================ order, and starvation

def test_higher_priority_runs_first() -> None:
    demands = (_demand(mission_id="bg", priority=Priority.BACKGROUND,
                       estimated_units=1.0),
               _demand(mission_id="now", priority=Priority.INTERACTIVE))
    result = plan(demands, tenant=TENANT, now=NOON, concurrency=1)
    assert result["dispatchable"] == ["now"]


def test_an_old_mission_is_not_starved_by_newer_work_of_equal_priority() -> None:
    """Ordering only by priority means a steady trickle of NORMAL work starves
    the NORMAL mission that has been waiting since Tuesday."""
    old = _demand(mission_id="old", created_at=NOON - timedelta(days=3))
    new = _demand(mission_id="new", created_at=NOON)
    result = plan((new, old), tenant=TENANT, now=NOON, concurrency=1)
    assert result["dispatchable"] == ["old"]


def test_work_beyond_capacity_is_next_and_says_so() -> None:
    """NEXT is not a problem, and must not read like one."""
    demands = tuple(_demand(mission_id=f"m{i}") for i in range(3))
    result = plan(demands, tenant=TENANT, now=NOON, concurrency=1)
    assert result["counts"][Queue.NOW.value] == 1
    assert result["counts"][Queue.NEXT.value] == 2
    for row in result["queues"][Queue.NEXT.value]:
        assert "free worker" in row["why"]


def test_blocked_work_does_not_consume_a_worker_slot() -> None:
    """A blocked mission occupying capacity would idle the whole queue behind
    something that is never going to start."""
    demands = (_demand(mission_id="dead", blocked_because="no host"),
               _demand(mission_id="live"))
    result = plan(demands, tenant=TENANT, now=NOON, concurrency=1)
    assert result["dispatchable"] == ["live"]


def test_the_plan_states_the_rule_a_reader_would_otherwise_infer() -> None:
    note = plan((), tenant=TENANT, now=NOON)["note"]
    assert "WAITING resolves" in note and "BLOCKED never" in note


# ============================================ tenancy

def test_another_tenants_work_is_absent_rather_than_refused() -> None:
    """Absent, not forbidden — a refusal confirms the mission exists."""
    demands = (_demand(mission_id="mine"),
               _demand(mission_id="theirs", tenant_id="tenant-b"))
    result = plan(demands, tenant=TENANT, now=NOON, concurrency=5)
    assert result["dispatchable"] == ["mine"]
    everything = json.dumps(result)
    assert "theirs" not in everything and "tenant-b" not in everything


def test_a_plan_without_a_tenant_is_refused_rather_than_defaulted() -> None:
    """A default is how a background job schedules every tenant's work."""
    with pytest.raises(TenantRequired):
        plan((_demand(),), tenant=None, now=NOON)


# ============================================ it decides order, never permission

def test_the_scheduler_does_not_re_implement_policy() -> None:
    """Read from the source. Policy is deterministic and lives above this; a
    second copy in the hot path is one nobody tested and both would drift."""
    from atlas_kernel.fabric import scheduler as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)

    for policy in ("ALLOWED", "EXECUTORS", "ApprovalService",
                   "REQUIRES_CUSTOMER_INPUT", "QuotaLedger"):
        assert policy not in imported, (
            f"{policy} decides whether work may happen. The scheduler decides "
            "when — importing it invites a second, untested copy of the rule")


def test_the_scheduler_cannot_claim_or_dispatch_anything() -> None:
    """It produces a decision. Something else acts on it — which is what keeps
    the atomic claim the single place two workers can race.

    Asserted on the *acts*, not on every verb: `list.append` is not a timeline
    append, and a check that cannot tell them apart is one that gets deleted
    the first time it is wrong.
    """
    from atlas_kernel.fabric import scheduler as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    acting: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            acting.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            acting.add((node.module or "").split(".")[0])
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            acting.add(node.func.id)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            # `service.claim(...)` acts; `out.append(...)` builds a list. The
            # receiver is what separates them.
            receiver = node.func.value
            if isinstance(receiver, ast.Name) and receiver.id in {
                    "service", "timeline", "sink", "db", "session", "client",
                    "repo", "worker"}:
                acting.add(f"{receiver.id}.{node.func.attr}")

    forbidden = acting & {"subprocess", "httpx", "requests", "asyncio",
                          "Popen", "claim", "transition", "release",
                          "dispatch", "execute"}
    assert forbidden == set(), f"the scheduler acts: {forbidden}"
    assert not any("." in name for name in acting), (
        f"the scheduler reaches into a store or a worker: "
        f"{[n for n in acting if '.' in n]}")


def test_a_decision_is_advice_the_claim_still_has_to_be_won() -> None:
    """`dispatchable` is not a grant. Two schedulers on two workers can name
    the same mission, and the atomic claim is what resolves it."""
    demands = (_demand(mission_id="m1"),)
    first = plan(demands, tenant=TENANT, now=NOON, concurrency=1)
    second = plan(demands, tenant=TENANT, now=NOON, concurrency=1)
    assert first["dispatchable"] == second["dispatchable"] == ["m1"]


# ============================================ credentials: any-of, not all-of

def test_one_connected_provider_satisfies_an_agent_that_lists_several() -> None:
    """They are alternatives. Requiring all of them would block work that could
    run perfectly well on the one key somebody entered."""
    agent = Registry().get("planner")
    assert len(agent.credentials) > 1, (
        "this must be an agent with genuine alternatives, or the test proves "
        "nothing about any-of")
    for credential in agent.credentials:
        assert unmet_credentials(agent, connected=frozenset({credential})) == ()


def test_an_agent_with_no_connected_provider_names_all_of_them() -> None:
    """Named, not counted — "needs 3 credentials" cannot be acted on."""
    agent = Registry().get("planner")
    assert unmet_credentials(agent, connected=frozenset()) == agent.credentials


def test_an_unrelated_credential_does_not_satisfy_an_agent() -> None:
    """The negative control on any-of: it must be any of *these*, not any at
    all."""
    agent = Registry().get("correspondent")
    assert unmet_credentials(agent, connected=frozenset({"youtube"})) == (
        agent.credentials)


def test_an_agent_needing_no_credential_is_never_blocked_on_one() -> None:
    agent = Registry().get("website-builder")
    assert agent.credentials == ()
    assert unmet_credentials(agent, connected=frozenset()) == ()


# ============================================ the bridge from folded missions

def _folded(**over: object) -> dict:
    """A folded row for routed work, unless a test says otherwise.

    It records `self-check` because these tests are about deferrals, timestamps
    and approval — and an unrouted mission is now blocked before any of that is
    reached. `self-check` needs no credentials, so routing it does not trade the
    unrouted block for a credential one. `demands_from` is called here without a route map, so this also
    exercises the fallback to the mission's own recorded agent. Tests that mean
    unrouted pass `agent_id=""`.
    """
    mission = Mission(id="m1", tenant_id=TENANT, title="a mission",
                      agent_id="self-check", status=MissionStatus.QUEUED)
    return {**mission.summary(), **over}


# ============================================ selection: who may run this

def _node(name: str, serves: str, caps: set[str], **over) -> NodeSnapshot:
    return NodeSnapshot(worker_name=name, serves=serves,
                        capabilities=frozenset(caps),
                        placements=frozenset(over.pop("placements", {"either"})),
                        node_id=over.pop("node_id", f"host:{name}"), **over)


PUBLISHER = _node("worker-publish", "site-publisher", {"site-publish"})
RESEARCHER = _node("worker-research", "researcher", {"dns", "http-fetch"})


def test_the_scheduler_names_the_worker_that_may_run_it() -> None:
    """"Can this be dispatched" and "to whom" are one answer, from one place."""
    decision = decide(_demand(agent_id="site-publisher",
                              required_tools=("site-publish",)),
                      nodes=(PUBLISHER, RESEARCHER), now=NOON)
    assert decision.queue is Queue.NOW
    assert decision.worker == "worker-publish"


def test_a_worker_that_does_not_advertise_the_tool_is_not_chosen() -> None:
    decision = decide(_demand(agent_id="researcher",
                              required_tools=("http-fetch", "site-publish")),
                      nodes=(RESEARCHER,), now=NOON)
    assert decision.queue is Queue.BLOCKED
    assert "site-publish" in decision.why, decision.why


def test_requiring_no_tools_is_not_a_wildcard() -> None:
    """A plan-based mission declares no recipe and therefore no tools. That is
    not permission to run anywhere: its agent still binds it."""
    decision = decide(_demand(agent_id="researcher", required_tools=()),
                      nodes=(PUBLISHER, RESEARCHER), now=NOON)
    assert decision.worker == "worker-research"


def test_a_stale_worker_is_not_chosen() -> None:
    gone = _node("worker-publish", "site-publisher", {"site-publish"},
                 fresh=False)
    decision = decide(_demand(agent_id="site-publisher",
                              required_tools=("site-publish",)),
                      nodes=(gone,), now=NOON)
    assert decision.queue is Queue.BLOCKED
    assert "stopped reporting" in decision.why, decision.why
    # The control: the same worker, reporting, is chosen.
    assert decide(_demand(agent_id="site-publisher",
                          required_tools=("site-publish",)),
                  nodes=(PUBLISHER,), now=NOON).worker == "worker-publish"


def test_the_most_specific_worker_wins_then_load_then_id() -> None:
    """Synthetic. No production recipe matches two workers, so this ordering has
    never been exercised against real work -- which is the reason to pin it."""
    general = _node("worker-many", "researcher",
                    {"dns", "http-fetch", "shell"}, node_id="host:aaa")
    specific = _node("worker-few", "researcher", {"dns", "http-fetch"},
                     node_id="host:zzz")
    order = eligible(_demand(agent_id="researcher",
                             required_tools=("http-fetch",)),
                     (general, specific))
    assert [n.worker_name for n in order] == ["worker-few", "worker-many"], (
        "id sorted first would have picked the generalist")

    busy = _node("worker-a", "researcher", {"dns", "http-fetch"}, load=1)
    idle = _node("worker-b", "researcher", {"dns", "http-fetch"}, load=0)
    assert eligible(_demand(agent_id="researcher",
                            required_tools=("http-fetch",)),
                    (busy, idle))[0].worker_name == "worker-b"


def test_placement_is_a_requirement_of_the_machine_not_a_preference() -> None:
    """Synthetic: every registered agent declares EITHER today."""
    cloud = _node("worker-cloud", "site-publisher", {"site-publish"},
                  placements={"cloud"})
    assert not eligible(_demand(agent_id="site-publisher",
                                required_tools=("site-publish",),
                                placement=Placement.LOCAL), (cloud,))
    assert eligible(_demand(agent_id="site-publisher",
                            required_tools=("site-publish",),
                            placement=Placement.CLOUD), (cloud,))


def test_no_node_information_is_not_the_same_as_no_nodes() -> None:
    """A caller that never mentions workers gets the queue decided as before.
    A caller that looked and found none gets a block. Collapsing the two would
    have every mission blocked the moment a surface forgot to pass nodes."""
    unaware = decide(_demand(agent_id="site-publisher"), nodes=None, now=NOON)
    empty = decide(_demand(agent_id="site-publisher"), nodes=(), now=NOON)
    assert unaware.queue is Queue.NOW and unaware.worker == ""
    assert empty.queue is Queue.BLOCKED


def test_plan_publishes_the_assignment_every_caller_reads() -> None:
    out = plan((_demand(mission_id="m-pub", agent_id="site-publisher",
                        required_tools=("site-publish",)),
                _demand(mission_id="m-res", agent_id="researcher",
                        required_tools=("http-fetch",))),
               tenant=TENANT, concurrency=4, nodes=(PUBLISHER, RESEARCHER))
    assert out["assigned"] == {"m-pub": "worker-publish",
                               "m-res": "worker-research"}


def test_an_unrouted_mission_is_not_dispatchable() -> None:
    """The contract this rule exists to make truthful.

    The scheduler used to call a mission with no agent dispatchable while the
    worker declined it. Two answers to one question, and the one a reader saw --
    `GET /schedule` -- was the wrong one.
    """
    decision = decide(_demand(agent_id=""), now=NOON)
    assert decision.queue is Queue.BLOCKED
    assert "no agent" in decision.why, decision.why


def test_it_blocks_before_the_credential_check_because_that_check_needs_an_agent() -> None:
    """Order matters here. With no agent resolved there are no credentials to
    be missing, so a later rule would report the mission as perfectly ready."""
    demand = _demand(agent_id="", missing_credentials=())
    assert decide(demand, now=NOON).queue is Queue.BLOCKED


def test_a_route_naming_an_unregistered_agent_is_still_routed() -> None:
    """Routed means somebody was named, not that `fabric.agents` knows them.

    `fake` is deliberately absent from the registry and is still something a
    worker runs. Treating an unresolvable name as unrouted would have made the
    scheduler block work the worker could carry out, and would have hidden a
    genuine mismatch behind "nobody was assigned" -- the worker refuses a
    substitution after claiming, and that is where a wrong name belongs.
    """
    rows = [_folded(agent_id="fake")]
    assert demands_from(rows)[0].agent_id == "fake"
    assert decide(demands_from(rows)[0], now=NOON).queue is Queue.NOW


def test_a_routed_mission_keeps_its_existing_behaviour() -> None:
    """The negative control for all three above: same mission, agent recorded."""
    assert decide(_folded_demand(), now=NOON).queue is Queue.NOW


def _folded_demand():
    return demands_from([_folded()])[0]


def test_plan_reports_the_unrouted_mission_as_blocked_not_dispatchable() -> None:
    """Through `plan`, because `dispatchable` is what every caller reads."""
    rows = [_folded(mission_id="routed"), _folded(mission_id="orphan", agent_id="")]
    out = plan(demands_from(rows), tenant=TENANT, concurrency=4)
    assert out["dispatchable"] == ["routed"]
    assert [d["mission_id"] for d in out["queues"]["BLOCKED"]] == ["orphan"]


def test_finished_missions_are_not_scheduled() -> None:
    rows = [_folded(status="complete"), _folded(mission_id="m2",
                                                status="queued")]
    assert [d.mission_id for d in demands_from(rows)] == ["m2"]


def test_a_mission_awaiting_approval_is_waiting_for_a_person() -> None:
    demands = demands_from([_folded(status="awaiting_approval")])
    assert decide(demands[0], now=NOON).queue is Queue.WAITING


def test_a_blocked_mission_carries_its_recorded_reason() -> None:
    rows = [_folded(status="blocked",
                    blockers=[{"kind": "PENDING_CREDENTIAL",
                               "detail": "no DNS token"}])]
    decision = decide(demands_from(rows)[0], now=NOON)
    assert decision.queue is Queue.BLOCKED
    assert "no DNS token" in decision.why


def test_a_blocked_mission_with_no_recorded_reason_says_that() -> None:
    """Rather than inventing one, or falling through to a queue that implies
    it is progressing."""
    decision = decide(demands_from([_folded(status="blocked")])[0], now=NOON)
    assert decision.queue is Queue.BLOCKED
    assert "not recorded" in decision.why


def test_the_plans_estimate_is_used_and_labelled_absent_when_missing() -> None:
    priced = demands_from([_folded(plan={"goal": "x", "estimated_cost": 12.0})])
    assert priced[0].estimated_units == 12.0
    assert demands_from([_folded(plan=None)])[0].estimated_units is None


def test_an_agents_placement_reaches_the_decision() -> None:
    rows = [_folded()]
    demands = demands_from(rows, agent_for={"m1": "cli-implementer"})
    assert demands[0].placement is Placement.LOCAL
    assert decide(demands[0], local_worker=False, now=NOON).queue is Queue.BLOCKED


def test_an_unknown_route_falls_back_rather_than_raising() -> None:
    """A stale route in a config file must not take the whole queue down."""
    demands = demands_from([_folded()], agent_for={"m1": "nobody"})
    assert demands[0].placement is Placement.EITHER


def test_a_timestamp_that_arrives_naive_does_not_crash_the_comparison() -> None:
    """The fold returns JSON, so datetimes arrive as text — and a naive one
    compared against an aware one raises at exactly the moment a deferral is
    being checked, which is the worst time to find out."""
    rows = [_folded(not_before="2026-08-25T18:00:00")]
    decision = decide(demands_from(rows)[0], now=NOON)
    assert decision.queue is Queue.SCHEDULED


def test_an_unparseable_timestamp_is_ignored_rather_than_fatal() -> None:
    rows = [_folded(not_before="tomorrow-ish")]
    assert decide(demands_from(rows)[0], now=NOON).queue is Queue.NOW


# ============================================ the deferral is enforced, not advised

def test_a_deferred_mission_cannot_be_claimed_by_a_worker_that_ignores_it() -> None:
    """The worker takes the oldest queued mission. If the deferral lived only
    in the scheduler's advice, the worker would run the night job at noon."""
    mission = Mission(id="m1", tenant_id=TENANT, title="heavy",
                      agent_id="self-check", status=MissionStatus.QUEUED)
    held, _ = service.defer(mission, until=datetime.now(UTC) + timedelta(hours=6),
                            tenant=TENANT, reason="expensive and not urgent")
    with pytest.raises(service.NotPermitted, match="held until"):
        service.claim(held, worker="w1", tenant=TENANT)


def test_the_same_mission_is_claimable_once_its_window_arrives() -> None:
    mission = Mission(id="m1", tenant_id=TENANT, title="heavy",
                      agent_id="self-check", status=MissionStatus.QUEUED,
                      not_before=datetime.now(UTC) - timedelta(minutes=1))
    claimed, _ = service.claim(mission, worker="w1", tenant=TENANT)
    assert claimed.status is MissionStatus.PROCESSING


def test_a_deferral_must_point_at_the_future_and_say_why() -> None:
    """"Deferred until yesterday" reads as a decision while behaving as no
    decision at all."""
    mission = Mission(id="m1", tenant_id=TENANT, title="x",
                      status=MissionStatus.QUEUED)
    with pytest.raises(service.NotPermitted, match="future"):
        service.defer(mission, until=datetime.now(UTC) - timedelta(hours=1),
                      tenant=TENANT, reason="because")
    with pytest.raises(service.NotPermitted, match="say why"):
        service.defer(mission, until=datetime.now(UTC) + timedelta(hours=1),
                      tenant=TENANT, reason="  ")


def test_a_deferral_does_not_change_the_missions_status() -> None:
    """It is still work somebody wants done. Moving it to BLOCKED would put it
    in the queue for things that are never going to happen."""
    mission = Mission(id="m1", tenant_id=TENANT, title="x",
                      status=MissionStatus.QUEUED)
    held, _ = service.defer(mission, until=datetime.now(UTC) + timedelta(hours=1),
                            tenant=TENANT, reason="night window")
    assert held.status is MissionStatus.QUEUED


def test_another_tenant_cannot_defer_a_mission() -> None:
    mission = Mission(id="m1", tenant_id=TENANT, title="x",
                      status=MissionStatus.QUEUED)
    with pytest.raises(service.NotPermitted):
        service.defer(mission, until=datetime.now(UTC) + timedelta(hours=1),
                      tenant="tenant-b", reason="night window")


# ============================================ across a real process boundary

def test_a_deferral_survives_the_process_that_made_it(tmp_path: Path) -> None:
    """Not a mocked restart. The deferral is written by this interpreter and
    read by one that never saw it — which is the only way to show the window
    is durable rather than held in memory by the process that chose it.
    """
    sink = Timeline(tmp_path / "missions.jsonl")
    mission = Mission(id="m1", tenant_id=TENANT, title="heavy",
                      agent_id="self-check", status=MissionStatus.QUEUED)
    until = datetime.now(UTC) + timedelta(hours=6)
    _, event = service.defer(mission, until=until, tenant=TENANT,
                             reason="expensive and not urgent")
    sink.append(event)

    script = textwrap.dedent(f"""
        import json
        from atlas_kernel.fabric import decide, demands_from
        from atlas_kernel.mission.service import fold
        from atlas_kernel.mission.timeline import Timeline

        rows = fold(Timeline({str(sink.path)!r}).read(), tenant={TENANT!r})
        decision = decide(demands_from(rows)[0])
        print(json.dumps(decision.summary()))
    """)
    finished = subprocess.run([sys.executable, "-c", script], check=True,
                             capture_output=True, text=True, timeout=120)
    decision = json.loads(finished.stdout.strip().splitlines()[-1])
    assert decision["queue"] == Queue.SCHEDULED.value
    assert decision["runs_after"].startswith(until.isoformat()[:16])


def test_the_fresh_process_would_have_run_it_without_the_deferral(
        tmp_path: Path) -> None:
    """The negative control for the test above. Without it, that test passes
    just as well against a scheduler that defers everything.
    """
    sink = Timeline(tmp_path / "missions.jsonl")
    mission = Mission(id="m1", tenant_id=TENANT, title="heavy",
                      agent_id="self-check", status=MissionStatus.QUEUED)
    _, event = service.transition(mission, MissionStatus.PROCESSING,
                                  tenant=TENANT, actor="w1")
    sink.append(event)

    script = textwrap.dedent(f"""
        import json
        from atlas_kernel.fabric import decide, demands_from
        from atlas_kernel.mission.service import fold
        from atlas_kernel.mission.timeline import Timeline

        rows = fold(Timeline({str(sink.path)!r}).read(), tenant={TENANT!r})
        print(json.dumps(decide(demands_from(rows)[0]).summary()))
    """)
    finished = subprocess.run([sys.executable, "-c", script], check=True,
                             capture_output=True, text=True, timeout=120)
    decision = json.loads(finished.stdout.strip().splitlines()[-1])
    assert decision["queue"] == Queue.NOW.value
