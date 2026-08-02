from __future__ import annotations

from .schedule_models import SchedulerPriority


class SchedulerPriorityEngine:
    """Deterministic scheduler priority rules."""

    _WEIGHTS = {
        SchedulerPriority.IMMEDIATE: 0,
        SchedulerPriority.HIGH: 1,
        SchedulerPriority.NORMAL: 2,
        SchedulerPriority.LOW: 3,
        SchedulerPriority.BACKGROUND: 4,
    }

    def weight(self, priority: SchedulerPriority) -> int:
        return self._WEIGHTS[priority]

    def sort_key(
        self,
        priority: SchedulerPriority,
        dependency_count: int,
        retry_count: int,
        stable_index: int,
    ) -> tuple[int, int, int, int]:
        # Lower tuple value means higher scheduling precedence.
        return (self.weight(priority), dependency_count, retry_count, stable_index)
