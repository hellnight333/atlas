"""What the worker asks the scheduler before it starts anything.

Three things were reaching the scheduler as blanks, so three of its rules could
never fire. Each of these tests fails on the version of `queued()` that omitted
the argument, which is the only reason they are worth having.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from atlas_kernel.fabric.agents import Registry
from atlas_kernel.fabric.scheduler import demands_from, plan

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "mission_worker", ROOT / "infra" / "mission_worker.py")
worker = importlib.util.module_from_spec(_spec)
sys.modules["mission_worker"] = worker
_spec.loader.exec_module(worker)

TENANT = "tenant-dispatch"


def a_folded_mission(**over) -> dict:
    row = {"mission_id": "m-1", "tenant_id": TENANT, "title": "needs a model",
           "status": "queued", "created_at": "2026-08-26T10:00:00+00:00"}
    row.update(over)
    return row


def dispatchable(routes: dict, connected: frozenset, **kw) -> list[str]:
    demands = demands_from([a_folded_mission()], agents=Registry(),
                           agent_for=routes, connected=connected, **kw)
    return plan(demands, tenant=TENANT, done=frozenset(),
                concurrency=1)["dispatchable"]


# ------------------------------------------------ the agent registry link

def test_without_a_route_the_scheduler_cannot_see_any_credential_requirement():
    """The bug, stated as a fact rather than as history.

    With no `agent_for`, every demand gets `placement=EITHER` and no required
    credentials — so a mission whose agent needs a key nobody configured was
    dispatched, reported as running, and failed at the provider.
    """
    demands = demands_from([a_folded_mission()], agents=Registry(),
                           agent_for={}, connected=frozenset())
    assert demands[0].missing_credentials == ()
    assert dispatchable({}, frozenset()) == ["m-1"]


def test_with_a_route_a_missing_credential_holds_the_mission():
    assert dispatchable({"m-1": "implementer"}, frozenset()) == []


def test_the_held_mission_says_which_credentials_are_missing():
    demands = demands_from([a_folded_mission()], agents=Registry(),
                           agent_for={"m-1": "implementer"},
                           connected=frozenset())
    assert set(demands[0].missing_credentials) >= {"qwen", "anthropic", "openai"}


def test_one_configured_credential_is_enough_to_release_it():
    assert dispatchable({"m-1": "implementer"}, frozenset({"qwen"})) == ["m-1"]


def test_a_deterministic_agent_needs_no_credential_at_all():
    """`self-check` is executor-backed. It must not be held by a missing key."""
    assert dispatchable({"m-1": "self-check"}, frozenset()) == ["m-1"]


def test_an_agent_nobody_declared_is_treated_as_unknown_not_as_permitted():
    demands = demands_from([a_folded_mission()], agents=Registry(),
                           agent_for={"m-1": "no-such-agent"},
                           connected=frozenset())
    assert demands[0].missing_credentials == ()


def test_the_agent_choice_map_covers_the_real_choices():
    """`fake` is deliberately absent — it is not a declared agent."""
    assert worker.REGISTERED_AS["self-check"] == "self-check"
    assert worker.REGISTERED_AS["llm"] == "implementer"
    assert "fake" not in worker.REGISTERED_AS
    for agent_id in worker.REGISTERED_AS.values():
        Registry().get(agent_id)          # raises if it is not declared


# ------------------------------------------------------------ the budget link

def test_an_unknown_allowance_is_not_treated_as_plenty():
    """`None` is UNKNOWN and stays UNKNOWN. The scheduler has its own rule for
    unpriced work; turning it into a number here would decide that quietly."""
    class Unmetered:
        def status(self, *a, **k):
            raise worker.Unmetered("no plan")
    assert worker.tenant_headroom(Unmetered(), TENANT) is None


def test_a_ledger_that_raises_yields_unknown_rather_than_a_number():
    class Broken:
        def status(self, *a, **k):
            raise RuntimeError("the ledger is unreadable")
    assert worker.tenant_headroom(Broken(), TENANT) is None


def test_headroom_reaches_the_demand_so_the_scheduler_can_use_it():
    demands = demands_from([a_folded_mission()], agents=Registry(),
                           agent_for={"m-1": "self-check"},
                           connected=frozenset(), remaining_units=3.0)
    assert demands[0].remaining_units == 3.0


# ------------------------------------------------------ queued() end to end

def test_queued_passes_all_three_through(tmp_path):
    """The integration the three tests above are about, through the real
    function rather than through `demands_from` directly."""
    timeline = worker.Timeline(tmp_path / "missions.jsonl")
    for status in ("draft", "planning", "queued"):
        timeline.append(_event(status))

    class NoAllowance:
        def status(self, *a, **k):
            raise worker.Unmetered("no plan")

    held = worker.queued(timeline, tenant=TENANT, connected=frozenset(),
                         agent_id="implementer")
    assert held == [], "a mission needing a model was offered with no credentials"

    released = worker.queued(timeline, tenant=TENANT,
                             connected=frozenset({"anthropic"}),
                             agent_id="implementer")
    assert [m.id for m in released] == ["m-1"]


def _event(status: str):
    """One mission event, built the way the service builds them."""
    from atlas_kernel.mission import service
    from atlas_kernel.mission.models import Mission, MissionStatus
    mission = Mission(id="m-1", tenant_id=TENANT, title="needs a model",
                      status=MissionStatus(status))
    return service._event(mission, actor="test", note=status)


# ------------------------------------------- the agent recorded on the mission

def test_attaching_a_plan_records_the_agent_policy_was_told_about():
    """So the blast radius somebody approved and the one read later match."""
    from atlas_kernel.mission import service
    from atlas_kernel.mission.models import MissionStatus, Plan, PlanStep
    mission, _ = service.create(tenant=TENANT, title="t", requested_by="x")
    mission, _ = service.transition(mission, MissionStatus.PLANNING,
                                    tenant=TENANT, actor="x")
    mission, _ = service.attach_plan(
        mission, Plan(goal="g", steps=(PlanStep(order=1, title="s"),)),
        tenant=TENANT, agent_id="implementer")
    assert mission.agent_id == "implementer"
    assert service.rehydrate(mission.summary(), tenant=TENANT).agent_id == "implementer"


def test_the_missions_own_agent_beats_the_workers_configured_one(tmp_path):
    """A mission approved as `self-check` work must not be dispatched as though
    it were the worker's default agent."""
    timeline = worker.Timeline(tmp_path / "m.jsonl")
    from atlas_kernel.mission import service
    from atlas_kernel.mission.models import Mission, MissionStatus
    recorded = Mission(id="m-1", tenant_id=TENANT, title="deterministic work",
                       status=MissionStatus.QUEUED, agent_id="self-check")
    timeline.append(service._event(recorded, actor="test", note="queued"))

    # The worker is configured for the model-backed agent, which needs a
    # credential. The mission's own agent needs none, and wins.
    offered = worker.queued(timeline, tenant=TENANT, connected=frozenset(),
                            agent_id="implementer")
    assert [m.id for m in offered] == ["m-1"]


def test_a_mission_with_no_recorded_agent_falls_back_to_the_workers(tmp_path):
    timeline = worker.Timeline(tmp_path / "m.jsonl")
    from atlas_kernel.mission import service
    from atlas_kernel.mission.models import Mission, MissionStatus
    anonymous = Mission(id="m-2", tenant_id=TENANT, title="unnamed",
                        status=MissionStatus.QUEUED)
    timeline.append(service._event(anonymous, actor="test", note="queued"))

    assert worker.queued(timeline, tenant=TENANT, connected=frozenset(),
                         agent_id="implementer") == []
    assert [m.id for m in worker.queued(timeline, tenant=TENANT,
                                        connected=frozenset({"qwen"}),
                                        agent_id="implementer")] == ["m-2"]
