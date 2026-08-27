"""Observation → Evidence → Inference → Suggested action, kept apart on purpose.

A finding is a confirmed absence: *this homepage has no Arabic page*, observed,
re-checkable, stated as fact. That is what `models.Finding` is for and it stays
that way.

This module is for the other half, which the system could not previously say at
all: **what somebody thinks the findings mean.** "Seventeen clinics in this
market have no Arabic page" is a count of facts. "Arabic localisation is
commercially valuable here" is a reading of them, and it might be wrong — the
seventeen might serve an entirely English-speaking clientele.

Collapsing those two is how an autonomous system starts producing confident
nonsense, so they are separate types. An `Observation` cannot carry an opinion
and an `Inference` cannot be stated without naming the evidence it rests on.

## What is actually enforced

Prose cannot be validated — no checker can tell "may be valuable" from "is
valuable" reliably, and one that tried would be a checker that passes when it
should not. So the rules here are structural, and each is refusable:

1. An observation carries evidence, and at least one piece.
2. An inference **names the evidence it rests on**, by fingerprint, and every
   fingerprint must be present in the signal. An inference resting on nothing
   is refused — that is acceptance criterion 7, "unsupported conclusions are
   refused", as a constructor error rather than a review comment.
3. An inference may not be certain. `confidence` is bounded below 1.0, because
   certainty is a property of observations and an inference that claims it is
   pretending to be one.
4. A suggested action that reaches outside — email, publishing, spending,
   creating an account — is marked, and marked actions carry
   `needs_approval=True` and cannot be constructed otherwise.

Rule 4 is not the approval boundary; `mission/policy.py` is. It is the *label*
that lets a surface show a person what they would be authorising, and a
mismatch between the label and the deterministic decision is caught by
`test_signals.py` rather than discovered afterwards.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import Evidence


def _now() -> datetime:
    return datetime.now(UTC)


class SignalKind(StrEnum):
    """What sort of thing was noticed. Additive."""

    NEW_BUSINESS = "new_business"
    MISSING_SERVICE = "missing_service"
    #: The site was fetched and what came back is weak. Distinct from
    #: MISSING_SERVICE, which is a fact about a *source* having no website
    #: recorded: this one rests on a response Qevik retrieved and audited.
    WEAK_WEB_PRESENCE = "weak_web_presence"
    MARKET_GAP = "market_gap"
    RISING_DEMAND = "rising_demand"
    TRAFFIC_ANOMALY = "traffic_anomaly"
    REPEATED_PROBLEM = "repeated_problem"
    COMPETITOR_GAP = "competitor_gap"
    NEW_CATEGORY = "new_category"
    #: An existing customer who now qualifies for something else.
    CUSTOMER_UPSELL = "customer_upsell"


class Reach(StrEnum):
    """How far a suggested action's effects travel.

    `INTERNAL` work is undoable inside Qevik. `OUTWARD` leaves the building —
    an email is sent, a page is published, money moves — and is the reason
    `needs_approval` exists on the action rather than being decided by whoever
    renders it.
    """

    INTERNAL = "internal"
    OUTWARD = "outward"


class Observation(BaseModel):
    """What was seen. Factual, countable, re-checkable.

    Deliberately has no `confidence`: an observation is either something that
    was seen or it is not, and a confidence on it would invite the caller to
    record a half-seen thing rather than not recording it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: One sentence of fact. "17 of 40 clinics in Dubai Marina have no Arabic
    #: page." Not "Arabic matters here."
    statement: str
    #: The market, city, country or customer set this was counted over. An
    #: observation without a scope is a number nobody can reproduce.
    scope: str
    #: The count and the population it was drawn from, where the observation is
    #: a count. Kept structured so a reader can see 17/40 rather than "many".
    counted: int | None = None
    out_of: int | None = None
    evidence: list[Evidence] = Field(min_length=1)
    observed_at: datetime = Field(default_factory=_now)

    @field_validator("statement", "scope")
    @classmethod
    def _present(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("an observation needs a statement and a scope")
        return value.strip()

    @model_validator(mode="after")
    def _count_is_coherent(self) -> Observation:
        if self.counted is not None and self.out_of is not None:
            if self.counted > self.out_of:
                raise ValueError(
                    f"{self.counted} of {self.out_of} is not a count anybody can "
                    "act on")
        if self.out_of is not None and self.counted is None:
            raise ValueError(
                "a population without a count says nothing; give both or neither")
        return self

    @property
    def fingerprints(self) -> frozenset[str]:
        return frozenset(e.fingerprint for e in self.evidence)


class Inference(BaseModel):
    """A reading of the evidence. **Not a fact, and never rendered as one.**"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: What somebody thinks this might mean. The surface shows it labelled as
    #: an inference; the words themselves are not validated, because a checker
    #: that tried to tell "may be" from "is" would pass when it should not.
    statement: str
    #: Fingerprints of the evidence this rests on. Every one must appear in the
    #: signal's observations — see the class note, rule 2.
    rests_on: tuple[str, ...] = Field(min_length=1)
    #: Strictly below 1.0. Certainty belongs to observations.
    confidence: float = Field(gt=0.0, lt=1.0)
    #: What would make this wrong. Optional, and worth a great deal when
    #: present: an inference nobody can imagine being wrong is usually a
    #: restatement of the observation.
    would_be_wrong_if: str = ""

    @field_validator("statement")
    @classmethod
    def _present(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("an inference needs a statement")
        return value.strip()


class SuggestedAction(BaseModel):
    """What could be done about it. A proposal, never a trigger."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    statement: str
    reach: Reach = Reach.INTERNAL
    #: True whenever `reach` is OUTWARD. Enforced rather than trusted.
    needs_approval: bool = True
    #: The Qevik capability that would carry it out, if one exists yet.
    capability: str = ""

    @field_validator("statement")
    @classmethod
    def _present(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("a suggested action needs a statement")
        return value.strip()

    @model_validator(mode="after")
    def _outward_needs_a_person(self) -> SuggestedAction:
        if self.reach is Reach.OUTWARD and not self.needs_approval:
            raise ValueError(
                "an action that leaves the building needs a person. Sending, "
                "publishing, spending and account creation are not undoable by "
                "Qevik, so no default may make them automatic.")
        return self


class Signal(BaseModel):
    """One thing noticed, what it rests on, what it might mean, and what next.

    The four parts stay four parts. A surface may render them together; nothing
    may merge them, because the merged form is the one that reads as though the
    inference had been observed.
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: f"sig-{datetime.now(UTC):%Y%m%d%H%M%S%f}")
    kind: SignalKind
    #: The business this is about, when it is about one. Market-level signals
    #: legitimately have none, which is why this is not required — and why
    #: `Finding` could not carry them.
    business_id: str = ""
    scope: str = ""
    #: Which source this came out of, so a reader can weigh it. An opportunity
    #: from a directory somebody edits and one from a regulator's register are
    #: not the same strength of claim.
    source: str = ""
    #: What the work might be worth, and whether anybody measured it.
    #:
    #: `None` with `UNKNOWN` is the honest and overwhelmingly common answer. It
    #: is **not** zero: a business whose value nobody has estimated is not a
    #: business worth nothing, and rendering it as 0 would sort it last for a
    #: reason that does not exist.
    estimated_value: float | None = None
    value_status: str = "UNKNOWN"
    observations: list[Observation] = Field(min_length=1)
    inferences: list[Inference] = Field(default_factory=list)
    actions: list[SuggestedAction] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)

    @model_validator(mode="after")
    def _inferences_rest_on_evidence_that_exists(self) -> Signal:
        """Rule 2. The one that stops a conclusion being attached to nothing."""
        available: set[str] = set()
        for observation in self.observations:
            available |= observation.fingerprints
        for inference in self.inferences:
            missing = sorted(set(inference.rests_on) - available)
            if missing:
                raise ValueError(
                    f"an inference rests on evidence this signal does not "
                    f"carry: {', '.join(missing)}. A conclusion whose support "
                    "is not present is one nobody can check, which is the same "
                    "as one that was made up.")
        return self

    @model_validator(mode="after")
    def _a_value_needs_a_measurement(self) -> Signal:
        """A number and its provenance travel together or not at all."""
        if self.estimated_value is not None and self.value_status == "UNKNOWN":
            raise ValueError(
                "a value of "
                f"{self.estimated_value:g} is labelled UNKNOWN. Either "
                "something measured or estimated it, and the status says which, "
                "or there is no number.")
        if self.estimated_value is None and self.value_status != "UNKNOWN":
            raise ValueError(
                f"value_status is {self.value_status!r} with no value. A status "
                "without a number claims a measurement that is not there.")
        return self

    @property
    def is_actionable_without_a_person(self) -> bool:
        """True only when every suggested action stays inside Qevik."""
        return all(not a.needs_approval for a in self.actions)

    def summary(self) -> dict:
        """The shape a surface renders. Four parts, still four."""
        return {
            "id": self.id, "kind": self.kind.value,
            "business_id": self.business_id, "scope": self.scope,
            "observations": [
                {"statement": o.statement, "scope": o.scope,
                 "counted": o.counted, "out_of": o.out_of,
                 "evidence_count": len(o.evidence),
                 "observed_at": o.observed_at.isoformat()}
                for o in self.observations],
            "inferences": [
                {"statement": i.statement, "confidence": i.confidence,
                 "rests_on": list(i.rests_on),
                 "would_be_wrong_if": i.would_be_wrong_if,
                 # Said in the payload, not left to the renderer to remember.
                 "is_an_inference": True}
                for i in self.inferences],
            "actions": [
                {"statement": a.statement, "reach": a.reach.value,
                 "needs_approval": a.needs_approval,
                 "capability": a.capability}
                for a in self.actions],
            "source": self.source,
            "detected_at": self.created_at.isoformat(),
            # Never a bare number: the status travels with it, and UNKNOWN
            # stays UNKNOWN rather than becoming 0.
            "value": {"amount": self.estimated_value,
                      "status": self.value_status},
            "created_at": self.created_at.isoformat(),
        }


def market_gap(findings: list, *, scope: str, population: int,
               says: str, might_mean: str, confidence: float,
               action: str, capability: str = "",
               wrong_if: str = "") -> Signal:
    """A market-level signal built from per-business findings.

    The user's own example, as code: seventeen clinics with a confirmed absence
    of an Arabic page is an **observation** — a count of facts each of which was
    separately evidenced. That Arabic localisation is commercially valuable
    there is an **inference**, and it might be wrong; the seventeen might serve
    an entirely English-speaking clientele.

    The evidence is the findings' own evidence, carried through rather than
    summarised, so the inference rests on the same records a reviewer can open.
    Nothing new is observed here: this aggregates what detectors already
    confirmed, which is why it cannot manufacture a market.
    """
    if not findings:
        raise ValueError(
            "a market gap over no findings is a claim about nothing")
    if population < len(findings):
        raise ValueError(
            f"{len(findings)} findings out of a population of {population} is "
            "not a count anybody can act on")

    evidence = [piece for finding in findings for piece in finding.evidence]
    if not evidence:
        raise ValueError(
            "these findings carry no evidence, so the count cannot be checked")

    observation = Observation(
        statement=says, scope=scope, counted=len(findings),
        out_of=population, evidence=evidence)
    return Signal(
        kind=SignalKind.MARKET_GAP, scope=scope,
        observations=[observation],
        inferences=[Inference(
            statement=might_mean,
            rests_on=tuple(sorted(observation.fingerprints)),
            confidence=confidence, would_be_wrong_if=wrong_if)],
        actions=[SuggestedAction(
            statement=action, reach=Reach.OUTWARD, needs_approval=True,
            capability=capability)])


def refuse_conclusion_without_evidence(signal: Signal) -> str:
    """Why this signal may not be shown as an opportunity, or "".

    A separate front door for the same rule, for a signal arriving from
    somewhere the constructor did not run — a stored row, a model's output, an
    API body.
    """
    if not signal.observations:
        return "a signal with no observation is a claim about nothing"
    if not any(o.evidence for o in signal.observations):
        return "a signal whose observations carry no evidence cannot be checked"
    for inference in signal.inferences:
        if not inference.rests_on:
            return (f"the inference {inference.statement!r} names no evidence. "
                    "An unsupported conclusion is refused.")
    return ""


__all__ = ["Inference", "Observation", "Reach", "Signal", "SignalKind",
           "SuggestedAction", "market_gap",
           "refuse_conclusion_without_evidence"]
