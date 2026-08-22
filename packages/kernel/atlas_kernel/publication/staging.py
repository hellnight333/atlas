"""The step between an artefact existing and anybody seeing it.

Four words get used interchangeably and mean different things, and the confusion
is expensive in both directions — publishing something nobody reviewed, or
telling a customer their site is live when it is sitting in a directory:

============  ==========================================================
GENERATED     The capability ran and QA passed. Nothing left the kernel.
STAGED        At the target, fetchable at a preview URL, serving nobody.
APPROVED      A person looked at the staged version and said yes.
PUBLISHED     Promoted. Visitors get it.
============  ==========================================================

`ArtefactState` folds those from facts that already exist — the execution
outcome, whether a stage record was written, the approval's state, and whether a
publication record says a target accepted it. No stored status, for the same
reason as the roadmap's task state: a stored one can disagree with the thing it
describes, and then nobody can tell which is lying.

**Staging is not publishing**, and that is checkable rather than assumed. The
target interface separates publish from promote precisely so an artefact can be
reachable-but-not-live, and `is_live` asks the target which version visitors
actually get.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ..approval.models import ApprovalRequest, ApprovalState
from ..execution.models import ExecutionOutcome, PublicationState
from ..opportunity.models import BusinessEvent
from ..opportunity.tenancy import TenantId, owns
from ..opportunity.tenancy import require as _require_tenant
from ..website.targets.base import DeploymentTargetRegistry
from .models import Destination, PublicationRecord, PublicationStatus

FACTORY = "publication"
STAGED = "artefact_staged"


class ArtefactState(StrEnum):
    """Where an artefact has got to. Derived, never assigned."""

    #: The capability ran; QA has not passed or has not run.
    GENERATED = "generated"
    #: QA passed. Waiting to be put somewhere a person can look at it.
    READY_TO_STAGE = "ready_to_stage"
    #: At the target, fetchable, serving nobody.
    STAGED = "staged"
    #: A person approved this exact version for this exact destination.
    APPROVED = "approved"
    #: A target reported it accepted and promoted it.
    PUBLISHED = "published"
    #: A gate refused it, or a person did.
    REFUSED = "refused"
    #: A target was asked and could not.
    FAILED = "failed"


class StagedVersion(BaseModel):
    """One artefact, at a target, serving nobody.

    Records the version id the target handed back, so approval and publication
    both act on the version a person actually looked at rather than on whatever
    the newest one happens to be by then.
    """

    model_config = ConfigDict(frozen=True)

    tenant_id: str
    business_id: str
    asset_id: str
    content_hash: str
    target: str
    destination: Destination
    #: The target's own handle. Opaque.
    version_id: str
    preview_url: str
    staged_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def summary(self) -> dict:
        return {"tenant_id": self.tenant_id, "business_id": self.business_id,
                "asset_id": self.asset_id, "content_hash": self.content_hash,
                "target": self.target, "destination": self.destination.model_dump(),
                "version_id": self.version_id, "preview_url": self.preview_url,
                "staged_at": self.staged_at.isoformat(),
                # Said in the record, because "staged" reads to most people as
                # "put live" and the whole point is that it is not.
                "public": False}


def state_of(outcome: ExecutionOutcome, *, staged: StagedVersion | None = None,
             approval: ApprovalRequest | None = None,
             record: PublicationRecord | None = None) -> ArtefactState:
    """Fold where this artefact has got to, most decisive fact first."""
    if record is not None:
        if record.status is PublicationStatus.PUBLISHED:
            return ArtefactState.PUBLISHED
        if record.status is PublicationStatus.FAILED:
            return ArtefactState.FAILED
    if approval is not None and approval.state in (ApprovalState.REJECTED,
                                                   ApprovalState.CANCELLED,
                                                   ApprovalState.EXPIRED):
        return ArtefactState.REFUSED
    if outcome.state is PublicationState.REJECTED:
        return ArtefactState.REFUSED
    if approval is not None and approval.state is ApprovalState.APPROVED:
        return ArtefactState.APPROVED
    if staged is not None:
        return ArtefactState.STAGED
    if outcome.state is PublicationState.READY_TO_PUBLISH:
        return ArtefactState.READY_TO_STAGE
    return ArtefactState.GENERATED


def stage(*, outcome: ExecutionOutcome, asset_id: str, files: dict[str, str],
          target_name: str, destination: Destination,
          registry: DeploymentTargetRegistry, tenant: TenantId | None,
          content_hash: str) -> StagedVersion:
    """Put the artefact where a person can look at it, and nowhere else.

    Refuses before READY_TO_PUBLISH: staging an artefact that failed QA puts a
    fetchable URL to a rejected page in an approval request, and somebody will
    approve it.
    """
    tenant = _require_tenant(tenant, method="staging.stage")
    if not owns(outcome.tenant_id, tenant):
        raise PermissionError("this execution belongs to a different tenant")
    if outcome.state is not PublicationState.READY_TO_PUBLISH:
        raise ValueError(
            f"cannot stage an artefact that is {outcome.state.value}. Staging "
            "produces a URL that goes into an approval request, and a fetchable "
            "link to a rejected page is one somebody will approve.")

    registration = registry.resolve(target_name)
    version = registration.target.publish(destination.slug, files)
    return StagedVersion(
        tenant_id=outcome.tenant_id or "", business_id=outcome.business_id,
        asset_id=asset_id, content_hash=content_hash, target=target_name,
        destination=destination, version_id=version.id,
        preview_url=version.preview_url)


def is_live(staged: StagedVersion, *, registry: DeploymentTargetRegistry) -> bool:
    """Whether visitors are being served this version. Asked, not assumed.

    Targets that cannot answer report `False`, and a caller relying on this for
    a safety guarantee should read `can_answer_what_is_live` first — an adapter
    that does not know is not evidence that nothing is live.
    """
    target = registry.resolve(staged.target).target
    live = getattr(target, "live_version", None)
    if live is None:
        return False
    return live(staged.destination.slug) == staged.version_id


def can_answer_what_is_live(staged: StagedVersion, *,
                            registry: DeploymentTargetRegistry) -> bool:
    """Whether `is_live` means anything for this target."""
    return hasattr(registry.resolve(staged.target).target, "live_version")


def to_event(staged: StagedVersion, *, actor: str = "publication") -> BusinessEvent:
    return BusinessEvent(business_id=staged.business_id, factory=FACTORY,
                         kind=STAGED, actor=actor, detail=staged.summary())


def read(events: list, *, tenant: TenantId | None = None) -> list[dict]:
    """TENANT_SCOPED. Staged previews for one tenant, newest first.

    Scoped because a preview URL is a working link to an unpublished artefact.
    Leaking one leaks the work itself, before anybody agreed it could be seen.
    """
    tenant = _require_tenant(tenant, method="staging.read")
    found = []
    for event in events:
        kind = getattr(event, "kind", None) or event.get("kind")
        if kind != STAGED:
            continue
        detail = getattr(event, "detail", None) or event.get("detail") or {}
        if not owns(detail.get("tenant_id"), tenant):
            continue
        found.append(dict(detail))
    return sorted(found, key=lambda d: d.get("staged_at", ""), reverse=True)
