"""The knowledge layer's first piece, and the two facts that shape it.

Both measured against NVIDIA's hosted catalogue on 2026-09-04:

* two embedding models answer at `/v1/embeddings` — `nemotron-3-embed-1b` at
  200 ms and `llama-nemotron-embed-vl-1b-v2` at 174 ms, both 2048 dimensions;
  six others in the same catalogue answer 404 there;
* reranking is gone. The documented endpoint answers `410 Gone — reached its
  end of life on 2026-05-18` and no replacement path works. So there is no
  rerank capability here, which is a finding rather than an omission.

The terms carry over from text unchanged, and for a sharper reason: an
embedding index is built once and queried for years. Indexing a customer's
documents through a provider entitled to train on them is not a mistake anybody
notices later.
"""

from __future__ import annotations

import httpx
import pytest

from atlas_kernel.llm.embeddings import (
    EMBEDDINGS,
    EmbeddingRegistry,
    EmbeddingSpec,
    NoEmbedderAvailable,
    OpenAICompatibleEmbedder,
    default_registry,
)
from atlas_kernel.llm.models import LLMError, NotConfigured, Terms, Unreachable

SPEC = EMBEDDINGS["nvidia/nemotron-3-embed-1b"]
PAID = EmbeddingSpec(id="paid/embed", provider="paid",
                     base_url="https://example.invalid/v1", dimensions=2048,
                     input_cost_per_mtok=0.02)


def _embedder(handler) -> OpenAICompatibleEmbedder:
    return OpenAICompatibleEmbedder(
        name="nvidia", key_env="X", key="k",
        client=httpx.Client(transport=httpx.MockTransport(handler)))


def _vectors(n: int, dimensions: int = 2048, *, shuffle: bool = False):
    order = list(range(n))
    if shuffle:
        order.reverse()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "data": [{"index": i, "embedding": [float(i)] * dimensions}
                     for i in order],
            "usage": {"prompt_tokens": 7}})
    return handler


class TestEmbedding:
    def test_vectors_come_back_with_their_provenance(self) -> None:
        result = _embedder(_vectors(2)).embed(["a", "b"], SPEC)
        assert result.dimensions == 2048
        assert result.model == SPEC.id and result.provider == "nvidia"
        assert result.input_tokens == 7
        assert result.latency_ms >= 0

    def test_vectors_are_ordered_by_the_providers_index(self) -> None:
        """A batch that came back reordered would attach every vector to the
        wrong text, and nothing downstream could notice — the index would be
        silently, permanently wrong."""
        result = _embedder(_vectors(3, shuffle=True)).embed(["a", "b", "c"], SPEC)
        assert [v[0] for v in result.vectors] == [0.0, 1.0, 2.0]

    def test_an_empty_batch_costs_nothing_and_asks_nothing(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("an empty batch must not reach the provider")

        assert _embedder(handler).embed([], SPEC).vectors == ()

    def test_a_short_reply_is_refused_rather_than_guessed(self) -> None:
        """Which text is the missing vector for? There is no safe answer, so
        there is no answer."""
        with pytest.raises(LLMError, match="Refusing rather than guessing"):
            _embedder(_vectors(2)).embed(["a", "b", "c"], SPEC)

    def test_an_unexpected_width_is_caught_here(self) -> None:
        """A store built for 2048 cannot hold 1024, and the cheapest place to
        discover that is before anything is stored."""
        with pytest.raises(LLMError, match="dimensions"):
            _embedder(_vectors(1, dimensions=1024)).embed(["a"], SPEC)

    def test_a_batch_over_the_limit_is_refused_at_the_boundary(self) -> None:
        with pytest.raises(LLMError, match="Batch upstream"):
            _embedder(_vectors(1)).embed(["x"] * 500, SPEC)

    def test_unreachable_is_not_a_refusal(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("disconnected")

        with pytest.raises(Unreachable):
            _embedder(handler).embed(["a"], SPEC)

    def test_a_missing_key_says_which_one(self) -> None:
        embedder = OpenAICompatibleEmbedder(name="nvidia", key_env="NOT_SET_X")
        with pytest.raises(NotConfigured, match="NOT_SET_X"):
            embedder.embed(["a"], SPEC)

    def test_the_purpose_reaches_the_provider(self) -> None:
        """Providers that distinguish a stored passage from a search query
        score materially better when told which this is."""
        seen: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            seen.append(json.loads(request.content))
            return _vectors(1)(request)

        _embedder(handler).embed(["a"], SPEC, purpose="query")
        assert seen[0]["input_type"] == "query"


class TestTheLicenceAppliesHereToo:
    def _both(self) -> EmbeddingRegistry:
        registry = EmbeddingRegistry()
        registry.register(_embedder(_vectors(1)), SPEC)      # evaluation only
        registry.register(_embedder(_vectors(1)), PAID)      # production
        return registry

    def test_a_paid_model_is_chosen_over_a_free_forbidden_one(self) -> None:
        assert self._both().resolve()[1].id == "paid/embed"

    def test_evaluating_reaches_the_free_one(self) -> None:
        assert self._both().resolve(evaluating=True)[1].terms is (
            Terms.EVALUATION_ONLY)

    def test_naming_it_is_still_refused(self) -> None:
        with pytest.raises(NoEmbedderAvailable, match="evaluation only"):
            self._both().resolve(preferred=SPEC.id)

    def test_only_forbidden_models_refuses_and_says_what_is_needed(self) -> None:
        """An index is built once and queried for years. Quietly using the free
        tier for a customer's documents is not a mistake anybody notices."""
        registry = EmbeddingRegistry()
        registry.register(_embedder(_vectors(1)), SPEC)
        with pytest.raises(NoEmbedderAvailable, match="terms permit it"):
            registry.resolve()

    def test_every_nvidia_embedding_model_is_evaluation_only(self) -> None:
        for spec in EMBEDDINGS.values():
            assert spec.terms is Terms.EVALUATION_ONLY, spec.id

    def test_nothing_registers_without_a_key(self, monkeypatch) -> None:
        for prefix in ("QEVIK_", "ATLAS_", ""):
            monkeypatch.delenv(f"{prefix}NVIDIA_API_KEY", raising=False)
        assert default_registry().models == []


def test_there_is_no_rerank_capability_and_that_is_deliberate() -> None:
    """The documented endpoint answers 410 Gone — end of life 2026-05-18 — and
    no replacement path works on this key. Declaring a capability that cannot
    be reached is how a caller ends up handling an error it was told could not
    happen."""
    import inspect

    from atlas_kernel.llm import embeddings

    source = inspect.getsource(embeddings)
    assert "410 Gone" in source, (
        "the reason there is no reranker is not written down, so the next "
        "person will add one and find out the same way")
    assert "def rerank" not in source
    assert not any("rerank" in name for name in embeddings.EMBEDDINGS)
