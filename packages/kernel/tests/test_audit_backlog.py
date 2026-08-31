"""A rotation only excuses staleness if the rotation actually ran.

`audit_freshness` reports that most observation records are more than a week
old. On a population larger than one night's fetch that is usually arithmetic
rather than a fault — forty a night over three hundred and fifty sites is a
nine-night sweep — so `coverage.Backlog` separates the part the queue explains
from the part it does not.

The trap this file exists for is the first half of that sentence. A sweep
length taken from the *configured* limit is a claim about a pass nobody
checked, and this codebase has already had a recurrence declare "nightly" while
writing no observations for twelve days. Read that way, a scheduler that
stopped a week ago leaves every record eight days old and the report calls it a
nine-night rotation working as intended — rebuilding the exact blind spot the
number was added to remove.

So the rate is measured from the verification events on the timeline, and the
tests below are mostly about what that measurement says when the pass is
degraded, stopped, or faster than the configured limit would suggest.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from sqlalchemy import text

from atlas_kernel import db
from atlas_kernel.db import SessionLocal
from atlas_kernel.opportunity.coverage import MEASURED_OVER, backlog
from atlas_kernel.opportunity.models import Business, BusinessEvent
from atlas_kernel.opportunity.repository import (
    SITES_A_NIGHT,
    VERIFIED_EVENT,
    OpportunityRepository,
)

#: The production shape the finding was measured on.
SITES = 350
#: A week of nights at the configured rate: what a healthy pass leaves behind.
A_HEALTHY_WEEK = SITES_A_NIGHT * MEASURED_OVER


def _sweep(*, verified_recently, days_ago, sites=SITES, **rest):
    return backlog(sites=sites, a_night_declared=SITES_A_NIGHT,
                   observed_days_ago=days_ago,
                   verified_recently=verified_recently, **rest)


class TestTheCadenceIsMeasuredNotAssumed:
    def test_a_running_rotation_explains_a_record_it_has_not_reached_yet(self):
        """The number the report exists to make readable.

        Every observation eight days old, and a sweep that genuinely takes
        nine: nothing here is a fault, and reporting 350 stale records with
        nothing beside them sends somebody to fix a cadence that is working.
        """
        found = _sweep(verified_recently=A_HEALTHY_WEEK, days_ago=[8] * SITES)

        assert found.the_pass_is_running
        assert found.a_night_observed == SITES_A_NIGHT
        assert found.nights_for_a_full_sweep == 9
        assert found.older_than_a_week == SITES
        assert found.explained_by_the_backlog == SITES
        assert found.older_than_a_full_sweep == 0
        assert found.the_cadence_explains_the_age

    def test_a_pass_that_stopped_explains_nothing(self):
        """The finding. Identical ages, identical configuration, no pass.

        With the sweep taken from the configured forty a night this reported a
        nine-night rotation and filed all 350 records as
        `explained_by_the_backlog` — a scheduler outage rendered as a queue
        doing its job, which is the failure the metric is meant to expose.
        """
        found = _sweep(verified_recently=0, days_ago=[8] * SITES)

        assert not found.the_pass_is_running
        assert found.a_night_observed == 0
        assert found.nights_for_a_full_sweep == 0, (
            "no sweep completes, and zero must never be read as a sweep of "
            "length zero that everything is older than")
        assert found.explained_by_the_backlog == 0, (
            "a rotation nobody performed cannot excuse a single record")
        assert found.older_than_a_full_sweep == SITES
        assert not found.the_cadence_explains_the_age

        payload = found.summary()
        assert payload["the_pass_is_running"] is False
        assert payload["a_night_declared"] == SITES_A_NIGHT
        assert payload["a_night_observed"] == 0
        assert "No sweep is completing" in payload["note"]

    def test_a_stopped_pass_is_visible_before_the_ages_drift(self):
        """A day into an outage nothing is stale yet, and it still says so.

        `the_cadence_explains_the_age` is true here — there is no old record to
        explain — so the running flag has to carry the outage on its own or the
        payload reads as healthy for the week it takes the ages to move.
        """
        found = _sweep(verified_recently=0, days_ago=[1] * SITES)

        assert found.older_than_a_week == 0
        assert found.the_cadence_explains_the_age
        assert not found.the_pass_is_running

    def test_a_degraded_pass_reports_the_longer_sweep_it_actually_achieves(self):
        """Half throughput is a real eighteen-night rotation, not a fault.

        And not a nine-night one either: the record that the slower sweep
        genuinely has not reached is separated from the one that is older than
        even that.
        """
        found = _sweep(verified_recently=A_HEALTHY_WEEK // 2,
                       days_ago=[8] * 300 + [20] * 50)

        assert found.a_night_observed == SITES_A_NIGHT / 2
        assert found.nights_for_a_full_sweep == 18
        assert found.explained_by_the_backlog == 300
        assert found.older_than_a_full_sweep == 50
        assert not found.the_cadence_explains_the_age

        note = found.summary()["note"]
        assert "measured" in note and str(SITES_A_NIGHT) in note, (
            "both rates belong in the note: the measured one is the claim, "
            "and the configured one is how a reader sees the shortfall")

    def test_the_rate_counts_attempts_so_a_small_population_is_not_flattered(
            self):
        """Distinct sites saturate; attempts do not.

        A hundred sites at forty a night is a three-night rotation. Measuring
        the rate as distinct sites verified in a week would top out at the
        hundred that exist, report fourteen a night and a seven-night sweep,
        and quietly excuse a five-day-old observation the queue had already
        passed over twice.
        """
        found = _sweep(verified_recently=A_HEALTHY_WEEK, sites=100,
                       days_ago=[5] * 100)

        assert found.a_night_observed == SITES_A_NIGHT
        assert found.nights_for_a_full_sweep == 3
        assert found.older_than_a_full_sweep == 100
        assert found.explained_by_the_backlog == 0
        assert not found.the_cadence_explains_the_age

    def test_an_unmeasured_caller_falls_back_to_the_configured_limit_and_says_so(
            self):
        """The only place the declared rate is used, and it is never silent."""
        found = backlog(sites=SITES, a_night_declared=SITES_A_NIGHT,
                        observed_days_ago=[8] * SITES)

        assert found.a_night_observed is None
        assert found.a_night_effective == SITES_A_NIGHT
        assert found.nights_for_a_full_sweep == 9
        assert found.summary()["a_night_observed"] is None
        assert "no verification was measured" in found.summary()["note"]

    def test_a_measured_zero_is_not_treated_as_unmeasured(self):
        """The distinction the fallback turns on.

        Zero verifications is the most informative reading there is, and a
        fallback that could not tell it from "nobody looked" would answer it
        with the configured rate.
        """
        assert _sweep(verified_recently=0, days_ago=[]).a_night_observed == 0
        assert backlog(sites=1, a_night_declared=SITES_A_NIGHT,
                       observed_days_ago=[]).a_night_observed is None


class TestWhatTheRotationNeverExplains:
    def test_a_population_with_nothing_to_sweep_makes_no_claim(self):
        found = _sweep(verified_recently=0, sites=0, days_ago=[])

        assert found.nights_for_a_full_sweep == 0
        assert found.older_than_a_week == 0
        assert found.explained_by_the_backlog == 0
        assert found.summary()["sites"] == 0

    def test_a_site_never_observed_is_not_an_age(self):
        found = _sweep(verified_recently=A_HEALTHY_WEEK,
                       days_ago=[8, None, None])

        assert found.never_observed == 2
        assert len(found.observed) == 1
        assert found.older_than_a_week == 1

    def test_the_residue_is_reported_beside_the_ages_and_never_added_to_them(
            self):
        """Three ways a record stays old however long the queue runs.

        Summing them into the stale count would hide the only half anybody can
        act on — the same distinction `reevaluation` draws between a fact about
        their site and a fact about our own checking.
        """
        found = _sweep(verified_recently=A_HEALTHY_WEEK, days_ago=[8] * SITES,
                       reached_without_observation=12, cannot_be_fetched=5,
                       shares_an_address=7)
        payload = found.summary()

        assert payload["older_than_a_week"] == SITES
        assert payload["explained_by_the_backlog"] == SITES
        assert (payload["reached_without_observation"],
                payload["cannot_be_fetched"],
                payload["shares_an_address"]) == (12, 5, 7)
        assert "none of those three age out" in payload["note"]


class TestOneLimit:
    """The bound the report divides by is the bound the pass actually runs at.

    `SITES_A_NIGHT` is what `audit_backlog` prints as `a_night_declared`, and
    the point of printing it beside the measured rate is that a reader can see
    a pass falling short of what it was asked for. That comparison is worth
    nothing if the runner was never asked for this number: it carried its own
    literal 40, so raising the constant would have moved the report and left
    the nightly pass exactly where it was.
    """

    class _Recording:
        """A repository that answers nothing and remembers what it was asked."""

        def __init__(self) -> None:
            self.limit: int | None = None

        def businesses_by_website(self, *, limit, tenant=None) -> dict:
            self.limit = limit
            return {}

    def test_the_runner_bounds_a_pass_by_the_shared_limit(self):
        """Behavioural, and the one that matters: nothing passes a limit.

        Whatever `SITES_A_NIGHT` becomes, this is the number the nightly pass
        actually fetches — so the report describing that rate is describing
        this pass.
        """
        from atlas_kernel.fabric import recipes
        from atlas_kernel.mission.toolrunner import targets_map_for

        recipe = recipes.get("verify-recorded-websites")
        assert recipe.targets_from == "business_websites", (
            "the verification recipe no longer takes its targets from memory; "
            "update this test rather than deleting it")

        repository = self._Recording()
        targets_map_for(recipe, repository=repository)
        assert repository.limit == SITES_A_NIGHT

        # Still overridable by a caller that names one — the shared limit is
        # the default, not a ceiling on a script asking for five.
        targets_map_for(recipe, repository=repository, limit=5)
        assert repository.limit == 5

    def test_the_repository_defaults_to_the_named_limit_not_a_literal(self):
        """Structural, because equal literals pass a behavioural check.

        Two 40s agree until one of them moves, and the failure then is silent:
        the queue serves a different number of sites than the report divides
        by, and both look right in isolation.
        """
        tree = ast.parse(Path(
            "packages/kernel/atlas_kernel/opportunity/repository.py").read_text())
        checked = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or node.name not in (
                    "businesses_by_website", "recorded_websites"):
                continue
            names = [a.arg for a in node.args.kwonlyargs]
            assert "limit" in names, f"{node.name} no longer bounds by `limit`"
            default = node.args.kw_defaults[names.index("limit")]
            assert isinstance(default, ast.Name) and \
                   default.id == "SITES_A_NIGHT", (
                f"{node.name} defaults `limit` to a literal. There is one "
                f"nightly limit and it is `SITES_A_NIGHT`")
            checked.add(node.name)
        assert checked == {"businesses_by_website", "recorded_websites"}, (
            "a queue-serving method moved or was renamed; update this test")


class TestItReadsTheRealTimeline:
    """The measurement, against the database rather than a constructed case."""

    @pytest.fixture(scope="class", autouse=True)
    def schema(self):
        db.init_db()

    @pytest.fixture
    def repo(self) -> OpportunityRepository:
        return OpportunityRepository()

    def test_a_verification_event_moves_the_measured_rate(self, repo):
        """Deltas, not absolutes: this reads the whole population.

        `website_verified` is the only thing that counts here, and it is
        deliberately the event `audit_freshness` refuses to read as a fresh
        observation — the pass having run and the page having been re-read are
        different facts, and this metric needs the first one precisely because
        the report above it reports the second.
        """
        business = repo.save_business(Business(
            name="Al Waha Dental", geography="United Arab Emirates",
            website="https://backlog.test", sources=["seed"]))
        try:
            before = repo.audit_backlog()
            assert before["over_nights"] == MEASURED_OVER
            assert before["a_night_declared"] == SITES_A_NIGHT
            assert isinstance(before["verified_recently"], int), (
                "a reading of the timeline is always a number; `None` here "
                "would fall the report back onto the configured rate")

            repo.record_event(BusinessEvent(
                business_id=business.id, kind=VERIFIED_EVENT,
                actor="recipe:verify-recorded-websites",
                detail={"answered": True, "findings": 0}))

            after = repo.audit_backlog()
            assert after["verified_recently"] == before["verified_recently"] + 1
            assert after["the_pass_is_running"] is True
            assert after["a_night_observed"] == round(
                after["verified_recently"] / MEASURED_OVER, 2)
            assert after["sites"] >= 1
        finally:
            with SessionLocal() as session:
                for table, column in (("atlas_business_events", "business_id"),
                                      ("atlas_findings", "business_id"),
                                      ("atlas_businesses", "id")):
                    session.execute(
                        text(f"DELETE FROM {table} WHERE {column} = :b"),
                        {"b": business.id})
                session.commit()

    def test_the_freshness_report_carries_it(self, repo):
        payload = repo.audit_freshness()["backlog"]

        assert {"a_night_declared", "a_night_observed", "verified_recently",
                "the_pass_is_running", "nights_for_a_full_sweep",
                "explained_by_the_backlog", "older_than_a_full_sweep"} <= \
               set(payload)
