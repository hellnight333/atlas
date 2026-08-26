"""An agent may only use the tools its registry entry declares.

The tool contract existed and was consulted only in aggregate — to decide
whether an agent needed the network or a sandbox. Never per step. So an agent
declared with `tools=("filesystem",)` could run any command at all, and the
isolation derived from its declaration would be wrong about the work it was
actually doing.

That is the same shape as an agent substitution: the blast radius somebody
approved and the one that runs diverge, quietly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas_kernel.fabric import tools
from atlas_kernel.mission import adapter


def step(tool: str, *command: str) -> adapter.Step:
    return adapter.Step(command=list(command) or ["true"],
                        proves=f"uses {tool}", tool=tool)


# ------------------------------------------------------------ what it allows

def test_a_step_defaults_to_the_shell_tool():
    """Every step in this codebase was a shell command before `tool` existed."""
    assert adapter.Step(command=["true"], proves="x").tool == "shell"


def test_the_self_check_steps_use_only_what_self_check_declares():
    """If this fails, the nightly canary stops running and says why."""
    fitted = adapter.Adapter.for_id("self-check")
    assert fitted.undeclared_tools(adapter.SELF_CHECK_STEPS) == ()


def test_a_declared_tool_is_allowed():
    fitted = adapter.Adapter.for_id("self-check")
    assert fitted.undeclared_tools([step("filesystem"), step("shell")]) == ()


# ----------------------------------------------------------- what it refuses

def test_a_tool_the_agent_does_not_declare_is_refused(tmp_path):
    fitted = adapter.Adapter.for_id("self-check")
    reaching_out = [step("http-fetch", "curl", "http://example.invalid")]

    assert fitted.undeclared_tools(reaching_out) == ("http-fetch",)
    with pytest.raises(adapter.NotRunnable, match="http-fetch"):
        fitted.run(reaching_out, workspace=tmp_path)


def test_the_refusal_names_what_the_agent_may_use(tmp_path):
    fitted = adapter.Adapter.for_id("self-check")
    with pytest.raises(adapter.NotRunnable) as refused:
        fitted.run([step("smtp")], workspace=tmp_path)
    assert "filesystem" in str(refused.value)
    assert "shell" in str(refused.value)


def test_a_tool_nobody_declared_anywhere_is_refused_too(tmp_path):
    """A typo in a step is not permission."""
    fitted = adapter.Adapter.for_id("self-check")
    assert fitted.undeclared_tools([step("shel")]) == ("shel",)


def test_one_bad_step_refuses_the_whole_sequence(tmp_path):
    """A sequence half-executed and then refused has already changed the
    workspace, and the refusal arrives too late to mean anything."""
    fitted = adapter.Adapter.for_id("self-check")
    marker = tmp_path / "written-anyway.txt"
    mixed = [
        adapter.Step(command=["sh", "-c", f"touch {marker}"],
                     proves="writes first", tool="shell"),
        step("smtp", "true"),
    ]
    with pytest.raises(adapter.NotRunnable):
        fitted.run(mixed, workspace=tmp_path)
    assert not marker.exists(), "a step ran before the sequence was refused"


# ------------------------------------------------- the contract it consumes

def test_every_tool_a_declared_agent_names_actually_exists():
    """A registry entry naming a tool nobody declared would make every step
    using it unrunnable, and the first anybody heard of it would be a refusal
    at dispatch."""
    from atlas_kernel.fabric.agents import AGENTS
    known = {tool.id for tool in tools.TOOLS}
    for agent in AGENTS:
        missing = set(agent.tools) - known
        assert not missing, f"{agent.id} names undeclared tool(s): {missing}"


def test_isolation_still_comes_from_the_declaration_not_from_the_steps():
    """The declaration is what policy and approval were shown. Deriving
    isolation from the steps instead would let a step widen its own
    containment."""
    fitted = adapter.Adapter.for_id("self-check")
    assert not tools.needs_network(fitted.agent)
    isolation = fitted.isolation_for(Path("/tmp"))
    assert not isolation.network
