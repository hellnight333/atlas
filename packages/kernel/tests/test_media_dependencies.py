"""The Media Factory's dependency graph, one test per invalidation rule (M013).

Each of these was stated as a requirement:

* Script changes            -> invalidate all dependent assets
* Narration changes         -> narration and assembly, but keep the picture
* Visual prompt changes     -> only the visual assets
* Music changes             -> only the assembly
* Publication metadata      -> only the publication

None of them are implemented as rules. They are consequences of the edges, and
these tests exist to prove the edges are drawn correctly -- because a wrong edge
either wastes GPU time or ships something stale, and both are silent.
"""

from __future__ import annotations

from atlas_kernel.media.dependencies import (
    MediaInputs,
    assembly_node,
    build_graph,
    publication_node,
    speech_node,
    visual_node,
)
from atlas_kernel.media.models import Publication, Rendition, Scene
from atlas_kernel.media.recipes import Recipe
from atlas_kernel.media.regeneration import plan_regeneration

VIDEO_RECIPE = Recipe(
    id="video-recipe",
    capability="video.generate",
    version="1.0.0",
    estimated_cost_per_second=0.02,
    estimated_seconds_per_second=14.0,
)
SPEECH_RECIPE = Recipe(id="speech-recipe", capability="speech.generate", version="1.0.0")


def _scenes(count: int = 3) -> list[Scene]:
    return [
        Scene(
            script_id="script",
            index=i,
            heading=f"Beat {i}",
            narration=f"Narration for beat {i}.",
            visual_direction=f"A wide shot, beat {i}.",
            target_seconds=5.0,
        )
        for i in range(count)
    ]


def _inputs(scenes: list[Scene], **overrides) -> MediaInputs:
    payload = {
        "rendition": Rendition(id="rendition-1", episode_id="e", script_id="script"),
        "scenes": scenes,
        "video_recipe": VIDEO_RECIPE,
        "speech_recipe": SPEECH_RECIPE,
        "music_key": "music-v1",
    }
    payload.update(overrides)
    return MediaInputs(**payload)


def _built(scenes: list[Scene], **overrides) -> tuple[dict[str, str], list[Scene]]:
    """A graph that has been built once, and the fingerprints it recorded."""
    graph = build_graph(_inputs(scenes, **overrides))
    return graph.snapshot(), scenes


# -- the five rules -------------------------------------------------------


def test_narration_changes_keep_the_picture() -> None:
    """The rule with the most money attached: a text edit must not throw away
    GPU minutes."""
    scenes = _scenes()
    recorded, _ = _built(scenes)

    scenes[1] = scenes[1].model_copy(update={"narration": "A completely new line."})
    stale = build_graph(_inputs(scenes)).stale(recorded)

    assert speech_node(scenes[1].id) in stale
    assert assembly_node("rendition-1") in stale
    assert visual_node(scenes[1].id) not in stale
    # And no other scene is disturbed at all.
    assert visual_node(scenes[0].id) not in stale
    assert speech_node(scenes[0].id) not in stale


def test_visual_changes_keep_the_narration() -> None:
    scenes = _scenes()
    recorded, _ = _built(scenes)

    scenes[2] = scenes[2].model_copy(update={"visual_direction": "A tight close-up instead."})
    stale = build_graph(_inputs(scenes)).stale(recorded)

    assert visual_node(scenes[2].id) in stale
    assert assembly_node("rendition-1") in stale
    assert speech_node(scenes[2].id) not in stale


def test_music_changes_only_the_assembly() -> None:
    """Nothing was re-rendered; the cut was remade."""
    scenes = _scenes()
    recorded, _ = _built(scenes)

    stale = build_graph(_inputs(scenes, music_key="music-v2")).stale(recorded)

    assert stale == {assembly_node("rendition-1")}


def test_reordering_scenes_only_changes_the_assembly() -> None:
    """A re-cut, not a re-render."""
    scenes = _scenes()
    recorded, _ = _built(scenes)

    scenes[0], scenes[1] = (
        scenes[0].model_copy(update={"index": 1}),
        scenes[1].model_copy(update={"index": 0}),
    )
    stale = build_graph(_inputs(scenes)).stale(recorded)

    assert stale == {assembly_node("rendition-1")}


def test_publication_metadata_changes_only_the_publication() -> None:
    """Re-titling a video does not re-cut it, let alone re-render it."""
    scenes = _scenes()
    publication = Publication(id="pub-1", rendition_id="rendition-1", title="First title")
    recorded, _ = _built(scenes, publication=publication)

    retitled = publication.model_copy(update={"title": "A better title"})
    stale = build_graph(_inputs(scenes, publication=retitled)).stale(recorded)

    assert stale == {publication_node("pub-1")}


def test_a_script_change_invalidates_everything_that_depends_on_it() -> None:
    """Rewriting every scene is the coarse case, and it should behave like the
    sum of the fine ones rather than being special."""
    scenes = _scenes()
    recorded, _ = _built(scenes)

    rewritten = [
        scene.model_copy(
            update={"narration": f"New line {i}.", "visual_direction": f"New shot {i}."}
        )
        for i, scene in enumerate(scenes)
    ]
    stale = build_graph(_inputs(rewritten)).stale(recorded)

    for scene in rewritten:
        assert visual_node(scene.id) in stale
        assert speech_node(scene.id) in stale
    assert assembly_node("rendition-1") in stale


# -- recipes participate --------------------------------------------------


def test_changing_the_recipe_invalidates_what_it_made() -> None:
    """A different recipe genuinely is a different output."""
    scenes = _scenes()
    recorded, _ = _built(scenes)

    tweaked = VIDEO_RECIPE.model_copy(update={"seed": 999})
    stale = build_graph(_inputs(scenes, video_recipe=tweaked)).stale(recorded)

    for scene in scenes:
        assert visual_node(scene.id) in stale
        assert speech_node(scene.id) not in stale
    assert assembly_node("rendition-1") in stale


def test_an_edited_workflow_graph_invalidates_renders() -> None:
    """A graph edited in the ComfyUI GUI keeps its filename and its version
    string. Only the hash notices."""
    scenes = _scenes()
    recorded, _ = _built(
        scenes, video_recipe=VIDEO_RECIPE.model_copy(update={"workflow_sha256": "aaa"})
    )

    stale = build_graph(
        _inputs(scenes, video_recipe=VIDEO_RECIPE.model_copy(update={"workflow_sha256": "bbb"}))
    ).stale(recorded)

    assert visual_node(scenes[0].id) in stale


def test_the_speech_recipe_does_not_disturb_pictures() -> None:
    scenes = _scenes()
    recorded, _ = _built(scenes)

    other_voice = SPEECH_RECIPE.model_copy(update={"model": "a-different-voice"})
    stale = build_graph(_inputs(scenes, speech_recipe=other_voice)).stale(recorded)

    for scene in scenes:
        assert speech_node(scene.id) in stale
        assert visual_node(scene.id) not in stale


# -- shape ----------------------------------------------------------------


def test_a_silent_scene_has_no_speech_node() -> None:
    """Otherwise assembly would depend on something that will never be built."""
    scenes = _scenes(2)
    scenes[0] = scenes[0].model_copy(update={"narration": "   "})
    graph = build_graph(_inputs(scenes))

    assert speech_node(scenes[0].id) not in graph
    assert speech_node(scenes[1].id) in graph


def test_nothing_is_stale_immediately_after_a_build() -> None:
    scenes = _scenes()
    graph = build_graph(_inputs(scenes))
    assert graph.stale(graph.snapshot()) == set()


# -- the plan a person sees ----------------------------------------------


def test_the_plan_names_only_what_changed() -> None:
    scenes = _scenes(5)
    recorded, _ = _built(scenes)
    scenes[2] = scenes[2].model_copy(update={"visual_direction": "Something else entirely."})

    graph = build_graph(_inputs(scenes))
    plan = plan_regeneration(
        graph, recorded, scenes, video_recipe=VIDEO_RECIPE, speech_recipe=SPEECH_RECIPE
    )

    assert plan.scenes_to_rerender() == [scenes[2].id]
    assert plan.scenes_to_revoice() == []
    assert plan.needs_assembly is True
    # Four of five scenes untouched, and the plan can say so.
    assert len(plan.untouched) > len(plan.work)


def test_the_plan_prices_what_it_can() -> None:
    """14 seconds of render per second of output, at $0.02/s, for one 5s scene."""
    scenes = _scenes(3)
    recorded, _ = _built(scenes)
    scenes[0] = scenes[0].model_copy(update={"visual_direction": "Different."})

    plan = plan_regeneration(
        build_graph(_inputs(scenes)),
        recorded,
        scenes,
        video_recipe=VIDEO_RECIPE,
        speech_recipe=SPEECH_RECIPE,
    )

    assert plan.total_seconds == 70.0
    assert plan.total_cost_usd == 0.10
    assert "1m 10s" in plan.summary()
    assert "$0.10" in plan.summary()


def test_an_unbenchmarked_recipe_yields_no_estimate() -> None:
    """A fabricated estimate is worse than none, because it will be believed."""
    scenes = _scenes(2)
    plain = Recipe(id="video-recipe", capability="video.generate")
    recorded, _ = _built(scenes, video_recipe=plain)
    scenes[0] = scenes[0].model_copy(update={"visual_direction": "Different."})

    plan = plan_regeneration(
        build_graph(_inputs(scenes, video_recipe=plain)), recorded, scenes, video_recipe=plain
    )

    assert plan.total_seconds is None
    assert plan.total_cost_usd is None
    assert "No estimate available" in plan.summary()


def test_a_partial_estimate_says_so() -> None:
    """Assembly is not priced, so a plan including it is a floor rather than a
    forecast -- and must not present a partial sum as the answer."""
    scenes = _scenes(2)
    recorded, _ = _built(scenes)
    scenes[0] = scenes[0].model_copy(update={"visual_direction": "Different."})

    plan = plan_regeneration(
        build_graph(_inputs(scenes)), recorded, scenes, video_recipe=VIDEO_RECIPE
    )

    assert plan.needs_assembly is True
    assert plan.fully_estimated is False
    assert "partial estimate" in plan.summary()


def test_an_unchanged_rendition_plans_nothing() -> None:
    scenes = _scenes()
    recorded, _ = _built(scenes)
    plan = plan_regeneration(build_graph(_inputs(scenes)), recorded, scenes)

    assert plan.is_empty
    assert plan.summary() == "Nothing to rebuild; everything is current."


def test_a_first_build_plans_everything() -> None:
    scenes = _scenes(3)
    plan = plan_regeneration(
        build_graph(_inputs(scenes)),
        {},
        scenes,
        video_recipe=VIDEO_RECIPE,
        speech_recipe=SPEECH_RECIPE,
    )

    assert len(plan.scenes_to_rerender()) == 3
    assert len(plan.scenes_to_revoice()) == 3
    assert plan.needs_assembly is True


def test_the_plan_is_ordered_so_dependencies_come_first() -> None:
    scenes = _scenes(2)
    plan = plan_regeneration(build_graph(_inputs(scenes)), {}, scenes)
    roles = [work.role for work in plan.work]
    assert roles.index("assembly") == len(roles) - 1
