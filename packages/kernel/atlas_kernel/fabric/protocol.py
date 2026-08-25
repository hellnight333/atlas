"""How agents ask each other for things, and why it cannot run away.

Two agents that can talk can talk forever. The planner asks the researcher, the
researcher asks the planner to clarify, and by morning there is a five-figure
bill and no work done. Every safeguard here exists for that, and each is a rule
rather than a warning in a prompt — a model asked politely not to loop will loop.

## An agent addresses a *capability*, never an agent

`Request(needs=Capability.RESEARCH)`, not `Request(to="researcher")`. Routing is
the exchange's job, resolved through the one registry.

This is what keeps "agents cannot recruit agents" true while still letting them
collaborate. An agent that could name its correspondent could build a private
chain outside the registry — a set of working relationships nobody declared,
nobody can enumerate, and no policy covers. Addressing a capability means every
edge in the graph is one the registry already knows about.

## The cap escalates; it does not truncate

At the hop limit the conversation goes to a person with the whole chain
attached. Silently returning the last message would hand the caller a
half-finished answer that reads like a finished one — and the loop, being
invisible, would run again tomorrow.

## A refusal is not a failure

`REFUSED` means a rule said no and names which. `FAILED` means something broke.
Collapsing them produces a retry loop against a limit that will refuse it every
time.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from ..opportunity.tenancy import TenantId, owns
from ..opportunity.tenancy import require as _require_tenant
from .agents import Capability, Registry


class Kind(StrEnum):
    REQUEST = "request"
    RESPONSE = "response"
    #: A rule said no, and says which. Distinct from FAILED, because a caller
    #: that cannot tell them apart retries against a limit that will refuse it
    #: every time.
    REFUSED = "refused"
    FAILED = "failed"
    #: Handed to a person, with the chain attached.
    ESCALATED = "escalated"


class Limits(BaseModel):
    """What stops a conversation running away.

    Small on purpose. A limit generous enough never to be hit is not a limit,
    and the first time it matters is the night nobody is watching.
    """

    model_config = ConfigDict(frozen=True)

    #: How far a chain of requests may go. A asks B asks C is three hops.
    max_hops: int = Field(default=4, ge=1, le=32)
    #: Total messages, including responses. Catches two agents ping-ponging
    #: within the hop limit by re-asking the same thing.
    max_messages: int = Field(default=24, ge=2, le=256)
    #: Units this whole exchange may consume. `None` is "no allowance
    #: configured", never "unlimited" — see `spend()`.
    budget_units: float | None = None


DEFAULT_LIMITS = Limits()


class Refused(Exception):
    """A rule declined the message. The message never happened."""


class Message(BaseModel):
    """One thing an agent said, and what it is an answer to."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(default_factory=lambda: f"msg-{uuid4().hex[:12]}")
    conversation_id: str
    tenant_id: str
    kind: Kind
    #: Which agent said it. `""` when a person or the scheduler opened the
    #: conversation, which is the only way one starts.
    sender: str = ""
    #: The agent it was routed to. Resolved from `needs`, never chosen by the
    #: sender.
    recipient: str = ""
    #: What the sender needed. Set on a REQUEST; empty on everything else.
    needs: Capability | None = None
    subject: str = ""
    body: str = ""
    #: The id of the request this answers. Absent on an opening request.
    in_reply_to: str = ""
    hop: int = 0
    #: What this message's work cost, when the provider said. `None` is UNKNOWN.
    units: float | None = None
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def summary(self) -> dict:
        return {"id": self.id, "conversation_id": self.conversation_id,
                "kind": self.kind.value, "sender": self.sender,
                "recipient": self.recipient,
                "needs": self.needs.value if self.needs else "",
                "subject": self.subject, "body": self.body,
                "in_reply_to": self.in_reply_to, "hop": self.hop,
                "units": self.units, "at": self.at.isoformat()}


class Conversation(BaseModel):
    """A chain of requests, and everything that bounds it.

    Folded from its messages rather than tracking counters separately. A counter
    beside the list is a second answer to "how many hops", and the two disagree
    the first time a message is dropped.
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: f"conv-{uuid4().hex[:12]}")
    tenant_id: str
    #: The mission this serves. A conversation with no mission is an agent
    #: talking for its own sake, which is the thing there is no budget for.
    mission_id: str
    opened_by: str = "operator"
    limits: Limits = DEFAULT_LIMITS
    messages: tuple[Message, ...] = ()
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def hops(self) -> int:
        return max((m.hop for m in self.messages), default=0)

    @property
    def spent(self) -> float | None:
        """Summed over the messages that reported a cost.

        `None` when none did — not zero, for the same reason a missing
        measurement is not zero anywhere else in this system.
        """
        known = [m.units for m in self.messages if m.units is not None]
        return sum(known) if known else None

    @property
    def escalated(self) -> bool:
        return any(m.kind is Kind.ESCALATED for m in self.messages)

    @property
    def path(self) -> tuple[str, ...]:
        """Who has been asked, in order."""
        return tuple(m.recipient for m in self.messages
                     if m.kind is Kind.REQUEST and m.recipient)

    @property
    def pending(self) -> tuple[str, ...]:
        """Agents asked something that nothing has answered yet.

        The cycle detector reads this rather than `path`: an agent that already
        answered can be asked again, and an agent still holding the question
        cannot.
        """
        answered = {m.in_reply_to for m in self.messages
                    if m.kind is not Kind.REQUEST and m.in_reply_to}
        return tuple(m.recipient for m in self.messages
                     if m.kind is Kind.REQUEST and m.id not in answered
                     and m.recipient)

    def summary(self) -> dict:
        return {"conversation_id": self.id, "tenant_id": self.tenant_id,
                "mission_id": self.mission_id, "opened_by": self.opened_by,
                "hops": self.hops, "max_hops": self.limits.max_hops,
                "messages": len(self.messages),
                "max_messages": self.limits.max_messages,
                "spent": self.spent, "budget_units": self.limits.budget_units,
                "escalated": self.escalated, "path": list(self.path),
                "pending": list(self.pending),
                "at": self.at.isoformat()}


class Exchange(BaseModel):
    """Routes requests and enforces the limits. Holds nothing.

    Every method returns a new `Conversation`. Nothing is mutated and nothing is
    stored here, so two callers cannot disagree about the state of an exchange —
    and a conversation can be folded from durable events like everything else.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    registry: Registry = Registry()

    # -- opening ----------------------------------------------------------

    def open(self, *, tenant: TenantId | None, mission_id: str,
             opened_by: str = "operator", limits: Limits = DEFAULT_LIMITS
             ) -> Conversation:
        """Start a conversation. Only a person or the scheduler may.

        An agent cannot open one, which is the difference between "agents
        collaborate on the work they were given" and "agents start projects".
        """
        tenant = _require_tenant(tenant, method="protocol.open")
        if not mission_id.strip():
            raise Refused("a conversation must serve a mission; one that serves "
                          "nothing is an agent talking at its own expense")
        return Conversation(tenant_id=str(tenant), mission_id=mission_id.strip(),
                            opened_by=opened_by, limits=limits)

    # -- the one rule that matters ----------------------------------------

    def request(self, conversation: Conversation, *, needs: Capability,
                subject: str, body: str = "", sender: str = "",
                in_reply_to: str = "", tenant: TenantId | None
                ) -> Conversation:
        """Ask for a capability. The exchange decides who answers.

        The sender never names the recipient. Routing through the registry is
        what keeps every edge in the graph one somebody declared.
        """
        tenant = _require_tenant(tenant, method="protocol.request")
        self._same_tenant(conversation, tenant)
        if conversation.escalated:
            raise Refused("this conversation is with a person; nothing more is "
                          "sent until they answer")

        hop = conversation.hops + 1
        # Limits first, and each names itself. "Refused" without which rule is a
        # dead end for whoever has to decide what to do about it.
        if hop > conversation.limits.max_hops:
            return self._escalate(
                conversation,
                why=(f"reached {conversation.limits.max_hops} hops without an "
                     f"answer. Last asked for {needs.value}: {subject}"))
        if len(conversation.messages) + 1 > conversation.limits.max_messages:
            return self._escalate(
                conversation,
                why=(f"reached {conversation.limits.max_messages} messages "
                     "without an answer, within the hop limit — which is what "
                     "two agents re-asking each other the same thing looks "
                     "like"))

        candidates = self.registry.capable_of(needs)
        if not candidates:
            return self._refuse(
                conversation, hop=hop, sender=sender, subject=subject,
                why=(f"nothing ready can do {needs.value}. It is in the "
                     "registry but not runnable, so promising it would fail "
                     "after the caller was told it was happening"))

        # First ready agent in registry order. Deterministic, and deliberately
        # not clever: routing by cost, load or placement is a real decision that
        # belongs beside the scheduler's, not hidden in a message layer. Stated
        # as a gap rather than approximated here.
        recipient = candidates[0].id
        # A request routed back to an agent that is *still waiting for an
        # answer* is a cycle: A asked B, and B is now asking A. Caught here
        # rather than left to the hop cap because "planner is already waiting on
        # you" is something a person can act on, where "reached 4 hops" is not.
        #
        # Deliberately not "has been asked before". A second question to the
        # same specialist, after the first was answered, is ordinary work.
        if recipient in self._awaiting(conversation) or recipient == sender:
            return self._escalate(
                conversation,
                why=(f"{recipient} is already waiting for an answer in this "
                     "conversation, so this request closes a cycle"))

        message = Message(
            conversation_id=conversation.id, tenant_id=conversation.tenant_id,
            kind=Kind.REQUEST, sender=sender, recipient=recipient, needs=needs,
            subject=subject, body=body, in_reply_to=in_reply_to, hop=hop)
        return self._append(conversation, message)

    def respond(self, conversation: Conversation, *, to: str, body: str,
                sender: str = "", units: float | None = None,
                tenant: TenantId | None) -> Conversation:
        """Answer a request. Does not advance the hop count.

        An answer is not a new question. Counting it would halve every limit and
        make the numbers in `Limits` mean something other than what they say.
        """
        tenant = _require_tenant(tenant, method="protocol.respond")
        self._same_tenant(conversation, tenant)
        asked = self._find(conversation, to)
        if asked is None:
            raise Refused("a response must answer a request in this "
                          "conversation; an uncorrelated answer cannot be "
                          "matched to what it is an answer to")
        if any(m.in_reply_to == to and m.kind is not Kind.REQUEST
               for m in conversation.messages):
            raise Refused(f"{to} has already been answered")

        spent = self._overspend(conversation, units)
        message = Message(
            conversation_id=conversation.id, tenant_id=conversation.tenant_id,
            kind=Kind.RESPONSE, sender=sender or asked.recipient,
            recipient=asked.sender, body=body, in_reply_to=to,
            hop=asked.hop, units=units)
        after = self._append(conversation, message)
        if spent:
            return self._escalate(after, why=spent)
        return after

    def fail(self, conversation: Conversation, *, to: str, why: str,
             sender: str = "", tenant: TenantId | None) -> Conversation:
        """Something broke. Distinct from a refusal, because it may be retried."""
        tenant = _require_tenant(tenant, method="protocol.fail")
        self._same_tenant(conversation, tenant)
        asked = self._find(conversation, to)
        if asked is None:
            raise Refused("a failure must answer a request in this conversation")
        return self._append(conversation, Message(
            conversation_id=conversation.id, tenant_id=conversation.tenant_id,
            kind=Kind.FAILED, sender=sender or asked.recipient,
            recipient=asked.sender, body=why, in_reply_to=to, hop=asked.hop))

    def escalate(self, conversation: Conversation, *, why: str,
                 tenant: TenantId | None) -> Conversation:
        """Hand it to a person deliberately, before a limit forces it."""
        tenant = _require_tenant(tenant, method="protocol.escalate")
        self._same_tenant(conversation, tenant)
        return self._escalate(conversation, why=why)

    # -- internals --------------------------------------------------------

    def _same_tenant(self, conversation: Conversation, tenant: TenantId) -> None:
        if not owns(conversation.tenant_id, tenant):
            raise Refused("that conversation belongs to a different tenant")

    def _awaiting(self, conversation: Conversation) -> frozenset[str]:
        return frozenset(conversation.pending)

    def _find(self, conversation: Conversation, message_id: str) -> Message | None:
        for message in conversation.messages:
            if message.id == message_id and message.kind is Kind.REQUEST:
                return message
        return None

    def _overspend(self, conversation: Conversation, units: float | None) -> str:
        """Whether this reply takes the conversation past its allowance.

        Checked on the way *in*, so the message that broke the budget is
        recorded before the escalation — a chain that ends without its last
        message does not explain what it cost.
        """
        allowance = conversation.limits.budget_units
        if allowance is None:
            return ""
        already = conversation.spent or 0.0
        if units is None:
            return (f"a reply arrived with no cost reported and "
                    f"{allowance - already:g} units of allowance left. An "
                    "unmetered call is not a free one, so this needs a person")
        if already + units > allowance:
            return (f"spent {already + units:g} of {allowance:g} units")
        return ""

    def _refuse(self, conversation: Conversation, *, hop: int, sender: str,
                subject: str, why: str) -> Conversation:
        return self._append(conversation, Message(
            conversation_id=conversation.id, tenant_id=conversation.tenant_id,
            kind=Kind.REFUSED, sender="exchange", recipient=sender,
            subject=subject, body=why, hop=hop))

    def _escalate(self, conversation: Conversation, *, why: str) -> Conversation:
        """Append the escalation regardless of the message cap.

        The cap bounds work, not the record of why the work stopped. Refusing
        to write the escalation because the conversation is full would leave a
        chain that ends mid-sentence with no explanation.
        """
        return conversation.model_copy(update={"messages": (
            *conversation.messages,
            Message(conversation_id=conversation.id,
                    tenant_id=conversation.tenant_id, kind=Kind.ESCALATED,
                    sender="exchange", subject="needs a person", body=why,
                    hop=conversation.hops))})

    def _append(self, conversation: Conversation, message: Message
                ) -> Conversation:
        return conversation.model_copy(
            update={"messages": (*conversation.messages, message)})
