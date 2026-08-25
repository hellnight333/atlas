"""Policy above the planner, tested on the plan that authorised itself.

`attach_plan` routed on `Plan.approval_required` — a field set by whatever
produced the plan. `FakeCodingAgent` sets it to `False`, so its plans went
straight to QUEUED with no approval at all, and an LLM emitting the same value
would have been obeyed identically.

That is the model authorising its own work, and it is the one thing the
architecture exists to prevent. The tests below are written against that
specific plan, not against a happy path that would pass in the broken version
too.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from atlas_kernel.fabric.agents import Blast, Registry
from atlas_kernel.mission import service
from atlas_kernel.mission.models import Mission, MissionStatus, Plan, PlanStep
from atlas_kernel.mission.policy import (
    COSTLY_UNITS,
    SAFE_PREFIXES,
    Requirement,
    decide,
    describe,
)

TENANT = "tenant-a"


def _plan(**over) -> Plan:
    base = {"goal": "do the thing", "approval_required": False,
            "estimated_cost": 1.0,
            "steps": (PlanStep(order=1, title="write", files=("docs/note.md",)),)}
    return Plan(**{**base, **over})


# ============================================ the plan that authorised itself

def test_a_planner_saying_no_approval_needed_is_not_obeyed() -> None:
    """The exact shape `FakeCodingAgent` produces: `approval_required=False`
    with a plan that edits source. It reached QUEUED with nobody asked."""
    verdict = decide(_plan(steps=(PlanStep(order=1, title="edit",
                                           files=("packages/kernel/x.py",)),)),
                     agent_id="implementer")
    assert verdict.needs_a_person is True
    assert verdict.requirement is Requirement.EXECUTION


def test_the_mission_lands_in_awaiting_approval_not_queued() -> None:
    """The end the defect had: a self-authorised plan reaching a runnable
    queue. Driven through the real service, not through `decide` alone."""
    mission = Mission(id="m1", tenant_id=TENANT, title="t",
                      status=MissionStatus.PLANNING)
    attached, _ = service.attach_plan(
        mission,
        _plan(steps=(PlanStep(order=1, title="edit",
                              files=("packages/kernel/x.py",)),)),
        tenant=TENANT, agent_id="implementer")
    assert attached.status is MissionStatus.AWAITING_APPROVAL


def test_the_transition_records_which_rule_decided() -> None:
    """"Why did this need a person" must have an answer that is not "policy"."""
    mission = Mission(id="m1", tenant_id=TENANT, title="t",
                      status=MissionStatus.PLANNING)
    _, event = service.attach_plan(
        mission, _plan(estimated_cost=None), tenant=TENANT,
        agent_id="implementer")
    assert "policy:" in event.detail["note"]
    assert "unpriced" in event.detail["note"]


def test_approving_in_chat_still_works_when_policy_already_queued_it() -> None:
    """`chat.approve` transitioned to QUEUED unconditionally after attaching
    the plan. That was safe only because `attach_plan` always routed to
    AWAITING_APPROVAL — the planner's flag was always True for a real plan.

    Policy can now clear a cheap reversible plan straight to QUEUED, and
    `ALLOWED` refuses QUEUED → QUEUED, so the unconditional transition would
    have failed the approval a person had just given.
    """
    from atlas_kernel.chat import service as chat

    conversation, opened = chat.start(tenant=TENANT, text="Write a doc note.",
                                      started_by="ayoub")
    conversation, _ = chat.plan_for(conversation, _plan(), tenant=TENANT)
    conversation, mission, _ = chat.approve(conversation, tenant=TENANT,
                                            approved_by="ayoub")
    assert mission.status is MissionStatus.QUEUED
    assert opened is not None


def test_and_when_policy_holds_it_the_person_still_queues_it() -> None:
    """The negative control on the branch above: the other path must also
    reach QUEUED, or approving would silently do nothing."""
    from atlas_kernel.chat import service as chat

    conversation, _ = chat.start(tenant=TENANT, text="Edit the kernel.",
                                 started_by="ayoub")
    needs_review = _plan(steps=(PlanStep(order=1, title="edit",
                                         files=("packages/kernel/x.py",)),))
    conversation, _ = chat.plan_for(conversation, needs_review, tenant=TENANT)
    _, mission, _ = chat.approve(conversation, tenant=TENANT,
                                 approved_by="ayoub")
    assert mission.status is MissionStatus.QUEUED


# ============================================ the planner may only raise it

def test_a_planner_asking_for_review_gets_review() -> None:
    """More cautious than the rule is allowed."""
    verdict = decide(_plan(approval_required=True), agent_id="implementer")
    assert verdict.needs_a_person is True
    assert verdict.planner_raised_it is True
    assert "asked for review anyway" in verdict.because


def test_and_that_is_visible_rather_than_indistinguishable() -> None:
    """A planner that always asks should be noticeable, not silently identical
    to policy requiring it."""
    by_policy = decide(_plan(estimated_cost=None), agent_id="implementer")
    by_planner = decide(_plan(approval_required=True), agent_id="implementer")
    assert by_policy.planner_raised_it is False
    assert by_planner.planner_raised_it is True


def test_the_same_plan_without_the_request_is_cleared() -> None:
    """The negative control. If everything needed approval the tests above
    would pass against a policy that is simply always yes."""
    assert decide(_plan(), agent_id="implementer").requirement is Requirement.NONE


# ============================================ deny by default

def test_an_unnamed_agent_needs_approval() -> None:
    """Work whose performer is unknown has an unknown blast radius, and an
    unknown blast radius is the one thing approval cannot work around."""
    verdict = decide(_plan(), agent_id="")
    assert verdict.requirement is Requirement.EXECUTION
    assert "blast radius is unknown" in verdict.because


def test_an_agent_nobody_declared_is_treated_as_the_worst_case() -> None:
    """Not the best case. The registry is the record of what an agent may do."""
    assert decide(_plan(), agent_id="not-in-the-registry"
                  ).requirement is Requirement.ARTEFACT


def test_an_unpriced_plan_needs_approval_on_a_metered_tenant() -> None:
    """The same rule the scheduler applies: an unpriced call is not a free
    one."""
    assert decide(_plan(estimated_cost=None), agent_id="implementer"
                  ).requirement is Requirement.EXECUTION


def test_an_unpriced_plan_is_ordinary_where_nothing_is_metered() -> None:
    """A self-hosted deployment with no plan configured must still work."""
    assert decide(_plan(estimated_cost=None), agent_id="implementer",
                  tenant_is_metered=False).requirement is Requirement.NONE


def test_expensive_work_needs_approval() -> None:
    verdict = decide(_plan(estimated_cost=COSTLY_UNITS + 1),
                     agent_id="implementer")
    assert verdict.requirement is Requirement.EXECUTION
    assert str(int(COSTLY_UNITS)) in verdict.because


def test_writing_outside_the_reviewed_free_paths_needs_approval() -> None:
    verdict = decide(_plan(steps=(PlanStep(order=1, title="edit",
                                           files=("infra/deploy.sh",)),)),
                     agent_id="implementer")
    assert verdict.requirement is Requirement.EXECUTION
    assert "infra/deploy.sh" in verdict.because


@pytest.mark.parametrize("prefix", SAFE_PREFIXES)
def test_the_reviewed_free_paths_really_are_free(prefix: str) -> None:
    """Each one, individually. A list where only the first entry works would
    pass a test that checked the list as a whole."""
    assert decide(_plan(steps=(PlanStep(order=1, title="write",
                                        files=(f"{prefix}thing.md",)),)),
                  agent_id="implementer").requirement is Requirement.NONE


# ============================================ two approvals, not one boolean

def test_irreversible_work_needs_the_artefact_not_the_intention() -> None:
    """"Somebody agreed this work should happen" is not "somebody agreed to
    this exact output going live". Collapsing them turns an execution approval
    into permission to publish."""
    verdict = decide(_plan(), agent_id="correspondent")
    assert verdict.requirement is Requirement.ARTEFACT
    assert Registry().get("correspondent").blast is Blast.IRREVERSIBLE


def test_irreversible_beats_every_cheaper_rule() -> None:
    """An email cannot be unsent however cheap it was, and it writes no files
    at all — so neither the cost rule nor the path rule may clear it."""
    cheap = _plan(estimated_cost=0.0, steps=(PlanStep(order=1, title="draft",
                                                      files=("docs/a.md",)),))
    assert decide(cheap, agent_id="correspondent"
                  ).requirement is Requirement.ARTEFACT


def test_costly_work_needs_execution_approval() -> None:
    assert decide(_plan(), agent_id="image-maker"
                  ).requirement is Requirement.EXECUTION


def test_the_three_requirements_are_distinct() -> None:
    assert len({r.value for r in Requirement}) == 3


# ============================================ deterministic, and above the model

def test_policy_consults_no_model_and_nothing_outside_itself() -> None:
    """Read from the source. A policy that asked a model what it should allow
    would be the same defect wearing a different hat."""
    from atlas_kernel.mission import policy as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add((node.module or "").split(".")[0])
    forbidden = names & {"httpx", "requests", "openai", "anthropic",
                         "subprocess", "random", "time"}
    assert forbidden == set(), f"policy reaches for {forbidden}"


def test_the_same_inputs_always_give_the_same_verdict() -> None:
    """What makes "the model proposed X and policy allowed it" checkable."""
    plan = _plan(estimated_cost=None)
    first = decide(plan, agent_id="implementer")
    for _ in range(20):
        assert decide(plan, agent_id="implementer") == first


def test_attach_plan_no_longer_reads_the_planners_flag_to_route() -> None:
    """The field still exists — a planner may raise the bar with it — but it
    must not be what chooses the destination."""
    source = Path(service.__file__).read_text(encoding="utf-8")
    body = source[source.index("def attach_plan("):source.index("def claim(")]
    assert "policy.decide" in body
    assert "if plan.approval_required" not in body


def test_the_rules_can_be_read_by_a_person() -> None:
    stated = describe()
    assert len(stated["rules"]) >= 5
    assert "Deny by default" in stated["note"]
    assert stated["reviewed_free_paths"] == list(SAFE_PREFIXES)
