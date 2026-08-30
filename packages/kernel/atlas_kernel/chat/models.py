"""What a conversation is, and what it may become.

Event-sourced like everything else: a conversation is folded from its turns, not
stored as a mutable row. That matters more here than elsewhere, because the
conversation is the provenance of a mission — the answer to "why did an agent
change this file" is a sentence somebody typed, and a record that can be edited
after the fact is not provenance.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from ..mission.models import Plan

FACTORY = "chat"
KIND = "chat_turn"


class Role(StrEnum):
    """Who is speaking. `SYSTEM` is Qevik explaining itself, never a persona."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ConversationStatus(StrEnum):
    OPEN = "open"
    #: A plan has been produced and is waiting for a person to look at it.
    PLAN_PROPOSED = "plan_proposed"
    #: A plan was approved and became a mission. The conversation stays
    #: readable; it does not become the mission.
    MISSION_CREATED = "mission_created"
    #: The person declined the plan. Recorded, because a rejected plan is the
    #: most useful thing in the file when the next one is written.
    PLAN_REJECTED = "plan_rejected"
    CLOSED = "closed"


class Message(BaseModel):
    """One thing said, and by whom."""

    model_config = ConfigDict(frozen=True)

    role: Role
    text: str
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    #: Set when a model produced this. Empty for anything a person typed, so a
    #: reader can always tell which is which — a transcript that blurs them is
    #: a transcript in which nobody can find what they actually asked for.
    provider: str = ""
    model: str = ""

    def summary(self) -> dict:
        return {"role": self.role.value, "text": self.text,
                "at": self.at.isoformat(), "provider": self.provider,
                "model": self.model}


class Turn(BaseModel):
    """A conversation's state after one exchange. Appended, never revised."""

    model_config = ConfigDict(frozen=True)

    conversation_id: str
    tenant_id: str
    messages: tuple[Message, ...] = ()
    status: ConversationStatus = ConversationStatus.OPEN
    title: str = ""
    started_by: str = ""
    #: The proposed plan, once one exists. Carried on the conversation rather
    #: than only on the mission, so a plan that was never approved is still on
    #: the record.
    plan: Plan | None = None
    #: Set once approval produced one. A conversation references a mission; it
    #: never becomes one.
    mission_id: str = ""
    #: Which business this is about, when it is about one.
    business_id: str = ""
    #: The agent that produced this plan, and therefore the one that will carry
    #: it out. Recorded beside the provider and model for the same reason: an
    #: approval is agreement with a specific proposal, and "who runs it" is part
    #: of that. Empty until a plan is proposed.
    agent_id: str = ""
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def summary(self) -> dict:
        return {
            "conversation_id": self.conversation_id,
            "tenant_id": self.tenant_id,
            "messages": [m.summary() for m in self.messages],
            "status": self.status.value, "title": self.title,
            "started_by": self.started_by,
            "plan": self.plan.model_dump(mode="json") if self.plan else None,
            "mission_id": self.mission_id, "business_id": self.business_id,
            "agent_id": self.agent_id,
            "at": self.at.isoformat(),
        }


class Conversation(BaseModel):
    """The folded state. Built from turns; never stored."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: f"chat-{uuid4().hex[:12]}")
    tenant_id: str
    title: str = ""
    started_by: str = ""
    messages: tuple[Message, ...] = ()
    status: ConversationStatus = ConversationStatus.OPEN
    plan: Plan | None = None
    mission_id: str = ""
    business_id: str = ""
    #: See `Turn.agent_id`.
    agent_id: str = ""
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def awaiting_approval(self) -> bool:
        return self.status is ConversationStatus.PLAN_PROPOSED

    @property
    def last_user_message(self) -> str:
        for message in reversed(self.messages):
            if message.role is Role.USER:
                return message.text
        return ""

    def turn(self) -> Turn:
        return Turn(conversation_id=self.id, tenant_id=self.tenant_id,
                    messages=self.messages, status=self.status,
                    title=self.title, started_by=self.started_by,
                    plan=self.plan, mission_id=self.mission_id,
                    business_id=self.business_id, agent_id=self.agent_id,
                    at=self.updated_at)

    def summary(self) -> dict:
        return {**self.turn().summary(),
                "started_at": self.started_at.isoformat(),
                "updated_at": self.updated_at.isoformat(),
                "awaiting_approval": self.awaiting_approval}
