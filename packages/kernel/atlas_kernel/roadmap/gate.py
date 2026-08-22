"""Whether a roadmap task may become work, and if not, exactly why not.

Seven conditions, each checked explicitly and each able to name itself. There is
no path through this module that reaches "executable" by not finding a problem —
every condition must be positively satisfied, and anything unknown counts as
unsatisfied. A missing approval record and a rejected one both stop the work;
the difference is what the customer is told.

The recommendation-level conditions are not re-implemented here. They belong to
`execution.service.may_execute`, which P1.3 already enforces, and this calls it
rather than growing a second opinion about the same question.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..approval.models import ApprovalRequest, ApprovalState
from ..execution.models import NotApproved, UnsupportedCapability
from ..execution.service import may_execute
from ..opportunity.tenancy import TenantId, owns
from ..recommendation.models import Recommendation, TaskKind
from .lifecycle import TaskFacts, blockers
from .models import Executability, RoadmapTask

if TYPE_CHECKING:                       # credits imports recommendation, which
    from ..credits.service import CreditService  # this package also imports

#: What the approval carries so a decision can be shown to describe this task
#: and no other. Same mechanism as the outreach gate's proposal fingerprint.
TASK_FINGERPRINT = "roadmap_task_fingerprint"

#: The action name a policy can attach to, without this module knowing that any
#: particular policy exists.
EXECUTE_ACTION = "qevik.roadmap.task.execute"


class NotExecutable(Exception):
    """The task may not become work. Carries every reason, not just the first.

    Reporting one reason at a time turns a blocked task into a queue of
    surprises: fix the approval, discover the dependency; fix that, discover the
    tenant. A customer should see the whole list once.
    """

    def __init__(self, task_id: str, reasons: tuple[str, ...]) -> None:
        self.task_id = task_id
        self.reasons = reasons
        super().__init__(f"{task_id} cannot execute: " + "; ".join(reasons))


@dataclass(frozen=True)
class Readiness:
    """The answer, with its reasoning kept."""

    executable: bool
    reasons: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.executable


def fingerprint(task: RoadmapTask) -> str:
    """What was approved. Changing any of it invalidates the approval.

    Covers what the act *is* — the capability, the business, the evidence it
    rests on — rather than everything on the task. Rescheduling a task from the
    30-day to the 60-day horizon does not change what a person consented to, and
    invalidating their decision over it would train people to re-approve without
    reading.
    """
    import hashlib
    import json

    material = {
        "task": task.task.title,
        "kind": task.task.kind.value,
        "capability_id": task.capability_id,
        "recommendation_id": task.recommendation_id,
        "dimension": task.dimension,
        "evidence": sorted(task.evidence),
    }
    return hashlib.sha256(
        json.dumps(material, sort_keys=True).encode("utf-8")).hexdigest()[:32]


def unmet(task: RoadmapTask, *, recommendation: Recommendation | None,
          approval: ApprovalRequest | None, facts: TaskFacts,
          tenant: TenantId | None,
          credits: CreditService | None = None) -> tuple[str, ...]:
    """Every condition this task does not satisfy. Empty means it may execute."""
    reasons: list[str] = []

    # 1. Qevik must be the one who can do it. A customer task is never ours to
    #    execute, whatever else is in place — this is the first check because it
    #    is the one whose failure means the others do not even apply.
    if task.kind is TaskKind.CUSTOMER_TASK:
        reasons.append("this is a customer task; only the customer can do it")
    if task.executability is not Executability.QEVIK_CAN_EXECUTE:
        reasons.append(f"executability is {task.executability.value}, "
                       "so Qevik has not claimed it can perform this")

    # 2. A capability must be named. The model already refuses to construct a
    #    QEVIK_CAN_EXECUTE task without one; checked again because this is the
    #    gate, and a gate that trusts an upstream invariant is not a gate.
    if not task.capability_id:
        reasons.append("no capability is named")

    # 3. The recommendation behind it must exist and still be the same one.
    if recommendation is None:
        reasons.append("the recommendation behind it was not supplied")
    elif recommendation.id != task.recommendation_id:
        reasons.append(f"recommendation {recommendation.id} is not this task's "
                       f"{task.recommendation_id or 'unnamed recommendation'}")

    # 4. Evidence. A task with none is a proposal nobody can check.
    if not task.evidence:
        reasons.append("it rests on no recorded evidence")

    # 5. Tenancy, on the task and on the recommendation both. An owner that
    #    cannot be established is not a match, and no tenant at all is refused
    #    rather than treated as "any" — the opposite default would make an
    #    unscoped call the most permissive one available.
    if tenant is None:
        reasons.append("no tenant was supplied, so ownership cannot be established")
    elif not owns(task.tenant_id, tenant):
        reasons.append("it belongs to a different tenant")
    elif recommendation is not None and not owns(recommendation.tenant_id, tenant):
        reasons.append("its recommendation belongs to a different tenant")

    # 6. Dependencies and outstanding customer work.
    reasons.extend(blockers(task, facts))

    # 7. Approval, bound to this exact task.
    if approval is None:
        reasons.append("no approval has been requested for it")
    elif approval.state is not ApprovalState.APPROVED:
        reasons.append(f"approval {approval.id} is {approval.state.value}")
    else:
        recorded = approval.metadata.get(TASK_FINGERPRINT)
        if not recorded:
            reasons.append(f"approval {approval.id} records no task fingerprint, "
                           "so it cannot be shown to describe this task")
        elif recorded != fingerprint(task):
            reasons.append("the task changed after it was approved; "
                           "re-request approval for the new version")

    # 8. The allowance, when credit enforcement is switched on. Optional
    #    because plans are not assigned yet — but *fail-closed once supplied*: a
    #    tenant with no plan is refused rather than treated as unlimited, which
    #    is the failure mode that makes a plan meaningless.
    if credits is not None and recommendation is not None:
        try:
            if credits.balance(tenant) < credits.units_for(recommendation.offer_id):
                reasons.append(
                    f"the {credits.plan_of(tenant).value} plan has "
                    f"{credits.balance(tenant):g} units left and this needs "
                    f"{credits.units_for(recommendation.offer_id):g}")
        except Exception as refusal:              # noqa: BLE001 - reported, not raised
            reasons.append(f"credits: {refusal}")

    # 9. And whatever P1.3 already refuses. Called rather than restated so the
    #    two cannot drift into disagreeing about the same recommendation.
    if recommendation is not None:
        try:
            may_execute(recommendation,
                        approved=approval is not None
                        and approval.state is ApprovalState.APPROVED,
                        customer_done=facts.completed_customer_tasks)
        except (NotApproved, UnsupportedCapability) as refusal:
            reasons.append(str(refusal))

    return tuple(dict.fromkeys(reasons))          # de-duplicated, order kept


def check(task: RoadmapTask, *, recommendation: Recommendation | None,
          approval: ApprovalRequest | None, facts: TaskFacts,
          tenant: TenantId | None,
          credits: CreditService | None = None) -> Readiness:
    """Non-raising form, for showing a customer why something is waiting."""
    reasons = unmet(task, recommendation=recommendation, approval=approval,
                    facts=facts, tenant=tenant, credits=credits)
    return Readiness(executable=not reasons, reasons=reasons)


def require(task: RoadmapTask, *, recommendation: Recommendation | None,
            approval: ApprovalRequest | None, facts: TaskFacts,
            tenant: TenantId | None,
            credits: CreditService | None = None) -> None:
    """Raise unless every condition is satisfied."""
    reasons = unmet(task, recommendation=recommendation, approval=approval,
                    facts=facts, tenant=tenant, credits=credits)
    if reasons:
        raise NotExecutable(task.id, reasons)
