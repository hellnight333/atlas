"""The plan: what to do next, in what order, and who does it.

`Task` and `TaskKind` come from `recommendation.models` — there is no second
task registry, and a roadmap task *contains* one rather than restating it. What
this module adds is the part a plan needs and a recommendation does not: when it
should happen, what must happen first, and how anybody will know it worked.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ..recommendation.models import Task, TaskKind


class Horizon(StrEnum):
    """When, not how long. A horizon is a commitment about ordering."""

    DAY_7 = "7-day"
    DAY_30 = "30-day"
    DAY_60 = "60-day"
    DAY_90 = "90-day"


ORDER: tuple[Horizon, ...] = (Horizon.DAY_7, Horizon.DAY_30, Horizon.DAY_60,
                              Horizon.DAY_90)


class Executability(StrEnum):
    """Whether the thing proposed can actually be done, and by whom."""

    #: A registered capability can perform it now.
    QEVIK_CAN_EXECUTE = "qevik_can_execute"
    #: Only the customer can — an account, a permission, an approval.
    CUSTOMER_MUST_ACT = "customer_must_act"
    #: Worth doing, nothing can do it yet. Shown, never promised.
    NO_CAPABILITY = "no_capability"
    #: The dimension is unmeasured; measure before proposing a fix.
    MEASURE_FIRST = "measure_first"


class RoadmapTask(BaseModel):
    """One step of the plan."""

    model_config = ConfigDict(frozen=True)

    id: str
    #: The existing vocabulary, reused whole.
    task: Task
    horizon: Horizon
    executability: Executability

    dimension: str = ""
    why: str
    #: Observations this rests on. Empty is only legitimate for a measurement
    #: task, which exists precisely because there is nothing to rest on yet.
    evidence: tuple[str, ...] = ()
    #: Ids of tasks that must complete first.
    depends_on: tuple[str, ...] = ()
    requires_approval: bool = True

    recommendation_id: str = ""
    capability_id: str = ""
    #: What would later show whether this worked. A metric key from the
    #: measurement catalogue, so the roadmap and the measurement layer agree.
    metric_key: str = ""
    expected_outcome: str = ""
    confidence: str = "MEDIUM"

    @property
    def kind(self) -> TaskKind:
        return self.task.kind

    @property
    def is_customer(self) -> bool:
        return self.task.kind is TaskKind.CUSTOMER_TASK

    @property
    def blocked_by_customer(self) -> bool:
        """Who has to act is the task's kind, not its executability.

        Keying this on `CUSTOMER_MUST_ACT` looked equivalent and was not: a
        measurement task that needs a Search Console grant is `MEASURE_FIRST`
        *and* waiting on the customer, and reading only the executability
        dropped it out of the waiting list it belongs in.
        """
        return self.is_customer and self.task.blocks

    def model_post_init(self, _: object) -> None:
        # A task Qevik claims it can execute must name the capability that would
        # do it. Without that the claim is unverifiable, which is how a plan
        # promises work nothing can perform.
        if self.executability is Executability.QEVIK_CAN_EXECUTE and not self.capability_id:
            raise ValueError(
                f"{self.id}: claims Qevik can execute this but names no capability")
        if (self.executability is not Executability.MEASURE_FIRST
                and not self.evidence):
            raise ValueError(
                f"{self.id}: has no evidence and is not a measurement task. Every "
                "other kind of task must rest on something observed.")


class Roadmap(BaseModel):
    """A whole plan, for one business, at one moment."""

    model_config = ConfigDict(frozen=True)

    business_id: str
    tenant_id: str | None = None
    business_model: str = ""
    readiness_overall: int | None = None
    tasks: tuple[RoadmapTask, ...] = ()
    #: Dimensions deliberately left alone because they are already working.
    left_alone: tuple[str, ...] = ()
    generated_at: str = ""
    #: What this plan was derived from. Changing any of it should change the
    #: plan, and re-evaluation compares these.
    derived_from: dict = Field(default_factory=dict)

    def at(self, horizon: Horizon) -> tuple[RoadmapTask, ...]:
        return tuple(t for t in self.tasks if t.horizon is horizon)

    @property
    def customer_tasks(self) -> tuple[RoadmapTask, ...]:
        return tuple(t for t in self.tasks if t.is_customer)

    @property
    def qevik_tasks(self) -> tuple[RoadmapTask, ...]:
        return tuple(t for t in self.tasks if not t.is_customer)

    @property
    def waiting_on_customer(self) -> tuple[RoadmapTask, ...]:
        return tuple(t for t in self.tasks if t.blocked_by_customer)

    @property
    def measurement_tasks(self) -> tuple[RoadmapTask, ...]:
        return tuple(t for t in self.tasks
                     if t.executability is Executability.MEASURE_FIRST)

    def ready_now(self, completed: frozenset[str] = frozenset()) -> tuple[RoadmapTask, ...]:
        """Tasks whose prerequisites are all satisfied.

        The honest answer to "what can actually start today", which is usually
        shorter than the 7-day list and is the more useful number. With nothing
        completed it returns the unblocked tasks; as customer tasks finish, the
        work behind them becomes available without regenerating the plan.
        """
        return tuple(t for t in self.tasks
                     if all(d in completed for d in t.depends_on))

    def fingerprint(self) -> tuple:
        """What makes this plan this plan. Two businesses agreeing on it would
        mean the generator ignored their evidence."""
        return tuple(sorted((t.dimension, t.task.title, t.horizon.value)
                            for t in self.tasks))
