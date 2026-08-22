"""The second approval, and the nine conditions around it.

P1.6 asked *"should Qevik perform this work?"* — a decision about a proposal,
taken before anything existed. This asks *"may this exact output go to this
exact destination?"* — a decision about a finished artefact somebody can look at.

They are different questions, asked at different times, and answerable
differently by the same person. Somebody can want a portfolio system and reject
the one that was built. Collapsing them would mean the first yes published the
second thing sight unseen, which is the whole reason `READY_TO_PUBLISH` exists.

So this is a second `ApprovalRequest` through the same `ApprovalService`, under
its own action name, bound to a fingerprint of the artefact's content and its
destination. Not a second approval system: a second question.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ..approval.models import ApprovalContext, ApprovalRequest, ApprovalScope, ApprovalState
from ..approval.service import ApprovalService
from ..execution.models import ExecutionOutcome, PublicationState
from ..models import Asset
from ..opportunity.tenancy import TenantId, owns
from ..website.targets.base import DeploymentTargetRegistry, NoTargetAvailable
from .connections import ConnectionStore
from .models import (
    ARTEFACT_FINGERPRINT,
    PUBLISH_ACTION,
    Connection,
    Destination,
    NotPublishable,
    artefact_fingerprint,
)


@dataclass(frozen=True)
class Publishable:
    """The answer, with its reasoning kept."""

    ok: bool
    reasons: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.ok


def request_artefact_approval(
    *, outcome: ExecutionOutcome, asset: Asset, destination: Destination,
    target: str, approvals: ApprovalService, business_name: str,
    preview_url: str = "", requested_by: str = "qevik") -> ApprovalRequest:
    """Ask whether this exact artefact may go to this exact destination.

    The approver is given the preview URL where one exists, because the point of
    publish-then-promote is that a person can look at the real thing on the real
    host before anybody else can. A description of a page is not a page.
    """
    fingerprint = artefact_fingerprint(
        content_hash=asset.content_hash or "", target=target,
        destination=destination, tenant_id=outcome.tenant_id or "")
    context = ApprovalContext(
        action=PUBLISH_ACTION,
        scopes=[ApprovalScope.PROJECT_PUBLISH, ApprovalScope.NETWORK],
        requested_by=requested_by,
        payload={
            "business": business_name,
            "target": target,
            "destination": destination.slug,
            "url": destination.url,
            "preview_url": preview_url,
            "content_hash": asset.content_hash,
            "qa": [{"gate": r.gate, "verdict": r.verdict.value} for r in outcome.qa],
            "evidence": list(asset.metadata.get("evidence") or ()),
            # Stated because it is the difference from the P1.6 approval, and a
            # reviewer seeing two approvals for one piece of work should be able
            # to tell which question they are answering.
            "note": "This makes the artefact live. The earlier approval "
                    "authorised building it; this one authorises publishing "
                    "exactly this version to exactly this destination.",
        },
    )
    return approvals.create_request(
        title=f"Publish to {destination.slug} — {business_name}",
        context=context,
        run_id=outcome.run_id, job_id=outcome.job_id, asset_id=asset.id,
        metadata={
            ARTEFACT_FINGERPRINT: fingerprint,
            "tenant_id": outcome.tenant_id,
            "business_id": outcome.business_id,
            "recommendation_id": outcome.recommendation_id,
            "target": target, "destination": destination.slug,
            "content_hash": asset.content_hash,
        },
    )


def unmet(*, outcome: ExecutionOutcome, asset: Asset | None, target: str,
          destination: Destination, registry: DeploymentTargetRegistry,
          connection: Connection | None, connections: ConnectionStore,
          approval: ApprovalRequest | None, tenant: TenantId | None,
          files: dict[str, str] | None = None,
          already_published: tuple[str, ...] = ()) -> tuple[str, ...]:
    """Every condition publication does not satisfy. Empty means it may go.

    Nine conditions, checked positively. There is no path to "publishable" that
    consists of not finding a problem — an unknown is unsatisfied, because the
    thing on the other side of this function is the public internet.
    """
    reasons: list[str] = []

    # 1. Tenant. Established first: without it, no other ownership check means
    #    anything.
    if tenant is None:
        reasons.append("no tenant was supplied, so ownership cannot be established")
    elif not owns(outcome.tenant_id, tenant):
        reasons.append("the execution belongs to a different tenant")

    # 2. Recommendation provenance — why this exists at all.
    if not outcome.recommendation_id:
        reasons.append("the execution names no recommendation, so there is no "
                       "record of why it was built")

    # 3 & 4. Job and run provenance.
    if not outcome.job_id or not outcome.run_id:
        reasons.append("the execution names no job or run, so it cannot be traced")

    # 5. The asset itself, and that it is the one this execution produced.
    if asset is None:
        reasons.append("no asset was supplied")
    else:
        if asset.id not in outcome.asset_ids:
            reasons.append(f"asset {asset.id} was not produced by job {outcome.job_id}")
        if not asset.content_hash:
            reasons.append("the asset has no content hash, so what would be "
                           "published cannot be identified")
        for link in ("recommendation_id", "business_id", "tenant_id"):
            if not asset.metadata.get(link):
                reasons.append(f"the asset's provenance is missing {link}")
        if tenant is not None and not owns(asset.metadata.get("tenant_id"), tenant):
            reasons.append("the asset belongs to a different tenant")
        # And the bytes about to go out must be the bytes that were approved.
        # The fingerprint covers the asset's content hash, so without this an
        # approval for one artefact could publish a different one — the files
        # are a separate argument and nothing else compares them.
        if files is not None and asset.content_hash:
            digests = {hashlib.sha256(body.encode("utf-8")).hexdigest()
                       for body in files.values()}
            if asset.content_hash not in digests:
                reasons.append(
                    "the files to publish do not match the approved asset's "
                    "content hash")

    # 6. QA. NOT_RUN blocks exactly as FAIL does — an unrun check has
    #    established nothing.
    if outcome.failed_gates:
        failed = ", ".join(f"{r.gate}={r.verdict.value}" for r in outcome.failed_gates)
        reasons.append(f"QA did not pass: {failed}")
    if not outcome.qa:
        reasons.append("no QA gates were run")

    # 7. The state P1.3 ends at. Anything else has not earned a decision yet.
    if outcome.state is not PublicationState.READY_TO_PUBLISH:
        reasons.append(f"the artefact is {outcome.state.value}, not READY_TO_PUBLISH")

    # 8. A registered target, and a connection for it that this tenant owns.
    try:
        registry.resolve(target)
    except NoTargetAvailable as missing:
        reasons.append(str(missing))
    if connection is None:
        reasons.append(f"no connection to {target!r} for this tenant")
    else:
        if connection.target != target:
            reasons.append(f"connection {connection.id} is for "
                           f"{connection.target!r}, not {target!r}")
        if tenant is not None and not owns(connection.tenant_id, tenant):
            reasons.append("the connection belongs to a different tenant")
        elif tenant is not None:
            # Resolvable, checked here rather than discovered mid-publish. The
            # credential is fetched and dropped; nothing keeps it.
            try:
                connections.resolve(connection, tenant=tenant)
            except Exception as failure:            # noqa: BLE001 - reported, not raised
                reasons.append(f"the connection could not be resolved: "
                               f"{type(failure).__name__}")

    # 9. The artefact approval, bound to this artefact and this destination.
    if approval is None:
        reasons.append("no artefact approval has been requested")
    elif approval.state is not ApprovalState.APPROVED:
        reasons.append(f"artefact approval {approval.id} is {approval.state.value}")
    elif asset is not None:
        recorded = approval.metadata.get(ARTEFACT_FINGERPRINT)
        expected = artefact_fingerprint(
            content_hash=asset.content_hash or "", target=target,
            destination=destination, tenant_id=outcome.tenant_id or "")
        if not recorded:
            reasons.append(f"approval {approval.id} records no artefact "
                           "fingerprint, so it cannot be shown to describe this")
        elif recorded != expected:
            reasons.append("the artefact or its destination changed after "
                           "approval; re-request approval for this version")
        if tenant is not None and not owns(approval.metadata.get("tenant_id"), tenant):
            reasons.append("the approval belongs to a different tenant")

    # And publishing the same artefact to the same place twice is not a second
    # publication, it is a repeat. Refused rather than deduplicated silently, so
    # a caller retrying a *failed* one is not confused with one doing it twice.
    if asset is not None:
        fingerprint = artefact_fingerprint(
            content_hash=asset.content_hash or "", target=target,
            destination=destination, tenant_id=outcome.tenant_id or "")
        if fingerprint in already_published:
            reasons.append("this exact artefact is already published to this "
                           "destination")

    return tuple(dict.fromkeys(reasons))


def check(*, outcome: ExecutionOutcome, asset: Asset | None, target: str,
          destination: Destination, registry: DeploymentTargetRegistry,
          connection: Connection | None, connections: ConnectionStore,
          approval: ApprovalRequest | None, tenant: TenantId | None,
          files: dict[str, str] | None = None,
          already_published: tuple[str, ...] = ()) -> Publishable:
    """Non-raising form, for showing why something is not going out."""
    reasons = unmet(outcome=outcome, asset=asset, target=target,
                    destination=destination, registry=registry,
                    connection=connection, connections=connections,
                    approval=approval, tenant=tenant, files=files,
                    already_published=already_published)
    return Publishable(ok=not reasons, reasons=reasons)


def require(*, outcome: ExecutionOutcome, asset: Asset | None, target: str,
            destination: Destination, registry: DeploymentTargetRegistry,
            connection: Connection | None, connections: ConnectionStore,
            approval: ApprovalRequest | None, tenant: TenantId | None,
            files: dict[str, str] | None = None,
            already_published: tuple[str, ...] = ()) -> None:
    """Raise unless every condition is satisfied."""
    reasons = unmet(outcome=outcome, asset=asset, target=target,
                    destination=destination, registry=registry,
                    connection=connection, connections=connections,
                    approval=approval, tenant=tenant, files=files,
                    already_published=already_published)
    if reasons:
        raise NotPublishable(getattr(asset, "id", "artefact"), reasons)
