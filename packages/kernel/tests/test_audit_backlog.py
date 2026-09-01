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
  was being read; and
* the rotation comes round inside a week and sites are stale anyway, which is
  what re-reading the alphabetically first forty did while succeeding nightly.

The pure arithmetic is tested pure, because every boolean above has to hold for
populations this database will never contain. The database tests assert the
things only the database can settle: that the two numbers standing beside each
other on one screen are the same number, and that a turn is not an observation.
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

        repo.record_event(BusinessEvent(
            business_id=business.id, kind=OBSERVED_EVENT, actor="test",
            detail={"url": business.website, "counts": {}}))
        observed = repo.audit_backlog()
        assert observed["nights_since_an_observation"] is not None
        assert observed["nights_since_an_observation"] <= 0.01
        assert observed["the_pass_is_running"]
        assert not observed["the_pass_ran_without_observing"]
    finally:
        _clean(business.id)


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
