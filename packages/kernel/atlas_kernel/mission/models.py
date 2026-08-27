"""A human-level request, and the plan it becomes.

A `Mission` is *"build multi-page website support"* or *"connect Cloudflare"* —
the thing a person asks for. It is not a unit of executable work: `Job` is, and
`Job` stays authoritative for anything that runs. Missions sit above jobs at the
product layer, which is why their statuses describe a *request's* life (drafted,
planned, awaiting approval, reviewed, committed) rather than a process's
(queued, running, failed). Collapsing the two would give the system two answers
to "what is running", and §9 forbids exactly that.

**Nothing here is stored in a new table.** A mission is a sequence of
`BusinessEvent`s and its status is folded from them, the same as a roadmap, a
publication and a credit reservation. That is what makes it survive a restart
without a migration — and it means the history of a mission cannot be quietly
rewritten, because the events are append-only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class MissionStatus(StrEnum):
    """A request's life. Deliberately not `JobStatus` — see the module note."""

    DRAFT = "draft"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    QUEUED = "queued"
    PROCESSING = "processing"
    TESTING = "testing"
    REVIEWING = "reviewing"
    COMMITTING = "committing"
    COMPLETE = "complete"
    FAILED = "failed"
    #: Waiting on something outside the system — a credential, a host, a person.
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


#: Statuses from which nothing further happens on its own.
TERMINAL: frozenset[MissionStatus] = frozenset(
    {MissionStatus.COMPLETE, MissionStatus.FAILED, MissionStatus.CANCELLED})

#: Statuses a worker may pick up. Nothing else is claimable, which is what stops
#: a worker starting a mission whose plan nobody has approved.
CLAIMABLE: frozenset[MissionStatus] = frozenset({MissionStatus.QUEUED})


class Blocker(BaseModel):
    """Why a mission cannot proceed, classified rather than described.

    The class matters more than the sentence: a credential blocker stops one
    capability, an architecture blocker stops a design decision, and treating
    them the same is how a project reports itself as stuck.
    """

    model_config = ConfigDict(frozen=True)

    #: One of the classes in §1 of the directive.
    kind: str
    detail: str
    #: What a person would actually do about it.
    action: str = ""


class PlanStep(BaseModel):
    """One step of a proposed implementation, before anybody agreed to it."""

    model_config = ConfigDict(frozen=True)

    order: int
    title: str
    why: str = ""
    #: Files the step expects to touch. An expectation, not a promise — recorded
    #: so a review can compare it against what actually changed.
    files: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()


class Plan(BaseModel):
    """What the agent proposes, for a human to approve, edit, reject or defer.

    The plan is the safety boundary §10 describes: arbitrary chat text never
    becomes execution directly, it becomes a plan somebody can read first.
    """

    model_config = ConfigDict(frozen=True)

    goal: str
    why: str = ""
    current_state: str = ""
    steps: tuple[PlanStep, ...] = ()
    dependencies: tuple[str, ...] = ()
    blockers: tuple[Blocker, ...] = ()
    test_plan: str = ""
    security_impact: str = ""
    rollback: str = ""
    #: Whether policy requires a human decision before this runs.
    approval_required: bool = True
    #: Estimated, and labelled as such. Never presented as a known figure.
    estimated_cost: float | None = None
    cost_status: str = "ESTIMATED"

    @property
    def files(self) -> tuple[str, ...]:
        seen: list[str] = []
        for step in self.steps:
            seen.extend(f for f in step.files if f not in seen)
        return tuple(seen)


class AgentInvocation(BaseModel):
    """One call to a coding agent, and what it cost.

    Token counts and cost are optional because not every provider reports them.
    `cost_status` says which it was: a fabricated exact figure would be the one
    number in this system nobody could check.
    """

    model_config = ConfigDict(frozen=True)

    provider: str
    model: str
    task: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    duration_seconds: float | None = None
    cost: float | None = None
    currency: str = ""
    #: REPORTED when the provider supplied it, ESTIMATED when computed from a
    #: configured price table, UNKNOWN when neither.
    cost_status: str = "UNKNOWN"
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def model_post_init(self, _: object) -> None:
        if self.cost is not None and self.cost_status == "UNKNOWN":
            raise ValueError(
                "a cost was supplied without saying where it came from. "
                "Set cost_status to REPORTED or ESTIMATED — an unlabelled "
                "figure reads as authoritative and cannot be checked.")


class Mission(BaseModel):
    """A human request, its plan, and what became of it."""

    model_config = ConfigDict(frozen=True)

    id: str
    tenant_id: str
    title: str
    description: str = ""
    requested_by: str = ""
    status: MissionStatus = MissionStatus.DRAFT
    priority: int = 0
    plan: Plan | None = None
    #: Existing ids. A mission references jobs; it does not replace them.
    job_ids: tuple[str, ...] = ()
    commits: tuple[str, ...] = ()
    invocations: tuple[AgentInvocation, ...] = ()
    blockers: tuple[Blocker, ...] = ()
    report_path: str = ""
    #: Set while a worker holds it, so a restart can tell a crashed mission from
    #: one nobody has started.
    claimed_by: str = ""
    #: Deliberately held until this moment — a window somebody chose, not a
    #: delay. Durable, because "why has this not run" must survive a restart
    #: with an answer that is not "the queue is long".
    not_before: datetime | None = None
    #: The recurring occurrence that created this mission, empty for one-off
    #: work. Carried on the mission rather than in a table of its own so the
    #: timeline stays the single record: "has tonight's scan already been
    #: created" is then answered by the missions themselves, and a second store
    #: cannot drift from them.
    occurrence: str = ""
    #: Where the work actually happened, and what it started from. A report
    #: saying "committed abc1234" names a sha that now exists only in a scratch
    #: clone; without these three, nothing anywhere says which repository to
    #: look in, and the commit becomes a rumour.
    #:
    #: `origin_kind` is `qevik` / `external` / `empty` — decided by comparing the
    #: origin against the repository this code is running from, so it cannot be
    #: set to the convenient answer from a config file.
    #: **Declared before execution**: which origin this mission asks for, by
    #: name. A key, never a path — see `mission/origins.py`. Empty means it did
    #: not ask, and the registry's default applies, which is Qevik and therefore
    #: needs a person.
    origin_name: str = ""
    #: Which agent is expected to carry this out, by registry id. Set when the
    #: plan is attached, from the same value `policy.decide` was given — so the
    #: blast radius a person approved and the blast radius anything else reads
    #: later are the same one. Empty means nobody named an agent, which policy
    #: already treats as the worst case.
    agent_id: str = ""
    #: Which recipe carries this out, by name. A **key** into `fabric.recipes`,
    #: exactly like `origin_name` is a key into the origin registry: a model may
    #: propose `recipe = "discover-uae-dental"` and cannot propose a step, a
    #: tool or a URL. A name nobody declared is a refusal, never a default.
    recipe: str = ""
    #: **Recorded after execution**: where the work actually happened, what it
    #: was cloned from, and what that was. Separate from `origin_name` on
    #: purpose: one is a request and the other is what happened, and a single
    #: field would make a mission that was refused look like one that ran.
    workspace: str = ""
    origin: str = ""
    origin_kind: str = ""
    #: The opportunity a person approved to produce this mission, by id. Empty
    #: for work that came from anywhere else.
    #:
    #: A signal is **not** a mission and never becomes one — this is a
    #: reference, written once when the approval was given, so the delivery and
    #: everything downstream of it can be traced to the specific opportunity a
    #: person said yes to rather than to "an opportunity of this kind".
    signal_id: str = ""
    #: What was approved, as the offer keys the opportunity's evidence
    #: supported. The mission may do this and nothing wider: a delivery that
    #: grew a scope after approval would be work nobody agreed to.
    approved_scope: str = ""
    #: The fingerprints the opportunity rested on, copied at approval.
    #:
    #: Copied rather than looked up, so the report can say what justified the
    #: work without depending on the signals table still holding the row — and
    #: so a later edit to the opportunity cannot silently restate what was
    #: approved.
    evidence_fingerprints: tuple[str, ...] = ()
    #: The mission whose artefact this one publishes. Empty for everything that
    #: is not a publication.
    #:
    #: One field, not four. The commit and the address are re-read from the
    #: authorisation at execution rather than carried here: a mission that held
    #: them could have them edited between the approval and the run, and then
    #: the record and the act would disagree with nothing to say which was right.
    publishes: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL

    @property
    def claimable(self) -> bool:
        return self.status in CLAIMABLE and not self.claimed_by

    @property
    def total_cost(self) -> float | None:
        """Summed only over invocations that reported a cost.

        `None` when nothing did — not zero, for the same reason a missing
        measurement is not zero.
        """
        known = [i.cost for i in self.invocations if i.cost is not None]
        return sum(known) if known else None

    def summary(self) -> dict:
        return {
            "mission_id": self.id, "tenant_id": self.tenant_id,
            "title": self.title, "description": self.description,
            "requested_by": self.requested_by, "status": self.status.value,
            "priority": self.priority,
            "plan": self.plan.model_dump(mode="json") if self.plan else None,
            "job_ids": list(self.job_ids), "commits": list(self.commits),
            "invocations": [i.model_dump(mode="json") for i in self.invocations],
            "blockers": [b.model_dump(mode="json") for b in self.blockers],
            "report_path": self.report_path, "claimed_by": self.claimed_by,
            "not_before": self.not_before.isoformat() if self.not_before else None,
            "occurrence": self.occurrence,
            "origin_name": self.origin_name, "agent_id": self.agent_id,
            "recipe": self.recipe,
            "workspace": self.workspace, "origin": self.origin,
            "origin_kind": self.origin_kind,
            "signal_id": self.signal_id,
            "approved_scope": self.approved_scope,
            "evidence_fingerprints": list(self.evidence_fingerprints),
            "publishes": self.publishes,
            "total_cost": self.total_cost,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
