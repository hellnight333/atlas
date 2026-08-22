"""Where a roadmap task stands, derived from states that already exist.

No task table, no stored status field, no second lifecycle. A roadmap task is a
*view* over facts other systems already own authoritatively:

| Fact | Owner |
|---|---|
| Has the customer accepted the recommendation? | `RecommendationState` |
| Has a human approved this specific act? | `ApprovalState` |
| Has the work run? | `JobStatus` |
| Are its prerequisites done? | the roadmap's own dependency graph |

Folding rather than storing is the same choice the recommendation and event
layers already made, and it is the one that keeps a task honest: a stored status
can disagree with the job it describes, and when it does nobody can tell which
is lying. A derived one cannot disagree, because it has nothing of its own to
disagree with.

**Completion is about the work, not the business.** `COMPLETED` means the
requested work was done. Whether it helped is a measurement question, answered
in `measurement/` at an attribution level its own evidence supports, and there
is deliberately no state here that could be mistaken for "it worked".
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from ..approval.models import ApprovalState
from ..models import JobStatus
from ..recommendation.models import RecommendationState, TaskKind
from .models import Executability, Roadmap, RoadmapTask


class TaskState(StrEnum):
    """What is happening with a task. Derived, never assigned."""

    #: Proposed to the customer; no decision yet.
    PROPOSED = "proposed"
    #: Everything needed is in place except the approval to start.
    READY = "ready"
    #: Something must happen first — a dependency, or the customer.
    BLOCKED = "blocked"
    #: A human approved this specific act. Not yet started.
    APPROVED = "approved"
    #: A job is running.
    EXECUTING = "executing"
    #: The requested work was done. **Not** a claim that it worked.
    COMPLETED = "completed"
    #: Attempted and did not finish. Kept distinct from COMPLETED, because
    #: collapsing them is the same error as calling a completed task a success.
    FAILED = "failed"
    #: A human said no.
    REJECTED = "rejected"
    #: Withdrawn before a decision, or the recommendation was declined.
    CANCELLED = "cancelled"


#: States from which no further work follows.
TERMINAL: frozenset[TaskState] = frozenset(
    {TaskState.COMPLETED, TaskState.REJECTED, TaskState.CANCELLED})


class TaskFacts(BaseModel):
    """The authoritative states this task's position is folded from.

    Every field is `None` when the corresponding system has nothing to say,
    which is different from having said no — the same distinction the evidence
    layer makes between CONFIRMED_ABSENT and NOT_VERIFIED.
    """

    model_config = ConfigDict(frozen=True)

    recommendation_state: RecommendationState | None = None
    approval_state: ApprovalState | None = None
    job_status: JobStatus | None = None
    #: Ids of tasks recorded complete, against which `depends_on` is checked.
    completed_task_ids: frozenset[str] = frozenset()
    #: Titles of customer tasks the customer reported done. Titles rather than
    #: ids because that is what a `Recommendation` knows its tasks by, and
    #: `facts_for` derives these from `completed_task_ids` so the two cannot
    #: disagree about the same task.
    completed_customer_tasks: frozenset[str] = frozenset()
    #: Whether the customer has done what only they can do. `None` means nobody
    #: has recorded either way, which blocks — an unrecorded permission is not a
    #: granted one.
    customer_action_done: bool | None = None


def facts_for(roadmap: Roadmap, *, completed_task_ids: frozenset[str] = frozenset(),
              recommendation_state: RecommendationState | None = None,
              approval_state: ApprovalState | None = None,
              job_status: JobStatus | None = None,
              customer_action_done: bool | None = None) -> TaskFacts:
    """Build the facts for one roadmap, deriving what can be derived.

    The customer-task titles come from the roadmap's own tasks rather than being
    passed in beside the ids. Two hand-supplied lists of the same completions
    drift, and the failure is silent: work runs because one list said the
    customer was finished while the other still said they were not.
    """
    titles = frozenset(t.task.title for t in roadmap.tasks
                       if t.id in completed_task_ids
                       and t.kind is TaskKind.CUSTOMER_TASK)
    return TaskFacts(
        recommendation_state=recommendation_state, approval_state=approval_state,
        job_status=job_status, completed_task_ids=completed_task_ids,
        completed_customer_tasks=titles, customer_action_done=customer_action_done)


def state_of(task: RoadmapTask, facts: TaskFacts) -> TaskState:
    """Fold a task's position from what other systems already know.

    Order is by decisiveness, not by the order a task moves through. What has
    already happened outranks what is merely allowed: a task whose job completed
    is COMPLETED whatever its approval now says, because the work is done and
    reporting otherwise would be a lie about the past.

    BLOCKED outranks APPROVED for the opposite reason — approval is permission,
    not capability. A task approved while a prerequisite is outstanding cannot
    proceed, and reporting it as APPROVED puts it on a customer's list of things
    that are about to happen when it is not.
    """
    # --- what already happened ------------------------------------------
    if facts.job_status is JobStatus.COMPLETED:
        return TaskState.COMPLETED
    if facts.job_status is JobStatus.FAILED:
        return TaskState.FAILED
    if facts.job_status is JobStatus.CANCELLED:
        return TaskState.CANCELLED
    if facts.job_status in (JobStatus.RUNNING, JobStatus.QUEUED, JobStatus.PAUSED):
        return TaskState.EXECUTING

    # --- what a human decided -------------------------------------------
    if facts.approval_state is ApprovalState.REJECTED:
        return TaskState.REJECTED
    if facts.approval_state in (ApprovalState.CANCELLED, ApprovalState.EXPIRED):
        return TaskState.CANCELLED
    if facts.recommendation_state is RecommendationState.DECLINED:
        return TaskState.REJECTED

    # --- has anyone agreed to it yet ------------------------------------
    # Before acceptance a task is a proposal, whatever else is outstanding.
    # Reporting it as BLOCKED would say something is in the way of work nobody
    # has agreed to do, which reads to a customer as a problem on a plan they
    # have not yet said yes to. A measurement task belongs to no recommendation
    # and so skips this.
    if task.recommendation_id and facts.recommendation_state is not RecommendationState.ACCEPTED:
        return TaskState.PROPOSED

    # --- what is in the way ---------------------------------------------
    if blockers(task, facts):
        return TaskState.BLOCKED

    if facts.approval_state is ApprovalState.APPROVED:
        return TaskState.APPROVED

    return TaskState.READY


def blockers(task: RoadmapTask, facts: TaskFacts) -> tuple[str, ...]:
    """Everything standing between this task and starting. Empty means nothing.

    Returned as sentences rather than a boolean so a customer can be told which
    thing is in the way. "Blocked" with no reason is the state that makes people
    stop reading a plan.
    """
    reasons: list[str] = []
    outstanding = [d for d in task.depends_on if d not in facts.completed_task_ids]
    if outstanding:
        reasons.append(f"waiting on {', '.join(outstanding)}")
    if task.kind is TaskKind.CUSTOMER_TASK and not facts.customer_action_done:
        reasons.append("waiting on the customer to do it")
    if task.executability is Executability.NO_CAPABILITY:
        reasons.append("no Qevik capability can perform this yet")
    if task.executability is Executability.MEASURE_FIRST and not facts.customer_action_done:
        # A measurement task needing a connection is blocked on the connection.
        # One Qevik can run alone records `customer_action_done=True`.
        if task.kind is TaskKind.CUSTOMER_TASK:
            reasons.append("waiting on access to the measurement source")
    return tuple(reasons)
