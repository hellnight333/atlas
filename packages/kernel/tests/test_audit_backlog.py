"""Why an observation is old: a queue position, or a pass that stopped.

`audit_freshness` reports that most of the population was observed more than a
week ago. That reads as an emergency and, at 359 recorded sites and forty a
night, is a nine-night rotation doing precisely what it was built to do — and
nothing on the operator's screen said which of the two it was.

So the work here is a **report, not a change**. Fetching more sites a night
would make the number smaller and would be a decision about other people's
bandwidth, taken to improve a screen. What is added is the arithmetic that
turns the number from alarming into explained, plus the two conditions under
which it is *not* explained and somebody does need to act:

* the pass has stopped, measured from the observation it writes — never from
  `website_verified`, which refreshed nightly for twelve days while nothing
  was being read, and never from another writer's `website_audited` either: a
  hand-run reconcile appends a row stamped now that read nothing, and letting
  it answer for the pass rebuilds the same blind spot; and
* the rotation comes round inside a week and sites are stale anyway, which is
  what re-reading the alphabetically first forty did while succeeding nightly.

And the arithmetic is over the population the pass can actually fetch, at the
throughput it actually achieves — a `mailto:` row is never a night's work, and
until the scheme filter moved into the query it could still spend one.

The pure arithmetic is tested pure, because every boolean above has to hold for
populations this database will never contain. The database tests assert the
things only the database can settle: that the two numbers standing beside each
other on one screen are the same number, that a turn is not an observation,
that whose reading it was decides whether it counts as the pass being alive, and
that a record the rotation does not contain is reported as unreachable rather
than as a turn that is coming.
"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from atlas_kernel import db
from atlas_kernel.db import SessionLocal
from atlas_kernel.mission.toolrunner import NIGHTLY_SITE_LIMIT, targets_map_for
from atlas_kernel.opportunity import coverage
from atlas_kernel.opportunity.audit_import import audit_event
from atlas_kernel.opportunity.coverage import A_WEEK_IN_NIGHTS, backlog
from atlas_kernel.opportunity.models import Business, BusinessEvent
from atlas_kernel.opportunity.repository import (
    OBSERVED_EVENT,
    PASS_OBSERVATION,
    PASS_TURN,
    ROTATION_CEILING,
    VERIFIED_EVENT,
    OpportunityRepository,
    rotation_size,
)

#: The production shape at the time of writing: 359 recorded sites, forty a
#: night, a nine-night sweep. Everything below is a departure from this.
POPULATION = {"sites": 359, "older_than_a_week": 200, "per_night": 40,
              "nights_since_an_observation": 0.4, "nights_since_a_turn": 0.4}


@pytest.fixture(scope="module", autouse=True)
def schema():
    db.init_db()


@pytest.fixture
def repo() -> OpportunityRepository:
    return OpportunityRepository()


def _business(repo: OpportunityRepository, website: str = "") -> Business:
    """A business with a website nothing else in the suite shares.

    The counts here are population-wide, so a shared address would make a
    `+1` assertion depend on which other tests had run.
    """
    return repo.save_business(Business(
        name="Al Waha Dental", geography="United Arab Emirates",
        website=website or f"https://{uuid4().hex}.backlog.test",
        sources=["seed"]))


def _unfetchable(repo: OpportunityRepository, website: str,
                 first_seen_at: datetime | None = None) -> Business:
    """A recorded address the rotation will never hand to a fetcher.

    Real: sources report `mailto:` values and bare hostnames, and
    `businesses_by_website` has always refused them rather than guessing a
    scheme in front of an address somebody typed by hand.
    """
    return repo.save_business(Business(
        name="Al Waha Dental", geography="United Arab Emirates",
        website=website, sources=["seed"],
        **({"first_seen_at": first_seen_at} if first_seen_at else {})))


def _a_reading_the_pass_wrote(business: Business) -> BusinessEvent:
    """What the nightly pass records, built by the pass's own writer.

    `read_by` is the mark: `toolrunner` sets it to `recipe:<id>/http-fetch` for
    every page it actually fetched, and nothing else that appends this kind
    sets it at all. Constructed through `audit_event` rather than by hand so a
    change to what the pass records fails this rather than passing it.
    """
    return audit_event(business.id,
                       {"url": business.website or "", "findings": []},
                       read_by="recipe:verify-recorded-websites/http-fetch")


def _clean(*business_ids: str) -> None:
    with SessionLocal() as session:
        for business_id in business_ids:
            for table, column in (("atlas_business_events", "business_id"),
                                  ("atlas_findings", "business_id"),
                                  ("atlas_businesses", "id")):
                session.execute(
                    text(f"DELETE FROM {table} WHERE {column} = :b"),
                    {"b": business_id})
        session.commit()


# ------------------------------------------------------- the arithmetic


def test_the_cadence_is_the_population_over_what_one_night_takes():
    """Nine nights for 359 sites at forty, and nine is more than a week.

    The number an operator needs in order to read "most of them are older than
    a week" as a schedule rather than as a fault.
    """
    found = backlog(**POPULATION)
    assert found.nights_for_a_full_sweep == 9
    assert found.the_pass_is_running
    assert found.the_cadence_explains_the_age

    summary = found.summary()
    # The contract a production probe checks independently, named here so it
    # cannot be renamed by a refactor that only reads this module.
    for key in ("sites", "older_than_a_week", "nights_for_a_full_sweep",
                "the_cadence_explains_the_age", "the_pass_is_running"):
        assert key in summary, f"{key} is not reported"
    assert summary["nights_for_a_full_sweep"] == 9
    assert "9 nights" in summary["note"] and "40 sites a night" in summary["note"]


def test_a_rotation_that_comes_round_inside_a_week_never_explains_stale_sites():
    """The alphabetical-forty bug, which succeeded nightly for 319 sites.

    A pass that visits everyone in two nights and leaves 200 of them older
    than a week is running and not reaching them, and that must not be drawn
    as a backlog draining.
    """
    quick = backlog(**{**POPULATION, "sites": 80})
    assert quick.nights_for_a_full_sweep == 2
    assert quick.the_pass_is_running
    assert not quick.the_cadence_explains_the_age
    assert "not account for the age" in quick.summary()["note"]

    # And the boundary, which is eight and not seven: `audit_freshness` counts
    # a site fresh within a week if it was read inside eight days, so a sweep
    # of exactly eight nights should leave nothing stale.
    exactly = backlog(**{**POPULATION, "sites": 40 * A_WEEK_IN_NIGHTS})
    assert exactly.nights_for_a_full_sweep == A_WEEK_IN_NIGHTS
    assert not exactly.the_cadence_explains_the_age
    assert backlog(**{**POPULATION,
                      "sites": 40 * A_WEEK_IN_NIGHTS + 1}
                   ).the_cadence_explains_the_age


def test_nothing_stale_needs_no_explaining():
    """A population with nothing older than a week is not a failed excuse."""
    assert backlog(**{**POPULATION, "sites": 80, "older_than_a_week": 0}
                   ).the_cadence_explains_the_age


def test_a_stopped_pass_is_never_explained_by_the_cadence():
    """The failure this whole surface must not print over.

    A nine-night sweep explains an old observation only while the sweep is
    happening. Twelve days of silence with the same arithmetic is a stall, and
    reporting it as a queue would be the most expensive sentence on the page.
    """
    stopped = backlog(**{**POPULATION, "nights_since_an_observation": 12.0})
    assert not stopped.the_pass_is_running
    assert not stopped.the_cadence_explains_the_age


def test_a_turn_is_not_an_observation():
    """`website_verified` moved every night while nothing was being read.

    Twelve days of it. So the pass being alive is measured from the record
    that carries observations, and a fresh turn beside a stale observation is
    reported under its own name rather than as health.
    """
    blind = backlog(**{**POPULATION, "nights_since_an_observation": 12.0,
                       "nights_since_a_turn": 0.3})
    assert not blind.the_pass_is_running, (
        "a site taking its turn made the pass look alive; that is the "
        "twelve-day failure, restored")
    assert blind.the_pass_ran_without_observing
    assert not blind.the_cadence_explains_the_age

    # And the healthy case does not claim it.
    assert not backlog(**POPULATION).the_pass_ran_without_observing


def test_a_turn_the_rotation_already_gave_is_not_a_queue_position():
    """The measured answer to whether the refresh path reaches these sites.

    The ordering promises every site a turn; it cannot promise a reading. A
    server that refused, timed out or returned something that is not HTML
    takes its turn and is deliberately not re-observed — so it cycles for
    ever, and "wait for the sweep" is a promise nothing will keep.
    """
    plain = backlog(**POPULATION)
    assert plain.unread_after_a_turn == 0
    assert not plain.waiting_will_not_clear_these

    stuck = backlog(**{**POPULATION, "unread_after_a_turn": 43})
    assert stuck.waiting_will_not_clear_these
    assert "will not clear those" in stuck.summary()["note"]
    # Kept out of the cadence verdict on purpose: this is a finding about
    # reach, which `Coverage` already counts and names as ours or theirs.
    assert stuck.the_cadence_explains_the_age

    # And never larger than the population it is part of, whatever it is
    # handed: a subset bigger than its set is a reader people stop believing.
    assert backlog(**{**POPULATION, "older_than_a_week": 5,
                      "unread_after_a_turn": 900}).unread_after_a_turn == 5


def test_a_record_the_rotation_will_never_select_is_not_a_queue_position():
    """The other half of "does the refresh path reach them", and the worse half.

    A turn that produced no reading is at least evidence of a turn. These have
    none and never will: one night's work is one *address*, so only the earliest
    business recorded against a website is ever fetched, and an address the
    fetcher is never handed is not in the sweep at all. Both keep an observation
    for ever, both count in `older_than_a_week`, and the ordering says of every
    stale record alike that its turn is coming.
    """
    plain = backlog(**POPULATION)
    assert plain.never_in_the_rotation == 0
    assert plain.beyond_the_rotations_reach == 0
    assert not plain.waiting_will_not_clear_these

    orphaned = backlog(**{**POPULATION, "never_in_the_rotation": 7})
    assert orphaned.waiting_will_not_clear_these, (
        "a record no turn is ever coming to was left inside the queue, which "
        "is the one sentence this surface exists to stop being said")
    assert orphaned.beyond_the_rotations_reach == 7
    assert "not in the rotation at all" in orphaned.summary()["note"]
    # A finding about reach, like the count beside it, and kept out of the
    # cadence verdict for the same reason: `Coverage` already names reach.
    assert orphaned.the_cadence_explains_the_age

    # Disjoint in the query, so they add rather than overlap.
    both = backlog(**{**POPULATION, "unread_after_a_turn": 6,
                      "never_in_the_rotation": 4})
    assert both.beyond_the_rotations_reach == 10
    assert "6 have already had a turn" in both.summary()["note"]
    assert "4 are not in the rotation" in both.summary()["note"]

    # And never more than the population between them: two parts that sum to
    # more than their whole is the same broken reader, arrived at by addition.
    crowded = backlog(**{**POPULATION, "older_than_a_week": 5,
                         "unread_after_a_turn": 4,
                         "never_in_the_rotation": 900})
    assert crowded.beyond_the_rotations_reach == 5
    assert crowded.never_in_the_rotation == 1

    # And it is genuinely on the page, beside the count it is added to.
    console = Path("apps/control/src/index.html").read_text(encoding="utf-8")
    assert "b.never_in_the_rotation" in console and \
           "b.beyond_the_rotations_reach" in console, (
        "records the sweep will never select are counted and never shown, so "
        "an operator is told to wait for a turn that is not coming")


def test_never_observed_is_not_an_old_observation():
    """`None`, never a large number.

    A system that has never observed anything and one that stopped observing a
    fortnight ago are different facts, and a reader that rendered them the same
    way would report a pass that never started as one that stopped.
    """
    never = backlog(**{**POPULATION, "nights_since_an_observation": None,
                       "nights_since_a_turn": None})
    assert never.summary()["nights_since_an_observation"] is None
    assert not never.the_pass_is_running
    assert not never.the_pass_ran_without_observing, (
        "nothing has ever taken a turn either, so there is no pass that ran "
        "without observing — there is no pass")


def test_an_empty_population_is_not_a_division_by_zero():
    """No recorded sites is a real state, and it is zero nights, not a crash."""
    assert backlog(sites=0, older_than_a_week=0,
                   per_night=40).nights_for_a_full_sweep == 0
    assert backlog(sites=10, older_than_a_week=0,
                   per_night=0).nights_for_a_full_sweep == 0


# --------------------------------------------- the cadence that is reported
#                                                is the cadence that runs


def test_the_reported_cadence_is_the_limit_the_pass_actually_fetches():
    """One number, or the report describes a pass that is not running.

    Read from the scheduled path's own signature rather than repeated here: a
    limit changed in `targets_map_for` and not here would give an operator
    arithmetic about forty sites a night while sixty were being fetched.
    """
    declared = inspect.signature(targets_map_for).parameters["limit"].default
    assert declared == NIGHTLY_SITE_LIMIT, (
        "the nightly pass fetches a number of sites that the backlog report "
        "does not know about")
    # And through the clamp the query applies, so the report cannot describe a
    # rotation size the query would have refused.
    assert rotation_size(NIGHTLY_SITE_LIMIT) == NIGHTLY_SITE_LIMIT
    assert rotation_size(10_000) == ROTATION_CEILING
    assert rotation_size(0) == 1


def test_the_observation_kind_is_the_one_the_pass_writes():
    """The constant the readers use, against the writer's literal.

    Everything on this surface counts `website_audited` rows. A writer that
    wrote a different kind would empty every one of these numbers while the
    pass ran perfectly, and nothing else in the suite compares the two.
    """
    written = audit_event("business-1", {"url": "https://x.test",
                                         "findings": []})
    assert written.kind == OBSERVED_EVENT
    assert VERIFIED_EVENT != OBSERVED_EVENT


def test_the_pass_signs_the_rows_the_health_reading_looks_for():
    """`PASS_OBSERVATION` and `PASS_TURN`, against the writer's own literals.

    Three other things append `website_audited` and one appends
    `website_verified`, so "is the nightly pass alive" is answered by narrowing
    to the rows the pass signs: `read_by` on the reading, `recipe:` on the turn.
    A pass that stopped signing them would report itself stopped — a false alarm
    is the safe direction and still a bug, and nothing else in the suite
    compares the predicates against the code that has to satisfy them.
    """
    pass_source = Path("packages/kernel/atlas_kernel/mission/toolrunner.py"
                       ).read_text(encoding="utf-8")
    assert 'read_by = f"recipe:{self._recipe.id}/http-fetch"' in pass_source, (
        "the pass no longer signs its readings, so PASS_OBSERVATION matches "
        "nothing and the console reports a healthy pass as stopped")
    assert 'actor=f"recipe:{self._recipe.id}"' in pass_source, (
        "the pass no longer signs its turns, so PASS_TURN matches nothing")
    assert "recipe:" in PASS_OBSERVATION and "read_by" in PASS_OBSERVATION
    assert "corrects" in PASS_OBSERVATION, (
        "a correction copies `read_by` forward from the reading it corrects, "
        "so `recipe:` alone lets a row that read nothing certify the pass")
    assert "recipe:" in PASS_TURN


def test_the_backlog_is_reported_where_freshness_already_is():
    """Structural, and asserted through the route rather than a comment.

    The age is on the coverage screen; an explanation of the age anywhere else
    is an explanation nobody reads at the moment they need it.
    """
    source = Path("packages/kernel/atlas_kernel/mission/api.py").read_text()
    tree = ast.parse(source)
    calls: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            calls[node.name] = {
                inner.func.attr for inner in ast.walk(node)
                if isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)}
    assert "audit_freshness" in calls["coverage"], (
        "the coverage route no longer carries freshness; this test is "
        "asserting the wrong surface")
    assert "audit_backlog" in calls["coverage"], (
        "the backlog is not surfaced where the operator sees freshness, so "
        "the number that alarms them still has no explanation beside it")


def test_the_route_reads_freshness_once_and_hands_it_to_the_backlog():
    """One response may not carry two answers to the same question.

    The backlog explains `older_than_a_week`, and the response prints that
    number twice. Read twice, an audit recorded between the two reads is enough
    to make the explanation refer to a number the page is not showing — and a
    screen caught contradicting itself is one nobody believes again.

    Asserted on the call rather than on the docstring: this is a property of
    how the route is wired, and a comment saying so is not the wiring.
    """
    tree = ast.parse(Path("packages/kernel/atlas_kernel/mission/api.py")
                     .read_text(encoding="utf-8"))
    route = next(node for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef) and node.name == "coverage")
    backlog_calls = [node for node in ast.walk(route)
                     if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Attribute)
                     and node.func.attr == "audit_backlog"]
    assert len(backlog_calls) == 1
    passed = {kw.arg for kw in backlog_calls[0].keywords}
    assert "freshness" in passed, (
        "the route lets the backlog read freshness for itself, so the two "
        "counts in one response come from two moments and can disagree")

    freshness_calls = [node for node in ast.walk(route)
                       if isinstance(node, ast.Call)
                       and isinstance(node.func, ast.Attribute)
                       and node.func.attr == "audit_freshness"]
    assert len(freshness_calls) == 1, (
        "freshness is read more than once while assembling one response")


def test_the_backlog_can_be_handed_the_freshness_the_caller_already_read(repo):
    """And uses it, rather than reading its own and reporting that.

    A caller that has already read freshness is the only one that can promise
    the two numbers match, so being handed one has to actually decide the
    answer. Handed a figure no query would produce, the report must carry it.
    """
    handed = repo.audit_backlog(freshness={"older_than_a_week": 4242})
    assert handed["older_than_a_week"] == 4242
    # And on its own it still reads one, so the standalone call is unchanged.
    assert repo.audit_backlog()["older_than_a_week"] == \
           repo.audit_freshness()["older_than_a_week"]


def test_no_field_here_is_a_name_the_console_refuses_to_render():
    """The console may not decide whether a worker is healthy.

    It is held to that by banning a list of names outright — `stale_after`
    among them, from `claims.stale_after_seconds` — because a surface that
    compares a heartbeat against a threshold is the failure, and a coarse ban
    is the cheap way to stop it. The first name given to the count below was
    `stale_after_a_turn`. It computes nothing, it is a number the timeline
    already settled, and it tripped that ban anyway: the whole console test
    failed, several files away, with a message about workers.

    So the collision is asserted here, where the field is named and where the
    message can say what to do about it. The banned list is read from its one
    declaration rather than copied, because a copy would drift and this test
    would then be checking a rule nothing enforces.
    """
    guard = ast.parse(Path("packages/kernel/tests/test_app_composition.py")
                      .read_text(encoding="utf-8"))
    forbidden: tuple[str, ...] = ()
    for node in ast.walk(guard):
        if (isinstance(node, ast.For)
                and isinstance(node.target, ast.Name)
                and node.target.id == "deriving"
                and isinstance(node.iter, ast.Tuple)):
            forbidden = tuple(e.value for e in node.iter.elts
                              if isinstance(e, ast.Constant))
    assert "stale_after" in forbidden, (
        "the console's worker-health ban was moved or renamed; this test is "
        "reading the wrong loop and proves nothing")

    for field in backlog(**POPULATION).summary():
        for banned in forbidden:
            assert banned not in field, (
                f"`{field}` contains {banned!r}, which the console refuses to "
                "carry because that is the shape of a worker-health "
                "threshold. Rename the field — the ban is deliberately blunt "
                "and is worth more than the name")

    # And the field is genuinely on the page, so the paragraph above is a
    # constraint on something rendered rather than on a dictionary nobody reads.
    console = Path("apps/control/src/index.html").read_text(encoding="utf-8")
    assert "b.unread_after_a_turn" in console, (
        "the sites the sweep reached and could not read are counted and never "
        "shown, so an operator is told to wait for a sweep that will not clear "
        "them")


# -------------------------------------------------------- against the database


def test_the_stale_count_is_the_one_freshness_already_reports(repo):
    """The same number, because it is literally the same read.

    Two queries written to the same intent is how two numbers standing next to
    each other on one screen come to disagree, and an operator who catches
    them disagreeing stops believing either.
    """
    business = _business(repo)
    try:
        assert repo.audit_backlog()["older_than_a_week"] == \
               repo.audit_freshness()["older_than_a_week"]

        before = repo.audit_freshness()["older_than_a_week"]
        repo.record_event(BusinessEvent(
            business_id=business.id, kind=OBSERVED_EVENT,
            actor="test", detail={"url": business.website, "counts": {}},
            at=datetime.now(UTC) - timedelta(days=30)))

        found = repo.audit_backlog()
        assert repo.audit_freshness()["older_than_a_week"] == before + 1
        assert found["older_than_a_week"] == \
               repo.audit_freshness()["older_than_a_week"]
    finally:
        _clean(business.id)


def test_a_turn_moves_the_turn_and_never_the_observation(repo):
    """The distinction the twelve days turned on, at the source.

    Asserted as deltas rather than absolutes: these read the whole population,
    and an absolute figure would be a claim about every other test's fixtures.
    """
    business = _business(repo)
    try:
        before = repo.audit_backlog()

        repo.record_event(BusinessEvent(
            business_id=business.id, kind=VERIFIED_EVENT,
            actor="recipe:verify-recorded-websites",
            detail={"answered": True, "findings": 0}))
        turned = repo.audit_backlog()
        assert turned["last_observation"] == before["last_observation"], (
            "a site taking its turn moved the observation clock; that is "
            "exactly what made twelve days of staleness invisible")
        assert turned["nights_since_a_turn"] is not None
        assert turned["nights_since_a_turn"] <= 0.01

        repo.record_event(_a_reading_the_pass_wrote(business))
        observed = repo.audit_backlog()
        assert observed["nights_since_an_observation"] is not None
        assert observed["nights_since_an_observation"] <= 0.01
        assert observed["the_pass_is_running"]
        assert not observed["the_pass_ran_without_observing"]
    finally:
        _clean(business.id)


def test_only_the_passs_own_readings_say_the_pass_is_running(repo):
    """Whose reading it was, not only how recent it is.

    Four things write `website_audited`. `infra/reconcile_audits.py` appends a
    correction stamped *now* and says on the row that it read nothing new;
    `infra/import_audits.py` replays a file. Measuring the pass's health from
    `max(at)` over all of them means one hand-run reconcile certifies a stalled
    nightly pass as healthy — the twelve-day blind spot rebuilt under a
    different actor, with the console then explaining the age away as cadence.

    Both shapes are built through the writers' own code paths, so this fails if
    either of them changes what it records rather than only when this reader
    does.
    """
    business = _business(repo)
    try:
        before = repo.audit_backlog()

        # A correction: `read_by` copied forward from the reading it corrects,
        # so the only thing distinguishing it is that it says what it is.
        reading = _a_reading_the_pass_wrote(business)
        repo.record_event(reading.model_copy(update={
            "actor": "reconcile_audits.py",
            "detail": {**reading.detail,
                       "corrects": {"withdrew": ["booking"],
                                    "because": "read a different way"}}}))
        corrected = repo.audit_backlog()
        assert corrected["last_observation"] == before["last_observation"], (
            "a correction that read nothing moved the clock that says whether "
            "the pass is reading anything")

        # An import: the pass's actor, and no `read_by` because no page was
        # fetched for it here.
        repo.record_event(audit_event(
            business.id, {"url": business.website, "findings": []}))
        imported = repo.audit_backlog()
        assert imported["last_observation"] == before["last_observation"], (
            "a replayed audit file made the nightly pass look alive")

        # And the pass's own reading does move it, so the filter above is
        # narrowing rather than excluding everything. A fresh one: the timeline
        # is keyed on the event id, and re-recording the row the correction was
        # copied from would insert nothing.
        repo.record_event(_a_reading_the_pass_wrote(business))
        ran = repo.audit_backlog()
        assert ran["last_observation"] != before["last_observation"]
        assert ran["the_pass_is_running"]
    finally:
        _clean(business.id)


def test_only_the_passs_own_turns_count_as_the_rotation_coming_round(repo):
    """`infra/verify_weak_web_presence.py` writes turns as `probe`.

    A hand-run probe is not the rotation, and letting it answer for the
    rotation would report the twelve-day shape — turns without readings — from
    a run that was never the nightly pass.
    """
    business = _business(repo)
    try:
        before = repo.audit_backlog()
        repo.record_event(BusinessEvent(
            business_id=business.id, kind=VERIFIED_EVENT, actor="probe",
            detail={"answered": True}))
        assert repo.audit_backlog()["last_turn"] == before["last_turn"], (
            "a hand-run probe counted as the nightly rotation taking a turn")

        repo.record_event(BusinessEvent(
            business_id=business.id, kind=VERIFIED_EVENT,
            actor="recipe:verify-recorded-websites",
            detail={"answered": True}))
        assert repo.audit_backlog()["last_turn"] != before["last_turn"]
    finally:
        _clean(business.id)


def test_the_population_is_the_one_the_rotation_can_actually_fetch(repo):
    """An address the pass will never visit is not a night's work.

    `businesses_by_website` drops anything without an `http(s)` scheme, so a
    `mailto:` or a bare hostname is recorded evidence and never a fetch.
    Counting them in `sites` divides a population that is never visited by a
    throughput that never visits it, and the sweep it reports is longer than
    the one that runs — which is the direction that quietly explains away an
    age nothing is fixing.
    """
    reachable = _business(repo)
    unfetchable = _unfetchable(repo, f"mailto:{uuid4().hex}@backlog.test")
    schemeless = _unfetchable(repo, f"{uuid4().hex}.backlog.test")
    try:
        with_all_three = repo.audit_backlog()["sites"]
        _clean(unfetchable.id, schemeless.id)
        assert repo.audit_backlog()["sites"] == with_all_three, (
            "an address the pass cannot hand to a fetcher was counted as a "
            "night's work")
        # And the one it can is still in the population, so this narrows the
        # count rather than emptying it.
        _clean(reachable.id)
        assert repo.audit_backlog()["sites"] == with_all_three - 1
    finally:
        _clean(reachable.id, unfetchable.id, schemeless.id)


def test_a_night_is_spent_on_sites_the_pass_can_fetch(repo):
    """The scheme filter runs before the limit, not after it.

    The filter used to run in Python over rows the `LIMIT` had already chosen,
    so a night's forty could come back as thirty-one addresses — a throughput
    nobody could see, and one the backlog report would then have described as
    forty. Here the rotation is asked for two while four rows sit at the head of
    the queue, the two unfetchable ones first: it used to return nothing.
    """
    # Never verified, so `NULLS FIRST` puts all four at the head of the queue,
    # and a first_seen_at older than anything else in the suite fixes their
    # order within it. Nothing about the assertion then depends on which other
    # fixtures happen to be in the database.
    head = datetime(1970, 1, 2, tzinfo=UTC)
    unfetchable = [_unfetchable(repo, f"mailto:{uuid4().hex}@backlog.test",
                                first_seen_at=head) for _ in range(2)]
    fetchable = [repo.save_business(Business(
        name="Al Waha Dental", geography="United Arab Emirates",
        website=f"https://{uuid4().hex}.backlog.test", sources=["seed"],
        first_seen_at=head + timedelta(seconds=1))) for _ in range(2)]
    try:
        found = repo.businesses_by_website(limit=2)
        assert len(found) == 2, (
            "the night's budget was spent on rows the fetcher is never given")
        assert set(found) == {b.website for b in fetchable}
    finally:
        _clean(*[b.id for b in unfetchable + fetchable])


def test_a_site_the_sweep_reached_and_could_not_read_is_counted(repo):
    """Measured off the timeline, not inferred from an `ORDER BY`.

    The rotation orders least-recently-verified first, so reading the query
    would say every stale site is about to be refreshed. This asks the
    timeline whether it *was*, and a site whose turn came after its last
    reading is one the sweep will not clear however long anybody waits.
    """
    business = _business(repo)
    try:
        before = repo.audit_backlog()

        # A reading a month old, then a turn since. This is the shape a site
        # that refuses, times out or serves a PDF leaves every single night.
        repo.record_event(BusinessEvent(
            business_id=business.id, kind=OBSERVED_EVENT, actor="test",
            detail={"url": business.website, "counts": {}},
            at=datetime.now(UTC) - timedelta(days=30)))
        stale_only = repo.audit_backlog()
        assert stale_only["unread_after_a_turn"] == before["unread_after_a_turn"], (
            "an old reading with no turn since is a queue position, and "
            "counting it here would report the queue as unreachable")

        repo.record_event(BusinessEvent(
            business_id=business.id, kind=VERIFIED_EVENT,
            actor="recipe:verify-recorded-websites",
            detail={"answered": False, "error": "timed out"},
            at=datetime.now(UTC) - timedelta(days=1)))
        stuck = repo.audit_backlog()
        assert stuck["unread_after_a_turn"] == before["unread_after_a_turn"] + 1
        assert stuck["waiting_will_not_clear_these"]
        assert stuck["unread_after_a_turn"] <= stuck["older_than_a_week"], (
            "these are a subset of the sites freshness calls stale, so the "
            "count cannot exceed it")

        # And a reading after the turn puts it back in the queue it belongs to.
        repo.record_event(BusinessEvent(
            business_id=business.id, kind=OBSERVED_EVENT, actor="test",
            detail={"url": business.website, "counts": {}}))
        assert repo.audit_backlog()["unread_after_a_turn"] == \
               before["unread_after_a_turn"]
    finally:
        _clean(business.id)


def test_a_second_business_on_one_address_is_never_reached_again(repo):
    """The rotation fetches an address, and only one business holds it.

    Two businesses on one website is a single night's work, which is why
    `sites` counts addresses — and it means the *other* business is fetched by
    nothing. It is never turned, so it can never be a turn that read nothing;
    it simply keeps whatever observation it has for ever while the ordering
    says its turn is coming.

    Asserted against the rotation's own answer rather than against a second
    opinion about which of the two it holds: the count and the query read one
    definition, and this fails if they ever stop doing so.
    """
    shared = f"https://{uuid4().hex}.shared.test"
    # A first_seen_at older than anything else in the suite, so the pair sits
    # at the head of the never-verified queue and which of them the rotation
    # holds does not depend on the order the tests happened to run in.
    head = datetime(1970, 1, 5, tzinfo=UTC)
    held = repo.save_business(Business(
        name="Al Waha Dental", geography="United Arab Emirates",
        website=shared, sources=["seed"], first_seen_at=head))
    orphaned = repo.save_business(Business(
        name="Al Waha Dental", geography="United Arab Emirates",
        website=shared, sources=["seed"],
        first_seen_at=head + timedelta(days=1)))
    try:
        before = repo.audit_backlog()
        stale = datetime.now(UTC) - timedelta(days=30)
        for business in (held, orphaned):
            repo.record_event(BusinessEvent(
                business_id=business.id, kind=OBSERVED_EVENT, actor="test",
                detail={"url": shared, "counts": {}}, at=stale))

        rotation = repo.businesses_by_website(limit=ROTATION_CEILING)
        assert shared in rotation, (
            "the address is not in the rotation at all; this test is asserting "
            "against a queue that does not contain what it is about")
        assert rotation[shared].id == held.id

        found = repo.audit_backlog()
        assert found["never_in_the_rotation"] == \
               before["never_in_the_rotation"] + 1, (
            "the business the rotation does not hold was counted as a queue "
            "position in a sweep that will never fetch it")
        assert found["unread_after_a_turn"] == before["unread_after_a_turn"], (
            "a business that has never been turned was counted as a turn that "
            "produced no reading")
        assert found["waiting_will_not_clear_these"]
        # And the one the rotation does hold is a queue position, so this
        # narrows to the unreachable half rather than condemning both.
        assert found["never_in_the_rotation"] < found["older_than_a_week"]
    finally:
        _clean(held.id, orphaned.id)


def test_an_address_the_fetcher_is_never_handed_keeps_its_reading_for_ever(repo):
    """`mailto:` and scheme-less values are recorded evidence, never a fetch.

    They are already kept out of `sites`, so the cadence is arithmetic over the
    population the pass rotates through. That leaves the other half unsaid: a
    reading taken against one of these — by the browser pass, or by an import —
    is stale for ever, counts in `older_than_a_week`, and no night will ever
    come round to it.

    A fresh one is counted by neither, because there is nothing to explain
    about a record that is not old.
    """
    stuck = _unfetchable(repo, f"mailto:{uuid4().hex}@backlog.test")
    recent = _unfetchable(repo, f"{uuid4().hex}.backlog.test")
    try:
        before = repo.audit_backlog()
        repo.record_event(BusinessEvent(
            business_id=stuck.id, kind=OBSERVED_EVENT, actor="test",
            detail={"url": stuck.website, "counts": {}},
            at=datetime.now(UTC) - timedelta(days=30)))
        repo.record_event(BusinessEvent(
            business_id=recent.id, kind=OBSERVED_EVENT, actor="test",
            detail={"url": recent.website, "counts": {}}))

        found = repo.audit_backlog()
        assert found["never_in_the_rotation"] == \
               before["never_in_the_rotation"] + 1, (
            "an address no night will ever visit was reported as a queue "
            "position, or a reading that is not old was reported as stuck")

        # A hand-run probe can still write a turn against one of these. It is
        # counted once, under the name that says why waiting will not help:
        # there is no rotation for the turn to have come from.
        repo.record_event(BusinessEvent(
            business_id=stuck.id, kind=VERIFIED_EVENT, actor="probe",
            detail={"answered": False, "error": "timed out"}))
        turned = repo.audit_backlog()
        assert turned["never_in_the_rotation"] == \
               found["never_in_the_rotation"]
        assert turned["unread_after_a_turn"] == found["unread_after_a_turn"], (
            "the same record was counted twice — once as reached and unread "
            "and once as never reached — so the two add to more than the age "
            "they explain")
        assert turned["beyond_the_rotations_reach"] <= \
               turned["older_than_a_week"]
    finally:
        _clean(stuck.id, recent.id)


def test_the_rotation_counts_addresses_because_that_is_what_it_fetches(repo):
    """Two businesses, one website, one night's work.

    `audit_freshness` counts businesses, because the age it reports is per
    business. The sweep counts addresses, because the rotation de-duplicates
    by address before it fetches — and using the wrong one would report a
    cadence slower than the one that runs.
    """
    shared = f"https://{uuid4().hex}.shared.test"
    first = _business(repo, website=shared)
    second = _business(repo, website=shared)
    try:
        assert first.id != second.id
        with_both = repo.audit_backlog()["sites"]
        _clean(second.id)
        assert repo.audit_backlog()["sites"] == with_both, (
            "the second business on the same address counted as another "
            "night's work; the rotation fetches addresses, not businesses")

        alone = _business(repo)
        try:
            assert repo.audit_backlog()["sites"] == with_both + 1
        finally:
            _clean(alone.id)
    finally:
        _clean(first.id, second.id)


def test_every_field_the_production_probe_checks_is_present(repo):
    """The contract, read off a real database rather than a constructor."""
    found = repo.audit_backlog()
    for key in ("sites", "older_than_a_week", "nights_for_a_full_sweep",
                "the_cadence_explains_the_age", "the_pass_is_running"):
        assert key in found, f"{key} is missing from audit_backlog()"
    assert isinstance(found["the_cadence_explains_the_age"], bool)
    assert isinstance(found["the_pass_is_running"], bool)
    assert found["per_night"] == rotation_size(NIGHTLY_SITE_LIMIT)
    assert found["nights_for_a_full_sweep"] == coverage.Backlog(
        sites=found["sites"], older_than_a_week=found["older_than_a_week"],
        per_night=found["per_night"]).nights_for_a_full_sweep
