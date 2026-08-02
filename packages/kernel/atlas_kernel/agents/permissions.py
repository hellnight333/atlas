from __future__ import annotations

from .models import AgentPermission


class AgentPermissionSet:
    @staticmethod
    def normalize(permissions: list[AgentPermission | str]) -> list[AgentPermission]:
        normalized: list[AgentPermission] = []
        for permission in permissions:
            value = AgentPermission(permission)
            if value not in normalized:
                normalized.append(value)
        return normalized
