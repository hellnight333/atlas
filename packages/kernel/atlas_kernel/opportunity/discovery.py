"""What "new" means, and the three different things it can mean.

The dangerous sentence this module exists to make unsayable:

    Qevik found it, therefore it is new to Google Maps.

It does not follow, and the gap between those two is where an autonomous
discovery system starts inventing. Qevik's memory being empty is a fact about
**Qevik**. Whether a business is new to the world is a fact about the world, and
only the world can supply it.

## Three states, and only one of them says anything about the world

``NEW_TO_QEVIK``
    Not in Qevik's durable memory before this sighting. That is all it means. A
    clinic trading for eleven years is `NEW_TO_QEVIK` the first time anything
    looks it up, and saying so is honest.

``DISCOVERED_BY_QEVIK``
    `NEW_TO_QEVIK`, **and** Qevik found it itself rather than being handed it.
    A claim about provenance, not about novelty: it distinguishes a business the
    scanner surfaced from one an operator typed in, which matters when judging
    whether the pipeline is working. It still says nothing about the world.

``PROVEN_NEW_TO_SOURCE``
    The source itself provided evidence that the entity is new **to that
    source** — a listing date, a first-review date, a "recently added" flag.
    Even this is narrower than it sounds: new to Google Maps is not new to the
    world, and the state name says `TO_SOURCE` so nobody can round it up.

The ladder only ever climbs on evidence. `classify()` cannot return
`PROVEN_NEW_TO_SOURCE` without a `Novelty` observation attached to the sighting,
and `Novelty` cannot be constructed without naming the field it read and the
value it read — so a caller that wants the strong state has to have looked
something up, and a reviewer can go and check the same field.

## Why not a boolean

`resolve_business()` already returns "did this row exist" as a bool, and the
first draft of discovery used it directly as "is new". That is the whole bug in
one variable: one bit cannot carry "absent from my notes" and "the world says
this is new", and a bool named `is_new` invites a caller to read whichever it
needs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import Evidence


def _now() -> datetime:
    return datetime.now(UTC)


class DiscoveryState(StrEnum):
    """How new this sighting is, and to whom.

    Ordered weakest to strongest claim. Nothing may be promoted without the
    evidence the stronger claim requires.
    """

    #: Qevik has seen this before. The ordinary case after the first scan.
    KNOWN = "KNOWN"
    #: Absent from Qevik's memory. A fact about Qevik.
    NEW_TO_QEVIK = "NEW_TO_QEVIK"
    #: Absent from Qevik's memory, and Qevik surfaced it rather than being told.
    DISCOVERED_BY_QEVIK = "DISCOVERED_BY_QEVIK"
    #: The source evidences that it is new **to that source**.
    PROVEN_NEW_TO_SOURCE = "PROVEN_NEW_TO_SOURCE"


#: States that assert something about the world rather than about Qevik. Exactly
#: one, and it is the only one whose name a reader could mistake for "new".
ABOUT_THE_WORLD: frozenset[DiscoveryState] = frozenset(
    {DiscoveryState.PROVEN_NEW_TO_SOURCE})


class Origin(StrEnum):
    """Where a sighting came from. Decides provenance, never novelty."""

    #: A scan Qevik ran on its own.
    SCAN = "scan"
    #: A person typed it in, or it arrived in a seed file.
    SUPPLIED = "supplied"
    #: Another Qevik subsystem referred it — an existing customer record, say.
    INTERNAL = "internal"


class Novelty(BaseModel):
    """The source's own statement that something is new to it.

    Cannot be constructed vaguely. It names the field it read and the value it
    read, so "the source says it is new" is a claim somebody can go and check
    against the same field — and so a caller cannot conjure the strong state by
    passing `True`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: The source that said so — `google-places`, `overpass`, a directory name.
    source: str
    #: The field consulted, exactly as the source names it.
    field: str
    #: What that field contained. Kept raw; a summarised value cannot be
    #: re-checked.
    value: str
    #: When the source says the entity appeared, if it says.
    appeared_at: datetime | None = None
    #: The evidence record for the response this was read out of.
    evidence: Evidence

    @field_validator("source", "field", "value")
    @classmethod
    def _present(cls, value: str) -> str:
        if not value.strip():
            raise ValueError(
                "novelty must name the source, the field and the value read. "
                "Without all three, 'the source says it is new' is not "
                "checkable, and an unfalsifiable claim is the thing this "
                "module exists to prevent.")
        return value.strip()


class Sighting(BaseModel):
    """One observation of one entity, by one source, at one moment."""

    model_config = ConfigDict(frozen=True)

    #: The business id once resolved. Empty before resolution.
    business_id: str = ""
    name: str
    source: str
    #: The source's own stable identifier — a place id, an OSM node, a URL.
    #: Kept separate from `source_url` because an id survives a site redesign
    #: and a URL does not.
    source_id: str = ""
    source_url: str = ""
    country: str = ""
    city: str = ""
    origin: Origin = Origin.SCAN
    observed_at: datetime = Field(default_factory=_now)
    evidence: list[Evidence] = Field(default_factory=list)
    #: Present only when the source actually said so.
    novelty: Novelty | None = None

    @field_validator("name", "source")
    @classmethod
    def _named(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("a sighting needs a name and a source")
        return value.strip()


class Classification(BaseModel):
    """What state a sighting is in, and the reason, in checkable terms."""

    model_config = ConfigDict(frozen=True)

    state: DiscoveryState
    because: str
    #: True only for `PROVEN_NEW_TO_SOURCE`. Carried explicitly so a renderer
    #: never has to infer it from the name of the state.
    claims_about_the_world: bool = False

    def summary(self) -> dict:
        return {"state": self.state.value, "because": self.because,
                "claims_about_the_world": self.claims_about_the_world}


def classify(sighting: Sighting, *, known_to_qevik: bool) -> Classification:
    """Which kind of new this is.

    `known_to_qevik` comes from `OpportunityRepository.resolve_business`, which
    is the only thing that knows. It is passed in rather than looked up so this
    function stays pure and testable, and so the caller cannot be under the
    impression that this consults the database.
    """
    if known_to_qevik:
        return Classification(
            state=DiscoveryState.KNOWN,
            because="Qevik has a record of this entity from an earlier sighting")

    if sighting.novelty is not None:
        return Classification(
            state=DiscoveryState.PROVEN_NEW_TO_SOURCE,
            claims_about_the_world=True,
            because=(f"{sighting.novelty.source} reports it as new: "
                     f"{sighting.novelty.field}={sighting.novelty.value}. This "
                     f"is new to {sighting.novelty.source}, which is not the "
                     "same as new to the world"))

    if sighting.origin is Origin.SCAN:
        return Classification(
            state=DiscoveryState.DISCOVERED_BY_QEVIK,
            because=("absent from Qevik's memory, and surfaced by a scan rather "
                     "than supplied. Says nothing about whether the entity is "
                     "new to anybody else"))

    return Classification(
        state=DiscoveryState.NEW_TO_QEVIK,
        because=("absent from Qevik's memory. Says nothing about whether the "
                 "entity is new to anybody else"))


def refuse_unsupported_novelty(state: DiscoveryState,
                               novelty: Novelty | None) -> str:
    """Why this pairing is not allowed, or "".

    A second check on the thing that matters most, deliberately separate from
    `classify` so that a caller assembling a `Classification` by hand — from a
    stored row, from an API body, from a model's output — is held to the same
    rule as one going through the front door.
    """
    if state is DiscoveryState.PROVEN_NEW_TO_SOURCE and novelty is None:
        return ("PROVEN_NEW_TO_SOURCE asserts that a source said this entity is "
                "new, and no source said so. Qevik not having seen something "
                "is a fact about Qevik; use NEW_TO_QEVIK or "
                "DISCOVERED_BY_QEVIK.")
    return ""


def describe() -> list[dict]:
    """The states and what each one may be read as claiming."""
    return [
        {"state": state.value,
         "claims_about_the_world": state in ABOUT_THE_WORLD,
         "means": {
             DiscoveryState.KNOWN: "Qevik has seen this before",
             DiscoveryState.NEW_TO_QEVIK:
                 "absent from Qevik's memory; nothing more",
             DiscoveryState.DISCOVERED_BY_QEVIK:
                 "absent from Qevik's memory, and Qevik surfaced it itself",
             DiscoveryState.PROVEN_NEW_TO_SOURCE:
                 "the source evidences that it is new to that source",
         }[state]}
        for state in DiscoveryState
    ]


__all__ = ["ABOUT_THE_WORLD", "Classification", "DiscoveryState", "Novelty",
           "Origin", "Sighting", "classify", "describe",
           "refuse_unsupported_novelty"]
