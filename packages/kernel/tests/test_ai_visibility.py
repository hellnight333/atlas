"""AI visibility: the number it must never invent.

Two failures are available here and both are expensive. Turning a mention into a
rank invents a position the customer will check. Turning a provider outage into
a miss reports our own downtime as their business becoming less visible.
"""

from __future__ import annotations

import pytest

from atlas_kernel.aivisibility import (
    LocalFixtureProvider,
    PendingCredentialProvider,
    ProviderUnavailable,
    fingerprint,
    queries_for,
    read,
    sweep,
    to_baseline,
    to_event,
)
from atlas_kernel.measurement.models import AIVisibilityObservation, BaselineState
from atlas_kernel.measurement.service import Progress, progress_of

A, B = "tenant-alpha", "tenant-beta"
NAME = "AHS Catering & Events"
QUERIES = queries_for(NAME, category="catering", geography="Dubai")


def _answering(**overrides):
    base = dict(name="assistant-a",
                mentions={QUERIES[0]: True, QUERIES[1]: False, QUERIES[2]: False,
                          QUERIES[3]: False, QUERIES[4]: True},
                citations={QUERIES[0]: "https://ahscatering.com/"})
    base.update(overrides)
    return LocalFixtureProvider(**base)


# ============================================ a mention is not a rank

def test_a_mention_is_never_recorded_as_a_position() -> None:
    result = sweep(business_id="ahs", business_name=NAME, tenant=A,
                   providers=[_answering()], category="catering", geography="Dubai")
    assert result.mention_rate == 0.4
    assert result.positions_supplied == ()
    for observation in result.observations:
        assert observation.position is None
        assert observation.position_available is False
    assert "no engine supplied a position" in result.statement()


def test_a_position_without_the_flag_is_refused() -> None:
    with pytest.raises(ValueError, match="a mention is not a rank"):
        AIVisibilityObservation(engine="e", query="q", mentioned=True, position=3)


def test_an_engine_that_supplies_a_rank_may_record_one() -> None:
    """The negative control's other half: the refusal must be about evidence,
    not a blanket ban."""
    ranking = LocalFixtureProvider(name="search-engine", supplies_position=True,
                                   mentions={QUERIES[0]: True},
                                   positions={QUERIES[0]: 3})
    result = sweep(business_id="ahs", business_name=NAME, tenant=A,
                   providers=[ranking], category="catering", geography="Dubai")
    supplied = result.positions_supplied
    assert len(supplied) == 1 and supplied[0].position == 3
    assert "1 supplied a position" in result.statement()


# ============================================ our outage is not their absence

def test_an_unreachable_provider_is_not_counted_as_a_miss() -> None:
    down = PendingCredentialProvider("assistant-b",
                                     credential="QEVIK_AI_VISIBILITY_TOKEN")
    both = sweep(business_id="ahs", business_name=NAME, tenant=A,
                 providers=[_answering(), down], category="catering",
                 geography="Dubai")
    only_up = sweep(business_id="ahs", business_name=NAME, tenant=A,
                    providers=[_answering()], category="catering", geography="Dubai")

    assert both.unavailable == ("assistant-b",)
    assert both.mention_rate == only_up.mention_rate, \
        "an engine we could not ask must not move the rate"


def test_when_nothing_answers_there_is_no_rate() -> None:
    down = PendingCredentialProvider("assistant-b", credential="TOKEN")
    result = sweep(business_id="ahs", business_name=NAME, tenant=A,
                   providers=[down], category="catering", geography="Dubai")

    assert result.mention_rate is None, "None, never 0.0"
    assert result.citation_rate is None
    assert "no result" in result.statement()
    assert "nothing was established" in result.statement()


def test_an_unmeasured_sweep_produces_no_baseline() -> None:
    down = PendingCredentialProvider("assistant-b", credential="TOKEN")
    result = sweep(business_id="ahs", business_name=NAME, tenant=A,
                   providers=[down], category="catering", geography="Dubai")
    baseline = to_baseline(result)

    assert baseline.state is BaselineState.NO_BASELINE
    assert baseline.baseline.value is None
    assert baseline.improved is None
    assert progress_of(baseline) is Progress.UNAVAILABLE


def test_an_unconnected_provider_refuses_rather_than_reporting_absence() -> None:
    provider = PendingCredentialProvider("perplexity", credential="QEVIK_TOKEN")
    with pytest.raises(ProviderUnavailable, match="different from the business not being mentioned"):
        provider.ask("anything", business_name=NAME)


# ============================================ sweeps are comparable

def test_two_sweeps_of_the_same_questions_are_comparable() -> None:
    first = sweep(business_id="ahs", business_name=NAME, tenant=A,
                  providers=[_answering()], category="catering", geography="Dubai")
    second = sweep(business_id="ahs", business_name=NAME, tenant=A,
                   providers=[_answering()], category="catering", geography="Dubai")
    assert first.query_fingerprint == second.query_fingerprint


def test_a_different_question_set_is_not_a_later_reading() -> None:
    """Comparing them would report a change that was ours."""
    with_geography = queries_for(NAME, category="catering", geography="Dubai")
    without = queries_for(NAME, category="catering")
    assert fingerprint(with_geography) != fingerprint(without)


def test_questions_come_from_what_is_known() -> None:
    """A business with no recorded category gets fewer questions, not invented ones."""
    bare = queries_for(NAME)
    full = queries_for(NAME, category="catering", geography="Dubai")
    assert len(bare) < len(full)
    assert queries_for("") == ()
    assert all(NAME in q or "catering" in q for q in full)


# ============================================ tenancy

def test_a_sweep_is_readable_only_by_its_own_tenant() -> None:
    result = sweep(business_id="ahs", business_name=NAME, tenant=A,
                   providers=[_answering()], category="catering", geography="Dubai")
    events = [to_event(result)]
    assert read(events, tenant=A)
    assert read(events, tenant=B) == []


def test_a_sweep_requires_a_tenant() -> None:
    from atlas_kernel.opportunity.tenancy import TenantRequired

    with pytest.raises(TenantRequired):
        sweep(business_id="ahs", business_name=NAME, tenant=None,
              providers=[_answering()])


# ============================================ the credential centre

def test_an_unconnected_integration_names_what_it_blocks() -> None:
    from atlas_kernel.integrations import blocked_capabilities, catalogue
    from atlas_kernel.publication import ConnectionStore

    store = ConnectionStore()
    listed = catalogue(store, tenant=A)
    assert listed["connected"] == []
    providers = {entry["provider"] for entry in listed["pending_credential"]}
    assert "ai-visibility" in providers
    assert "measurement:ai_mention_rate" in blocked_capabilities(store, tenant=A)

    for entry in listed["pending_credential"]:
        assert entry["action"].startswith("Add ")
        assert entry["credential"], "a request must name what to add"


def test_connecting_a_provider_changes_its_status_without_a_stored_flag() -> None:
    from atlas_kernel.integrations import IntegrationStatus, catalogue
    from atlas_kernel.publication import Connection, ConnectionStore

    store = ConnectionStore()
    store.register(Connection(id="c1", tenant_id=A, target="ai-visibility",
                              reference="QEVIK_AI_VISIBILITY_TOKEN"))
    listed = catalogue(store, tenant=A)
    assert [e["provider"] for e in listed["connected"]] == ["ai-visibility"]
    assert listed["connected"][0]["status"] == IntegrationStatus.CONNECTED.value
    # And it is not connected for anybody else.
    assert catalogue(store, tenant=B)["connected"] == []


def test_the_credential_centre_holds_no_secrets() -> None:
    from atlas_kernel.integrations import catalogue
    from atlas_kernel.publication import Connection, ConnectionStore

    store = ConnectionStore()
    store.register(Connection(id="c1", tenant_id=A, target="ai-visibility",
                              reference="QEVIK_AI_VISIBILITY_TOKEN"))
    import os

    os.environ["QEVIK_AI_VISIBILITY_TOKEN"] = "the-actual-secret-value"
    try:
        entries = catalogue(store, tenant=A)["connected"]
        assert [e["connection_id"] for e in entries] == ["c1"], \
            "the connection id identifies it"
        # The resolved value must appear nowhere. Checked against the values
        # rather than the whole payload, because the payload contains prose
        # *about* secrets and matching on the word tests the wrong thing.
        for entry in entries:
            for value in entry.values():
                assert "the-actual-secret-value" not in str(value)
    finally:
        os.environ.pop("QEVIK_AI_VISIBILITY_TOKEN", None)
