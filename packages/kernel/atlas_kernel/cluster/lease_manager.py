from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from .events import LeaseExpired, ReservationCreated, ReservationReleased
from .models import (
    ExecutionLease,
    ExecutionReservation,
    LeaseState,
    ReservationState,
)

if TYPE_CHECKING:
    from ..event_bus import EventBus
    from ..repository import AtlasRepository


DEFAULT_LEASE_SECONDS = 120


class LeaseManagerError(RuntimeError):
    pass


class LeaseManager:
    """Owns reservations and leases.

    A reservation is the claim on a worker slot; a lease is the time-bounded
    right to execute. Both are released explicitly, and a lease that outlives
    its deadline is reclaimed so work is never stranded on a dead worker.
    """

    def __init__(
        self,
        repository: AtlasRepository,
        event_bus: EventBus,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> None:
        self.repository = repository
        self.event_bus = event_bus
        self.lease_seconds = lease_seconds

    # ------------------------------------------------------------------
    # Reservations
    # ------------------------------------------------------------------

    def reserve(
        self,
        *,
        worker_id: str,
        schedule_id: str,
        entry_id: str,
        execution_id: str | None = None,
        capability: str = "",
        priority: int = 0,
        reason: str = "",
    ) -> ExecutionReservation:
        reservation = ExecutionReservation(
            worker_id=worker_id,
            schedule_id=schedule_id,
            entry_id=entry_id,
            execution_id=execution_id,
            capability=capability,
            priority=priority,
            state=ReservationState.ACTIVE,
            reason=reason,
        )
        self.repository.create_reservation(reservation)
        self.event_bus.publish(
            ReservationCreated(
                reservation_id=reservation.id,
                worker_id=worker_id,
                schedule_id=schedule_id,
                entry_id=entry_id,
            )
        )
        return reservation

    def release_reservation(
        self, reservation_id: str, reason: str = "completed"
    ) -> ExecutionReservation:
        reservation = self._require_reservation(reservation_id)
        if reservation.state is ReservationState.RELEASED:
            return reservation
        released = reservation.model_copy(
            update={
                "state": ReservationState.RELEASED,
                "released_at": datetime.now(UTC),
                "reason": reason,
            }
        )
        self.repository.update_reservation(released)
        self.event_bus.publish(
            ReservationReleased(
                reservation_id=reservation_id, worker_id=released.worker_id, reason=reason
            )
        )
        return released

    def list_active_reservations(self, worker_id: str | None = None) -> list[ExecutionReservation]:
        return [
            r
            for r in self.repository.list_reservations(worker_id=worker_id)
            if r.state is ReservationState.ACTIVE
        ]

    # ------------------------------------------------------------------
    # Leases
    # ------------------------------------------------------------------

    def acquire(
        self,
        *,
        reservation_id: str,
        worker_id: str,
        execution_id: str,
        lease_seconds: int | None = None,
    ) -> ExecutionLease:
        seconds = lease_seconds or self.lease_seconds
        now = datetime.now(UTC)
        lease = ExecutionLease(
            reservation_id=reservation_id,
            worker_id=worker_id,
            execution_id=execution_id,
            lease_seconds=seconds,
            created_at=now,
            expires_at=now + timedelta(seconds=seconds),
        )
        self.repository.create_lease(lease)
        return lease

    def renew(self, lease_id: str, lease_seconds: int | None = None) -> ExecutionLease:
        lease = self._require_lease(lease_id)
        if lease.state is not LeaseState.ACTIVE:
            raise LeaseManagerError(
                f"Lease {lease_id} is {lease.state.value} and cannot be renewed"
            )
        now = datetime.now(UTC)
        seconds = lease_seconds or lease.lease_seconds
        renewed = lease.model_copy(
            update={
                "renewed_at": now,
                "expires_at": now + timedelta(seconds=seconds),
                "lease_seconds": seconds,
            }
        )
        self.repository.update_lease(renewed)
        return renewed

    def release(self, lease_id: str) -> ExecutionLease:
        lease = self._require_lease(lease_id)
        if lease.state is not LeaseState.ACTIVE:
            return lease
        released = lease.model_copy(
            update={"state": LeaseState.RELEASED, "released_at": datetime.now(UTC)}
        )
        self.repository.update_lease(released)
        return released

    def expire(self, lease_id: str) -> ExecutionLease:
        lease = self._require_lease(lease_id)
        if lease.state is not LeaseState.ACTIVE:
            return lease
        expired = lease.model_copy(
            update={"state": LeaseState.EXPIRED, "released_at": datetime.now(UTC)}
        )
        self.repository.update_lease(expired)
        self.event_bus.publish(
            LeaseExpired(
                lease_id=lease_id,
                worker_id=expired.worker_id,
                execution_id=expired.execution_id,
            )
        )
        return expired

    def expire_due(self, now: datetime | None = None) -> list[ExecutionLease]:
        now = now or datetime.now(UTC)
        due = [
            lease
            for lease in self.repository.list_leases()
            if lease.state is LeaseState.ACTIVE and lease.expires_at <= now
        ]
        return [self.expire(lease.id) for lease in due]

    def get_lease(self, lease_id: str) -> ExecutionLease | None:
        return self.repository.get_lease(lease_id)

    def list_active_leases(self, worker_id: str | None = None) -> list[ExecutionLease]:
        return [
            lease
            for lease in self.repository.list_leases(worker_id=worker_id)
            if lease.state is LeaseState.ACTIVE
        ]

    def _require_reservation(self, reservation_id: str) -> ExecutionReservation:
        reservation = self.repository.get_reservation(reservation_id)
        if reservation is None:
            raise LeaseManagerError(f"Reservation not found: {reservation_id}")
        return reservation

    def _require_lease(self, lease_id: str) -> ExecutionLease:
        lease = self.repository.get_lease(lease_id)
        if lease is None:
            raise LeaseManagerError(f"Lease not found: {lease_id}")
        return lease
