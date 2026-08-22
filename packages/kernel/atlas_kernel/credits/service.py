"""Reserve, then act, then settle — or release and consume nothing.

The accounting lives in `quota.QuotaLedger`, which already knows about windows,
floors and refusing rather than failing. What this adds is the part the ledger
deliberately does not have: an intent that has been checked and set aside but
has not consumed anything yet.

    reserve()  → units are held; the ledger is untouched
    settle()   → the work happened; the units go through the ledger
    release()  → the work did not happen; nothing was consumed

A held reservation is subtracted from what the next caller may reserve, or two
jobs would each pass the check and only one of them could be paid for. Holding
them outside the ledger is what makes a release free: if the process dies with
reservations outstanding, nothing was consumed, which is correct — nothing was
done.

**Tenancy is not optional here.** An allowance belongs to one customer, so every
method takes a tenant and a tenant with no plan is refused rather than defaulted
to the free tier — that is a provisioning gap, and hiding it makes the numbers
unexplainable later.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from ..opportunity.models import BusinessEvent
from ..opportunity.tenancy import TenantId, owns
from ..opportunity.tenancy import require as _require_tenant
from ..quota.ledger import QuotaLedger
from ..quota.models import QuotaExhausted, QuotaStatus
from ..recommendation.offers import offer_for
from .models import (
    NoPlan,
    NotReserved,
    Plan,
    Reservation,
    ReservationState,
    policy_for,
    resource_for,
)

log = logging.getLogger(__name__)

FACTORY = "credits"
RESERVED = "credits_reserved"
SETTLED = "credits_settled"
RELEASED = "credits_released"


class CreditService:
    """One customer's allowance, drawn from the existing ledger."""

    def __init__(self, ledger: QuotaLedger | None = None) -> None:
        self._ledger = ledger or QuotaLedger(policies=[])
        self._plans: dict[str, Plan] = {}
        self._held: dict[str, Reservation] = {}

    # -- provisioning ------------------------------------------------------

    def assign(self, tenant_id: str, plan: Plan) -> Plan:
        """Put a tenant on a plan, registering its allowance with the ledger."""
        if not tenant_id.strip():
            raise NoPlan("a plan belongs to a tenant; none was named")
        self._plans[tenant_id] = plan
        self._ledger.register(policy_for(tenant_id, plan))
        log.info("credits: %s assigned to %s", tenant_id, plan.value)
        return plan

    def plan_of(self, tenant: TenantId | None) -> Plan:
        tenant = _require_tenant(tenant, method="credits.plan_of")
        found = self._plans.get(str(tenant))
        if found is None:
            raise NoPlan(
                f"{tenant} is not on a plan, so there is no allowance to draw "
                "on. This is a provisioning gap rather than an empty balance, "
                "and defaulting to the free tier would hide it.")
        return found

    # -- what a piece of work costs ---------------------------------------

    def units_for(self, action: str) -> float:
        """What the capability itself declares. Never a second price list."""
        offer = offer_for(action)
        if offer is None:
            raise NotReserved(
                f"no offer {action!r}, so nothing declares what it costs. A "
                "capability with no offer cannot be charged for.")
        return float(offer.estimated_units)

    # -- the allowance -----------------------------------------------------

    def balance(self, tenant: TenantId | None, *, essential: bool = False) -> float:
        """What may still be reserved, after everything already held."""
        tenant = _require_tenant(tenant, method="credits.balance")
        self.plan_of(tenant)
        remaining = self._ledger.remaining(resource_for(str(tenant)),
                                           essential=essential)
        return max(0.0, remaining - self.held(tenant))

    def held(self, tenant: TenantId | None) -> float:
        """Units set aside and not yet settled or released."""
        tenant = _require_tenant(tenant, method="credits.held")
        return sum(r.units for r in self._held.values()
                   if r.outstanding and owns(r.tenant_id, tenant))

    def status(self, tenant: TenantId | None) -> QuotaStatus:
        tenant = _require_tenant(tenant, method="credits.status")
        self.plan_of(tenant)
        return self._ledger.status(resource_for(str(tenant)))

    # -- reserve / settle / release ---------------------------------------

    def reserve(self, *, tenant: TenantId | None, action: str, business_id: str = "",
                units: float | None = None, essential: bool = False,
                note: str = "") -> Reservation:
        """Set units aside before the work starts, or refuse.

        Refuses on the balance *after* outstanding holds, so two jobs cannot
        each pass the check and leave one of them unpayable.
        """
        tenant = _require_tenant(tenant, method="credits.reserve")
        plan = self.plan_of(tenant)
        amount = self.units_for(action) if units is None else float(units)
        if amount < 0:
            raise ValueError("a reservation cannot be negative")

        available = self.balance(tenant, essential=essential)
        if amount > available:
            raise QuotaExhausted(resource_for(str(tenant)),
                                 self._ledger.policy(resource_for(str(tenant))).kind,
                                 available, amount)

        reservation = Reservation(
            id=f"cred-{uuid4().hex[:12]}", tenant_id=str(tenant), action=action,
            units=amount, business_id=business_id, essential=essential,
            note=note or f"{plan.value} plan")
        self._held[reservation.id] = reservation
        return reservation

    def settle(self, reservation_id: str, *, tenant: TenantId | None,
               job_id: str = "", actual_units: float | None = None) -> Reservation:
        """The work happened. Put the units through the ledger.

        `actual_units` lets a capability report what it really took. It may be
        less than reserved — never more, because the excess was never checked
        against the allowance and settling it would let a job overspend a plan
        after the fact.
        """
        tenant = _require_tenant(tenant, method="credits.settle")
        reservation = self._require(reservation_id, tenant)
        amount = reservation.units if actual_units is None else float(actual_units)
        if amount > reservation.units:
            raise QuotaExhausted(
                resource_for(str(tenant)),
                self._ledger.policy(resource_for(str(tenant))).kind,
                reservation.units, amount)

        self._ledger.spend(resource_for(str(tenant)), amount,
                           essential=reservation.essential,
                           note=f"{reservation.action} ({reservation.id})")
        settled = reservation.model_copy(update={
            "state": ReservationState.SETTLED, "units": amount, "job_id": job_id})
        self._held[reservation_id] = settled
        return settled

    def release(self, reservation_id: str, *, tenant: TenantId | None,
                reason: str = "") -> Reservation:
        """The work did not happen. Nothing is consumed.

        A failed job must not cost a customer anything: the provider may have
        been called, but no artefact reached them, and charging for that is how
        a plan runs out on work nobody received.
        """
        tenant = _require_tenant(tenant, method="credits.release")
        reservation = self._require(reservation_id, tenant)
        released = reservation.model_copy(update={
            "state": ReservationState.RELEASED,
            "note": reason or reservation.note})
        self._held[reservation_id] = released
        return released

    def _require(self, reservation_id: str, tenant: TenantId) -> Reservation:
        found = self._held.get(reservation_id)
        # Another tenant's reservation reads as absent, as everywhere else.
        if found is None or not owns(found.tenant_id, tenant):
            raise NotReserved(f"no reservation {reservation_id!r}")
        if not found.outstanding:
            raise NotReserved(
                f"reservation {reservation_id!r} is already {found.state.value}. "
                "Settling twice would charge for one piece of work twice.")
        return found

    # -- history -----------------------------------------------------------

    def history(self, tenant: TenantId | None) -> tuple[Reservation, ...]:
        """TENANT_SCOPED. Everything reserved for this tenant, newest first."""
        tenant = _require_tenant(tenant, method="credits.history")
        mine = [r for r in self._held.values() if owns(r.tenant_id, tenant)]
        return tuple(sorted(mine, key=lambda r: r.at, reverse=True))


def to_event(reservation: Reservation, *, actor: str = "credits") -> BusinessEvent:
    """The timeline entry. Units and ids only — no money, because there is none."""
    kind = {ReservationState.HELD: RESERVED,
            ReservationState.SETTLED: SETTLED,
            ReservationState.RELEASED: RELEASED}[reservation.state]
    return BusinessEvent(
        business_id=reservation.business_id, factory=FACTORY, kind=kind,
        actor=actor,
        detail={"reservation_id": reservation.id, "tenant_id": reservation.tenant_id,
                "action": reservation.action, "units": reservation.units,
                "state": reservation.state.value, "job_id": reservation.job_id,
                "essential": reservation.essential, "note": reservation.note,
                "at": reservation.at.isoformat()})


def read(events: list, *, tenant: TenantId | None = None) -> list[dict]:
    """TENANT_SCOPED. Usage history for one tenant, newest first."""
    tenant = _require_tenant(tenant, method="credits.read")
    found = []
    for event in events:
        kind = getattr(event, "kind", None) or event.get("kind")
        if kind not in (RESERVED, SETTLED, RELEASED):
            continue
        detail = getattr(event, "detail", None) or event.get("detail") or {}
        if not owns(detail.get("tenant_id"), tenant):
            continue
        found.append(dict(detail))
    return sorted(found, key=lambda d: d.get("at", ""), reverse=True)
