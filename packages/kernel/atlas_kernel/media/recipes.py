"""Recipes: the only thing allowed to decide *how* something is rendered.

A recipe is a versioned, declarative artefact in git. The LLM picks one **by
name** and never authors a node graph, because a model asked to wire ComfyUI
nodes will hallucinate node wiring forever and produce something that cannot be
repeated tomorrow.

Recipes name a capability rather than a provider wherever they can. The provider
field is a *preference*, not an instruction: the router still decides, so a
recipe written against a local GPU keeps working when the work moves to another
workstation, a rented GPU, or three workers at once.

Loading is `yaml.safe_load` only. These files are repository content, but a
recipe directory is exactly the sort of thing that eventually gets pointed at a
user-supplied path, and `full_load` would make that a code execution hole.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .provenance import LoraRef, workflow_hash


class RecipeError(RuntimeError):
    """A recipe is missing, malformed, or asks for something impossible."""


class Recipe(BaseModel):
    """One way of producing one kind of output."""

    model_config = ConfigDict(frozen=True)

    id: str
    version: str = "1.0.0"
    #: What this produces, e.g. ``video.generate`` or ``audio.narrate``. The
    #: router matches on this; it is the reason a recipe outlives a provider.
    capability: str
    description: str = ""

    #: Preferred provider. A hint for the router, not a binding.
    provider: str | None = None
    model: str | None = None
    #: Path to a pinned workflow graph, relative to the recipe file.
    workflow: str | None = None

    prompt_template: str = "{prompt}"
    negative_prompt: str | None = None
    seed: int | None = None
    loras: list[LoraRef] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)

    #: What this is expected to cost and take, per second of output. Estimates,
    #: used to tell an operator what a re-render will cost *before* they approve
    #: it. Measured values are recorded on the render itself.
    estimated_cost_per_second: float | None = None
    estimated_seconds_per_second: float | None = None

    #: Absolute path to the workflow file, resolved at load. Not part of the
    #: recipe's identity -- it differs per machine.
    workflow_path: Path | None = None
    workflow_sha256: str | None = None

    @field_validator("id")
    @classmethod
    def _id_is_a_slug(cls, value: str) -> str:
        if not value or " " in value:
            raise ValueError("recipe id must be a non-empty slug without spaces")
        return value

    def render_prompt(self, prompt: str) -> str:
        """Apply the recipe's template to a scene's visual direction.

        A missing placeholder is the author's decision, not an error: a recipe
        with a fixed prompt is legitimate.
        """
        try:
            return self.prompt_template.format(prompt=prompt)
        except (KeyError, IndexError) as error:
            raise RecipeError(
                f"recipe {self.id} has an unusable prompt_template: {error}"
            ) from error

    def estimate(self, output_seconds: float) -> tuple[float | None, float | None]:
        """(cost in USD, wall-clock seconds) for this much output, if known.

        Returns ``None`` where the recipe has not been benchmarked. The approval
        screen shows "unknown" rather than a fabricated number -- a made-up cost
        estimate is worse than no estimate, because it will be believed.
        """
        cost = (
            round(self.estimated_cost_per_second * output_seconds, 4)
            if self.estimated_cost_per_second is not None
            else None
        )
        seconds = (
            round(self.estimated_seconds_per_second * output_seconds, 1)
            if self.estimated_seconds_per_second is not None
            else None
        )
        return cost, seconds


class RecipeRegistry:
    """Recipes loaded from a directory tree of YAML files."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._by_id: dict[str, Recipe] = {}

    def load(self) -> RecipeRegistry:
        """Read every recipe under the root. Idempotent."""
        self._by_id.clear()
        if not self.root.exists():
            return self

        for path in sorted(self.root.rglob("*.yaml")) + sorted(self.root.rglob("*.yml")):
            recipe = self._load_one(path)
            if recipe.id in self._by_id:
                raise RecipeError(
                    f"duplicate recipe id {recipe.id!r} ({path} and an earlier file). "
                    "Recipe ids are referenced from provenance records and must be unique."
                )
            self._by_id[recipe.id] = recipe
        return self

    def _load_one(self, path: Path) -> Recipe:
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as error:
            raise RecipeError(f"{path} is not valid YAML: {error}") from error
        if not isinstance(payload, dict):
            raise RecipeError(f"{path} must contain a mapping")

        try:
            recipe = Recipe(**payload)
        except Exception as error:  # pydantic validation
            raise RecipeError(f"{path} is not a valid recipe: {error}") from error

        if recipe.workflow:
            workflow_path = (path.parent / recipe.workflow).resolve()
            if not workflow_path.exists():
                raise RecipeError(
                    f"recipe {recipe.id} points at a workflow that does not exist: "
                    f"{workflow_path}. A recipe whose graph is missing cannot be "
                    "reproduced, so this fails at load rather than at render."
                )
            recipe = recipe.model_copy(
                update={
                    "workflow_path": workflow_path,
                    "workflow_sha256": workflow_hash(workflow_path.read_bytes()),
                }
            )
        return recipe

    def get(self, recipe_id: str) -> Recipe:
        recipe = self._by_id.get(recipe_id)
        if recipe is None:
            known = ", ".join(sorted(self._by_id)) or "none loaded"
            raise RecipeError(f"unknown recipe {recipe_id!r}. Known recipes: {known}")
        return recipe

    def for_capability(self, capability: str) -> list[Recipe]:
        return [r for r in self._by_id.values() if r.capability == capability]

    def all(self) -> list[Recipe]:
        return sorted(self._by_id.values(), key=lambda r: r.id)


def default_root() -> Path:
    """``recipes/`` at the repository root.

    Overridable by whoever constructs the registry; this is only the default a
    development checkout wants.
    """
    return Path(__file__).resolve().parents[4] / "recipes"
