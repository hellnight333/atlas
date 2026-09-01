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
"""

from __future__ import annotations

import inspect
import re
from datetime import UTC, datetime
from pathlib import Path

from atlas_kernel.opportunity.models import OutreachMessage, OutreachStatus
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
    the direction that matters here is an approval reappearing as a draft."""
    for carried in ({"approval_id": "manual-abc123"},
                    {"approved_fingerprint": "b" * 64},
                    {"sent_at": NOW},
                    {"authorized_automated_at": NOW}):
        assert unreviewed.undecided(message(**carried)) is False, carried


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
    across every tenant's outreach is a disclosure."""
    from atlas_kernel.opportunity.repository import OpportunityRepository

    source = inspect.getsource(OpportunityRepository.unreviewed_outreach)
    assert "_require_tenant" in source
    assert "_tenant_predicate" in source
    for forbidden in ("DELETE", "UPDATE", "INSERT", "commit()"):
        assert forbidden not in source, f"the read performs {forbidden}"


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
