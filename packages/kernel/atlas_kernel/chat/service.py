"""Conversation → plan → approval → mission.

Four transitions, and the rules that make them safe are all about what *cannot*
happen here.

**Nothing executes.** No subprocess, no repository, no worker. `approve()`
returns a mission and an event; something else picks the mission up. A test
reads this module's source to keep that true, because it is the kind of property
that survives in the docstring long after it stops being in the code.

**A plan is proposed by a model and approved by a person, and the two are
recorded separately.** The plan carries which provider and model wrote it, so an
approval is never mistaken for agreement with Qevik in general — it is agreement
with a specific proposal from a specific model at a specific time.

**A conversation is not a mission.** It references one. Collapsing them would
mean the record of what was asked is mutable by the thing that was asked to do
it.

**The person who approves is the authenticated session.** There is no
`approved_by` argument to pass, because a field for it is a field to lie in.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from ..mission import service as mission_service
from ..mission.models import Mission, MissionStatus, Plan
from ..opportunity.models import BusinessEvent
from ..opportunity.tenancy import TenantId, owns
from ..opportunity.tenancy import require as _require_tenant
from .models import FACTORY, KIND, Conversation, ConversationStatus, Message, Role

log = logging.getLogger(__name__)

#: Long enough to be a real request, short enough to be one message.
MAX_MESSAGE = 8000


class PlanRejected(Exception):
    """The conversation cannot move the way the caller asked."""


class ConversationStore:
    """Turns, appended. A deployment may back this with anything append-only."""

    def __init__(self) -> None:
        self._turns: list = []

    def append(self, event: BusinessEvent) -> None:
        self._turns.append(event)

    def read(self) -> list:
        return list(self._turns)


def _event(conversation: Conversation, *, actor: str, note: str = "") -> BusinessEvent:
    return BusinessEvent(business_id=conversation.business_id or conversation.tenant_id,
                         factory=FACTORY, kind=KIND, actor=actor,
                         detail={**conversation.summary(), "note": note})


def start(*, tenant: TenantId | None, text: str, started_by: str = "",
          business_id: str = "") -> tuple[Conversation, BusinessEvent]:
    """Open a conversation with the first thing somebody said."""
    tenant = _require_tenant(tenant, method="chat.start")
    body = (text or "").strip()
    if not body:
        raise PlanRejected("a conversation starts with something said")
    if len(body) > MAX_MESSAGE:
        raise PlanRejected(f"that message is {len(body)} characters; the limit "
                           f"is {MAX_MESSAGE}")

    conversation = Conversation(
        tenant_id=str(tenant), started_by=started_by, business_id=business_id,
        # The title is the opening line, trimmed. Not model-generated: a title
        # nobody wrote is a title that can drift from what was asked, and this
        # is the string a person scans a list by.
        title=body[:80] + ("…" if len(body) > 80 else ""),
        messages=(Message(role=Role.USER, text=body),))
    return conversation, _event(conversation, actor=started_by or "user",
                                note="started")


def send(conversation: Conversation, *, tenant: TenantId | None, text: str,
         role: Role = Role.USER, provider: str = "", model: str = ""
         ) -> tuple[Conversation, BusinessEvent]:
    """Add one message. Appends; never rewrites what was already said."""
    tenant = _require_tenant(tenant, method="chat.send")
    if not owns(conversation.tenant_id, tenant):
        raise PlanRejected("that conversation belongs to another tenant")
    body = (text or "").strip()
    if not body:
        raise PlanRejected("an empty message says nothing")
    if len(body) > MAX_MESSAGE:
        raise PlanRejected(f"that message is {len(body)} characters; the limit "
                           f"is {MAX_MESSAGE}")
    if conversation.status is ConversationStatus.CLOSED:
        raise PlanRejected("this conversation is closed")

    message = Message(role=role, text=body, provider=provider, model=model)
    updated = conversation.model_copy(update={
        "messages": (*conversation.messages, message),
        "updated_at": datetime.now(UTC)})
    return updated, _event(updated, actor=role.value, note="message")


def plan_for(conversation: Conversation, plan: Plan, *, tenant: TenantId | None,
             provider: str = "", model: str = ""
             ) -> tuple[Conversation, BusinessEvent]:
    """Attach a proposed plan and show it. Nothing runs from this.

    The provider and model that produced the plan are recorded on the
    conversation as an assistant message, so approval is agreement with a
    specific proposal from a specific model rather than with Qevik in general.
    """
    tenant = _require_tenant(tenant, method="chat.plan_for")
    if not owns(conversation.tenant_id, tenant):
        raise PlanRejected("that conversation belongs to another tenant")
    if conversation.status is ConversationStatus.MISSION_CREATED:
        raise PlanRejected(
            f"this conversation already produced mission "
            f"{conversation.mission_id}. Planning again would leave two plans "
            "and no way to say which one was approved.")
    if not plan.steps and not plan.blockers:
        raise PlanRejected(
            "a plan with no steps and no blockers proposes nothing. Say what "
            "is in the way instead — an empty plan reads as agreement.")

    described = Message(role=Role.ASSISTANT, text=_describe(plan),
                        provider=provider, model=model)
    updated = conversation.model_copy(update={
        "plan": plan,
        "messages": (*conversation.messages, described),
        "status": ConversationStatus.PLAN_PROPOSED,
        "updated_at": datetime.now(UTC)})
    return updated, _event(updated, actor=model or "planner", note="plan proposed")


def _describe(plan: Plan) -> str:
    """The plan as a person reads it, not as JSON.

    Blockers first when there are any. A plan whose steps are listed above the
    reason they cannot run reads as a plan that will run.
    """
    lines = []
    if plan.blockers:
        lines.append("This cannot proceed yet:")
        lines += [f"  - [{b.kind}] {b.detail}"
                  + (f" → {b.action}" if b.action else "") for b in plan.blockers]
        if plan.steps:
            lines.append("")
    if plan.steps:
        lines.append(f"Plan: {plan.goal}" if plan.goal else "Plan:")
        for step in sorted(plan.steps, key=lambda s: s.order):
            entry = f"  {step.order}. {step.title}"
            if step.files:
                entry += f"  ({', '.join(step.files)})"
            lines.append(entry)
    if plan.approval_required:
        lines.append("")
        lines.append("Nothing runs until you approve this.")
    return "\n".join(lines)


def approve(conversation: Conversation, *, tenant: TenantId | None,
            approved_by: str) -> tuple[Conversation, Mission, list[BusinessEvent]]:
    """Turn an approved plan into a queued mission.

    Returns the mission and the events; **it does not run anything**. The worker
    is a different process and finds the mission by folding the timeline.

    The mission goes through the ordinary lifecycle — draft → planning →
    awaiting_approval → queued — rather than being constructed already queued.
    A mission that skipped its own transitions would have no history explaining
    how it got there, and the history is what a person reads when it goes wrong.
    """
    tenant = _require_tenant(tenant, method="chat.approve")
    if not owns(conversation.tenant_id, tenant):
        raise PlanRejected("that conversation belongs to another tenant")
    if conversation.status is not ConversationStatus.PLAN_PROPOSED:
        raise PlanRejected(
            f"there is no plan awaiting approval here (status: "
            f"{conversation.status.value}). Approving nothing would create a "
            "mission with no agreed scope.")
    plan = conversation.plan
    if plan is None:                              # pragma: no cover - status guards
        raise PlanRejected("no plan is attached")
    if plan.blockers and not plan.steps:
        raise PlanRejected(
            "this plan is blocked and proposes no steps, so approving it would "
            "queue work that cannot start. Clear the blocker first.")

    events: list[BusinessEvent] = []
    mission, event = mission_service.create(
        tenant=tenant, title=conversation.title,
        description=conversation.last_user_message,
        requested_by=approved_by)
    events.append(event)
    mission, event = mission_service.transition(mission, MissionStatus.PLANNING,
                                                tenant=tenant, actor=approved_by)
    events.append(event)
    mission, event = mission_service.attach_plan(mission, plan, tenant=tenant,
                                                 actor=approved_by)
    events.append(event)
    # Only if policy has not already queued it.
    #
    # `attach_plan` used to route on the planner's own `approval_required`,
    # which was always True for a real plan, so this transition always ran from
    # AWAITING_APPROVAL. Policy decides now, and a cheap reversible plan lands
    # in QUEUED directly — where an unconditional QUEUED → QUEUED is refused by
    # `ALLOWED` and would have failed the approval a person just gave.
    if mission.status is not MissionStatus.QUEUED:
        mission, event = mission_service.transition(
            mission, MissionStatus.QUEUED, tenant=tenant, actor=approved_by,
            note=f"approved in conversation {conversation.id}")
        events.append(event)

    updated = conversation.model_copy(update={
        "status": ConversationStatus.MISSION_CREATED,
        "mission_id": mission.id,
        "messages": (*conversation.messages,
                     Message(role=Role.SYSTEM,
                             text=f"Approved. Mission {mission.id} is queued. "
                                  "It runs in a separate process, so you can "
                                  "close this page.")),
        "updated_at": datetime.now(UTC)})
    events.append(_event(updated, actor=approved_by, note="approved"))
    return updated, mission, events


def reject(conversation: Conversation, *, tenant: TenantId | None,
           rejected_by: str, why: str = "") -> tuple[Conversation, BusinessEvent]:
    """Decline a plan, and keep it.

    The rejected plan stays on the conversation. It is the most useful thing in
    the file when the next one is written, and deleting it would leave a
    conversation that appears to have proposed nothing.
    """
    tenant = _require_tenant(tenant, method="chat.reject")
    if not owns(conversation.tenant_id, tenant):
        raise PlanRejected("that conversation belongs to another tenant")
    if conversation.status is not ConversationStatus.PLAN_PROPOSED:
        raise PlanRejected("there is no plan awaiting a decision here")

    updated = conversation.model_copy(update={
        "status": ConversationStatus.PLAN_REJECTED,
        "messages": (*conversation.messages,
                     Message(role=Role.SYSTEM,
                             text=f"Plan declined{f': {why}' if why else ''}. "
                                  "Nothing was queued.")),
        "updated_at": datetime.now(UTC)})
    return updated, _event(updated, actor=rejected_by, note="rejected")


def fold(events: list, *, tenant: TenantId | None = None) -> list[dict]:
    """TENANT_SCOPED. Every conversation's current state, newest first.

    Latest by `at`, not last in the list — the same rule `mission.fold` learned
    the hard way, and for the same reason: two processes append to one timeline
    and arrival order is not event order.
    """
    tenant = _require_tenant(tenant, method="chat.fold")
    current: dict[str, dict] = {}
    for event in events:
        kind = getattr(event, "kind", None) or event.get("kind")
        if kind != KIND:
            continue
        detail = getattr(event, "detail", None) or event.get("detail") or {}
        if not owns(detail.get("tenant_id"), tenant):
            continue
        conversation_id = detail.get("conversation_id")
        if not conversation_id:
            continue
        seen = current.get(conversation_id)
        if seen is None or detail.get("at", "") >= seen.get("at", ""):
            current[conversation_id] = dict(detail)
    return sorted(current.values(), key=lambda d: d.get("at", ""), reverse=True)


def history(events: list, conversation_id: str, *, tenant: TenantId | None = None
            ) -> list[dict]:
    """Every turn of one conversation, oldest first. Never collapsed."""
    tenant = _require_tenant(tenant, method="chat.history")
    found = []
    for event in events:
        kind = getattr(event, "kind", None) or event.get("kind")
        if kind != KIND:
            continue
        detail = getattr(event, "detail", None) or event.get("detail") or {}
        if detail.get("conversation_id") != conversation_id:
            continue
        if not owns(detail.get("tenant_id"), tenant):
            continue
        found.append(dict(detail))
    return sorted(found, key=lambda d: d.get("at", ""))


def rehydrate(summary: dict, *, tenant: TenantId | None = None) -> Conversation:
    """A folded conversation back into an object, so a surface can act on it."""
    tenant = _require_tenant(tenant, method="chat.rehydrate")
    if not owns(summary.get("tenant_id"), tenant):
        raise PlanRejected("that conversation belongs to another tenant")
    fields = {k: v for k, v in summary.items()
              if k in Conversation.model_fields and k != "id"}
    return Conversation.model_validate(
        {**fields, "id": summary.get("conversation_id", "")})
