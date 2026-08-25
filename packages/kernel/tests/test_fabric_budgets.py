"""Budgets at four scopes, tested on the ways a limit stops limiting.

Three failures, each of which passes a happy-path suite.

Checking only the tightest scope lets a hundred conversations, each within its
own small budget, empty the tenant's. Checking only the widest lets one of them
do it alone. And committing scope by scope leaves the tenant charged for a spend
the conversation refused — an overcharge nothing downstream ever learns about.

The fourth is quieter: treating "no policy configured" as "no limit". That one
is only discovered when the bill arrives.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from atlas_kernel.credits.models import resource_for as credit_resource
from atlas_kernel.fabric.budgets import (
    Envelope,
    Scope,
    Unmetered,
    assess,
    policy,
    reserve,
    resource_for,
)
from atlas_kernel.quota.ledger import QuotaLedger
from atlas_kernel.quota.models import (
    LimitKind,
    QuotaExhausted,
    QuotaPolicy,
    QuotaWindow,
)

T = "tenant-a"


@pytest.fixture
def ledger() -> QuotaLedger:
    return QuotaLedger()


def _meter(ledger: QuotaLedger, scope: Scope, key: str, limit: float, *,
           tenant: str = T, kind: LimitKind = LimitKind.SPEND) -> None:
    """Register one allowance.

    The tenant's goes through `credits`, because that is where a customer's
    allowance is decided — registering it any other way here would test a
    parallel budget this module deliberately does not have.
    """
    if scope is Scope.TENANT:
        ledger.register(QuotaPolicy(resource=credit_resource(tenant),
                                    limit=limit, kind=kind,
                                    window=QuotaWindow.MONTHLY))
        return
    ledger.register(policy(scope, key, tenant=tenant, limit=limit, kind=kind))


def _envelope(**over: str) -> Envelope:
    return Envelope(**{"tenant_id": T, "mission_id": "m1", "agent_id": "planner",
                       "conversation_id": "c1", **over})


# ============================================ every enclosing scope

def test_a_conversation_within_its_own_budget_is_refused_by_the_tenants(
        ledger) -> None:
    """The failure that a per-conversation limit alone cannot catch: a hundred
    small conversations emptying one big allowance."""
    _meter(ledger, Scope.TENANT, T, 5.0)
    _meter(ledger, Scope.CONVERSATION, "c1", 1000.0)
    with pytest.raises(QuotaExhausted):
        reserve(ledger, _envelope(), 10.0)


def test_a_tenant_with_plenty_is_still_stopped_by_one_conversation(ledger
                                                                   ) -> None:
    """The other direction. A tenant limit alone cannot stop one runaway."""
    _meter(ledger, Scope.TENANT, T, 1000.0)
    _meter(ledger, Scope.CONVERSATION, "c1", 5.0)
    with pytest.raises(QuotaExhausted):
        reserve(ledger, _envelope(), 10.0)


def test_work_inside_every_budget_goes_through(ledger) -> None:
    """The negative control. If either test above passed against a version that
    refuses everything, neither would mean anything."""
    _meter(ledger, Scope.TENANT, T, 1000.0)
    _meter(ledger, Scope.CONVERSATION, "c1", 100.0)
    verdict = reserve(ledger, _envelope(), 10.0)
    assert verdict.affordable
    assert verdict.remaining["tenant"] == 1000.0


def test_a_spend_is_charged_to_every_scope_not_just_one(ledger) -> None:
    _meter(ledger, Scope.TENANT, T, 100.0)
    _meter(ledger, Scope.MISSION, "m1", 100.0)
    _meter(ledger, Scope.AGENT, "planner", 100.0)
    _meter(ledger, Scope.CONVERSATION, "c1", 100.0)
    reserve(ledger, _envelope(), 40.0)
    after = assess(ledger, _envelope(), 0.0)
    assert set(after.remaining.values()) == {60.0}, after.remaining


def test_agent_and_mission_budgets_are_separate_allowances(ledger) -> None:
    """Two missions run by the same agent draw down that agent's budget
    together, and their own budgets apart."""
    _meter(ledger, Scope.TENANT, T, 1000.0)
    _meter(ledger, Scope.AGENT, "planner", 15.0)
    _meter(ledger, Scope.MISSION, "m1", 100.0)
    _meter(ledger, Scope.MISSION, "m2", 100.0)
    reserve(ledger, _envelope(mission_id="m1", conversation_id=""), 10.0)
    with pytest.raises(QuotaExhausted):
        reserve(ledger, _envelope(mission_id="m2", conversation_id=""), 10.0)


# ============================================ all-or-nothing

def test_a_refused_spend_charges_nothing_anywhere(ledger) -> None:
    """Committing scope by scope leaves the tenant charged for work the
    conversation refused, and that overcharge is invisible."""
    _meter(ledger, Scope.TENANT, T, 1000.0)
    _meter(ledger, Scope.CONVERSATION, "c1", 5.0)
    before = assess(ledger, _envelope(), 0.0).remaining
    with pytest.raises(QuotaExhausted):
        reserve(ledger, _envelope(), 10.0)
    assert assess(ledger, _envelope(), 0.0).remaining == before


def test_asking_costs_nothing(ledger) -> None:
    """`assess` exists so the scheduler can decline to start work it cannot
    finish, without that question itself consuming the allowance."""
    _meter(ledger, Scope.TENANT, T, 100.0)
    for _ in range(50):
        assess(ledger, _envelope(), 10.0)
    assert assess(ledger, _envelope(), 0.0).remaining["tenant"] == 100.0


# ============================================ unmetered is not unlimited

def test_a_tenant_with_no_budget_refuses_rather_than_spending_freely(ledger
                                                                     ) -> None:
    """Treating "nobody set a budget" as "no limit" is how the first month's
    bill arrives."""
    _meter(ledger, Scope.CONVERSATION, "c1", 1000.0)
    with pytest.raises(Unmetered) as raised:
        reserve(ledger, _envelope(), 1.0)
    assert raised.value.scope is Scope.TENANT
    assert "not an unlimited one" in str(raised.value)


def test_an_unmetered_tenant_spends_nothing_on_the_way_out(ledger) -> None:
    """The refusal must not have already charged the scopes that did have
    policies."""
    _meter(ledger, Scope.CONVERSATION, "c1", 1000.0)
    with pytest.raises(Unmetered):
        reserve(ledger, _envelope(), 1.0)
    assert assess(ledger, _envelope(), 0.0).remaining["conversation"] == 1000.0


def test_unmetered_is_not_the_same_error_as_exhausted(ledger) -> None:
    """"You have no allowance configured" and "your allowance is gone" have
    opposite remedies, and a caller that confuses them waits for a window that
    is never going to reset."""
    assert not issubclass(Unmetered, QuotaExhausted)
    assert not issubclass(QuotaExhausted, Unmetered)


def test_a_mission_with_no_budget_of_its_own_is_ordinary(ledger) -> None:
    """Not every mission gets its own allowance. The tenant's still applies."""
    _meter(ledger, Scope.TENANT, T, 100.0)
    verdict = reserve(ledger, _envelope(), 10.0)
    assert verdict.affordable
    assert Scope.MISSION in verdict.unmetered


def test_an_unmetered_scope_is_named_rather_than_mistaken_for_headroom(ledger
                                                                       ) -> None:
    _meter(ledger, Scope.TENANT, T, 100.0)
    verdict = assess(ledger, _envelope(), 1.0)
    assert set(verdict.unmetered) == {Scope.MISSION, Scope.AGENT,
                                      Scope.CONVERSATION}


def test_headroom_is_unknown_rather_than_plenty_when_nothing_is_metered(ledger
                                                                        ) -> None:
    """`None`, never a large number. UNKNOWN read as plenty is the same bug as
    UNKNOWN cost read as zero."""
    verdict = assess(ledger, _envelope(), 1.0)
    assert verdict.headroom is None


def test_headroom_is_the_tightest_scope(ledger) -> None:
    _meter(ledger, Scope.TENANT, T, 1000.0)
    _meter(ledger, Scope.CONVERSATION, "c1", 7.0)
    assert assess(ledger, _envelope(), 1.0).headroom == 7.0


# ============================================ the refusal is actionable

def test_the_refusal_names_the_scope_that_ran_out(ledger) -> None:
    """"The tenant is out of money" and "this conversation is out" call for
    different actions."""
    _meter(ledger, Scope.TENANT, T, 1000.0)
    _meter(ledger, Scope.CONVERSATION, "c1", 5.0)
    verdict = assess(ledger, _envelope(), 10.0)
    assert verdict.refused_by is Scope.CONVERSATION
    assert "conversation's budget" in verdict.reason


def test_the_widest_scope_that_refused_is_the_one_reported(ledger) -> None:
    """When the tenant is out, saying "this conversation is out" would send
    somebody to raise a limit that was never the problem."""
    _meter(ledger, Scope.TENANT, T, 5.0)
    _meter(ledger, Scope.CONVERSATION, "c1", 5.0)
    assert assess(ledger, _envelope(), 10.0).refused_by is Scope.TENANT


def test_a_platform_limit_is_not_offered_as_something_to_buy(ledger) -> None:
    """A caller told to "raise the ceiling" on a platform limit will try, and
    the limit is not for sale."""
    _meter(ledger, Scope.TENANT, T, 5.0, kind=LimitKind.PLATFORM)
    verdict = assess(ledger, _envelope(), 10.0)
    assert "not for sale" in verdict.reason
    assert "raise the ceiling" not in verdict.reason


def test_a_spend_limit_says_it_can_be_raised(ledger) -> None:
    """The negative control on the line above."""
    _meter(ledger, Scope.TENANT, T, 5.0, kind=LimitKind.SPEND)
    assert "raise the ceiling" in assess(ledger, _envelope(), 10.0).reason


# ============================================ tenants never share an allowance

def test_two_tenants_with_the_same_mission_id_have_separate_budgets() -> None:
    """`mission-1` is not globally unique. Without the tenant prefix these two
    would draw down one allowance — a cross-tenant leak in the one place
    nobody would look for it."""
    mine = resource_for(Scope.MISSION, "mission-1", tenant=T)
    theirs = resource_for(Scope.MISSION, "mission-1", tenant="tenant-b")
    assert mine != theirs


def test_the_tenant_scope_is_the_credits_resource_not_a_second_one() -> None:
    """`credits` already owns "what may this customer spend", registered on this
    same ledger by their plan. A parallel `budget.<tenant>` would be a second
    answer, and the wrong one is always whichever the operator is not looking
    at."""
    assert resource_for(Scope.TENANT, "ignored", tenant=T) == credit_resource(T)
    assert resource_for(Scope.TENANT, "x", tenant="tenant-b") != resource_for(
        Scope.TENANT, "x", tenant=T)


def test_a_tenant_allowance_cannot_be_defined_here() -> None:
    """Setting one would be a second place deciding a customer's spend — the
    drift this module exists to avoid, not to introduce."""
    with pytest.raises(ValueError, match="their plan"):
        policy(Scope.TENANT, T, tenant=T, limit=100.0)


def test_a_tenants_plan_is_the_budget_the_fabric_draws_down() -> None:
    """End to end through the real service: assigning a plan is what makes the
    fabric's tenant scope metered."""
    from atlas_kernel.credits.models import Plan
    from atlas_kernel.credits.service import CreditService

    ledger = QuotaLedger()
    CreditService(ledger).assign(T, Plan.LIST)
    verdict = assess(ledger, _envelope(), 1.0)
    assert Scope.TENANT not in verdict.unmetered
    assert verdict.remaining["tenant"] > 0


def test_a_key_cannot_smuggle_a_separator_into_the_resource_name() -> None:
    """A dotted key would merge two allowances into one, and the merge is
    silent."""
    sneaky = resource_for(Scope.MISSION, "m1.conversation.c1", tenant=T)
    honest = resource_for(Scope.CONVERSATION, "c1", tenant=T)
    assert sneaky != honest
    assert sneaky.count(".") == honest.count(".")


def test_an_empty_key_is_refused_rather_than_pooling_every_mission() -> None:
    with pytest.raises(ValueError, match="needs a key"):
        resource_for(Scope.MISSION, "   ", tenant=T)


def test_a_budget_without_a_tenant_is_refused_rather_than_defaulted() -> None:
    from atlas_kernel.opportunity.tenancy import TenantRequired

    with pytest.raises(TenantRequired):
        resource_for(Scope.MISSION, "m1", tenant=None)


# ============================================ one ledger, not two

def test_the_budget_layer_does_not_reimplement_the_ledger() -> None:
    """Window arithmetic in two places is two answers to "what is left", and
    the wrong one is whichever the operator is not looking at."""
    from atlas_kernel.fabric import budgets as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert {"remaining", "spend", "policy"} <= called, (
        "the budget layer must go through the ledger rather than around it")
    for arithmetic in ("timedelta", "window_start", "window_end", "_spends"):
        assert arithmetic not in source, (
            f"{arithmetic} is the ledger's job; a second copy of it drifts")


def test_a_negative_spend_is_refused(ledger) -> None:
    _meter(ledger, Scope.TENANT, T, 100.0)
    with pytest.raises(ValueError, match="cannot be negative"):
        assess(ledger, _envelope(), -5.0)


def test_the_default_budget_is_money_and_monthly() -> None:
    """An agent budget is money, and money can be raised by deciding to. A
    platform limit cannot, and defaulting to it would misdescribe every one of
    these."""
    made = policy(Scope.AGENT, "planner", tenant=T, limit=50.0)
    assert made.kind is LimitKind.SPEND
    assert made.window is QuotaWindow.MONTHLY
