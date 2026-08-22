"""Recommendation → approval → job → asset → QA → READY_TO_PUBLISH.

The whole slice, in one readable path, because the point of P1.3 is to prove the
architecture rather than to generalise it. Everything it touches already existed:
the approval engine, the kernel Job, the Asset graph, the tenant rules from
P1.1, and the recommendation from P1.2.

Three refusals sit before any work happens, and they are the reason this is safe
to run:

* **not approved** — an accepted recommendation is not consent to execute;
* **a customer task is outstanding** — we would be doing work the customer has
  not enabled, and it would fail or be wrong;
* **no executor** — a capability nothing can perform must not produce a job that
  looks queued forever.

Nothing here publishes. `READY_TO_PUBLISH` is where the path ends by design.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from uuid import uuid4

from ..models import Asset, Job, JobStatus, Run
from ..opportunity.tenancy import owns
from ..recommendation.models import Recommendation, RecommendationState
from ..recommendation.offers import offer_for
from .capabilities import EXECUTORS
from .models import (
    ExecutionOutcome,
    NotApproved,
    PublicationState,
    UnsupportedCapability,
)
from .qa import Context, run_gates

log = logging.getLogger(__name__)

#: Where a produced artefact lives. Content-addressed, so the same input
#: produces the same location and a changed artefact cannot silently overwrite
#: the one that was reviewed.
URI = "atlas://qevik/{business_id}/{capability}/{digest}.html"


def _digest(artefact: str) -> str:
    return hashlib.sha256(artefact.encode("utf-8")).hexdigest()


def may_execute(recommendation: Recommendation, *, approved: bool,
                customer_done: frozenset[str] = frozenset()) -> None:
    """Raise unless every condition for doing the work is met.

    `customer_done` names customer tasks the customer has since reported
    complete, folded from the event timeline. It defaults to empty, so a caller
    that does not know refuses rather than proceeds — an unrecorded permission
    is not a granted one.
    """
    if not approved:
        raise NotApproved(
            f"{recommendation.id} has not been approved. Acceptance records that a "
            "customer wants this; approval records that they consent to it "
            "happening now.")
    if recommendation.state is not RecommendationState.ACCEPTED:
        raise NotApproved(
            f"{recommendation.id} is {recommendation.state.value}, not accepted")
    outstanding = [t.title for t in recommendation.customer_tasks
                   if t.blocks and t.title not in customer_done]
    if outstanding:
        raise NotApproved(
            f"{recommendation.id} is waiting on the customer: {', '.join(outstanding)}")
    if recommendation.offer_id not in EXECUTORS:
        raise UnsupportedCapability(
            f"no executor for {recommendation.offer_id!r}. A capability nothing can "
            "perform must not become a job.")


def execute(recommendation: Recommendation, *, approved: bool, research: dict,
            business_name: str, repository=None, project_id: str = "",
            actor: str = "execution",
            customer_done: frozenset[str] = frozenset()) -> ExecutionOutcome:
    """Run one approved recommendation and report what came of it.

    Returns an outcome even when the work fails: a failure is a result, and a
    job that raises past its caller leaves no record of having been attempted.
    """
    started = datetime.now(UTC)
    may_execute(recommendation, approved=approved, customer_done=customer_done)

    offer = offer_for(recommendation.offer_id)
    executor = EXECUTORS[recommendation.offer_id]
    run = Run(
        id=f"run-{uuid4().hex[:12]}",
        title=f"{recommendation.title} — {business_name}",
        description=recommendation.rationale[:400],
        studio="qevik",
        workflow_id="qevik-execution",
        project_id=project_id or None,
        status=JobStatus.RUNNING,
    )
    job = Job(id=f"job-{uuid4().hex[:12]}", run_id=run.id,
              action=recommendation.offer_id,
              payload={"recommendation_id": recommendation.id,
                       "business_id": recommendation.business_id,
                       "tenant_id": recommendation.tenant_id,
                       "capability_id": recommendation.capability_id},
              status=JobStatus.RUNNING)

    artefact, provenance, error = "", {}, ""
    try:
        artefact, provenance = executor(
            business_name=business_name, research=research,
            strengths=recommendation.strengths)
    except Exception as failure:                  # noqa: BLE001 - a failure is data
        log.exception("execution: %s failed for %s", recommendation.offer_id,
                      recommendation.business_id)
        error = f"{type(failure).__name__}: {failure}"[:300]

    assets: list[Asset] = []
    if artefact:
        digest = _digest(artefact)
        assets.append(Asset(
            type="document",
            project_id=project_id or "project-unassigned",
            run_id=run.id, job_id=job.id,
            uri=URI.format(business_id=recommendation.business_id,
                           capability=recommendation.offer_id, digest=digest[:16]),
            mime_type="text/html",
            file_size=len(artefact.encode("utf-8")),
            content_hash=digest,
            metadata={
                # Provenance the QA gates and any later measurement read. An
                # asset that cannot say what it was built from and why cannot be
                # explained to a customer six months later.
                "recommendation_id": recommendation.id,
                "opportunity_key": recommendation.opportunity_key,
                "capability_id": recommendation.capability_id,
                "offer_id": recommendation.offer_id,
                "business_id": recommendation.business_id,
                "tenant_id": recommendation.tenant_id,
                "evidence": list(recommendation.evidence),
                "built_from": provenance,
                "publication_state": PublicationState.DRAFT.value,
            },
        ))

    results = run_gates(Context(outcome_error=error, assets=assets,
                                recommendation=recommendation, offer=offer,
                                artefact=artefact))
    blocked = [r for r in results if r.blocks]
    state = PublicationState.REJECTED if blocked else PublicationState.READY_TO_PUBLISH
    job = job.model_copy(update={
        "status": JobStatus.FAILED if (error or blocked) else JobStatus.COMPLETED,
        "produced_asset_ids": [a.id for a in assets],
        "output": {"state": state.value,
                   "qa": [{"gate": r.gate, "verdict": r.verdict.value} for r in results]},
    })

    if repository is not None:
        repository.create_run(run)
        repository.create_job(job)
        for asset in assets:
            asset.metadata["publication_state"] = state.value
            repository.create_asset(asset)

    return ExecutionOutcome(
        job_id=job.id, run_id=run.id, recommendation_id=recommendation.id,
        business_id=recommendation.business_id, tenant_id=recommendation.tenant_id,
        capability_id=recommendation.capability_id,
        succeeded=not error, error=error,
        asset_ids=tuple(a.id for a in assets), qa=results, state=state,
        # The measurement hooks. P1.4 reads these; nothing here interprets them,
        # and an observed change is never recorded as a caused one.
        baseline={"captured_at": started.isoformat(),
                  "research_facts": (research.get("facts") or {}).get("cms", {}),
                  "orphans": ((research.get("facts") or {}).get("seo") or {})
                  .get("orphan_count")},
        measures=tuple(offer.measurement) if offer else (),
        started_at=started, finished_at=datetime.now(UTC),
    )


def visible_to(outcome: ExecutionOutcome, tenant) -> bool:
    """TENANT_SCOPED. An outcome with no tenant belongs to nobody."""
    return owns(outcome.tenant_id, tenant)


def publish(outcome: ExecutionOutcome) -> None:
    """Deliberately not implemented **here**, and not going to be.

    Publication exists now — `atlas_kernel.publication` has the target, the
    connection and the second approval on the artefact itself. It is a separate
    package on purpose: this layer has no way to reach the outside world, and a
    test asserts that by reading its imports. Adding a publish path here would
    make that true only until somebody changed it.

    Kept as a refusal rather than deleted so the boundary stays visible at the
    place a caller would look for it.
    """
    raise NotImplementedError(
        "publication does not happen in the execution layer. READY_TO_PUBLISH "
        "means an artefact passed its gates and is waiting for a human. Use "
        "atlas_kernel.publication.publish(), which requires a registered "
        "target, a tenant-owned connection and a second approval on this "
        "exact artefact.")
