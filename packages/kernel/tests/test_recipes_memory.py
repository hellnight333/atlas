"""Which recipes need business memory, and why the answer is derived."""

from __future__ import annotations

from atlas_kernel.fabric import recipes
from atlas_kernel.fabric.recipes import Recipe


def test_every_memory_field_is_a_real_field():
    """A rename would otherwise empty the set silently, and every recipe would
    quietly report that it needs no database."""
    unknown = [f for f in Recipe.MEMORY_FIELDS if f not in Recipe.model_fields]
    assert not unknown, f"MEMORY_FIELDS names {unknown}, which are not fields"


def test_a_recipe_that_reads_or_writes_memory_says_so():
    for recipe in recipes.all_recipes():
        touches = any(getattr(recipe, f) for f in Recipe.MEMORY_FIELDS)
        assert recipe.needs_memory is touches, recipe.id


def test_the_delivery_recipe_needs_memory():
    """It reads the approval, the business and the findings. It blocked itself
    for a whole test run by reporting that it did not."""
    assert recipes.get("deliver-website").needs_memory
