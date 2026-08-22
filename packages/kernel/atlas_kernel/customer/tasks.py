"""What Qevik needs from the customer, and what counts as having got it.

A customer task is the only kind of work Qevik cannot do, so it is also the only
kind whose completion Qevik cannot observe by having done it. That makes "is it
done?" a real question rather than a bookkeeping one, and the tempting answer —
a checkbox — is the one that quietly unblocks execution against work nobody did.

So completion needs **proof**, and the kind of proof is declared per task rather
than assumed:

============  ==============================================================
OBSERVED      The system checked. A domain resolves; an account answers.
APPROVAL      An `ApprovalRequest` reached APPROVED. A human decision, on file.
ARTEFACT      The customer supplied something, and it is stored under an id.
ATTESTATION   The customer said so. Only where the task is *designed* for it.
============  ==============================================================

`ATTESTATION` exists because some things genuinely cannot be checked — "we have
permission to use these photographs" is a statement about a contract Qevik
cannot read. Recording it as an attestation, with who said it and when, is
honest. Recording it as an observation would not be, and recording it as
nothing at all is how that question gets skipped.

Nothing here is a new task registry. A `Task` is the existing one from
`recommendation.models`; this adds the evidence that it happened.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ..approval.models import ApprovalRequest, ApprovalState
from ..opportunity.models import BusinessEvent
from ..opportunity.tenancy import TenantId, owns
from ..opportunity.tenancy import require as _require_tenant
from ..recommendation.models import TaskKind
from ..research.net import Resolution, host_of, resolution
from ..roadmap.lifecycle import TaskFacts, blockers
from ..roadmap.models import Roadmap, RoadmapTask

FACTORY = "customer"
COMPLETED = "customer_task_completed"


class ProofKind(StrEnum):
    OBSERVED = "observed"
    APPROVAL = "approval"
    ARTEFACT = "artefact"
    ATTESTATION = "attestation"


#: Kinds the system establishes for itself. Anything else rests on a person,
#: and the record says whose word it is.
VERIFIABLE: frozenset[ProofKind] = frozenset({ProofKind.OBSERVED,
                                              ProofKind.APPROVAL})


class ProofRejected(Exception):
    """The evidence offered does not establish that the task was done."""


class Proof(BaseModel):
    """Why the system believes a customer task is complete."""

    model_config = ConfigDict(frozen=True)

    kind: ProofKind
    #: What was checked or supplied: a hostname, an approval id, an asset id.
    #: Never a secret — this is written to the timeline and shown back.
    reference: str
    detail: str = ""
    #: Who supplied it. For an attestation this is the whole of the evidence,
    #: so it is required rather than defaulted to "system".
    attested_by: str = ""
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def model_post_init(self, _: object) -> None:
        if not self.reference.strip():
            raise ProofRejected(f"{self.kind.value} proof names nothing")
        if self.kind is ProofKind.ATTESTATION and not self.attested_by.strip():
            raise ProofRejected(
                "an attestation is somebody's word, so it has to record whose. "
                "Without a name it is an unsourced claim in the customer's file.")


def verify_domain(host: str) -> Proof:
    """Check that a domain the customer said they connected actually resolves.

    The one customer task Qevik can genuinely observe, and worth doing properly:
    a plan that proceeds to publish against a domain that does not exist fails
    at the last step, in front of the customer.
    """
    name = host_of(host)
    answer = resolution(name)
    if answer is not Resolution.RESOLVED:
        raise ProofRejected(
            f"{name or host!r} does not resolve ({answer.value}), so it has not "
            "been connected yet. This is checked rather than taken on trust "
            "because publishing to a domain that does not exist fails in front "
            "of the customer.")
    return Proof(kind=ProofKind.OBSERVED, reference=name,
                 detail="the domain resolves")


def verify_approval(approval: ApprovalRequest) -> Proof:
    """An approval is complete evidence of the decision it records."""
    if approval.state is not ApprovalState.APPROVED:
        raise ProofRejected(
            f"approval {approval.id} is {approval.state.value}, so nothing has "
            "been agreed")
    return Proof(kind=ProofKind.APPROVAL, reference=approval.id,
                 detail=approval.title,
                 attested_by=next((d.actor for d in approval.decisions), ""))


def complete(task: RoadmapTask, proof: Proof, *, tenant: TenantId | None,
             actor: str = "customer") -> BusinessEvent:
    """Record that the customer did their part, with the evidence.

    Refuses a Qevik task: completing our own work on the customer's behalf is
    the conversion this whole distinction exists to prevent, and it would arrive
    here as a plausible-looking call.
    """
    tenant = _require_tenant(tenant, method="customer.tasks.complete")
    if not owns(task.tenant_id, tenant):
        raise PermissionError("this task belongs to a different tenant")
    if task.kind is not TaskKind.CUSTOMER_TASK:
        raise ProofRejected(
            f"{task.task.title!r} is a Qevik task. Marking it complete on the "
            "customer's behalf would turn work we owe them into work they did.")
    return BusinessEvent(
        business_id="", factory=FACTORY, kind=COMPLETED,
        actor=actor if proof.kind is not ProofKind.ATTESTATION else proof.attested_by,
        detail={"roadmap_task_id": task.id, "tenant_id": task.tenant_id,
                "title": task.task.title, "proof": proof.model_dump(mode="json"),
                # Stated so a later reader does not have to know which kinds are
                # checkable to know whether this was checked.
                "verified_by_system": proof.kind in VERIFIABLE})


def completed_ids(events: list, *, tenant: TenantId | None = None) -> frozenset[str]:
    """Task ids the customer has completed, folded from the timeline."""
    tenant = _require_tenant(tenant, method="customer.tasks.completed_ids")
    done = set()
    for event in events:
        kind = getattr(event, "kind", None) or event.get("kind")
        if kind != COMPLETED:
            continue
        detail = getattr(event, "detail", None) or event.get("detail") or {}
        if not owns(detail.get("tenant_id"), tenant):
            continue
        if task_id := detail.get("roadmap_task_id"):
            done.add(task_id)
    return frozenset(done)


def outstanding(roadmap: Roadmap, facts: TaskFacts) -> tuple[dict, ...]:
    """"What does Qevik need from me?", in the order it is needed.

    Only tasks that are actually the customer's, only ones not yet done, and
    each one saying what it unblocks — a list of obligations with no consequence
    attached is one people put off.
    """
    waiting = []
    by_id = {t.id: t for t in roadmap.tasks}
    for task in roadmap.tasks:
        if task.kind is not TaskKind.CUSTOMER_TASK:
            continue
        if task.id in facts.completed_task_ids:
            continue
        unblocks = [by_id[other.id].task.title for other in roadmap.tasks
                    if task.id in other.depends_on]
        waiting.append({
            "task_id": task.id,
            "title": task.task.title,
            "do": task.task.action,
            "why": task.why,
            "horizon": task.horizon.value,
            "unblocks": unblocks,
            "blocked_by": list(blockers(task, facts)),
        })
    return tuple(waiting)
