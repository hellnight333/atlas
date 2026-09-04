"""Building a model registry from stored credentials rather than the environment.

§8 asks that changing which model runs a task require no source change. The
existing `ModelRegistry` already routes by capability and cost; what it could
not do was get its keys from anywhere but `os.environ`, which is exactly the
failure the vault exists to fix — a key that lives in a shell dies with it.

`registry_for` builds the same registry from a tenant's stored credentials. A
provider whose credential is missing, disabled or unverified is simply not
registered, so `resolve()` raises `NoModelAvailable` rather than selecting a
model that cannot run. That is the same choice `default_registry` already makes
about absent environment variables, applied to a different source of truth.

Roles come from §8's list: planning, implementation, review, summarisation,
research and cheap background work may each name a different model. The
selection is data, so a person changes it in the Credential Center.
"""

from __future__ import annotations

import logging
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from ..llm.models import ModelSpec
from ..llm.providers import MODELS, AnthropicProvider, OpenAICompatibleProvider
from ..llm.registry import ModelRegistry, Registration
from ..opportunity.tenancy import TenantId
from .service import CredentialService, Status

log = logging.getLogger(__name__)


class Role(StrEnum):
    """What a model is being chosen for.

    §8's list, extended for media. Extended here rather than given a registry of
    its own: an image provider is a model chosen for a role, and a second
    registry of "media models" beside this one is how an invocation ends up
    recorded against something that never saw the request.

    The media roles have no provider yet. They exist so the fabric can express
    an image agent without inventing a parallel vocabulary for it.
    """

    PLANNING = "planning"
    IMPLEMENTATION = "implementation"
    REVIEW = "review"
    SUMMARISATION = "summarisation"
    RESEARCH = "research"
    CHEAP = "cheap"
    IMAGE = "image"
    VIDEO = "video"


#: Which credential each provider family draws on. The provider id is the same
#: one `integrations.registry` uses, so the Credential Center and the model
#: registry name the same thing.
PROVIDER_CREDENTIAL: dict[str, str] = {
    "qwen": "qwen",
    "nvidia": "nvidia",
    "anthropic": "anthropic",
    "openai": "openai",
    "deepseek": "deepseek",
}

#: Models grouped by the provider that serves them.
PROVIDER_MODELS: dict[str, tuple[str, ...]] = {
    # Kept in step with `llm.registry.default_registry`, and for the same
    # reason: every one of these was called against the configured workspace
    # before being listed. A model the account cannot run is one the
    # cheapest-first policy selects first.
    "qwen": ("qwen-turbo", "qwen-plus", "qwen-max", "qwen3-max",
             "qwen3-coder-plus", "qwen-vl-plus", "qwen-vl-max"),
    "anthropic": ("claude-sonnet-5", "claude-opus-5"),
    # Evaluation only — see `llm.models.Terms` and docs/qevik-docs/13_NVIDIA.md.
    # Listed here so the Credential Centre and the Models page can show them;
    # `ModelRegistry.resolve` is what stops one being selected for real work.
    "nvidia": ("nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
               "nvidia/nemotron-3.5-lightning-30b-a3b",
               "nvidia/nemotron-3-super-120b-a12b",
               "nvidia/nemotron-3-ultra-550b-a55b",
               "openai/gpt-oss-20b", "moonshotai/kimi-k3",
               "minimaxai/minimax-m3", "poolside/laguna-xs-2.1",
               "deepseek-ai/deepseek-v4-flash-0731",
               "google/gemma-4-31b-it",
               "meta/llama-3.2-11b-vision-instruct"),
}


class Selection(BaseModel):
    """Which model runs which role. Data, so changing it is not a code change."""

    model_config = ConfigDict(frozen=True)

    #: role -> model id. A role with no entry falls to the registry's own
    #: cheapest-capable choice, which is a reasonable default and not a silent
    #: one: `chosen_for` reports which happened.
    by_role: dict[str, str] = {}

    def for_role(self, role: Role) -> str:
        return self.by_role.get(role.value, "")


def registry_for(credentials: CredentialService, *, tenant: TenantId | None,
                 include_environment: bool = False) -> ModelRegistry:
    """A registry built from this tenant's stored, usable credentials.

    A provider is registered only when its credential is stored *and* enabled
    *and* not known-invalid. Registering one that cannot run turns a clear
    refusal at selection time into a confusing provider error later, further
    from the cause — the same reasoning `default_registry` gives.
    """
    registry = ModelRegistry()

    for provider, credential in PROVIDER_CREDENTIAL.items():
        record = credentials.record(provider=credential, tenant=tenant)
        if record is None:
            continue
        # PENDING_CREDENTIAL is allowed: stored but never tested is a usable
        # key that nobody has exercised yet, and refusing it would mean a
        # credential could only ever be proven by a test that needs it.
        if record.status in {Status.DISABLED, Status.INVALID_CREDENTIAL,
                             Status.INSUFFICIENT_PERMISSION}:
            log.info("model registry: skipping %s (%s)", provider,
                     record.status.value)
            continue

        names = PROVIDER_MODELS.get(provider, ())
        if not names:
            continue

        # The stored secret, handed to the adapter.
        #
        # This is the one thing this module exists to do, and it did not do it:
        # the adapters were built with a `key_env` and no key, so they read
        # `os.environ` exactly as before while the vault decided only *whether*
        # to register them. A deployment could have a credential stored, enabled
        # and verified, and still fail every call because the shell that started
        # the process had no matching variable — the failure this file's own
        # docstring describes as the reason it was written.
        try:
            secret = credentials.resolve(provider=credential, tenant=tenant)
        except Exception as failure:            # noqa: BLE001 - see below
            # Never the key material, and never a traceback that might carry it.
            log.info("model registry: skipping %s (%s)", provider,
                     type(failure).__name__)
            continue
        if not secret:
            continue

        adapter = (AnthropicProvider(key=secret) if provider == "anthropic"
                   else OpenAICompatibleProvider(
                       name=provider, key_env=f"{provider.upper()}_API_KEY",
                       key=secret))
        # `key_env` stays as the shape the adapter wants, but `key` is set, so
        # it is never consulted. Leaving it lets a self-hosted endpoint with no
        # stored credential keep working the way it always has.
        for name in names:
            if name in MODELS:
                registry.register(Registration(provider=adapter, spec=MODELS[name]))

    if include_environment and not registry.models:
        # A deliberate, narrow fallback for local development, and off by
        # default: silently preferring an environment variable would make the
        # vault optional, which is how the old failure returns.
        from ..llm.registry import default_registry

        return default_registry()
    return registry


def chosen_for(registry: ModelRegistry, selection: Selection, role: Role
               ) -> tuple[ModelSpec | None, str]:
    """The model for a role, and how it was chosen.

    Returns the reason as well as the model so a report can say "selected" or
    "defaulted" rather than presenting a fallback as a decision somebody made.
    """
    preferred = selection.for_role(role)
    if preferred:
        for registration in registry.models:
            if registration.name == preferred:
                return registration.spec, "selected"
        return None, f"{preferred} is selected for {role.value} but not available"
    if not registry.models:
        return None, "no model is registered"
    return registry.resolve().spec, "defaulted to the registry's preference"
