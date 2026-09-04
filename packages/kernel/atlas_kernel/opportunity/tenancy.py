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


#: The tenant an operator account belongs to when it belongs to no customer.
#:
#: An administrator running the console is not a customer, and before this they
#: had `tenant_id = ""` — which meant every tenant-scoped surface answered 403
#: or read nothing, so a console with 59 companies in its database showed the
#: operator an empty screen on every page. A house tenant is a real tenant that
#: happens to be us, which is both true and the thing that makes writes work.
HOUSE_TENANT = "house"


def of_user(user, *, method: str) -> TenantId:
    """The tenant a request writes to. One definition, not five.

    This decision lived as five copies of the same eight lines — in chat,
    models, credentials, missions and the app — each with its own wording and
    its own opportunity to drift. It is one thing: whose rows is this caller
    touching.
    """
    from ..auth.models import Scope

    tenant = (getattr(user, "tenant_id", "") or "").strip()
    if tenant:
        return tenant
    # An operator running Qevik itself has no customer tenant — that is what the
    # `User.tenant_id` docstring means by "they use the internal surfaces, which
    # name a tenant explicitly". This is that naming, in the one place it can
    # be, rather than each surface answering 403 and leaving the operator a
    # console where chat, models and credentials all refuse them.
    if Scope.ADMIN in (getattr(user, "scopes", frozenset()) or frozenset()):
        return HOUSE_TENANT
    raise TenantRequired(
        f"{method} is tenant-scoped and this account is attached to no tenant.")


def console_scope(user, *, method: str) -> TenantId:
    """What an operator console *reads*, which is not what it writes.

    Deliberately a second function rather than a flag on the first, because the
    two answers differ for the same person and hiding that behind a boolean is
    how one of them ends up applied to the other. An administrator writes to
    their own tenant and reads across all of them; anybody else does both within
    their own.

    Every cross-tenant read in this system is therefore greppable: it either
    names ALL_TENANTS or it calls this.
    """
    from ..auth.models import Scope

    scopes = getattr(user, "scopes", frozenset()) or frozenset()
    if Scope.ADMIN in scopes:
        return ALL_TENANTS
    return of_user(user, method=method)


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
