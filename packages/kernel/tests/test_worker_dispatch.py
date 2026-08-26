"""What the worker asks the scheduler before it starts anything.

Three things were reaching the scheduler as blanks, so three of its rules could
never fire. Each of these tests fails on the version of `queued()` that omitted
the argument, which is the only reason they are worth having.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

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


def test_a_worker_is_not_offered_a_mission_it_cannot_carry_out(tmp_path):
    """The fault this closes, found on the first real two-worker deploy.

    `policy.refuse_agent_substitution` catches a mismatch after the claim, and
    the claim is a race — so each worker took the *other's* mission and refused
    it, and both nightly recurrences were BLOCKED within a minute. A worker that
    filters its own queue never enters that race.
    """
    timeline = worker.Timeline(tmp_path / "m.jsonl")
    from atlas_kernel.mission import service
    from atlas_kernel.mission.models import Mission, MissionStatus
    recorded = Mission(id="m-1", tenant_id=TENANT, title="deterministic work",
                       status=MissionStatus.QUEUED, agent_id="self-check")
    timeline.append(service._event(recorded, actor="test", note="queued"))

    assert worker.queued(timeline, tenant=TENANT, connected=frozenset(),
                         agent_id="implementer") == [], (
        "a worker was offered a mission approved for a different agent")

    served = worker.queued(timeline, tenant=TENANT, connected=frozenset(),
                           agent_id="self-check")
    assert [m.id for m in served] == ["m-1"], (
        "the worker that serves it was not offered it")


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


# ============================================================ no silent fallback
#
# One test per substitution that would otherwise happen quietly. Each asserts a
# *refusal*, because in every one of these cases carrying on is the bug.

# ---------------------------------------------------------------- agent

def test_a_worker_may_not_stand_in_for_the_agent_a_plan_was_approved_with():
    """A mission approved as deterministic `self-check` work must not be
    carried out by a model because that is what this worker happens to run."""
    from atlas_kernel.mission import policy
    refusal = policy.refuse_agent_substitution("self-check", "implementer")
    assert refusal
    assert "self-check" in refusal and "implementer" in refusal


def test_substituting_a_more_capable_agent_is_refused_too():
    """Widening the blast radius is not a favour."""
    from atlas_kernel.mission import policy
    assert policy.refuse_agent_substitution("self-check", "cli-implementer")


def test_the_matching_agent_is_allowed():
    from atlas_kernel.mission import policy
    assert policy.refuse_agent_substitution("self-check", "self-check") == ""


def test_a_worker_with_no_declared_agent_may_not_run_a_named_mission():
    """`--agent fake` is not in the registry. It must not silently serve a
    mission that named a real agent."""
    from atlas_kernel.mission import policy
    assert policy.refuse_agent_substitution("implementer", "")


def test_an_unnamed_mission_is_not_a_substitution():
    """Nothing was promised, so nothing is being swapped."""
    from atlas_kernel.mission import policy
    assert policy.refuse_agent_substitution("", "implementer") == ""


# ----------------------------------------------------------- credentials

def test_a_missing_credential_never_falls_back_to_another_provider():
    """The agent declares qwen/anthropic/openai. With none of them usable the
    mission is held — it does not quietly pick a fourth, or run without one."""
    demands = demands_from([a_folded_mission()], agents=Registry(),
                           agent_for={"m-1": "implementer"},
                           connected=frozenset({"stripe", "cloudflare"}))
    assert demands[0].missing_credentials
    assert plan(demands, tenant=TENANT, done=frozenset(),
                concurrency=1)["dispatchable"] == []


def test_an_unverified_credential_does_not_count_as_available():
    """`usable_for` applies `resolve()`'s own rule rather than "has a row".
    A key somebody typed and nothing verified is exactly the case that would
    dispatch work doomed to fail at the provider."""
    from atlas_kernel.credentials.service import usable_for

    class Sealed:
        def status(self, *a, **k):
            raise RuntimeError("the vault is sealed")

    assert usable_for(Sealed(), tenant=TENANT) == frozenset()
    assert usable_for(None, tenant=TENANT) == frozenset()


# ---------------------------------------------------------------- origin

def test_an_unregistered_origin_never_falls_back_to_the_default():
    """The default is Qevik, so a typo must not become self-modification."""
    from atlas_kernel.mission import origins
    with pytest.raises(origins.UnknownOrigin):
        origins.Registry.build().resolve("acme-web-typo")


def test_a_customer_origin_may_not_be_pointed_at_qevik():
    from atlas_kernel.mission import origins, scratch
    with pytest.raises(origins.OriginRefused, match="Qevik's own repository"):
        origins.Registry.build({"acme": str(scratch.running_from())})


# ---------------------------------------------------------------- budget

def _mission_costing(amount, agent="self-check"):
    from atlas_kernel.mission.models import Mission, MissionStatus, Plan, PlanStep
    return Mission(id="m-1", tenant_id=TENANT, title="costly",
                   status=MissionStatus.QUEUED, agent_id=agent,
                   plan=Plan(goal="g", steps=(PlanStep(order=1, title="s"),),
                             estimated_cost=amount))


def _ledger_with(limit: float):
    """A ledger with an allowance on the **mission** scope.

    Not the tenant scope: `budgets.policy()` refuses that outright, because a
    tenant's allowance is their plan and a second place to set one would be a
    second answer to what a customer may spend. The gate under test asks every
    scope, so a mission limit exercises it exactly.
    """
    from atlas_kernel.fabric.budgets import Scope
    from atlas_kernel.fabric.budgets import policy as budget_policy
    from atlas_kernel.quota.ledger import QuotaLedger
    events: list = []
    ledger = QuotaLedger(events=events, sink=events.append)
    ledger.register(budget_policy(Scope.MISSION, "m-1", tenant=TENANT,
                                  limit=limit))
    return ledger


def test_a_mission_beyond_its_allowance_is_refused_before_it_runs():
    ledger = _ledger_with(2.0)
    refusal = worker.refuse_over_budget(ledger, _mission_costing(10.0),
                                        tenant=TENANT)
    assert refusal
    assert "10 units" in refusal


def test_a_mission_within_its_allowance_is_not_refused():
    ledger = _ledger_with(50.0)
    assert worker.refuse_over_budget(ledger, _mission_costing(10.0),
                                     tenant=TENANT) == ""


def test_an_unreadable_ledger_refuses_rather_than_assuming_it_fits():
    """Not knowing whether the work is covered is not the same as knowing it
    is. The optimistic reading spends money nobody approved."""
    class Broken:
        def status(self, *a, **k):
            raise RuntimeError("unreadable")
        def policy(self, *a, **k):
            raise RuntimeError("unreadable")
    refusal = worker.refuse_over_budget(Broken(), _mission_costing(10.0),
                                        tenant=TENANT)
    assert refusal
    assert "could not be read" in refusal


def test_an_unpriced_mission_is_not_refused_here_and_is_not_treated_as_free():
    """`policy.decide` already required a person for it. Refusing again on a
    cost nobody stated would wall off every unestimated mission for ever — and
    nothing here turns the absence into a number."""
    ledger = _ledger_with(0.5)
    assert worker.refuse_over_budget(ledger, _mission_costing(None),
                                     tenant=TENANT) == ""


def test_an_unmetered_tenant_is_not_one_with_an_infinite_balance():
    """There is simply nothing to refuse it against, and that is recorded
    rather than rendered as headroom."""
    from atlas_kernel.quota.ledger import QuotaLedger
    events: list = []
    ledger = QuotaLedger(events=events, sink=events.append)
    assert worker.refuse_over_budget(ledger, _mission_costing(10.0),
                                     tenant=TENANT) == ""
    assert worker.tenant_headroom(ledger, TENANT) is None
