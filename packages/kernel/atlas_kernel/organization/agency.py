"""An agency reading its customers' data, without a second tenancy system.

The temptation is to add a hierarchy — an `Agency` owning `Customer` rows, with
its own parent/child column and its own resolution rules. That would be a second
answer to "who may see this", and the two would eventually disagree.

The existing model already answers it. An `Organization` carries a `tenant_id`.
A `Membership` links an identity to an organization. So the set of tenants a
person may act for is **the tenants of the organizations they are a member of**,
and an agency is simply an identity with memberships in several customer
organizations. No new table, no new hierarchy, no parent pointer.

That has a property worth stating: revoking an agency's access to one customer
is removing one membership, which is the same operation as removing any other
member. There is no separate agency-access concept that could be forgotten when
somebody leaves.

**Delegation widens who, never what.** Holding memberships in three customers
lets an identity act for three tenants; it does not raise their scopes, bypass
an approval, or make a customer task theirs to complete. Every downstream guard
still runs with the tenant they selected.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..opportunity.tenancy import CrossTenantAccess, TenantId
from .models import Membership, Organization


@dataclass(frozen=True)
class Delegation:
    """Which tenants one identity may act for, and through which organization.

    Keeps the organization alongside the tenant because "you may read tenant
    X" is not a useful thing to show somebody — "you may read Acme Ltd" is, and
    an agency console listing opaque tenant ids is unusable.
    """

    identity_id: str
    #: tenant_id -> organization name, for display and for audit.
    tenants: dict[str, str]

    def may_act_for(self, tenant: TenantId | None) -> bool:
        return bool(tenant) and str(tenant) in self.tenants

    def require(self, tenant: TenantId | None) -> TenantId:
        """The selected tenant, or a refusal naming nothing they cannot see.

        The message does not say whether the tenant exists — the same reason the
        customer routes return an indistinguishable 404. An agency probing ids
        would otherwise learn which customers Qevik has.
        """
        if not self.may_act_for(tenant):
            raise CrossTenantAccess(
                "this account does not act for that customer")
        return str(tenant)

    @property
    def is_agency(self) -> bool:
        """More than one customer. Not a role — an observation about access."""
        return len(self.tenants) > 1


def delegation_for(identity_id: str, *, memberships: list[Membership],
                   organizations: list[Organization]) -> Delegation:
    """Resolve what an identity may act for, from memberships alone.

    Expired and inactive memberships are excluded by `is_current`, so access
    ends when the membership does rather than when somebody remembers to revoke
    a separate agency grant.
    """
    by_id = {o.id: o for o in organizations}
    tenants: dict[str, str] = {}
    for membership in memberships:
        if membership.identity_id != identity_id or not membership.is_current():
            continue
        organization = by_id.get(membership.organization_id)
        if organization is None or not organization.active:
            continue
        tenants[organization.tenant_id] = organization.name
    return Delegation(identity_id=identity_id, tenants=tenants)


def customers(delegation: Delegation) -> list[dict]:
    """The agency's customer list, for a console. Names, not opaque ids."""
    return sorted(
        ({"tenant_id": tenant, "organization": name}
         for tenant, name in delegation.tenants.items()),
        key=lambda entry: entry["organization"])
