"""What a change actually costs, before anyone commits to it.

Turns a dependency graph into the question a person can answer:

    Scene 3 changed.
    Re-render 1 of 5 scenes — estimated 2m 18s, estimated $0.11.
    Approve / Reject.

Two things this is careful about, both of which matter more than they look.

**Unknown is reported as unknown.** A recipe that has never been benchmarked
produces no estimate, and the plan says so rather than inventing a number.
A fabricated estimate is worse than none, because it will be believed and then
used to decide.

**Nothing is rebuilt that did not change.** The plan comes from the graph, not
from a rule someone wrote about narration implying pictures. If the picture's
inputs are untouched, the picture is not in the plan -- and that is the whole
economic argument for the graph.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..dependency import DependencyGraph, Node
from .dependencies import ASSEMBLY, PUBLICATION, SPEECH, VISUAL
from .models import Scene
from .recipes import Recipe


@dataclass(frozen=True)
class PlannedWork:
    """One thing that has to be redone."""

    node_id: str
    role: str
    #: Human-facing, e.g. "Scene 3 — picture".
    description: str
    scene_id: str | None = None
    scene_index: int | None = None
    estimated_seconds: float | None = None
    estimated_cost_usd: float | None = None

    @property
    def has_estimate(self) -> bool:
        return self.estimated_seconds is not None or self.estimated_cost_usd is not None


@dataclass
class RegenerationPlan:
    """Everything a change implies, priced where it can be."""

    work: list[PlannedWork] = field(default_factory=list)
    #: Nodes that are current and will be left alone. The reassuring half of
    #: the message: "four of five scenes are untouched".
    untouched: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.work

    @property
    def total_seconds(self) -> float | None:
        known = [w.estimated_seconds for w in self.work if w.estimated_seconds is not None]
        return round(sum(known), 1) if known else None

    @property
    def total_cost_usd(self) -> float | None:
        known = [w.estimated_cost_usd for w in self.work if w.estimated_cost_usd is not None]
        return round(sum(known), 4) if known else None

    @property
    def fully_estimated(self) -> bool:
        """Whether every item has an estimate.

        When false, the totals are a floor rather than a forecast, and the
        interface must say so instead of presenting a partial sum as the answer.
        """
        return bool(self.work) and all(w.has_estimate for w in self.work)

    def scenes_to_rerender(self) -> list[str]:
        return sorted({w.scene_id for w in self.work if w.role == VISUAL and w.scene_id})

    def scenes_to_revoice(self) -> list[str]:
        return sorted({w.scene_id for w in self.work if w.role == SPEECH and w.scene_id})

    @property
    def needs_assembly(self) -> bool:
        return any(w.role == ASSEMBLY for w in self.work)

    @property
    def needs_publication(self) -> bool:
        return any(w.role == PUBLICATION for w in self.work)

    def summary(self) -> str:
        """One line, for a person about to approve or reject."""
        if self.is_empty:
            return "Nothing to rebuild; everything is current."

        bits: list[str] = []
        if visuals := self.scenes_to_rerender():
            bits.append(f"re-render {len(visuals)} scene(s)")
        if voices := self.scenes_to_revoice():
            bits.append(f"re-voice {len(voices)} scene(s)")
        if self.needs_assembly:
            bits.append("reassemble")
        if self.needs_publication:
            bits.append("update the publication")

        line = ", ".join(bits).capitalize()
        seconds, cost = self.total_seconds, self.total_cost_usd
        if seconds is None and cost is None:
            return f"{line}. No estimate available."

        parts = []
        if seconds is not None:
            parts.append(f"~{_duration(seconds)}")
        if cost is not None:
            parts.append(f"~${cost:.2f}")
        qualifier = "" if self.fully_estimated else " (partial estimate)"
        return f"{line}. {' · '.join(parts)}{qualifier}."


def _duration(seconds: float) -> str:
    if seconds < 60:
        return f"{int(round(seconds))}s"
    minutes, remainder = divmod(int(round(seconds)), 60)
    return f"{minutes}m {remainder:02d}s"


def plan_regeneration(
    graph: DependencyGraph,
    recorded: dict[str, str],
    scenes: list[Scene],
    *,
    video_recipe: Recipe | None = None,
    speech_recipe: Recipe | None = None,
) -> RegenerationPlan:
    """Read a plan off the graph.

    ``recorded`` is what was last built. Everything the graph reports as stale
    goes in the plan, in dependency order, so a caller executing it top to
    bottom never rebuilds something before what it is built from.
    """
    by_scene = {scene.id: scene for scene in scenes}
    stale_nodes = graph.rebuild_plan(recorded)
    stale_ids = {node.id for node in stale_nodes}

    work: list[PlannedWork] = []
    for node in stale_nodes:
        role = node.labels.get("role", "")
        scene = by_scene.get(node.labels.get("scene_id", ""))
        work.append(_planned(node, role, scene, video_recipe, speech_recipe))

    untouched = sorted(node.id for node in graph.nodes() if node.id not in stale_ids)
    return RegenerationPlan(work=work, untouched=untouched)


def _planned(
    node: Node,
    role: str,
    scene: Scene | None,
    video_recipe: Recipe | None,
    speech_recipe: Recipe | None,
) -> PlannedWork:
    index = int(node.labels["index"]) if "index" in node.labels else None
    position = f"Scene {index + 1}" if index is not None else "The rendition"

    if role == VISUAL:
        cost, seconds = _estimate(video_recipe, scene)
        return PlannedWork(
            node_id=node.id,
            role=role,
            description=f"{position} — picture",
            scene_id=scene.id if scene else None,
            scene_index=index,
            estimated_seconds=seconds,
            estimated_cost_usd=cost,
        )

    if role == SPEECH:
        cost, seconds = _estimate(speech_recipe, scene)
        return PlannedWork(
            node_id=node.id,
            role=role,
            description=f"{position} — narration",
            scene_id=scene.id if scene else None,
            scene_index=index,
            estimated_seconds=seconds,
            estimated_cost_usd=cost,
        )

    if role == ASSEMBLY:
        # Not estimated. Assembly is local ffmpeg work whose cost is a few
        # seconds of CPU, and pricing it would imply a precision that is not
        # there.
        return PlannedWork(node_id=node.id, role=role, description="Reassemble the video")

    if role == PUBLICATION:
        return PlannedWork(node_id=node.id, role=role, description="Update the published metadata")

    return PlannedWork(node_id=node.id, role=role or "unknown", description=node.id)


def _estimate(recipe: Recipe | None, scene: Scene | None) -> tuple[float | None, float | None]:
    if recipe is None or scene is None:
        return (None, None)
    return recipe.estimate(scene.target_seconds)
