"""Production must stay free of test fixtures. Checked against production itself.

Every other test in this suite runs against `<database>_test`, redirected by
conftest before `atlas_kernel.db` builds its engine. This file is the exception:
it opens the **production** database read-only and asserts that nothing the
suite writes has landed there.

That arrangement is the point. The redirect is the mechanism; this is the
detector. If someone removes the redirect, weakens it, or adds a test that
constructs its own engine from a hardcoded URL, the mechanism fails silently and
only an independent check notices. A guard that lives inside the thing it guards
verifies nothing.

It is read-only and skips rather than fails when production is unreachable, so a
laptop with no server access still runs a green suite.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text

PRODUCTION_URL = os.environ.get("QEVIK_PRODUCTION_DATABASE_URL", "")

#: The same signatures the cleanup used. RFC 2606 reserves .test and .example
#: precisely so they can never belong to a real business.
FIXTURE_RECIPIENTS = ("@clinic.test", "@example.com", "@example.test", "@test.test")

#: A test double that records what would have been sent. Nothing in production
#: writes it, so a single row means the suite reached production.
FIXTURE_CHANNELS = ("recording",)


@pytest.fixture(scope="module")
def production():
    if not PRODUCTION_URL:
        pytest.skip("no production database configured — nothing to guard")
    if PRODUCTION_URL.rstrip("/").endswith("_test"):
        pytest.skip("already pointed at a test database")
    engine = create_engine(PRODUCTION_URL, future=True)
    try:
        with engine.connect() as conn:
            yield conn
    except Exception as unreachable:  # noqa: BLE001 - offline is not a failure
        pytest.skip(f"production unreachable: {unreachable}")
    finally:
        engine.dispose()


def test_the_suite_is_not_pointed_at_production() -> None:
    """The redirect itself, asserted rather than assumed."""
    current = os.environ.get("ATLAS_DATABASE_URL", "")
    if not current:
        pytest.skip("no database configured")
    assert current.rstrip("/").endswith("_test"), (
        "tests are running against a non-test database. conftest's redirect has "
        "been removed or bypassed, and this run is writing to production."
    )
    if PRODUCTION_URL:
        assert current != PRODUCTION_URL


def test_no_fixture_channel_reached_production(production) -> None:
    channels = ", ".join(f"'{c}'" for c in FIXTURE_CHANNELS)
    count = production.execute(
        text(f"SELECT count(*) FROM atlas_outreach_messages WHERE channel IN ({channels})")
    ).scalar()
    assert count == 0, (
        f"{count} row(s) on a test-only channel are in production. The suite has "
        "written there again — check conftest's redirect."
    )


def test_no_fixture_recipient_reached_production(production) -> None:
    clause = " OR ".join(f"recipient LIKE '%{r}'" for r in FIXTURE_RECIPIENTS)
    count = production.execute(
        text(f"SELECT count(*) FROM atlas_outreach_messages WHERE {clause}")
    ).scalar()
    assert count == 0, f"{count} outreach row(s) addressed to a reserved test domain"


def test_no_event_in_production_is_orphaned(production) -> None:
    """An event whose business does not exist was written by a test.

    Real code saves the business first — `resolve_business` returns one before
    any event references it. Eighty-one of these had accumulated.
    """
    count = production.execute(
        text(
            "SELECT count(*) FROM atlas_business_events e WHERE NOT EXISTS "
            "(SELECT 1 FROM atlas_businesses b WHERE b.id = e.business_id)"
        )
    ).scalar()
    assert count == 0, f"{count} event(s) reference a business that does not exist"


def test_the_twenty_audited_businesses_are_intact(production) -> None:
    """The commercial history this cleanup existed to protect.

    Asserts the shape rather than exact totals: audits and drafts accumulate
    legitimately each time they are re-run, and a test that pins those numbers
    fails for the wrong reason on the next honest run.
    """
    demos = production.execute(
        text(
            "SELECT count(DISTINCT business_id) FROM atlas_business_events "
            "WHERE kind = 'website_demo_published'"
        )
    ).scalar()
    assert demos == 20, f"expected 20 businesses with a published demo, found {demos}"

    every_demo_has_an_audit = production.execute(
        text(
            "SELECT count(*) FROM ("
            "  SELECT business_id FROM atlas_business_events"
            "  WHERE kind = 'website_demo_published' GROUP BY business_id"
            ") d WHERE NOT EXISTS ("
            "  SELECT 1 FROM atlas_business_events a"
            "  WHERE a.business_id = d.business_id AND a.kind = 'website_audited'"
            ")"
        )
    ).scalar()
    assert every_demo_has_an_audit == 0, "a demo exists for a business with no audit"


def test_nothing_has_been_sent_to_a_real_business(production) -> None:
    """The commercial invariant. No channel is connected; nothing may be sent."""
    sent = production.execute(
        text(
            "SELECT count(*) FROM atlas_outreach_messages "
            "WHERE channel IN ('email', 'whatsapp') "
            "AND (status <> 'draft' OR sent_at IS NOT NULL "
            "     OR approval_id IS NOT NULL OR approved_fingerprint IS NOT NULL)"
        )
    ).scalar()
    assert sent == 0, f"{sent} outreach message(s) are no longer an unsent draft"
