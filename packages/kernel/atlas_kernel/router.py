from __future__ import annotations

from .models import ProviderSpec
from .registry import Registry


class ProviderRouter:
    def __init__(self, registry: Registry) -> None:
        self.registry = registry

    def select_provider(
        self, required_kind: str | None = None, required_vram_gb: int = 0
    ) -> ProviderSpec | None:
        candidates = [p for p in self.registry.list_providers() if p.vram_gb >= required_vram_gb]
        if required_kind is not None:
            candidates = [p for p in candidates if p.kind == required_kind]
        if not candidates:
            return None
        return sorted(
            candidates, key=lambda p: (p.is_local is False, p.cost_per_unit, p.p50_latency_ms)
        )[0]
