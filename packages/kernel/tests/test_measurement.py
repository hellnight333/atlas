"""Measurement: what may honestly be said, and everything that may not.

This is the layer every future report rests on, so almost all of it is
negative. The single most damaging output this system could produce is a
confident causal claim about somebody's business that the data does not carry —
and the defence is structural: the attribution level is derived from the
evidence, and the language a level licenses follows from the level.

A word list can be worked around by rephrasing. This cannot, because rephrasing
does not change what the measurement actually established.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from atlas_kernel.measurement import (
    AIVisibilityObservation,
    Attribution,
    BaselineState,
    Claim,
    Confidence,
    Measurement,
    Observation,
    Window,
    phrasing,
    refuse,
    window_around,
)
from atlas_kernel.measurement.attribution import claim_of, permits
from atlas_kernel.measurement.models import BY_KEY, Direction, MetricFamily
from atlas_kernel.measurement.service import (
    OutsideWindow,
    ProvenanceMissing,
    read,
    record,
    summarise,
    vet,
)
from atlas_kernel.opportunity.tenancy import ALL_TENANTS, TenantRequired

NOW = datetime(2026, 7, 1, tzinfo=UTC)


def _measurement(**over) -> Measurement:
    base = {
        "business_id": "ahs", "tenant_id": "t-qevik", "metric_key": "leads",
        "job_id": "job-1", "recommendation_id": "rec-1",
        "window": window_around(NOW, days=30),
        "baseline": Observation(value=34, source="analytics"),
        "observed": Observation(value=61, source="analytics",
                                observed_at=NOW + timedelta(days=29)),
    }
    return Measurement(**{**base, **over})


# --- the scale is derived, never assigned ---------------------------------

def test_attribution_is_earned_by_evidence_not_declared() -> None:
    """Each level requires something the one below it did not."""
    no_baseline = _measurement(baseline=None)
    assert no_baseline.attribution is Attribution.UNKNOWN

    # A window with no intervention preceding it: the numbers moved, nothing more.
    unordered = _measurement(window=Window(
        baseline_start=NOW - timedelta(days=30), baseline_end=NOW,
        observation_start=NOW, observation_end=NOW + timedelta(days=30)))
    assert unordered.attribution is Attribution.OBSERVED

    assert _measurement().attribution is Attribution.ASSOCIATED
    assert _measurement(attribution_source="referrer data").attribution \
        is Attribution.ATTRIBUTED


def test_no_level_licenses_a_claim_of_agency() -> None:
    """The sentence this whole layer exists to make unreachable."""
    for level in Attribution:
        problem = refuse(level, "Qevik increased organic leads from 34 to 61.")
        assert problem, f"{level.value} licensed a claim of sole agency"
        assert "sole agency" in problem


@pytest.mark.parametrize("sentence", [
    "Qevik increased leads.", "Qevik caused the growth.", "because of Qevik, traffic rose",
    "the campaign caused a lift", "this generated 40 new leads",
    "this resulted in more traffic", "we increased conversions",
])
def test_every_agency_phrasing_is_recognised(sentence) -> None:
    assert claim_of(sentence) is Claim.AGENCY


def test_a_hedge_does_not_launder_an_agency_claim() -> None:
    """Reading the weakest phrase in a sentence is how a disclaimer smuggles one."""
    assert claim_of("During the measurement window, Qevik increased leads.") \
        is Claim.AGENCY


# 1 --- missing baseline does not become zero ------------------------------

def test_a_missing_baseline_is_not_zero() -> None:
    missing = _measurement(baseline=None)
    assert missing.state is BaselineState.NO_BASELINE
    assert missing.change is None, "a missing baseline must not compute as 61 - 0"
    assert missing.improved is None
    assert "no baseline was captured" in missing.statement()


def test_a_baseline_of_zero_is_not_a_missing_baseline() -> None:
    """Genuinely zero is data. The two must not collapse into each other."""
    real_zero = _measurement(baseline=Observation(value=0, source="analytics"))
    assert real_zero.state is BaselineState.MEASUREMENT_AVAILABLE
    assert real_zero.change == 61


# 2 --- missing measurement does not become failure ------------------------

def test_a_missing_observation_is_not_a_negative_result() -> None:
    unmeasured = _measurement(observed=None)
    assert unmeasured.state is BaselineState.BASELINE_AVAILABLE
    assert unmeasured.improved is None, "unmeasured must not read as 'did not improve'"
    assert "no later reading has been taken" in unmeasured.statement()


def test_an_intervention_with_no_measurement_stays_unmeasured() -> None:
    assert summarise([]) == {
        "total": 0, "measured": 0, "not_measured": 0, "by_attribution": {},
        "strongest": "UNKNOWN", "statements": []}


def test_a_summary_counts_what_it_could_not_measure() -> None:
    """A report that drops the unmeasured reads as though all was measured."""
    events = [record(_measurement(), known_jobs={"job-1"}),
              record(_measurement(baseline=None), known_jobs={"job-1"})]
    rows = read(events, tenant="t-qevik")
    summary = summarise(rows)
    assert summary["total"] == 2 and summary["measured"] == 1
    assert summary["not_measured"] == 1


# 3 --- cross-tenant -------------------------------------------------------

def test_another_tenants_measurement_is_inaccessible() -> None:
    mine = record(_measurement(), known_jobs={"job-1"})
    theirs = record(_measurement(tenant_id="t-other"), known_jobs={"job-1"})
    assert len(read([mine, theirs], tenant="t-qevik")) == 1
    assert read([mine, theirs], tenant="t-qevik")[0]["tenant_id"] == "t-qevik"


def test_reading_measurements_requires_a_tenant() -> None:
    with pytest.raises(TenantRequired):
        read([record(_measurement(), known_jobs={"job-1"})])


def test_an_untenanted_measurement_belongs_to_nobody() -> None:
    orphan = record(_measurement(tenant_id=None), known_jobs={"job-1"})
    assert read([orphan], tenant="t-qevik") == []
    assert len(read([orphan], tenant=ALL_TENANTS)) == 1


# 4 --- an AI mention never becomes a ranking ------------------------------

def test_a_position_cannot_be_recorded_without_the_engine_supplying_one() -> None:
    with pytest.raises(Exception, match="not a rank"):
        AIVisibilityObservation(engine="ChatGPT", query="best catering dubai",
                                mentioned=True, position=3)


def test_a_mention_and_a_position_stay_different_facts() -> None:
    chatgpt = AIVisibilityObservation(engine="ChatGPT", query="best catering dubai",
                                      mentioned=True, cited=True,
                                      citation_url="https://ahscatering.com/")
    google = AIVisibilityObservation(engine="Google", query="best catering dubai",
                                     position=7, position_available=True)
    assert chatgpt.position is None
    assert "position not supplied" in chatgpt.statement()
    assert "position 7" in google.statement()
    assert "rank" not in chatgpt.statement().lower()


def test_ai_visibility_metrics_are_rates_not_ranks() -> None:
    """There is deliberately no ai_position metric to record one into."""
    ai = [m for m in BY_KEY.values() if m.family is MetricFamily.AI_VISIBILITY]
    assert ai
    assert all("position" not in m.key and "rank" not in m.key for m in ai)


# 5, 6, 7 --- causation, refusal and what is allowed -----------------------

def test_an_observed_change_does_not_become_causation() -> None:
    observed = _measurement(window=Window(
        baseline_start=NOW - timedelta(days=30), baseline_end=NOW,
        observation_start=NOW, observation_end=NOW + timedelta(days=30)))
    assert observed.attribution is Attribution.OBSERVED
    assert refuse(observed.attribution, "An increase was observed after the intervention.")
    assert not refuse(observed.attribution,
                      "Leads increased from 34 to 61 during the window.")


def test_an_unsupported_causal_sentence_is_rejected() -> None:
    assert vet("Qevik increased organic leads from 34 to 61.", Attribution.ATTRIBUTED)
    assert vet("This resulted in 27 more leads.", Attribution.ASSOCIATED)


def test_evidence_backed_attribution_is_allowed() -> None:
    attributed = _measurement(attribution_source="landing page referrer")
    assert attributed.attribution is Attribution.ATTRIBUTED
    assert vet(attributed.statement(), attributed.attribution) == ""
    assert "attributed to the intervention" in attributed.statement()


def test_every_generated_statement_passes_its_own_gate() -> None:
    """The phrasing helper must never produce a sentence the level forbids."""
    for level in Attribution:
        sentence = phrasing(level, metric="Leads", before=34, after=61,
                            window="the 30-day window", source="referrer data")
        assert permits(level, sentence), f"{level.value} produced {sentence!r}"


@pytest.mark.parametrize("over", [
    {},                                            # measured, associated
    {"attribution_source": "referrer"},            # measured, attributed
    {"baseline": None},                            # no baseline
    {"observed": None},                            # nothing observed yet
    {"window": Window(baseline_start=NOW - timedelta(days=1), baseline_end=NOW,
                      intervention_at=NOW, observation_start=NOW,
                      observation_end=NOW + timedelta(days=60))},   # incomparable
])
def test_a_measurements_own_sentence_always_passes_its_own_gate(over) -> None:
    """The one a customer actually reads, in every state it can be in.

    This gap is how a "no result" sentence containing the word "measured" got
    written: the helper was covered, the model's own statement was not.
    """
    measurement = _measurement(**over)
    sentence = measurement.statement()
    assert vet(sentence, measurement.attribution) == "", \
        f"{measurement.state.value} produced {sentence!r}"


# 8 --- a measurement outside its window -----------------------------------

def test_an_observation_outside_the_window_is_refused() -> None:
    late = _measurement(observed=Observation(value=61, source="analytics",
                                             observed_at=NOW + timedelta(days=400)))
    with pytest.raises(OutsideWindow, match="outside"):
        record(late, known_jobs={"job-1"})


def test_an_undefined_window_is_not_a_before_and_after() -> None:
    undefined = _measurement(window=Window())
    with pytest.raises(OutsideWindow, match="undefined window"):
        record(undefined, known_jobs={"job-1"})


def test_incomparable_periods_are_not_a_before_and_after() -> None:
    """Four weeks against four days finds more of everything."""
    lopsided = _measurement(window=Window(
        baseline_start=NOW - timedelta(days=1), baseline_end=NOW,
        intervention_at=NOW, observation_start=NOW,
        observation_end=NOW + timedelta(days=60)))
    assert lopsided.state is BaselineState.BASELINE_INSUFFICIENT
    assert lopsided.attribution is Attribution.UNKNOWN
    assert lopsided.confidence is Confidence.LOW


# 9, 10 --- provenance cannot be fabricated --------------------------------

def test_a_measurement_cannot_be_attached_to_a_job_that_does_not_exist() -> None:
    with pytest.raises(ProvenanceMissing, match="did not happen"):
        record(_measurement(job_id="job-invented"), known_jobs={"job-1"})


def test_a_measurement_cannot_cite_a_recommendation_that_does_not_exist() -> None:
    with pytest.raises(ProvenanceMissing):
        record(_measurement(recommendation_id="rec-invented"),
               known_jobs={"job-1"}, known_recommendations={"rec-1"})


def test_a_measurement_must_name_the_business_it_describes() -> None:
    with pytest.raises(ProvenanceMissing, match="must name the business"):
        record(_measurement(business_id=""), known_jobs={"job-1"})


def test_the_provenance_chain_reaches_back_to_the_work() -> None:
    event = record(_measurement(), known_jobs={"job-1"},
                   known_recommendations={"rec-1"})
    detail = event.detail
    assert detail["job_id"] == "job-1"
    assert detail["recommendation_id"] == "rec-1"
    assert detail["measurement_id"] and detail["metric_key"]


# 11 --- confidence rather than manufactured precision ---------------------

def test_weak_data_reports_low_confidence_rather_than_a_number() -> None:
    assert _measurement(baseline=None).confidence is Confidence.UNKNOWN
    assert _measurement(observed=None).confidence is Confidence.LOW
    assert _measurement().confidence is Confidence.MEDIUM
    assert _measurement(attribution_source="referrer").confidence is Confidence.HIGH


def test_direction_decides_whether_a_fall_is_an_improvement() -> None:
    """Without it a falling CPA reads as a regression."""
    cpa = Measurement(business_id="b", tenant_id="t", metric_key="cpa",
                      window=window_around(NOW),
                      baseline=Observation(value=42, source="ads"),
                      observed=Observation(value=31, source="ads",
                                           observed_at=NOW + timedelta(days=10)))
    assert BY_KEY["cpa"].better is Direction.DOWN
    assert cpa.change == -11 and cpa.improved is True


# 12 --- AHS is not reported as improved because the framework exists ------

def test_ahs_is_not_reported_as_improved_merely_because_measurement_exists() -> None:
    """The standing control. A framework must not manufacture a result."""
    ahs = Measurement(business_id="466e86e8", tenant_id="t-qevik",
                      metric_key="orphan_pages", job_id="job-1",
                      window=window_around(NOW),
                      baseline=Observation(value=34, source="research"))
    assert ahs.state is BaselineState.BASELINE_AVAILABLE
    assert ahs.improved is None
    assert ahs.attribution is Attribution.UNKNOWN
    assert ahs.confidence is Confidence.LOW
    assert "no result" in ahs.statement()
    assert vet(ahs.statement(), ahs.attribution) == ""


def test_the_ahs_baseline_records_what_research_found_without_claiming_change() -> None:
    ahs = Measurement(business_id="466e86e8", tenant_id="t-qevik",
                      metric_key="orphan_pages", window=window_around(NOW),
                      baseline=Observation(value=34, source="research",
                                           detail="34 pages linked from nothing"))
    assert ahs.baseline.value == 34
    assert ahs.change is None
    assert refuse(ahs.attribution, "Unlinked pages fell from 34 to 0."), \
        "no observation yet, so no change may be stated"
