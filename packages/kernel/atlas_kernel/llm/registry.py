"""Which provider serves ``text.generate``.

Same shape as the media provider registry and the deployment target registry,
for the same reason: choosing a model becomes a registration and a policy rather
than a code change, so adding Qwen or DeepSeek later touches configuration only.

Selection is cost-aware and capability-aware. A caller asks for what it needs —
tool use, a context size, a spend ceiling — and gets the cheapest model that can
do it. Nothing in Qevik names a vendor.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Completion, LLMError, Message, ModelSpec
from .providers import LLMProvider


class NoModelAvailable(LLMError):
    """Nothing registered can serve the request.

    A configuration problem rather than a generation failure, so the message
    says which requirement excluded everything instead of "generation failed".
    """


@dataclass
class Registration:
    provider: LLMProvider
    spec: ModelSpec
    #: Preferred when nothing is named. Local/self-hosted first, matching the
    #: local-first rule the media registry already follows.
    is_local: bool = False
    labels: dict[str, str] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.spec.id


class ModelRegistry:
    """Registered models, and the policy for picking one."""

    def __init__(self) -> None:
        self._registrations: list[Registration] = []

    def register(self, registration: Registration) -> Registration:
        self._registrations = [r for r in self._registrations if r.name != registration.name]
        self._registrations.append(registration)
        return registration

    @property
    def models(self) -> list[Registration]:
        return list(self._registrations)

    def resolve(
        self,
        *,
        preferred: str | None = None,
        needs_tools: bool = False,
        needs_vision: bool = False,
        needs_json: bool = False,
        min_context: int = 0,
        max_cost_per_mtok: float | None = None,
    ) -> Registration:
        if not self._registrations:
            raise NoModelAvailable("no model registered for text.generate")

        if preferred is not None:
            for registration in self._registrations:
                if registration.name == preferred:
                    return registration
            known = ", ".join(sorted(r.name for r in self._registrations))
            raise NoModelAvailable(f"model {preferred!r} is not registered (known: {known})")

        candidates = [
            r
            for r in self._registrations
            if (not needs_tools or r.spec.supports_tools)
            and (not needs_vision or r.spec.supports_vision)
            and (not needs_json or r.spec.supports_json)
            and r.spec.context_tokens >= min_context
            and (max_cost_per_mtok is None or r.spec.input_cost_per_mtok <= max_cost_per_mtok)
        ]
        if not candidates:
            # Naming the constraints beats "no model available", which sends the
            # reader to look for a missing registration that is not missing.
            wanted = [
                name
                for name, on in (
                    ("tools", needs_tools),
                    ("vision", needs_vision),
                    ("json", needs_json),
                )
                if on
            ]
            raise NoModelAvailable(
                f"no registered model satisfies: {', '.join(wanted) or 'the request'}"
                + (f", context >= {min_context}" if min_context else "")
                + (f", cost <= ${max_cost_per_mtok}/Mtok" if max_cost_per_mtok else "")
            )

        # Local first, then cheapest. A self-hosted model costs nothing per
        # token, so this naturally prefers the Z8 once it exists.
        return sorted(
            candidates,
            key=lambda r: (not r.is_local, r.spec.input_cost_per_mtok, r.name),
        )[0]

    def complete(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,
        **requirements,
    ) -> Completion:
        """Generate, through whichever provider fits. Callers name no vendor."""
        registration = self.resolve(preferred=model, **requirements)
        return registration.provider.complete(
            messages, registration.spec, max_tokens=max_tokens, temperature=temperature
        )


def default_registry() -> ModelRegistry:
    """Whatever is configured, cheapest-capable first.

    A provider is registered only when its credential is present. Registering
    one without a key turns a clear NotConfigured at call time into a silent
    selection of a model that cannot run, which surfaces later and further from
    the cause.

    With both configured, routine work lands on Qwen and only jobs that ask for
    more reach Claude — which is the entire reason for a registry rather than a
    hard-coded client.
    """
    import os

    from .providers import MODELS, AnthropicProvider, OpenAICompatibleProvider

    def configured(name: str) -> bool:
        return any(os.environ.get(f"{p}{name}", "").strip() for p in ("QEVIK_", "ATLAS_", ""))

    registry = ModelRegistry()

    if configured("DASHSCOPE_API_KEY") or configured("QWEN_API_KEY"):
        qwen = OpenAICompatibleProvider(name="qwen", key_env="DASHSCOPE_API_KEY")
        # Every one of these was called against the configured workspace before
        # being listed here. A Model Studio workspace serves the models it has
        # been granted and 403s the rest, so a catalogue copied from the vendor's
        # documentation registers models this account cannot run — which the
        # cheapest-first policy then selects first, by construction.
        for name in ("qwen-turbo", "qwen-plus", "qwen-max", "qwen3-max",
                     "qwen3-coder-plus", "qwen-vl-plus", "qwen-vl-max"):
            registry.register(Registration(provider=qwen, spec=MODELS[name]))

    if configured("ANTHROPIC_API_KEY"):
        anthropic = AnthropicProvider()
        for name in ("claude-sonnet-5", "claude-opus-5"):
            registry.register(Registration(provider=anthropic, spec=MODELS[name]))

    return registry
