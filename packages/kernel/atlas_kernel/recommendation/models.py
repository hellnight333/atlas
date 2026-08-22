"""What Qevik proposes doing, and why it believes it should be done.

A recommendation is not a finding restated in a friendlier tone. It names an
action, the capability that would perform it, what the customer must supply, and
what would later be measured to decide whether it worked. If any of those cannot
be filled in, the recommendation should not exist.

Two rules are enforced in the type rather than left to the caller:

**Evidence, or nothing.** A recommendation without evidence references is a sales
pitch, and constructing one raises. The same guard `Opportunity` already uses,
for the same reason.

**Unverified stays unverified.** Evidence the research engine could not confirm
may be *mentioned* — "we could not check this" is useful — but it may never be
the ground a recommendation rests on. A stage that failed has not discovered a
problem, and a recommendation built on one would be an invented weakness.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Unsupported(Exception):
    """A recommendation was built without the grounds to make it.

    Deliberately not caught anywhere. An unsupported recommendation is a
    fabricated claim about somebody's business, and failing loudly in a test is
    the cheapest place to find out.

    Not a `ValueError`, which is unusual and deliberate: pydantic converts
    `ValueError` raised inside a validator into a `ValidationError`, and the
    guard would then reach the caller as a generic validation failure among
    however many others. Raising outside that hierarchy means this one arrives
    as itself, and a caller can catch exactly it.
    """


class TaskKind(StrEnum):
    """Who has to do this.

    The distinction the later roadmap is built on. A plan that silently lists a
    customer's obligations as things Qevik will handle stalls, and nobody can
    see why — so the kind is on the task rather than inferred from its wording.
    """

    QEVIK_TASK = "qevik_task"
    CUSTOMER_TASK = "customer_task"


class RecommendationState(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    #: Refused for good. Re-proposing every cycle is how an automated system
    #: becomes noise a customer stops reading.
    DECLINED = "declined"
    #: Wanted, but something is missing — a connection, a permission, a plan.
    BLOCKED = "blocked"
    #: Approved and waiting on execution. P1.3 takes it from here.
    SCHEDULED = "scheduled"
    DONE = "done"


TERMINAL = frozenset({RecommendationState.DECLINED, RecommendationState.DONE})


class Task(BaseModel):
    """One step, and whose step it is."""

    model_config = ConfigDict(frozen=True)

    kind: TaskKind
    title: str
    #: Why this step exists, in the customer's terms.
    why: str = ""
    #: For a customer task: exactly what they must do. Empty for a Qevik task.
    action: str = ""
    blocks: bool = True

    def model_post_init(self, _: object) -> None:
        if self.kind is TaskKind.CUSTOMER_TASK and not self.action:
            raise Unsupported(
                f"{self.title!r} is a customer task with no action. A customer "
                "task that does not say what to do is a task nobody can complete."
            )


def QevikTask(title: str, why: str = "", *, blocks: bool = True) -> Task:
    return Task(kind=TaskKind.QEVIK_TASK, title=title, why=why, blocks=blocks)


def CustomerTask(title: str, action: str, why: str = "", *, blocks: bool = True) -> Task:
    return Task(kind=TaskKind.CUSTOMER_TASK, title=title, action=action, why=why,
                blocks=blocks)


class Recommendation(BaseModel):
    """An opportunity, joined to the capability that could act on it."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: f"rec-{datetime.now(UTC):%Y%m%d%H%M%S%f}")
    business_id: str
    #: Denormalised so a read can be scoped without a join, exactly as P1.1 did
    #: for businesses. A recommendation with no tenant belongs to nobody.
    tenant_id: str | None = None

    #: Provenance. Which opportunity, resting on which observations.
    opportunity_key: str
    evidence: tuple[str, ...] = ()
    #: Mentioned, never relied upon. Kept so a customer can see what we could
    #: not check rather than being told everything was verified.
    unverified: tuple[str, ...] = ()

    #: The capability that would execute it — an id in the existing registry.
    capability_id: str = ""
    offer_id: str = ""

    title: str
    rationale: str
    #: What the business already does well. Present so a recommendation to a
    #: strong company reads as an addition rather than a complaint.
    strengths: tuple[str, ...] = ()

    tasks: tuple[Task, ...] = ()
    priority: str = "MEDIUM"
    confidence: str = "MEDIUM"
    requires_approval: bool = True
    estimated_units: int = 0
    qa_layers: tuple[str, ...] = ()
    publication_target: str = ""
    measurement: tuple[str, ...] = ()

    state: RecommendationState = RecommendationState.PROPOSED
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def model_post_init(self, _: object) -> None:
        if not self.evidence:
            raise Unsupported(
                f"{self.id}: a recommendation with no evidence is a sales pitch. "
                "Cite the observations it rests on, or do not make it."
            )
        if not self.rationale.strip():
            raise Unsupported(f"{self.id}: a recommendation must say why it matters")
        if self.priority not in ("HIGH", "MEDIUM", "LOW"):
            raise Unsupported(f"{self.id}: priority {self.priority!r} is off the scale")

    @property
    def customer_tasks(self) -> tuple[Task, ...]:
        return tuple(t for t in self.tasks if t.kind is TaskKind.CUSTOMER_TASK)

    @property
    def qevik_tasks(self) -> tuple[Task, ...]:
        return tuple(t for t in self.tasks if t.kind is TaskKind.QEVIK_TASK)

    @property
    def waiting_on_customer(self) -> bool:
        return any(t.blocks for t in self.customer_tasks)

    @property
    def executable(self) -> bool:
        """Whether a job could be created from this today.

        Never true on its own. Approval is a separate act recorded elsewhere,
        and this only reports that nothing else is in the way.
        """
        return (self.state is RecommendationState.ACCEPTED
                and bool(self.capability_id)
                and not self.waiting_on_customer)

    def why(self) -> dict:
        """Everything needed to answer 'why am I being told this?'"""
        return {
            "opportunity": self.opportunity_key,
            "evidence": list(self.evidence),
            "not_verified": list(self.unverified),
            "strengths": list(self.strengths),
            "capability": self.capability_id,
            "approval_required": self.requires_approval,
            "customer_tasks": [t.title for t in self.customer_tasks],
            "qevik_tasks": [t.title for t in self.qevik_tasks],
            "measurement": list(self.measurement),
        }
