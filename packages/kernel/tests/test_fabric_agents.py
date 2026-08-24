"""The agent registry, tested on the ways a fabric becomes a swarm.

Three properties separate a fabric from a swarm, and none of them is about
capability. An agent must not be a process. An agent must not recruit another
agent. And an agent's *capability* must never be mistaken for its *authority*.

The last is the one that matters most: this module says what an agent could be
asked to do. Whether it may is decided by `EXECUTORS`, `REQUIRES_CUSTOMER_INPUT`,
the approval boundaries and `owns()` — none of which live here, and a test reads
the source to keep it that way.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from atlas_kernel.fabric import (
    AGENTS,
    Agent,
    Backend,
    Blast,
    Capability,
    Placement,
    Registry,
    UnknownAgent,
    capable_of,
)
from atlas_kernel.fabric.agents import APPROVAL_FOR

# ============================================ records, not processes

def test_an_agent_is_a_record_that_cannot_do_anything() -> None:
    """Three hundred records cost nothing. Three hundred processes are
    impossible, which is why the registry holds the first kind."""
    agent = Registry().get("planner")
    assert isinstance(agent, Agent)
    for doing in ("run", "execute", "dispatch", "start", "spawn", "send"):
        assert not hasattr(agent, doing), doing


def test_nothing_in_the_registry_executes_or_dispatches() -> None:
    """Read from the source. A registry that grew a dispatch method would be a
    second scheduler, and the second one is the one nobody tested."""
    from atlas_kernel.fabric import agents as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add((node.module or "").split(".")[0])
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                names.add(node.func.attr)

    forbidden = names & {"subprocess", "Popen", "run", "spawn", "Worker",
                         "dispatch", "claim", "httpx", "requests"}
    assert forbidden == set(), f"the registry reaches for {forbidden}"


def test_an_agent_cannot_name_another_agent() -> None:
    """Agents recruiting agents is an unbounded resource commitment made by a
    language model. There is no field in which to express it."""
    fields = set(Agent.model_fields)
    for recruiting in ("delegates_to", "children", "subagents", "team",
                       "can_spawn", "manages"):
        assert recruiting not in fields, recruiting


# ============================================ capability is not authority

def test_the_registry_decides_nothing_about_permission() -> None:
    """It answers "which agents could be asked". Policy answers "may they"."""
    from atlas_kernel.fabric import agents as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    for policy in ("REQUIRES_CUSTOMER_INPUT", "ApprovalService", "owns(",
                   "QuotaLedger", "ALLOWED"):
        assert policy not in source, (
            f"{policy} is policy; the registry must not re-implement or "
            "shortcut it")


def test_blast_radius_decides_which_approval_applies() -> None:
    """An agent that reads a page and one that sends an email are the same
    shape and completely different risks — and the difference is whether the
    effect can be undone, not how clever the model is."""
    assert APPROVAL_FOR[Blast.REVERSIBLE] == "execution"
    assert APPROVAL_FOR[Blast.COSTLY] == "budget"
    assert APPROVAL_FOR[Blast.IRREVERSIBLE] == "artefact"
    # Every radius has an approval. Adding one without deciding is a failure.
    assert set(APPROVAL_FOR) == set(Blast)


@pytest.mark.parametrize("agent_id", ["correspondent", "merchandiser", "social",
                                      "administrator"])
def test_everything_that_cannot_be_undone_needs_artefact_approval(agent_id
                                                                   ) -> None:
    """An email cannot be unsent, a post cannot be recalled, an order cannot be
    un-created, a deletion cannot be reversed. Each needs approval of the exact
    payload — not of the capability."""
    agent = Registry().get(agent_id)
    assert agent.blast is Blast.IRREVERSIBLE
    assert agent.approval == "artefact"


def test_a_reversible_agent_is_not_burdened_with_artefact_approval() -> None:
    """The negative control. If everything needed artefact approval, approval
    would be noise and people would click through it."""
    assert Registry().get("researcher").approval == "execution"


# ============================================ one registry, not two

def test_model_backed_agents_declare_a_role_rather_than_a_model() -> None:
    """`ModelRegistry` stays the only answer to "what can run". An agent naming
    a model would be a second registry, and it would drift."""
    for agent in AGENTS:
        if agent.backend is Backend.API_MODEL:
            assert agent.role is not None, agent.id
        assert not hasattr(agent, "model"), agent.id


def test_executor_backed_agents_point_at_a_real_offer() -> None:
    """The fabric and `EXECUTORS` must describe one thing. An agent naming an
    offer nothing can perform is exactly the promise `EXECUTORS` exists to
    prevent."""
    from atlas_kernel.execution.capabilities import EXECUTORS

    for agent in AGENTS:
        if agent.backend is Backend.EXECUTOR and agent.offer_id and agent.ready:
            assert agent.offer_id in EXECUTORS, (
                f"{agent.id} claims {agent.offer_id}, which has no executor")


def test_every_offer_with_an_executor_has_an_agent() -> None:
    """The other direction: a capability that ships and has no agent is one the
    fabric cannot route work to."""
    from atlas_kernel.execution.capabilities import EXECUTORS

    claimed = {a.offer_id for a in AGENTS if a.offer_id}
    assert set(EXECUTORS) <= claimed, set(EXECUTORS) - claimed


def test_credentials_are_named_as_the_centre_names_them() -> None:
    """So "what does this key unlock" and "what breaks without it" are the same
    question, answered from one vocabulary."""
    from atlas_kernel.integrations import BY_ID

    for agent in AGENTS:
        for credential in agent.credentials:
            assert credential in BY_ID, f"{agent.id}: {credential!r}"


# ============================================ the gaps are visible

def test_an_unrunnable_agent_is_listed_rather_than_absent() -> None:
    """An absence is invisible. A record saying why is a gap somebody can act
    on."""
    unready = [a for a in AGENTS if not a.ready]
    assert unready, "the fixture must contain a designed-but-unbuilt agent"
    for agent in unready:
        assert agent.why_not_ready, agent.id
        assert any(kind in agent.why_not_ready
                   for kind in ("PENDING_CREDENTIAL", "PENDING_INFRASTRUCTURE")), (
            f"{agent.id} must say which kind of blocker it is — a credential is "
            "solvable by typing and a machine is not")


def test_a_cli_agent_declares_that_it_needs_a_sandbox() -> None:
    """It writes files with its own tool loop. That is a container, not a
    permission."""
    for agent in AGENTS:
        if agent.backend is Backend.CLI_AGENT:
            assert agent.needs_sandbox is True
            assert agent.ready is False, (
                f"{agent.id} is a CLI agent and Qevik has no sandbox; marking "
                "it ready would dispatch a filesystem-writing process into a "
                "worktree and call that isolation")


def test_the_arabic_agent_still_refuses_to_translate() -> None:
    """The fabric must not quietly restate a capability more permissively than
    the thing that implements it."""
    assert "Never translates" in Registry().get("arabic-builder").notes


# ============================================ routing

def test_capable_of_returns_only_agents_that_could_actually_run() -> None:
    """Dispatching to an agent whose backend does not exist produces a failure
    at execution, after a customer was told the work would happen."""
    browsers = capable_of(Capability.BROWSE)
    assert browsers == (), "the browser agent is not ready"
    assert capable_of(Capability.BROWSE, ready_only=False), "but it is listed"


def test_capable_of_finds_several_agents_for_one_capability() -> None:
    """Routing is only interesting when there is a choice."""
    assert len(capable_of(Capability.IMPLEMENT)) >= 2


def test_an_unknown_agent_is_an_error_rather_than_a_default() -> None:
    with pytest.raises(UnknownAgent):
        Registry().get("nobody")


def test_a_deployment_can_hold_a_different_set() -> None:
    """A tenant with no marketplace agents, a developer machine with only the
    deterministic ones. None of this is global state."""
    small = Registry(agents=(Registry().get("researcher"),))
    assert len(small.agents) == 1
    assert small.capable_of(Capability.IMPLEMENT) == ()


def test_a_credential_reports_what_it_unlocks() -> None:
    unlocked = {a.id for a in Registry().needing("smtp")}
    assert "correspondent" in unlocked


def test_the_summary_states_the_rule_it_enforces() -> None:
    """A reader should not have to infer "records, not processes" from the
    absence of a run method."""
    note = Registry().summary()["note"]
    assert "not a running process" in note
    assert "recruit" in note


def test_placement_is_a_requirement_not_a_preference() -> None:
    """A mission needing local execution with no local worker is BLOCKED with a
    reason, not silently queued forever."""
    assert Registry().get("cli-implementer").placement is Placement.LOCAL
    assert Registry().get("browser").placement is Placement.CLOUD
