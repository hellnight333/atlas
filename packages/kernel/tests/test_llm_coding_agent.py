"""`LLMCodingAgent` — the seam every mission's spend flows through.

Nothing in this repository called this class before. That is exactly why two
defects lived here: it read token usage from an attribute `Completion` has
never had, so every invocation recorded UNKNOWN cost with the provider's own
numbers sitting unread in the object.

The failure had no symptom. Missions ran, reports rendered, and the spend
column was empty — which reads as "cheap" rather than as "not measured". These
tests spend real numbers and check they arrive.
"""

from __future__ import annotations

import httpx
import pytest

from atlas_kernel.llm.models import Completion, ModelSpec
from atlas_kernel.llm.providers import MODELS, OpenAICompatibleProvider
from atlas_kernel.mission.agents import LLMCodingAgent, MalformedResult
from atlas_kernel.mission.models import Plan, PlanStep


def _provider(text: str = "done", *, prompt_tokens: int = 12_000,
              completion_tokens: int = 3_000) -> OpenAICompatibleProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": prompt_tokens,
                      "completion_tokens": completion_tokens},
        })

    return OpenAICompatibleProvider(
        name="qwen", key_env="X", key="k",
        client=httpx.Client(transport=httpx.MockTransport(handler)))


def _agent(**kwargs) -> LLMCodingAgent:
    return LLMCodingAgent(_provider(**kwargs), MODELS["qwen-plus"])


A_PLAN = Plan(goal="add a health route", why="because",
              steps=(PlanStep(order=1, title="add a health route"),))


class TestSpendIsActuallyRecorded:
    def test_the_tokens_the_provider_reported_reach_the_invocation(self) -> None:
        outcome = _agent().implement(A_PLAN, workspace_root="/tmp")
        assert outcome.invocation.input_tokens == 12_000
        assert outcome.invocation.output_tokens == 3_000

    def test_a_priced_model_produces_a_cost_and_says_where_it_came_from(self) -> None:
        invocation = _agent().implement(A_PLAN, workspace_root="/tmp").invocation
        assert invocation.cost is not None
        assert invocation.cost > 0
        assert invocation.cost_status == "ESTIMATED"
        assert invocation.currency == "USD"

    def test_the_cost_is_the_providers_own_figure_not_a_second_one(self) -> None:
        """Two computations of the same number can disagree; one cannot."""
        spec = MODELS["qwen-plus"]
        expected = Completion(text="done", model=spec.id, provider="qwen",
                              input_tokens=12_000, output_tokens=3_000,
                              cost_usd=spec.cost_usd(12_000, 3_000)).cost_usd
        assert _agent().implement(A_PLAN, workspace_root="/tmp").invocation.cost == expected

    def test_a_free_model_reports_no_cost_rather_than_zero_dollars(self) -> None:
        """A self-hosted model has no price table, and "$0.00" and "not priced"
        are different claims. `model_post_init` forbids the first without a
        provenance label, so this also proves the label is never invented."""
        free = ModelSpec(id="qwen3-72b", provider="qwen",
                         base_url="http://127.0.0.1:8000/v1")
        agent = LLMCodingAgent(_provider(), free)
        invocation = agent.implement(A_PLAN, workspace_root="/tmp").invocation
        assert invocation.cost is None
        assert invocation.cost_status == "UNKNOWN"
        assert invocation.currency == ""

    def test_a_provider_that_reports_nothing_is_unknown_not_free(self) -> None:
        invocation = _agent(prompt_tokens=0, completion_tokens=0).implement(
            A_PLAN, workspace_root="/tmp").invocation
        assert invocation.cost is None
        assert invocation.cost_status == "UNKNOWN"

    def test_review_records_its_own_spend_and_does_not_reuse_the_write(self) -> None:
        agent = _agent()
        written = agent.implement(A_PLAN, workspace_root="/tmp")
        reviewed = agent.review(A_PLAN, written, diff="--- a\n+++ b")
        assert reviewed.invocation.task == "review"
        assert written.invocation.task == "implement"
        assert reviewed.invocation.cost is not None


class TestWhatTheAgentClaims:
    def test_the_provider_and_model_are_both_recorded(self) -> None:
        """"Which model wrote this" is a provenance question a bare name
        cannot answer once two providers serve similar model names."""
        invocation = _agent().implement(A_PLAN, workspace_root="/tmp").invocation
        assert invocation.provider == "qwen"
        assert invocation.model == "qwen-plus"

    def test_an_empty_reply_is_malformed_rather_than_a_silent_success(self) -> None:
        with pytest.raises(MalformedResult):
            _agent(text="   ").implement(A_PLAN, workspace_root="/tmp")

    def test_done_is_a_claim_and_is_named_as_one(self) -> None:
        assert _agent().implement(A_PLAN, workspace_root="/tmp").claims_done is True

    def test_planning_returns_a_plan_the_model_actually_wrote(self) -> None:
        plan = _agent(text="step one: read the router").plan("add a health route")
        assert "read the router" in plan.why
        assert plan.approval_required is True
