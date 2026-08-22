"""Plans, and the units a plan includes.

Credits here are an **allowance**, not money. Nothing in this package prices
anything, charges anything or talks to a payment provider — P1.7's own brief
says no billing-provider connection until explicitly authorised, and the useful
half of the feature is the half that works without one: a customer on the List
plan cannot consume Enterprise amounts of work, and a job cannot start unless
the allowance for it was set aside first.

Two things are deliberately *not* here:

**No second registry of what work costs.** `CapabilityOffer.estimated_units`
already declares it, and the offer id is the action key. A separate price list
would be a second answer to the same question and would drift.

**No second ledger.** `quota.QuotaLedger` is the authoritative record of what
was consumed. A reservation is an *intent* that has not consumed anything yet,
so it is held here until it settles — at which point the spend goes through the
ledger like every other spend in the system.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ..quota.models import LimitKind, QuotaPolicy, QuotaWindow


class Plan(StrEnum):
    """What a customer is on. The names the commercial documents use."""

    LIST = "LIST"
    PRO = "PRO"
    ADVANCED = "ADVANCED"
    ENTERPRISE = "ENTERPRISE"


#: Units included per month, per plan. A unit is whatever a capability declares
#: through `estimated_units`, so the numbers are comparable across capabilities
#: by construction rather than by a conversion table somebody maintains.
#:
#: LIST is deliberately small and non-zero: it has to be able to run something,
#: or the free tier is a landing page rather than a plan.
INCLUDED: dict[Plan, float] = {
    Plan.LIST: 40.0,
    Plan.PRO: 200.0,
    Plan.ADVANCED: 600.0,
    Plan.ENTERPRISE: 2_400.0,
}

#: Held back from ordinary work so an approved publication is never blocked by
#: a month of generation. Essential work may use it; nothing else sees it.
ESSENTIAL_FLOOR: dict[Plan, float] = {
    Plan.LIST: 0.0,
    Plan.PRO: 20.0,
    Plan.ADVANCED: 60.0,
    Plan.ENTERPRISE: 240.0,
}


class NoPlan(Exception):
    """This tenant has no plan, so there is no allowance to draw on.

    Refused rather than defaulted to the smallest plan: a tenant nobody has put
    on a plan is a provisioning gap, and quietly granting them the free tier
    hides it until somebody wonders why the numbers do not add up.
    """


class NotReserved(Exception):
    """Work was settled or released against a reservation that does not exist."""


class ReservationState(StrEnum):
    HELD = "held"
    #: The work happened. The units went through the ledger.
    SETTLED = "settled"
    #: The work did not happen. Nothing was consumed.
    RELEASED = "released"


class Reservation(BaseModel):
    """Units set aside before the work starts.

    Reserve-before-act exists because discovering the limit afterwards means the
    job already ran: the provider was called, the artefact exists, and nobody
    can say whether it counted. Asking first turns an overrun into a decision.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    tenant_id: str
    #: The offer being paid for. The same id the registries use.
    action: str
    units: float = Field(ge=0)
    state: ReservationState = ReservationState.HELD
    #: The job it was taken for, once one exists. Empty while only intended.
    job_id: str = ""
    business_id: str = ""
    essential: bool = False
    note: str = ""
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def outstanding(self) -> bool:
        return self.state is ReservationState.HELD


def resource_for(tenant_id: str) -> str:
    """The ledger key for a tenant's monthly allowance.

    One allowance per tenant rather than one per capability: a customer's plan
    is a budget for the month's work, not a set of per-feature buckets they have
    to manage. The capability still declares what it costs; this is where it is
    drawn from.
    """
    return f"credits.{tenant_id}"


def policy_for(tenant_id: str, plan: Plan) -> QuotaPolicy:
    """The tenant's allowance, as a policy the existing ledger understands."""
    return QuotaPolicy(
        resource=resource_for(tenant_id),
        limit=INCLUDED[plan],
        window=QuotaWindow.MONTHLY,
        # SPEND rather than PLATFORM: this ceiling is a commercial decision and
        # moving to a larger plan raises it, which is exactly what SPEND means.
        kind=LimitKind.SPEND,
        floor=ESSENTIAL_FLOOR[plan],
    )
