from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from .events import AuditRecorded
from .models import AuditAction, AuditRecord

if TYPE_CHECKING:
    from ..event_bus import EventBus
    from ..repository import AtlasRepository


class AuditService:
    """Append-only audit trail.

    There is deliberately no update and no delete. The repository exposes no
    mutating method for ``atlas_audit_records`` either, so an audit entry cannot
    be rewritten through any code path in the kernel.
    """

    def __init__(self, repository: AtlasRepository, event_bus: EventBus) -> None:
        self.repository = repository
        self.event_bus = event_bus

    def record(
        self,
        *,
        action: AuditAction,
        actor_id: str = "system",
        actor_display: str | None = None,
        organization_id: str | None = None,
        target_type: str = "",
        target_id: str | None = None,
        summary: str = "",
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditRecord:
        record = AuditRecord(
            organization_id=organization_id,
            actor_id=actor_id,
            actor_display=actor_display or actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            summary=summary,
            before=before or {},
            after=after or {},
            metadata=metadata or {},
        )
        self.repository.create_audit_record(record)
        self.event_bus.publish(
            AuditRecorded(
                audit_id=record.id,
                organization_id=organization_id,
                action=action.value,
                actor_id=actor_id,
            )
        )
        return record

    def get(self, audit_id: str) -> AuditRecord | None:
        return self.repository.get_audit_record(audit_id)

    def list_records(
        self,
        organization_id: str | None = None,
        action: AuditAction | None = None,
        actor_id: str | None = None,
        target_id: str | None = None,
        since: datetime | None = None,
        limit: int = 200,
    ) -> list[AuditRecord]:
        return self.repository.list_audit_records(
            organization_id=organization_id,
            action=action,
            actor_id=actor_id,
            target_id=target_id,
            since=since,
            limit=limit,
        )
