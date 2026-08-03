"""The one place a person is asked, and the only thing they are asked about.

**Approval is on the outcome, not the implementation.** A person is shown the
video, the metadata it will be published under, and what bringing it up to date
will cost. They are not shown -- and never asked to authorise -- which scenes
Atlas intends to re-render. That is Atlas's problem, and asking would be asking
someone to audit an internal plan they have no way to evaluate.

So there is exactly **one** gate. Once it is approved, Atlas executes the whole
dependency plan and publishes, unattended: renders, reassembly, upload. No
second confirmation between internal steps. A policy may add gates -- that is
what the policy engine is for -- but nothing here inserts one.

The safety property that makes approving-in-advance legitimate: **the approval
binds to a specific outcome.** The effective fingerprint of the publication is
recorded when the request is made and re-checked before the upload. If anything
that would change the result moved in between -- a rewritten line, a different
title, a new recipe -- the approval no longer describes what would be published,
and it is refused rather than honoured. Approval is consent to a particular
thing, not a standing permission.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..approval.models import ApprovalRequest, ApprovalScope, ApprovalState
from ..approval.service import ApprovalService
from ..dependency import DependencyGraph
from ..dependency_store import DependencyStore
from .assembly_service import AssemblyService, stored_path
from .dependencies import MediaInputs, build_graph, publication_node
from .models import Publication, PublicationStatus, Rendition, Scene, WorkStatus
from .publishing import (
    Publisher,
    PublishError,
    PublishRequest,
    assert_not_public,
)
from .recipes import RecipeRegistry
from .regeneration import RegenerationPlan, plan_regeneration
from .render_service import SceneRenderService
from .repository import MediaRepository

if TYPE_CHECKING:
    from ..asset_system import AssetService

#: Recorded on the approval so the check at upload time compares like with like.
OUTCOME_FINGERPRINT = "outcome_fingerprint"


class PublishRefused(RuntimeError):
    """The upload was not allowed to proceed."""


@dataclass
class PublishOutcome:
    """What a person is being asked to approve."""

    rendition: Rendition
    publication: Publication
    plan: RegenerationPlan
    outcome_fingerprint: str
    #: The cut as it stands, so the approver can watch something rather than
    #: read a description of something.
    preview_path: Path | None = None
    duration_seconds: float | None = None

    def describe(self) -> str:
        lines = [
            f"Publish “{self.publication.title or 'Untitled'}” to "
            f"{self.publication.platform} as {self.publication.visibility.value}.",
        ]
        if self.duration_seconds:
            lines.append(f"Length: {int(round(self.duration_seconds))}s.")
        lines.append(self.plan.summary())
        return " ".join(lines)


@dataclass
class PublishResult:
    publication: Publication
    plan_executed: RegenerationPlan
    #: Nodes rebuilt on the way. Reported afterwards, never asked about before.
    rebuilt: list[str] = field(default_factory=list)


class PublishGate:
    def __init__(
        self,
        *,
        media_repository: MediaRepository,
        approvals: ApprovalService,
        dependencies: DependencyStore,
        renderer: SceneRenderService,
        assembler: AssemblyService,
        publisher: Publisher,
        recipes: RecipeRegistry,
        asset_service: AssetService,
    ) -> None:
        self.media = media_repository
        self.approvals = approvals
        self.dependencies = dependencies
        self.renderer = renderer
        self.assembler = assembler
        self.publisher = publisher
        self.recipes = recipes
        self.assets = asset_service

    # -- asking -----------------------------------------------------------

    def prepare(
        self,
        rendition: Rendition,
        scenes: list[Scene],
        publication: Publication,
        *,
        video_recipe_id: str,
        speech_recipe_id: str | None = None,
        music_key: str | None = None,
    ) -> PublishOutcome:
        """Work out what publishing this would mean, without doing any of it."""
        assert_not_public(publication.visibility)

        video_recipe = self.recipes.get(video_recipe_id)
        speech_recipe = self.recipes.get(speech_recipe_id) if speech_recipe_id else None
        graph = self._graph(rendition, scenes, publication, video_recipe, speech_recipe, music_key)

        plan = plan_regeneration(
            graph,
            self.dependencies.recorded(rendition.id),
            scenes,
            video_recipe=video_recipe,
            speech_recipe=speech_recipe,
        )

        preview = None
        duration = None
        if rendition.asset_id:
            asset = self.assets.repository.get_asset(rendition.asset_id)
            if asset:
                preview = stored_path(asset.uri)
                duration = asset.metadata.get("duration_seconds")

        return PublishOutcome(
            rendition=rendition,
            publication=publication,
            plan=plan,
            outcome_fingerprint=graph.effective_fingerprint(publication_node(publication.id)),
            preview_path=preview,
            duration_seconds=duration,
        )

    def request_approval(
        self, outcome: PublishOutcome, *, requested_by: str = "system"
    ) -> ApprovalRequest:
        """Ask a person about the outcome.

        The plan is attached as context -- what it will cost, how long it will
        take -- but the question is "publish this?", not "may Atlas re-render
        scene three?".
        """
        from ..approval.models import ApprovalContext

        publication = outcome.publication
        request = self.approvals.create_request(
            title=f"Publish: {publication.title or 'Untitled'}",
            context=ApprovalContext(
                action="media.publish",
                scopes=[ApprovalScope.PROJECT_PUBLISH, ApprovalScope.EXTERNAL_API],
                estimated_cost=outcome.plan.total_cost_usd or 0.0,
                requested_by=requested_by,
                payload={
                    "rendition_id": outcome.rendition.id,
                    "publication_id": publication.id,
                    "platform": publication.platform,
                    "visibility": publication.visibility.value,
                    "title": publication.title,
                    "description": publication.description,
                    "tags": list(publication.tags),
                    "duration_seconds": outcome.duration_seconds,
                    "preview_path": str(outcome.preview_path) if outcome.preview_path else None,
                    OUTCOME_FINGERPRINT: outcome.outcome_fingerprint,
                    "plan": {
                        "summary": outcome.plan.summary(),
                        "estimated_seconds": outcome.plan.total_seconds,
                        "estimated_cost_usd": outcome.plan.total_cost_usd,
                        "fully_estimated": outcome.plan.fully_estimated,
                        "work": [w.description for w in outcome.plan.work],
                    },
                },
            ),
            asset_id=outcome.rendition.asset_id,
        )
        self.media.update_publication(
            publication.id,
            approval_id=request.id,
            status=PublicationStatus.PENDING_APPROVAL,
        )
        return request

    # -- doing ------------------------------------------------------------

    def execute(
        self,
        approval_id: str,
        rendition: Rendition,
        scenes: list[Scene],
        publication: Publication,
        *,
        video_recipe_id: str,
        speech_recipe_id: str | None = None,
        music_recipe_id: str | None = None,
        music_key: str | None = None,
        assembly_options: dict | None = None,
    ) -> PublishResult:
        """Execute the approved outcome, end to end, without asking again.

        Renders what needs rendering, reassembles if the cut moved, then
        uploads. Every one of those steps is an internal consequence of the one
        decision already taken.
        """
        approval = self._verify(approval_id)

        video_recipe = self.recipes.get(video_recipe_id)
        speech_recipe = self.recipes.get(speech_recipe_id) if speech_recipe_id else None
        graph = self._graph(rendition, scenes, publication, video_recipe, speech_recipe, music_key)

        current = graph.effective_fingerprint(publication_node(publication.id))
        approved = approval.payload.get(OUTCOME_FINGERPRINT)
        if approved != current:
            self.media.update_publication(
                publication.id,
                status=PublicationStatus.FAILED,
                error="the content changed after approval",
            )
            raise PublishRefused(
                "This was approved for a different version. Something that changes the "
                "result was edited after approval, so the approval no longer describes "
                "what would be published. Ask again."
            )

        plan = plan_regeneration(
            graph,
            self.dependencies.recorded(rendition.id),
            scenes,
            video_recipe=video_recipe,
            speech_recipe=speech_recipe,
        )

        # Everything below here runs unattended. This is the point of the gate:
        # one decision, then the whole plan.
        rebuilt: list[str] = []
        if plan.scenes_to_rerender() or plan.scenes_to_revoice():
            self.renderer.render_rendition(
                rendition,
                scenes,
                video_recipe_id=video_recipe_id,
                narration_recipe_id=speech_recipe_id,
                render_visuals=plan.scenes_to_rerender(),
                render_narration=plan.scenes_to_revoice(),
            )
            rebuilt.extend(w.node_id for w in plan.work if w.scene_id)

        if plan.needs_assembly or rendition.asset_id is None:
            rendition = self.media.get_rendition(rendition.id) or rendition
            self.assembler.assemble(
                rendition,
                scenes,
                music_recipe_id=music_recipe_id,
                options=assembly_options,
            )
            rendition = self.media.get_rendition(rendition.id) or rendition
            rebuilt.append(f"assembly:{rendition.id}")

        published = self._upload(rendition, publication)
        self.dependencies.record(rendition.id, graph.snapshot())
        return PublishResult(publication=published, plan_executed=plan, rebuilt=rebuilt)

    def _verify(self, approval_id: str) -> ApprovalRequest:
        """The approval must exist, be approved, and still be live.

        Re-read by id rather than inferred from control flow: "we only got here
        because it was approved" is exactly the reasoning that publishes
        something nobody agreed to after a refactor.
        """
        approval = self.approvals.get(approval_id)
        if approval is None:
            raise PublishRefused(f"no approval {approval_id!r}")
        if approval.state is not ApprovalState.APPROVED:
            raise PublishRefused(f"approval {approval_id} is {approval.state.value}, not approved")
        if approval.expires_at is not None and approval.expires_at <= datetime.now(UTC):
            raise PublishRefused(f"approval {approval_id} expired at {approval.expires_at:%c}")
        return approval

    def _upload(self, rendition: Rendition, publication: Publication) -> Publication:
        assert_not_public(publication.visibility)

        if not rendition.asset_id:
            raise PublishRefused("there is nothing assembled to publish")
        asset = self.assets.repository.get_asset(rendition.asset_id)
        if asset is None:
            raise PublishRefused(f"asset {rendition.asset_id} is missing")

        media_path = stored_path(asset.uri)
        # Resolved from the recorded asset id, never by guessing at a path
        # beside the video: the asset store renames what it keeps, so a sibling
        # .srt would silently never be found.
        captions = None
        captions_id = (rendition.build_metadata or {}).get("assembly", {}).get("captions_asset_id")
        if captions_id:
            captions_asset = self.assets.repository.get_asset(captions_id)
            if captions_asset:
                candidate = stored_path(captions_asset.uri)
                captions = candidate if candidate.exists() else None

        self.media.update_publication(publication.id, status=PublicationStatus.UPLOADING)
        try:
            receipt = self.publisher.publish(
                PublishRequest(
                    media_path=media_path,
                    title=publication.title,
                    description=publication.description,
                    tags=list(publication.tags),
                    visibility=publication.visibility,
                    captions_path=captions,
                    metadata={
                        "rendition_id": rendition.id,
                        "episode_id": rendition.episode_id,
                    },
                )
            )
        except PublishError as error:
            self.media.update_publication(
                publication.id, status=PublicationStatus.FAILED, error=str(error)
            )
            raise

        updated = self.media.update_publication(
            publication.id,
            status=PublicationStatus.PUBLISHED,
            remote_id=receipt.remote_id,
            remote_url=receipt.remote_url,
            visibility=receipt.visibility,
            error=None,
        )
        self.media.update_rendition(rendition.id, status=WorkStatus.READY)
        return updated or publication

    def _graph(
        self,
        rendition: Rendition,
        scenes: list[Scene],
        publication: Publication,
        video_recipe: Any,
        speech_recipe: Any,
        music_key: str | None,
    ) -> DependencyGraph:
        return build_graph(
            MediaInputs(
                rendition=rendition,
                scenes=scenes,
                video_recipe=video_recipe,
                speech_recipe=speech_recipe,
                music_key=music_key,
                publication=publication,
            )
        )
