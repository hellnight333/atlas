"""Budgets at four scopes, on the one ledger that already exists.

`QuotaLedger` already does the hard part: reserve before acting, refuse rather
than fail, windows computed from timestamped entries so a restart does not
forget, and a `plan()` that says *why* it is not more instead of quietly
returning zero. None of that is rebuilt here.

What was missing is scope. A tenant allowance alone cannot stop one runaway
conversation from spending a month of it in an afternoon, and a conversation
allowance alone is theatre if nothing checks the mission it belongs to.

## Every enclosing scope must afford it

    TENANT   ⊃   MISSION   ⊃   AGENT   ⊃   CONVERSATION

A spend is checked against **all** of them and then committed to **all** of
them. Checking only the tightest is the bug that lets a hundred conversations,
each within its own small budget, empty the tenant's. Checking only the widest
is the bug that lets one of them do it alone.

Check-all-then-commit-all, in that order. Committing as it goes would leave the
tenant charged for a spend the conversation refused — a partially applied spend
is worse than a refusal because it is invisible.

## An unmetered scope is skipped; an unmetered tenant is not

No policy for a mission means nobody set that mission a budget, which is
ordinary. No policy for the tenant means the customer is not on a plan, and
treating that as "unlimited" is how the first month's bill arrives. `reserve()`
refuses, and `Unmetered` says which scope was missing rather than reading as
"you are out of money".

## The tenant scope is the credits resource, not a new one

`credits` already owns "what may this customer spend" — a plan, registered on
the same ledger by `CreditService.assign()`. `Scope.TENANT` resolves to exactly
that resource, and `policy()` refuses to define one. A parallel
`budget.<tenant>` would be a second answer, and the wrong one is always the one
the operator is not looking at.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from ..credits.models import resource_for as credit_resource
from ..opportunity.tenancy import TenantId
from ..opportunity.tenancy import require as _require_tenant
from ..quota.ledger import QuotaLedger
from ..quota.models import LimitKind, QuotaExhausted, QuotaPolicy, QuotaWindow


class Scope(StrEnum):
    """Widest to tightest. The order is the containment order."""

    TENANT = "tenant"
    MISSION = "mission"
    AGENT = "agent"
    CONVERSATION = "conversation"


#: Widest first, so a refusal can name the widest scope that failed — "the
#: tenant is out" and "this conversation is out" call for different actions.
ORDER: tuple[Scope, ...] = (Scope.TENANT, Scope.MISSION, Scope.AGENT,
                            Scope.CONVERSATION)

#: What may appear in a resource name. A key with a dot in it would collide with
#: the separator and quietly merge two allowances into one.
_SAFE = re.compile(r"[^a-zA-Z0-9_-]+")


class Unmetered(RuntimeError):
    """Nobody set a budget for the scope that requires one.

    Not `QuotaExhausted`. "You have no allowance configured" and "your allowance
    is gone" have opposite remedies, and a caller that cannot tell them apart
    will wait for a window that is never going to reset.
    """

    def __init__(self, scope: Scope, resource: str) -> None:
        self.scope, self.resource = scope, resource
        super().__init__(
            f"no budget is configured for {resource!r}. Nothing was spent. "
            "An unmetered allowance is not an unlimited one — set a policy "
            f"for this {scope.value} before work runs against it.")


def resource_for(scope: Scope, key: str, *, tenant: TenantId | None) -> str:
    """The ledger resource name for one scope.

    **The tenant scope is the credits resource**, delegated to `credits.models`
    rather than restated. A tenant's allowance is their plan — that is already
    decided, registered by `CreditService.assign()` and drawn down by every
    capability. A second `budget.<tenant>` beside it would be a competing answer
    to "what may this customer spend", and the wrong one is always whichever the
    operator is not looking at.

    Inner scopes are tenant-prefixed too. `mission-1` is not globally unique, so
    without the prefix two tenants would draw down one allowance — a cross-tenant
    leak in the one place nobody would look for it.
    """
    tenant = _require_tenant(tenant, method="budgets.resource_for")
    if scope is Scope.TENANT:
        return credit_resource(str(tenant))
    slug = _SAFE.sub("-", str(tenant)).strip("-")
    inner = _SAFE.sub("-", key).strip("-")
    if not inner:
        raise ValueError(
            f"a {scope.value} budget needs a key naming what it belongs to; an "
            "empty one would put every mission on the same allowance")
    return f"budget.{slug}.{scope.value}.{inner}"


def policy(scope: Scope, key: str, *, tenant: TenantId | None, limit: float,
           window: QuotaWindow = QuotaWindow.MONTHLY,
           kind: LimitKind = LimitKind.SPEND, floor: float = 0.0
           ) -> QuotaPolicy:
    """An allowance for one inner scope, ready to register on the ledger.

    Refuses the tenant scope. A tenant's allowance comes from their plan, and
    setting one here would be a second place deciding what a customer may spend
    — which is the drift this module exists to avoid, not to introduce.

    Defaults to a monthly *spend* limit because that is what an agent budget is:
    money, and money can be raised by deciding to. A platform limit cannot, and
    saying so is what stops a caller trying to buy its way out of one.
    """
    if scope is Scope.TENANT:
        raise ValueError(
            "a tenant's allowance is their plan. Register it with "
            "CreditService.assign(); a second policy here would be a second "
            "answer to what this customer may spend")
    return QuotaPolicy(resource=resource_for(scope, key, tenant=tenant),
                       limit=limit, window=window, kind=kind, floor=floor)


class Envelope(BaseModel):
    """The scopes one piece of work sits inside.

    A mission's work names its mission; a conversation names its mission, the
    agent speaking and itself. Whatever is named is checked — and nothing that
    is not named can be checked, which is why the constructor takes the keys
    rather than discovering them.
    """

    model_config = ConfigDict(frozen=True)

    tenant_id: str
    mission_id: str = ""
    agent_id: str = ""
    conversation_id: str = ""

    def keys(self) -> tuple[tuple[Scope, str], ...]:
        named = {Scope.TENANT: self.tenant_id, Scope.MISSION: self.mission_id,
                 Scope.AGENT: self.agent_id,
                 Scope.CONVERSATION: self.conversation_id}
        return tuple((scope, named[scope]) for scope in ORDER if named[scope])

    def resources(self) -> tuple[tuple[Scope, str], ...]:
        return tuple((scope, resource_for(scope, key, tenant=self.tenant_id))
                     for scope, key in self.keys())


class Assessment(BaseModel):
    """What every scope had to say, before anything was spent."""

    model_config = ConfigDict(frozen=True)

    amount: float
    affordable: bool
    #: The widest scope that refused, or `None`. Widest because "the tenant is
    #: out of money" and "this conversation is out" need different actions.
    refused_by: Scope | None = None
    reason: str = ""
    #: Scopes with no policy. Skipped, and named so the gap is visible rather
    #: than being mistaken for headroom.
    unmetered: tuple[Scope, ...] = ()
    #: What each metered scope has left, tightest constraint first.
    remaining: dict[str, float] = {}

    @property
    def headroom(self) -> float | None:
        """The least any scope can still afford. `None` when nothing is metered
        — which is UNKNOWN, and must never be read as plenty."""
        return min(self.remaining.values()) if self.remaining else None


def assess(ledger: QuotaLedger, envelope: Envelope, amount: float, *,
           essential: bool = False) -> Assessment:
    """Ask every scope, spend nothing.

    Separate from `reserve()` so the scheduler can decline to start work it
    cannot finish without that question itself costing an allowance.
    """
    if amount < 0:
        raise ValueError("a spend cannot be negative")

    unmetered: list[Scope] = []
    remaining: dict[str, float] = {}
    refused: Scope | None = None
    reason = ""

    for scope, resource in envelope.resources():
        try:
            left = ledger.remaining(resource, essential=essential)
        except KeyError:
            unmetered.append(scope)
            continue
        remaining[scope.value] = left
        if amount > left and refused is None:
            kind = ledger.policy(resource).kind
            remedy = ("raise the ceiling if the work is worth it"
                      if kind is LimitKind.SPEND
                      else "this one is not for sale; wait for the window")
            reason = (f"this {scope.value}'s budget has {left:g} left and the "
                      f"work needs {amount:g} — {remedy}")
            refused = scope

    return Assessment(amount=amount, affordable=refused is None,
                      refused_by=refused, reason=reason,
                      unmetered=tuple(unmetered), remaining=remaining)


def reserve(ledger: QuotaLedger, envelope: Envelope, amount: float, *,
            essential: bool = False, note: str = "") -> Assessment:
    """Charge every scope, or none of them.

    Checks all before committing any. Committing scope by scope would leave the
    tenant charged for work the conversation refused, and that overcharge is
    invisible — nothing downstream ever learns the spend did not happen.
    """
    tenant_resource = resource_for(Scope.TENANT, envelope.tenant_id,
                                   tenant=envelope.tenant_id)
    verdict = assess(ledger, envelope, amount, essential=essential)
    if Scope.TENANT in verdict.unmetered:
        raise Unmetered(Scope.TENANT, tenant_resource)  # not on a plan
    if not verdict.affordable:
        scope = verdict.refused_by or Scope.TENANT
        resource = dict(envelope.resources())[scope]
        raise QuotaExhausted(resource, ledger.policy(resource).kind,
                             verdict.remaining.get(scope.value, 0.0), amount)

    for scope, resource in envelope.resources():
        if scope in verdict.unmetered:
            continue
        ledger.spend(resource, amount, essential=essential,
                     note=note or f"{scope.value} {envelope.tenant_id}")
    return verdict
