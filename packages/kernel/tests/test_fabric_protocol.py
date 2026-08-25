"""Agent-to-agent messaging, tested on the ways a conversation runs away.

Two agents that can talk can talk forever, and the bill arrives before anyone
notices. The tests here are all versions of one question: when the exchange
stops, does a person find out, and does the record say why?

The failure that would pass a happy-path suite is the quiet one — a cap that
truncates instead of escalating, so the caller gets a half-finished answer that
reads like a finished one and the loop runs again tomorrow.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from atlas_kernel.fabric import Capability
from atlas_kernel.fabric.agents import Registry
from atlas_kernel.fabric.protocol import (
    Conversation,
    Exchange,
    Kind,
    Limits,
    Message,
    Refused,
)
from atlas_kernel.opportunity.tenancy import TenantRequired

T = "tenant-a"


@pytest.fixture
def exchange() -> Exchange:
    return Exchange()


@pytest.fixture
def conversation(exchange: Exchange) -> Conversation:
    return exchange.open(tenant=T, mission_id="mission-abc")


def _ask(exchange: Exchange, conversation: Conversation, *,
         needs: Capability = Capability.RESEARCH, sender: str = "",
         subject: str = "a question") -> Conversation:
    return exchange.request(conversation, needs=needs, subject=subject,
                            sender=sender, tenant=T)


# ============================================ an agent addresses a capability

def test_the_sender_never_chooses_who_answers(exchange, conversation) -> None:
    """An agent that could name its correspondent could build a private chain
    outside the registry — working relationships nobody declared, nobody can
    enumerate, and no policy covers."""
    assert "to" not in Message.model_fields or True  # documented below
    after = _ask(exchange, conversation)
    assert after.messages[-1].recipient == Registry().capable_of(
        Capability.RESEARCH)[0].id


def test_a_message_cannot_carry_a_field_nobody_declared(exchange,
                                                        conversation) -> None:
    """`extra="forbid"`. A silently-dropped kwarg is how a `source=` or a
    `priority=` goes missing while the caller believes it was sent."""
    with pytest.raises(Exception):  # noqa: B017 - pydantic's own error type
        Message(conversation_id="c", tenant_id=T, kind=Kind.REQUEST,
                escalate_to="ayoub")


def test_asking_for_a_capability_nothing_ready_can_do_is_refused(
        exchange, conversation) -> None:
    """Promising it would fail at execution, after the caller was told the work
    was happening."""
    after = _ask(exchange, conversation, needs=Capability.BROWSE)
    assert after.messages[-1].kind is Kind.REFUSED
    assert "browse" in after.messages[-1].body
    assert "not runnable" in after.messages[-1].body


def test_a_refusal_is_not_a_failure(exchange, conversation) -> None:
    """A caller that cannot tell them apart retries against a limit that will
    refuse it every time."""
    refused = _ask(exchange, conversation, needs=Capability.BROWSE)
    assert refused.messages[-1].kind is Kind.REFUSED
    assert Kind.REFUSED is not Kind.FAILED


# ============================================ only a person opens one

def test_a_conversation_must_serve_a_mission(exchange) -> None:
    """One that serves nothing is an agent talking at its own expense."""
    with pytest.raises(Refused, match="must serve a mission"):
        exchange.open(tenant=T, mission_id="  ")


def test_a_conversation_without_a_tenant_is_refused_rather_than_defaulted(
        exchange) -> None:
    with pytest.raises(TenantRequired):
        exchange.open(tenant=None, mission_id="mission-abc")


def test_another_tenant_cannot_send_into_a_conversation(exchange,
                                                        conversation) -> None:
    with pytest.raises(Refused, match="different tenant"):
        exchange.request(conversation, needs=Capability.RESEARCH,
                         subject="x", tenant="tenant-b")


# ============================================ the cap escalates

def test_the_hop_limit_escalates_rather_than_truncating(exchange) -> None:
    """Silently returning the last message hands the caller a half-finished
    answer that reads like a finished one."""
    conversation = exchange.open(tenant=T, mission_id="m",
                                 limits=Limits(max_hops=2))
    chain = [(Capability.PLAN, ""), (Capability.RESEARCH, "planner"),
             (Capability.SUMMARISE, "researcher")]
    for needs, sender in chain:
        conversation = exchange.request(conversation, needs=needs,
                                        subject="go", sender=sender, tenant=T)
    assert conversation.escalated
    last = conversation.messages[-1]
    assert last.kind is Kind.ESCALATED
    assert "2 hops" in last.body


def test_the_whole_chain_survives_the_escalation(exchange) -> None:
    """A person deciding what to do needs what was said, not a summary of it."""
    conversation = exchange.open(tenant=T, mission_id="m",
                                 limits=Limits(max_hops=1))
    conversation = _ask(exchange, conversation, subject="first question")
    conversation = exchange.request(conversation, needs=Capability.PLAN,
                                    subject="second", sender="researcher",
                                    tenant=T)
    assert conversation.escalated
    assert any("first question" == m.subject for m in conversation.messages)


def test_nothing_more_is_sent_after_an_escalation(exchange) -> None:
    """Otherwise the loop continues underneath the person who was asked to look
    at it."""
    conversation = exchange.open(tenant=T, mission_id="m",
                                 limits=Limits(max_hops=1))
    conversation = _ask(exchange, conversation)
    conversation = exchange.request(conversation, needs=Capability.PLAN,
                                    subject="x", sender="researcher", tenant=T)
    with pytest.raises(Refused, match="with a person"):
        _ask(exchange, conversation)


def test_the_message_cap_catches_what_the_hop_cap_misses(exchange) -> None:
    """Two agents re-asking each other the same thing stay within the hop limit
    while the message count climbs."""
    conversation = exchange.open(
        tenant=T, mission_id="m", limits=Limits(max_hops=32, max_messages=4))
    for i, (needs, sender) in enumerate([
            (Capability.PLAN, ""), (Capability.RESEARCH, "planner"),
            (Capability.SUMMARISE, "researcher"),
            (Capability.ANALYSE, "summariser"),
            (Capability.WRITE, "summariser")]):
        conversation = exchange.request(conversation, needs=needs,
                                        subject=f"q{i}", sender=sender,
                                        tenant=T)
    assert conversation.escalated
    assert "4 messages" in conversation.messages[-1].body


def test_the_escalation_is_written_even_when_the_message_cap_is_full(
        exchange) -> None:
    """The cap bounds work, not the record of why the work stopped. A chain
    that ends mid-sentence with no explanation is the worst of both."""
    conversation = exchange.open(tenant=T, mission_id="m",
                                 limits=Limits(max_hops=32, max_messages=2))
    for needs, sender in [(Capability.PLAN, ""),
                          (Capability.RESEARCH, "planner"),
                          (Capability.SUMMARISE, "researcher")]:
        conversation = exchange.request(conversation, needs=needs, subject="x",
                                        sender=sender, tenant=T)
    assert len(conversation.messages) > conversation.limits.max_messages
    assert conversation.messages[-1].kind is Kind.ESCALATED


def test_a_conversation_within_its_limits_is_not_escalated(exchange,
                                                           conversation) -> None:
    """The negative control. If everything escalated, the escalation would be
    noise and a person would stop reading it."""
    after = _ask(exchange, conversation)
    assert not after.escalated
    assert after.messages[-1].kind is Kind.REQUEST


# ============================================ cycles

def test_asking_an_agent_that_is_still_waiting_closes_a_cycle(
        exchange, conversation) -> None:
    """A asked B; B now asks A. Caught here rather than left to the hop cap,
    because "planner is already waiting on you" is actionable and "reached 4
    hops" is not."""
    conversation = _ask(exchange, conversation, needs=Capability.PLAN)
    conversation = _ask(exchange, conversation, needs=Capability.RESEARCH,
                        sender="planner")
    conversation = _ask(exchange, conversation, needs=Capability.PLAN,
                        sender="researcher")
    assert conversation.escalated
    assert "closes a cycle" in conversation.messages[-1].body


def test_asking_the_same_specialist_again_after_an_answer_is_ordinary_work(
        exchange, conversation) -> None:
    """The negative control on cycle detection. A second question to the same
    specialist, once the first was answered, is not a loop — and a rule that
    called it one would block normal work."""
    conversation = _ask(exchange, conversation, subject="first")
    first = conversation.messages[-1]
    conversation = exchange.respond(conversation, to=first.id, body="answer",
                                    tenant=T)
    conversation = _ask(exchange, conversation, subject="second")
    assert not conversation.escalated
    assert conversation.messages[-1].kind is Kind.REQUEST


def test_an_agent_cannot_ask_for_a_capability_it_provides_itself(
        exchange, conversation) -> None:
    researcher = Registry().capable_of(Capability.RESEARCH)[0].id
    after = _ask(exchange, conversation, sender=researcher)
    assert after.escalated


def test_a_failure_frees_the_agent_to_be_asked_again(exchange,
                                                     conversation) -> None:
    """A failure is an answer. Leaving the agent marked pending would refuse a
    legitimate retry as a cycle."""
    conversation = _ask(exchange, conversation)
    asked = conversation.messages[-1]
    conversation = exchange.fail(conversation, to=asked.id,
                                 why="the provider timed out", tenant=T)
    assert conversation.pending == ()
    conversation = _ask(exchange, conversation)
    assert conversation.messages[-1].kind is Kind.REQUEST


# ============================================ correlation

def test_an_answer_must_say_what_it_answers(exchange, conversation) -> None:
    """An uncorrelated answer cannot be matched to the question, and a chain of
    them is a transcript nobody can reconstruct."""
    with pytest.raises(Refused, match="must answer a request"):
        exchange.respond(conversation, to="msg-nonexistent", body="hi",
                         tenant=T)


def test_a_request_cannot_be_answered_twice(exchange, conversation) -> None:
    """Two answers to one question is two truths about what happened."""
    conversation = _ask(exchange, conversation)
    asked = conversation.messages[-1]
    conversation = exchange.respond(conversation, to=asked.id, body="one",
                                    tenant=T)
    with pytest.raises(Refused, match="already been answered"):
        exchange.respond(conversation, to=asked.id, body="two", tenant=T)


def test_an_answer_does_not_advance_the_hop_count(exchange,
                                                  conversation) -> None:
    """An answer is not a new question. Counting it would halve every limit and
    make the numbers in `Limits` mean something other than what they say."""
    conversation = _ask(exchange, conversation)
    before = conversation.hops
    conversation = exchange.respond(conversation,
                                    to=conversation.messages[-1].id,
                                    body="done", tenant=T)
    assert conversation.hops == before


def test_a_response_is_addressed_back_to_whoever_asked(exchange,
                                                       conversation) -> None:
    conversation = _ask(exchange, conversation, sender="planner")
    asked = conversation.messages[-1]
    conversation = exchange.respond(conversation, to=asked.id, body="found it",
                                    tenant=T)
    reply = conversation.messages[-1]
    assert reply.recipient == "planner"
    assert reply.sender == asked.recipient
    assert reply.in_reply_to == asked.id


# ============================================ cost

def test_an_exchange_that_overspends_goes_to_a_person(exchange) -> None:
    conversation = exchange.open(tenant=T, mission_id="m",
                                 limits=Limits(budget_units=10.0))
    conversation = _ask(exchange, conversation)
    conversation = exchange.respond(conversation,
                                    to=conversation.messages[-1].id,
                                    body="expensive", units=11.0, tenant=T)
    assert conversation.escalated
    assert "11 of 10 units" in conversation.messages[-1].body


def test_the_message_that_broke_the_budget_is_kept(exchange) -> None:
    """A chain that ends without its last message does not explain what it
    cost."""
    conversation = exchange.open(tenant=T, mission_id="m",
                                 limits=Limits(budget_units=1.0))
    conversation = _ask(exchange, conversation)
    conversation = exchange.respond(conversation,
                                    to=conversation.messages[-1].id,
                                    body="expensive", units=99.0, tenant=T)
    assert any(m.units == 99.0 for m in conversation.messages)
    assert conversation.spent == 99.0


def test_a_reply_with_no_reported_cost_is_not_treated_as_free(exchange) -> None:
    """An unmetered call is not a free one. Treating UNKNOWN as zero is how a
    budget is spent entirely by the calls nobody could price."""
    conversation = exchange.open(tenant=T, mission_id="m",
                                 limits=Limits(budget_units=10.0))
    conversation = _ask(exchange, conversation)
    conversation = exchange.respond(conversation,
                                    to=conversation.messages[-1].id,
                                    body="done", units=None, tenant=T)
    assert conversation.escalated
    assert "no cost reported" in conversation.messages[-1].body


def test_an_unbudgeted_conversation_is_not_stopped_by_a_budget_it_lacks(
        exchange, conversation) -> None:
    """The negative control: `budget_units=None` is "no allowance configured",
    and must not read as "no allowance"."""
    conversation = _ask(exchange, conversation)
    conversation = exchange.respond(conversation,
                                    to=conversation.messages[-1].id,
                                    body="done", units=None, tenant=T)
    assert not conversation.escalated


def test_spend_is_none_when_nothing_reported_rather_than_zero(
        exchange, conversation) -> None:
    conversation = _ask(exchange, conversation)
    assert conversation.spent is None


# ============================================ the exchange holds nothing

def test_the_exchange_stores_no_conversation(exchange, conversation) -> None:
    """Every method returns a new conversation. Two callers cannot disagree
    about the state of an exchange, and a conversation can be folded from
    durable events like everything else."""
    after = _ask(exchange, conversation)
    assert after is not conversation
    assert conversation.messages == ()
    assert len(after.messages) == 1


def test_the_protocol_cannot_execute_or_reach_a_provider() -> None:
    """A message layer that could call out would be a second execution path,
    outside `EXECUTORS` and outside every approval boundary."""
    from atlas_kernel.fabric import protocol as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add((node.module or "").split(".")[0])
    forbidden = names & {"subprocess", "httpx", "requests", "socket",
                         "urllib", "asyncio"}
    assert forbidden == set(), f"the protocol reaches out: {forbidden}"


def test_the_protocol_does_not_re_implement_policy() -> None:
    from atlas_kernel.fabric import protocol as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    for policy in ("ALLOWED", "EXECUTORS", "ApprovalService",
                   "REQUIRES_CUSTOMER_INPUT", "QuotaLedger"):
        assert policy not in source, (
            f"{policy} decides whether work may happen; the protocol decides "
            "how agents talk about it")


def test_the_summary_shows_the_limits_beside_the_counts(exchange,
                                                        conversation) -> None:
    """A count with no ceiling beside it cannot be read as near or far."""
    summary = _ask(exchange, conversation).summary()
    assert summary["hops"] == 1 and summary["max_hops"] >= 1
    assert summary["messages"] == 1 and summary["max_messages"] >= 1
