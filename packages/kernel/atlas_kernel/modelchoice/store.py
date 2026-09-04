"""The stored answer to "which model runs which role", per tenant.

Kept beside the registry rather than inside it, because they answer different
questions and fail differently. The registry answers "what could run" and is
derived from credentials — it changes when a key is added or a provider starts
refusing. The selection answers "what should run" and is a person's decision; it
must not silently change because a key expired.

That distinction produces the one rule here: **a selection naming a model the
registry cannot serve is reported, never quietly replaced.** Substituting the
next available model would run somebody's implementation work on a model they
did not pick, and the invocation record would name the substitute as though it
had been chosen.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from ..llm.models import Terms
from ..llm.providers import MODELS
from ..credentials.models import (
    PROVIDER_CREDENTIAL,
    PROVIDER_MODELS,
    Role,
    Selection,
    chosen_for,
    registry_for,
)
from ..credentials.service import CredentialService, Status
from ..opportunity.tenancy import TenantId
from ..opportunity.tenancy import require as _require_tenant


class Choice(BaseModel):
    """One role's model, and how it came to be that one."""

    model_config = ConfigDict(frozen=True)

    role: str
    model: str = ""
    provider: str = ""
    #: `selected` when a person chose it, `defaulted` when the registry did,
    #: or the reason nothing is available. Reported rather than collapsed to a
    #: model name, so a screen can distinguish a decision from a fallback.
    reason: str = ""
    available: bool = False


class SelectionStore:
    """Per-tenant selections. In memory; a deployment may back it elsewhere.

    Deliberately not merged into `CredentialService`. A selection is not a
    secret, is safe to show, and survives a credential being rotated or removed
    — coupling their lifetimes would delete a person's choices when they
    replaced a key.
    """

    def __init__(self) -> None:
        self._by_tenant: dict[str, Selection] = {}

    def get(self, *, tenant: TenantId | None) -> Selection:
        tenant = _require_tenant(tenant, method="modelchoice.get")
        return self._by_tenant.get(str(tenant), Selection())

    def set_role(self, *, tenant: TenantId | None, role: Role, model: str
                 ) -> Selection:
        """Choose a model for one role, or clear it with an empty string."""
        tenant = _require_tenant(tenant, method="modelchoice.set_role")
        current = dict(self.get(tenant=tenant).by_role)
        if model:
            current[role.value] = model
        else:
            current.pop(role.value, None)
        updated = Selection(by_role=current)
        self._by_tenant[str(tenant)] = updated
        return updated

    def clear(self, *, tenant: TenantId | None) -> Selection:
        tenant = _require_tenant(tenant, method="modelchoice.clear")
        self._by_tenant.pop(str(tenant), None)
        return Selection()


def available(credentials: CredentialService, *, tenant: TenantId | None
              ) -> list[dict]:
    """Every model this tenant could actually run, and every one it could not.

    Both halves, because a list of only the usable models cannot answer "why
    isn't Claude here" — and that question is the whole reason somebody opens
    this screen. A provider with no credential is listed with the credential it
    needs, which is the same string the Credential Centre uses.
    """
    tenant = _require_tenant(tenant, method="modelchoice.available")
    registry = registry_for(credentials, tenant=tenant)
    usable = {r.name for r in registry.models}

    rows = []
    for provider, models in sorted(PROVIDER_MODELS.items()):
        record = credentials.record(provider=provider, tenant=tenant)
        status = record.status if record else Status.NOT_CONFIGURED
        for model in models:
            spec = MODELS.get(model)
            # What the provider's licence permits. Surfaced beside the
            # credential status because they are two different reasons a model
            # cannot do a job, and only one of them is fixed by entering a key.
            evaluation_only = bool(
                spec is not None and spec.terms is Terms.EVALUATION_ONLY)
            rows.append({
                "model": model,
                "provider": provider,
                "credential": PROVIDER_CREDENTIAL.get(provider, provider),
                "status": status.value,
                "usable": model in usable,
                "evaluation_only": evaluation_only,
                "terms": (spec.terms.value if spec is not None
                          else Terms.PRODUCTION.value),
                # Why not, in the words a person can act on. An empty string
                # here means it is usable and there is nothing to say.
                "blocked_by": (
                    "the provider's licence permits evaluation only, not "
                    "customer work" if evaluation_only
                    else "" if model in usable else _why(status)),
            })
    return rows


def _why(status: Status) -> str:
    return {
        Status.NOT_CONFIGURED: "no credential has been entered for this provider",
        Status.PENDING_CREDENTIAL: "",   # stored but untested — still usable
        Status.INVALID_CREDENTIAL: "the stored credential was rejected",
        Status.INSUFFICIENT_PERMISSION: "the credential lacks the needed access",
        Status.DISABLED: "this provider is switched off",
    }.get(status, f"provider status is {status.value}")


def chosen(credentials: CredentialService, selection: Selection, *,
           tenant: TenantId | None) -> list[Choice]:
    """What would run each role right now, and whether that was a decision.

    A role whose selected model is unavailable reports `available=False` with
    the reason. It is not silently reassigned: running somebody's implementation
    work on a model they did not pick, and then recording the substitute as the
    model used, is worse than refusing.
    """
    tenant = _require_tenant(tenant, method="modelchoice.chosen")
    registry = registry_for(credentials, tenant=tenant)

    choices = []
    for role in Role:
        spec, reason = chosen_for(registry, selection, role)
        provider = ""
        if spec is not None:
            provider = next((p for p, models in PROVIDER_MODELS.items()
                             if spec.id in models), "")
        choices.append(Choice(role=role.value,
                              model=spec.id if spec else "",
                              provider=provider, reason=reason,
                              available=spec is not None))
    return choices
