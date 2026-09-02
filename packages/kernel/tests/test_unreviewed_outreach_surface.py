"""Getting the reason a draft is unreviewed as far as a person.

Two halves of that already existed and neither of them reaches anybody.
`outreach.unreviewed` derives, per drafted message, why nobody has decided about
it, and reads nothing. `OpportunityRepository.unreviewed_outreach_records` reads
the records it derives from, and derives nothing. Between them there was no
route and no screen, so fourteen messages written to strangers sat undecided
with the explanation for each one computable and unread.

This is that last stretch — `/api/missions/outreach-unreviewed` and the console
page that draws it — and what is under test is the stretch, not either half.
Neither derivation is re-checked here; both have their own suites in
`test_unreviewed_outreach.py` and `test_unreviewed_outreach_records.py`.

Four things can go wrong in the join, and each one ends with a person acting on
something that is not true:

* **The reason gets re-worded on the way out.** Two answers to "why has nobody
  decided this" is two answers, and the one a person reads before writing to a
  stranger would be the untested one.
* **The records get narrowed before the reader sees them.** Whether a draft was
  replaced is a fact about the messages *around* it, so a route that passed on
  only the messages it was asked about would turn a superseded draft back into
  current words somebody then sends.
* **The queue grows a control.** A list of undecided things is the most tempting
  place in this system to put a button that decides all of them; approving is a
  decision about one message bound to the words a person actually read, and it
  stays where it is.
* **The screen collapses the two questions.** "Nobody has looked at this" and
  "this cannot be answered yet" are different situations with different next
  moves, and one badge carrying both makes them the same amber dot.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atlas_kernel.auth import Scope, User
from atlas_kernel.auth import api as auth_api
from atlas_kernel.auth.models import hash_password
from atlas_kernel.auth.store import AuthStore
from atlas_kernel.mission import api as mission_api
from atlas_kernel.opportunity.models import (
    BusinessEvent,
    OutreachMessage,
    OutreachStatus,
)
from atlas_kernel.outreach import unreviewed

A, B = "tenant-alpha", "tenant-beta"

PATH = "/api/missions/outreach-unreviewed"

WRITTEN = datetime(2026, 8, 19, 13, 35, tzinfo=UTC)
LATER = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)

#: A number the audited clinics publish, and one WhatsApp accepts.
MOBILE = "0501029104"


def _user(tenant: str, *scopes: Scope) -> User:
    return User(username=f"u-{tenant}",
                password_hash=hash_password("test-only-password"),
                tenant_id=tenant,
                scopes=frozenset(scopes or frozenset(Scope)))


def _message(**fields) -> OutreachMessage:
    """One drafted message, with only what the test cares about stated."""
    fields.setdefault("proposal_id", "prop-1")
    fields.setdefault("business_id", "biz-1")
    fields.setdefault("channel", "email")
    fields.setdefault("recipient", "hello@clinic.example")
    fields.setdefault("subject", "Your website")
    fields.setdefault("body", "Some words about the site we built.")
    fields.setdefault("status", OutreachStatus.DRAFT)
    fields.setdefault("created_at", WRITTEN)
    return OutreachMessage(**fields)


def _declared() -> list:
    """The routes this module declares, in the order it declares them.

    Read from `build_router()` and never from `app.routes`. FastAPI wraps an
    included router in an `_IncludedRouter` that carries no `.path`, so walking
    a composed application's route list finds no `/api/missions` entry at all
    and every question asked of it answers "absent" — which is how the first
    attempt at this surface failed two of its own tests on a route the tests
    had already fetched successfully. `test_app_composition.py` reads the
    OpenAPI document for the same reason, and `test_mission_models.py` reads
    `build_router().routes` exactly like this to pin declaration order. The
    prefix is on the router, so these paths are the full ones a client calls.
    """
    return [route for route in mission_api.build_router().routes
            if hasattr(route, "methods")]


class _Records:
    """The repository read, stated rather than run.

    The read has its own suite against a real database. What matters here is
    what the route does with the bundle it gets back, so the bundle is handed
    over directly and the call is recorded.
    """

    def __init__(self, bundle: dict) -> None:
        self.bundle = bundle
        self.calls: list[dict] = []

    def unreviewed_outreach_records(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        return dict(self.bundle)


def _bundle(messages, *, only=None, names=None, events=None) -> dict:
    return {"messages": list(messages),
            "only": list(only if only is not None else [m.id for m in messages]),
            "names": dict(names or {"biz-1": "Jumeirah Dental"}),
            "events": dict(events or {})}


@pytest.fixture
def app(tmp_path):
    application = FastAPI()
    auth_api.install(application, AuthStore())
    mission_api.install(application)
    application.state.mission_events = []
    application.state.mission_sink = application.state.mission_events.append
    application.state.repository_root = str(tmp_path)
    return application


@pytest.fixture
def client(app, monkeypatch):
    holder = {"user": _user(A)}
    monkeypatch.setattr(AuthStore, "authenticate", lambda self, token: holder["user"])

    class Acting(TestClient):
        def acting_as(self, user: User):
            holder["user"] = user
            return self

    with Acting(app) as test_client:
        test_client.headers["Authorization"] = "Bearer test"
        yield test_client


def _records(app, bundle: dict) -> _Records:
    """The repository is built lazily on first use, so stating it here is the
    only way a test controls what the route reads."""
    stub = _Records(bundle)
    app.state.opportunity_repository = stub
    return stub


# ==================================================== the route that surfaces it


class TestTheRoute:

    def test_it_is_not_swallowed_by_the_mission_detail_handler(
            self, client, app) -> None:
        """`/{mission_id}` matches a literal segment happily. Registered after
        it, this would be served as a mission called `outreach-unreviewed` — a
        404 that reads as "nothing is waiting", which is the one answer a queue
        of undecided things must never give by accident."""
        _records(app, _bundle([]))

        response = client.get(PATH)

        assert response.status_code == 200
        assert "unreviewed" in response.json()
        paths = [route.path for route in _declared()]
        assert paths.index(PATH) < paths.index("/api/missions/{mission_id}")

    def test_it_says_which_business_which_channel_when_and_how_long(
            self, client, app) -> None:
        """The five facts an operator triages on. A row missing any of them
        cannot be acted on without opening the database."""
        _records(app, _bundle([_message(id="m-1", channel="whatsapp",
                                        recipient=MOBILE)]))

        row = client.get(PATH).json()["unreviewed"][0]

        assert row["business_id"] == "biz-1"
        assert row["business_name"] == "Jumeirah Dental"
        assert row["channel"] == "whatsapp"
        assert row["drafted_at"].startswith("2026-08-19")
        assert isinstance(row["waiting_days"], int) and row["waiting_days"] > 0
        assert row["state"] == unreviewed.NEVER_ASKED
        assert row["reason"] == unreviewed.NEVER_ASKED
        assert row["why"], "a reason with no record behind it is an assertion"

    def test_a_draft_nobody_asked_about_is_told_apart_from_one_that_cannot_be_answered(
            self, client, app) -> None:
        """The distinction the whole surface exists to make. Both rows are
        undecided; one is waiting on a person and the other could not be
        answered by anybody today, and they must not arrive identical."""
        waiting = _message(id="m-waiting")
        unanswerable = _message(id="m-nobody", business_id="biz-2",
                                proposal_id="prop-2", recipient="  ")
        _records(app, _bundle([waiting, unanswerable],
                              names={"biz-1": "Jumeirah Dental",
                                     "biz-2": "Marina Vets"}))

        body = client.get(PATH).json()
        rows = {row["message_id"]: row for row in body["unreviewed"]}

        assert rows["m-waiting"]["state"] == unreviewed.NEVER_ASKED
        assert rows["m-waiting"]["blocked_on"] == []
        assert rows["m-nobody"]["blocked_on"] == [unreviewed.NO_RECIPIENT]
        assert rows["m-nobody"]["reason"] == unreviewed.NO_RECIPIENT
        assert body["counts"]["total"] == 2
        assert body["counts"]["never_asked"] == 2
        assert body["counts"]["addressed_to_nobody"] == 1

    def test_a_question_put_about_the_business_is_not_a_question_about_these_words(
            self, client, app) -> None:
        """The middle state has to survive the trip. Collapsing it to either
        neighbour is a fabricated fact about a person — in one direction that
        nobody was asked, in the other that they were asked about this."""
        asked = BusinessEvent(business_id="biz-1", kind="approval_requested",
                              at=LATER, detail={"approval_id": "ap-7"})
        _records(app, _bundle([_message(id="m-1")],
                              events={"biz-1": [asked]}))

        row = client.get(PATH).json()["unreviewed"][0]

        assert row["state"] == unreviewed.ASKED_ABOUT_THE_BUSINESS
        assert "ap-7" in row["why"]

    def test_it_does_not_word_the_reason_itself(self, client, app) -> None:
        """Byte for byte the kernel's own sentence. A route that paraphrased
        would be a second answer to "why has nobody decided this", and it would
        be the one a person reads."""
        messages = [_message(id="m-1"), _message(id="m-2", recipient="")]
        bundle = _bundle(messages)
        _records(app, bundle)

        served = client.get(PATH).json()["unreviewed"]
        # The same records, straight through the module. `now` differs by the
        # duration of the request, and `waiting_days` is whole days, so the
        # wording that carries a day count still matches.
        derived = unreviewed.from_records(**_bundle(messages))

        assert [row["why"] for row in served] == [row.why for row in derived]
        assert [row["traces"] for row in served] == [dict(row.traces)
                                                     for row in derived]

    def test_it_hands_over_every_record_it_was_given(self, client, app) -> None:
        """Supersession is a fact about the messages around a draft. A route
        that narrowed `messages` to the ones it was asked about would report a
        replaced draft as the current words for that origin, and somebody would
        send them."""
        old = _message(id="m-old", created_at=WRITTEN)
        new = _message(id="m-new", created_at=LATER)
        # `only` names the old one alone — exactly what a limit produces.
        _records(app, _bundle([old, new], only=["m-old"]))

        rows = client.get(PATH).json()["unreviewed"]

        assert [row["message_id"] for row in rows] == ["m-old"]
        assert rows[0]["blocked_on"] == [unreviewed.SUPERSEDED]
        assert "m-new" in rows[0]["why"]

    def test_a_message_somebody_decided_about_is_not_listed(
            self, client, app) -> None:
        """Listing it invites a second decision on a message that already has
        one. The two approved by hand on 2026-08-19 are exactly that case."""
        decided = _message(id="m-approved",
                           status=OutreachStatus.APPROVED_FOR_MANUAL_SEND,
                           approved_fingerprint="fp-1")
        _records(app, _bundle([decided, _message(id="m-1")]))

        rows = client.get(PATH).json()["unreviewed"]

        assert [row["message_id"] for row in rows] == ["m-1"]

    def test_the_records_are_read_for_the_account_s_own_tenant(
            self, client, app) -> None:
        """There is no argument in which to ask for somebody else's drafts.
        One tenant reading another's undecided outreach is a disclosure."""
        stub = _records(app, _bundle([]))

        client.acting_as(_user(B)).get(PATH)

        assert stub.calls[-1]["tenant"] == B

    def test_a_full_window_says_there_may_be_more(self, client, app) -> None:
        """A truncation nobody is told about is how "14 drafts" comes to mean
        "the 14 we happened to look at"."""
        _records(app, _bundle([_message(id="m-1")]))

        full = client.get(PATH, params={"limit": 1}).json()
        roomy = client.get(PATH, params={"limit": 50}).json()

        assert full["limit"] == 1
        assert "more" in full["note"]
        assert "more" not in roomy["note"]

    def test_a_window_of_nothing_is_refused_rather_than_answered_empty(
            self, client, app) -> None:
        """The truncation note cannot cover a page nobody asked to fill.

        `limit=0` — and any negative, which the read answers the same way —
        returns no candidates, so the response would carry an empty list, a
        zero count and a note about what is *not* in it, with nothing anywhere
        saying the window was shut. That is the 404-that-reads-as-an-empty-queue
        this route was declared early to avoid, reached through a query
        parameter instead: the console draws exactly that body as every message
        on file having been decided about.
        """
        stub = _records(app, _bundle([_message(id="m-1")]))

        for shut in (0, -1):
            response = client.get(PATH, params={"limit": shut})

            assert response.status_code == 400, shut
            assert "unreviewed" not in response.json(), (
                "a refused window still answers with a list, so a caller that "
                "reads the body before the status sees an empty queue")
            assert "waiting" in response.json()["detail"]
        assert stub.calls == [], (
            "the records were read for a window the route had already decided "
            "it could not answer honestly")

    def test_nothing_on_this_path_decides_anything(self, client, app) -> None:
        """`GET` and `READ`, by design rather than as a first instalment. A
        list of undecided messages is the most tempting place in this system to
        grow a control that decides all of them at once."""
        _records(app, _bundle([_message(id="m-1")]))

        for verb in (client.post, client.put, client.delete):
            assert verb(PATH).status_code in (404, 405), verb

        served = [route for route in _declared() if route.path == PATH]
        assert served, "the route is not mounted"
        assert set().union(*(route.methods for route in served)) <= {"GET", "HEAD"}

    def test_looking_needs_only_read(self, client, app) -> None:
        """Requiring EXECUTE to look would make the queue invisible to the
        people it is for, which is the same as not having built it."""
        _records(app, _bundle([_message(id="m-1")]))

        response = client.acting_as(_user(A, Scope.READ)).get(PATH)

        assert response.status_code == 200
        assert len(response.json()["unreviewed"]) == 1

    def test_the_handler_neither_writes_nor_re_derives(self) -> None:
        """Read from the module, because the docstring is exactly what stays
        true while the code stops being. The docstring is also why the scan
        starts after it: the prose legitimately says the word "approves", and a
        check that could not tell a sentence from a call would either fail on
        the explanation or be written loosely enough to miss the call."""
        source = Path(mission_api.__file__).read_text(encoding="utf-8")
        start = source.index('@router.get("/outreach-unreviewed")')
        handler = source[start:source.index('@router.get("/{mission_id}")', start)]
        opened = handler.index('"""')
        body = handler[handler.index('"""', opened + 3) + 3:]

        for call in ("_append(", "approve(", "send(", "record_event(",
                     "commit(", "delete(", "save("):
            assert call not in body, (
                f"the unreviewed-draft route reaches for {call!r}; surfacing a "
                "draft is not acting on it")
        # The bundle goes over as the reader's own arguments. Unpacking and
        # rebuilding it here is where a third vocabulary starts.
        assert "from_records(**" in body, (
            "the route rebuilds the record bundle instead of handing it over, "
            "which is a second place for the two halves to disagree")


# ================================================= the screen an operator reads


@pytest.fixture(scope="module")
def console() -> str:
    from atlas_kernel.qevik.app import CONSOLE

    return (CONSOLE / "index.html").read_text(encoding="utf-8")


def _function(source: str, opening: str) -> str:
    """One top-level function of the console, from its opening to its closing
    brace in the first column. Every nested brace in this file is indented."""
    start = source.index(opening)
    end = source.index("\n}", start)
    return source[start:end]


class TestTheScreen:

    def test_the_console_asks_the_route_for_them(self, console) -> None:
        assert PATH in console, (
            "nothing in the console reads the unreviewed drafts, so the reason "
            "each one is undecided reaches nobody")
        assert "views.outreach" in console
        assert "['outreach', 'Outreach']" in console, (
            "the page has no destination, so it is reachable only by typing a "
            "fragment nobody has been told about")

    def test_every_draft_says_business_channel_when_and_how_long(
            self, console) -> None:
        row = _function(console, "function draftedRow(")

        for shown in ("r.business_name", "r.channel", "r.drafted_at",
                      "r.waiting_days"):
            assert shown in row, (
                f"a draft is drawn without {shown}; an operator cannot triage "
                "a message without knowing who it is to and how long it has sat")

    def test_the_two_questions_are_drawn_apart(self, console) -> None:
        """One badge carrying both is how "nobody has looked at this" and "this
        cannot be answered yet" become the same amber dot."""
        row = _function(console, "function draftedRow(")

        assert "r.state" in row and "r.blocked_on" in row
        assert row.index("Has anybody been asked") < row.index("To settle")
        # Drawn even when empty. A section that disappears reads as "not
        # shown", which is the opposite of what an absence of conditions means.
        assert "Nothing in the record has to be settled" in row, (
            "a draft with nothing to settle first simply omits the band, so it "
            "is indistinguishable from one whose conditions were not drawn")

    def test_the_reason_is_the_kernel_s_own_wording(self, console) -> None:
        """The console may not own this vocabulary. It renders the trace the
        kernel wrote, and the only thing it may map a state name to is a
        colour."""
        row = _function(console, "function draftedRow(")
        assert "traces[r.state]" in row and "traces[b]" in row

        for name in (unreviewed.NEVER_ASKED, unreviewed.ASKED,
                     unreviewed.ASKED_ABOUT_THE_BUSINESS):
            for mapped in re.finditer(re.escape(name) + r"\s*:\s*'([^']*)'",
                                      console):
                assert mapped.group(1) in {"", "ok", "bad", "warn", "run", "wait"}, (
                    f"the console writes its own meaning for {name!r}; it must "
                    "render the sentence the kernel returned")

    def test_the_screen_offers_no_way_to_approve_or_send(self, console) -> None:
        """A button on a list of fourteen is how fourteen strangers get written
        to with one click. Approving is one message at a time, bound to the
        words a person read, and it lives on the mission that composed them."""
        drawn = (_function(console, "views.outreach = async")
                 + _function(console, "function unreviewedOutreach(")
                 + _function(console, "function draftedRow("))

        for control in ("<button", "API.post", "API.put", "API.del",
                        "data-approve", "outreach/approve", "data-respond"):
            assert control not in drawn, (
                f"the unreviewed-draft screen carries {control!r}; it reads, "
                "and the decision boundary is elsewhere")

    def test_an_undated_draft_is_not_drawn_as_nought_days(self, console) -> None:
        """A row that records no moment has no waiting time, and `0` is a real
        answer for a draft written today. Printing one as the other invents a
        fact about the only message nobody can otherwise account for."""
        row = _function(console, "function draftedRow(")

        assert row.index("r.drafted_at") < row.index("r.waiting_days"), (
            "the day count is printed without first checking the row carries a "
            "date, so an undated draft reads as having waited no time at all")
        assert "not dated" in row

    def test_a_failed_read_is_not_drawn_as_an_empty_queue(self, console) -> None:
        """The most expensive thing this page could say wrongly is that no
        drafts are waiting: it reads as every message having been dealt with,
        and a failed read must never be able to produce it."""
        view = _function(console, "views.outreach = async")

        assert "fail(" in view
        assert view.index("catch") < view.index("unreviewedOutreach(found)")
