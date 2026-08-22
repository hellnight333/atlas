"""The one place a roadmap task becomes work somebody agreed to.

Existing at all is the point. A roadmap task is a proposal; a Job is work being
done; and the step between them is where a plan stops being a document. Leaving
that step implicit is how a system ends up executing everything it planned.

Nothing here is new machinery. The approval is an `ApprovalRequest` from
`atlas_kernel.approval`, the same service the Media Factory publishes through
and the outreach gate contacts strangers through. The execution is P1.3's
`execute()`, producing the same `Run`, `Job` and `Asset` provenance. This module
only carries a task across, and refuses when it may not go.

Three properties, all inherited rather than reinvented:

* **A task does not execute because it exists.** `gate.require` must pass first,
  and one of its conditions is an approval that is currently APPROVED.
* **The approval is bound to a fingerprint of the task.** Approving one act does
  not approve a different one; change the capability, the evidence or the
  recommendation and the decision no longer applies.
* **Nothing here can approve anything.** This module requests and reads. The
  decision is an authenticated human call on `ApprovalService`.
"""

from __future__ import annotations

import logging

from ..approval.models import ApprovalContext, ApprovalRequest, ApprovalScope
from ..approval.service import ApprovalService
from ..execution.models import ExecutionOutcome
from ..execution.service import execute as _execute
from ..opportunity.models import BusinessEvent
from ..opportunity.tenancy import TenantId
from ..recommendation.models import Recommendation
from ..repository import AtlasRepository
from . import gate
from .lifecycle import TaskFacts
from .models import RoadmapTask

log = logging.getLogger(__name__)

FACTORY = "roadmap"
REQUESTED = "roadmap_task_approval_requested"
EXECUTED = "roadmap_task_executed"


def request_approval(task: RoadmapTask, *, recommendation: Recommendation,
                     approvals: ApprovalService, business_name: str,
                     requested_by: str = "qevik") -> ApprovalRequest:
    """Ask a human to allow this specific task. Nothing runs because of this.

    The payload carries the evidence, not only a summary. An approver who cannot
    see what a claim rests on is being asked to trust the generator, and the
    whole evidence architecture exists so that they do not have to.
    """
    context = ApprovalContext(
        action=gate.EXECUTE_ACTION,
        scopes=[ApprovalScope.PROVIDER_COST, ApprovalScope.FILESYSTEM_WRITE],
        requested_by=requested_by,
        payload={
            "business": business_name,
            "task": task.task.title,
            "why": task.why,
            "capability": task.capability_id,
            "dimension": task.dimension,
            "evidence": list(task.evidence),
            "expected_outcome": task.expected_outcome,
            "measured_by": task.metric_key,
            # Said explicitly because it is the thing most easily assumed. What
            # is being approved is the work, not its publication.
            "publishes": False,
            "note": "Approving this authorises the work and its QA. It does not "
                    "publish anything: the result stops at READY_TO_PUBLISH and "
                    "needs a separate decision.",
        },
    )
    return approvals.create_request(
        title=f"{task.task.title} — {business_name}",
        context=context,
        metadata={
            gate.TASK_FINGERPRINT: gate.fingerprint(task),
            "roadmap_task_id": task.id,
            "recommendation_id": task.recommendation_id,
            "business_id": recommendation.business_id,
            "tenant_id": task.tenant_id,
            "capability_id": task.capability_id,
        },
    )


def execute_task(task: RoadmapTask, *, recommendation: Recommendation,
                 approval: ApprovalRequest | None, facts: TaskFacts,
                 tenant: TenantId | None, research: dict, business_name: str,
                 repository: AtlasRepository | None = None, project_id: str = "",
                 actor: str = "roadmap") -> ExecutionOutcome:
    """Carry an approved task into execution, or refuse and say why.

    Raises `NotExecutable` with every unmet condition rather than executing
    partially. The alternative — running and reporting a failure — spends
    provider cost on work that was never allowed to start.
    """
    gate.require(task, recommendation=recommendation, approval=approval,
                 facts=facts, tenant=tenant)
    log.info("roadmap: executing %s (%s) for %s", task.id, task.capability_id,
             recommendation.business_id)
    return _execute(recommendation, approved=True, research=research,
                    business_name=business_name, repository=repository,
                    project_id=project_id, actor=actor,
                    customer_done=facts.completed_customer_tasks)


def requested_event(task: RoadmapTask, approval: ApprovalRequest,
                    *, business_id: str, actor: str = "roadmap") -> BusinessEvent:
    return BusinessEvent(
        business_id=business_id, factory=FACTORY, kind=REQUESTED, actor=actor,
        detail={"roadmap_task_id": task.id, "approval_id": approval.id,
                "tenant_id": task.tenant_id, "title": task.task.title,
                "fingerprint": gate.fingerprint(task),
                "capability_id": task.capability_id})


def executed_event(task: RoadmapTask, outcome: ExecutionOutcome,
                   *, actor: str = "roadmap") -> BusinessEvent:
    """What happened, in terms that cannot be read as a business result.

    Records the publication state rather than a success flag, because
    READY_TO_PUBLISH is the honest end of this path and "succeeded" invites the
    reading that something reached a customer.
    """
    return BusinessEvent(
        business_id=outcome.business_id, factory=FACTORY, kind=EXECUTED, actor=actor,
        detail={"roadmap_task_id": task.id, "tenant_id": outcome.tenant_id,
                "job_id": outcome.job_id, "run_id": outcome.run_id,
                "recommendation_id": outcome.recommendation_id,
                "capability_id": outcome.capability_id,
                "asset_ids": list(outcome.asset_ids),
                "publication_state": outcome.state.value,
                "work_completed": outcome.succeeded,
                "qa": [{"gate": r.gate, "verdict": r.verdict.value} for r in outcome.qa],
                "measures": list(outcome.measures),
                "baseline": outcome.baseline})
