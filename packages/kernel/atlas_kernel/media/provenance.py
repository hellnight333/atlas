"""What it would take to make this exact thing again.

Every render permanently records how it was made. Not for auditing -- for
*reproduction*. Years from now Atlas should be able to read one of these rows
and produce the same output, or say precisely why it cannot.

That is a long-term advantage and a short-lived opportunity: provenance not
captured at render time cannot be reconstructed afterwards at any price. A seed
that was never written down is gone.

Two rules hold this together:

* **The kernel never inspects ``provider_extra``.** Whatever ComfyUI, Wan,
  Seedance, Veo or Kling need to say about themselves goes in there, opaque.
  The moment business logic branches on its contents, providers have stopped
  being disposable.
* **Absence is recorded as absence.** A provider that cannot report its model
  version stores ``None``, which is a fact. Substituting a plausible default
  would make an unreproducible render look reproducible, which is worse than
  admitting the gap.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LoraRef(BaseModel):
    """One LoRA and how strongly it was applied.

    The weight matters as much as the identity: the same stack at different
    strengths is a different render.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    weight: float = 1.0
    #: Hash or revision of the weights file, when the provider knows it. Names
    #: get reused; a file's contents do not.
    version: str | None = None


class RenderProvenance(BaseModel):
    """The complete record of one render.

    Frozen: provenance describes something that already happened, and a record
    of the past that can be edited is not a record.
    """

    model_config = ConfigDict(frozen=True)

    # -- who made it --------------------------------------------------------
    provider: str
    model: str | None = None
    model_version: str | None = None

    # -- what it was told to do --------------------------------------------
    recipe_id: str
    recipe_version: str = "0"
    #: The workflow or graph the recipe pinned -- for ComfyUI, the API graph.
    workflow: str | None = None
    #: Hash of that workflow's contents. A graph edited in a GUI is not the
    #: same graph, whatever it is still called.
    workflow_hash: str | None = None

    prompt: str = ""
    negative_prompt: str | None = None
    #: None when the provider does not expose one. Recorded honestly rather
    #: than defaulted, because a wrong seed is worse than a missing seed.
    seed: int | None = None
    loras: list[LoraRef] = Field(default_factory=list)
    #: Fully resolved -- what the provider was actually given, after recipe
    #: defaults were applied. Not the recipe's declaration.
    parameters: dict[str, Any] = Field(default_factory=dict)

    # -- what it cost -------------------------------------------------------
    #: Measured, not estimated. Feeds the estimates the approval screen shows
    #: before asking whether to re-render a scene.
    render_ms: int | None = None
    cost_usd: float | None = None

    # -- provider's own business -------------------------------------------
    #: Opaque to the kernel, forever. Never branch on this.
    provider_extra: dict[str, Any] = Field(default_factory=dict)

    rendered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def reproduction_key(self) -> str:
        """Identity of the *inputs*, ignoring the outcome.

        Two renders sharing this key were asked for the same thing. Cost and
        timing are excluded because they describe what happened, not what was
        requested -- a slower run of identical inputs is still the same render.
        """
        material = {
            "provider": self.provider,
            "model": self.model,
            "model_version": self.model_version,
            "recipe_id": self.recipe_id,
            "recipe_version": self.recipe_version,
            "workflow_hash": self.workflow_hash,
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "seed": self.seed,
            "loras": [lora.model_dump() for lora in self.loras],
            "parameters": self.parameters,
        }
        encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]

    def is_reproducible(self) -> tuple[bool, list[str]]:
        """Whether this render could actually be made again, and what is missing.

        Honest rather than optimistic. A render without a seed or without a
        pinned workflow is not reproducible, and Atlas should say so at the
        point someone asks -- not imply it and disappoint them later.
        """
        missing: list[str] = []
        if not self.provider:
            missing.append("provider")
        if not self.recipe_id:
            missing.append("recipe_id")
        if self.model is None:
            missing.append("model")
        if self.workflow is not None and self.workflow_hash is None:
            missing.append("workflow_hash")
        if self.seed is None:
            missing.append("seed")
        return (not missing, missing)


def workflow_hash(payload: str | bytes | dict[str, Any]) -> str:
    """Content hash of a workflow definition.

    Takes the contents rather than a path, because the point is to detect a
    graph that changed while keeping its filename -- which is exactly what
    happens when someone edits it in the ComfyUI GUI and saves over the top.
    """
    if isinstance(payload, dict):
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    elif isinstance(payload, str):
        raw = payload.encode("utf-8")
    else:
        raw = payload
    return hashlib.sha256(raw).hexdigest()
