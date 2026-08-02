from atlas_kernel.models import (
    ActionSpec,
    CapabilitySpec,
    ExecutorSpec,
    ModelSpec,
    ProviderSpec,
    RecipeSpec,
)
from atlas_kernel.registry import Registry


def test_registry_register_and_retrieve_entries():
    registry = Registry()
    action = ActionSpec(name="image.generate", description="Generate an image")
    provider = ProviderSpec(name="local-flux", kind="image", is_local=True, vram_gb=24)

    registry.register_action(action)
    registry.register_provider(provider)
    registry.register_recipe("product-shot", {"name": "product-shot"})

    assert registry.get_action("image.generate") == action
    assert registry.get_provider("local-flux") == provider
    assert registry.get_recipe("product-shot") == {"name": "product-shot"}
    assert len(registry.list_actions()) == 1
    assert len(registry.list_providers()) == 1
    assert len(registry.list_recipes()) == 1


def test_capability_registry_and_compatibility_lookups():
    registry = Registry()
    registry.register_provider(
        ProviderSpec(name="local-flux", kind="image", is_local=True, vram_gb=24)
    )
    registry.register_provider(ProviderSpec(name="local-llm", kind="llm", is_local=True, vram_gb=0))
    registry.register_executor(
        ExecutorSpec(id="local", kind="local", is_local=True, max_vram_gb=48)
    )
    registry.register_model(
        ModelSpec(id="flux-dev", provider_id="local-flux", capability_ids=["cap-image-generation"])
    )

    capability = CapabilitySpec(
        id="cap-image-generation",
        name="Image Generation",
        supported_provider_kinds=["image"],
        supported_executor_kinds=["local", "cloud"],
    )
    registry.register_capability(capability)

    recipe = RecipeSpec(
        id="recipe-fast-draft",
        capability_id=capability.id,
        name="Fast Draft",
        metadata={"supported_executor_kinds": ["local", "cloud"]},
    )
    registry.register_capability_recipe(recipe)

    assert registry.get_capability(capability.id) == capability
    assert registry.get_capability_recipe(recipe.id) == recipe
    assert len(registry.list_capabilities()) == 1
    assert len(registry.list_capability_recipes(capability.id)) == 1

    providers = registry.list_compatible_providers(capability.id)
    assert len(providers) == 1
    assert providers[0].name == "local-flux"

    executors = registry.list_compatible_executors(capability.id)
    assert executors == ["local", "cloud"]

    executor_specs = registry.list_compatible_executor_specs(capability.id)
    assert len(executor_specs) == 1
    assert executor_specs[0].id == "local"

    models = registry.list_compatible_models(capability.id, provider_id="local-flux")
    assert len(models) == 1
    assert models[0].id == "flux-dev"
