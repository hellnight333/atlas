from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from .agents.schedule_models import QueueEntryStatus, RuntimeExecutionStatus
from .logging_setup import get_logger

if TYPE_CHECKING:
    from .agents.runtime import AgentRuntime
    from .cluster.heartbeat_service import HeartbeatService
    from .cluster.lease_manager import LeaseManager
    from .cluster.worker_registry import WorkerRegistry
    from .repository import AtlasRepository

logger = get_logger("runtime")

#: An execution still RUNNING with no heartbeat for this long is orphaned —
#: the process that owned it is gone.
DEFAULT_ORPHAN_AFTER_SECONDS = 300

#: A reservation with no live lease and no live execution is stale.
DEFAULT_STALE_RESERVATION_SECONDS = 600


class RecoveryAction(BaseModel):
    kind: str
    target_id: str
    detail: str = ""


class RecoveryReport(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    dry_run: bool = False
    actions: list[RecoveryAction] = Field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.actions)

    def of_kind(self, kind: str) -> list[RecoveryAction]:
        return [a for a in self.actions if a.kind == kind]


class RecoveryService:
    """Finds and repairs work stranded by a crash, a dead worker, or a lease
    that outlived its owner.

    Every sweep is idempotent and every repair is additive: nothing is deleted,
    executions are requeued rather than discarded, and a dry run reports exactly
    what a real run would do.
    """

    def __init__(
        self,
        repository: AtlasRepository,
        runtime: AgentRuntime,
        lease_manager: LeaseManager,
        heartbeats: HeartbeatService,
        registry: WorkerRegistry,
        orphan_after_seconds: int = DEFAULT_ORPHAN_AFTER_SECONDS,
        stale_reservation_seconds: int = DEFAULT_STALE_RESERVATION_SECONDS,
    ) -> None:
        self.repository = repository
        self.runtime = runtime
        self.lease_manager = lease_manager
        self.heartbeats = heartbeats
        self.registry = registry
        self.orphan_after_seconds = orphan_after_seconds
        self.stale_reservation_seconds = stale_reservation_seconds

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def find_orphaned_executions(self, now: datetime | None = None) -> list[Any]:
        """RUNNING or PREPARING executions whose owner stopped reporting."""
        now = now or datetime.now(UTC)
        cutoff = now - timedelta(seconds=self.orphan_after_seconds)
        live = {RuntimeExecutionStatus.RUNNING, RuntimeExecutionStatus.PREPARING}

        orphans = []
        for execution in self.repository.list_runtime_executions():
            if execution.status not in live:
                continue
            last_seen = execution.heartbeat_at or execution.updated_at
            if last_seen < cutoff:
                orphans.append(execution)
        return orphans

    def find_stale_reservations(self, now: datetime | None = None) -> list[Any]:
        """Active reservations whose lease and execution are both finished."""
        now = now or datetime.now(UTC)
        cutoff = now - timedelta(seconds=self.stale_reservation_seconds)

        live_leases = {lease.reservation_id for lease in self.lease_manager.list_active_leases()}
        stale = []
        for reservation in self.lease_manager.list_active_reservations():
            if reservation.id in live_leases:
                continue
            if reservation.created_at > cutoff:
                continue
            stale.append(reservation)
        return stale

    def find_stuck_queue_entries(self) -> list[tuple[Any, Any]]:
        """Entries left PREPARING or RUNNING with no live execution behind them."""
        live_entry_ids = {
            execution.entry_id
            for execution in self.repository.list_runtime_executions()
            if execution.status
            in {
                RuntimeExecutionStatus.RUNNING,
                RuntimeExecutionStatus.PREPARING,
                RuntimeExecutionStatus.QUEUED,
                RuntimeExecutionStatus.WAITING_APPROVAL,
                RuntimeExecutionStatus.WAITING_PLACEMENT,
            }
        }

        stuck: list[tuple[Any, Any]] = []
        in_flight = {QueueEntryStatus.PREPARING, QueueEntryStatus.RUNNING}
        for schedule in self.repository.list_schedules():
            for entry in schedule.queue_entries:
                if entry.status in in_flight and entry.id not in live_entry_ids:
                    stuck.append((schedule, entry))
        return stuck

    # ------------------------------------------------------------------
    # Sweeps
    # ------------------------------------------------------------------

    def recover_orphaned_executions(
        self, dry_run: bool = False, now: datetime | None = None
    ) -> list[RecoveryAction]:
        actions: list[RecoveryAction] = []
        for execution in self.find_orphaned_executions(now):
            detail = f"no heartbeat since {(execution.heartbeat_at or execution.updated_at)}"
            if not dry_run:
                self.runtime.recover_execution(
                    execution.execution_id, reason="orphaned execution recovered"
                )
                logger.warning(
                    "recovered orphaned execution",
                    extra={
                        "execution_id": execution.execution_id,
                        "worker_id": execution.worker_id,
                    },
                )
            actions.append(
                RecoveryAction(
                    kind="orphaned_execution", target_id=execution.execution_id, detail=detail
                )
            )
        return actions

    def release_stale_reservations(
        self, dry_run: bool = False, now: datetime | None = None
    ) -> list[RecoveryAction]:
        actions: list[RecoveryAction] = []
        for reservation in self.find_stale_reservations(now):
            if not dry_run:
                self.lease_manager.release_reservation(reservation.id, reason="stale reservation")
                self._return_slot(reservation.worker_id)
                logger.warning(
                    "released stale reservation",
                    extra={"reservation_id": reservation.id, "worker_id": reservation.worker_id},
                )
            actions.append(
                RecoveryAction(
                    kind="stale_reservation",
                    target_id=reservation.id,
                    detail=f"worker {reservation.worker_id}, no live lease",
                )
            )
        return actions

    def _return_slot(self, worker_id: str) -> None:
        """A worker referenced by a stale reservation may have been removed from
        the cluster entirely. Releasing the reservation still matters, so a
        missing worker must not abort the sweep."""
        try:
            self.registry.adjust_load(worker_id, -1)
        except Exception as exc:  # noqa: BLE001 - recovery must be resilient
            logger.info(
                "could not return worker slot during recovery",
                extra={"worker_id": worker_id, "reason": str(exc)},
            )

    def recover_queue(self, dry_run: bool = False) -> list[RecoveryAction]:
        actions: list[RecoveryAction] = []
        for schedule, entry in self.find_stuck_queue_entries():
            if not dry_run:
                entry.status = QueueEntryStatus.READY
                entry.started_time = None
                self.repository.update_schedule(schedule)
                logger.warning(
                    "requeued stuck entry",
                    extra={"schedule_id": schedule.schedule_id, "entry_id": entry.id},
                )
            actions.append(
                RecoveryAction(
                    kind="stuck_queue_entry",
                    target_id=entry.id,
                    detail=f"schedule {schedule.schedule_id} had no live execution",
                )
            )
        return actions

    def recover_workers(
        self, dry_run: bool = False, now: datetime | None = None
    ) -> list[RecoveryAction]:
        actions: list[RecoveryAction] = []
        for worker in self.heartbeats.stale_workers(now):
            if not dry_run:
                self.registry.mark_offline(worker.id, reason="heartbeat timeout")
                logger.warning("worker marked offline", extra={"worker_id": worker.id})
            actions.append(
                RecoveryAction(
                    kind="stale_worker",
                    target_id=worker.id,
                    detail=f"last heartbeat {worker.last_heartbeat_at}",
                )
            )
        return actions

    def expire_leases(self, dry_run: bool = False) -> list[RecoveryAction]:
        if dry_run:
            now = datetime.now(UTC)
            due = [
                lease
                for lease in self.repository.list_leases()
                if lease.state.value == "active" and lease.expires_at <= now
            ]
            return [
                RecoveryAction(kind="expired_lease", target_id=lease.id, detail="past deadline")
                for lease in due
            ]

        return [
            RecoveryAction(kind="expired_lease", target_id=lease.id, detail="past deadline")
            for lease in self.lease_manager.expire_due()
        ]

    def run_full_sweep(self, dry_run: bool = False, now: datetime | None = None) -> RecoveryReport:
        """Order matters: expire leases and mark workers offline first, so the
        execution and reservation sweeps see an accurate cluster."""
        actions: list[RecoveryAction] = []
        # Each stage is isolated: one unrecoverable target must not prevent the
        # rest of the sweep from repairing what it can.
        stages: list[tuple[str, Any]] = [
            ("workers", lambda: self.recover_workers(dry_run=dry_run, now=now)),
            ("leases", lambda: self.expire_leases(dry_run=dry_run)),
            ("executions", lambda: self.recover_orphaned_executions(dry_run=dry_run, now=now)),
            ("reservations", lambda: self.release_stale_reservations(dry_run=dry_run, now=now)),
            ("queue", lambda: self.recover_queue(dry_run=dry_run)),
        ]
        for name, stage in stages:
            try:
                actions.extend(stage())
            except Exception as exc:  # noqa: BLE001 - a sweep reports, never crashes
                logger.error("recovery stage failed", extra={"stage": name, "reason": str(exc)})
                actions.append(RecoveryAction(kind="stage_failed", target_id=name, detail=str(exc)))

        report = RecoveryReport(dry_run=dry_run, actions=actions)
        if actions and not dry_run:
            logger.info("recovery sweep completed", extra={"actions": len(actions)})
        return report

    def startup_recovery(self) -> RecoveryReport:
        """Run once at boot: a previous process may have died mid-execution."""
        report = self.run_full_sweep(dry_run=False)
        if report.count:
            logger.warning(
                "startup recovery repaired stranded work", extra={"actions": report.count}
            )
        return report
