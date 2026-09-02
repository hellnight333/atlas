"""The records that answer "why is this outreach draft still unreviewed".

`atlas_kernel.outreach.unreviewed` derives the answer and reads nothing: every
record it reasons over arrives as an argument, deliberately, so the derivation
stays testable without a database and the query can be written separately. This
is that query — `OpportunityRepository.unreviewed_outreach_records` — and what is
under test here is the boundary between the two halves, not the derivation. The
derivation has its own suite in `test_unreviewed_outreach.py` and none of it is
repeated.

Four properties carry the weight, and each is a way the boundary can be wrong
while every individual half looks right:

* **The bundle is the module's own signature.** Keys that drift from
  `from_records`' record parameters are a second vocabulary for the two halves
  to disagree in.
* **"Undecided" is decided once.** The window is taken inside the database and
  the judgement runs after it, so a query that narrows only by `status` lets a
  row carrying an approval spend a place and leaves a genuinely undecided draft
  behind it unread.
* **The limit counts messages.** A business holds several drafts, so a window
  counted in businesses answers a request for two rows with an unpredictable
  number and drops the rest without saying so.
* **More is read than is reported.** Whether a draft was replaced is a fact
  about the messages *around* it, so narrowing the records to the window would
  turn a superseded draft back into current words somebody then sends.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from atlas_kernel import db
from atlas_kernel.db import SessionLocal
from atlas_kernel.mission.reevaluation import (
    COMPARED,
    FACTORY as REEVALUATION_FACTORY,
    Change,
)
from atlas_kernel.opportunity.models import (
    Business,
    BusinessEvent,
    OutreachMessage,
    OutreachStatus,
)
from atlas_kernel.opportunity.repository import OpportunityRepository
from atlas_kernel.opportunity.tenancy import ALL_TENANTS, TenantRequired
from atlas_kernel.outreach import unreviewed

DRAFTED = datetime(2026, 8, 19, 13, 35, tzinfo=UTC)
LATER = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)
NOW = datetime(2026, 9, 1, 13, 35, tzinfo=UTC)

#: A number the audited clinics publish, and one WhatsApp accepts.
MOBILE = "0501029104"

#: An empty registry rather than the real one. Whether a channel can reach an
#: address is the derivation's business and is settled in its own suite; reading
#: the live registry here would make these tests depend on which providers happen
#: to be configured.
NO_CHANNELS: dict = {}


@pytest.fixture(scope="module", autouse=True)
def schema():
    db.init_db()
    # `tenant_id` arrives with `infra/migrate_tenancy.py` rather than with
    # `init_db`, exactly as `test_tenant_isolation` handles it. Without the
    # column the scoped predicate cannot be exercised at all, and the isolation
    # test below would pass by never running.
    with SessionLocal() as session:
        session.execute(text(
            "ALTER TABLE atlas_businesses ADD COLUMN IF NOT EXISTS tenant_id TEXT"))
        session.commit()


@pytest.fixture
def repo() -> OpportunityRepository:
    return OpportunityRepository()


@pytest.fixture
def world(repo):
    """A tenant no other run has used, and everything made under it removed after.

    The test database persists between runs and this read is scoped by tenant, so
    a tenant of this test's own is what makes "these are the rows in the answer"
    an assertion about the query rather than about the leftovers.
    """
    tenant = f"tenant-unreviewed-{uuid.uuid4().hex[:8]}"
    made: list[str] = []

    def business(name: str, *, owner: str | None = tenant) -> Business:
        record = repo.save_business(Business(
            name=f"{name} {uuid.uuid4().hex[:6]}",
            geography="United Arab Emirates",
            website=f"https://unreviewed-{uuid.uuid4().hex[:8]}.test",
            sources=["unreviewed-records-test"]))
        with SessionLocal() as session:
            session.execute(
                text("UPDATE atlas_businesses SET tenant_id = :t WHERE id = :i"),
                {"t": owner, "i": record.id})
            session.commit()
        made.append(record.id)
        return record

    def draft(company: Business, *, created_at: datetime = DRAFTED,
              **overrides) -> OutreachMessage:
        payload = {
            "proposal_id": "p-unreviewed",
            "business_id": company.id,
            "channel": "whatsapp",
            "recipient": MOBILE,
            "subject": "",
            "body": "Hello — I'm Ayoub.",
            "created_at": created_at,
        }
        payload.update(overrides)
        return repo.save_message(OutreachMessage(**payload))

    yield SimpleNamespace(tenant=tenant, business=business, draft=draft)

    if made:
        with SessionLocal() as session:
            for table, column in (("atlas_outreach_messages", "business_id"),
                                  ("atlas_business_events", "business_id"),
                                  ("atlas_businesses", "id")):
                session.execute(
                    text(f"DELETE FROM {table} WHERE {column} = ANY(:ids)"),
                    {"ids": made})
            session.commit()


def _record_parameters() -> set[str]:
    """The arguments of `from_records` that are records rather than settings.

    Read from the signature rather than written out, because the claim being
    made is about that signature. `now` is a clock and `channels` is the registry
    of send paths; neither is read from the database, and a read that returned
    either would be answering a question nobody asked it.
    """
    return set(inspect.signature(unreviewed.from_records).parameters) - {
        "now", "channels"}


def _derived(records: dict) -> list[unreviewed.Unreviewed]:
    return unreviewed.from_records(**records, now=NOW, channels=NO_CHANNELS)


# --- the bundle is the module's own signature ------------------------------

def test_the_bundle_is_exactly_the_records_the_module_asks_for(repo, world) -> None:
    """Keys, not merely count. They are the parameter names, so the two halves
    are wired by the signature itself and there is no third place for them to
    agree in — which is what the splat below demonstrates rather than asserts."""
    company = world.business("Al Noor Dental")
    world.draft(company)

    records = repo.unreviewed_outreach_records(tenant=world.tenant)

    assert set(records) == _record_parameters()
    rows = _derived(records)
    assert [row.business_name for row in rows] == [company.name]


def test_a_window_of_nothing_is_answered_with_nothing(repo, world) -> None:
    """And with every key still present. An empty answer that dropped the keys
    would fail at the splat instead of reporting an empty queue, so the caller
    would see a `TypeError` on the one day there is nothing to review."""
    world.draft(world.business("Nothing Waiting Dental"))

    for limit in (0, -1):
        records = repo.unreviewed_outreach_records(limit=limit, tenant=world.tenant)
        assert set(records) == _record_parameters()
        assert records == {"messages": [], "only": [], "names": {}, "events": {}}
        assert _derived(records) == []


# --- "undecided" is decided once, and the query narrows by the same signals -

def test_a_row_carrying_a_decision_never_spends_a_place_in_the_window(
        repo, world) -> None:
    """The failure a looser filter usually does not have.

    `LIMIT` runs inside the database and `unreviewed.undecided` runs after it. A
    row whose status still says `draft` while it carries an approval is admitted
    by a status-only filter, spends one of the places, and is then correctly
    dropped — so the genuinely undecided draft behind it is never read at all,
    and the queue reports nothing while somebody is waiting.
    """
    company = world.business("Jumeirah Smile")
    decided = world.draft(company, approved_fingerprint="f" * 64)
    waiting = world.draft(company, created_at=LATER, channel="email",
                          recipient="owner@example.ae")

    records = repo.unreviewed_outreach_records(limit=1, tenant=world.tenant)

    assert records["only"] == [waiting.id], (
        "a decided row spent the one place in the window, and the draft behind "
        "it was never read")
    assert decided.id not in records["only"]
    assert [row.message_id for row in _derived(records)] == [waiting.id]


def test_the_query_narrows_by_the_readers_own_lists() -> None:
    """One definition of "nobody has decided", not two.

    Two is how an approved message eventually turns up in a queue inviting
    somebody to approve it a second time. The names are read from the reader, so
    a signal added there cannot be forgotten here.
    """
    source = inspect.getsource(OpportunityRepository.unreviewed_outreach_records)
    assert "reader.UNDECIDED_STATUSES" in source
    assert "reader.DECISION_COLUMNS" in source
    spelled = [name for name in (*unreviewed.UNDECIDED_STATUSES,
                                 *unreviewed.DECISION_COLUMNS)
               if f"'{name}'" in source or f'"{name}"' in source]
    assert not spelled, (
        f"{spelled} are named here as well as in the reader, so the two "
        "definitions of 'nobody has decided' can drift apart")


# --- the limit counts messages ---------------------------------------------

def test_the_limit_counts_messages_and_not_businesses(repo, world) -> None:
    """A business holds several drafts — `outreach_drafts.py` writes a WhatsApp
    message and an email for every one it prepares — so a window counted in
    businesses answers a request for two rows with three."""
    company = world.business("Marina Dental")
    first = world.draft(company, channel="whatsapp")
    second = world.draft(company, channel="email", recipient="owner@example.ae",
                         created_at=DRAFTED + timedelta(minutes=1))
    third = world.draft(company, channel="sms",
                        created_at=DRAFTED + timedelta(minutes=2))

    records = repo.unreviewed_outreach_records(limit=2, tenant=world.tenant)

    assert records["only"] == [first.id, second.id]
    assert third.id not in records["only"]
    assert len(_derived(records)) == 2
    # One company, and the window did not round up to all of its drafts.
    assert set(records["names"]) == {company.id}


def test_the_window_starts_with_whatever_has_waited_longest(repo, world) -> None:
    """Truncation drops the newest, so a long-waiting draft is never permanently
    behind the cut and clearing the front of the queue brings the rest into
    view."""
    company = world.business("Deira Dental")
    oldest = world.draft(company, channel="whatsapp", created_at=DRAFTED)
    newest = world.draft(company, channel="email", recipient="owner@example.ae",
                         created_at=LATER)

    records = repo.unreviewed_outreach_records(limit=1, tenant=world.tenant)

    assert records["only"] == [oldest.id]
    assert newest.id not in records["only"]


# --- more is read than is reported -----------------------------------------

def test_a_replacement_outside_the_window_still_arrives_with_the_records(
        repo, world) -> None:
    """Supersession is a fact about the messages around a draft, and the
    replacement is not itself undecided — it was sent. Returning only the window
    would describe superseded text as the current words."""
    company = world.business("Barsha Dental")
    superseded = world.draft(company, created_at=DRAFTED)
    replacement = world.draft(company, created_at=LATER,
                              status=OutreachStatus.SENT, sent_at=LATER)

    records = repo.unreviewed_outreach_records(tenant=world.tenant)

    assert records["only"] == [superseded.id], "a sent message is a decision"
    assert {m.id for m in records["messages"]} == {superseded.id, replacement.id}
    row, = _derived(records)
    assert row.reason == unreviewed.SUPERSEDED
    assert replacement.id in row.why


# --- the timelines go back whole -------------------------------------------

def test_the_timeline_is_returned_whole_rather_than_by_kind(repo, world) -> None:
    """Which kinds matter is `classify`'s question. Narrowing here would put the
    reader's vocabulary in the query as well, and the copy stops matching
    silently the day a kind is added."""
    company = world.business("Karama Dental")
    world.draft(company, created_at=DRAFTED)
    repo.record_event(BusinessEvent(business_id=company.id, kind="website_audited",
                                    at=LATER, detail={"error": ""}))
    repo.record_event(BusinessEvent(
        business_id=company.id, factory=REEVALUATION_FACTORY, kind=COMPARED,
        at=LATER, detail={"changes": [{"feature": "online_booking",
                                       "change": Change.DISAPPEARED.value}]}))

    records = repo.unreviewed_outreach_records(tenant=world.tenant)

    kinds = {event.kind for event in records["events"][company.id]}
    assert {"website_audited", COMPARED} <= kinds, (
        "the events were narrowed by kind, so a kind added to the reader would "
        "never reach it")
    row, = _derived(records)
    assert row.reason == unreviewed.EVIDENCE_MOVED


def test_a_question_recorded_about_the_business_reaches_the_reader(
        repo, world) -> None:
    """The middle state, end to end. It also proves `detail` arrives decoded: a
    JSON string would carry the approval id past `classify` unread, and the row
    would claim nobody was ever asked — a false negative about a person."""
    company = world.business("Satwa Dental")
    world.draft(company, created_at=DRAFTED)
    repo.record_event(BusinessEvent(
        business_id=company.id, kind=unreviewed.APPROVAL_REQUESTED, at=LATER,
        opportunity_id="opp-1", detail={"approval_id": "apr-77"}))

    row, = _derived(repo.unreviewed_outreach_records(tenant=world.tenant))

    assert row.state == unreviewed.ASKED_ABOUT_THE_BUSINESS
    assert "apr-77" in row.why


def test_every_business_in_the_answer_is_named_and_has_a_history(
        repo, world) -> None:
    """An absent history and a history nobody fetched are not the same empty
    list, so every business in the answer carries an entry either way."""
    one = world.business("Mirdif Dental")
    two = world.business("Rashidiya Dental")
    world.draft(one)
    world.draft(two)

    records = repo.unreviewed_outreach_records(tenant=world.tenant)

    assert records["names"] == {one.id: one.name, two.id: two.name}
    assert set(records["events"]) == {one.id, two.id}
    assert records["events"][one.id] == []


# --- whose undecided outreach it is ----------------------------------------

def test_a_scoped_call_without_a_tenant_is_refused(repo) -> None:
    """No default. A default is how a background job reads every tenant."""
    with pytest.raises(TenantRequired, match="unreviewed_outreach_records"):
        repo.unreviewed_outreach_records()


def test_one_tenant_never_sees_anothers_undecided_outreach(repo, world) -> None:
    """The same disclosure a shared cooldown would be: what another tenant has
    drafted, to whom, and how much of it is waiting."""
    mine = world.business("Ours Dental")
    theirs = world.business("Theirs Dental", owner="tenant-somebody-else")
    world.draft(mine)
    world.draft(theirs)

    records = repo.unreviewed_outreach_records(tenant=world.tenant)

    assert set(records["names"]) == {mine.id}
    assert all(m.business_id == mine.id for m in records["messages"])
    assert set(records["events"]) == {mine.id}


def test_a_business_owned_by_nobody_is_returned_to_nobody(repo, world) -> None:
    """Legacy residue is invisible to every tenant, and visible to the operator
    console that asks for it in as many words."""
    orphan = world.business("Orphan Dental", owner=None)
    # Older than anything a test writes today, so the console's window reaches it
    # without reading the whole database to prove the point.
    world.draft(orphan, created_at=datetime(2019, 1, 1, tzinfo=UTC))

    assert orphan.id not in repo.unreviewed_outreach_records(
        tenant=world.tenant)["names"]
    assert orphan.id in repo.unreviewed_outreach_records(
        limit=50, tenant=ALL_TENANTS)["names"]


def test_the_guard_is_wired_and_not_merely_imported() -> None:
    """A guard that is imported but not called protects nothing."""
    source = inspect.getsource(OpportunityRepository.unreviewed_outreach_records)
    assert "TENANT_SCOPED" in source
    assert "_require_tenant" in source
    assert "_tenant_predicate" in source


# --- it reads, and only reads ----------------------------------------------

def test_the_read_can_only_read() -> None:
    """A list of undecided things is the most tempting place in the system to
    grow a control that decides them all at once. The reader holds the same
    guarantee from the other side; this is the half that touches the database."""
    source = inspect.getsource(OpportunityRepository.unreviewed_outreach_records)
    for forbidden in ("INSERT", "UPDATE ", "DELETE", "commit(", "save_message",
                      "record_event", "delete_unsent_drafts"):
        assert forbidden not in source, f"the read gained {forbidden!r}"
