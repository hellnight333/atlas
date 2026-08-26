"""Whether a plan may run without a person. Decided here, never by the planner.

`attach_plan` read `Plan.approval_required` and routed on it. That field is set
by whatever produced the plan — and `FakeCodingAgent` sets it to `False`, so a
plan from it went **straight to QUEUED**, skipping approval entirely. An LLM
agent emitting the same value would have been obeyed identically.

That is the model authorising its own work, which is the one thing the whole
architecture is arranged to prevent.

## The planner may raise the bar, never lower it

    required = policy_says_yes  OR  plan.approval_required

A planner that asks for review gets review. A planner that says "no review
needed" is ignored. The same shape as an agent's blast radius against its tools:
more cautious than the rule is allowed, less is not.

## Deny by default

`decide()` returns "approval required" unless a rule explicitly clears it, and
the only rules that clear it are about work that is cheap, reversible and
confined. A new capability arriving with no matching rule needs a person, which
is the correct failure direction for authority.

## Deterministic

No model input, no network, no clock beyond what is passed in. The same plan and
the same context always produce the same verdict — which is what makes it
reviewable, and what makes "the model proposed X and policy allowed it" a
sentence somebody can check.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from ..fabric.agents import Blast, Registry, UnknownAgent
from .models import Plan


class Requirement(StrEnum):
    """What a person has to do before this runs.

    Three values, not a boolean. "Somebody must agree this work should happen"
    and "somebody must agree to *this exact output* going live" are different
    decisions made at different times, and collapsing them is how an execution
    approval gets treated as permission to publish.
    """

    #: Nobody. Cheap, reversible, confined work.
    NONE = "none"
    #: A person agrees the work should happen. Before it runs.
    EXECUTION = "execution"
    #: A person agrees to the exact artefact. After it exists, before it leaves.
    ARTEFACT = "artefact"


#: Above this estimated cost, a person decides. Deliberately low: the question
#: is not "is this expensive" but "would somebody want to have been asked".
COSTLY_UNITS = 5.0

#: Paths a plan may touch without review. Everything else is reviewed — an
#: allow-list, because a deny-list is a promise to have thought of every
#: dangerous path anybody will ever add.
SAFE_PREFIXES: tuple[str, ...] = ("docs/", "reports/", "tests/")


class Verdict(BaseModel):
    """What policy decided, and why, in words a person can check."""

    model_config = ConfigDict(frozen=True)

    requirement: Requirement
    #: The rule that decided it. Named, so "why did this need approval" has an
    #: answer that is not "the policy".
    because: str
    #: True when the planner asked for more review than policy required. Kept
    #: visible so a planner that always asks is noticeable rather than invisible.
    planner_raised_it: bool = False

    @property
    def needs_a_person(self) -> bool:
        return self.requirement is not Requirement.NONE

    def summary(self) -> dict:
        return {"requirement": self.requirement.value, "because": self.because,
                "planner_raised_it": self.planner_raised_it,
                "needs_a_person": self.needs_a_person}


def decide(plan: Plan, *, agent_id: str = "", registry: Registry | None = None,
           tenant_is_metered: bool = True,
           modifies_qevik_itself: bool = True) -> Verdict:
    """Whether this plan needs a person, and which kind of approval.

    `agent_id` names who would carry it out. Absent, the answer is EXECUTION:
    work whose performer is unknown has an unknown blast radius, and the
    architecture's own rule is that an unknown blast radius is the one thing
    approval cannot work around.

    `modifies_qevik_itself` defaults to **True**, and a caller has to state
    otherwise. The production worker's `--repository` is Qevik's own source, so
    every mission today edits the system that is deciding whether to allow it. A
    cheap docs-only plan satisfied every rule below and reached the queue with
    nobody asked — self-modification arriving as a side effect of a path
    allow-list rather than as anybody's decision.
    """
    # 1a. Changing Qevik itself. Above every other rule, including the cheap
    #     paths: "reversible" is doing a lot of work when the thing being
    #     changed is the thing that decides what reversible means.
    if modifies_qevik_itself:
        return _with_planner(
            plan, Requirement.EXECUTION,
            "this changes Qevik's own source, and Qevik does not authorise "
            "changes to Qevik")
    # 1. Irreversible work always needs approval of the exact artefact. Checked
    #    first because nothing below can lower it — an email cannot be unsent
    #    however cheap it was.
    blast = _blast_of(agent_id, registry)
    if blast is Blast.IRREVERSIBLE:
        return _with_planner(plan, Requirement.ARTEFACT,
                             f"{agent_id or 'this work'} cannot be undone, so a "
                             "person approves the exact output rather than the "
                             "intention")

    if not agent_id:
        return _with_planner(plan, Requirement.EXECUTION,
                             "nothing names which agent would do this, so its "
                             "blast radius is unknown")

    # 2. Cost. UNKNOWN is not free — the same rule the scheduler applies.
    if plan.estimated_cost is None:
        if tenant_is_metered:
            return _with_planner(plan, Requirement.EXECUTION,
                                 "nothing estimated what this costs, and an "
                                 "unpriced call is not a free one")
    elif plan.estimated_cost > COSTLY_UNITS:
        return _with_planner(plan, Requirement.EXECUTION,
                             f"it is estimated at {plan.estimated_cost:g} units, "
                             f"above the {COSTLY_UNITS:g} a person is asked about")

    # 3. Where it writes. An allow-list: a plan touching anything outside it is
    #    reviewed, including a plan that touches nothing identifiable.
    unsafe = tuple(f for f in plan.files
                   if not f.startswith(SAFE_PREFIXES))
    if unsafe:
        return _with_planner(plan, Requirement.EXECUTION,
                             f"it writes outside the reviewed-free paths: "
                             f"{', '.join(sorted(unsafe)[:4])}")

    if blast is Blast.COSTLY:
        return _with_planner(plan, Requirement.EXECUTION,
                             f"{agent_id} spends money to produce a result")

    # 4. Cheap, reversible, confined. The only path to no approval, and it is
    #    reached by satisfying every rule rather than by matching none.
    return _with_planner(plan, Requirement.NONE,
                         "cheap, reversible, and confined to reviewed-free "
                         "paths")


def _blast_of(agent_id: str, registry: Registry | None) -> Blast:
    if not agent_id:
        return Blast.REVERSIBLE
    try:
        return (registry or Registry()).get(agent_id).blast
    except UnknownAgent:
        # An agent nobody declared. Treated as the worst case rather than the
        # best: the registry is the record of what an agent may do, and work by
        # something absent from it has no bounded radius at all.
        return Blast.IRREVERSIBLE


def _with_planner(plan: Plan, decided: Requirement, because: str) -> Verdict:
    """Apply the planner's request, which may only raise the requirement."""
    if decided is Requirement.NONE and plan.approval_required:
        return Verdict(requirement=Requirement.EXECUTION,
                       because="policy did not require it; the planner asked "
                               "for review anyway",
                       planner_raised_it=True)
    return Verdict(requirement=decided, because=because)


def refuse_unapproved_self_modification(
        history: list[dict], *, origin_is_qevik: bool) -> str:
    """Why this mission must not run against Qevik's own source, or "".

    A second, later check than `decide`, and deliberately not a repetition of
    it. `decide` runs when a plan is attached, using what the planner *declared*
    about the work. This runs in the worker, using what the origin repository
    *actually is* — and the two can disagree, because the declaration is a
    field and the origin is a fact.

    Without it, a plan declaring `modifies_qevik_itself=False` reaches QUEUED
    with nobody asked, and the worker then hands it a clone of Qevik. The scratch
    clone makes that harmless to the production checkout and does not make it
    harmless: the whole point of staging work in a clone is that somebody later
    promotes it.

    Approval is detected structurally rather than by reading a note. The only
    route from AWAITING_APPROVAL is a person acting, so a mission that was ever
    in that state was approved by one; a mission that went PLANNING -> QUEUED
    was cleared by policy alone. Matching on the words "approved by operator"
    would pass for any mission whose note happened to contain them.
    """
    if not origin_is_qevik:
        return ""
    if any(entry.get("status") == "awaiting_approval" for entry in history):
        return ""
    return ("this mission would run against Qevik's own repository, and no "
            "person ever approved it — it reached the queue on policy alone, "
            "which means something declared it was not a change to Qevik")


def refuse_agent_substitution(named: str, available: str) -> str:
    """Why this worker must not run this mission, or "".

    A mission records the agent its plan was approved with — the same value
    `decide()` was given, and therefore the blast radius a person actually
    agreed to. A worker runs whatever its own `--agent` says.

    Those can differ, and nothing was comparing them: a mission approved as
    `self-check` work (deterministic, no network, no credentials) picked up by a
    worker started with `--agent llm` was carried out by a model. The approval
    was for one thing and the execution was another, which makes the approval
    record wrong rather than merely stale.

    Refusing is the only safe direction. Substituting "a more capable agent"
    silently widens the blast radius; substituting a less capable one silently
    produces work nobody can trust. Both are the model or the operator getting
    authority that policy did not grant.

    An unnamed agent is not a substitution — nothing was promised — so it is
    allowed, and the worker records what it actually used.
    """
    if not named:
        return ""
    if not available:
        return (f"this mission was approved to run as {named!r}, and this "
                "worker has no declared agent at all")
    if named != available:
        return (f"this mission was approved to run as {named!r} and this worker "
                f"runs {available!r}. The blast radius a person agreed to is "
                f"the one attached to {named!r}, so another agent may not stand "
                "in for it — start a worker that serves it.")
    return ""


def describe() -> dict:
    """The rules, for a report or a review screen."""
    return {
        "costly_units": COSTLY_UNITS,
        "reviewed_free_paths": list(SAFE_PREFIXES),
        "rules": [
            "irreversible work always needs approval of the exact artefact",
            "an unnamed agent has an unknown blast radius and needs approval",
            "an unpriced plan against a metered tenant needs approval",
            f"an estimate above {COSTLY_UNITS:g} units needs approval",
            "writing outside the reviewed-free paths needs approval",
            "spending money to produce a result needs approval",
        ],
        "note": ("Deny by default: approval is required unless every rule is "
                 "satisfied. The planner may ask for more review than policy "
                 "requires and can never ask for less."),
    }
