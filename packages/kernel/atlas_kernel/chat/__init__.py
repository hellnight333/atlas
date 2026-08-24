"""The middle of the pipeline: a sentence becomes an approved mission.

Both ends existed and this did not. A person could not say what they wanted, and
a mission could not say where it came from.

The shape is fixed by one rule: **chat never executes anything.** A message
produces a conversation turn; a conversation produces a plan; a plan is shown;
a person approves it; approval produces a mission; a worker somewhere else picks
the mission up. Nothing in this package runs code, touches a repository or calls
a provider on a schedule of its own.

That is not caution for its own sake. A chat surface that executed what it
understood would make natural language the authorisation boundary — and natural
language is attacker-controlled the moment a plan quotes a customer's website,
an email, or a research result. The plan being inspectable *before* anything
runs is what keeps a prompt injection a proposal rather than an action.
"""

from .models import (
    Conversation,
    ConversationStatus,
    Message,
    Role,
    Turn,
)
from .service import (
    ConversationStore,
    PlanRejected,
    approve,
    fold,
    history,
    plan_for,
    send,
    start,
)

__all__ = ["Conversation", "ConversationStatus", "ConversationStore", "Message",
           "PlanRejected", "Role", "Turn", "approve", "fold", "history",
           "plan_for", "send", "start"]
