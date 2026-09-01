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
"""

from __future__ import annotations

import inspect
import re
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
CONSOLE = (Path(__file__).resolve().parents[3] / "apps" / "control" / "src"
           / "index.html")


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


def only(messages, **kwargs) -> unreviewed.Unreviewed:
    rows = unreviewed.from_records(messages, now=NOW, **kwargs)
    assert len(rows) == 1, [row.reason for row in rows]
    return rows[0]


# --- what "nobody has decided" means ---------------------------------------

def test_a_draft_nobody_was_asked_about_says_exactly_that() -> None:
    row = only([message()])
    assert row.state == unreviewed.NEVER_ASKED
    assert row.reason == unreviewed.NEVER_ASKED
    assert "never put to anybody" in row.why
    # The record it was read from, not an adjective.
    assert "2026-08-19" in row.why
    assert row.waiting_days == 13


def test_a_message_awaiting_approval_is_asked_and_unanswered() -> None:
    """`AWAITING_APPROVAL` is the only status that records the question having
    been put. Reading a draft as one would report an ask nobody made."""
    row = only([message(status=OutreachStatus.AWAITING_APPROVAL)])
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
    from atlas_kernel.opportunity.repository import OpportunityRepository

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
    row = only([message(channel="email", recipient="")])
    assert row.reason == unreviewed.NO_RECIPIENT
    assert "recipient is empty" in row.why
    # The request state is still answered; the condition does not replace it.
    assert row.state == unreviewed.NEVER_ASKED


def test_a_landline_names_the_channel_that_cannot_reach_it() -> None:
    """Sixteen of the twenty audited clinics publish a landline. A WhatsApp
    message to one is silence, not an error, and approving it would authorise
    something that cannot happen."""
    row = only([message(channel="whatsapp", recipient="043951010")])
    assert row.reason == unreviewed.UNREACHABLE
    assert "whatsapp" in row.why
    assert "043951010" in row.why


def test_a_reachable_number_raises_no_condition_at_all() -> None:
    row = only([message(channel="whatsapp", recipient="0501029104")])
    assert row.blocked_on == ()
    assert row.reason == unreviewed.NEVER_ASKED


def test_an_unknown_channel_is_not_reported_as_unreachable() -> None:
    """A channel nothing knows about is not an address nothing can reach.
    Reporting the first as the second puts a condition on a draft that no
    record supports."""
    row = only([message(channel="carrier-pigeon", recipient="Deiram")])
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
    row = only([older, approved])
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
    row = only([message()], changes={"msg-1": [
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
    row = only([message()], names={"biz-1": "Malabar Dental Clinic"})
    assert row.business_name == "Malabar Dental Clinic"
    assert row.summary()["business_name"] == "Malabar Dental Clinic"


def test_a_naive_timestamp_does_not_take_the_list_down() -> None:
    """Rows come back aware and fixtures often do not. Sorting a mixture
    raises, in a list whose whole purpose is to be readable when untidy."""
    row = only([message(created_at=datetime(2026, 8, 19, 13, 35))])
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
    from atlas_kernel.opportunity.repository import OpportunityRepository

    source = inspect.getsource(OpportunityRepository.unreviewed_outreach)
    assert "_require_tenant" in source
    assert "_tenant_predicate" in source
    for method in (OpportunityRepository.unreviewed_outreach,
                   OpportunityRepository._evidence_changes_for):
        body = inspect.getsource(method)
        for forbidden in ("DELETE", "UPDATE", "INSERT", "commit()"):
            assert forbidden not in body, (
                f"{method.__name__} performs {forbidden}")


# --- and it is actually reachable ------------------------------------------

def test_the_route_is_not_swallowed_by_the_mission_route() -> None:
    """A path parameter matches a literal segment happily. Registered after
    `/{mission_id}` this is served as a mission called `outreach-unreviewed` —
    a 404 that reads as "nothing is waiting", which is the one answer this
    endpoint must never give by accident."""
    from atlas_kernel.mission.api import build_router

    paths = [r.path for r in build_router().routes if hasattr(r, "methods")]
    assert "/api/missions/outreach-unreviewed" in paths
    assert paths.index("/api/missions/outreach-unreviewed") < paths.index(
        "/api/missions/{mission_id}")


def test_looking_at_a_draft_is_not_deciding_about_it() -> None:
    """READ, and GET only. Requiring EXECUTE to look would make "why has nobody
    decided this" visible only to the person who can decide it."""
    from atlas_kernel.auth.models import Scope
    from atlas_kernel.mission.api import build_router

    route = {r.path: r for r in build_router().routes
             if hasattr(r, "methods")}["/api/missions/outreach-unreviewed"]
    assert route.methods == {"GET"}
    scopes = set()
    for dependency in route.dependant.dependencies:
        for cell in (getattr(getattr(dependency, "call", None),
                             "__closure__", None) or ()):
            if hasattr(cell.cell_contents, "value"):
                scopes.add(cell.cell_contents)
    assert Scope.READ in scopes
    assert Scope.EXECUTE not in scopes


def test_the_console_shows_the_drafts_and_decides_nothing_about_them() -> None:
    """It asks the kernel and prints the answer. A reason worded on the page is
    a second answer to "why has nobody decided this", and the untested one."""
    source = CONSOLE.read_text(encoding="utf-8")
    assert "/api/missions/outreach-unreviewed" in source
    assert "unreviewedOutreach" in source
    for named in (unreviewed.NEVER_ASKED, unreviewed.ASKED,
                  unreviewed.SUPERSEDED, unreviewed.NO_RECIPIENT,
                  unreviewed.UNREACHABLE, unreviewed.EVIDENCE_MOVED):
        assert named not in source, (
            f"the console names {named} itself; the kernel already decides "
            "which reason a row carries")
    # No control that decides one, and none that decides all of them.
    section = source[source.index("function unreviewedOutreach"):]
    section = section[:section.index("views.measurements")]
    assert not re.search(r"API\.post|data-approve|<button", section), (
        "the console grew a control on a list of undecided messages")


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
    db.init_db()
    # `atlas_businesses.tenant_id` is not created by `init_db`; the tenancy
    # migration was applied out of band and the schema never caught up. Added
    # here for the reason `test_tenant_isolation` adds it — the predicate this
    # queue is scoped by reads the column, and without it the queue cannot run
    # at all against a freshly initialised database.
    with SessionLocal() as session:
        session.execute(text(
            "ALTER TABLE atlas_businesses ADD COLUMN IF NOT EXISTS tenant_id TEXT"))
        session.commit()
    return OpportunityRepository()


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

    def draft(business_id: str, *, at: datetime, **carried) -> OutreachMessage:
        made = OutreachMessage(
            proposal_id="", business_id=business_id, channel="email",
            recipient="owner@example.ae", subject="A quick health check",
            body="Hello — I'm Ayoub.", status=OutreachStatus.DRAFT,
            created_at=at, **carried)
        repo.save_message(made)
        return made

    def reevaluated(business_id: str, *, at: datetime) -> None:
        repo.record_event(BusinessEvent(
            business_id=business_id, factory="reevaluation",
            kind="business_reevaluated", at=at,
            detail={"changes": [{"feature": "online booking", "was": "present",
                                 "now": "not_found", "change": "disappeared"}]}))

    yield SimpleNamespace(tenant=tenant, business=business, draft=draft,
                          reevaluated=reevaluated)

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

    def test_the_longest_waiting_are_the_ones_a_short_limit_keeps(
            self, repo, queue) -> None:
        """A limit truncates; which end it truncates is the design.

        Ordered by id, a business whose id sorted late was behind the cut
        however long it had waited, and stayed there — the queue could not be
        cleared into visibility. Ordered by the oldest draft, working the front
        of the queue brings the rest into view.
        """
        oldest = queue.business("z-oldest")
        queue.draft(oldest, at=DRAFTED)
        newest = queue.business("a-newest")
        queue.draft(newest, at=DRAFTED + timedelta(days=3))

        rows = repo.unreviewed_outreach(limit=1, tenant=queue.tenant)

        assert [row.business_id for row in rows] == [oldest]
