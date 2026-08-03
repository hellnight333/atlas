"""Recipes are the core primitive, so their failure modes matter (M013).

The theme of every test here: a recipe that cannot be reproduced should fail
when it is *loaded*, not when someone is waiting on a render. A bad recipe
discovered at render time has already cost GPU minutes and an operator's
attention.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas_kernel.media.recipes import Recipe, RecipeError, RecipeRegistry, default_root

VALID = """
id: test-recipe
version: 2.1.0
capability: video.generate
provider: some-provider
model: some-model
prompt_template: "{prompt}, cinematic"
parameters:
  width: 1280
  height: 720
"""


def _write(root: Path, name: str, body: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_text(body)
    return path


# -- the recipes actually shipped ----------------------------------------


def test_the_repository_recipes_all_load() -> None:
    """The ones in git are valid, or CI says so before a human does."""
    registry = RecipeRegistry(default_root()).load()
    ids = {recipe.id for recipe in registry.all()}
    assert {"mock-slate-1080p", "wan-t2v-720p", "mock-narration"} <= ids


def test_capabilities_are_declared_not_inferred() -> None:
    registry = RecipeRegistry(default_root()).load()
    assert {r.id for r in registry.for_capability("video.generate")} == {
        "mock-slate-1080p",
        "wan-t2v-720p",
    }
    assert {r.id for r in registry.for_capability("speech.generate")} == {"mock-narration"}


def test_the_real_video_recipe_pins_its_seed() -> None:
    """A recipe whose output changes between runs is not a recipe."""
    registry = RecipeRegistry(default_root()).load()
    assert registry.get("wan-t2v-720p").seed is not None


# -- loading --------------------------------------------------------------


def test_a_recipe_round_trips(tmp_path: Path) -> None:
    _write(tmp_path, "r.yaml", VALID)
    recipe = RecipeRegistry(tmp_path).load().get("test-recipe")
    assert recipe.version == "2.1.0"
    assert recipe.parameters["width"] == 1280
    assert recipe.render_prompt("a harbour at dusk") == "a harbour at dusk, cinematic"


def test_a_missing_recipe_names_the_ones_that_exist(tmp_path: Path) -> None:
    """Because "unknown recipe" alone sends someone reading directories."""
    _write(tmp_path, "r.yaml", VALID)
    with pytest.raises(RecipeError, match="test-recipe"):
        RecipeRegistry(tmp_path).load().get("nope")


def test_duplicate_ids_are_refused(tmp_path: Path) -> None:
    """Recipe ids are referenced from provenance records. Two recipes sharing
    one id would make a render's history ambiguous forever."""
    _write(tmp_path, "a.yaml", VALID)
    _write(tmp_path, "b.yaml", VALID)
    with pytest.raises(RecipeError, match="duplicate recipe id"):
        RecipeRegistry(tmp_path).load()


def test_malformed_yaml_names_the_file(tmp_path: Path) -> None:
    _write(tmp_path, "bad.yaml", "id: [unclosed\n")
    with pytest.raises(RecipeError, match="bad.yaml"):
        RecipeRegistry(tmp_path).load()


def test_a_non_mapping_document_is_rejected(tmp_path: Path) -> None:
    _write(tmp_path, "list.yaml", "- not\n- a mapping\n")
    with pytest.raises(RecipeError, match="must contain a mapping"):
        RecipeRegistry(tmp_path).load()


def test_an_invalid_recipe_names_the_file(tmp_path: Path) -> None:
    _write(tmp_path, "nocap.yaml", "id: x\n")  # capability is required
    with pytest.raises(RecipeError, match="nocap.yaml"):
        RecipeRegistry(tmp_path).load()


def test_ids_must_be_slugs() -> None:
    with pytest.raises(ValueError):
        Recipe(id="has spaces", capability="video.generate")


def test_an_empty_directory_is_not_an_error(tmp_path: Path) -> None:
    """A checkout with no recipes yet is a normal state, not a crash."""
    assert RecipeRegistry(tmp_path / "absent").load().all() == []


# -- workflow pinning -----------------------------------------------------


def test_a_pinned_workflow_is_hashed(tmp_path: Path) -> None:
    """The hash is what notices a graph edited in the ComfyUI GUI and saved
    under the same name."""
    _write(tmp_path, "graph.json", '{"nodes": []}')
    _write(tmp_path, "r.yaml", VALID + "workflow: graph.json\n")

    recipe = RecipeRegistry(tmp_path).load().get("test-recipe")
    assert recipe.workflow_sha256 is not None
    assert recipe.workflow_path is not None and recipe.workflow_path.exists()

    before = recipe.workflow_sha256
    _write(tmp_path, "graph.json", '{"nodes": [1]}')
    after = RecipeRegistry(tmp_path).load().get("test-recipe").workflow_sha256
    assert after != before


def test_a_missing_workflow_fails_at_load(tmp_path: Path) -> None:
    """Not at render time, when someone is waiting."""
    _write(tmp_path, "r.yaml", VALID + "workflow: nowhere.json\n")
    with pytest.raises(RecipeError, match="does not exist"):
        RecipeRegistry(tmp_path).load()


# -- estimates ------------------------------------------------------------


def test_estimates_scale_with_output_length(tmp_path: Path) -> None:
    """Feeds "estimated render time / estimated cost" on the approval screen."""
    _write(
        tmp_path,
        "r.yaml",
        VALID + "estimated_cost_per_second: 0.02\nestimated_seconds_per_second: 14\n",
    )
    recipe = RecipeRegistry(tmp_path).load().get("test-recipe")

    cost, seconds = recipe.estimate(5.0)
    assert cost == pytest.approx(0.10)
    assert seconds == pytest.approx(70.0)


def test_an_unbenchmarked_recipe_estimates_nothing(tmp_path: Path) -> None:
    """A fabricated cost estimate is worse than none, because it will be
    believed."""
    _write(tmp_path, "r.yaml", VALID)
    assert RecipeRegistry(tmp_path).load().get("test-recipe").estimate(5.0) == (None, None)


def test_a_broken_prompt_template_is_reported(tmp_path: Path) -> None:
    _write(tmp_path, "r.yaml", VALID.replace('"{prompt}, cinematic"', '"{missing_key}"'))
    recipe = RecipeRegistry(tmp_path).load().get("test-recipe")
    with pytest.raises(RecipeError, match="prompt_template"):
        recipe.render_prompt("anything")


def test_a_fixed_prompt_template_is_legitimate(tmp_path: Path) -> None:
    """A recipe that ignores the scene's direction is a real thing to want --
    an intro card, say."""
    _write(tmp_path, "r.yaml", VALID.replace('"{prompt}, cinematic"', '"always the same"'))
    recipe = RecipeRegistry(tmp_path).load().get("test-recipe")
    assert recipe.render_prompt("ignored") == "always the same"
