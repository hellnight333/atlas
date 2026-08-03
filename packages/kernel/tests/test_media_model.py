"""Content/rendering separation and staleness detection (M013).

The layering test is the important one. Everything else here can be re-derived
by reading the code; the layering rule is a decision that a well-meaning change
could quietly undo, and its cost only shows up a milestone later when the first
non-video renderer needs a migration across the whole content model.
"""

from __future__ import annotations

import inspect
from uuid import uuid4

import pytest

from atlas_kernel.media.models import (
    Campaign,
    Episode,
    Publication,
    PublicationStatus,
    Rendition,
    RenditionKind,
    Scene,
    SceneRender,
    Script,
    Visibility,
    WorkStatus,
    fingerprint_scenes,
)

# Words that only make sense once an output form has been chosen. A content
# entity that grows one of these has broken the seam.
MEDIUM_SPECIFIC = (
    "asset",
    "audio",
    "codec",
    "fps",
    "frame",
    "height",
    "media",
    "provider",
    "recipe",
    "render",
    "resolution",
    "thumbnail",
    "video",
    "width",
)


def _scenes(count: int = 3, script_id: str = "script-1") -> list[Scene]:
    return [
        Scene(
            script_id=script_id,
            index=i,
            heading=f"Beat {i}",
            narration=f"Narration for beat {i}.",
            visual_direction=f"A wide shot, beat {i}.",
            target_seconds=5.0,
        )
        for i in range(count)
    ]


@pytest.mark.parametrize("model", [Campaign, Episode, Script, Scene])
def test_content_entities_carry_no_medium_specific_fields(model: type) -> None:
    """A blog renderer must never inherit a field only video needed.

    Content describes what is said. The moment a Scene grows `media_asset_id`,
    every future output form has to reason about video, and the seam is gone.
    """
    for name in model.model_fields:
        for banned in MEDIUM_SPECIFIC:
            assert banned not in name.lower(), (
                f"{model.__name__}.{name} is medium-specific. It belongs on "
                "Rendition or SceneRender, not on the content layer. "
                "See docs/VIDEO_FACTORY.md."
            )


def test_rendering_entities_are_where_media_lives() -> None:
    """The counterpart: the rendering layer is allowed to know about media."""
    assert "media_asset_id" in SceneRender.model_fields
    assert "audio_asset_id" in SceneRender.model_fields
    assert "asset_id" in Rendition.model_fields


def test_a_scene_render_points_at_a_scene_rather_than_duplicating_it() -> None:
    """Rendering references content; it does not copy it.

    If narration were duplicated onto SceneRender, editing the script would
    leave two disagreeing sources of truth.
    """
    assert "scene_id" in SceneRender.model_fields
    assert "narration" not in SceneRender.model_fields
    assert "visual_direction" not in SceneRender.model_fields


def test_media_models_do_not_import_tooling() -> None:
    """The domain model stays free of tooling.

    ffmpeg wrappers, provider SDKs and HTTP clients belong in adapters. A domain
    model that imports them cannot be reused by a renderer that wants none of
    them.

    Parsed rather than grepped: prose about ffmpeg in a docstring is fine and
    often necessary, an `import` of it is not.
    """
    import ast

    from atlas_kernel.media import models

    banned = {"subprocess", "ffmpeg", "googleapiclient", "google", "requests", "httpx", "boto3"}
    imported: set[str] = set()
    for node in ast.walk(ast.parse(inspect.getsource(models))):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])

    offenders = imported & banned
    assert not offenders, f"media.models must not import {sorted(offenders)}"


def test_scene_fingerprint_tracks_content_not_identity() -> None:
    """Two scenes saying the same thing fingerprint the same.

    Identity must not participate, or a rewrite that happens to produce
    identical text would still be reported as a change.
    """
    left = Scene(script_id="a", index=0, narration="Hello", visual_direction="A field")
    right = Scene(script_id="b", index=0, narration="Hello", visual_direction="A field")
    assert left.content_fingerprint() == right.content_fingerprint()

    changed = right.model_copy(update={"narration": "Goodbye"})
    assert changed.content_fingerprint() != right.content_fingerprint()


def test_metadata_changes_do_not_invalidate_a_cut() -> None:
    """Only authored content should be able to make a video stale."""
    scene = Scene(script_id="a", index=0, narration="Hello")
    tagged = scene.model_copy(update={"metadata": {"note": "checked by Ayoub"}})
    assert tagged.content_fingerprint() == scene.content_fingerprint()


def test_reordering_scenes_changes_the_fingerprint() -> None:
    """Order is meaning. Swapping two beats is a different video."""
    scenes = _scenes(3)
    original = fingerprint_scenes(scenes)

    swapped = [
        scenes[0].model_copy(update={"index": 1}),
        scenes[1].model_copy(update={"index": 0}),
        scenes[2],
    ]
    assert fingerprint_scenes(swapped) != original


def test_fingerprint_is_stable_against_row_order() -> None:
    """A database returning rows in another order is not a content change."""
    scenes = _scenes(4)
    assert fingerprint_scenes(scenes) == fingerprint_scenes(list(reversed(scenes)))


def test_a_rendition_goes_stale_when_its_scenes_change() -> None:
    """The whole point of the fingerprint: never ship a cut that lies."""
    scenes = _scenes(3)
    rendition = Rendition(
        episode_id="ep", script_id="script-1", scene_fingerprint=fingerprint_scenes(scenes)
    )

    assert rendition.is_stale_against(scenes) is False

    edited = [scenes[0], scenes[1].model_copy(update={"narration": "Rewritten."}), scenes[2]]
    assert rendition.is_stale_against(edited) is True


def test_an_unbuilt_rendition_is_not_stale() -> None:
    """Nothing has been claimed yet, so nothing can be out of date."""
    assert Rendition(episode_id="ep", script_id="s").is_stale_against(_scenes()) is False


def test_scene_validation_rejects_nonsense() -> None:
    with pytest.raises(ValueError):
        Scene(script_id="a", index=-1)
    with pytest.raises(ValueError):
        Scene(script_id="a", index=0, target_seconds=0)
    with pytest.raises(ValueError):
        Script(episode_id="e", version=0)


def test_publication_defaults_are_private() -> None:
    """Publishing defaults must never be public, at any layer."""
    publication = Publication(rendition_id=str(uuid4()))
    assert publication.visibility is Visibility.PRIVATE
    assert publication.status is PublicationStatus.PENDING_APPROVAL


def test_defaults_are_the_conservative_ones() -> None:
    assert Episode(campaign_id="c", brief="b").status is WorkStatus.PENDING
    assert Rendition(episode_id="e", script_id="s").kind is RenditionKind.VIDEO_1080P
    assert Rendition(episode_id="e", script_id="s").status is WorkStatus.PENDING
