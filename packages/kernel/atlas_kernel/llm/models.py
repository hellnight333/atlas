"""One shape for every model provider.

Claude is the provider in use. Qwen and DeepSeek are expected, so the fields
they need exist now rather than being retrofitted into a shape built around one
vendor's API — retrofitting is how a "provider layer" ends up with Anthropic's
parameter names and a translation layer for everyone else.

What differs between these providers, and is therefore modelled generically:

* **Where they live.** Claude is a hosted API; Qwen and DeepSeek are commonly
  self-hosted or OpenAI-compatible. ``base_url`` is a first-class field, not an
  override.
* **How they are billed.** Per-token, at different rates for input and output,
  and self-hosted models cost nothing per token. Cost is computed from the
  provider's own rates rather than assumed.
* **What they support.** Tool use, JSON mode and vision are not universal.
  Declared, so a caller can select on capability instead of on a name.
* **Context and output limits.** Different by an order of magnitude.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

#: The capability. Asked for by name.
TEXT_GENERATE = "text.generate"


def _now() -> datetime:
    return datetime.now(UTC)


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class Message(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Role
    content: str


class ModelSpec(BaseModel):
    """One model, described in terms every provider can answer.

    ``id`` is the provider's own model name and is passed through untouched.
    Everything else is Qevik's vocabulary.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    provider: str
    #: For self-hosted or OpenAI-compatible endpoints. Claude leaves it unset.
    base_url: str | None = None
    context_tokens: int = 128_000
    max_output_tokens: int = 8_192
    #: USD per million tokens. Zero for a model running on hardware already
    #: paid for, which is the point of keeping the field rather than assuming
    #: everything is billed.
    input_cost_per_mtok: float = 0.0
    output_cost_per_mtok: float = 0.0
    supports_tools: bool = False
    supports_json: bool = False
    supports_vision: bool = False
    #: Free-form provider extras — Qwen's `enable_thinking`, DeepSeek's
    #: `reasoning_effort`. Kept opaque so a new provider needs no schema change.
    options: dict[str, Any] = Field(default_factory=dict)

    def cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        return round(
            input_tokens / 1_000_000 * self.input_cost_per_mtok
            + output_tokens / 1_000_000 * self.output_cost_per_mtok,
            6,
        )


class Completion(BaseModel):
    """What came back, and what it cost.

    Records the model *and* its provider, because "which model wrote this" is a
    provenance question the artifact system asks and a bare string cannot
    answer once two providers serve similar model names.
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: f"cmpl-{uuid4().hex[:12]}")
    text: str
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    #: Why generation stopped. "length" and "stop" mean different things to a
    #: caller deciding whether the answer is complete.
    stop_reason: str = ""
    latency_ms: int = 0
    created_at: datetime = Field(default_factory=_now)

    @property
    def truncated(self) -> bool:
        """Whether the model ran out of room rather than finished.

        Worth its own property: a truncated JSON response is invalid rather
        than short, and callers get this wrong when they only check the text.
        """
        return self.stop_reason in ("max_tokens", "length")


class LLMError(RuntimeError):
    """Generation failed."""


class NotConfigured(LLMError):
    """No credentials for this provider. Its own type so the fix is obvious."""


class RateLimited(LLMError):
    """Provider throttled the request. Retryable, unlike the others."""


class Unaffordable(LLMError):
    """The account cannot pay for this model right now.

    Its own type because the fix is neither a retry nor a new key, and both of
    the generic answers send the reader somewhere useless. A valid Anthropic key
    with an empty balance answers HTTP 400, which mapped to "refused the request
    (400)" and reads exactly like a malformed payload — an afternoon spent
    reading a prompt that was always fine. An Aliyun workspace that has not
    purchased a model answers 403, which mapped to "rejected the credentials"
    and sends the reader to rotate a key that works.

    Distinguishing this from :class:`NotConfigured` is the whole point: one is
    "there is no key", this one is "the key is good and the wallet is not".
    """
