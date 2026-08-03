"""Media repository against a real database (M013).

The test database persists between runs, so every id here is unique per run.
A fixed id passes once and fails forever afterwards.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from atlas_kernel import db
from atlas_kernel.media.models import (
    Campaign,
    Episode,
    Publication,
    PublicationStatus,
    Rendition,
    Scene,
    SceneRender,
    Script,
    Visibility,
    WorkStatus,
    fingerprint_scenes,
)
from atlas_kernel.media.repository import MediaRepository

db.init_db()


@pytest.fixture
def repo() -> MediaRepository:
    return MediaRepository()


@pytest.fixture
def episode(repo: MediaRepository) -> Episode:
    campaign = repo.create_campaign(Campaign(name=f"Campaign {uuid4().hex[:8]}"))
    return repo.create_episode(
        Episode(campaign_id=campaign.id, brief="Explain the Atlas kernel in 30 seconds.")
    )


def _script_with_scenes(
    repo: MediaRepository, episode: Episode, count: int = 3
) -> tuple[Script, list[Scene]]:
    script = repo.create_script(
        Script(
            episode_id=episode.id,
            version=repo.next_script_version(episode.id),
            authored_by="test",
        )
    )
    scenes = repo.replace_scenes(
        script.id,
        [
            Scene(
                script_id=script.id,
                index=i,
                heading=f"Beat {i}",
                narration=f"Narration {i}.",
                visual_direction=f"Shot {i}.",
                target_seconds=4.0 + i,
            )
            for i in range(count)
        ],
    )
    return script, scenes


def test_campaign_episode_script_scene_round_trip(repo: MediaRepository, episode: Episode) -> None:
    script, scenes = _script_with_scenes(repo, episode, count=4)

    assert repo.get_episode(episode.id) == episode
    assert repo.get_script(script.id) == script
    assert len(scenes) == 4
    assert [scene.index for scene in scenes] == [0, 1, 2, 3]

    loaded = repo.get_scene(scenes[2].id)
    assert loaded is not None
    assert loaded.narration == "Narration 2."
    assert loaded.target_seconds == 6.0


def test_scenes_come_back_in_script_order(repo: MediaRepository, episode: Episode) -> None:
    """Order is meaning, and it must survive the database rather than the
    insertion sequence."""
    script = repo.create_script(Script(episode_id=episode.id, version=1))
    repo.replace_scenes(
        script.id,
        [Scene(script_id=script.id, index=i, narration=f"n{i}") for i in (3, 0, 2, 1)],
    )
    assert [scene.index for scene in repo.list_scenes(script.id)] == [0, 1, 2, 3]


def test_script_versions_increment_and_do_not_overwrite(
    repo: MediaRepository, episode: Episode
) -> None:
    """A rewrite must not destroy the script a shipped video was built from."""
    first, _ = _script_with_scenes(repo, episode)
    second, _ = _script_with_scenes(repo, episode)

    assert first.version == 1
    assert second.version == 2
    assert repo.get_script(first.id) is not None
    latest = repo.latest_script(episode.id)
    assert latest is not None and latest.id == second.id


def test_replace_scenes_is_a_whole_set_operation(repo: MediaRepository, episode: Episode) -> None:
    """Scenes only mean something as an ordered whole; a shorter rewrite must
    not leave orphans from the longer one behind."""
    script, _ = _script_with_scenes(repo, episode, count=5)
    repo.replace_scenes(
        script.id,
        [Scene(script_id=script.id, index=i, narration=f"new {i}") for i in range(2)],
    )
    remaining = repo.list_scenes(script.id)
    assert len(remaining) == 2
    assert all(scene.narration.startswith("new") for scene in remaining)


def test_rendition_tracks_staleness_across_a_scene_edit(
    repo: MediaRepository, episode: Episode
) -> None:
    """The behaviour partial regeneration depends on."""
    script, scenes = _script_with_scenes(repo, episode)
    rendition = repo.create_rendition(
        Rendition(
            episode_id=episode.id,
            script_id=script.id,
            scene_fingerprint=fingerprint_scenes(scenes),
            status=WorkStatus.READY,
        )
    )

    assert rendition.is_stale_against(repo.list_scenes(script.id)) is False

    repo.update_scene(scenes[1].id, narration="Rewritten narration.")
    reloaded = repo.get_rendition(rendition.id)
    assert reloaded is not None
    assert reloaded.is_stale_against(repo.list_scenes(script.id)) is True


def test_scene_renders_are_independent_units_of_work(
    repo: MediaRepository, episode: Episode
) -> None:
    """One scene failing is one scene failing, not a dead video."""
    script, scenes = _script_with_scenes(repo, episode)
    rendition = repo.create_rendition(Rendition(episode_id=episode.id, script_id=script.id))

    for scene in scenes:
        repo.create_scene_render(
            SceneRender(
                rendition_id=rendition.id,
                scene_id=scene.id,
                index=scene.index,
                source_fingerprint=scene.content_fingerprint(),
            )
        )

    renders = repo.list_scene_renders(rendition.id)
    assert [r.index for r in renders] == [0, 1, 2]

    repo.update_scene_render(renders[0].id, status=WorkStatus.READY, media_asset_id="asset-a")
    repo.update_scene_render(renders[1].id, status=WorkStatus.FAILED, error="provider timeout")

    after = repo.list_scene_renders(rendition.id)
    assert after[0].status is WorkStatus.READY
    assert after[0].media_asset_id == "asset-a"
    assert after[1].status is WorkStatus.FAILED
    assert after[1].error == "provider timeout"
    # Untouched, which is the entire point of per-scene work.
    assert after[2].status is WorkStatus.PENDING


def test_one_scene_render_per_scene_per_rendition(repo: MediaRepository, episode: Episode) -> None:
    """Re-running a scene updates its render; it does not accumulate rows."""
    script, scenes = _script_with_scenes(repo, episode, count=1)
    rendition = repo.create_rendition(Rendition(episode_id=episode.id, script_id=script.id))
    render = SceneRender(rendition_id=rendition.id, scene_id=scenes[0].id, index=0)

    repo.create_scene_render(render)
    repo.create_scene_render(render.model_copy(update={"id": str(uuid4())}))

    assert len(repo.list_scene_renders(rendition.id)) == 1


def test_stale_scene_is_identifiable_individually(repo: MediaRepository, episode: Episode) -> None:
    """So regeneration re-runs one scene rather than all of them."""
    script, scenes = _script_with_scenes(repo, episode)
    rendition = repo.create_rendition(Rendition(episode_id=episode.id, script_id=script.id))
    for scene in scenes:
        repo.create_scene_render(
            SceneRender(
                rendition_id=rendition.id,
                scene_id=scene.id,
                index=scene.index,
                status=WorkStatus.READY,
                source_fingerprint=scene.content_fingerprint(),
            )
        )

    repo.update_scene(scenes[1].id, visual_direction="A completely different shot.")

    current = {scene.id: scene for scene in repo.list_scenes(script.id)}
    stale = [
        render
        for render in repo.list_scene_renders(rendition.id)
        if render.source_fingerprint != current[render.scene_id].content_fingerprint()
    ]

    assert [render.index for render in stale] == [1]


def test_publication_round_trip_defaults_to_private(
    repo: MediaRepository, episode: Episode
) -> None:
    script, _ = _script_with_scenes(repo, episode)
    rendition = repo.create_rendition(Rendition(episode_id=episode.id, script_id=script.id))

    publication = repo.create_publication(
        Publication(rendition_id=rendition.id, title="Test upload")
    )
    assert publication.visibility is Visibility.PRIVATE

    updated = repo.update_publication(
        publication.id,
        status=PublicationStatus.PUBLISHED,
        remote_id="abc123",
        remote_url="https://youtu.be/abc123",
        tags=["atlas", "test"],
    )
    assert updated is not None
    assert updated.status is PublicationStatus.PUBLISHED
    assert updated.remote_id == "abc123"
    assert updated.tags == ["atlas", "test"]
    # Visibility was not part of the update and must not have drifted.
    assert updated.visibility is Visibility.PRIVATE


def test_updates_ignore_fields_that_are_not_allowed(
    repo: MediaRepository, episode: Episode
) -> None:
    """The update helpers take **kwargs, so the allow-list is what stops a typo
    or a hostile key from reaching the SQL."""
    updated = repo.update_episode(episode.id, title="Real title", campaign_id="hijacked")
    assert updated is not None
    assert updated.title == "Real title"
    assert updated.campaign_id == episode.campaign_id


def test_media_tables_have_no_orphans_after_use() -> None:
    assert db.check_integrity()["healthy"] is True
