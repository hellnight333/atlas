"""READY_TO_PUBLISH → PUBLISHED, and the record that survives it.

One function does the crossing, and most of it is refusing. What it adds beyond
the gate is small and deliberate:

* **A failure is a record, not an exception.** A publication that the host
  rejected is a thing that happened, and losing it because an exception
  propagated would leave the customer's site in an unknown state with nothing
  written down. `FAILED` records exist; `PUBLISHED` ones are only ever written
  after a target reported success.
* **Publish and promote are separate**, because the target interface already
  separates them and that separation is what lets a person look at the real
  artefact on the real host before anybody else can. `stage()` exposes it for
  callers that want a preview to approve against.
* **The record is immutable.** A retry is a new record. The failed one stays,
  because "we tried twice and the first one 404'd" is the kind of thing nobody
  can reconstruct later.

Nothing here interprets a successful publication. The target said yes; whether
the business is better off is a `measurement/` question, asked later, at
whatever attribution level the evidence supports.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import uuid4

from ..approval.models import ApprovalRequest
from ..execution.models import ExecutionOutcome
from ..models import Asset
from ..opportunity.models import BusinessEvent
from ..opportunity.tenancy import TenantId, owns
from ..opportunity.tenancy import require as _require_tenant
from ..website.targets.base import DeploymentError, DeploymentTargetRegistry
from . import gate, staging
from .connections import ConnectionStore
from .models import (
    Connection,
    Destination,
    PublicationRecord,
    PublicationStatus,
    artefact_fingerprint,
)

log = logging.getLogger(__name__)

FACTORY = "publication"
PUBLISHED = "artefact_published"
FAILED = "artefact_publication_failed"


def publish(*, outcome: ExecutionOutcome, asset: Asset, files: dict[str, str],
            target_name: str, destination: Destination,
            registry: DeploymentTargetRegistry, connections: ConnectionStore,
            connection: Connection | None, approval: ApprovalRequest | None,
            tenant: TenantId | None, roadmap_task_id: str = "",
            execution_approval_id: str = "",
            already_published: tuple[str, ...] = ()) -> PublicationRecord:
    """Make an approved artefact live, and record exactly what happened.

    Raises `NotPublishable` when a condition is unmet — nothing was attempted,
    so there is nothing to record. Returns a record in every other case,
    including failure.
    """
    gate.require(outcome=outcome, asset=asset, target=target_name,
                 destination=destination, registry=registry,
                 connection=connection, connections=connections,
                 approval=approval, tenant=tenant, files=files,
                 already_published=already_published)
    assert connection is not None and approval is not None    # gate proved both

    fingerprint = artefact_fingerprint(
        content_hash=asset.content_hash or "", target=target_name,
        destination=destination, tenant_id=outcome.tenant_id or "")
    record_id = f"pub-{uuid4().hex[:12]}"

    def _record(status: PublicationStatus, *, external_id: str = "",
                external_url: str = "", error: str = "") -> PublicationRecord:
        """Every field written in one place, whatever the outcome was.

        Building the shared part as a dict and splatting it read more neatly and
        meant a field could be added to one branch and not the other. A record
        that carries its provenance only when publication succeeded is exactly
        the record nobody has when they need it.
        """
        return PublicationRecord(
            id=record_id, tenant_id=outcome.tenant_id or "",
            business_id=outcome.business_id,
            recommendation_id=outcome.recommendation_id,
            roadmap_task_id=roadmap_task_id, run_id=outcome.run_id,
            job_id=outcome.job_id, asset_id=asset.id,
            content_hash=asset.content_hash or "", target=target_name,
            destination=destination, connection_id=connection.id,
            execution_approval_id=execution_approval_id,
            artefact_approval_id=approval.id, artefact_fingerprint=fingerprint,
            status=status, external_id=external_id, external_url=external_url,
            error=error, completed_at=datetime.now(UTC))

    # Resolved for this one use and never held. The value is not passed to the
    # target here because the local target's connection *is* its root; a
    # credentialed target reads it at the same point and drops it the same way.
    connections.resolve(connection, tenant=tenant)

    try:
        # The same staging step a preview uses, so what gets promoted is what an
        # approver could have looked at. Two ways to put files at a target would
        # eventually differ, and the difference would be invisible.
        version = staging.stage(
            outcome=outcome, asset_id=asset.id, files=files,
            target_name=target_name, destination=destination, registry=registry,
            tenant=tenant, content_hash=asset.content_hash or "")
        live_url = registry.resolve(target_name).target.promote(
            destination.slug, version.version_id)
    except (DeploymentError, OSError, ValueError, PermissionError) as failure:
        # The host refused or broke. A record, and never PUBLISHED — the type
        # name and message only, because a provider's error body can echo a
        # request, and a request can carry a token.
        log.warning("publication failed for %s at %s: %s", asset.id, target_name,
                    type(failure).__name__)
        return _record(PublicationStatus.FAILED,
                       error=f"{type(failure).__name__}: {failure}"[:300])

    return _record(PublicationStatus.PUBLISHED,
                   external_id=version.version_id, external_url=live_url)


def to_event(record: PublicationRecord, *, actor: str = "publication") -> BusinessEvent:
    """The timeline entry. `summary()` is the only shape that goes in.

    Nothing on the record holds a secret, so this is not a redaction — but going
    through one method means a field added later is added in one place and
    reviewed once, rather than appearing in an event because a `model_dump()`
    picked it up.
    """
    return BusinessEvent(
        business_id=record.business_id, factory=FACTORY,
        kind=PUBLISHED if record.published else FAILED,
        actor=actor, detail=record.summary())


def read(events: list, *, tenant: TenantId | None = None) -> list[dict]:
    """TENANT_SCOPED. Publication records for one tenant, newest first."""
    tenant = _require_tenant(tenant, method="publication.read")
    found = []
    for event in events:
        kind = getattr(event, "kind", None) or event.get("kind")
        if kind not in (PUBLISHED, FAILED):
            continue
        detail = getattr(event, "detail", None) or event.get("detail") or {}
        if not owns(detail.get("tenant_id"), tenant):
            continue
        found.append(dict(detail))
    return sorted(found, key=lambda d: d.get("attempted_at", ""), reverse=True)


def published_fingerprints(events: list, *, tenant: TenantId | None = None,
                           ) -> tuple[str, ...]:
    """What is already live, for the duplicate check.

    Only successful ones. A failed attempt must not stop a retry — that would
    turn one bad afternoon into a permanently unpublishable artefact.
    """
    return tuple(
        record["artefact_fingerprint"] for record in read(events, tenant=tenant)
        if record.get("status") == PublicationStatus.PUBLISHED.value
        and record.get("artefact_fingerprint"))
