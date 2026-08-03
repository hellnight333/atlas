"""The approval gate (M013 step 6).

Two properties this exists to prove.

**Approval is on the outcome.** The question is "publish this?", not "may Atlas
re-render scene three?". The plan is attached as context -- cost, duration --
but nobody is asked to authorise an internal step.

**One gate, then unattended execution.** After approval, renders, reassembly and
upload happen without a second confirmation. The safety property that makes
approving-in-advance legitimate is that the approval binds to a specific
outcome: if anything that would change the result moves in between, the upload
is refused rather than honoured.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from atlas_kernel import db
from atlas_kernel.approval.models import ApprovalScope
from atlas_kernel.composition_root import create_runtime
from atlas_kernel.dependency_store import DependencyStore
from atlas_kernel.media import capabilities, ffmpeg
from atlas_kernel.media.assembly.base import AssemblerRegistry
from atlas_kernel.media.assembly.video import VideoAssembler, VideoFormat
from atlas_kernel.media.assembly_service import AssemblyService
from atlas_kernel.media.models import (
    Episode,
    Publication,
    PublicationStatus,
    Rendition,
    Scene,
    Script,
    Series,
    Visibility,
)
from atlas_kernel.media.providers.mock import (
    MockMusicProvider,
    MockNarrationProvider,
    MockVideoProvider,
)
from atlas_kernel.media.publish_gate import PublishGate, PublishRefused
from atlas_kernel.media.publishing import (
    PublicVisibilityRefused,
    PublishError,
    PublishRequest,
    RecordingPublisher,
    assert_not_public,
)
from atlas_kernel.media.recipes import RecipeRegistry, default_root
from atlas_kernel.media.registry import MediaProviderRegistry, ProviderRegistration
from atlas_kernel.media.render_service import SceneRenderService
from atlas_kernel.media.repository import MediaRepository

pytestmark = pytest.mark.skipif(
    not ffmpeg.available(), reason="ffmpeg and ffprobe are required for media tests"
)

db.init_db()

FAST = VideoFormat(width=320, height=180, fps=12, preset="ultrafast", crf=30)
VIDEO_RECIPE = "mock-slate-1080p"
SPEECH_RECIPE = "mock-narration"


@pytest.fixture
def world(tmp_path: Path):
    media = MediaRepository()
    runtime = create_runtime()
    recipes = RecipeRegistry(default_root()).load()

    providers = MediaProviderRegistry()
    for provider, capability in (
        (MockVideoProvider(workspace=tmp_path / "v"), capabilities.VIDEO_GENERATE),
        (MockNarrationProvider(workspace=tmp_path / "a"), capabilities.SPEECH_GENERATE),
        (MockMusicProvider(workspace=tmp_path / "m"), capabilities.MUSIC_GENERATE),
    ):
        providers.register(ProviderRegistration(provider=provider, capability=capability))

    assemblers = AssemblerRegistry()
    assemblers.register(VideoAssembler(FAST))

    series = media.create_series(Series(name=f"Series {uuid4().hex[:8]}"))
    episode = media.create_episode(Episode(series_id=series.id, brief="Explain Atlas."))
    script = media.create_script(Script(episode_id=episode.id, version=1))
    scenes = media.replace_scenes(
        script.id,
        [
            Scene(
                script_id=script.id,
                index=i,
                heading=f"Beat {i}",
                narration=f"Narration for beat {i}.",
                visual_direction=f"A shot, beat {i}.",
                target_seconds=1.0,
            )
            for i in range(2)
        ],
    )
    rendition = media.create_rendition(Rendition(episode_id=episode.id, script_id=script.id))
    publication = media.create_publication(
        Publication(
            rendition_id=rendition.id,
            title="Explaining the Atlas kernel",
            description="A short explainer.",
            tags=["atlas", "test"],
            visibility=Visibility.PRIVATE,
        )
    )

    publisher = RecordingPublisher()
    gate = PublishGate(
        media_repository=media,
        approvals=runtime.approval_service,
        dependencies=DependencyStore(),
        renderer=SceneRenderService(
            media_repository=media,
            providers=providers,
            recipes=recipes,
            asset_service=runtime.asset_service,
            workspace=tmp_path / "renders",
            poll_interval=0.01,
        ),
        assembler=AssemblyService(
            media_repository=media,
            assemblers=assemblers,
            asset_service=runtime.asset_service,
            workspace=tmp_path / "assembly",
            providers=providers,
            recipes=recipes,
        ),
        publisher=publisher,
        recipes=recipes,
        asset_service=runtime.asset_service,
    )

    return {
        "media": media,
        "runtime": runtime,
        "gate": gate,
        "publisher": publisher,
        "rendition": rendition,
        "publication": publication,
        "scenes": scenes,
        "script_id": script.id,
    }


def _prepare(world, publication=None):
    return world["gate"].prepare(
        world["media"].get_rendition(world["rendition"].id),
        world["media"].list_scenes(world["script_id"]),
        publication or world["publication"],
        video_recipe_id=VIDEO_RECIPE,
        speech_recipe_id=SPEECH_RECIPE,
    )


def _execute(world, approval_id, publication=None):
    return world["gate"].execute(
        approval_id,
        world["media"].get_rendition(world["rendition"].id),
        world["media"].list_scenes(world["script_id"]),
        publication or world["media"].get_publication(world["publication"].id),
        video_recipe_id=VIDEO_RECIPE,
        speech_recipe_id=SPEECH_RECIPE,
        music_recipe_id="mock-music-bed",
    )


# -- the outcome is what is approved --------------------------------------


def test_the_request_describes_the_outcome_not_the_steps(world) -> None:
    """A person is shown the video and the metadata. They are not asked to
    authorise which scenes get re-rendered."""
    outcome = _prepare(world)
    request = world["gate"].request_approval(outcome)

    assert request.title.startswith("Publish:")
    assert request.payload["title"] == "Explaining the Atlas kernel"
    assert request.payload["visibility"] == "private"
    assert ApprovalScope.PROJECT_PUBLISH in request.scopes

    # The plan is context, not the question.
    assert "plan" in request.payload
    assert request.payload["plan"]["summary"]


def test_the_estimate_travels_with_the_request(world) -> None:
    """So the person deciding knows what they are authorising the spend of."""
    outcome = _prepare(world)
    request = world["gate"].request_approval(outcome)
    assert request.payload["plan"]["estimated_cost_usd"] == outcome.plan.total_cost_usd


def test_a_publication_is_marked_pending_while_it_waits(world) -> None:
    outcome = _prepare(world)
    request = world["gate"].request_approval(outcome)

    stored = world["media"].get_publication(world["publication"].id)
    assert stored.status is PublicationStatus.PENDING_APPROVAL
    assert stored.approval_id == request.id


# -- one gate, then unattended --------------------------------------------


def test_approval_executes_the_whole_plan_without_asking_again(world) -> None:
    """Renders, assembly and upload all happen off one decision."""
    outcome = _prepare(world)
    request = world["gate"].request_approval(outcome)
    approvals = world["runtime"].approval_service

    before = len(approvals.list_requests())
    approvals.approve(request.id, actor="ayoub")

    result = _execute(world, request.id)

    assert result.publication.status is PublicationStatus.PUBLISHED
    assert result.publication.remote_id
    assert result.rebuilt, "nothing was built, so nothing was proved"

    # The decisive assertion: no second approval was created along the way.
    assert len(approvals.list_requests()) == before


def test_the_video_is_actually_uploaded(world) -> None:
    outcome = _prepare(world)
    request = world["gate"].request_approval(outcome)
    world["runtime"].approval_service.approve(request.id, actor="ayoub")
    _execute(world, request.id)

    published = world["publisher"].published
    assert len(published) == 1
    assert published[0].media_path.exists()
    assert ffmpeg.probe(published[0].media_path).has_video is True
    assert published[0].title == "Explaining the Atlas kernel"


def test_captions_are_offered_as_a_sidecar(world) -> None:
    """A caption track that can be turned off, translated and read by search
    beats burned-in pixels."""
    outcome = _prepare(world)
    request = world["gate"].request_approval(outcome)
    world["runtime"].approval_service.approve(request.id, actor="ayoub")
    _execute(world, request.id)

    uploaded = world["publisher"].published[0]
    assert uploaded.captions_path is not None
    assert uploaded.captions_path.exists()


def test_a_second_publish_of_unchanged_content_rebuilds_nothing(world) -> None:
    """The dependency graph closes the loop: approved, built, recorded."""
    first = _prepare(world)
    request = world["gate"].request_approval(first)
    world["runtime"].approval_service.approve(request.id, actor="ayoub")
    _execute(world, request.id)

    again = _prepare(world)
    assert again.plan.is_empty
    assert again.plan.summary() == "Nothing to rebuild; everything is current."


# -- approval binds to a specific outcome ---------------------------------


def test_editing_the_script_after_approval_voids_it(world) -> None:
    """The property that makes approving-in-advance legitimate.

    Otherwise "approve" would be a standing permission to publish whatever the
    content happens to be by the time the upload runs.
    """
    outcome = _prepare(world)
    request = world["gate"].request_approval(outcome)
    world["runtime"].approval_service.approve(request.id, actor="ayoub")

    world["media"].update_scene(
        world["scenes"][0].id, narration="Something entirely different now."
    )

    with pytest.raises(PublishRefused, match="approved for a different version"):
        _execute(world, request.id)

    assert world["publisher"].published == []


def test_changing_the_title_after_approval_voids_it(world) -> None:
    """Metadata is part of the outcome, not a detail beneath it."""
    outcome = _prepare(world)
    request = world["gate"].request_approval(outcome)
    world["runtime"].approval_service.approve(request.id, actor="ayoub")

    world["media"].update_publication(world["publication"].id, title="A different title")

    with pytest.raises(PublishRefused, match="approved for a different version"):
        _execute(world, request.id)


def test_a_voided_approval_marks_the_publication_failed(world) -> None:
    """Rather than leaving it pending forever, which reads as "still waiting"."""
    outcome = _prepare(world)
    request = world["gate"].request_approval(outcome)
    world["runtime"].approval_service.approve(request.id, actor="ayoub")
    world["media"].update_scene(world["scenes"][0].id, narration="Changed.")

    with pytest.raises(PublishRefused):
        _execute(world, request.id)

    stored = world["media"].get_publication(world["publication"].id)
    assert stored.status is PublicationStatus.FAILED


# -- refusals --------------------------------------------------------------


def test_publishing_without_approval_is_refused(world) -> None:
    outcome = _prepare(world)
    request = world["gate"].request_approval(outcome)

    with pytest.raises(PublishRefused, match="not approved"):
        _execute(world, request.id)
    assert world["publisher"].published == []


def test_a_rejected_request_cannot_publish(world) -> None:
    outcome = _prepare(world)
    request = world["gate"].request_approval(outcome)
    world["runtime"].approval_service.reject(request.id, actor="ayoub", comment="no")

    with pytest.raises(PublishRefused, match="rejected"):
        _execute(world, request.id)


def test_an_unknown_approval_is_refused(world) -> None:
    with pytest.raises(PublishRefused, match="no approval"):
        _execute(world, "approval-does-not-exist")


def test_approval_is_re_read_rather_than_assumed(world) -> None:
    """ "We only got here because it was approved" is the reasoning that
    publishes something nobody agreed to after a refactor.

    A request cancelled while pending is not approved, and the gate must find
    that out by asking rather than by remembering.
    """
    outcome = _prepare(world)
    request = world["gate"].request_approval(outcome)
    world["runtime"].approval_service.cancel(request.id, actor="ayoub")

    with pytest.raises(PublishRefused, match="cancelled"):
        _execute(world, request.id)
    assert world["publisher"].published == []


def test_an_expired_approval_is_refused(world) -> None:
    """Consent has a shelf life; a month-old approval is not consent to publish
    today.

    The expiry is injected at the read rather than written through the service,
    because the service refuses to expire something already approved -- which is
    correct of it, and would leave this guard untested.
    """
    from datetime import UTC, datetime, timedelta

    outcome = _prepare(world)
    request = world["gate"].request_approval(outcome)
    approvals = world["runtime"].approval_service
    approvals.approve(request.id, actor="ayoub")

    live = approvals.get(request.id)
    stale = live.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(hours=1)})
    world["gate"].approvals = type(
        "ExpiredView",
        (),
        {"get": staticmethod(lambda approval_id: stale if approval_id == request.id else None)},
    )()

    with pytest.raises(PublishRefused, match="expired"):
        _execute(world, request.id)
    assert world["publisher"].published == []


# -- public is refused, not clamped ---------------------------------------


def test_public_visibility_is_refused_at_every_layer(world) -> None:
    """A refusal, not a silent downgrade: the caller must not believe it
    published when it did not."""
    with pytest.raises(PublicVisibilityRefused):
        assert_not_public(Visibility.PUBLIC)

    public = world["media"].update_publication(
        world["publication"].id, visibility=Visibility.PUBLIC
    )
    with pytest.raises(PublicVisibilityRefused):
        _prepare(world, public)


def test_a_publisher_refuses_public_even_if_asked_directly(tmp_path: Path) -> None:
    """The guard lives with the publisher too, so no caller can route around
    the gate."""
    media = tmp_path / "video.mp4"
    media.write_bytes(b"not really a video, but it exists")

    with pytest.raises(PublicVisibilityRefused):
        RecordingPublisher().publish(
            PublishRequest(media_path=media, title="x", visibility=Visibility.PUBLIC)
        )


def test_private_and_unlisted_are_both_allowed() -> None:
    assert_not_public(Visibility.PRIVATE)
    assert_not_public(Visibility.UNLISTED)


def test_publishing_a_missing_file_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(PublishError, match="nothing to publish"):
        RecordingPublisher().publish(PublishRequest(media_path=tmp_path / "absent.mp4", title="x"))
