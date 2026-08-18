"""Providers. Claude today; Qwen and DeepSeek register the same way.

Two shapes cover the field. Anthropic has its own request format; almost
everything else — Qwen, DeepSeek, vLLM, Ollama, OpenRouter — speaks the
OpenAI chat-completions format. So there are two adapters rather than one per
vendor, and adding DeepSeek is a ``ModelSpec`` with a ``base_url``, not a class.

No SDKs. ``httpx`` against the documented endpoints, for the same reason the
Google OAuth flow is hand-rolled: Qevik ships as a packaged binary and vendor
SDKs are a reliable source of packaging breakage, for what is one HTTP call.
"""

from __future__ import annotations

import os
import time
from typing import Protocol, runtime_checkable

import httpx

from .models import Completion, LLMError, Message, ModelSpec, NotConfigured, RateLimited, Role

ANTHROPIC_ENDPOINT = "https://api.anthropic.com/v1/messages"

#: Qwen's OpenAI-compatible endpoint.
#:
#: The shared international host is the default; the mainland host differs, and
#: picking the wrong one fails as an auth error rather than as a routing error,
#: which is a confusing afternoon.
#:
#: **Overridable, because a Model Studio workspace gets its own host** — a
#: dedicated endpoint like ``ws-<id>.<region>.maas.aliyuncs.com`` serves that
#: workspace's key and rejects it anywhere else. Hard-coding the shared host
#: turns a correct key into a 401 that reads exactly like a wrong one, and that
#: mistake has now cost time twice.
DEFAULT_QWEN_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"


def qwen_base_url() -> str:
    """The Qwen endpoint, from the environment when a workspace host is set.

    Reads the environment directly rather than through ``_env``, which is
    defined further down this module: this runs at import time, and a helper
    that does not exist yet is a NameError rather than a default.
    """
    for prefix in ("QEVIK_", "ATLAS_", ""):
        value = os.environ.get(f"{prefix}DASHSCOPE_BASE_URL", "")
        if value.strip():
            return value.strip().rstrip("/")
    return DEFAULT_QWEN_BASE_URL


QWEN_BASE_URL = qwen_base_url()
ANTHROPIC_VERSION = "2023-06-01"
REQUEST_TIMEOUT_SECONDS = 180.0

#: Prefixes accepted for every credential, so the rename does not break a
#: machine that is already configured.
_PREFIXES = ("QEVIK_", "ATLAS_", "")


def _env(name: str) -> str | None:
    for prefix in _PREFIXES:
        value = os.environ.get(f"{prefix}{name}")
        if value and value.strip():
            return value.strip()
    return None


@runtime_checkable
class LLMProvider(Protocol):
    """Generates text. Knows nothing about what Qevik wants it for."""

    @property
    def name(self) -> str: ...

    def complete(
        self, messages: list[Message], spec: ModelSpec, *, max_tokens: int, temperature: float
    ) -> Completion: ...


def _split_system(messages: list[Message]) -> tuple[str, list[Message]]:
    """Anthropic takes the system prompt as a separate field, not as a turn."""
    system = "\n\n".join(m.content for m in messages if m.role is Role.SYSTEM)
    rest = [m for m in messages if m.role is not Role.SYSTEM]
    return system, rest


class AnthropicProvider:
    """Claude."""

    def __init__(self, *, key: str | None = None, client: httpx.Client | None = None) -> None:
        self._key = key
        self._client = client
        self._owns_client = client is None

    @property
    def name(self) -> str:
        return "anthropic"

    def _api_key(self) -> str:
        key = self._key or _env("ANTHROPIC_API_KEY")
        if not key:
            raise NotConfigured(
                "no Anthropic key. Set QEVIK_ANTHROPIC_API_KEY (or ANTHROPIC_API_KEY)."
            )
        return key

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS)
        return self._client

    def close(self) -> None:
        if self._client is not None and self._owns_client:
            self._client.close()
            self._client = None

    def complete(
        self,
        messages: list[Message],
        spec: ModelSpec,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> Completion:
        system, turns = _split_system(messages)
        payload: dict[str, object] = {
            "model": spec.id,
            "max_tokens": min(max_tokens, spec.max_output_tokens),
            "temperature": temperature,
            "messages": [{"role": m.role.value, "content": m.content} for m in turns],
        }
        if system:
            payload["system"] = system

        started = time.monotonic()
        try:
            response = self._get_client().post(
                ANTHROPIC_ENDPOINT,
                headers={
                    "x-api-key": self._api_key(),
                    "anthropic-version": ANTHROPIC_VERSION,
                    "content-type": "application/json",
                },
                json=payload,
            )
        except httpx.HTTPError as error:
            raise LLMError(f"could not reach Anthropic: {error}") from error

        _raise_for_status(response, "Anthropic")
        body = response.json()
        text = "".join(
            block.get("text", "")
            for block in body.get("content", [])
            if block.get("type") == "text"
        )
        usage = body.get("usage", {})
        return _completion(
            text=text,
            spec=spec,
            provider=self.name,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            stop_reason=body.get("stop_reason", ""),
            started=started,
        )


class OpenAICompatibleProvider:
    """Qwen, DeepSeek, vLLM, Ollama, OpenRouter — anything speaking chat-completions.

    One adapter rather than one per vendor. They differ in the URL and the
    credential, both of which are configuration, so a new provider is a
    ``ModelSpec`` and an environment variable.
    """

    def __init__(
        self,
        *,
        name: str,
        key_env: str,
        key: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._name = name
        self._key_env = key_env
        self._key = key
        self._client = client
        self._owns_client = client is None

    @property
    def name(self) -> str:
        return self._name

    def _api_key(self) -> str:
        # A self-hosted endpoint often needs no key at all, so an empty string
        # is a valid configuration rather than an error.
        return self._key or _env(self._key_env) or ""

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS)
        return self._client

    def close(self) -> None:
        if self._client is not None and self._owns_client:
            self._client.close()
            self._client = None

    def complete(
        self,
        messages: list[Message],
        spec: ModelSpec,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> Completion:
        if not spec.base_url:
            raise NotConfigured(
                f"{self._name} needs a base_url on the ModelSpec (for example http://host:8000/v1)"
            )
        headers = {"content-type": "application/json"}
        if key := self._api_key():
            headers["authorization"] = f"Bearer {key}"

        started = time.monotonic()
        try:
            response = self._get_client().post(
                f"{spec.base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json={
                    "model": spec.id,
                    "max_tokens": min(max_tokens, spec.max_output_tokens),
                    "temperature": temperature,
                    "messages": [{"role": m.role.value, "content": m.content} for m in messages],
                    **spec.options,
                },
            )
        except httpx.HTTPError as error:
            raise LLMError(f"could not reach {self._name}: {error}") from error

        _raise_for_status(response, self._name)
        body = response.json()
        choice = (body.get("choices") or [{}])[0]
        usage = body.get("usage", {})
        return _completion(
            text=(choice.get("message") or {}).get("content", "") or "",
            spec=spec,
            provider=self._name,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            stop_reason=choice.get("finish_reason", ""),
            started=started,
        )


def _raise_for_status(response: httpx.Response, provider: str) -> None:
    """Map a failure to something a caller can act on.

    Rate limiting is separated because it is the only retryable one, and the
    body is never surfaced: provider errors echo the request, which for this
    capability is the prompt.
    """
    if response.status_code == 429:
        raise RateLimited(f"{provider} rate-limited the request (429)")
    if response.status_code in (401, 403):
        raise NotConfigured(f"{provider} rejected the credentials ({response.status_code})")
    if response.status_code >= 400:
        raise LLMError(f"{provider} refused the request ({response.status_code})")


def _completion(
    *,
    text: str,
    spec: ModelSpec,
    provider: str,
    input_tokens: int,
    output_tokens: int,
    stop_reason: str,
    started: float,
) -> Completion:
    return Completion(
        text=text,
        model=spec.id,
        provider=provider,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=spec.cost_usd(input_tokens, output_tokens),
        stop_reason=stop_reason,
        latency_ms=int((time.monotonic() - started) * 1000),
    )


#: Registered models. Claude is in use; the others are declared so adding them
#: later is configuration rather than code. Costs are indicative and the
#: provider's published rates are authoritative.
MODELS: dict[str, ModelSpec] = {
    "claude-opus-5": ModelSpec(
        id="claude-opus-5",
        provider="anthropic",
        context_tokens=200_000,
        max_output_tokens=32_000,
        input_cost_per_mtok=15.0,
        output_cost_per_mtok=75.0,
        supports_tools=True,
        supports_json=True,
        supports_vision=True,
    ),
    "claude-sonnet-5": ModelSpec(
        id="claude-sonnet-5",
        provider="anthropic",
        context_tokens=200_000,
        max_output_tokens=64_000,
        input_cost_per_mtok=3.0,
        output_cost_per_mtok=15.0,
        supports_tools=True,
        supports_json=True,
        supports_vision=True,
    ),
    # Qwen's hosted API, OpenAI-compatible, pay as you go. Roughly an order of
    # magnitude cheaper than Claude for routine work, which is the point:
    # the registry picks the cheapest model that meets the stated requirements,
    # so drafting and extraction land here and only the hard jobs reach Claude.
    #
    # Rates are indicative. The provider's published pricing is authoritative
    # and changes without asking us.
    "qwen-turbo": ModelSpec(
        id="qwen-turbo",
        provider="qwen",
        base_url=QWEN_BASE_URL,
        context_tokens=1_000_000,
        max_output_tokens=8_192,
        input_cost_per_mtok=0.05,
        output_cost_per_mtok=0.20,
        supports_tools=True,
        supports_json=True,
    ),
    "qwen-plus": ModelSpec(
        id="qwen-plus",
        provider="qwen",
        base_url=QWEN_BASE_URL,
        context_tokens=1_000_000,
        max_output_tokens=32_768,
        input_cost_per_mtok=0.40,
        output_cost_per_mtok=1.20,
        supports_tools=True,
        supports_json=True,
        supports_vision=True,
    ),
    "qwen-max": ModelSpec(
        id="qwen-max",
        provider="qwen",
        base_url=QWEN_BASE_URL,
        context_tokens=262_144,
        max_output_tokens=32_768,
        input_cost_per_mtok=1.60,
        output_cost_per_mtok=6.40,
        supports_tools=True,
        supports_json=True,
    ),
    # Self-hosted. Declared for when the Z8 becomes a worker; costs nothing per
    # token, so the registry will prefer it over everything above.
    "qwen3-72b": ModelSpec(
        id="qwen3-72b",
        provider="qwen",
        base_url=None,
        context_tokens=128_000,
        max_output_tokens=8_192,
        supports_tools=True,
        supports_json=True,
    ),
    "deepseek-chat": ModelSpec(
        id="deepseek-chat",
        provider="deepseek",
        base_url="https://api.deepseek.com/v1",
        context_tokens=64_000,
        max_output_tokens=8_192,
        input_cost_per_mtok=0.27,
        output_cost_per_mtok=1.10,
        supports_tools=True,
        supports_json=True,
    ),
}
