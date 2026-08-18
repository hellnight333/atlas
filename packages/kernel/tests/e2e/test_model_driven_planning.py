"""Open-ended objectives, where the model decides the steps.

Every earlier acceptance test handed the runner a plan someone had written. These
hand it an *objective* and assert on properties of whatever comes back, because
the thing being tested is the deciding — and a test that checks for the eight-step
website DAG would pass only when the model reproduced a recipe, which is the
opposite of what it is supposed to demonstrate.

So there is no expected step list anywhere below. The assertions are invariants
any competent plan must satisfy:

  * only registered actions appear
  * code is written before it is executed
  * a deployment is verified after it happens, not before
  * the verification reads the deploy step's output rather than a literal URL
  * the model composed it, and the plan says so

**Two modes, deliberately distinguished.** `live` runs against a configured model
and is the real acceptance; it skips when no credential exists. `harness` runs
against a scripted provider that returns a deliberately *unusual* plan shape, and
exists to prove these assertions are shape-agnostic — if any of them secretly
encoded the eight-step recipe, the harness mode would fail.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from atlas_kernel.actions import (
    ExecutionContext,
    PlanRunner,
    RegenerateRepairer,
    default_action_runner,
    plan_website,
)
from atlas_kernel.actions.llm_planner import LLMPlanner
from atlas_kernel.actions.runner import REFERENCE
from atlas_kernel.llm.models import Completion, ModelSpec
from atlas_kernel.llm.registry import ModelRegistry, Registration
from atlas_kernel.workspace import Workspace

pytestmark = [pytest.mark.e2e, pytest.mark.integration]


# The objectives. Neither names an action, a step count or an order.
GAME_OBJECTIVE = (
    "Create a simple children's browser game about a rabbit wearing a hat. "
    "Build it, test it, deploy it, verify the public deployment, and report the result."
)
RESEARCH_OBJECTIVE = (
    "Research several children's game concepts, choose the strongest concept, "
    "create the game, test it, deploy it, verify it, and report the URL and evidence."
)


class ScriptedProvider:
    """Returns a fixed reply, so the harness can be exercised without a model.

    The plan it returns is deliberately not the shape the deterministic planner
    produces: different ids, a different number of steps, research folded in
    late. If an assertion in this file quietly depended on the familiar recipe,
    this is what would catch it.
    """

    name = "scripted"

    def __init__(self, plan: dict) -> None:
        self.plan = plan
        self.messages = None

    def complete(self, messages, spec, *, max_tokens, temperature):
        self.messages = messages
        return Completion(text=json.dumps(self.plan), model=spec.id, provider=self.name)


UNUSUAL_PLAN = {
    "steps": [
        {"id": "look_around", "action": "web.search", "payload": {"query": "kids game ideas"}},
        {
            "id": "make_it",
            "action": "code.generate",
            "payload": {"title": "Hat Rabbit", "headline": "Hat Rabbit"},
            "dependencies": ["look_around"],
        },
        {
            "id": "save_it",
            "action": "code.write",
            "payload": {"files": "${make_it.files}"},
            "dependencies": ["make_it"],
        },
        {
            "id": "prove_it",
            "action": "code.execute",
            "payload": {"argv": [sys.executable, "-m", "pytest", "-q", "test_app.py"]},
            "dependencies": ["save_it"],
        },
        {
            "id": "package_it",
            "action": "code.execute",
            "payload": {"argv": [sys.executable, "build.py"]},
            "dependencies": ["prove_it"],
        },
        {
            "id": "ship_it",
            "action": "site.deploy",
            "payload": {"slug": "hat-rabbit", "source_dir": "dist"},
            "dependencies": ["package_it"],
        },
        {
            "id": "check_it",
            "action": "browser.operate",
            "payload": {
                "url": "${ship_it.url}",
                "expect_title": "Hat Rabbit",
                "screenshot": "shipped.png",
            },
            "dependencies": ["ship_it"],
        },
    ]
}


def _scripted_planner(plan: dict, actions):
    provider = ScriptedProvider(plan)
    registry = ModelRegistry()
    registry.register(
        Registration(
            provider=provider,
            spec=ModelSpec(id="scripted-1", provider="scripted", supports_json=True),
        )
    )
    return LLMPlanner(registry, actions=actions, fallback=plan_website), provider


@pytest.fixture
def live_planner():
    """A planner backed by a real, configured model. Skips when none exists."""
    # default_planner() rather than a hand-built one, so the acceptance run
    # exercises the configuration Qevik actually uses — including which model
    # it chooses to plan with.
    from atlas_kernel.actions import default_planner

    actions = default_action_runner()
    planner = default_planner(actions=actions)
    if not planner.available:
        pytest.skip(
            "no model credential configured — set QEVIK_DASHSCOPE_API_KEY or "
            "QEVIK_ANTHROPIC_API_KEY. This is the real acceptance run."
        )
    return planner, actions


# -- the invariants any plan must satisfy ---------------------------------


def assert_plan_is_sane(plan, actions) -> None:
    """Properties, not a step list. Nothing here names an expected shape."""
    steps = plan.steps
    assert steps, "the model returned an empty plan"

    known = set(actions.registered())
    assert {s.action for s in steps} <= known, "the plan used an action that does not exist"

    order = {s.id: i for i, s in enumerate(steps)}

    def positions(action: str) -> list[int]:
        return [order[s.id] for s in steps if s.action == action]

    # Code is written before it is run.
    if positions("code.execute") and positions("code.write"):
        assert min(positions("code.write")) < min(positions("code.execute")), (
            "it tried to execute code before writing any"
        )

    # A deployment is verified after it happens.
    if positions("site.deploy"):
        after = [p for p in positions("browser.operate") if p > min(positions("site.deploy"))]
        assert after, "it deployed and never checked what a visitor receives"

    # And the verification reads the deploy step's output rather than a literal
    # URL. This is the difference between composing steps and listing them.
    deploy_ids = {s.id for s in steps if s.action == "site.deploy"}
    if deploy_ids:
        verifying = [
            s
            for s in steps
            if s.action == "browser.operate"
            and any(
                ref.split(".", 1)[0] in deploy_ids
                for ref in REFERENCE.findall(json.dumps(s.payload))
            )
        ]
        assert verifying, "the verification did not consume the deployment's output"


class TestTheHarnessIsShapeAgnostic:
    """Proves the assertions above do not secretly encode the familiar recipe.

    The scripted plan has seven steps with names no deterministic planner would
    produce. If `assert_plan_is_sane` were checking for the known DAG, this would
    fail — which is the only reason these tests exist alongside the live ones.
    """

    def test_an_unfamiliar_plan_shape_still_satisfies_the_invariants(self) -> None:
        actions = default_action_runner()
        planner, _ = _scripted_planner(UNUSUAL_PLAN, actions)
        plan = planner.plan(GAME_OBJECTIVE)

        assert plan.context_snapshot["planner"] == "llm"
        assert [s.id for s in plan.steps] != [
            "research",
            "generate",
            "write",
            "test",
            "build",
            "verify_local",
            "deploy",
            "verify_deployed",
        ], "the scripted plan must differ from the deterministic one or it proves nothing"
        assert_plan_is_sane(plan, actions)

    def test_the_objective_reaches_the_model_unaltered(self) -> None:
        """The model is given the request, not a pre-digested step list."""
        actions = default_action_runner()
        planner, provider = _scripted_planner(UNUSUAL_PLAN, actions)
        planner.plan(GAME_OBJECTIVE)
        assert provider.messages[-1].content == GAME_OBJECTIVE

    def test_a_plan_that_skips_verification_is_caught(self) -> None:
        """The invariant that matters most: a plan can deploy and report success
        without ever looking. That must fail loudly."""
        actions = default_action_runner()
        blind = {
            "steps": [
                {"id": "g", "action": "code.generate", "payload": {"title": "X"}},
                {
                    "id": "w",
                    "action": "code.write",
                    "payload": {"files": "${g.files}"},
                    "dependencies": ["g"],
                },
                {
                    "id": "d",
                    "action": "site.deploy",
                    "payload": {"slug": "x"},
                    "dependencies": ["w"],
                },
            ]
        }
        planner, _ = _scripted_planner(blind, actions)
        plan = planner.plan(GAME_OBJECTIVE)
        with pytest.raises(AssertionError, match="never checked"):
            assert_plan_is_sane(plan, actions)

    def test_a_plan_using_a_literal_url_is_caught(self) -> None:
        """Composition means the URL comes from the deploy step. A hard-coded
        one looks identical in a report and is a coincidence, not a pipeline."""
        actions = default_action_runner()
        literal = json.loads(json.dumps(UNUSUAL_PLAN))
        literal["steps"][-1]["payload"]["url"] = "http://2.28.62.83/hat-rabbit/"
        planner, _ = _scripted_planner(literal, actions)
        plan = planner.plan(GAME_OBJECTIVE)
        with pytest.raises(AssertionError, match="did not consume"):
            assert_plan_is_sane(plan, actions)


class TestLiveModelPlanning:
    """The real acceptance. Skips without a credential; nothing is simulated."""

    def test_it_plans_a_game_from_an_open_ended_objective(self, live_planner) -> None:
        planner, actions = live_planner
        plan = planner.plan(GAME_OBJECTIVE, title="Hat Rabbit", python=sys.executable)
        assert plan.context_snapshot["planner"] == "llm", planner.last_fallback_reason
        assert_plan_is_sane(plan, actions)

    def test_a_research_objective_produces_research_that_feeds_the_build(
        self, live_planner
    ) -> None:
        """Conditional behaviour rather than a fixed recipe: the second objective
        asks for concepts to be compared and one chosen, so a plan that searches
        and then ignores what it found has not done the task."""
        planner, actions = live_planner
        plan = planner.plan(RESEARCH_OBJECTIVE, title="Chosen Concept", python=sys.executable)
        assert plan.context_snapshot["planner"] == "llm", planner.last_fallback_reason
        assert_plan_is_sane(plan, actions)

        search_ids = {s.id for s in plan.steps if s.action == "web.search"}
        assert search_ids, "it was asked to research and did not"
        consumers = [
            s
            for s in plan.steps
            if any(
                ref.split(".", 1)[0] in search_ids
                for ref in REFERENCE.findall(json.dumps(s.payload))
            )
        ]
        assert consumers, "it researched and then ignored what it found"

    def test_the_two_objectives_do_not_produce_identical_plans(self, live_planner) -> None:
        """If they did, the model is emitting a template rather than deciding."""
        planner, _ = live_planner
        game = planner.plan(GAME_OBJECTIVE, title="Hat Rabbit", python=sys.executable)
        research = planner.plan(RESEARCH_OBJECTIVE, title="Chosen", python=sys.executable)
        assert [s.action for s in game.steps] != [s.action for s in research.steps] or len(
            game.steps
        ) != len(research.steps), "both objectives produced the same plan"


class TestFailureRecoveryUnderAModelPlan:
    def test_a_model_plan_repairs_a_genuine_failure_and_re_runs(self, tmp_path: Path) -> None:
        """The failure is real — the project is corrupted after it is written, so
        its own test suite fails — and the repair happens inside the runner with
        no intervention. Uses the scripted planner so the failure is reproducible
        rather than dependent on what a model happened to emit."""
        actions = default_action_runner()
        workspace = Workspace.create(tmp_path, "model-plan-repair")
        ctx = ExecutionContext(workspace=workspace, search_factory=_stub_search)

        local = json.loads(json.dumps(UNUSUAL_PLAN))
        local["steps"] = [
            s for s in local["steps"] if s["action"] not in ("site.deploy", "browser.operate")
        ]
        planner, _ = _scripted_planner(local, actions)
        plan = planner.plan(GAME_OBJECTIVE)
        assert plan.context_snapshot["planner"] == "llm"

        from atlas_kernel.actions.handlers import code_write

        class Saboteur:
            done = False

            def __call__(self, payload, context):
                result = code_write(payload, context)
                if context.workspace.exists("app.py") and not self.done:
                    self.done = True
                    context.workspace.write("app.py", "def render():\n    return missing\n")
                return result

        actions.register(actions.specs["code.write"], Saboteur())
        report = PlanRunner(actions, repairer=RegenerateRepairer()).run(plan, ctx)

        assert report.ok, f"the model plan did not recover:\n{report.summary()}"
        assert report.repairs == 1
        attempts = [r for r in report.records if r.step_id == "prove_it"]
        assert len(attempts) == 2
        assert not attempts[0].ok and attempts[1].ok
        assert attempts[1].attempt == 2


def _stub_search():
    class Stub:
        def search(self, query):
            from atlas_kernel.research.models import SearchResult, SearchResults

            return SearchResults(
                query=query.text,
                provider="stub",
                results=[SearchResult(url="https://example.com/kids-games", title="Ideas")],
            )

    return Stub()
