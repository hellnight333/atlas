"""The tool table, tested on the drift it exists to prevent.

`Agent.tools` was a tuple of free-form strings. Nothing checked a name existed,
nothing said what it could do, and nothing connected it to the isolation the
agent would run under — two lists kept in step by hand until the day they were
not. Writing the tools down found two real errors, and the tests below are the
ones that would have found them earlier.
"""

from __future__ import annotations

import pytest

from atlas_kernel.fabric import AGENTS, Blast, Registry
from atlas_kernel.fabric.agents import Backend
from atlas_kernel.fabric.tools import (
    BY_ID,
    SEVERITY,
    TOOLS,
    UnknownTool,
    describe,
    for_agent,
    get,
    needs_network,
    understates,
    unmet,
    worst,
)

# ============================================ nothing dangles

def test_every_tool_an_agent_names_exists() -> None:
    """A dangling name fails the build rather than being discovered at
    dispatch. Hand-synced lists drift silently; this is the derivation."""
    for agent in AGENTS:
        for name in agent.tools:
            assert name in BY_ID, (
                f"{agent.id} names {name!r}, which no tool record defines")


def test_an_unknown_tool_is_an_error_rather_than_a_default() -> None:
    with pytest.raises(UnknownTool, match="blast radius is unknown"):
        get("a-tool-nobody-wrote")


def test_every_tool_is_reachable_by_some_agent() -> None:
    """The other direction: a tool nothing can use is a record that will drift
    out of date without anybody noticing."""
    reached = {name for agent in AGENTS for name in agent.tools}
    assert {t.id for t in TOOLS} == reached, (
        f"unused: {sorted({t.id for t in TOOLS} - reached)}")


def test_tool_ids_are_unique() -> None:
    assert len(BY_ID) == len(TOOLS)


# ============================================ blast belongs to the tool

def test_no_agent_understates_what_its_tools_can_do() -> None:
    """An agent that says REVERSIBLE while holding a tool that sends email
    would be routed to execution approval instead of artefact approval — the
    wrong boundary, chosen by a typo."""
    guilty = [a.id for a in AGENTS if understates(a)]
    assert guilty == [], guilty


def test_a_declared_blast_matches_the_worst_tool_exactly() -> None:
    """Stricter than "does not understate", so an agent that quietly stops
    matching its tools is visible.

    An agent is *allowed* to be more cautious than its tools — but the reason
    has to be written down here, in this list, rather than sitting unexplained
    in a record. The list is empty today.
    """
    deliberately_cautious: dict[str, str] = {}
    for agent in AGENTS:
        if agent.id in deliberately_cautious:
            continue
        assert agent.blast is worst(for_agent(agent)), (
            f"{agent.id} declares {agent.blast.value} while its tools are "
            f"{worst(for_agent(agent)).value}. If that is deliberate, say why "
            "in `deliberately_cautious`")


def test_the_browser_is_irreversible() -> None:
    """It said REVERSIBLE. A browser that can navigate can also submit a form,
    buy something or send a message, and nothing about "browse" is reversible
    once a button is clicked."""
    assert Registry().get("browser").blast is Blast.IRREVERSIBLE
    assert get("browser").blast is Blast.IRREVERSIBLE
    assert Registry().get("browser").approval == "artefact"


def test_a_shell_in_a_worktree_and_a_shell_on_a_host_are_different_tools(
        ) -> None:
    """One string carried both blast radii: `cli-implementer` called its shell
    reversible and `administrator` called its shell irreversible, and both were
    right about their own case."""
    assert get("shell").blast is Blast.REVERSIBLE
    assert get("host-shell").blast is Blast.IRREVERSIBLE
    assert "host-shell" in Registry().get("administrator").tools
    assert "host-shell" not in Registry().get("cli-implementer").tools


def test_worst_of_nothing_is_reversible() -> None:
    """An agent with no tools cannot do damage with one."""
    assert worst(()) is Blast.REVERSIBLE
    assert for_agent(Registry().get("planner")) == ()


def test_severity_covers_every_blast() -> None:
    """A blast radius added without a severity would silently compare as
    equal-to-nothing and never trip the understating check."""
    assert set(SEVERITY) == set(Blast)


# ============================================ a sandbox does not contain an email

def test_only_local_effects_are_marked_contained() -> None:
    """Calling a sent email "contained" because the process was in a namespace
    would be the most dangerous kind of wrong: the effect is already
    elsewhere."""
    for tool in TOOLS:
        if tool.contained_by_sandbox:
            assert tool.network is False, tool.id
            assert tool.blast is Blast.REVERSIBLE, tool.id


def test_something_is_contained_and_something_is_not() -> None:
    """The negative control on the rule above, in both directions."""
    assert any(t.contained_by_sandbox for t in TOOLS)
    assert any(not t.contained_by_sandbox for t in TOOLS)


# ============================================ the network flag is enforced

def test_an_agent_with_only_local_tools_does_not_get_the_network() -> None:
    """`needs_network` feeds `sandbox.Isolation`, so this is enforced by the
    kernel rather than requested in a prompt."""
    assert needs_network(Registry().get("cli-implementer")) is False
    assert needs_network(Registry().get("website-builder")) is False


def test_an_agent_that_has_to_reach_out_says_so() -> None:
    assert needs_network(Registry().get("researcher")) is True
    assert needs_network(Registry().get("correspondent")) is True


def test_the_isolation_a_local_agent_would_run_under_has_no_network(tmp_path
                                                                    ) -> None:
    """End to end: the flag actually reaches the sandbox argument."""
    from atlas_kernel.fabric.sandbox import Isolation

    agent = Registry().get("cli-implementer")
    isolation = Isolation(workspace=tmp_path, network=needs_network(agent))
    assert isolation.network is False


# ============================================ credentials stay in step

def test_no_agent_holds_a_tool_whose_credential_it_never_lists() -> None:
    """An agent holding a tool whose key it never lists fails at the provider,
    after the customer was told the work was happening."""
    for agent in AGENTS:
        assert unmet(agent) == (), f"{agent.id} is missing {unmet(agent)}"


def test_tool_credentials_are_named_as_the_centre_names_them() -> None:
    """So "what does this key unlock" and "what breaks without it" are one
    question with one vocabulary."""
    from atlas_kernel.integrations import BY_ID as INTEGRATIONS

    for tool in TOOLS:
        for credential in tool.credentials:
            assert credential in INTEGRATIONS, f"{tool.id}: {credential!r}"


def test_the_check_would_notice_a_missing_credential() -> None:
    """The negative control. Without it, `unmet() == ()` everywhere could mean
    the function returns nothing at all."""
    stripped = Registry().get("correspondent").model_copy(
        update={"credentials": ()})
    assert unmet(stripped) == ("smtp",)


# ============================================ the record stays readable

def test_every_tool_says_what_it_does() -> None:
    for tool in TOOLS:
        assert tool.does.strip(), tool.id
        assert not tool.does.startswith(tool.id), (
            f"{tool.id} restates its own name instead of saying what it does")


def test_a_tool_cannot_carry_a_field_nobody_declared() -> None:
    """`extra="forbid"`. A silently-dropped kwarg is how a `blast=` goes
    missing while its author believes it was set."""
    from atlas_kernel.fabric.tools import Tool

    with pytest.raises(Exception):  # noqa: B017 - pydantic's own error type
        Tool(id="x", does="something", danger="high")


def test_the_description_states_the_rule_it_enforces() -> None:
    stated = describe()
    assert "Blast radius belongs to the tool" in stated["note"]
    assert set(stated["irreversible"]) == {
        t.id for t in TOOLS if t.blast is Blast.IRREVERSIBLE}


def test_the_tools_a_cli_agent_holds_are_all_containable() -> None:
    """A CLI agent runs in a sandbox. If one of its tools could not be
    contained, the sandbox would be reassurance rather than protection."""
    for agent in AGENTS:
        if agent.backend is Backend.CLI_AGENT and agent.id != "browser":
            for tool in for_agent(agent):
                if not tool.contained_by_sandbox:
                    assert agent.blast is Blast.IRREVERSIBLE, (
                        f"{agent.id} holds {tool.id}, which a sandbox does not "
                        f"contain, while declaring {agent.blast.value}")
