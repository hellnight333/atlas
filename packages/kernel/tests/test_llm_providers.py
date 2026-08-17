"""Multi-provider language models.

Claude is in use; Qwen and DeepSeek are expected. These tests defend the thing
that makes that cheap later: nothing in Qevik names a vendor, and adding a
provider is a registration rather than a change to any caller.

The selection tests matter most. A self-hosted model costs nothing per token, so
the moment the Z8 exists the registry should prefer it — without a single call
site being edited. That is the whole return on having a provider layer.
"""

from __future__ import annotations

import httpx
import pytest

from atlas_kernel.llm.models import (
    Completion,
    Message,
    NotConfigured,
    RateLimited,
    Role,
)
from atlas_kernel.llm.providers import MODELS, AnthropicProvider, OpenAICompatibleProvider
from atlas_kernel.llm.registry import (
    ModelRegistry,
    NoModelAvailable,
    Registration,
    default_registry,
)

HELLO = [Message(role=Role.SYSTEM, content="Be brief."), Message(role=Role.USER, content="Hi")]


def _anthropic_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "content": [{"type": "text", "text": "Hello."}],
            "usage": {"input_tokens": 12, "output_tokens": 3},
            "stop_reason": "end_turn",
        },
    )


def _openai_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": "Hello."}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3},
        },
    )


def _anthropic(handler) -> AnthropicProvider:
    return AnthropicProvider(key="k", client=httpx.Client(transport=httpx.MockTransport(handler)))


def _compatible(handler, name: str = "qwen") -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        name=name, key_env="X", key="k", client=httpx.Client(transport=httpx.MockTransport(handler))
    )


@pytest.fixture(autouse=True)
def no_inherited_keys(monkeypatch: pytest.MonkeyPatch):
    """A developer with real keys exported would otherwise run a different test
    from CI, and the one that passes locally is the one nobody investigates."""
    for prefix in ("QEVIK_", "ATLAS_", ""):
        for name in ("ANTHROPIC_API_KEY", "DASHSCOPE_API_KEY", "QWEN_API_KEY"):
            monkeypatch.delenv(f"{prefix}{name}", raising=False)


class TestOneShapeForEveryProvider:
    def test_anthropic_and_openai_compatible_return_the_same_type(self) -> None:
        """The point of the layer. A caller cannot tell which one answered."""
        a = _anthropic(_anthropic_ok).complete(
            HELLO, MODELS["claude-sonnet-5"], max_tokens=100, temperature=0
        )
        spec = MODELS["qwen3-72b"].model_copy(update={"base_url": "http://z8:8000/v1"})
        q = _compatible(_openai_ok).complete(HELLO, spec, max_tokens=100, temperature=0)
        assert isinstance(a, Completion) and isinstance(q, Completion)
        assert a.text == q.text == "Hello."
        assert (a.input_tokens, a.output_tokens) == (q.input_tokens, q.output_tokens)

    def test_each_records_which_provider_answered(self) -> None:
        """Provenance: "which model wrote this" cannot be answered by a bare
        model name once two providers serve similar ones."""
        a = _anthropic(_anthropic_ok).complete(
            HELLO, MODELS["claude-sonnet-5"], max_tokens=10, temperature=0
        )
        assert a.provider == "anthropic" and a.model == "claude-sonnet-5"

    def test_the_system_prompt_becomes_a_field_for_anthropic(self) -> None:
        """Anthropic takes it separately; the OpenAI format takes it as a turn.
        Callers write one thing and the adapters differ."""
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return _anthropic_ok(request)

        _anthropic(handler).complete(HELLO, MODELS["claude-sonnet-5"], max_tokens=10, temperature=0)
        import json

        body = json.loads(seen[0].content)
        assert body["system"] == "Be brief."
        assert [m["role"] for m in body["messages"]] == ["user"]

    def test_cost_is_computed_from_the_providers_own_rates(self) -> None:
        a = _anthropic(_anthropic_ok).complete(
            HELLO, MODELS["claude-opus-5"], max_tokens=10, temperature=0
        )
        assert a.cost_usd == pytest.approx(12 / 1e6 * 15 + 3 / 1e6 * 75)

    def test_a_self_hosted_model_costs_nothing(self) -> None:
        """The field exists so this is expressible rather than assumed away."""
        spec = MODELS["qwen3-72b"].model_copy(update={"base_url": "http://z8:8000/v1"})
        q = _compatible(_openai_ok).complete(HELLO, spec, max_tokens=10, temperature=0)
        assert q.cost_usd == 0.0

    def test_truncation_is_distinguishable_from_finishing(self) -> None:
        """A truncated JSON reply is invalid rather than short, and callers get
        this wrong when they only look at the text."""
        assert Completion(text="{", model="m", provider="p", stop_reason="max_tokens").truncated
        assert not Completion(text="{}", model="m", provider="p", stop_reason="end_turn").truncated


class TestSelection:
    def _registry(self) -> ModelRegistry:
        registry = ModelRegistry()
        registry.register(
            Registration(provider=_anthropic(_anthropic_ok), spec=MODELS["claude-opus-5"])
        )
        registry.register(
            Registration(provider=_anthropic(_anthropic_ok), spec=MODELS["claude-sonnet-5"])
        )
        return registry

    def test_it_picks_the_cheapest_model_that_can_do_the_job(self) -> None:
        assert self._registry().resolve(needs_tools=True).name == "claude-sonnet-5"

    def test_a_local_model_wins_even_against_a_cheaper_hosted_one(self) -> None:
        """The Z8 arriving should redirect traffic with no call site edited."""
        registry = self._registry()
        spec = MODELS["qwen3-72b"].model_copy(update={"base_url": "http://z8:8000/v1"})
        registry.register(Registration(provider=_compatible(_openai_ok), spec=spec, is_local=True))
        assert registry.resolve(needs_tools=True).name == "qwen3-72b"

    def test_an_explicit_choice_is_honoured(self) -> None:
        assert self._registry().resolve(preferred="claude-opus-5").name == "claude-opus-5"

    def test_an_unregistered_model_names_the_registered_ones(self) -> None:
        with pytest.raises(NoModelAvailable, match="known:"):
            self._registry().resolve(preferred="gpt-9")

    def test_an_unsatisfiable_requirement_says_which_one(self) -> None:
        """Beats "no model available", which sends the reader hunting for a
        registration that is not missing."""
        with pytest.raises(NoModelAvailable, match="cost"):
            self._registry().resolve(needs_vision=True, max_cost_per_mtok=0.5)

    def test_an_empty_registry_names_the_capability(self) -> None:
        with pytest.raises(NoModelAvailable, match="text.generate"):
            ModelRegistry().resolve()

    def test_completing_through_the_registry_names_no_vendor(self) -> None:
        """How every caller in Qevik should reach a model."""
        result = self._registry().complete(HELLO, needs_tools=True)
        assert result.text == "Hello."

    def test_registering_the_same_model_twice_replaces_it(self) -> None:
        registry = self._registry()
        registry.register(
            Registration(provider=_anthropic(_anthropic_ok), spec=MODELS["claude-opus-5"])
        )
        assert len(registry.models) == 2


class TestFailures:
    def test_rate_limiting_is_its_own_type_because_it_is_retryable(self) -> None:
        with pytest.raises(RateLimited):
            _anthropic(lambda r: httpx.Response(429)).complete(
                HELLO, MODELS["claude-sonnet-5"], max_tokens=10, temperature=0
            )

    def test_a_rejected_key_is_not_configured_rather_than_a_failure(self) -> None:
        with pytest.raises(NotConfigured):
            _anthropic(lambda r: httpx.Response(401)).complete(
                HELLO, MODELS["claude-sonnet-5"], max_tokens=10, temperature=0
            )

    def test_a_missing_key_says_which_variable_to_set(self) -> None:
        with pytest.raises(NotConfigured, match="QEVIK_ANTHROPIC_API_KEY"):
            AnthropicProvider().complete(
                HELLO, MODELS["claude-sonnet-5"], max_tokens=10, temperature=0
            )

    def test_an_error_never_echoes_the_body(self) -> None:
        """Provider errors echo the request, which here is the prompt."""
        from atlas_kernel.llm.models import LLMError

        handler = lambda r: httpx.Response(400, text="prompt was: SECRET-PROMPT-TEXT")  # noqa: E731
        with pytest.raises(LLMError) as raised:
            _anthropic(handler).complete(
                HELLO, MODELS["claude-sonnet-5"], max_tokens=10, temperature=0
            )
        assert "SECRET-PROMPT-TEXT" not in str(raised.value)

    def test_a_compatible_provider_without_a_base_url_says_so(self) -> None:
        with pytest.raises(NotConfigured, match="base_url"):
            _compatible(_openai_ok).complete(
                HELLO, MODELS["qwen3-72b"], max_tokens=10, temperature=0
            )


class TestDefaults:
    def test_a_provider_without_a_key_is_not_registered(self) -> None:
        """Registering one whose credential is absent turns a clear error at
        call time into a silent selection of a model that cannot run, which
        surfaces later and further from the cause."""
        assert default_registry().models == []

    def test_qwen_takes_routine_work_and_claude_stays_for_the_rest(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The entire reason for a registry rather than a hard-coded client.
        Qwen is roughly two orders of magnitude cheaper for a draft."""
        monkeypatch.setenv("QEVIK_DASHSCOPE_API_KEY", "x")
        monkeypatch.setenv("QEVIK_ANTHROPIC_API_KEY", "y")
        registry = default_registry()

        assert registry.resolve().name == "qwen-turbo"
        assert registry.resolve(preferred="claude-opus-5").name == "claude-opus-5"
        assert (
            MODELS["qwen-turbo"].cost_usd(20_000, 4_000)
            < MODELS["claude-opus-5"].cost_usd(20_000, 4_000) / 100
        )

    def test_claude_alone_still_works(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("QEVIK_ANTHROPIC_API_KEY", "y")
        assert {m.name for m in default_registry().models} == {
            "claude-sonnet-5",
            "claude-opus-5",
        }

    def test_qwen_cloud_and_self_hosted_are_both_declared(self) -> None:
        """Cloud today; the Z8 later, at zero cost per token."""
        assert {"qwen-turbo", "qwen-plus", "qwen-max"} <= set(MODELS)
        assert MODELS["qwen3-72b"].input_cost_per_mtok == 0.0
        assert "deepseek-chat" in MODELS
