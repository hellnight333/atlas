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
    """What a model is being chosen for. §8's list."""

    PLANNING = "planning"
    IMPLEMENTATION = "implementation"
    REVIEW = "review"
    SUMMARISATION = "summarisation"
    RESEARCH = "research"
    CHEAP = "cheap"


#: Which credential each provider family draws on. The provider id is the same
#: one `integrations.registry` uses, so the Credential Center and the model
#: registry name the same thing.
PROVIDER_CREDENTIAL: dict[str, str] = {
    "qwen": "qwen",
    "anthropic": "anthropic",
    "openai": "openai",
    "deepseek": "deepseek",
}

#: Models grouped by the provider that serves them.
PROVIDER_MODELS: dict[str, tuple[str, ...]] = {
    "qwen": ("qwen-turbo", "qwen-plus", "qwen-max"),
    "anthropic": ("claude-sonnet-5", "claude-opus-5"),
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
        adapter = (AnthropicProvider() if provider == "anthropic"
                   else OpenAICompatibleProvider(name=provider,
                                                 key_env=f"{provider.upper()}_API_KEY"))
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
