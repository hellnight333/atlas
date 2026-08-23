"""Agency access, tested on the customer it must not reach.

White-label is the point at which a tenancy model usually acquires a second
hierarchy — an Agency table owning Customer rows, with its own resolution rules
that eventually disagree with the first set. These tests pin the alternative:
access is membership, and everything else follows from that.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from atlas_kernel.opportunity.tenancy import CrossTenantAccess
from atlas_kernel.organization.agency import customers, delegation_for
from atlas_kernel.organization.models import Membership, Organization

ACME = Organization(id="org-1", name="Acme Ltd", slug="acme", tenant_id="tenant-acme")
BETA = Organization(id="org-2", name="Beta Co", slug="beta", tenant_id="tenant-beta")
SOLO = Organization(id="org-3", name="Solo Inc", slug="solo", tenant_id="tenant-solo")
ORGS = [ACME, BETA, SOLO]

AGENCY = "identity-agency"
SOLO_USER = "identity-solo"

MEMBERSHIPS = [
    Membership(identity_id=AGENCY, organization_id="org-1"),
    Membership(identity_id=AGENCY, organization_id="org-2"),
    Membership(identity_id=SOLO_USER, organization_id="org-3"),
]


def _for(identity: str, memberships=None, organizations=None):
    return delegation_for(identity, memberships=memberships or MEMBERSHIPS,
                          organizations=organizations or ORGS)


# ============================================ access is membership

def test_an_agency_acts_for_every_customer_it_is_a_member_of() -> None:
    delegation = _for(AGENCY)
    assert set(delegation.tenants) == {"tenant-acme", "tenant-beta"}
    assert delegation.is_agency


def test_a_single_customer_identity_is_not_an_agency() -> None:
    delegation = _for(SOLO_USER)
    assert set(delegation.tenants) == {"tenant-solo"}
    assert not delegation.is_agency


def test_there_is_no_second_hierarchy() -> None:
    """No parent pointer, no agency table, no owner column."""
    from pathlib import Path

    from atlas_kernel.organization import agency, models

    agency_source = Path(agency.__file__).read_text(encoding="utf-8")
    model_source = Path(models.__file__).read_text(encoding="utf-8")
    for forbidden in ("class Agency", "parent_organization", "agency_id",
                      "owner_organization"):
        assert forbidden not in agency_source, forbidden
        assert forbidden not in model_source, forbidden


# ============================================ the customer it must not reach

def test_an_agency_cannot_act_for_a_customer_it_does_not_hold() -> None:
    delegation = _for(AGENCY)
    assert not delegation.may_act_for("tenant-solo")
    with pytest.raises(CrossTenantAccess):
        delegation.require("tenant-solo")


def test_a_customer_cannot_act_for_the_agencys_other_customers() -> None:
    """The relationship is not symmetric, and a model that made it so would
    hand every customer their agency's whole book."""
    delegation = _for(SOLO_USER)
    for tenant in ("tenant-acme", "tenant-beta"):
        assert not delegation.may_act_for(tenant)


def test_the_refusal_does_not_say_whether_the_customer_exists() -> None:
    """An agency probing ids would otherwise learn which customers Qevik has."""
    delegation = _for(AGENCY)
    with pytest.raises(CrossTenantAccess) as real:
        delegation.require("tenant-solo")
    with pytest.raises(CrossTenantAccess) as invented:
        delegation.require("tenant-does-not-exist")
    assert str(real.value) == str(invented.value)


def test_no_tenant_at_all_is_refused() -> None:
    delegation = _for(AGENCY)
    assert not delegation.may_act_for(None)
    assert not delegation.may_act_for("")
    with pytest.raises(CrossTenantAccess):
        delegation.require(None)


# ============================================ access ends when membership does

def test_an_expired_membership_grants_nothing() -> None:
    expired = [Membership(identity_id=AGENCY, organization_id="org-1",
                          expires_at=datetime.now(UTC) - timedelta(days=1))]
    assert _for(AGENCY, memberships=expired).tenants == {}


def test_an_inactive_membership_grants_nothing() -> None:
    inactive = [Membership(identity_id=AGENCY, organization_id="org-1",
                           active=False)]
    assert _for(AGENCY, memberships=inactive).tenants == {}


def test_an_archived_organization_grants_nothing() -> None:
    archived = ACME.model_copy(update={"active": False})
    delegation = _for(AGENCY, organizations=[archived, BETA, SOLO])
    assert "tenant-acme" not in delegation.tenants
    assert "tenant-beta" in delegation.tenants


def test_a_membership_in_an_unknown_organization_grants_nothing() -> None:
    dangling = [Membership(identity_id=AGENCY, organization_id="org-deleted")]
    assert _for(AGENCY, memberships=dangling).tenants == {}


# ============================================ delegation widens who, not what

def test_delegation_carries_no_scopes_or_permissions() -> None:
    """Holding three customers lets an identity act for three tenants. It does
    not raise their scopes or bypass an approval."""
    delegation = _for(AGENCY)
    fields = set(vars(delegation))
    assert fields == {"identity_id", "tenants"}
    for forbidden in ("scopes", "permissions", "roles", "approve"):
        assert forbidden not in fields


def test_the_customer_list_shows_names_not_opaque_ids() -> None:
    listed = customers(_for(AGENCY))
    assert [entry["organization"] for entry in listed] == ["Acme Ltd", "Beta Co"]
    assert all(entry["tenant_id"].startswith("tenant-") for entry in listed)
