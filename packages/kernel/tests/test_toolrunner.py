"""The tool-executing role: what it may reach, and what it may not.

A tool-executing agent is **not a model with tools**. A model may eventually
propose `recipe = "discover-uae-dental"` — a key, which resolves or is refused.
It may not propose a tool, a URL, a step, or an interpretation. These tests are
each one of those refusals.
"""

from __future__ import annotations

import pytest

from atlas_kernel.fabric import recipes
from atlas_kernel.fabric.agents import Registry
from atlas_kernel.mission import toolrunner
from atlas_kernel.mission.agents import AgentOutcome, CodingAgent
from atlas_kernel.mission.toolrunner import ToolAgent

RESEARCHER = "researcher"
RECIPE = "discover-uae-dental"


def a_recipe(tool: str, *command: str, agent: str = RESEARCHER) -> recipes.Recipe:
    return recipes.Recipe(
        id="probe", does="probe", agent_id=agent,
        capability=Registry().get(agent).capability,
        steps=(recipes.Step(tool=tool, command=command or ("x",),
                            proves="probes"),))


# ------------------------------------------- tool access comes from the role

def test_the_research_role_declares_only_network_research_tools():
    assert set(Registry().get(RESEARCHER).tools) == {"http-fetch", "dns"}


@pytest.mark.parametrize("tool,capability", [
    ("shell", "arbitrary shell"),
    ("filesystem", "filesystem write"),
    ("git-worktree", "git"),
    ("browser", "browser automation"),
    ("smtp", "email"),
    ("publish", "publication"),
    ("amazon", "marketplace side effects"),
])
def test_a_research_recipe_cannot_obtain(tool, capability):
    """Not given generic shell access merely because the adapter exists."""
    refused = toolrunner.refusals(a_recipe(tool), Registry().get(RESEARCHER))
    assert refused, f"{capability} was permitted"
    assert tool in refused[0]
    assert "comes from the registered role" in refused[0]


def test_a_tool_nobody_declared_anywhere_is_refused():
    """A typo is not permission."""
    assert toolrunner.refusals(a_recipe("htp-fetch"), Registry().get(RESEARCHER))


def test_a_declared_tool_with_no_adapter_is_refused_before_it_runs():
    """`browser` is a real tool in the contract that nothing here can invoke.
    Refused up front rather than failing partway through a sequence."""
    browsing = Registry().get("browser")
    assert "browser" in browsing.tools
    refused = toolrunner.refusals(
        a_recipe("browser", agent="browser"), browsing)
    assert refused and "nothing here knows how to invoke it" in refused[0]


def test_the_declared_recipe_is_runnable_by_its_agent():
    assert toolrunner.refusals(recipes.get(RECIPE),
                               Registry().get(RESEARCHER)) == []


# ------------------------------------------------ a URL comes from the recipe

def test_the_allow_list_is_exactly_what_the_recipe_names():
    assert toolrunner.permitted_urls(recipes.get(RECIPE)) == {
        "https://www.dha.gov.ae/"}


def test_a_url_outside_the_recipe_is_refused_before_a_socket_opens():
    """What makes "a model proposed a recipe" safe."""
    step = toolrunner._fetch(
        recipes.Step(tool="http-fetch",
                     command=("https://attacker.example/exfil",),
                     proves="p"),
        allowed=frozenset({"https://allowed.example/"}), client=None,
        check_addresses=True)
    assert not step.passed
    assert "not named by this recipe" in step.detail
    assert not step.evidence, "evidence was produced for a refused URL"


def test_a_recipe_naming_an_undeclared_agent_is_not_dispatchable():
    orphan = recipes.Recipe(
        id="orphan", does="p", agent_id="nobody",
        capability=recipes.Capability.RESEARCH,
        steps=(recipes.Step(tool="http-fetch", command=("https://x.test/",),
                            proves="p"),))
    with pytest.raises(toolrunner.NotDispatchable, match="no registry entry"):
        toolrunner.run(orphan)


def test_running_a_recipe_the_agent_cannot_use_refuses_before_any_step():
    with pytest.raises(toolrunner.NotDispatchable, match="does not declare"):
        toolrunner.run(a_recipe("shell", "echo", "hello"))


# ----------------------------------------------------------- the role itself

def test_the_role_satisfies_the_same_protocol_every_other_role_does():
    """A non-coding agent is a role, not a second worker."""
    assert isinstance(ToolAgent(recipes.get(RECIPE)), CodingAgent)


def test_the_role_needs_no_model_credential():
    """No prompt, no provider, no key."""
    agent = ToolAgent(recipes.get(RECIPE))
    assert not hasattr(agent, "provider")
    plan = agent.plan("anything")
    assert plan.goal == recipes.get(RECIPE).does
    assert len(plan.steps) == len(recipes.get(RECIPE).steps)


def test_the_plan_is_the_recipe_and_nothing_is_generated():
    """A plan is what a person approves; for a declared recipe the steps were
    approved when it merged."""
    plan = ToolAgent(recipes.get(RECIPE)).plan("ignored request text")
    assert RECIPE in plan.why
    assert plan.estimated_cost == 0.0 and plan.cost_status == "REPORTED"


def test_an_undispatchable_recipe_becomes_a_blocker_not_a_crash():
    agent = ToolAgent(a_recipe("shell", "echo", "hi"))
    outcome = agent.implement(agent.plan("x"), workspace_root="/tmp")
    assert not outcome.claims_done
    assert outcome.blockers and outcome.blockers[0].kind == "ARCHITECTURE"


def test_a_research_outcome_writes_no_files_and_says_so():
    """Its currency is evidence. Judging it on files failed every successful
    run before `produced_nothing` learned to ask the outcome."""
    empty = AgentOutcome(claims_done=True, files=(), evidence_count=0)
    assert empty.produced_nothing

    researched = AgentOutcome(claims_done=True, files=(), evidence_count=3)
    assert not researched.produced_nothing

    coded = AgentOutcome(claims_done=True, files=("a.py",))
    assert not coded.produced_nothing


def test_a_coding_agent_is_held_to_exactly_the_same_standard_as_before():
    """The guard was generalised, not weakened."""
    assert AgentOutcome(claims_done=True, files=()).produced_nothing


# ------------------------------------------------------- the evidence boundary

def test_the_runner_records_which_tools_were_actually_invoked():
    """"could have fetched" and "fetched" are different facts."""
    found = toolrunner.Result(recipe="r", agent_id="a", steps=[
        toolrunner.Step(tool="dns", invoked="x", proves="p", passed=True)])
    assert found.tools_invoked == ("dns",)


def test_the_result_summary_carries_identity_and_counts_not_conclusions():
    rendered = toolrunner.Result(recipe=RECIPE, agent_id=RESEARCHER).summary()
    assert rendered["recipe"] == RECIPE and rendered["agent_id"] == RESEARCHER
    assert set(rendered) == {"recipe", "agent_id", "passed", "tools_invoked",
                             "evidence_count", "steps"}
    words = str(rendered).lower()
    assert "opportunity" not in words and "is new" not in words


def test_an_inconclusive_dns_answer_records_nothing_and_does_not_fail():
    """A name server that says no such host has answered; one that times out
    has not."""
    step = toolrunner._resolve(
        recipes.Step(tool="dns", command=("localhost",), proves="p"))
    assert step.passed
    assert all(e.observed["resolution"] != "unknown" for e in step.evidence)


# -------------------------------------------------- the recurrence names it

def test_the_daily_discovery_recurrence_names_its_recipe():
    """Asserts that it names *a* recipe and which agent runs it — deliberately
    not a specific id. The earlier version pinned the placeholder's name, which
    is how the recurrence went on pointing at a recipe with no extractor while
    the suite stayed green."""
    from atlas_kernel.mission import recurrence

    daily = next(r for r in recurrence.RECURRENCES
                 if r.id == "rec-daily-business-discovery")
    assert daily.recipe
    assert recipes.get(daily.recipe).agent_id == RESEARCHER
    assert daily.agent_id == RESEARCHER


def test_every_recurrence_that_names_a_recipe_names_a_real_one():
    from atlas_kernel.mission import recurrence

    for rule in recurrence.RECURRENCES:
        if rule.recipe:
            assert recipes.get(rule.recipe).agent_id == rule.agent_id, rule.id


def test_the_mission_a_recurrence_creates_carries_the_recipe():
    from atlas_kernel.mission import origins, recurrence

    daily = next(r for r in recurrence.RECURRENCES
                 if r.id == "rec-daily-business-discovery")
    registry = origins.Registry.build()
    firing = recurrence.assess(daily, at=daily.anchor, missions=[])
    mission, _ = recurrence.enqueue(daily, firing, tenant=daily.tenant_id,
                                    origin=registry.resolve(daily.origin_name))
    assert mission.recipe == daily.recipe
    assert mission.agent_id == RESEARCHER


# --------------------------------------- the tests measure the declaration

@pytest.mark.parametrize("tool", ["shell", "filesystem", "git-worktree"])
def test_the_refusals_follow_the_declaration_and_not_a_hardcoded_list(tool):
    """A negative control on the permission tests themselves.

    Every "cannot obtain X" test above passes if the refusal is hardcoded
    rather than derived from the role's entry. This widens a *copy* of the role
    and asserts the refusal disappears — so the tests are measuring the
    declaration.

    It caught a real inconsistency: `git-worktree` was refused even when
    declared, because `COMMANDS` and `DISPATCHABLE` were written out separately
    and disagreed. `_command` had a branch nothing could reach, and a recipe
    declaring it was refused for the wrong reason.
    """
    registry = Registry()
    real = registry.get(RESEARCHER)
    widened = real.model_copy(update={
        "tools": ("http-fetch", "dns", "shell", "filesystem", "git-worktree")})

    assert toolrunner.refusals(a_recipe(tool), real), (
        f"{tool} was permitted to the real role")
    assert not toolrunner.refusals(a_recipe(tool), widened), (
        f"{tool} stayed refused after being declared, so the refusal is not "
        "coming from the declaration")


def test_dispatchable_is_derived_so_the_two_sets_cannot_drift():
    assert toolrunner.COMMANDS <= toolrunner.DISPATCHABLE
    assert {"http-fetch", "dns"} <= toolrunner.DISPATCHABLE


def test_a_recurrence_that_should_produce_sightings_names_a_recipe_that_can():
    """The nightly discovery entry pointed at a recipe with **no extractor**,
    so it would have fetched a page, extracted nothing and recorded no business
    — night after night, reporting success each time.

    A recurrence whose whole purpose is to remember businesses must name a
    recipe that can produce them.
    """
    from atlas_kernel.mission import recurrence

    daily = next(r for r in recurrence.RECURRENCES
                 if r.id == "rec-daily-business-discovery")
    assert daily.recipe, "the discovery recurrence names no recipe"
    assert recipes.get(daily.recipe).extractor, (
        f"{daily.recipe} declares no extractor, so it produces evidence and "
        "never a sighting")


# ------------------------------------- targets from memory, not from a proposal

def test_a_recipe_without_a_target_source_ignores_offered_targets():
    """The ordinary case: the steps name every URL, and nothing widens that."""
    declared = recipes.get(RECIPE)
    assert not declared.targets_from
    assert toolrunner.permitted_urls(
        declared, targets=["https://attacker.example/"]) == \
        toolrunner.permitted_urls(declared)


def test_a_verification_recipe_may_fetch_what_memory_holds():
    verify = recipes.get("verify-recorded-websites")
    assert verify.targets_from == "business_websites"
    allowed = toolrunner.permitted_urls(
        verify, targets=["https://clinic.example/"])
    assert "https://clinic.example/" in allowed


def test_a_target_source_nobody_declared_is_refused():
    with pytest.raises(recipes.RecipeRefused, match="not a declared source"):
        recipes.validate(recipes.Recipe(
            id="invented", does="x", agent_id=RESEARCHER,
            capability=recipes.Capability.RESEARCH, targets_from="anywhere",
            steps=(recipes.Step(tool="http-fetch",
                                command=("https://x.test/",), proves="p"),)))


def test_targets_are_bounded():
    """A market that grows to ten thousand businesses must not become ten
    thousand fetches in one mission."""
    class Everything:
        def businesses_by_website(self, *, limit, tenant=None):
            assert limit <= 200, "the repository was asked for an unbounded list"
            from atlas_kernel.opportunity.models import Business
            return {f"https://s{n}.example/":
                    Business(id=f"b-{n}", name=f"S{n}",
                             website=f"https://s{n}.example/")
                    for n in range(limit)}

    found = toolrunner.targets_for(recipes.get("verify-recorded-websites"),
                                   repository=Everything(), limit=10)
    assert len(found) == 10


def test_no_repository_means_no_targets():
    """A verification run with nowhere to read from fetches nothing rather than
    falling back to something."""
    assert toolrunner.targets_for(recipes.get("verify-recorded-websites"),
                                  repository=None) == []


def test_an_address_guard_refusal_still_fails_a_multi_target_step():
    """One site being down is one target out of many. Being pointed at an
    address the guard refuses is worth stopping for."""
    step = toolrunner._fetch(
        recipes.Step(tool="http-fetch",
                     command=("http://169.254.169.254/", "http://10.0.0.1/"),
                     proves="p"),
        allowed=frozenset({"http://169.254.169.254/", "http://10.0.0.1/"}),
        client=None, check_addresses=True)
    assert not step.passed
    assert step.evidence, "the refusals were not recorded as evidence"
