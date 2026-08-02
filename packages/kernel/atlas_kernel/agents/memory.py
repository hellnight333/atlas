from __future__ import annotations

from .models import AgentMemoryReference, MemoryReferenceKind


class AgentMemoryManager:
    """Agent memory stores only asset references, never asset content."""

    @staticmethod
    def validate_kind(kind: str) -> MemoryReferenceKind:
        normalized = kind.strip().lower()
        allowed = {
            "conversation",
            "research",
            "image",
            "workflow",
            "review",
            "workspace",
        }
        if normalized not in allowed:
            raise ValueError(f"Unsupported memory reference kind: {kind}")
        return normalized  # type: ignore[return-value]

    @classmethod
    def create_reference(
        cls,
        memory_id: str,
        agent_id: str,
        kind: str,
        asset_id: str,
    ) -> AgentMemoryReference:
        return AgentMemoryReference(
            memory_id=memory_id,
            agent_id=agent_id,
            kind=cls.validate_kind(kind),
            asset_id=asset_id,
        )
