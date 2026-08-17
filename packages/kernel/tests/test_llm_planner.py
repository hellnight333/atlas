"""The model-driven planner, and the validation that makes it usable.

A model asked for a plan will invent an action, reference a step that never ran,
or omit verification. None of those may reach the runner, so most of what
follows is about refusing bad plans rather than accepting good ones.
"""

from __future__ import annotations

import json

import pytest

from atlas_kernel.actions import default_action_runner, plan_website
from atlas_kernel.actions.llm_planner import (
    LLMPlanner,
    PlanRejected,
    extract_json,
    validate,
)
from atlas_kernel.llm.models import Completion, ModelSpec
from atlas_kernel.llm.registry import ModelRegistry, NoModelAvailable, Registration

ACTIONS = default_action_runner()
KNOWN = set(ACTIONS.registered())

GOOD_PLAN = {
    "steps": [
        {"id": "gen", "action": "code.generate", "payload": {"title": "Rabbit Racer"}},
        {
            "id": "write",
            "action": "code.write",
            "payload": {"files": "${gen.files}"},
            "dependencies": ["gen"],
        },
        {
            "id": "test",
            "action": "code.execute",
            "payload": {"argv": ["python3", "-m", "pytest", "-q"]},
            "dependencies": ["write"],
        },
    ]
}


class FakeProvider:
    """Returns whatever reply the test wants, and records what it was asked."""

    name = "fake"

    def __init__(self, reply: str = "", error: Exception | None = None) -> None:
        self.reply = reply
        self.error = error
        self.messages = None

    def complete(self, messages, spec, *, max_tokens, temperature):
        self.messages = messages
        if self.error:
            raise self.error
        return Completion(text=self.reply, model=spec.id, provider=self.name)


def _registry(provider) -> ModelRegistry:
    registry = ModelRegistry()
    registry.register(
        Registration(
            provider=provider,
            spec=ModelSpec(id="fake-1", provider="fake", supports_json=True),
        )
    )
    return registry


def _planner(reply="", error=None, fallback=plan_website):
    provider = FakeProvider(json.dumps(GOOD_PLAN) if reply == "" else reply, error)
    return LLMPlanner(_registry(provider), actions=ACTIONS, fallback=fallback), provider


class TestReadingTheReply:
    def test_plain_json_is_read(self) -> None:
        assert extract_json('{"steps": []}') == {"steps": []}

    def test_a_fenced_reply_is_tolerated(self) -> None:
        """Models fence their JSON despite being asked not to."""
        assert extract_json('```json\n{"steps": [1]}\n```') == {"steps": [1]}

    def test_a_prefaced_reply_is_tolerated(self) -> None:
        assert extract_json('Sure! Here is the plan:\n{"steps": [2]}') == {"steps": [2]}

    def test_prose_with_no_json_is_rejected(self) -> None:
        with pytest.raises(PlanRejected, match="no JSON object"):
            extract_json("I cannot help with that.")

    def test_malformed_json_is_rejected_with_the_reason(self) -> None:
        with pytest.raises(PlanRejected, match="not valid JSON"):
            extract_json('{"steps": [,]}')

    def test_a_json_array_is_not_a_plan(self) -> None:
        with pytest.raises(PlanRejected, match="not an object"):
            extract_json("[1, 2, 3]")


class TestValidation:
    """Nothing a model produces is trusted until it validates."""

    def test_a_good_plan_becomes_steps(self) -> None:
        steps = validate(GOOD_PLAN, known_actions=KNOWN)
        assert [s.id for s in steps] == ["gen", "write", "test"]
        assert steps[1].dependencies == ["gen"]

    def test_an_invented_action_is_rejected_and_names_what_exists(self) -> None:
        """The failure that actually happens."""
        plan = {"steps": [{"id": "a", "action": "site.publish_everywhere", "payload": {}}]}
        with pytest.raises(PlanRejected) as raised:
            validate(plan, known_actions=KNOWN)
        assert "site.publish_everywhere" in str(raised.value)
        assert "code.execute" in str(raised.value), "it should say what is available"

    def test_a_reference_to_a_step_that_has_not_run_is_rejected(self) -> None:
        """Caught before execution, so a mid-run failure — after files are
        written and money is spent — becomes a rejected plan instead."""
        plan = {
            "steps": [
                {"id": "a", "action": "code.write", "payload": {"files": "${later.files}"}},
                {"id": "later", "action": "code.generate", "payload": {}},
            ]
        }
        with pytest.raises(PlanRejected, match="has not run by then"):
            validate(plan, known_actions=KNOWN)

    def test_a_forward_dependency_is_rejected(self) -> None:
        plan = {
            "steps": [
                {"id": "a", "action": "code.generate", "payload": {}, "dependencies": ["b"]},
                {"id": "b", "action": "code.generate", "payload": {}},
            ]
        }
        with pytest.raises(PlanRejected, match="not an earlier step"):
            validate(plan, known_actions=KNOWN)

    def test_a_shell_string_for_argv_is_rejected(self) -> None:
        """code.execute takes argv; a string would be assembled into something
        a shell interprets."""
        plan = {"steps": [{"id": "a", "action": "code.execute", "payload": {"argv": "rm -rf /"}}]}
        with pytest.raises(PlanRejected, match="never a shell string"):
            validate(plan, known_actions=KNOWN)

    def test_duplicate_ids_are_rejected(self) -> None:
        plan = {
            "steps": [
                {"id": "a", "action": "code.generate", "payload": {}},
                {"id": "a", "action": "code.write", "payload": {"files": {"x": "y"}}},
            ]
        }
        with pytest.raises(PlanRejected, match="duplicate step id"):
            validate(plan, known_actions=KNOWN)

    def test_an_empty_plan_is_rejected(self) -> None:
        with pytest.raises(PlanRejected, match="no steps"):
            validate({"steps": []}, known_actions=KNOWN)

    def test_a_step_without_an_id_is_rejected(self) -> None:
        with pytest.raises(PlanRejected, match="has no id"):
            validate({"steps": [{"action": "code.generate"}]}, known_actions=KNOWN)

    def test_a_non_object_payload_is_rejected(self) -> None:
        plan = {"steps": [{"id": "a", "action": "code.generate", "payload": "stuff"}]}
        with pytest.raises(PlanRejected, match="non-object payload"):
            validate(plan, known_actions=KNOWN)

    def test_references_nested_in_lists_and_dicts_are_checked(self) -> None:
        plan = {
            "steps": [
                {
                    "id": "a",
                    "action": "browser.operate",
                    "payload": {"expect_text": {"#h": "${nope.title}"}},
                }
            ]
        }
        with pytest.raises(PlanRejected, match="nope"):
            validate(plan, known_actions=KNOWN)


class TestPlanning:
    def test_it_composes_a_plan_from_the_model(self) -> None:
        planner, _ = _planner()
        plan = planner.plan("build me a site")
        assert [s.id for s in plan.steps] == ["gen", "write", "test"]
        assert plan.context_snapshot["planner"] == "llm"
        assert planner.last_fallback_reason == ""

    def test_the_prompt_lists_the_actions_that_are_actually_registered(self) -> None:
        """Generated from the registry, so an action added later is available to
        the planner without anyone remembering to update a prompt."""
        planner, provider = _planner()
        planner.plan("anything")
        system = provider.messages[0].content
        for action in ACTIONS.registered():
            assert action in system

    def test_a_rejected_plan_falls_back_and_says_why(self) -> None:
        planner, _ = _planner(reply='{"steps": [{"id": "a", "action": "nope"}]}')
        plan = planner.plan("build me a site", title="Fallback Site")
        assert plan.context_snapshot["planner"] == "deterministic"
        assert "rejected" in planner.last_fallback_reason
        assert "nope" in planner.last_fallback_reason

    def test_a_failing_model_call_falls_back(self) -> None:
        planner, _ = _planner(error=RuntimeError("502 from the provider"))
        plan = planner.plan("build me a site", title="Fallback Site")
        assert plan.context_snapshot["planner"] == "deterministic"
        assert "502" in planner.last_fallback_reason

    def test_no_model_configured_falls_back_rather_than_failing(self) -> None:
        """The state the server is actually in: no credential."""
        planner = LLMPlanner(ModelRegistry(), actions=ACTIONS, fallback=plan_website)
        assert not planner.available
        plan = planner.plan("build a site", title="Deterministic")
        assert plan.context_snapshot["planner"] == "deterministic"
        assert "no model configured" in planner.last_fallback_reason
        assert [s.id for s in plan.steps][:2] == ["generate", "write"]

    def test_without_a_fallback_it_refuses_rather_than_inventing(self) -> None:
        planner = LLMPlanner(ModelRegistry(), actions=ACTIONS, fallback=None)
        with pytest.raises(PlanRejected):
            planner.plan("build a site")

    def test_availability_reflects_the_registry(self) -> None:
        planner, _ = _planner()
        assert planner.available
        with pytest.raises(NoModelAvailable):
            ModelRegistry().resolve()

    def test_planning_is_deterministic_by_default(self) -> None:
        """A plan is a structured artifact, not prose; sampling variety buys
        nothing and costs reproducibility."""
        planner, _ = _planner()
        assert planner.temperature == 0.0


class TestTheBoundaryDoesNotMove:
    def test_a_model_cannot_grant_itself_authorisation(self) -> None:
        """Approval is enforced in the deploy handler against the execution
        context, not in the plan — so a model emitting "public": true produces a
        plan that is refused at run time exactly as a hand-written one would be.
        """
        plan = {
            "steps": [
                {
                    "id": "deploy",
                    "action": "site.deploy",
                    "payload": {"slug": "x", "public": True},
                }
            ]
        }
        steps = validate(plan, known_actions=KNOWN)  # valid as a plan...
        assert steps[0].payload["public"] is True

        from atlas_kernel.actions.handlers import PublishNotAuthorised, site_deploy

        class Target:
            name = "public-host"
            is_public = True

        class Ctx:
            approvals = None
            deploy_target = Target()

        # ...and still refused when it runs.
        with pytest.raises(PublishNotAuthorised):
            site_deploy(steps[0].payload, Ctx())
