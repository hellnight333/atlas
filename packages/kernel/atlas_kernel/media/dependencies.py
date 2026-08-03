"""The Media Factory's dependency graph, declared for the kernel to reason about.

The kernel knows only "A depends on B". This module is where a *renderer*
decides what A and B are. Everything media-specific about invalidation lives
here and nowhere else.

The shape:

    scene visual  ─┐
                   ├─► scene render (picture)  ─┐
    video recipe  ─┘                            │
                                                ├─► assembly ─► publication
    scene narration ─┬─► scene render (voice) ──┤       ▲
    speech recipe  ──┘                          │       │
                                                │       │
    scene layout ───────────────────────────────┘       │
    music ──────────────────────────────────────────────┘
    publication metadata ───────────────────────────────┘

Read the consequences off the picture rather than writing them as rules:

* Rewrite the narration -> the voice and the assembly move; **the picture does
  not**, because nothing it depends on changed.
* Change the visual direction -> the picture and the assembly move; the voice
  does not.
* Change the music -> only the assembly moves.
* Reorder scenes or change a duration -> only the assembly moves; both renders
  survive.
* Edit the title -> only the publication moves.
* Change the recipe or its pinned workflow -> every render made with it moves,
  because a different recipe genuinely is a different output.

None of those are special cases anyone implemented. They fall out of the edges.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..dependency import DependencyGraph, fingerprint
from .models import Publication, Rendition, Scene
from .recipes import Recipe

# Node id prefixes. Opaque to the kernel; meaningful only here.
VISUAL = "visual"
SPEECH = "speech"
ASSEMBLY = "assembly"
PUBLICATION = "publication"
MUSIC = "music"
RECIPE = "recipe"


def visual_node(scene_id: str) -> str:
    return f"{VISUAL}:{scene_id}"


def speech_node(scene_id: str) -> str:
    return f"{SPEECH}:{scene_id}"


def assembly_node(rendition_id: str) -> str:
    return f"{ASSEMBLY}:{rendition_id}"


def publication_node(publication_id: str) -> str:
    return f"{PUBLICATION}:{publication_id}"


def recipe_node(recipe_id: str) -> str:
    return f"{RECIPE}:{recipe_id}"


@dataclass(frozen=True)
class MediaInputs:
    """Everything a rendition is built from, other than the scenes themselves."""

    rendition: Rendition
    scenes: list[Scene]
    video_recipe: Recipe | None = None
    speech_recipe: Recipe | None = None
    #: Identity of the bed track. A recipe id, an asset id, or a file hash --
    #: whatever identifies "this music" to the caller.
    music_key: str | None = None
    publication: Publication | None = None
    #: Assembly settings that change the cut: transitions, whether captions are
    #: burned. Not settings that only change encoding speed.
    assembly_options: dict | None = None


def _recipe_fingerprint(recipe: Recipe | None) -> str:
    """A recipe's identity for invalidation purposes.

    The pinned workflow hash participates: a graph edited in the ComfyUI GUI
    keeps its filename and its version string, and only the hash notices. A
    render made from the old graph is not reproducible by the new one, so it is
    genuinely stale.
    """
    if recipe is None:
        return fingerprint(None)
    return fingerprint(
        recipe.id,
        recipe.version,
        # The model makes the output, so it participates. The *provider* does
        # not: it is a preference the router may override, and including it
        # would invalidate renders whenever scheduling changed rather than
        # when the result would.
        recipe.model,
        recipe.workflow_sha256,
        recipe.seed,
        recipe.prompt_template,
        recipe.negative_prompt,
        sorted(recipe.parameters.items()),
        [(lora.name, lora.weight, lora.version) for lora in recipe.loras],
    )


def build_graph(inputs: MediaInputs) -> DependencyGraph:
    """Declare what depends on what, for one rendition."""
    graph = DependencyGraph()
    scenes = sorted(inputs.scenes, key=lambda scene: scene.index)

    video_recipe_id = recipe_node(inputs.video_recipe.id) if inputs.video_recipe else None
    if video_recipe_id:
        graph.add(video_recipe_id, fingerprint=_recipe_fingerprint(inputs.video_recipe))

    speech_recipe_id = recipe_node(inputs.speech_recipe.id) if inputs.speech_recipe else None
    if speech_recipe_id and speech_recipe_id != video_recipe_id:
        graph.add(speech_recipe_id, fingerprint=_recipe_fingerprint(inputs.speech_recipe))

    assembly_dependencies: list[str] = []

    for scene in scenes:
        visual = visual_node(scene.id)
        graph.add(
            visual,
            fingerprint=scene.visual_fingerprint(),
            depends_on=[video_recipe_id] if video_recipe_id else [],
            labels={"scene_id": scene.id, "index": str(scene.index), "role": VISUAL},
        )
        assembly_dependencies.append(visual)

        # A scene with nothing to say has no voice to render, and adding an
        # empty node would make the assembly depend on something that will
        # never be built.
        if scene.narration.strip():
            speech = speech_node(scene.id)
            graph.add(
                speech,
                fingerprint=scene.narration_fingerprint(),
                depends_on=[speech_recipe_id] if speech_recipe_id else [],
                labels={"scene_id": scene.id, "index": str(scene.index), "role": SPEECH},
            )
            assembly_dependencies.append(speech)

    assembly = assembly_node(inputs.rendition.id)
    graph.add(
        assembly,
        # Layout and music are assembly's *own* inputs: they change the cut
        # without changing anything that was rendered.
        fingerprint=fingerprint(
            # Which scene sits where, in order -- not merely the set of
            # positions. Two scenes of equal length swapping places leaves the
            # multiset of layout fingerprints identical, so hashing those alone
            # made a reordering invisible and would have shipped an unchanged
            # cut for a changed script.
            [(scene.id, scene.layout_fingerprint()) for scene in scenes],
            inputs.music_key,
            sorted((inputs.assembly_options or {}).items()),
            inputs.rendition.kind.value,
        ),
        depends_on=assembly_dependencies,
        labels={"rendition_id": inputs.rendition.id, "role": ASSEMBLY},
    )

    if inputs.publication is not None:
        publication = inputs.publication
        graph.add(
            publication_node(publication.id),
            # Metadata only. Re-titling a video does not re-cut it.
            fingerprint=fingerprint(
                publication.title,
                publication.description,
                tuple(publication.tags),
                publication.visibility.value,
                publication.platform,
                publication.thumbnail_asset_id,
            ),
            depends_on=[assembly],
            labels={"publication_id": publication.id, "role": PUBLICATION},
        )

    graph.validate()
    return graph
