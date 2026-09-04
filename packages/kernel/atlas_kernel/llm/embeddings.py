"""Turning text into vectors, through the same shape everything else uses.

The `knowledge` layer needs three things: something to embed with, somewhere to
put the vectors, and something to rank results. This is the first. It is
deliberately small — a protocol, one adapter, and a registry that answers the
same question the text registry answers, so a caller asks for an embedding and
never names a vendor.

**Measured, not assumed.** Two models on NVIDIA's hosted catalogue answer at
`/v1/embeddings` — `nemotron-3-embed-1b` at 200 ms and
`llama-nemotron-embed-vl-1b-v2` at 174 ms, both 2048 dimensions. Six others in
the same catalogue answer 404. They had also appeared as REFUSED in the chat
survey, which was wrong of that survey rather than true of them: it asked them a
chat question. An endpoint mismatch is a fact about the caller.

**Reranking is not here, and that is a finding rather than an omission.** The
documented rerank endpoint answers `410 Gone — this endpoint has reached its end
of life on 2026-05-18` and no replacement path works on this key. A capability
that cannot be reached is not one to declare.

Terms carry over exactly as they do for text: NVIDIA's hosted models are
`EVALUATION_ONLY`, so they may index our own research and may not index a
customer's documents. See `models.Terms` and docs/qevik-docs/13_NVIDIA.md.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import httpx

from .models import LLMError, NotConfigured, Terms, Unreachable
from .providers import REQUEST_TIMEOUT_SECONDS, _env, _raise_for_status


class NoEmbedderAvailable(LLMError):
    """Nothing registered can turn text into vectors for this request."""


@dataclass(frozen=True)
class EmbeddingSpec:
    """One embedding model, and what it is allowed to be pointed at."""

    id: str
    provider: str
    base_url: str
    #: How many numbers come back. Recorded because a store built for one width
    #: cannot hold another, and discovering that at query time is expensive.
    dimensions: int
    #: Some providers distinguish the thing being stored from the thing being
    #: searched for, and get materially better results when told which.
    supports_input_type: bool = True
    max_batch: int = 64
    input_cost_per_mtok: float = 0.0
    terms: Terms = Terms.PRODUCTION


@dataclass(frozen=True)
class Embeddings:
    """Vectors, and where they came from."""

    vectors: tuple[tuple[float, ...], ...]
    model: str
    provider: str
    input_tokens: int = 0
    latency_ms: int = 0

    @property
    def dimensions(self) -> int:
        return len(self.vectors[0]) if self.vectors else 0


@runtime_checkable
class Embedder(Protocol):
    """Embeds text. Knows nothing about what the vectors are for."""

    @property
    def name(self) -> str: ...

    def embed(self, texts: list[str], spec: EmbeddingSpec, *,
              purpose: str = "passage") -> Embeddings: ...


@dataclass
class OpenAICompatibleEmbedder:
    """Anything speaking `POST /v1/embeddings` — NVIDIA, OpenAI, a local NIM.

    One adapter, for the same reason there is one chat adapter: they differ in
    the URL and the credential, both of which are configuration.
    """

    name: str
    key_env: str
    key: str | None = None
    client: httpx.Client | None = field(default=None, repr=False)

    def _api_key(self) -> str:
        found = self.key or _env(self.key_env) or ""
        if not found:
            raise NotConfigured(
                f"no key for {self.name}. Set QEVIK_{self.key_env}.")
        return found

    def _get_client(self) -> httpx.Client:
        if self.client is None:
            self.client = httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS)
        return self.client

    def embed(self, texts: list[str], spec: EmbeddingSpec, *,
              purpose: str = "passage") -> Embeddings:
        """Embed a batch.

        `purpose` is "passage" for something being stored and "query" for
        something being searched for. Providers that make the distinction score
        materially better when told; the rest ignore it. Defaulting to "passage"
        is the safer way round — a query embedded as a passage still retrieves,
        where the reverse quietly degrades every stored vector.
        """
        if not texts:
            return Embeddings(vectors=(), model=spec.id, provider=spec.provider)
        if len(texts) > spec.max_batch:
            raise LLMError(
                f"{spec.id} takes {spec.max_batch} inputs at a time and was "
                f"given {len(texts)}. Batch upstream, where the caller knows "
                "what the texts are and can keep them in order.")

        payload: dict[str, object] = {
            "model": spec.id, "input": list(texts), "encoding_format": "float"}
        if spec.supports_input_type:
            payload["input_type"] = purpose

        started = time.monotonic()
        try:
            response = self._get_client().post(
                f"{spec.base_url.rstrip('/')}/embeddings",
                headers={"Authorization": f"Bearer {self._api_key()}",
                         "Content-Type": "application/json"},
                json=payload)
        except httpx.HTTPError as error:
            raise Unreachable(f"could not reach {self.name}: {error}") from error

        _raise_for_status(response, self.name)
        body = response.json()
        # Ordered by the provider's own index, never by arrival: a batch that
        # came back reordered would attach every vector to the wrong text, and
        # nothing downstream could notice.
        rows = sorted(body.get("data", []), key=lambda row: row.get("index", 0))
        vectors = tuple(tuple(float(x) for x in row["embedding"]) for row in rows)

        if len(vectors) != len(texts):
            raise LLMError(
                f"{spec.id} was given {len(texts)} inputs and returned "
                f"{len(vectors)} vectors. Refusing rather than guessing which "
                "text each one belongs to.")
        if vectors and len(vectors[0]) != spec.dimensions:
            # A store built for one width cannot hold another, and the cheapest
            # place to find that out is here.
            raise LLMError(
                f"{spec.id} is declared as {spec.dimensions} dimensions and "
                f"returned {len(vectors[0])}.")

        return Embeddings(
            vectors=vectors, model=spec.id, provider=spec.provider,
            input_tokens=(body.get("usage") or {}).get("prompt_tokens", 0),
            latency_ms=int((time.monotonic() - started) * 1000))


#: Where NVIDIA's hosted inference lives. Same host as the chat models.
from .providers import NVIDIA_BASE_URL  # noqa: E402

#: Embedding models, each one called at `/v1/embeddings` before being listed.
#: Six others in the same catalogue answer 404 there and are not here.
EMBEDDINGS: dict[str, EmbeddingSpec] = {
    "nvidia/nemotron-3-embed-1b": EmbeddingSpec(
        id="nvidia/nemotron-3-embed-1b", provider="nvidia",
        base_url=NVIDIA_BASE_URL, dimensions=2048,
        terms=Terms.EVALUATION_ONLY),
    # Vision-language: embeds images alongside text into the same space, which
    # is what makes "find the competitor page that looked like this" a query.
    "nvidia/llama-nemotron-embed-vl-1b-v2": EmbeddingSpec(
        id="nvidia/llama-nemotron-embed-vl-1b-v2", provider="nvidia",
        base_url=NVIDIA_BASE_URL, dimensions=2048,
        terms=Terms.EVALUATION_ONLY),
}


@dataclass
class EmbeddingRegistry:
    """Which embedder serves a request. Same policy as the text registry."""

    registrations: list[tuple[Embedder, EmbeddingSpec]] = field(
        default_factory=list)

    def register(self, embedder: Embedder, spec: EmbeddingSpec) -> None:
        self.registrations = [(e, s) for e, s in self.registrations
                              if s.id != spec.id]
        self.registrations.append((embedder, spec))

    @property
    def models(self) -> list[EmbeddingSpec]:
        return [spec for _, spec in self.registrations]

    def resolve(self, *, preferred: str = "", evaluating: bool = False
                ) -> tuple[Embedder, EmbeddingSpec]:
        """The cheapest embedder allowed to do this work.

        `evaluating` behaves exactly as it does for text, and for the same
        reason: the free tier is the cheapest thing here, so without it every
        customer document would be indexed through a provider whose terms
        forbid it and whose terms allow training on it.
        """
        if not self.registrations:
            raise NoEmbedderAvailable("no embedding model is registered")

        allowed = [(e, s) for e, s in self.registrations
                   if evaluating or s.terms is not Terms.EVALUATION_ONLY]
        if preferred:
            for embedder, spec in self.registrations:
                if spec.id == preferred:
                    if not evaluating and spec.terms is Terms.EVALUATION_ONLY:
                        raise NoEmbedderAvailable(
                            f"{preferred} is licensed for evaluation only and "
                            "this is not an evaluation")
                    return embedder, spec
            known = ", ".join(sorted(s.id for _, s in self.registrations))
            raise NoEmbedderAvailable(
                f"{preferred!r} is not registered (known: {known})")

        if not allowed:
            excluded = ", ".join(sorted(s.id for _, s in self.registrations))
            raise NoEmbedderAvailable(
                "every registered embedding model is licensed for evaluation "
                f"only: {excluded}. Indexing customer documents needs a model "
                "whose terms permit it.")
        return sorted(allowed, key=lambda pair: (pair[1].input_cost_per_mtok,
                                                 pair[1].id))[0]


def default_registry() -> EmbeddingRegistry:
    """Whatever is configured. A provider with no key is not registered."""
    import os

    registry = EmbeddingRegistry()
    if any(os.environ.get(f"{p}NVIDIA_API_KEY", "").strip()
           for p in ("QEVIK_", "ATLAS_", "")):
        embedder = OpenAICompatibleEmbedder(name="nvidia",
                                            key_env="NVIDIA_API_KEY")
        for spec in EMBEDDINGS.values():
            registry.register(embedder, spec)
    return registry


__all__ = ["EMBEDDINGS", "Embedder", "Embeddings", "EmbeddingRegistry",
           "EmbeddingSpec", "NoEmbedderAvailable", "OpenAICompatibleEmbedder",
           "default_registry"]
