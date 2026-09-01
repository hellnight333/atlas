"""Drafted outreach nobody decided about: why each one is there, and who says so.

Two properties are worth more than the wording of any single reason.

**A decision is never listed as undecided.** Two messages were approved by hand
on 2026-08-19 and never sent; what happens to them is DQ-008 and belongs to a
person. A queue that showed them beside genuine drafts would invite somebody to
decide them a second time, which is the one outcome the standing instruction
forbids.

**The reader cannot act, and reads nothing.** No approve, no send, no delete,
structurally rather than by a flag — a list of undecided things is the most
tempting place in this system to grow a control that decides all of them at
once. And every record arrives as an argument, which is why every test below
runs without a database.

`TestTheUnitIsAMessage` is the reviewer's finding from the earlier attempt, kept
as a test. `outreach_drafts.py` writes a WhatsApp message *and* an email for
every business it prepares, so a window counted in businesses answers a request
for four rows with eight — and the extra four are not a page anybody asked for,
they are rows the caller cannot tell it was given.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from atlas_kernel.mission.reevaluation import COMPARED, Change
from atlas_kernel.opportunity.models import (
    BusinessEvent,
    OutreachMessage,
    OutreachStatus,
)
from atlas_kernel.outreach import unreviewed

DRAFTED = datetime(2026, 8, 19, 13, 35, tzinfo=UTC)
LATER = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)
NOW = datetime(2026, 9, 1, 13, 35, tzinfo=UTC)

#: A number sixteen of the twenty audited clinics publish. WhatsApp refuses it.
LANDLINE = "043951010"
MOBILE = "0501029104"

#: The two offsets these records actually arrive in: the clinics are in Dubai
#: and the control plane writes UTC.
DUBAI = timezone(timedelta(hours=4))


def message(**overrides) -> OutreachMessage:
    base = {
        "id": "msg-1",
        "proposal_id": "",
        "mission_id": "",
        "business_id": "biz-1",
        "channel": "whatsapp",
        "recipient": MOBILE,
        "subject": "",
        "body": "Hello — I'm Ayoub.",
        "status": OutreachStatus.DRAFT,
        "created_at": DRAFTED,
    }
    base.update(overrides)
    return OutreachMessage(**base)


def reevaluated(at: datetime, *changes: Change,
                business_id: str = "biz-1", kind: str = COMPARED) -> BusinessEvent:
    """One `business_reevaluated` entry on a company's timeline."""
    return BusinessEvent(
        business_id=business_id, kind=kind, at=at,
        detail={"changes": [{"feature": "online_booking", "change": change.value}
                            for change in changes]})


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


def test_that_it_was_asked_is_recorded_and_when_it_was_asked_is_not() -> None:
    """The row carries one moment, and it is not the moment somebody was asked.

    A draft can sit for weeks and be raised with a person yesterday; `status`
    moves, `created_at` does not. Reporting the age of the words as the age of
    the ask would tell an operator they had ignored a request for thirteen days
    when they first saw it this morning — a statement about a person, made up
    out of a timestamp about a message.
    """
    row = one_row([message(status=OutreachStatus.AWAITING_APPROVAL)])
    assert "When it was put is not recorded" in row.why
    assert "when the words were written, 13 day(s) ago" in row.why
    assert "put to a person 13 day(s) ago" not in row.why
    # The only moment quoted is the one the row actually carries.
    assert row.drafted_at in row.why
    assert row.waiting_days == 13


def test_an_undated_row_that_was_asked_about_quotes_no_moment_at_all() -> None:
    """With no `created_at` there is nothing to measure from, and a row that has
    been put to somebody is no exception: `0 day(s) ago` beside "a time that was
    not recorded" would read as today."""
    undated = SimpleNamespace(id="msg-1", business_id="biz-1",
                              status="awaiting_approval", channel="whatsapp",
                              recipient=MOBILE, subject="", body="",
                              mission_id="", proposal_id="", created_at=None)
    row = one_row([undated])
    assert row.state == unreviewed.ASKED
    assert "no moment at all" in row.why
    assert "day(s) ago" not in row.why
    assert row.waiting_days == 0


def test_an_approved_message_is_never_listed() -> None:
    """DQ-008's two. They are decisions somebody took, and are not this list's
    business — showing them invites a second decision on the first one."""
    approved = message(status=OutreachStatus.APPROVED_FOR_MANUAL_SEND,
                       approval_id="manual-abc123",
                       approved_fingerprint="a" * 64)
    assert unreviewed.from_records([approved], now=NOW) == []
    assert unreviewed.undecided(approved) is False


def test_a_sent_message_is_never_listed() -> None:
    assert unreviewed.from_records(
        [message(status=OutreachStatus.SENT, sent_at=NOW)], now=NOW) == []


def test_a_rejected_message_is_a_decision_too() -> None:
    assert unreviewed.from_records(
        [message(status=OutreachStatus.REJECTED)], now=NOW) == []


def test_a_status_that_says_draft_is_not_enough_on_its_own() -> None:
    """Four signals, not one column. A status is one edit away from lying, and
    the direction that matters here is an approval reappearing as a draft.

    Driven by `DECISION_COLUMNS` rather than a list written out again, because
    the query that feeds this queue narrows by the same names and a signal added
    to one place and not the other is the defect that constant exists to close.
    """
    carried = {"approval_id": "manual-abc123",
               "approved_fingerprint": "b" * 64,
               "sent_at": NOW,
               "authorized_automated_at": NOW}
    assert set(carried) == set(unreviewed.DECISION_COLUMNS), (
        "a decision signal is not exercised here")
    for column, value in carried.items():
        assert unreviewed.undecided(message(**{column: value})) is False, column


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
    """A WhatsApp message to a landline is silence, not an error, and approving
    it would authorise something that cannot happen."""
    row = one_row([message(channel="whatsapp", recipient=LANDLINE)])
    assert row.reason == unreviewed.UNREACHABLE
    assert "whatsapp" in row.why
    assert LANDLINE in row.why


def test_a_reachable_number_raises_no_condition_at_all() -> None:
    row = one_row([message(channel="whatsapp", recipient=MOBILE)])
    assert row.blocked_on == ()
    assert row.reason == unreviewed.NEVER_ASKED


def test_an_unknown_channel_is_not_reported_as_unreachable() -> None:
    """A channel nothing knows about is not an address nothing can reach.
    Reporting the first as the second puts a condition on a draft that no
    record supports."""
    row = one_row([message(channel="carrier-pigeon", recipient="Deiram")])
    assert row.blocked_on == ()


def test_the_channels_can_be_supplied_rather_than_looked_up() -> None:
    """The registry is a default, not a dependency the caller cannot displace."""
    refusing = {"whatsapp": SimpleNamespace(can_reach=lambda recipient: False)}
    row = one_row([message(recipient=MOBILE)], channels=refusing)
    assert row.reason == unreviewed.UNREACHABLE


def test_a_replaced_draft_names_the_one_that_replaced_it() -> None:
    rows = {row.message_id: row for row in unreviewed.from_records(
        [message(id="msg-new", created_at=LATER), message(id="msg-old")],
        now=NOW)}
    assert rows["msg-old"].reason == unreviewed.SUPERSEDED
    assert "msg-new" in rows["msg-old"].why
    assert rows["msg-new"].blocked_on == ()


def test_a_draft_replaced_by_one_that_was_later_approved_is_still_moot() -> None:
    """Which is why the fold is given every message rather than the undecided
    ones: told only about drafts, it would call this one current."""
    approved = message(id="msg-approved", created_at=LATER,
                       status=OutreachStatus.APPROVED_FOR_MANUAL_SEND,
                       approval_id="manual-abc123",
                       approved_fingerprint="c" * 64)
    row = one_row([message(id="msg-old"), approved])
    assert row.message_id == "msg-old"
    assert row.reason == unreviewed.SUPERSEDED


def test_two_drafts_written_in_the_same_instant_replace_nothing() -> None:
    """Same origin, same moment: the records establish no order, so neither row
    may be told it was replaced. Sorting can always produce a last message — the
    key falls back to the id — but a tiebreak is not a fact about time, and
    `REPLACED_BY_A_LATER_DRAFT` is a claim about what happened."""
    rows = unreviewed.from_records(
        [message(id="msg-b", created_at=DRAFTED),
         message(id="msg-a", created_at=DRAFTED)],
        now=NOW)
    assert [row.reason for row in rows] == [unreviewed.NEVER_ASKED] * 2
    assert unreviewed.counts(rows)["superseded"] == 0


def test_an_undated_draft_is_never_reported_as_replaced() -> None:
    """The row this list exists for. Nothing is recorded about when it was
    written, so nothing can be recorded about what came after it — and the trace
    would have named a replacement written at no time at all."""
    undated = SimpleNamespace(id="msg-undated", business_id="biz-1",
                              status="draft", channel="whatsapp",
                              recipient=MOBILE, subject="", body="",
                              mission_id="", proposal_id="", created_at=None)
    rows = {row.message_id: row for row in unreviewed.from_records(
        [undated, message(id="msg-dated", created_at=LATER)], now=NOW)}
    assert rows["msg-undated"].blocked_on == ()
    assert rows["msg-dated"].blocked_on == ()


def test_an_undated_draft_does_not_replace_a_dated_one() -> None:
    """The other direction, and the one a sort gets wrong quietly: a row with no
    timestamp sorts somewhere, and wherever it lands it must not retire a
    message whose own timestamp is on file."""
    undated = SimpleNamespace(id="msg-zzz", business_id="biz-1", status="draft",
                              channel="whatsapp", recipient=MOBILE, subject="",
                              body="", mission_id="", proposal_id="",
                              created_at=None)
    row = one_row([undated, message(id="msg-dated")], only=["msg-dated"])
    assert row.blocked_on == ()


def test_the_replacement_a_row_names_is_always_one_with_a_time() -> None:
    """Whatever else is in the records for that origin. The trace states when
    the replacement was written, and a trace with a blank where the moment goes
    is the assertion this module refuses to make."""
    undated = SimpleNamespace(id="msg-undated", business_id="biz-1",
                              status="draft", channel="whatsapp",
                              recipient=MOBILE, subject="", body="",
                              mission_id="", proposal_id="", created_at=None)
    row = one_row([message(id="msg-old"), message(id="msg-new", created_at=LATER),
                   undated],
                  only=["msg-old"])
    assert row.reason == unreviewed.SUPERSEDED
    assert "msg-new" in row.why
    assert "2026-08-25" in row.why


def test_a_draft_from_another_mission_is_not_a_replacement() -> None:
    """Two missions can each prepare an email to one business about two
    different published artefacts. Calling the older one replaced would retire
    a message nobody replaced."""
    rows = unreviewed.from_records(
        [message(id="msg-a", channel="email", recipient="a@example.test",
                 mission_id="m-1"),
         message(id="msg-b", channel="email", recipient="a@example.test",
                 mission_id="m-2", created_at=LATER)],
        now=NOW)
    assert [row.reason for row in rows] == [unreviewed.NEVER_ASKED] * 2


# --- evidence that moved after the words were written -----------------------

def test_evidence_recorded_after_the_words_were_written_is_carried() -> None:
    """The words still say what was observed then. That the ground moved is a
    separate fact, and a reviewer has to see both."""
    row = one_row([message()], events={"biz-1": [
        reevaluated(LATER, Change.DISAPPEARED)]})
    assert row.reason == unreviewed.EVIDENCE_MOVED
    assert "1 change(s)" in row.why
    assert "2026-08-25" in row.why


def test_evidence_recorded_before_the_words_has_not_moved_under_them() -> None:
    """The words were written knowing it. A window that ignored the draft's own
    timestamp would flag every message about a business ever reevaluated."""
    earlier = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    row = one_row([message()], events={"biz-1": [
        reevaluated(earlier, Change.CONTRADICTED)]})
    assert row.blocked_on == ()


def test_a_reevaluation_at_the_very_instant_of_the_draft_is_not_after_it() -> None:
    row = one_row([message()], events={"biz-1": [
        reevaluated(DRAFTED, Change.CONTRADICTED)]})
    assert row.blocked_on == ()


def test_a_change_about_our_own_checking_is_not_the_ground_moving() -> None:
    """`reevaluation` separates a site that changed from a reading that could
    not see it. A draft flagged because our own crawler lost visibility would
    train an operator to ignore the flag."""
    row = one_row([message()], events={"biz-1": [
        reevaluated(LATER, Change.NOW_UNVERIFIED, Change.NOW_CONFIRMED)]})
    assert row.blocked_on == ()


def test_another_kind_of_event_is_not_read_as_evidence() -> None:
    """A business's history holds everything every factory recorded. Only a
    reevaluation says what the ground under these claims looks like now."""
    row = one_row([message()], events={"biz-1": [
        reevaluated(LATER, Change.DISAPPEARED, kind="approval_requested")]})
    assert row.blocked_on == ()


def test_another_business_history_does_not_attach_to_this_draft() -> None:
    row = one_row([message(business_id="biz-1")], events={
        "biz-2": [reevaluated(LATER, Change.DISAPPEARED, business_id="biz-2")]})
    assert row.blocked_on == ()


def test_events_may_arrive_as_rows_rather_than_models() -> None:
    """The same events come back as mappings from one caller and as models from
    another, and this module must not dictate which."""
    row = one_row([message()], events={"biz-1": [
        {"kind": COMPARED, "at": LATER,
         "detail": {"changes": [{"change": Change.NEWLY_OBSERVED.value}]}}]})
    assert row.reason == unreviewed.EVIDENCE_MOVED


def test_a_reevaluation_with_no_detail_at_all_says_nothing() -> None:
    row = one_row([message()],
                  events={"biz-1": [{"kind": COMPARED, "at": LATER}]})
    assert row.blocked_on == ()


def test_the_latest_change_is_the_latest_moment_not_the_largest_string() -> None:
    """Events arrive in whatever offset they were written in.

    `2026-08-26T02:00:00+04:00` is an hour *earlier* than
    `2026-08-25T23:00:00+00:00` and the larger of the two as text, so ordering
    the rendered strings sorts these by their offset rather than by when they
    happened. Naming the Dubai one as the most recent thing anybody found would
    date the moving ground a day after it moved, in the one sentence a reviewer
    is meant to check back against the record.
    """
    row = one_row([message()], events={"biz-1": [
        reevaluated(datetime(2026, 8, 25, 23, 0, tzinfo=UTC),
                    Change.DISAPPEARED),
        reevaluated(datetime(2026, 8, 26, 2, 0, tzinfo=DUBAI),
                    Change.CONTRADICTED)]})
    assert row.reason == unreviewed.EVIDENCE_MOVED
    assert "2 change(s)" in row.why
    assert "2026-08-25T23:00:00+00:00" in row.why
    assert "+04:00" not in row.why


# --- how several conditions are reported together ---------------------------

def test_the_headline_reason_is_the_most_decisive_and_the_rest_survive() -> None:
    """A row with several conditions still says one thing first. Hiding the
    others behind it would be the same fault as hiding the first."""
    rows = {row.message_id: row for row in unreviewed.from_records(
        [message(id="msg-old", channel="email", recipient=""),
         message(id="msg-new", channel="email", recipient="",
                 created_at=LATER)],
        now=NOW)}
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
         message(id="msg-2", business_id="biz-2", recipient=LANDLINE),
         message(id="msg-3", business_id="biz-3",
                 status=OutreachStatus.AWAITING_APPROVAL)],
        events={"biz-2": [reevaluated(LATER, Change.DISAPPEARED,
                                      business_id="biz-2")]},
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


def test_a_draft_with_no_timestamp_is_still_listed_and_says_so() -> None:
    """A row whose `created_at` never arrived is exactly the kind this list
    exists for. Dropping it, or inventing a date for it, would hide the one
    draft nobody can otherwise account for — and with no moment to measure
    from, nothing can be said about what moved after it."""
    undated = SimpleNamespace(id="msg-1", business_id="biz-1", status="draft",
                              channel="whatsapp", recipient=MOBILE, subject="",
                              body="", mission_id="", proposal_id="",
                              created_at=None)
    row = one_row([undated],
                  events={"biz-1": [reevaluated(LATER, Change.DISAPPEARED)]})
    assert row.state == unreviewed.NEVER_ASKED
    assert "a time that was not recorded" in row.why
    assert row.drafted_at == ""
    assert row.waiting_days == 0
    assert row.blocked_on == ()


def test_the_tally_breaks_down_by_name() -> None:
    """Not one "blocked" number: four drafts addressed to nobody and one
    waiting on a person are different afternoons."""
    rows = unreviewed.from_records(
        [message(id="msg-1", business_id="biz-1", channel="email", recipient=""),
         message(id="msg-2", business_id="biz-2", recipient=LANDLINE),
         message(id="msg-3", business_id="biz-3",
                 status=OutreachStatus.AWAITING_APPROVAL)],
        now=NOW)
    assert unreviewed.counts(rows) == {
        "total": 3, "never_asked": 2, "asked": 1, "superseded": 0,
        "addressed_to_nobody": 1, "unreachable": 1, "evidence_moved": 0}


def test_every_named_condition_has_a_total() -> None:
    """A tally that omits a reason reads as "none of those", not as "not
    counted". Pairing the keys with the ladder is what stops a fifth condition
    from being named on rows and missing from every total."""
    assert tuple(unreviewed.COUNT_KEYS) == unreviewed.LADDER
    assert set(unreviewed.counts([])) == {
        "total", "never_asked", "asked", *unreviewed.COUNT_KEYS.values()}


def test_a_row_with_several_conditions_is_counted_under_each() -> None:
    """The condition totals are not slices of `total` and do not sum to it. One
    draft addressed to nobody whose evidence also moved is one row and two
    things to settle."""
    rows = unreviewed.from_records(
        [message(channel="email", recipient="")],
        events={"biz-1": [reevaluated(LATER, Change.DISAPPEARED)]}, now=NOW)
    assert rows[0].blocked_on == (unreviewed.NO_RECIPIENT,
                                  unreviewed.EVIDENCE_MOVED)
    assert unreviewed.counts(rows) == {
        "total": 1, "never_asked": 1, "asked": 0, "superseded": 0,
        "addressed_to_nobody": 1, "unreachable": 0, "evidence_moved": 1}


# --- the unit is a message, and so is any window ---------------------------


class TestTheUnitIsAMessage:
    """The reviewer's finding, kept as tests rather than as a comment.

    A business holds several drafts, so anything counted in businesses returns
    an unpredictable number of messages and silently drops the rest.
    """

    @staticmethod
    def two_drafts_each(*business_ids: str) -> list[OutreachMessage]:
        return [message(id=f"msg-{business}-{channel}", business_id=business,
                        channel=channel,
                        recipient=MOBILE if channel == "whatsapp" else "")
                for business in business_ids
                for channel in ("whatsapp", "email")]

    def test_a_window_of_four_messages_reports_four_messages(self) -> None:
        drafts = self.two_drafts_each("biz-1", "biz-2", "biz-3")
        asked_about = [draft.id for draft in drafts[:4]]
        rows = unreviewed.from_records(drafts, only=asked_about, now=NOW)
        assert {row.message_id for row in rows} == set(asked_about)
        assert len(rows) == 4
        # Four messages, and they belong to two businesses. A window counted in
        # businesses would have answered this with two rows or with six.
        assert len({row.business_id for row in rows}) == 2

    def test_the_tally_counts_messages_not_companies(self) -> None:
        rows = unreviewed.from_records(self.two_drafts_each("biz-1"), now=NOW)
        assert unreviewed.counts(rows)["total"] == 2
        assert len({row.business_id for row in rows}) == 1

    def test_every_draft_a_business_holds_is_reported_separately(self) -> None:
        """Two drafts for one company, two different reasons. Collapsing them
        to one row per business would drop whichever was second."""
        rows = unreviewed.from_records(self.two_drafts_each("biz-1"), now=NOW)
        assert {row.reason for row in rows} == {unreviewed.NEVER_ASKED,
                                                unreviewed.NO_RECIPIENT}


# --- narrowing what is reported, without narrowing what is read ------------

def test_only_reports_the_messages_it_names() -> None:
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
    row = one_row([message(id="msg-old"), message(id="msg-new", created_at=LATER)],
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


def test_the_id_a_row_reports_is_the_id_only_accepts_back() -> None:
    """`only` is how a caller asks again about rows it was handed, so the
    identifier a row carries and the identifier the filter matches have to be
    the same string — including when there is no identifier at all.

    A row whose `id` never arrived reports `""`, and that is the only handle
    anybody has on it. A filter that read the same absence as `"None"` would
    make exactly the draft this list exists for the one draft nobody can ask
    about a second time.
    """
    idless = SimpleNamespace(id=None, business_id="biz-1", status="draft",
                             channel="whatsapp", recipient=MOBILE, subject="",
                             body="", mission_id="", proposal_id="",
                             created_at=DRAFTED)
    records = [idless, message(id="msg-2")]
    handed = [row.message_id for row in unreviewed.from_records(records, now=NOW)]
    assert handed == ["", "msg-2"]

    asked_again = unreviewed.from_records(records, only=handed, now=NOW)
    assert [row.message_id for row in asked_again] == handed


def test_no_only_at_all_still_reports_everything_undecided() -> None:
    rows = unreviewed.from_records(
        [message(id="msg-1"),
         message(id="msg-2", channel="email", recipient="owner@example.ae")],
        now=NOW)
    assert {row.message_id for row in rows} == {"msg-1", "msg-2"}


def test_the_list_is_oldest_first() -> None:
    """The order an operator works in. Newest-first would leave the drafts that
    have waited longest at the bottom of every page."""
    rows = unreviewed.from_records(
        [message(id="msg-new", created_at=LATER), message(id="msg-old")],
        now=NOW)
    assert [row.message_id for row in rows] == ["msg-old", "msg-new"]


# --- the reader cannot act, and reads nothing ------------------------------

def test_the_reader_can_neither_decide_nor_send_nor_delete() -> None:
    """Structural, like `outreach_drafts.py`'s own guard. A reader that can act
    is one confident edit away from acting on everything it lists."""
    source = Path(unreviewed.__file__).read_text(encoding="utf-8")
    for forbidden in ("smtplib", "httpx", "requests.post", "save_message",
                      "record_event", "DELETE ", "UPDATE ", "INSERT "):
        assert forbidden not in source, f"the reader gained {forbidden!r}"
    for name in dir(unreviewed):
        assert not any(verb in name.lower()
                       for verb in ("send", "approve", "delete", "reject")), name


def test_the_reader_opens_no_database_of_its_own() -> None:
    """Everything arrives as an argument. A read from here would put the query
    and the derivation in one place, and the derivation is the half that has to
    be answerable without a database — as every test above is."""
    source = Path(unreviewed.__file__).read_text(encoding="utf-8")
    for forbidden in ("SessionLocal", "sqlalchemy", "session.execute", "engine"):
        assert forbidden not in source, f"the reader gained {forbidden!r}"
