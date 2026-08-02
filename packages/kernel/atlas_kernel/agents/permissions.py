from __future__ import annotations

from collections.abc import Sequence

from .models import AgentPermission


class AgentPermissionSet:
    @staticmethod
    def normalize(permissions: Sequence[AgentPermission | str]) -> list[AgentPermission]:
        normalized: list[AgentPermission] = []
        for permission in permissions:
            value = AgentPermission(permission)
            if value not in normalized:
                normalized.append(value)
        return normalized
