from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import ActionSpec, CapabilitySpec, ExecutorSpec, ModelSpec, ProviderSpec, RecipeSpec


@dataclass
class Registry:
    actions: dict[str, ActionSpec] = field(default_factory=dict)
    providers: dict[str, ProviderSpec] = field(default_factory=dict)
    recipes: dict[str, Any] = field(default_factory=dict)
    capabilities: dict[str, CapabilitySpec] = field(default_factory=dict)
    capability_recipes: dict[str, RecipeSpec] = field(default_factory=dict)
    executors: dict[str, ExecutorSpec] = field(default_factory=dict)
    models: dict[str, ModelSpec] = field(default_factory=dict)

    def register_action(self, action: ActionSpec) -> None:
        self.actions[action.name] = action

    def register_provider(self, provider: ProviderSpec) -> None:
        self.providers[provider.name] = provider

    def register_recipe(self, name: str, payload: dict[str, Any]) -> None:
        self.recipes[name] = payload

    def register_capability(self, capability: CapabilitySpec) -> None:
        self.capabilities[capability.id] = capability

    def update_capability(self, capability: CapabilitySpec) -> None:
        self.capabilities[capability.id] = capability

    def register_capability_recipe(self, recipe: RecipeSpec) -> None:
        self.capability_recipes[recipe.id] = recipe

    def register_executor(self, executor: ExecutorSpec) -> None:
        self.executors[executor.id] = executor

    def register_model(self, model: ModelSpec) -> None:
        self.models[model.id] = model

    def get_action(self, name: str) -> ActionSpec | None:
        return self.actions.get(name)

    def get_provider(self, name: str) -> ProviderSpec | None:
        return self.providers.get(name)

    def get_recipe(self, name: str) -> dict[str, Any] | None:
        return self.recipes.get(name)

    def get_capability(self, capability_id: str) -> CapabilitySpec | None:
        return self.capabilities.get(capability_id)

    def get_capability_recipe(self, recipe_id: str) -> RecipeSpec | None:
        return self.capability_recipes.get(recipe_id)

    def get_executor(self, executor_id: str) -> ExecutorSpec | None:
        return self.executors.get(executor_id)

    def get_model(self, model_id: str) -> ModelSpec | None:
        return self.models.get(model_id)

    def list_actions(self) -> list[ActionSpec]:
        return list(self.actions.values())

    def list_recipes(self) -> list[dict[str, Any]]:
        return list(self.recipes.values())

    def list_providers(self) -> list[ProviderSpec]:
        return list(self.providers.values())

    def list_capabilities(self) -> list[CapabilitySpec]:
        return list(self.capabilities.values())

    def list_capability_recipes(self, capability_id: str) -> list[RecipeSpec]:
        return [
            recipe
            for recipe in self.capability_recipes.values()
            if recipe.capability_id == capability_id
        ]

    def list_executors(self) -> list[ExecutorSpec]:
        return list(self.executors.values())

    def list_models(self) -> list[ModelSpec]:
        return list(self.models.values())

    def list_compatible_providers(self, capability_id: str) -> list[ProviderSpec]:
        capability = self.get_capability(capability_id)
        if capability is None:
            return []
        if not capability.supported_provider_kinds:
            return self.list_providers()
        supported = set(capability.supported_provider_kinds)
        return [provider for provider in self.providers.values() if provider.kind in supported]

    def list_compatible_executors(self, capability_id: str) -> list[str]:
        capability = self.get_capability(capability_id)
        if capability is None:
            return []
        if capability.supported_executor_kinds:
            return list(capability.supported_executor_kinds)

        discovered: set[str] = set()
        for recipe in self.list_capability_recipes(capability_id):
            executor_kinds = recipe.metadata.get("supported_executor_kinds", [])
            if isinstance(executor_kinds, list):
                discovered.update(str(item) for item in executor_kinds)
        return sorted(discovered)

    def list_compatible_executor_specs(self, capability_id: str) -> list[ExecutorSpec]:
        supported_ids = set(self.list_compatible_executors(capability_id))
        if not supported_ids:
            return self.list_executors()
        return [
            executor
            for executor in self.executors.values()
            if executor.id in supported_ids or executor.kind in supported_ids
        ]

    def list_compatible_models(
        self, capability_id: str, provider_id: str | None = None
    ) -> list[ModelSpec]:
        models = [model for model in self.models.values() if capability_id in model.capability_ids]
        if provider_id is not None:
            models = [model for model in models if model.provider_id == provider_id]
        return models
