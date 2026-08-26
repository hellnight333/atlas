"""Recipes: named, declared sequences of tool steps.

`CLAUDE.md` is unambiguous about why this is a primitive: an LLM must never
freestyle the steps, because it will hallucinate them forever. The model's only
job is choosing a recipe **by name** — the same shape as `mission/origins.py`,
and these tests are mostly about the ways a name could become more than a name.
"""

from __future__ import annotations

import pytest

from atlas_kernel.fabric import recipes
from atlas_kernel.fabric.agents import AGENTS, Capability, Registry
from atlas_kernel.fabric.tools import TOOLS

# --------------------------------------------------------------- declarations

def test_every_declared_recipe_is_runnable_by_its_agent():
    """Validated at import, so this is a second opinion rather than the only
    one — but a recipe that would be refused at dispatch must never ship."""
    for recipe in recipes.RECIPES:
        recipes.validate(recipe)


def test_every_recipe_names_a_declared_agent():
    known = {agent.id for agent in AGENTS}
    for recipe in recipes.RECIPES:
        assert recipe.agent_id in known, recipe.id


def test_every_recipe_step_names_a_declared_tool():
    known = {tool.id for tool in TOOLS}
    for recipe in recipes.RECIPES:
        for step in recipe.steps:
            assert step.tool in known, f"{recipe.id}: {step.tool}"


def test_a_recipe_may_not_use_a_tool_its_agent_lacks():
    """The check that makes a recipe safe to route work to."""
    reaching = recipes.Recipe(
        id="overreach", does="fetch something", agent_id="self-check",
        capability=Capability.VERIFY,
        steps=(recipes.Step(tool="http-fetch", command=("curl", "http://x"),
                            proves="fetches"),))
    with pytest.raises(recipes.RecipeRefused, match="http-fetch"):
        recipes.validate(reaching)


def test_a_recipe_may_not_name_an_agent_nobody_declared():
    orphan = recipes.Recipe(
        id="orphan", does="something", agent_id="no-such-agent",
        capability=Capability.VERIFY,
        steps=(recipes.Step(tool="shell", command=("true",), proves="runs"),))
    with pytest.raises(recipes.RecipeRefused, match="no registry entry"):
        recipes.validate(orphan)


def test_a_recipe_filed_under_the_wrong_capability_is_refused():
    """The scheduler routes by capability. A recipe filed under one its agent
    does not have is work sent somewhere it cannot be done."""
    misfiled = recipes.Recipe(
        id="misfiled", does="something", agent_id="self-check",
        capability=Capability.IMPLEMENT,
        steps=(recipes.Step(tool="shell", command=("true",), proves="runs"),))
    with pytest.raises(recipes.RecipeRefused, match="capability"):
        recipes.validate(misfiled)


# ------------------------------------------------------------ a name is a key

def test_an_unknown_name_is_refused_and_never_substituted():
    with pytest.raises(recipes.UnknownRecipe, match="no recipe named"):
        recipes.get("something-nobody-wrote")


def test_the_refusal_says_which_recipes_exist():
    with pytest.raises(recipes.UnknownRecipe) as refused:
        recipes.get("nope")
    assert "execution-canary" in str(refused.value)


@pytest.mark.parametrize("attempt", ["../../etc", "a/b", "a.b", "a:b", " x"])
def test_a_recipe_id_that_looks_like_a_path_cannot_be_declared(attempt):
    with pytest.raises(ValueError):
        recipes.Recipe(id=attempt, does="x", agent_id="self-check",
                       capability=Capability.VERIFY,
                       steps=(recipes.Step(tool="shell", command=("true",),
                                           proves="runs"),))


# ------------------------------------------------------- what a step must say

def test_a_step_with_no_command_is_refused():
    with pytest.raises(ValueError, match="needs a command"):
        recipes.Step(tool="shell", command=(), proves="nothing")


def test_a_step_must_say_what_it_establishes():
    with pytest.raises(ValueError, match="what it establishes"):
        recipes.Step(tool="shell", command=("true",), proves="  ")


def test_a_recipe_with_no_steps_is_refused():
    with pytest.raises(ValueError, match="does nothing"):
        recipes.Recipe(id="empty", does="x", agent_id="self-check",
                       capability=Capability.VERIFY, steps=())


def test_an_unknown_field_is_refused():
    with pytest.raises(ValueError):
        recipes.Step(tool="shell", command=("true",), proves="runs",
                     retries=3)


# --------------------------------------------------- one declaration, not two

def test_the_canary_steps_come_from_the_recipe():
    """They were a hardcoded list in `adapter`. A recipe declaring the same
    three commands would have been a second copy that drifts."""
    from atlas_kernel.mission import adapter
    canary = recipes.get("execution-canary")
    assert len(adapter.SELF_CHECK_STEPS) == len(canary.steps)
    assert [s.proves for s in adapter.SELF_CHECK_STEPS] == \
           [s.proves for s in canary.steps]
    assert [s.tool for s in adapter.SELF_CHECK_STEPS] == \
           [s.tool for s in canary.steps]


def test_the_canary_still_asserts_the_sandbox_is_confining():
    """The step that matters. The first two would pass on a host with no
    sandbox at all."""
    canary = recipes.get("execution-canary")
    assert any("/etc/shadow" in " ".join(s.command) for s in canary.steps)
    assert any("outside the workspace" in s.proves for s in canary.steps)


def test_looking_up_by_capability_finds_it():
    found = recipes.for_capability(Capability.VERIFY)
    assert "execution-canary" in {r.id for r in found}
    assert recipes.for_capability(Capability.PUBLISH_SOCIAL) == ()


def test_a_recipe_declared_twice_would_be_refused():
    """A tuple keeps both and `get` returns whichever comes first, so the other
    is invisible — the same failure a duplicate dict key causes."""
    one = recipes.get("execution-canary")
    with pytest.raises(recipes.RecipeRefused, match="declared twice"):
        original = recipes.RECIPES
        recipes.RECIPES = (one, one)
        try:
            recipes._validate_all()
        finally:
            recipes.RECIPES = original


def test_the_agent_a_recipe_names_is_the_one_that_runs_it():
    """Not chosen at runtime: the agent decides the blast radius, and a runtime
    choice is a runtime blast radius."""
    canary = recipes.get("execution-canary")
    agent = Registry().get(canary.agent_id)
    assert agent.capability is canary.capability


# ------------------------------------- every registry references something real

def test_no_declarative_registry_has_a_dangling_reference():
    """Five hand-maintained tuples reference each other by string. Nothing
    stops one naming something another dropped, and the first anybody would
    hear of it is a refusal at dispatch.

    This is the same guard `_validate_all` gives recipes, widened to the set:
    agents -> tools, recipes -> agents and tools, recurrences -> agents and
    origins.
    """
    from atlas_kernel.mission import origins, recurrence

    known_tools = {tool.id for tool in TOOLS}
    known_agents = {agent.id for agent in AGENTS}
    registry = origins.Registry.build()
    dangling: list[str] = []

    for agent in AGENTS:
        dangling += [f"agent {agent.id} -> tool {t}"
                     for t in agent.tools if t not in known_tools]
    for recipe in recipes.RECIPES:
        if recipe.agent_id not in known_agents:
            dangling.append(f"recipe {recipe.id} -> agent {recipe.agent_id}")
        dangling += [f"recipe {recipe.id} -> tool {s.tool}"
                     for s in recipe.steps if s.tool not in known_tools]
    for rule in recurrence.RECURRENCES:
        if rule.agent_id not in known_agents:
            dangling.append(f"recurrence {rule.id} -> agent {rule.agent_id}")
        if not registry.known(rule.origin_name):
            dangling.append(f"recurrence {rule.id} -> origin {rule.origin_name}")

    assert not dangling, dangling
