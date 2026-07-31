from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import ActionSpec, ProviderSpec


@dataclass
class Registry:
    actions: dict[str, ActionSpec] = field(default_factory=dict)
    providers: dict[str, ProviderSpec] = field(default_factory=dict)
    recipes: dict[str, Any] = field(default_factory=dict)

    def register_action(self, action: ActionSpec) -> None:
        self.actions[action.name] = action

    def register_provider(self, provider: ProviderSpec) -> None:
        self.providers[provider.name] = provider

    def register_recipe(self, name: str, payload: dict[str, Any]) -> None:
        self.recipes[name] = payload

    def get_action(self, name: str) -> ActionSpec | None:
        return self.actions.get(name)

    def get_provider(self, name: str) -> ProviderSpec | None:
        return self.providers.get(name)

    def list_actions(self) -> list[ActionSpec]:
        return list(self.actions.values())

    def list_providers(self) -> list[ProviderSpec]:
        return list(self.providers.values())
