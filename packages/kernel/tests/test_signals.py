"""Observation, evidence, inference, action — and the walls between them.

"Seventeen clinics have no Arabic page" is a count of facts. "Arabic
localisation is commercially valuable here" is a reading of them, and it might
be wrong: the seventeen might serve an entirely English-speaking clientele.
Collapsing those two is how an autonomous system starts producing confident
nonsense, so they are separate types and these tests are the walls.
"""

from __future__ import annotations

import pytest

from atlas_kernel.opportunity import signals as S
from atlas_kernel.opportunity.models import (
    Evidence,
    EvidenceKind,
    Finding,
    FindingKind,
    Severity,
)


def an_evidence(url: str) -> Evidence:
    return Evidence(kind=EvidenceKind.HTML_CONTENT, source=url,
                    observed={"arabic_link": False, "lang": "en"},
                    detector="website-audit")


def a_finding(url: str) -> Finding:
    return Finding(business_id=f"b-{url}", kind=FindingKind.NO_ARABIC,
                   severity=Severity.MEDIUM,
                   statement="The homepage has no Arabic version.",
                   evidence=[an_evidence(url)], confidence=0.9)


def an_observation() -> S.Observation:
    return S.Observation(
        statement="17 of 40 clinics in Dubai Marina have no Arabic page.",
        scope="dubai-marina/dental", counted=17, out_of=40,
        evidence=[an_evidence("https://a.test/")])


# ============================== 6. an opportunity is generated from evidence

def test_a_market_gap_is_built_from_findings_that_already_exist():
    """Nothing new is observed: this aggregates what detectors confirmed,
    which is why it cannot manufacture a market."""
    findings = [a_finding(f"https://clinic{n}.test/") for n in range(17)]
    signal = S.market_gap(
        findings, scope="dubai-marina/dental", population=40,
        says="17 of 40 clinics in Dubai Marina have no Arabic page.",
        might_mean="Arabic localisation may be commercially valuable here.",
        confidence=0.45,
        wrong_if="the clientele is predominantly English-speaking",
        action="Offer the Arabic experience to qualifying clinics.",
        capability="arabic-builder")

    assert signal.kind is S.SignalKind.MARKET_GAP
    assert signal.observations[0].counted == 17
    assert signal.observations[0].out_of == 40
    assert len(signal.observations[0].evidence) == 17
    assert signal.inferences[0].confidence == 0.45
    assert signal.actions[0].needs_approval


def test_the_four_parts_stay_four_parts_in_the_payload():
    """A surface may render them together; nothing may merge them, because the
    merged form reads as though the inference had been observed."""
    rendered = S.market_gap(
        [a_finding("https://a.test/")], scope="x", population=1,
        says="1 of 1 has no Arabic page.", might_mean="Might matter.",
        confidence=0.3, action="Offer it.").summary()
    assert set(rendered) >= {"observations", "inferences", "actions"}
    assert rendered["inferences"][0]["is_an_inference"] is True
    assert "confidence" not in rendered["observations"][0]


def test_an_inference_is_labelled_as_one_in_the_payload_itself():
    """Said in the data, not left to the renderer to remember."""
    signal = S.Signal(kind=S.SignalKind.MARKET_GAP,
                      observations=[an_observation()],
                      inferences=[S.Inference(
                          statement="Might matter.",
                          rests_on=tuple(an_observation().fingerprints),
                          confidence=0.5)])
    assert signal.summary()["inferences"][0]["is_an_inference"] is True


def test_a_market_gap_over_no_findings_is_refused():
    with pytest.raises(ValueError, match="claim about nothing"):
        S.market_gap([], scope="x", population=10, says="none",
                     might_mean="nothing", confidence=0.5, action="do nothing")


def test_a_count_larger_than_its_population_is_refused():
    with pytest.raises(ValueError, match="not a count anybody can act on"):
        S.market_gap([a_finding("https://a.test/")], scope="x", population=0,
                     says="1 of 0", might_mean="?", confidence=0.5, action="x")


# ================================== 7. unsupported conclusions are refused

def test_an_inference_resting_on_evidence_the_signal_lacks_is_refused():
    """The rule that stops a conclusion being attached to nothing."""
    with pytest.raises(ValueError, match="does not carry"):
        S.Signal(kind=S.SignalKind.MARKET_GAP,
                 observations=[an_observation()],
                 inferences=[S.Inference(statement="Invented.",
                                         rests_on=("no-such-fingerprint",),
                                         confidence=0.9)])


def test_an_inference_must_name_something_it_rests_on():
    with pytest.raises(ValueError):
        S.Inference(statement="Just so.", rests_on=(), confidence=0.5)


def test_an_inference_may_not_be_certain():
    """Certainty is a property of observations. An inference claiming it is
    pretending to be one."""
    supporting = tuple(an_observation().fingerprints)
    with pytest.raises(ValueError):
        S.Inference(statement="Definitely true.", rests_on=supporting,
                    confidence=1.0)
    with pytest.raises(ValueError):
        S.Inference(statement="Definitely false.", rests_on=supporting,
                    confidence=0.0)


def test_an_observation_must_carry_evidence():
    with pytest.raises(ValueError):
        S.Observation(statement="17 clinics lack Arabic.", scope="x",
                      evidence=[])


def test_an_observation_has_no_confidence_field():
    """A confidence on an observation invites recording a half-seen thing
    rather than not recording it."""
    assert "confidence" not in S.Observation.model_fields


def test_a_population_without_a_count_says_nothing():
    with pytest.raises(ValueError, match="give both or neither"):
        S.Observation(statement="many", scope="x", out_of=40,
                      evidence=[an_evidence("https://a.test/")])


def test_the_separate_front_door_refuses_the_same_things():
    """For a signal arriving from a stored row, a model's output or an API
    body, where the constructor did not run."""
    good = S.market_gap([a_finding("https://a.test/")], scope="x",
                        population=1, says="1 of 1.", might_mean="Might.",
                        confidence=0.4, action="Offer.")
    assert S.refuse_conclusion_without_evidence(good) == ""

    hollow = good.model_copy(update={
        "inferences": [good.inferences[0].model_construct(
            statement="Unsupported.", rests_on=(), confidence=0.9)]})
    assert "names no evidence" in S.refuse_conclusion_without_evidence(hollow)


# ============ 10. no external side effect without policy/approval

def test_an_action_that_leaves_the_building_cannot_be_automatic():
    """Sending, publishing, spending and account creation are not undoable by
    Qevik, so no default may make them automatic."""
    with pytest.raises(ValueError, match="needs a person"):
        S.SuggestedAction(statement="Email all 17 clinics.",
                          reach=S.Reach.OUTWARD, needs_approval=False)


def test_an_outward_action_makes_the_whole_signal_need_a_person():
    signal = S.market_gap([a_finding("https://a.test/")], scope="x",
                          population=1, says="1 of 1.", might_mean="Might.",
                          confidence=0.4, action="Email them.")
    assert not signal.is_actionable_without_a_person


def test_internal_work_may_be_automatic():
    """The rule is about reach, not about caution for its own sake."""
    quiet = S.SuggestedAction(statement="Record this for the weekly summary.",
                              reach=S.Reach.INTERNAL, needs_approval=False)
    signal = S.Signal(kind=S.SignalKind.NEW_BUSINESS,
                      observations=[an_observation()], actions=[quiet])
    assert signal.is_actionable_without_a_person


def test_a_signal_carries_no_way_to_execute_anything():
    """A suggested action is a proposal, never a trigger. If this model ever
    grows a callable, discovery has become an orchestrator."""
    for name, field in S.SuggestedAction.model_fields.items():
        assert not callable(getattr(field, "default", None)) or name == "reach"
    assert not any(hasattr(S.Signal, attr)
                   for attr in ("run", "execute", "dispatch", "send"))


def test_the_labelled_reach_agrees_with_the_deterministic_policy():
    """The label is what a surface shows a person. `mission/policy.py` is the
    boundary. A mismatch between them is caught here rather than discovered
    afterwards."""
    from atlas_kernel.mission import policy
    from atlas_kernel.mission.models import Plan, PlanStep

    outward = S.market_gap([a_finding("https://a.test/")], scope="x",
                           population=1, says="1 of 1.", might_mean="Might.",
                           confidence=0.4, action="Email them.",
                           capability="correspondent")
    assert outward.actions[0].needs_approval

    # The same work as a plan carried out by the agent that would do it.
    verdict = policy.decide(
        Plan(goal="Email the clinics",
             steps=(PlanStep(order=1, title="send"),), estimated_cost=0.1),
        agent_id="correspondent", modifies_qevik_itself=False)
    assert verdict.needs_a_person, (
        "the signal says a person is needed and policy does not")
    assert verdict.requirement is policy.Requirement.ARTEFACT
