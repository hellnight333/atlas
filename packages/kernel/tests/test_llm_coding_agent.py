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

    def test_done_reflects_what_happened_not_what_the_model_said(self, tmp_path) -> None:
        """This asserted `claims_done is True` for a reply of "done" that
        changed nothing — which encoded the behaviour that made every real
        mission fail. `claims_done` now follows the workspace."""
        prose = _agent().implement(A_PLAN, workspace_root=str(tmp_path))
        assert prose.claims_done is False, "said done, wrote nothing"

        wrote = LLMCodingAgent(_provider("<<<FILE a.md\nreal\n>>>END\n"),
                               MODELS["qwen-plus"]).implement(
            A_PLAN, workspace_root=str(tmp_path))
        assert wrote.claims_done is True

    def test_planning_returns_a_plan_the_model_actually_wrote(self) -> None:
        plan = _agent(text="step one: read the router").plan("add a health route")
        assert "read the router" in plan.why
        assert plan.approval_required is True


class TestItActuallyChangesTheWorkspace:
    """`implement` asked the model and returned its prose, having touched
    nothing.

    So every mission run by this agent reported success, changed no file, and
    was correctly refused by the worker: three attempts, then failed. Observed
    on production as mission-2e19f410464e. The end-to-end chain — sentence to
    commit — was only ever proven with `FakeCodingAgent`, which does write.
    """

    BLOCK = ("Here is the change.\n"
             "<<<FILE docs/notes/backup.md\n"
             "# Backups\n"
             "\n"
             "An off-host copy survives the machine.\n"
             ">>>END\n"
             "That is all.\n")

    def test_a_returned_file_reaches_the_workspace(self, tmp_path) -> None:
        outcome = LLMCodingAgent(_provider(self.BLOCK), MODELS["qwen-plus"]).implement(
            A_PLAN, workspace_root=str(tmp_path))

        written = tmp_path / "docs" / "notes" / "backup.md"
        assert written.is_file(), "the agent reported a change and wrote nothing"
        assert written.read_text(encoding="utf-8").startswith("# Backups")
        assert outcome.files == ("docs/notes/backup.md",)
        assert outcome.claims_done is True

    def test_a_reply_with_no_file_does_not_claim_to_be_done(self, tmp_path) -> None:
        """The exact claim the worker exists to catch. Better to be honest here
        than to make it catch us."""
        outcome = LLMCodingAgent(_provider("I have completed the work."),
                                 MODELS["qwen-plus"]).implement(
            A_PLAN, workspace_root=str(tmp_path))
        assert outcome.claims_done is False
        assert outcome.files == ()
        assert list(tmp_path.iterdir()) == []

    def test_several_files_in_one_reply(self, tmp_path) -> None:
        reply = ("<<<FILE a.md\nfirst\n>>>END\n"
                 "<<<FILE nested/b.md\nsecond\n>>>END\n")
        outcome = LLMCodingAgent(_provider(reply), MODELS["qwen-plus"]).implement(
            A_PLAN, workspace_root=str(tmp_path))
        assert set(outcome.files) == {"a.md", "nested/b.md"}
        assert (tmp_path / "nested" / "b.md").read_text().strip() == "second"

    def test_an_unterminated_block_is_dropped(self, tmp_path) -> None:
        """A file cut off mid-way is worse than no file, because it looks like
        a change."""
        reply = "<<<FILE a.md\nfirst\n>>>END\n<<<FILE b.md\nsecond, and no end"
        outcome = LLMCodingAgent(_provider(reply), MODELS["qwen-plus"]).implement(
            A_PLAN, workspace_root=str(tmp_path))
        assert outcome.files == ("a.md",)
        assert not (tmp_path / "b.md").exists()


class TestItCannotWriteOutsideTheWorkspace:
    """The distance between "may write the files it names" and "may do what it
    likes" is the whole of what this architecture refuses."""

    def _implement(self, reply: str, tmp_path):
        return LLMCodingAgent(_provider(reply), MODELS["qwen-plus"]).implement(
            A_PLAN, workspace_root=str(tmp_path))

    @pytest.mark.parametrize("path", [
        "../escaped.md",
        "/etc/passwd",
        "nested/../../escaped.md",
        ".git/config",
        "nested/.git/hooks/pre-commit",
    ])
    def test_a_path_leaving_the_repository_is_refused(self, path, tmp_path) -> None:
        with pytest.raises(MalformedResult):
            self._implement(f"<<<FILE {path}\nowned\n>>>END\n", tmp_path)

    def test_one_bad_path_writes_none_of_them(self, tmp_path) -> None:
        """All-or-nothing on the paths. A partial write leaves a workspace that
        is neither the old state nor the requested one, and the commit that
        followed would be of something nobody asked for."""
        reply = ("<<<FILE fine.md\nlegitimate\n>>>END\n"
                 "<<<FILE ../escaped.md\nnot\n>>>END\n")
        with pytest.raises(MalformedResult):
            self._implement(reply, tmp_path)
        assert not (tmp_path / "fine.md").exists()

    def test_too_many_files_is_refused_before_anything_is_written(self, tmp_path) -> None:
        reply = "".join(f"<<<FILE f{i}.md\nx\n>>>END\n" for i in range(200))
        with pytest.raises(MalformedResult, match="the limit is"):
            self._implement(reply, tmp_path)
        assert list(tmp_path.iterdir()) == []

    def test_too_many_bytes_is_refused_before_anything_is_written(self, tmp_path) -> None:
        reply = f"<<<FILE big.md\n{'x' * 3_000_000}\n>>>END\n"
        with pytest.raises(MalformedResult, match="the limit is"):
            self._implement(reply, tmp_path)
        assert list(tmp_path.iterdir()) == []

    def test_the_agent_runs_nothing(self) -> None:
        """Writing is all it does. A model that can aim a tool is the thing the
        architecture refuses, and this is the class a model's words reach."""
        import inspect

        from atlas_kernel.mission import agents

        source = inspect.getsource(agents.LLMCodingAgent)
        for forbidden in ("subprocess", "os.system", "popen", "shutil.rmtree",
                          "eval(", "exec(", "unlink", "rmdir"):
            assert forbidden not in source, (
                f"the model-backed agent can do more than write files: {forbidden}")
