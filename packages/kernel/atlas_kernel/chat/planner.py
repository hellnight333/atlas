"""Turning a conversation into a proposed plan.

The whole design rests on what happens when no model is configured, because that
is the state every new installation starts in and the state a demo runs in.

**It returns a plan whose only content is a blocker naming the credential.** Not
a fabricated plan, not a generic three-step template, and not an exception that
reads as a bug. A template plan would be the most damaging possible output here:
it looks like Qevik understood the request, a person approves it, a worker picks
it up, and an agent implements steps nobody derived from anything. The plan would
be wrong in a way that survives review, because it was never produced by
reasoning about the request at all.

So the rule is: **a plan is either produced by a model that saw the request, or
it is a blocker.** There is no third kind.

When a model *is* configured, planning goes through `LLMCodingAgent`, which is
the same agent the worker uses — one agent abstraction, not a second one that
plans differently from the thing that implements.
"""

from __future__ import annotations

import logging

from ..credentials.models import PROVIDER_CREDENTIAL, Role, Selection, chosen_for, registry_for
from ..credentials.service import CredentialService
from ..mission.agents import AgentError, LLMCodingAgent, MalformedResult
from ..mission.models import Blocker, Plan, PlanStep
from ..opportunity.tenancy import TenantId
from ..opportunity.tenancy import require as _require_tenant
from .models import Conversation

log = logging.getLogger(__name__)

#: What a plan carries when no model could be reached. `PENDING_CREDENTIAL` is
#: the class the control plane already groups blockers by, so this appears in
#: the action centre beside every other missing credential rather than as a
#: special case nobody built a screen for.
NO_MODEL = "PENDING_CREDENTIAL"
PLANNING_FAILED = "PENDING_PROVIDER"


class Proposal:
    """A plan and the provenance of it. Never one without the other."""

    __slots__ = ("plan", "provider", "model", "reason")

    def __init__(self, plan: Plan, *, provider: str = "", model: str = "",
                 reason: str = "") -> None:
        self.plan = plan
        self.provider = provider
        self.model = model
        #: How the model was chosen — `selected`, `defaulted`, or why none was.
        self.reason = reason

    @property
    def blocked(self) -> bool:
        return bool(self.plan.blockers) and not self.plan.steps

    def summary(self) -> dict:
        return {"provider": self.provider, "model": self.model,
                "reason": self.reason, "blocked": self.blocked,
                "plan": self.plan.model_dump(mode="json")}


def _blocked(detail: str, action: str, *, kind: str = NO_MODEL,
             reason: str = "") -> Proposal:
    return Proposal(
        Plan(goal="", approval_required=True,
             blockers=(Blocker(kind=kind, detail=detail, action=action),)),
        reason=reason or detail)


def propose(conversation: Conversation, *, tenant: TenantId | None,
            credentials: CredentialService, selection: Selection | None = None,
            context: str = "") -> Proposal:
    """A plan for what the conversation asked, or a blocker saying why not.

    Never both empty, and never a template. The caller can rely on
    `Proposal.blocked` to decide whether to show a plan or an action.
    """
    tenant = _require_tenant(tenant, method="chat.planner.propose")
    request = conversation.last_user_message
    if not request:
        return _blocked("this conversation contains no request to plan for",
                        "Say what you would like Qevik to do.",
                        kind="EMPTY_REQUEST")

    registry = registry_for(credentials, tenant=tenant)
    spec, why = chosen_for(registry, selection or Selection(), Role.PLANNING)
    if spec is None:
        wanted = ", ".join(sorted(set(PROVIDER_CREDENTIAL.values())))
        return _blocked(
            f"No model is available for planning: {why}. Qevik will not "
            "invent a plan without one — a template plan looks like "
            "understanding and is not.",
            f"Add a model credential in the Credential Centre ({wanted}).",
            reason=why)

    registration = next((r for r in registry.models if r.name == spec.id), None)
    if registration is None:                     # pragma: no cover - chosen_for
        return _blocked(f"{spec.id} was chosen but is not registered",
                        "Re-enter the credential for this provider.",
                        kind=PLANNING_FAILED, reason=why)

    agent = LLMCodingAgent(registration.provider, spec)
    try:
        plan = agent.plan(request, context=context)
    except (AgentError, MalformedResult) as failure:
        # The provider was reached and did not produce a usable plan. Distinct
        # from having no provider, and a different action for the person: this
        # one is worth retrying, the other never is.
        log.warning("planning failed on %s: %s", spec.id, failure)
        return _blocked(
            f"{spec.id} did not return a usable plan ({type(failure).__name__}).",
            "Try again, or choose a different planning model.",
            kind=PLANNING_FAILED, reason=str(failure)[:200])
    except Exception as failure:                 # noqa: BLE001 - reported, not swallowed
        log.exception("planner crashed on %s", spec.id)
        return _blocked(
            f"The planning provider failed: {type(failure).__name__}.",
            "Check the provider's status in the Credential Centre.",
            kind=PLANNING_FAILED, reason=type(failure).__name__)

    provider = next((p for p, models in _models_by_provider().items()
                     if spec.id in models), "")
    if not plan.steps and not plan.blockers:
        # A model that answered with nothing actionable. Recorded as a blocker
        # rather than passed through, because `plan_for` would refuse it and an
        # empty plan shown to a person reads as agreement.
        return _blocked(
            f"{spec.id} produced a plan with no steps.",
            "Restate the request more concretely, or try another model.",
            kind=PLANNING_FAILED, reason="empty plan")

    return Proposal(plan, provider=provider, model=spec.id, reason=why)


def _models_by_provider() -> dict[str, tuple[str, ...]]:
    from ..credentials.models import PROVIDER_MODELS

    return PROVIDER_MODELS


def blockers_as_steps(plan: Plan) -> tuple[PlanStep, ...]:
    """A blocked plan's blockers, as the steps a *person* would take.

    Used by the action centre rather than by the worker: these are things only a
    human can do, and returning them as PlanSteps for an agent would queue work
    that cannot start.
    """
    return tuple(
        PlanStep(order=index, title=blocker.action or blocker.detail,
                 why=blocker.detail)
        for index, blocker in enumerate(plan.blockers, start=1))
