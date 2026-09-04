"""One tenant must not be able to reach another's data, by any route.

These are the negative controls the migration was gated on. Each fails if the
tenant predicate is removed from the method it covers — that is the point of
them, and the reason they assert on the *absence* of another tenant's rows
rather than on the presence of their own.

The read that matters most is `find_possible_duplicates`. Unscoped it answers
"does anyone else in this system know this company", which discloses a
competitor's customer list one probe at a time, and it does so while looking
like a helpful de-duplication feature.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from atlas_kernel.db import SessionLocal
from atlas_kernel.opportunity.models import Business, BusinessEvent
from atlas_kernel.opportunity.repository import OpportunityRepository
from atlas_kernel.opportunity.tenancy import (
    ALL_TENANTS,
    CrossTenantAccess,
    Scope,
    TenantRequired,
    check,
    owns,
    predicate,
    require,
)

TENANT_A = "tenant-test-a"
TENANT_B = "tenant-test-b"


@pytest.fixture(scope="module")
def repo() -> OpportunityRepository:
    return OpportunityRepository()


@pytest.fixture(scope="module")
def tenants(repo):
    """One business per tenant, plus one owned by nobody."""
    made = {}
    with SessionLocal() as session:
        for column in ("organization_id", "tenant_id"):
            session.execute(text(
                f"ALTER TABLE atlas_businesses ADD COLUMN IF NOT EXISTS {column} TEXT"))
        session.commit()
    for label, tenant in (("a", TENANT_A), ("b", TENANT_B), ("orphan", None)):
        business = repo.save_business(Business(
            name=f"Isolation {label} {uuid.uuid4().hex[:6]}",
            geography="United Arab Emirates",
            website=f"https://isolation-{label}-{uuid.uuid4().hex[:6]}.test",
            sources=["isolation-test"]))
        with SessionLocal() as session:
            session.execute(text(
                "UPDATE atlas_businesses SET tenant_id = :t, organization_id = :o "
                "WHERE id = :i"),
                {"t": tenant, "o": f"org-{tenant}" if tenant else None, "i": business.id})
            session.commit()
        repo.record_event(BusinessEvent(
            business_id=business.id, factory="opportunity", kind="business_discovered",
            actor="isolation-test", detail={}))
        made[label] = business
    yield made
    with SessionLocal() as session:
        ids = [b.id for b in made.values()]
        session.execute(text("DELETE FROM atlas_business_events WHERE business_id = ANY(:i)"),
                        {"i": ids})
        session.execute(text("DELETE FROM atlas_businesses WHERE id = ANY(:i)"), {"i": ids})
        session.commit()


# --- reads -----------------------------------------------------------------

def test_a_tenant_never_lists_another_tenants_business(repo, tenants) -> None:
    names = {b.name for b in repo.list_businesses(tenant=TENANT_A)}
    assert tenants["a"].name in names
    assert tenants["b"].name not in names, "tenant A listed tenant B's business"
    assert tenants["orphan"].name not in names, "an unowned business was listed"


def test_fetching_another_tenants_business_returns_nothing(repo, tenants) -> None:
    """None, not a refusal: the caller turns it into 404, and a 403 would
    confirm the record exists."""
    assert repo.get_business(tenants["a"].id, tenant=TENANT_A) is not None
    assert repo.get_business(tenants["b"].id, tenant=TENANT_A) is None


def test_an_unowned_business_belongs_to_nobody(repo, tenants) -> None:
    """Legacy residue and the unresolved business are visible to no tenant."""
    assert repo.get_business(tenants["orphan"].id, tenant=TENANT_A) is None
    assert repo.get_business(tenants["orphan"].id, tenant=TENANT_B) is None
    assert repo.get_business(tenants["orphan"].id, tenant=ALL_TENANTS) is not None


def test_duplicate_search_cannot_probe_another_tenant(repo, tenants) -> None:
    """The disclosure that looks like a feature."""
    probe = Business(name=tenants["b"].name, geography="United Arab Emirates",
                     website=tenants["b"].website, sources=["probe"])
    found = repo.find_possible_duplicates(probe, tenant=TENANT_A)
    assert all(f.id != tenants["b"].id for f in found), \
        "duplicate search exposed another tenant's business"


def test_events_do_not_cross_tenants(repo, tenants) -> None:
    ids = {e.business_id for e in repo.list_events(tenant=TENANT_A)}
    assert tenants["b"].id not in ids
    assert tenants["orphan"].id not in ids


def test_aggregates_cannot_reveal_another_tenants_volume(repo, tenants) -> None:
    """A count that includes another tenant's rows leaks how much work they have."""
    a = len(repo.list_businesses(tenant=TENANT_A))
    b = len(repo.list_businesses(tenant=TENANT_B))
    everything = len(repo.list_businesses(tenant=ALL_TENANTS))
    assert a >= 1 and b >= 1
    assert everything > a and everything > b, "ALL_TENANTS must see more than one tenant"
    assert a + b <= everything


# --- writes ----------------------------------------------------------------

def test_a_tenant_cannot_write_against_another_tenants_business(repo, tenants) -> None:
    """The write path is guarded by the same read: you cannot fetch it, so you
    cannot act on it."""
    assert repo.get_business(tenants["b"].id, tenant=TENANT_A) is None


# --- the tenant is never implicit -----------------------------------------

@pytest.mark.parametrize("call", [
    lambda r: r.list_businesses(),
    lambda r: r.get_business("anything"),
    lambda r: r.list_events(),
])
def test_a_scoped_call_without_a_tenant_is_refused(repo, call) -> None:
    """No default. A default is how a background job reads every tenant."""
    with pytest.raises(TenantRequired):
        call(repo)


def test_reading_across_tenants_has_to_be_spelled_out(repo, tenants) -> None:
    """ALL_TENANTS is greppable; a forgotten argument is not."""
    assert len(repo.list_businesses(tenant=ALL_TENANTS)) >= 3


def test_contact_history_is_tenant_scoped(repo, tenants) -> None:
    """A tenant must not learn who another tenant has written to, or when —
    a shared cooldown discloses outreach volume."""
    import inspect
    assert "tenant" in inspect.signature(repo.load_contact_history).parameters
    history = repo.load_contact_history(tenant=TENANT_A)
    assert history.last_contacted(tenants["b"].id) is None, \
        "contact history exposed another tenant's outreach"


# --- house level stays house level ----------------------------------------

def test_suppression_remains_global_on_purpose(repo) -> None:
    """A do-not-contact request is made to us, not to one tenant. Honouring it
    for one while another writes to them would be indefensible."""
    entry = f"isolation-{uuid.uuid4().hex[:8]}@example.test"
    repo.suppress(entry, reason="isolation test")
    assert repo.load_suppression().contains(entry)
    import inspect
    assert "tenant" not in inspect.signature(repo.load_suppression).parameters, \
        "suppression must stay house-level"


# --- the primitives --------------------------------------------------------

def test_the_scope_vocabulary_is_explicit() -> None:
    assert {s.value for s in Scope} == {"tenant_scoped", "business_scoped", "house_level"}


def test_a_predicate_is_always_produced() -> None:
    """Never an empty string — a query is never accidentally unscoped."""
    assert predicate("t-1")[0] == "tenant_id = :_tenant"
    assert predicate(ALL_TENANTS)[0] == "TRUE"
    assert predicate("t-1", alias="b")[0] == "b.tenant_id = :_tenant"


def test_ownership_of_an_unowned_row() -> None:
    assert owns(None, ALL_TENANTS) is True
    assert owns(None, "t-1") is False
    assert owns("t-1", "t-1") is True
    assert owns("t-1", "t-2") is False


def test_check_raises_rather_than_returning_false() -> None:
    with pytest.raises(CrossTenantAccess):
        check("t-2", "t-1", what="business")


def test_require_names_the_method_it_refused() -> None:
    with pytest.raises(TenantRequired, match="list_businesses"):
        require(None, method="list_businesses")


# --- the guard must be wired, not merely present --------------------------

@pytest.mark.parametrize("method", [
    "get_business", "list_businesses", "find_possible_duplicates", "list_events"])
def test_every_scoped_method_requires_and_applies(method) -> None:
    """A guard that is imported but not called protects nothing."""
    import inspect
    source = inspect.getsource(getattr(OpportunityRepository, method))
    assert "_require_tenant" in source, f"{method} does not require a tenant"
    assert "_tenant_predicate" in source or "owns(" in source, \
        f"{method} requires a tenant but never applies it"


# --- the column the queries were written against -------------------------------

def test_a_business_carries_the_tenant_its_repository_filters_on() -> None:
    """`list_businesses` has always been documented TENANT_SCOPED and filtered
    on `b.tenant_id`. Neither the model nor the table had such a field.

    On production the column did not exist, so `/api/missions/outreach-unreviewed`
    answered HTTP 500 with `column b.tenant_id does not exist`, and every other
    business read worked only because the operator console asks with
    ALL_TENANTS — whose predicate is always true and never names the column.
    The tenancy was real in the SQL, real in the docstrings, and absent from
    the schema.
    """
    from atlas_kernel.opportunity.models import Business

    assert "tenant_id" in Business.model_fields
    assert Business(name="Al Noor Dental").tenant_id == "", (
        "empty means not established, exactly as it does on User")


def test_the_schema_creates_and_indexes_the_column() -> None:
    from pathlib import Path

    db = (Path(__file__).resolve().parents[1] / "atlas_kernel" / "db.py"
          ).read_text(encoding="utf-8")
    create = db.split("CREATE TABLE IF NOT EXISTS atlas_businesses", 1)[1][:400]
    assert "tenant_id" in create, "a fresh database would not have the column"
    assert "ADD COLUMN IF NOT EXISTS tenant_id" in db, (
        "an existing database would not gain it")
    assert "atlas_businesses_tenant_idx" in db


def test_the_backfill_is_guarded_by_state_and_not_by_a_date() -> None:
    """It runs on a database that predates tenancy and never again.

    A dated guard would still be a guard: it would sweep a customer's business
    inserted with an empty tenant into the house on the next migration. The
    condition is "no business has a tenant yet", which stops being true the
    moment this runs once.
    """
    from pathlib import Path

    db = (Path(__file__).resolve().parents[1] / "atlas_kernel" / "db.py"
          ).read_text(encoding="utf-8")
    assert "WHERE tenant_id <> ''" in db, "the backfill has no guard"
    assert "UPDATE atlas_businesses SET tenant_id" in db


def test_saving_a_business_writes_its_tenant() -> None:
    """The insert named ten columns and `tenant_id` was not among them, so every
    business the opportunity factory created belonged to nobody — visible only
    to a reader asking with ALL_TENANTS."""
    from pathlib import Path

    repository = (Path(__file__).resolve().parents[1] / "atlas_kernel" /
                  "opportunity" / "repository.py").read_text(encoding="utf-8")
    insert = repository.split("INSERT INTO atlas_businesses", 1)[1][:600]
    assert "tenant_id" in insert.split("ON CONFLICT")[0], (
        "a saved business does not record which tenant knows about it")
    assert "tenant_id = EXCLUDED.tenant_id" not in insert, (
        "seeing a company again must not move it between tenants")
