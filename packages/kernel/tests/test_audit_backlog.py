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
from datetime import UTC, datetime
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


def _forget(*business_ids: str) -> None:
    """Every row the database tests below leave behind."""
    with SessionLocal() as session:
        for business_id in business_ids:
            for table, column in (("atlas_business_events", "business_id"),
                                  ("atlas_findings", "business_id"),
                                  ("atlas_businesses", "id")):
                session.execute(
                    text(f"DELETE FROM {table} WHERE {column} = :b"),
                    {"b": business_id})
        session.commit()


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
        """Half throughput is a real eighteen-night rotation, and it says so.

        Reported as eighteen because that is how long the queue is now taking —
        the number a reader needs. What it does *not* become is an
        eighteen-night licence: see
        `TestARotationOnlyExcusesTheSweepItWasPromised`, which is the half of
        this that a longer sweep must never buy.
        """
        found = _sweep(verified_recently=A_HEALTHY_WEEK // 2,
                       days_ago=[8] * 300 + [20] * 50)

        assert found.a_night_observed == SITES_A_NIGHT / 2
        assert found.nights_for_a_full_sweep == 18
        assert not found.the_pass_is_keeping_up
        assert found.nights_the_rotation_explains == 9
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


class TestARotationOnlyExcusesTheSweepItWasPromised:
    """Measuring the rate solves half the problem and opens the other half.

    A sweep length taken from the *configured* limit excuses any age the
    configuration implies, whether or not a pass ran. But a sweep length taken
    from the *measured* rate alone excuses more the worse the pass performs: a
    single forty-site run in a week over three hundred and fifty sites measures
    5.7 a night, which is a sixty-two-night rotation, and a sixty-two-night
    rotation arithmetically accounts for a two-month-old observation. A
    scheduler that had all but stopped would be handed a longer alibi than a
    healthy one — the same false reassurance, reached from the other direction.

    So the excuse is the shorter of the sweep the pass achieves and the sweep
    it was promised, and the shortfall is reported as itself.
    """

    def test_a_pass_that_all_but_stopped_earns_no_sixty_two_night_excuse(self):
        """The finding, in the shape it actually arrives in.

        One forty-site pass inside the window over the production population.
        The eight-day-old records are still within the nine nights a healthy
        rotation takes, so they stay explained and the report does not cry
        wolf — but the forty-day-old ones are residue, and under the measured
        sweep alone all fifty of them would have been filed as the queue
        working its way round.
        """
        found = _sweep(verified_recently=SITES_A_NIGHT,
                       days_ago=[8] * 300 + [40] * 50)

        assert found.the_pass_is_running, (
            "forty verifications is not an outage, and reporting it as one "
            "would hide that this is a throughput problem")
        assert found.nights_for_a_full_sweep == 62, (
            "the achieved sweep is reported honestly; a queue taking two "
            "months is itself the finding")
        assert not found.the_pass_is_keeping_up
        assert found.nights_the_rotation_explains == 9, (
            "a rotation explains an age only as far as the sweep it was "
            "promised at")
        assert found.older_than_a_full_sweep == 50
        assert found.explained_by_the_backlog == 300
        assert not found.the_cadence_explains_the_age

    def test_a_faster_pass_is_held_to_the_sweep_it_achieves(self):
        """The cap is a ceiling on the excuse and never a floor under it.

        Double throughput comes round in five nights, so a six-day-old record
        is one the queue has already passed over. Excusing it up to the nine
        nights the configuration promises would be the configured rate's
        original lie, kept alive in the cap.
        """
        found = _sweep(verified_recently=A_HEALTHY_WEEK * 2,
                       days_ago=[6] * SITES)

        assert found.a_night_observed == SITES_A_NIGHT * 2
        assert found.nights_for_a_full_sweep == 5
        assert found.nights_the_rotation_explains == 5
        assert found.the_pass_is_keeping_up
        assert found.older_than_a_full_sweep == SITES
        assert not found.the_cadence_explains_the_age

    def test_one_slipped_night_is_not_a_degraded_pass(self):
        """Exactly one night of tolerance, and it is not arbitrary.

        The window is a whole number of nights and the pass runs at some hour
        inside it, so a run that drifts past midnight lands twice in one night
        and not at all in another. A flag that fired on that would be on most
        weeks, and a warning that is always on is a warning nobody reads. Two
        missed nights is a real shortfall.
        """
        def keeping_up(nights_run: int) -> bool:
            return _sweep(verified_recently=SITES_A_NIGHT * nights_run,
                          days_ago=[]).the_pass_is_keeping_up

        assert keeping_up(MEASURED_OVER)
        assert keeping_up(MEASURED_OVER - 1)
        assert not keeping_up(MEASURED_OVER - 2)

    def test_a_small_market_is_never_permanently_behind(self):
        """Twenty sites cannot be verified forty a night.

        Holding a small market to the configured limit would leave the flag
        raised for ever on a queue coming round nightly, so what is expected is
        the limit or the population, whichever is smaller.
        """
        found = _sweep(verified_recently=20 * MEASURED_OVER, sites=20,
                       days_ago=[1] * 20)

        assert found.a_night_expected == 20
        assert found.the_pass_is_keeping_up
        assert found.nights_the_rotation_explains == 1

    def test_the_payload_carries_the_shortfall_and_the_note_explains_it(self):
        """A reader of the JSON must be able to see the difference.

        The achieved sweep and the age it is allowed to excuse are the same
        number while the pass keeps up and deliberately are not while it does
        not, so reporting only one of them puts the reader back where they
        started.
        """
        payload = _sweep(verified_recently=SITES_A_NIGHT,
                         days_ago=[8] * SITES).summary()

        assert payload["the_pass_is_keeping_up"] is False
        assert payload["a_night_expected"] == SITES_A_NIGHT
        assert payload["nights_for_a_full_sweep"] == 62
        assert payload["nights_the_rotation_explains"] == 9
        assert "behind what it was asked for" in payload["note"]
        assert "promised" in payload["note"]

    def test_a_healthy_pass_says_nothing_about_a_shortfall(self):
        """The other half: the note stays quiet when there is nothing to say."""
        payload = _sweep(verified_recently=A_HEALTHY_WEEK,
                         days_ago=[8] * SITES).summary()

        assert payload["the_pass_is_keeping_up"] is True
        assert payload["nights_the_rotation_explains"] == 9
        assert payload["nights_for_a_full_sweep"] == 9
        assert "behind what it was asked for" not in payload["note"]


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
            _forget(business.id)

    def test_the_freshness_report_carries_it(self, repo):
        payload = repo.audit_freshness()["backlog"]

        assert {"a_night_declared", "a_night_observed", "verified_recently",
                "the_pass_is_running", "the_pass_is_keeping_up",
                "nights_for_a_full_sweep", "nights_the_rotation_explains",
                "explained_by_the_backlog", "older_than_a_full_sweep"} <= \
               set(payload)


class TestTheNumeratorAndTheDenominatorAreOnePopulation:
    """Throughput counted over sites the queue does not serve.

    The sweep length is `sites / rate`. The denominator is the queue's own
    population — distinct fetchable addresses — so a numerator counting every
    recent `website_verified` event on the timeline is a rate over a different
    set: work on a business whose address has since been emptied, changed, or
    de-duplicated behind an older record is work this rotation will never
    repeat. Counted in, it shortens the reported sweep, and a shorter sweep
    excuses fewer stale records than it should — the report goes quiet about
    exactly what it exists to surface.
    """

    @pytest.fixture(scope="class", autouse=True)
    def schema(self):
        db.init_db()

    @pytest.fixture
    def repo(self) -> OpportunityRepository:
        return OpportunityRepository()

    @staticmethod
    def _verify(repo, business_id: str) -> None:
        repo.record_event(BusinessEvent(
            business_id=business_id, kind=VERIFIED_EVENT,
            actor="recipe:verify-recorded-websites",
            detail={"answered": True, "findings": 0}))

    def test_an_address_the_queue_cannot_fetch_does_not_count_as_throughput(
            self, repo):
        """A `mailto:` is excluded from the sweep, so it is excluded from
        the rate that drains it."""
        empty = repo.audit_backlog()
        business = repo.save_business(Business(
            name="Al Waha Dental", geography="United Arab Emirates",
            website="mailto:hello@backlog-unfetchable.test", sources=["seed"]))
        try:
            before = repo.audit_backlog()
            assert before["cannot_be_fetched"] == empty["cannot_be_fetched"] + 1
            assert before["sites"] == empty["sites"], (
                "an unfetchable address is not one of the sites a sweep covers")

            self._verify(repo, business.id)

            after = repo.audit_backlog()
            assert after["sites"] == before["sites"]
            assert after["verified_recently"] == before["verified_recently"], (
                "a verification of a site the queue does not serve inflates "
                "the rate against a population it is not in")
        finally:
            _forget(business.id)

    def test_a_deduplicated_business_does_not_count_but_the_canonical_one_does(
            self, repo):
        """Two businesses, one address, one fetch a night.

        The queue serves the earliest holder of the address and nothing else,
        so only that record's verifications are work on this population — and
        they must still be counted, or the restriction would fix the inflation
        by throwing the measurement away.
        """
        shared = "https://backlog-shared-address.test"
        older = repo.save_business(Business(
            name="Al Waha Dental", geography="United Arab Emirates",
            website=shared, sources=["seed"],
            first_seen_at=datetime(2026, 1, 1, tzinfo=UTC)))
        newer = repo.save_business(Business(
            name="Al Waha Dental Clinic", geography="United Arab Emirates",
            website=shared, sources=["seed"],
            first_seen_at=datetime(2026, 2, 1, tzinfo=UTC)))
        try:
            before = repo.audit_backlog()

            self._verify(repo, newer.id)
            deduplicated = repo.audit_backlog()
            assert deduplicated["verified_recently"] == \
                   before["verified_recently"], (
                "the queue never fetches the de-duplicated record, so nothing "
                "it carries is throughput")

            self._verify(repo, older.id)
            canonical = repo.audit_backlog()
            assert canonical["verified_recently"] == \
                   before["verified_recently"] + 1
        finally:
            _forget(older.id, newer.id)


class TestAnObservationIsOfAnAddress:
    """`save_business` overwrites `website` on every re-ingestion.

    The audit on the timeline records the URL it read. Joined to a business by
    id alone, the audit of an address that business has since left is reported
    as an observation of the address it holds now — a replacement URL nothing
    has ever fetched, shown as observed today. That is the freshest reading the
    report can produce, of a page nobody has looked at.
    """

    @pytest.fixture(scope="class", autouse=True)
    def schema(self):
        db.init_db()

    @pytest.fixture
    def repo(self) -> OpportunityRepository:
        return OpportunityRepository()

    def test_an_audit_of_a_previous_address_is_not_an_observation_of_the_new_one(
            self, repo):
        was = "https://backlog-previous-address.test"
        now = "https://backlog-replacement-address.test"
        business = repo.save_business(Business(
            name="Al Waha Dental", geography="United Arab Emirates",
            website=was, sources=["seed"]))
        try:
            unobserved = repo.audit_backlog()

            repo.record_event(BusinessEvent(
                business_id=business.id, kind="website_audited",
                actor="test:backlog",
                detail={"url": was, "observations": []}))
            observed = repo.audit_backlog()
            assert observed["observed"] == unobserved["observed"] + 1
            assert observed["never_observed"] == unobserved["never_observed"] - 1

            # The address moves. The audit stays where it is — history is
            # immutable — and it names the address that was read.
            repo.save_business(business.model_copy(update={"website": now}))
            moved = repo.audit_backlog()

            assert moved["sites"] == observed["sites"], (
                "one business, one fetchable address, before and after")
            assert moved["observed"] == unobserved["observed"], (
                "the replacement address has never been read")
            assert moved["never_observed"] == unobserved["never_observed"]
        finally:
            _forget(business.id)

    def test_an_audit_of_the_same_address_survives_a_redirect_difference(
            self, repo):
        """The comparison is `verification.same_website` and not equality.

        A scheme or a trailing slash is what a redirect changes, and treating
        those as a different site would file most of the population as never
        observed — a worse misreport than the one this guards against, and
        arrived at while looking careful.
        """
        business = repo.save_business(Business(
            name="Al Waha Dental", geography="United Arab Emirates",
            website="https://backlog-redirect.test", sources=["seed"]))
        try:
            before = repo.audit_backlog()
            repo.record_event(BusinessEvent(
                business_id=business.id, kind="website_audited",
                actor="test:backlog",
                detail={"url": "http://backlog-redirect.test/",
                        "observations": []}))

            after = repo.audit_backlog()
            assert after["observed"] == before["observed"] + 1
        finally:
            _forget(business.id)

    def test_an_audit_that_predates_the_url_field_is_still_an_observation(
            self, repo):
        """Several hundred historical audits carry no `url` at all.

        Reading their silence as "this was some other address" would call the
        whole backlog unobserved on the strength of a field nobody wrote.
        """
        business = repo.save_business(Business(
            name="Al Waha Dental", geography="United Arab Emirates",
            website="https://backlog-legacy-audit.test", sources=["seed"]))
        try:
            before = repo.audit_backlog()
            repo.record_event(BusinessEvent(
                business_id=business.id, kind="website_audited",
                actor="test:backlog", detail={"observations": []}))

            after = repo.audit_backlog()
            assert after["observed"] == before["observed"] + 1
        finally:
            _forget(business.id)
