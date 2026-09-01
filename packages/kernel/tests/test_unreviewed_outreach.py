"""Drafted outreach nobody decided about: why each one is there, and who says so.

Two properties are worth more than the wording of any single reason.

**A decision is never listed as undecided.** Two messages were approved by hand
on 2026-08-19 and never sent; what happens to them is DQ-008 and belongs to a
person. A queue that showed them beside genuine drafts would invite somebody to
decide them a second time, which is the one outcome the standing instruction
forbids.

**No claim is made that the records do not support.** That cuts hardest against
the *negative* claim, and the reason is a gap in the repository as it stands:
`OpportunityService.request_approval` creates the approval and appends an
`approval_requested` entry to the business's timeline, and it does not touch the
message. Nothing anywhere assigns `OutreachStatus.AWAITING_APPROVAL` to an
`OutreachMessage`, and no method writes a decision back onto one either. So a
draft row on its own cannot say "nobody was ever asked", and the timeline entry
cannot say "this message was asked about" — it names an approval and an
opportunity, never a message, and every business here holds two drafts.
`TestAskedAboutTheBusiness` is the state that sits between the two and says
exactly what the records hold. Closing the gap is a change to the approval
service; these tests describe this module against the records that exist.

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

from atlas_kernel.mission.reevaluation import (
    COMPARED,
    FACTORY as REEVALUATION_FACTORY,
    Change,
)
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


def reevaluated(at: datetime, *changes: Change, business_id: str = "biz-1",
                kind: str = COMPARED, factory: str = REEVALUATION_FACTORY,
                feature: str = "online_booking") -> BusinessEvent:
    """One `business_reevaluated` entry on a company's timeline.

    Under the reevaluation factory's label, because that is what `to_event`
    writes and `kind` means nothing without it: the timeline is shared by every
    factory and each namespaces its own vocabulary.
    """
    return BusinessEvent(
        business_id=business_id, factory=factory, kind=kind, at=at,
        detail={"changes": [{"feature": feature, "change": change.value}
                            for change in changes]})


def asked(at: datetime = LATER, *, approval_id: str = "apr-77",
          business_id: str = "biz-1") -> BusinessEvent:
    """The entry `OpportunityService.request_approval` appends.

    An approval and an opportunity. No message — which is the whole difficulty.
    """
    return BusinessEvent(business_id=business_id,
                         kind=unreviewed.APPROVAL_REQUESTED, at=at,
                         opportunity_id="opp-1",
                         detail={"approval_id": approval_id})


def claims_a_reading(trace: str) -> bool:
    """Whether a trace says anybody looked at the words.

    Word by word rather than by substring: `already` contains `read`, and a
    guard that failed on it would push the next writer towards deleting a true
    sentence to satisfy a test.
    """
    words = {word.strip(".,;:()'\"").lower() for word in trace.split()}
    return bool(words & {"read", "unread", "seen", "opened", "reviewed"})


def one_row(messages, **kwargs) -> unreviewed.Unreviewed:
    rows = unreviewed.from_records(messages, now=NOW, **kwargs)
    assert len(rows) == 1, [row.reason for row in rows]
    return rows[0]


# --- what "nobody has decided" means ---------------------------------------

def test_a_draft_nobody_was_asked_about_says_exactly_that() -> None:
    """And says it having looked in both places. The claim is an absence, so it
    is only true if the business's history is silent as well as the row."""
    row = one_row([message()])
    assert row.state == unreviewed.NEVER_ASKED
    assert row.reason == unreviewed.NEVER_ASKED
    assert "no record anywhere" in row.why
    assert "history records no approval request" in row.why
    # The record it was read from, not an adjective.
    assert "2026-08-19" in row.why
    assert row.waiting_days == 13


def test_a_message_awaiting_approval_is_asked_and_unanswered() -> None:
    """`AWAITING_APPROVAL` is the strongest record there is — the row itself
    saying the question was put about these exact words."""
    row = one_row([message(status=OutreachStatus.AWAITING_APPROVAL)])
    assert row.state == unreviewed.ASKED
    assert row.reason == unreviewed.ASKED
    assert "the row records no answer" in row.why


def test_the_claim_is_about_the_row_and_not_about_the_approver() -> None:
    """The row recording no answer is provable from the row. That nobody
    answered is not.

    The answer is taken elsewhere — `ApprovalService` decides against its own
    request record — and nothing carries it back: no method on
    `OpportunityService` writes a terminal decision onto the message. So what
    this module states is what it can see, and it points at the request that
    holds the rest.
    """
    row = one_row([message(status=OutreachStatus.AWAITING_APPROVAL,
                           approval_id="apr-77")])
    assert "the row records no answer" in row.why
    assert "and not answered" not in row.why


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
    """Four signals — the status and three columns — not one column. A status is
    one edit away from lying, and the direction that matters here is an approval
    reappearing as a draft.

    Driven by `DECISION_COLUMNS` rather than a list written out again, because
    the query that feeds this queue narrows by the same names and a signal added
    to one place and not the other is the defect that constant exists to close.
    """
    carried = {"approved_fingerprint": "b" * 64,
               "sent_at": NOW,
               "authorized_automated_at": NOW}
    assert set(carried) == set(unreviewed.DECISION_COLUMNS), (
        "a decision signal is not exercised here")
    for column, value in carried.items():
        assert unreviewed.undecided(message(**{column: value})) is False, column


def test_a_message_bound_to_a_pending_request_is_still_waiting() -> None:
    """`approval_id` names the question, not an answer.

    Today the gate writes it only alongside a terminal status, so it does not
    yet appear on an undecided row; the moment the ask is wired back to the
    message it will, and reading it as an act somebody took would drop every
    pending request out of the queue — the drafts a person is actually waiting
    on would be exactly the ones the list of drafts a person is waiting on left
    out. It is here so a reader can go and check the claim the row makes.
    """
    request = message(status=OutreachStatus.AWAITING_APPROVAL,
                      approval_id="apr-77")
    assert unreviewed.undecided(request) is True

    row = one_row([request])
    assert row.state == unreviewed.ASKED
    assert "apr-77" in row.why


def test_an_asked_row_naming_no_request_says_so() -> None:
    """Rather than implying there is somewhere to check. A row whose status says
    a question was put but that names no request is one whose claim nobody can
    verify, and saying "the answer is over there" about a record that does not
    exist is worse than admitting the gap."""
    row = one_row([message(status=OutreachStatus.AWAITING_APPROVAL,
                           approval_id=None)])
    assert row.state == unreviewed.ASKED
    assert "names no approval request" in row.why


def test_a_row_that_names_a_request_is_asked_even_while_it_still_says_draft() -> None:
    """The row is the message-level record, and `approval_id` is one whether or
    not the status moved with it. Reading only the status would call a draft
    bound to a live request one nobody was ever asked about — the same false
    negative, one column over."""
    row = one_row([message(status=OutreachStatus.DRAFT, approval_id="apr-9")])
    assert row.state == unreviewed.ASKED
    assert "approval_id names a request" in row.why
    assert "the status still reads draft" in row.why
    assert "apr-9" in row.why


# --- asked about the company, and not about these words ---------------------


class TestAskedAboutTheBusiness:
    """The middle state, and the records that force it to exist.

    `request_approval` puts the question to a person and leaves the message
    alone: it appends an `approval_requested` entry naming an approval and an
    opportunity. That entry is enough to refute "nobody was ever asked" and not
    enough to establish "this message was asked about", and a module that
    reports only two states has to get one of those two wrong.
    """

    def test_a_business_somebody_was_asked_about_is_not_one_nobody_was(self) -> None:
        row = one_row([message()], events={"biz-1": [asked()]})
        assert row.state == unreviewed.ASKED_ABOUT_THE_BUSINESS
        assert row.reason == unreviewed.ASKED_ABOUT_THE_BUSINESS
        assert row.state != unreviewed.NEVER_ASKED

    def test_the_entry_is_never_read_as_an_ask_about_this_message(self) -> None:
        """The case that decides it. One approval was requested and this
        business holds two drafts, so marking either as `ASKED` would put a
        question on words nobody may have raised."""
        rows = unreviewed.from_records(
            [message(id="msg-whatsapp", channel="whatsapp", recipient=MOBILE),
             message(id="msg-email", channel="email",
                     recipient="owner@example.ae")],
            events={"biz-1": [asked()]}, now=NOW)
        assert len(rows) == 2
        assert {row.state for row in rows} == {
            unreviewed.ASKED_ABOUT_THE_BUSINESS}
        assert unreviewed.ASKED not in {row.state for row in rows}
        for row in rows:
            assert "no identifier ties any of them to this row" in row.why
            assert "do not show which words were meant" in row.why

    def test_the_trace_holds_only_what_this_rows_records_say(self) -> None:
        """The case above is the *argument* for the state, and it is made in the
        module docstring. A trace that made it on every row would be describing
        records the call was never handed: `classify` is given one message and
        one business history, never the row's siblings, so it cannot know what
        else the company holds — and for a business with a single draft the
        sentence is simply false.
        """
        row = one_row([message(channel="whatsapp")], events={"biz-1": [asked()]})
        assert row.state == unreviewed.ASKED_ABOUT_THE_BUSINESS
        for unseen in ("more than one channel", "drafts on", "email"):
            assert unseen not in row.why, unseen

    def test_the_trace_states_what_the_entry_holds_not_what_entries_usually_do(
            self) -> None:
        """`request_approval` writes an approval id and an opportunity id, and
        this fold deliberately keeps entries carrying neither — it never reads
        `opportunity_id` at all. So "each names an approval and an opportunity"
        would be a sentence about the writer of the record rather than about the
        record, and on this entry a false one.
        """
        row = one_row([message()],
                      events={"biz-1": [{"kind": unreviewed.APPROVAL_REQUESTED,
                                         "at": LATER, "detail": {}}]})
        assert row.state == unreviewed.ASKED_ABOUT_THE_BUSINESS
        assert "an approval it does not name" in row.why
        assert "names an approval" not in row.why
        assert "opportunity" not in row.why

    def test_the_request_is_named_and_dated_so_it_can_be_settled(self) -> None:
        """The state says what cannot be answered here. A trace that did not
        name the request would leave a reader with nowhere to take it."""
        row = one_row([message()], events={"biz-1": [asked(approval_id="apr-77")]})
        assert "apr-77" in row.why
        assert "2026-08-25" in row.why

    def test_the_trace_never_claims_the_request_is_still_open(self) -> None:
        """Nothing writes a decision back onto the message, so an entry saying a
        question was put says nothing about whether it was answered. Reading it
        as an open question would send an operator to re-decide something
        somebody already settled."""
        row = one_row([message()], events={"biz-1": [asked()]})
        assert "in the request record" in row.why
        assert "unanswered" not in row.why
        assert "still waiting" not in row.why

    def test_the_rows_own_record_outranks_the_business_history(self) -> None:
        """Most specific record wins. A row that names the question itself is
        answering about these words; the timeline entry is not."""
        row = one_row([message(status=OutreachStatus.AWAITING_APPROVAL)],
                      events={"biz-1": [asked()]})
        assert row.state == unreviewed.ASKED

    def test_another_companys_ask_does_not_reach_this_draft(self) -> None:
        row = one_row([message(business_id="biz-1")],
                      events={"biz-2": [asked(business_id="biz-2")]})
        assert row.state == unreviewed.NEVER_ASKED

    def test_another_factorys_request_is_not_a_question_about_this_company(
            self) -> None:
        """`kind` is namespaced by `factory` and the timeline is shared by all
        fifteen of them, so `approval_requested` on its own does not say who
        was asked what. A roadmap task or a credit spend waiting on somebody is
        not a question put about contacting this business, and reading it as one
        would stand a sentence about a person on a record that never mentioned
        them."""
        row = one_row([message()], events={"biz-1": [
            BusinessEvent(business_id="biz-1", factory="roadmap",
                          kind=unreviewed.APPROVAL_REQUESTED, at=LATER,
                          detail={"approval_id": "apr-99"})]})
        assert row.state == unreviewed.NEVER_ASKED
        assert "apr-99" not in row.why

    def test_the_opportunity_factorys_own_request_still_counts(self) -> None:
        """The other half of the same check: the entry `request_approval`
        actually appends carries the Opportunity Factory's label, and narrowing
        by the namespace must not lose it."""
        row = one_row([message()], events={"biz-1": [
            BusinessEvent(business_id="biz-1",
                          factory=unreviewed.OPPORTUNITY_FACTORY,
                          kind=unreviewed.APPROVAL_REQUESTED, at=LATER,
                          opportunity_id="opp-1",
                          detail={"approval_id": "apr-77"})]})
        assert row.state == unreviewed.ASKED_ABOUT_THE_BUSINESS
        assert "apr-77" in row.why

    def test_an_entry_naming_no_factory_at_all_is_not_excluded(self) -> None:
        """A row a caller assembled without the column is not a record of some
        *other* factory. Dropping it would restore the false negative about a
        person over a missing field — the same failure as reading the row's
        status alone."""
        row = one_row([message()],
                      events={"biz-1": [{"kind": unreviewed.APPROVAL_REQUESTED,
                                         "at": LATER,
                                         "detail": {"approval_id": "apr-77"}}]})
        assert row.state == unreviewed.ASKED_ABOUT_THE_BUSINESS

    def test_several_asks_are_all_carried(self) -> None:
        """Two requests and no way to tell which draft either was about. Naming
        one of them would be picking."""
        row = one_row([message()], events={"biz-1": [
            asked(LATER, approval_id="apr-77"),
            asked(datetime(2026, 8, 27, 9, 0, tzinfo=UTC), approval_id="apr-78")]})
        assert "2 approval_requested entry(ies)" in row.why
        assert "apr-77" in row.why
        assert "apr-78" in row.why

    def test_an_entry_whose_detail_names_no_approval_still_counts(self) -> None:
        """What it establishes is that a question was put, and that survives a
        detail nobody filled in. Dropping the entry would restore the false
        negative over a missing field."""
        row = one_row([message()],
                      events={"biz-1": [{"kind": unreviewed.APPROVAL_REQUESTED,
                                         "at": LATER, "detail": {}}]})
        assert row.state == unreviewed.ASKED_ABOUT_THE_BUSINESS
        assert "an approval it does not name" in row.why

    def test_an_entry_with_no_moment_still_counts(self) -> None:
        """Same reason. When the question was put is not what the state rests
        on; that it was put is."""
        row = one_row([message()],
                      events={"biz-1": [{"kind": unreviewed.APPROVAL_REQUESTED,
                                         "detail": {"approval_id": "apr-77"}}]})
        assert row.state == unreviewed.ASKED_ABOUT_THE_BUSINESS
        assert "at no recorded time" in row.why

    def test_the_ask_is_not_read_as_the_evidence_moving(self) -> None:
        """The two questions stay apart. The same history answers both, and an
        approval request says nothing about whether the ground under the claims
        shifted."""
        row = one_row([message()], events={"biz-1": [asked()]})
        assert row.state == unreviewed.ASKED_ABOUT_THE_BUSINESS
        assert row.blocked_on == ()

    def test_a_condition_still_outranks_it_as_the_headline(self) -> None:
        """`reason` is what to say first, and an unaddressed draft cannot be
        decided about at all — whoever was asked about the company."""
        row = one_row([message(channel="email", recipient="")],
                      events={"biz-1": [asked()]})
        assert row.reason == unreviewed.NO_RECIPIENT
        assert row.state == unreviewed.ASKED_ABOUT_THE_BUSINESS
        assert row.traces[unreviewed.ASKED_ABOUT_THE_BUSINESS]


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


def test_a_replaced_draft_quotes_both_moments_and_claims_no_reading() -> None:
    """Two dated rows for one origin establish that a later message exists, and
    that is the whole of what they establish.

    Nothing anywhere records that anybody looked at a draft — no column on the
    message, no entry on the timeline — so "replaced before anybody read it"
    would be a fact about a person invented out of two timestamps. What the
    trace states instead is both moments, which is what makes "later" something
    a reader can check rather than something they have to take.
    """
    rows = {row.message_id: row for row in unreviewed.from_records(
        [message(id="msg-new", created_at=LATER), message(id="msg-old")],
        now=NOW)}
    why = rows["msg-old"].traces[unreviewed.SUPERSEDED]
    assert not claims_a_reading(why), why
    assert "2026-08-25" in why  # the replacement
    assert "2026-08-19" in why  # these words


def test_a_replaced_draft_somebody_was_asked_about_contradicts_itself_nowhere() -> None:
    """Both fields are answered from different records and both are shown, so
    they have to be able to stand together. A supersession trace saying these
    words went unread would sit directly beside an `ASKED` state saying somebody
    was asked about them — and only one of the two can be true, while only the
    state is something a record supports.
    """
    rows = {row.message_id: row for row in unreviewed.from_records(
        [message(id="msg-old", status=OutreachStatus.AWAITING_APPROVAL),
         message(id="msg-new", created_at=LATER)],
        now=NOW)}
    replaced = rows["msg-old"]
    assert replaced.state == unreviewed.ASKED
    assert replaced.reason == unreviewed.SUPERSEDED
    assert "the question was put to a person" in replaced.traces[unreviewed.ASKED]
    assert not claims_a_reading(replaced.traces[unreviewed.SUPERSEDED])


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
        reevaluated(LATER, Change.DISAPPEARED, kind="outreach_drafted")]})
    assert row.blocked_on == ()


def test_the_same_kind_under_another_factory_is_not_a_reevaluation() -> None:
    """The kind is only half the name. `business_reevaluated` means a second
    look at the site *in the reevaluation factory's vocabulary*, and the
    timeline is shared — so an entry another factory labelled with those words
    is not the record this condition claims to be reading."""
    row = one_row([message()], events={"biz-1": [
        reevaluated(LATER, Change.DISAPPEARED, factory="aivisibility")]})
    assert row.blocked_on == ()


def test_a_reevaluation_naming_no_factory_still_counts() -> None:
    """Absence of the column is not a record of a different factory, and the
    direction of error here is the one that matters: a change nobody is shown
    is a stale claim sent to a stranger."""
    row = one_row([message()], events={"biz-1": [
        {"kind": COMPARED, "at": LATER,
         "detail": {"changes": [{"feature": "arabic",
                                 "change": Change.CONTRADICTED.value}]}}]})
    assert row.reason == unreviewed.EVIDENCE_MOVED


def test_a_change_to_a_feature_these_words_never_mention_still_counts() -> None:
    """Deliberate, and not a missing filter.

    Nothing records which findings a message rests on — an `OutreachMessage`
    carries a `proposal_id` *or* a `mission_id` and no findings, and the manual
    drafts carry neither — and a claim cites a `finding_id` while a change names
    a research `feature`, with no record mapping the two. So a filter by "the
    features these words talk about" could only be a guess, and the guess fails
    towards silence: a reviewer not shown a change approves stale claims about a
    company. The condition therefore says what it can prove — something about
    this business moved after these words were written — and the trace says out
    loud that which change bears on the words is not recorded.
    """
    row = one_row([message(body="Your site has no Arabic version.")],
                  events={"biz-1": [reevaluated(LATER, Change.CONTRADICTED,
                                                feature="opening_hours")]})
    assert row.reason == unreviewed.EVIDENCE_MOVED
    assert "1 change(s) about the business" in row.why
    # Says what moved was the company's record, never that it was this claim.
    assert "recorded nowhere" in row.why


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
    assert "2026-08-25T23:00:00+00:00" in row.traces[unreviewed.EVIDENCE_MOVED]
    assert "+04:00" not in row.traces[unreviewed.EVIDENCE_MOVED]


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
                 status=OutreachStatus.AWAITING_APPROVAL),
         message(id="msg-4", business_id="biz-4")],
        events={"biz-2": [reevaluated(LATER, Change.DISAPPEARED,
                                      business_id="biz-2")],
                "biz-4": [asked(business_id="biz-4")]},
        now=NOW)
    assert len(rows) == 4
    # Every state the module can name is exercised here.
    assert {row.state for row in rows} == set(unreviewed.STATE_KEYS)
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
                 status=OutreachStatus.AWAITING_APPROVAL),
         message(id="msg-4", business_id="biz-4")],
        events={"biz-4": [asked(business_id="biz-4")]},
        now=NOW)
    assert unreviewed.counts(rows) == {
        "total": 4, "never_asked": 2, "asked_about_the_business": 1, "asked": 1,
        "superseded": 0, "addressed_to_nobody": 1, "unreachable": 1,
        "evidence_moved": 0}


def test_every_named_condition_has_a_total() -> None:
    """A tally that omits a reason reads as "none of those", not as "not
    counted". Pairing the keys with the ladder is what stops a fifth condition
    from being named on rows and missing from every total."""
    assert tuple(unreviewed.COUNT_KEYS) == unreviewed.LADDER
    assert set(unreviewed.counts([])) == {
        "total", *unreviewed.STATE_KEYS.values(), *unreviewed.COUNT_KEYS.values()}


def test_every_named_state_has_a_total() -> None:
    """The same guard, one vocabulary over. A third request state that rows
    could carry and no tally counted would read as "none of those" — and this
    module gained its third state precisely because two were not enough."""
    assert set(unreviewed.STATE_KEYS) == {unreviewed.NEVER_ASKED,
                                          unreviewed.ASKED_ABOUT_THE_BUSINESS,
                                          unreviewed.ASKED}
    assert len(set(unreviewed.STATE_KEYS.values())) == 3


def test_the_states_partition_the_list_and_sum_to_the_total() -> None:
    """Unlike the conditions. Every row is in exactly one state, so an operator
    can read these three as a breakdown; reading the condition totals the same
    way would over-count."""
    rows = unreviewed.from_records(
        [message(id="msg-1", business_id="biz-1"),
         message(id="msg-2", business_id="biz-2"),
         message(id="msg-3", business_id="biz-3",
                 status=OutreachStatus.AWAITING_APPROVAL)],
        events={"biz-2": [asked(business_id="biz-2")]}, now=NOW)
    tally = unreviewed.counts(rows)
    assert sum(tally[key] for key in unreviewed.STATE_KEYS.values()) == tally["total"]
    for row in rows:
        assert row.state in unreviewed.STATE_KEYS


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
        "total": 1, "never_asked": 1, "asked_about_the_business": 0, "asked": 0,
        "superseded": 0, "addressed_to_nobody": 1, "unreachable": 0,
        "evidence_moved": 1}


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
