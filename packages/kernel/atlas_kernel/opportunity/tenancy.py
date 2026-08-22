"""Who is asking, and what they are allowed to see.

Isolation lives in the repository because that is the only place every caller
passes through. A filter in a route protects one route; a filter in a template
protects one screen; a filter here protects everything, including the background
job somebody writes next year.

Three scopes, and the distinction is not cosmetic:

**TENANT_SCOPED** — rows belonging to one tenant. Reaching another tenant's is
the failure this module exists to prevent.

**BUSINESS_SCOPED** — rows reached through a business whose ownership was
already checked. They inherit rather than re-deriving, so there is one place
ownership is decided.

**HOUSE_LEVEL** — genuinely global, and there is exactly one: the do-not-contact
suppression list. A person who asks not to be contacted asks *us*, and honouring
it for one tenant while another writes to them would be indefensible.

The tenant is a parameter, never ambient. Request-local globals work until a
worker, a migration or a cron job runs without one — and then they silently read
everything.
"""

from __future__ import annotations

from enum import StrEnum


class Scope(StrEnum):
    TENANT_SCOPED = "tenant_scoped"
    BUSINESS_SCOPED = "business_scoped"
    HOUSE_LEVEL = "house_level"


class CrossTenantAccess(PermissionError):
    """A caller asked for a row belonging to somebody else.

    Raised rather than returned empty so the attempt is visible in a log. The
    HTTP layer answers 404 — a 403 would confirm the record exists, which is
    itself a disclosure.
    """


class TenantRequired(ValueError):
    """A tenant-scoped call arrived without a tenant.

    Not defaulted. A default is how a background job ends up reading every
    tenant's data while looking correct.
    """


class _AllTenants:
    """The operator console's explicit request for every tenant's rows.

    A sentinel rather than `None` so that reading across tenants is a visible,
    greppable act. `grep ALL_TENANTS` lists every place it can happen; there is
    no equivalent search for a forgotten argument.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "ALL_TENANTS"

    def __bool__(self) -> bool:
        return True


ALL_TENANTS = _AllTenants()

#: What a tenant argument may be: an id, or the deliberate everything.
TenantId = str | _AllTenants


def require(tenant: TenantId | None, *, method: str) -> TenantId:
    """Refuse a tenant-scoped call that did not say who is asking."""
    if tenant is None or (isinstance(tenant, str) and not tenant.strip()):
        raise TenantRequired(
            f"{method} is tenant-scoped and needs a tenant. Pass the caller's "
            "tenant id, or ALL_TENANTS if this really is the operator console.")
    return tenant


def predicate(tenant: TenantId, *, column: str = "tenant_id",
              alias: str = "") -> tuple[str, dict]:
    """The SQL fragment and parameters that scope a query.

    Returns an always-true fragment only for ALL_TENANTS, so a query is never
    accidentally unscoped: every call site interpolates something.
    """
    if isinstance(tenant, _AllTenants):
        return "TRUE", {}
    qualified = f"{alias}.{column}" if alias else column
    return f"{qualified} = :_tenant", {"_tenant": tenant}


def owns(row_tenant: str | None, tenant: TenantId) -> bool:
    """Whether this caller may see a row with that tenant.

    A row with no tenant belongs to nobody and is returned to nobody — legacy
    residue and the unresolved business are invisible to every tenant, and
    visible only to the operator console.
    """
    if isinstance(tenant, _AllTenants):
        return True
    return row_tenant is not None and row_tenant == tenant


def check(row_tenant: str | None, tenant: TenantId, *, what: str) -> None:
    if not owns(row_tenant, tenant):
        raise CrossTenantAccess(f"{what} does not belong to this tenant")
