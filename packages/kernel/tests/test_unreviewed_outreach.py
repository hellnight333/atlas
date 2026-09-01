"""Drafted outreach nobody decided about: why each one is there, and who says so.

Two properties are worth more than the wording of any single reason.

**A decision is never listed as undecided.** Two messages were approved by hand
on 2026-08-19 and never sent; what happens to them is DQ-008 and belongs to a
person. A queue that showed them beside genuine drafts would invite somebody to
decide them a second time, which is the one outcome the standing instruction
forbids.

**The reader cannot act.** No approve, no send, no delete, structurally rather
than by a flag — a list of undecided things is the most tempting place in this
system to grow a control that decides all of them at once.

`TestTheQueueAgainstRealRows` adds the third, which only a database can be wrong
about: **nothing waiting is invisible**. The judgement above runs in Python and
the `LIMIT` runs in Postgres, so the two have to agree on what "decided" means
before the limit is taken — and reading the queue has to cost one query rather
than one per draft, because a queue expensive enough to time out is a queue that
shows nothing at all.

The limit is counted in messages, and `TestTheLimitIsCountedInMessages` is the
whole of why. `outreach_drafts.py` writes a WhatsApp message *and* an email for
every business it prepares, so a limit counted in businesses answers a request
for twenty rows with forty — and the extra twenty are not a page anybody asked
for, they are rows the caller cannot tell it was given.
"""

from __future__ import annotations

import inspect
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import event, text

from atlas_kernel import db
from atlas_kernel.db import SessionLocal
from atlas_kernel.opportunity.models import (
    Business,
    BusinessEvent,
    OutreachMessage,
    OutreachStatus,
)
from atlas_kernel.opportunity.repository import OpportunityRepository
from atlas_kernel.outreach import unreviewed

DRAFTED = datetime(2026, 8, 19, 13, 35, tzinfo=UTC)
NOW = datetime(2026, 9, 1, 13, 35, tzinfo=UTC)


def message(**overrides) -> OutreachMessage:
    base = {
        "id": "msg-1",
        "proposal_id": "",
        "mission_id": "",
        "business_id": "biz-1",
        "channel": "whatsapp",
        "recipient": "0501234567",
        "subject": "",
        "body": "Hello — I'm Ayoub.",
        "status": OutreachStatus.DRAFT,
        "created_at": DRAFTED,
    }
    base.update(overrides)
    return OutreachMessage(**base)


def one_row(messages, **kwargs) -> unreviewed.Unreviewed:
    rows = unreviewed.from_records(messages, now=NOW, **kwargs)
    assert len(rows) == 1, [row.reason for row in rows]
    return rows[0]


# --- what "nobody has decided" means ---------------------------------------

def test_a_draft_nobody_was_asked_about_says_exactly_that() -> None:
    row = one_row([message()])
    assert row.state == unreviewed.NEVER_ASKED
    assert row.reason == unreviewed.NEVER_ASKED
    assert "never put to anybody" in row.why
    # The record it was read from, not an adjective.
    assert "2026-08-19" in row.why
    assert row.waiting_days == 13


def test_a_message_awaiting_approval_is_asked_and_unanswered() -> None:
    """`AWAITING_APPROVAL` is the only status that records the question having
    been put. Reading a draft as one would report an ask nobody made."""
    row = one_row([message(status=OutreachStatus.AWAITING_APPROVAL)])
    assert row.state == unreviewed.ASKED
    assert row.reason == unreviewed.ASKED
    assert "not answered" in row.why


def test_an_approved_message_is_never_listed() -> None:
    """DQ-008's two. They are decisions somebody took, and are not this list's
    business — showing them invites a second decision on the first one."""
    approved = message(status=OutreachStatus.APPROVED_FOR_MANUAL_SEND,
                       approval_id="manual-abc123",
                       approved_fingerprint="a" * 64)
    assert unreviewed.from_records([approved], now=NOW) == []
    assert unreviewed.undecided(approved) is False


def test_a_sent_message_is_never_listed() -> None:
    sent = message(status=OutreachStatus.SENT, sent_at=NOW)
    assert unreviewed.from_records([sent], now=NOW) == []


def test_a_status_that_says_draft_is_not_enough_on_its_own() -> None:
    """Four signals, not one column. A status is one edit away from lying, and
    the direction that matters here is an approval reappearing as a draft.

    Driven by `DECISION_COLUMNS` rather than a list written out again, because
    the SQL that feeds this queue narrows by the same names and a signal added
    to one place and not the other is the defect this constant exists to close.
    """
    carried = {"approval_id": "manual-abc123",
               "approved_fingerprint": "b" * 64,
               "sent_at": NOW,
               "authorized_automated_at": NOW}
    assert set(carried) == set(unreviewed.DECISION_COLUMNS), (
        "a decision signal is not exercised here")
    for column, value in carried.items():
        assert unreviewed.undecided(message(**{column: value})) is False, column


def test_the_queue_narrows_by_every_signal_that_means_decided() -> None:
    """The database query and the judgement must agree on what "decided" is.

    `LIMIT` runs inside the database and `undecided` runs after it, so a query
    that admits a row the judgement then drops has spent a place in the queue on
    nothing — and the draft behind it is not read at all. Narrowing by `status`
    alone did exactly that. The query is built from `DECISION_COLUMNS`, so this
    asserts it is *derived from* the list rather than a copy of it.
    """
    source = inspect.getsource(OpportunityRepository.unreviewed_outreach)
    assert "reader.DECISION_COLUMNS" in source, (
        "the candidate query does not narrow by the reader's decision signals")
    assert "reader.UNDECIDED_STATUSES" in source
    # And it narrows before the limit, which is the whole point.
    assert source.index("undecided_sql") < source.index("LIMIT :limit")


def test_a_rejected_message_is_a_decision_too() -> None:
    assert unreviewed.from_records(
        [message(status=OutreachStatus.REJECTED)], now=NOW) == []


# --- why each one is still sitting there -----------------------------------

def test_a_draft_addressed_to_nobody_says_so() -> None:
    """Every email draft `outreach_drafts.py` writes carries an empty
    recipient. There is no address to approve words *to*, and until this said
    so the row was indistinguishable from one waiting on a person."""
    row = one_row([message(channel="email", recipient="")])
    assert row.reason == unreviewed.NO_RECIPIENT
    assert "recipient is empty" in row.why
    # The request state is still answered; the condition does not replace it.
    assert row.state == unreviewed.NEVER_ASKED


def test_a_landline_names_the_channel_that_cannot_reach_it() -> None:
    """Sixteen of the twenty audited clinics publish a landline. A WhatsApp
    message to one is silence, not an error, and approving it would authorise
    something that cannot happen."""
    row = one_row([message(channel="whatsapp", recipient="043951010")])
    assert row.reason == unreviewed.UNREACHABLE
    assert "whatsapp" in row.why
    assert "043951010" in row.why


def test_a_reachable_number_raises_no_condition_at_all() -> None:
    row = one_row([message(channel="whatsapp", recipient="0501029104")])
    assert row.blocked_on == ()
    assert row.reason == unreviewed.NEVER_ASKED


def test_an_unknown_channel_is_not_reported_as_unreachable() -> None:
    """A channel nothing knows about is not an address nothing can reach.
    Reporting the first as the second puts a condition on a draft that no
    record supports."""
    row = one_row([message(channel="carrier-pigeon", recipient="Deiram")])
    assert unreviewed.UNREACHABLE not in row.blocked_on


def test_a_replaced_draft_names_the_one_that_replaced_it() -> None:
    older = message(id="msg-old", created_at=DRAFTED)
    newer = message(id="msg-new",
                    created_at=datetime(2026, 8, 25, 9, 0, tzinfo=UTC))
    rows = {row.message_id: row
            for row in unreviewed.from_records([newer, older], now=NOW)}
    assert rows["msg-old"].reason == unreviewed.SUPERSEDED
    assert "msg-new" in rows["msg-old"].why
    assert rows["msg-new"].blocked_on == ()


def test_a_draft_replaced_by_one_that_was_later_approved_is_still_moot() -> None:
    """Which is why the fold is given every message rather than the undecided
    ones: told only about drafts, it would call this one current."""
    older = message(id="msg-old")
    approved = message(id="msg-approved",
                       created_at=datetime(2026, 8, 25, 9, 0, tzinfo=UTC),
                       status=OutreachStatus.APPROVED_FOR_MANUAL_SEND,
                       approval_id="manual-abc123",
                       approved_fingerprint="c" * 64)
    row = one_row([older, approved])
    assert row.message_id == "msg-old"
    assert row.reason == unreviewed.SUPERSEDED


def test_a_draft_from_another_mission_is_not_a_replacement() -> None:
    """Two missions can each prepare an email to one business about two
    different published artefacts. Calling the older one replaced would retire
    a message nobody replaced."""
    first = message(id="msg-a", channel="email", recipient="a@example.test",
                    mission_id="m-1")
    second = message(id="msg-b", channel="email", recipient="a@example.test",
                     mission_id="m-2",
                     created_at=datetime(2026, 8, 25, 9, 0, tzinfo=UTC))
    rows = unreviewed.from_records([first, second], now=NOW)
    assert [row.reason for row in rows] == [unreviewed.NEVER_ASKED] * 2


def test_evidence_recorded_after_the_words_were_written_is_carried() -> None:
    """The words still say what was observed then. That the ground moved is a
    separate fact, and a reviewer has to see both."""
    row = one_row([message()], changes={"msg-1": [
        {"change": "website_changed", "at": "2026-08-28T10:00:00+00:00"}]})
    assert row.reason == unreviewed.EVIDENCE_MOVED
    assert "1 change(s)" in row.why
    assert "2026-08-28" in row.why


def test_the_headline_reason_is_the_most_decisive_and_the_rest_survive() -> None:
    """A row with several conditions still says one thing first. Hiding the
    others behind it would be the same fault as hiding the first."""
    older = message(id="msg-old", channel="email", recipient="")
    newer = message(id="msg-new", channel="email", recipient="",
                    created_at=datetime(2026, 8, 25, 9, 0, tzinfo=UTC))
    rows = {row.message_id: row
            for row in unreviewed.from_records([older, newer], now=NOW)}
    replaced = rows["msg-old"]
    assert replaced.reason == unreviewed.SUPERSEDED
    assert replaced.blocked_on == (unreviewed.SUPERSEDED,
                                   unreviewed.NO_RECIPIENT)
    assert set(unreviewed.LADDER).issuperset(replaced.blocked_on)


def test_every_named_reason_carries_the_record_it_was_read_from() -> None:
    """A reason with no trace is an assertion. The whole point of this list is
    that a person can follow each statement back to a row."""
    rows = unreviewed.from_records(
        [message(id="msg-1", business_id="biz-1", channel="email", recipient=""),
         message(id="msg-2", business_id="biz-2", recipient="043951010"),
         message(id="msg-3", business_id="biz-3",
                 status=OutreachStatus.AWAITING_APPROVAL)],
        changes={"msg-2": [{"change": "website_changed", "at": ""}]},
        now=NOW)
    assert len(rows) == 3
    for row in rows:
        assert row.why, row.reason
        for name in (row.state, *row.blocked_on):
            assert row.traces.get(name), (row.message_id, name)


def test_the_business_is_named_when_the_records_name_it() -> None:
    row = one_row([message()], names={"biz-1": "Malabar Dental Clinic"})
    assert row.business_name == "Malabar Dental Clinic"
    assert row.summary()["business_name"] == "Malabar Dental Clinic"


def test_a_naive_timestamp_does_not_take_the_list_down() -> None:
    """Rows come back aware and fixtures often do not. Sorting a mixture
    raises, in a list whose whole purpose is to be readable when untidy."""
    row = one_row([message(created_at=datetime(2026, 8, 19, 13, 35))])
    assert row.drafted_at.startswith("2026-08-19")
    assert row.waiting_days == 13


def test_the_tally_breaks_down_by_name() -> None:
    """Not one "blocked" number: four drafts addressed to nobody and one
    waiting on a person are different afternoons."""
    rows = unreviewed.from_records(
        [message(id="msg-1", business_id="biz-1", channel="email", recipient=""),
         message(id="msg-2", business_id="biz-2", recipient="043951010"),
         message(id="msg-3", business_id="biz-3",
                 status=OutreachStatus.AWAITING_APPROVAL)],
        now=NOW)
    assert unreviewed.counts(rows) == {
        "total": 3, "never_asked": 2, "asked": 1, "superseded": 0,
        "addressed_to_nobody": 1, "unreachable": 1, "evidence_moved": 0}


# --- narrowing what is reported, without narrowing what is read ------------

def test_only_reports_the_messages_it_names() -> None:
    """A caller that has already chosen which drafts it wants gets those.

    One row per message asked about, which is what makes a limit counted in
    messages expressible at all.
    """
    rows = unreviewed.from_records(
        [message(id="msg-1", business_id="biz-1"),
         message(id="msg-2", business_id="biz-1", channel="email",
                 recipient="owner@example.ae"),
         message(id="msg-3", business_id="biz-2")],
        only=["msg-1", "msg-3"], now=NOW)
    assert [row.message_id for row in rows] == ["msg-1", "msg-3"]


def test_a_draft_outside_only_still_supersedes_the_one_inside_it() -> None:
    """`only` narrows the report, never the records the report rests on.

    Narrowing the input instead would be the same defect in a different place:
    a draft whose replacement fell outside the caller's window would be
    described as the current words, and somebody would approve superseded text.
    """
    row = one_row([message(id="msg-old"),
                   message(id="msg-new",
                           created_at=datetime(2026, 8, 25, 9, 0, tzinfo=UTC))],
                  only=["msg-old"])
    assert row.message_id == "msg-old"
    assert row.reason == unreviewed.SUPERSEDED
    assert "msg-new" in row.why


def test_only_never_invents_a_row() -> None:
    """It is a filter, not a promise. An id that names a decided message, or no
    message at all, contributes nothing rather than an empty-reasoned row."""
    decided = message(id="msg-decided", approved_fingerprint="d" * 64,
                      status=OutreachStatus.APPROVED_FOR_MANUAL_SEND)
    assert unreviewed.from_records(
        [decided], only=["msg-decided", "msg-imaginary"], now=NOW) == []


def test_no_only_at_all_still_reports_everything_undecided() -> None:
    rows = unreviewed.from_records(
        [message(id="msg-1"), message(id="msg-2", channel="email",
                                      recipient="owner@example.ae")],
        now=NOW)
    assert {row.message_id for row in rows} == {"msg-1", "msg-2"}


# --- the reader cannot act -------------------------------------------------

def test_the_reader_can_neither_decide_nor_send_nor_delete() -> None:
    """Structural, like `outreach_drafts.py`'s own guard. A reader that can act
    is one confident edit away from acting on everything it lists."""
    source = Path(unreviewed.__file__).read_text(encoding="utf-8")
    for forbidden in ("smtplib", "httpx", "requests.post", "save_message",
                      "record_event", "DELETE ", "UPDATE ", "INSERT ",
                      "SessionLocal"):
        assert forbidden not in source, f"the reader gained {forbidden!r}"
    for name in dir(unreviewed):
        assert not any(verb in name.lower()
                       for verb in ("send", "approve", "delete", "reject")), name


def test_the_repository_read_writes_nothing_and_is_tenant_scoped() -> None:
    """A guard that is imported but not called protects nothing, and a read
    across every tenant's outreach is a disclosure.

    The helper is covered too. Batching the evidence read moved SQL out of the
    scoped method, and a write is no less a write for sitting one call away.
    """
    source = inspect.getsource(OpportunityRepository.unreviewed_outreach)
    assert "_require_tenant" in source
    assert "_tenant_predicate" in source
    for method in (OpportunityRepository.unreviewed_outreach,
                   OpportunityRepository._evidence_changes_for):
        body = inspect.getsource(method)
        for forbidden in ("DELETE", "UPDATE", "INSERT", "commit()"):
            assert forbidden not in body, (
                f"{method.__name__} performs {forbidden}")


# --- nothing waiting is invisible ------------------------------------------


@contextmanager
def counting(table: str):
    """How many statements touching one table a block of work runs.

    An N+1 is invisible to an assertion on the answer, because the answer is
    correct either way — the cost is the defect, so the cost is what is
    measured. Attached to the engine rather than to a session, so a call that
    opens its own connections is counted too, which is exactly what the
    per-message version did.
    """
    seen = SimpleNamespace(queries=0)

    def record(conn, cursor, statement, parameters, context, executemany):
        if table in statement:
            seen.queries += 1

    event.listen(db.engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(db.engine, "before_cursor_execute", record)


@pytest.fixture(scope="module")
def repo() -> OpportunityRepository:
    """No hand-applied schema. `init_db` is the whole setup, deliberately.

    This fixture used to add `atlas_businesses.tenant_id` itself, which made the
    queue testable while leaving it unable to run against a database built the
    ordinary way: the tenancy migration had added the column out of band and the
    managed schema never caught up. A fixture that repairs the schema hides
    exactly the failure a fresh installation would hit, so the repair moved into
    `init_db` and `test_the_initialised_schema_carries_the_ownership_column`
    fails if it is ever taken out again.
    """
    db.init_db()
    return OpportunityRepository()


def test_the_initialised_schema_carries_the_ownership_column(repo) -> None:
    """The queue must run on a database built the ordinary way.

    It is scoped through `atlas_businesses`, so the predicate names
    `b.tenant_id`. Without the column the query does not return the wrong rows —
    it raises `UndefinedColumn`, and a queue that raises reports nothing waiting
    just as surely as an empty one does. Only a *named* tenant reaches the
    column, because `ALL_TENANTS` compiles to `TRUE` and names nothing, which is
    how every other tenant-scoped read went on passing while it was missing.

    Asserted by running the read rather than by inspecting the schema alone: the
    column existing and the query working are the same claim, and only the
    second one is what a fresh installation needs.

    And asserted of `init_db`'s source as well, because the live checks cannot
    fail on a database that already has the column — this suite's has carried it
    since a fixture added it by hand, which is exactly how the gap survived. The
    source is what a fresh installation runs.
    """
    source = inspect.getsource(db.init_db)
    assert "atlas_businesses ADD COLUMN IF NOT EXISTS tenant_id" in source, (
        "init_db no longer adds the ownership column, so a database built from "
        "it cannot answer any read scoped to a named tenant")

    assert repo.unreviewed_outreach(
        limit=1, tenant=f"tenant-owns-nothing-{uuid.uuid4().hex[:8]}") == []

    with SessionLocal() as session:
        column = session.execute(text(
            "SELECT is_nullable, column_default FROM information_schema.columns "
            "WHERE table_name = 'atlas_businesses' AND column_name = 'tenant_id'"
        )).first()
        indexes = {row[0] for row in session.execute(text(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'atlas_businesses'"))}

    assert column is not None, "init_db does not create atlas_businesses.tenant_id"
    # Nullable, exactly as `infra/migrate_tenancy.py` made it. Residue owned by
    # nobody keeps a NULL because that is the honest record, and `tenancy.owns`
    # returns such a row to nobody; a `DEFAULT ''` would invent an owner for
    # eight thousand legacy rows and hand them to whoever asked with one.
    assert (column[0], column[1]) == ("YES", None), (
        "tenant_id was given a default or made NOT NULL, which assigns an owner "
        "to rows that have none")
    assert "atlas_businesses_tenant_idx" in indexes, (
        "the ownership index is missing, or init_db and migrate_tenancy have "
        "stopped agreeing on its name — two indexes on one column is what that "
        "disagreement looks like in production")


@pytest.fixture
def queue(repo):
    """A tenant of its own, and everything it wrote removed afterwards.

    A fresh tenant per test rather than a shared one: these assert on what the
    *whole* queue contains, the suite's database is shared, and a draft another
    test left behind would be indistinguishable from a defect here.
    """
    tenant = f"tenant-unreviewed-{uuid.uuid4().hex[:8]}"
    created: list[str] = []

    def business(label: str) -> str:
        """A business whose id sorts by its label, so ordering is assertable."""
        made = Business(id=f"biz-unreviewed-{label}-{uuid.uuid4().hex[:8]}",
                        name=f"Unreviewed {label} {uuid.uuid4().hex[:6]}",
                        geography="United Arab Emirates",
                        sources=["unreviewed-queue-test"])
        repo.save_business(made)
        with SessionLocal() as session:
            session.execute(
                text("UPDATE atlas_businesses SET tenant_id = :t WHERE id = :i"),
                {"t": tenant, "i": made.id})
            session.commit()
        created.append(made.id)
        return made.id

    def draft(business_id: str, *, at: datetime, channel: str = "email",
              recipient: str = "owner@example.ae", **carried) -> OutreachMessage:
        made = OutreachMessage(
            proposal_id="", business_id=business_id, channel=channel,
            recipient=recipient, subject="A quick health check",
            body="Hello — I'm Ayoub.", status=OutreachStatus.DRAFT,
            created_at=at, **carried)
        repo.save_message(made)
        return made

    def prepared(business_id: str, *, at: datetime) -> list[OutreachMessage]:
        """What `outreach_drafts.py` actually writes: two messages, one business.

        A WhatsApp message and an email, in that order, for every business it
        prepares. The reason a limit counted in businesses is unpredictable.
        """
        return [draft(business_id, at=at, channel="whatsapp",
                      recipient="0501029104"),
                draft(business_id, at=at + timedelta(seconds=1), channel="email",
                      recipient="")]

    def reevaluated(business_id: str, *, at: datetime) -> None:
        repo.record_event(BusinessEvent(
            business_id=business_id, factory="reevaluation",
            kind="business_reevaluated", at=at,
            detail={"changes": [{"feature": "online booking", "was": "present",
                                 "now": "not_found", "change": "disappeared"}]}))

    yield SimpleNamespace(tenant=tenant, business=business, draft=draft,
                          prepared=prepared, reevaluated=reevaluated)

    with SessionLocal() as session:
        for statement in (
                "DELETE FROM atlas_outreach_messages WHERE business_id = ANY(:i)",
                "DELETE FROM atlas_business_events WHERE business_id = ANY(:i)",
                "DELETE FROM atlas_businesses WHERE id = ANY(:i)"):
            session.execute(text(statement), {"i": created})
        session.commit()


class TestTheQueueAgainstRealRows:
    """What the dataclass tests above cannot see, because it lives in the SQL.

    Everything before this point checks the judgement on records handed to it.
    Neither of the two defects here is visible that way: both are about the
    *set of records the judgement is handed*, which the database chooses.

    **A place in the queue must cost a real one.** The limit is applied in
    Postgres and `undecided` is applied in Python afterwards, so a candidate the
    query admits and the judgement drops leaves a genuine draft unread — and
    there is no second page to find it on.

    **Reading the queue is one query, not one per draft.** Every undecided
    message asks the same table the same question over a different window.
    Asking separately was a session and a round trip each, and a page that times
    out reports nothing waiting just as surely as an empty list does.
    """

    def test_a_decided_row_does_not_spend_a_place_in_the_queue(
            self, repo, queue) -> None:
        """The limit is the database's and the judgement is Python's.

        A row that only *looked* undecided was admitted by the query, counted
        against the limit, and then correctly dropped — and the genuine draft
        behind it was never read. There is no second page, so it was not late:
        it was invisible.

        The decided business is first by both orderings the query has ever used:
        its id sorts earlier and its draft is older.
        """
        decided = queue.business("a-decided")
        queue.draft(decided, at=DRAFTED, approved_fingerprint="c" * 64)
        waiting = queue.business("z-waiting")
        queue.draft(waiting, at=DRAFTED + timedelta(hours=1))

        rows = repo.unreviewed_outreach(limit=1, tenant=queue.tenant)

        assert [row.business_id for row in rows] == [waiting], (
            "the one place in the queue was spent on a message somebody had "
            "already decided about")

    def test_no_decision_signal_at_all_survives_the_candidate_query(
            self, repo, queue) -> None:
        """Each of the four, against the database rather than the dataclass.

        The unit test proves `undecided` refuses them. This proves the query
        that feeds it refuses them too, which is the half that governs the
        limit — and it is the half that narrowed by `status` alone.
        """
        marks = {"approval_id": "manual-abc123",
                 "approved_fingerprint": "d" * 64,
                 "sent_at": DRAFTED,
                 "authorized_automated_at": DRAFTED}
        assert set(marks) == set(unreviewed.DECISION_COLUMNS)
        for index, (column, value) in enumerate(marks.items()):
            queue.draft(queue.business(f"decided-{index}"), at=DRAFTED,
                        **{column: value})
        waiting = queue.business("waiting")
        queue.draft(waiting, at=DRAFTED + timedelta(hours=1))

        rows = repo.unreviewed_outreach(limit=1, tenant=queue.tenant)

        assert [row.business_id for row in rows] == [waiting]

    def test_the_whole_queue_costs_one_evidence_query(self, repo, queue) -> None:
        """Not one per draft, and not a session per draft either.

        Ten here; a real queue is a hundred and the endpoint permits a thousand.
        At one round trip each, reading the list is where the Publications page
        exhausts the connection pool.
        """
        business = queue.business("busy")
        for index in range(10):
            queue.draft(business, at=DRAFTED + timedelta(minutes=index),
                        mission_id=f"mission-{index}")
        queue.reevaluated(business, at=DRAFTED + timedelta(days=1))

        with counting("atlas_business_events") as counted:
            rows = repo.unreviewed_outreach(limit=50, tenant=queue.tenant)

        assert len(rows) == 10
        assert counted.queries == 1, (
            f"reading {len(rows)} drafts took {counted.queries} evidence "
            "queries; it is one question asked over ten windows")

    def test_one_query_still_answers_each_draft_separately(
            self, repo, queue) -> None:
        """Batching must not batch the *question*.

        Each draft asks what moved after **it** was written. A fold that reused
        the oldest draft's window would report the ground moving under words
        that were written after it moved, which is worse than not reporting it:
        an operator learns the flag means nothing.
        """
        business = queue.business("moved")
        before = queue.draft(business, at=DRAFTED, mission_id="mission-early")
        after = queue.draft(business, at=DRAFTED + timedelta(days=2),
                            mission_id="mission-late")
        queue.reevaluated(business, at=DRAFTED + timedelta(days=1))

        rows = {row.message_id: row for row
                in repo.unreviewed_outreach(limit=10, tenant=queue.tenant)}

        assert unreviewed.EVIDENCE_MOVED in rows[before.id].blocked_on
        assert unreviewed.EVIDENCE_MOVED not in rows[after.id].blocked_on, (
            "a draft written after the change was reported as resting on "
            "evidence that moved")

    def test_another_tenants_undecided_outreach_is_not_in_the_queue(
            self, repo, queue) -> None:
        """Scoped through the business, like contact history.

        `atlas_outreach_messages` carries no tenant of its own, so the join is
        the whole of the isolation — and one tenant reading another's undecided
        drafts would disclose who they are about to write to.
        """
        queue.draft(queue.business("mine"), at=DRAFTED)

        rows = repo.unreviewed_outreach(
            limit=50, tenant=f"tenant-somebody-else-{uuid.uuid4().hex[:8]}")

        assert rows == []


class TestTheLimitIsCountedInMessages:
    """A limit counted in businesses returns an unpredictable number of rows.

    `outreach_drafts.py` writes two messages for every business it prepares — a
    WhatsApp message and an email — and nothing stops a business holding more.
    Counting the limit in businesses therefore answered "give me two" with four,
    and the two extra were not a page a caller could ask for again: they were
    rows it had no way of knowing it had been given. Worse in the other
    direction, a caller that *did* trim to the count would silently drop drafts
    the queue had already fetched and reasoned about.

    So the unit is the message, and these say so against the database, which is
    where the counting happens.
    """

    def test_one_business_holding_two_drafts_yields_one_row_for_a_limit_of_one(
            self, repo, queue) -> None:
        """The plainest form of the defect: one business, two drafts, limit 1.

        Counted in businesses this returns both, because the business is the
        thing being counted and it holds two.
        """
        business = queue.business("prepared")
        whatsapp, _email = queue.prepared(business, at=DRAFTED)

        rows = repo.unreviewed_outreach(limit=1, tenant=queue.tenant)

        assert len(rows) == 1, (
            f"a limit of one returned {len(rows)} messages; the limit is "
            "counted in businesses, and this business holds two drafts")
        assert rows[0].message_id == whatsapp.id

    def test_a_limit_returns_exactly_that_many_messages(
            self, repo, queue) -> None:
        """Three businesses, six drafts, and every limit across the range.

        Asserted for each value rather than one, because a limit that is right
        at the boundaries and wrong in between is the shape a business-counted
        limit actually has: it agrees with a message count exactly when every
        business happens to hold one draft.
        """
        for index, label in enumerate(("first", "second", "third")):
            queue.prepared(queue.business(label),
                           at=DRAFTED + timedelta(minutes=index))

        for wanted in range(1, 7):
            rows = repo.unreviewed_outreach(limit=wanted, tenant=queue.tenant)
            assert len(rows) == wanted, (
                f"asked for {wanted} messages and was given {len(rows)}")

        assert len(repo.unreviewed_outreach(
            limit=50, tenant=queue.tenant)) == 6, "and no more than exist"

    def test_the_longest_waiting_messages_are_the_ones_a_short_limit_keeps(
            self, repo, queue) -> None:
        """A limit truncates; which end it truncates is the design.

        Ordered by id, a draft whose id sorted late was behind the cut however
        long it had waited, and stayed there — the queue could not be cleared
        into visibility. Ordered by when the words were written, working the
        front of the queue brings the rest into view.
        """
        newest = queue.business("a-newest")
        recent = queue.draft(newest, at=DRAFTED + timedelta(days=3))
        oldest = queue.business("z-oldest")
        first = queue.draft(oldest, at=DRAFTED, channel="whatsapp",
                            recipient="0501029104")
        second = queue.draft(oldest, at=DRAFTED + timedelta(minutes=1))

        rows = repo.unreviewed_outreach(limit=2, tenant=queue.tenant)

        assert [row.message_id for row in rows] == [first.id, second.id], (
            "the two longest-waiting messages are not the two that were kept")
        assert recent.id not in {row.message_id for row in rows}

    def test_a_replacement_beyond_the_limit_still_retires_the_draft(
            self, repo, queue) -> None:
        """The limit chooses what is *reported*, never what is *read*.

        A limit implemented by narrowing the rows the fold is handed would
        describe this draft as the current words for the business, and somebody
        would approve text that had already been replaced. Every message for the
        businesses in the queue is fetched; `only` decides which are reported.
        """
        business = queue.business("replaced")
        older = queue.draft(business, at=DRAFTED)
        newer = queue.draft(business, at=DRAFTED + timedelta(days=2))

        rows = repo.unreviewed_outreach(limit=1, tenant=queue.tenant)

        assert [row.message_id for row in rows] == [older.id]
        assert rows[0].reason == unreviewed.SUPERSEDED
        assert newer.id in rows[0].why, (
            "the draft that replaced it was outside the limit and so was not "
            "read at all")

    def test_the_tally_counts_the_messages_that_were_returned(
            self, repo, queue) -> None:
        """`counts` is over the rows a caller was handed, so a truncated queue
        reports the truncated total rather than a number of companies."""
        business = queue.business("tallied")
        queue.prepared(business, at=DRAFTED)

        rows = repo.unreviewed_outreach(limit=1, tenant=queue.tenant)

        tally = unreviewed.counts(rows)
        assert tally["total"] == 1 == len(rows)
