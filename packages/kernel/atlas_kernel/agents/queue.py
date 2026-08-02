from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .schedule_models import QueueEntryStatus, ResumeToken, ScheduleQueueEntry


class SchedulerQueue:
    """Mutable queue state holder for scheduler-only lifecycle operations."""

    def __init__(self, entries: list[ScheduleQueueEntry]) -> None:
        self.entries = entries

    def mark_ready(self, entry_ids: list[str]) -> list[str]:
        updated: list[str] = []
        for entry in self.entries:
            if entry.id in entry_ids and entry.status == QueueEntryStatus.QUEUED:
                entry.status = QueueEntryStatus.READY
                updated.append(entry.id)
        return updated

    def pause(self) -> tuple[list[str], list[ResumeToken]]:
        now = datetime.now(UTC)
        updated: list[str] = []
        tokens: list[ResumeToken] = []
        for entry in self.entries:
            if entry.status in {QueueEntryStatus.QUEUED, QueueEntryStatus.READY, QueueEntryStatus.RUNNING}:
                entry.status = QueueEntryStatus.PAUSED
                updated.append(entry.id)
                tokens.append(ResumeToken(entry_id=entry.id, metadata={"paused_at": now.isoformat()}))
        return updated, tokens

    def resume(self, token_ids: set[str] | None = None) -> list[str]:
        updated: list[str] = []
        for entry in self.entries:
            if entry.status == QueueEntryStatus.PAUSED:
                entry.status = QueueEntryStatus.QUEUED
                updated.append(entry.id)
        return updated

    def cancel(self) -> list[str]:
        updated: list[str] = []
        now = datetime.now(UTC)
        for entry in self.entries:
            if entry.status not in {QueueEntryStatus.COMPLETED, QueueEntryStatus.CANCELLED}:
                entry.status = QueueEntryStatus.CANCELLED
                entry.completed_time = now
                updated.append(entry.id)
        return updated

    def retry(self, entry_id: str) -> bool:
        for entry in self.entries:
            if entry.id == entry_id and entry.status in {QueueEntryStatus.BLOCKED, QueueEntryStatus.PAUSED, QueueEntryStatus.CANCELLED}:
                entry.retry_count += 1
                entry.status = QueueEntryStatus.QUEUED
                entry.started_time = None
                entry.completed_time = None
                return True
        return False

    def delay(self, entry_id: str, delay_seconds: int) -> bool:
        if delay_seconds < 0:
            raise ValueError("Delay must be non-negative")
        for entry in self.entries:
            if entry.id == entry_id:
                if entry.status not in {QueueEntryStatus.QUEUED, QueueEntryStatus.READY}:
                    return False
                entry.status = QueueEntryStatus.PAUSED
                entry.scheduled_time = datetime.now(UTC) + timedelta(seconds=delay_seconds)
                return True
        return False
