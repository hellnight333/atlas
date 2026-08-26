"""Turning a fetched response into a sighting, by declared rules only.

The join the discovery chain was missing. Everything either side of it existed:
a recipe fetches through the guard and records `Evidence`, and
`opportunity/scan.py` resolves a `Sighting` against memory and classifies it.
Nothing turned the first into the second.

## Why this is a declaration and not a parser

The obvious implementation is a function that reads a response and returns
whatever it can find. That is also the implementation where, six months from
now, a model is handed a page and asked to "pull out the business details" —
and a `Sighting` arrives whose `name` came from a heading, whose `country` came
from a guess, and whose evidence supports neither.

So an extractor **declares which fields it can produce**, and a field it does
not declare cannot appear in its output. That is the same shape as
`origins.Registry` and `fabric.recipes`: the allow-list is code, and the thing
being allowed is a name.

## Absence has three answers, not two

The tag `website` missing from an OpenStreetMap node means *OpenStreetMap does
not record a website for this business*. It does not mean the business has no
website. The existing Overpass source already got this right in a comment; this
makes it a type, so a caller cannot lose the distinction by reading a `None`.

    OBSERVED           the source stated a value
    ABSENT_IN_SOURCE   the source was consulted and had none
    NOT_CONSULTED      this extractor does not read that field at all

`NOT_CONSULTED` is the one that matters most and is the easiest to omit: a field
nobody looked for is not a field that is missing, and a detector treating the
two alike produces "this clinic has no phone number" about a source that was
never asked.

## Provenance

Every extraction carries the fingerprint of the evidence it came from, so a
sighting is traceable to the exact bytes that produced it. An extraction whose
evidence is gone is a claim, and this module produces no claims.

## What an LLM may do here

Nothing. There is no prompt and no provider. A model may eventually *explain* an
extraction or propose that a new source is worth adding, and adding it is a code
change somebody reviews.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .discovery import Novelty, Origin, Sighting
from .models import Evidence, EvidenceKind


class Presence(StrEnum):
    """What the source had to say about one field."""

    #: The source stated a value.
    OBSERVED = "observed"
    #: The source was consulted for this field and had none. A fact about the
    #: source, never about the business.
    ABSENT_IN_SOURCE = "absent_in_source"
    #: This extractor does not read that field. Not the same as missing.
    NOT_CONSULTED = "not_consulted"


class ExtractionError(RuntimeError):
    """Evidence this extractor cannot read. Never a partial guess."""


class Field_(BaseModel):
    """One field an extractor can fill, and where it reads it from."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: The `Sighting` field this fills. Checked against the model, so a rule
    #: naming a field that does not exist fails at import rather than producing
    #: an extraction nobody can use.
    name: str
    #: Source keys, in priority order. The first that carries a value wins —
    #: several tags carry a website in OSM, and checking only `website` reports
    #: businesses as siteless when the URL was recorded under another key.
    reads: tuple[str, ...]
    #: When true, an element without this field is skipped rather than
    #: extracted. An unnamed node cannot be written to or researched, and would
    #: arrive as an anonymous row that poisons the counts.
    required: bool = False
    notes: str = ""

    @field_validator("name")
    @classmethod
    def _is_a_sighting_field(cls, value: str) -> str:
        if value not in Sighting.model_fields:
            raise ValueError(
                f"{value!r} is not a field of Sighting. An extractor may only "
                f"fill declared fields; known: "
                f"{', '.join(sorted(Sighting.model_fields))}")
        return value

    @field_validator("reads")
    @classmethod
    def _reads_something(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("a field rule must say which source keys it reads")
        return value


class Extraction(BaseModel):
    """One entity read out of one piece of evidence."""

    model_config = ConfigDict(frozen=True)

    extractor: str
    #: What the source calls this thing. The stable identifier.
    source_id: str
    #: Field name -> value, for fields the source actually stated.
    fields: dict[str, str] = Field(default_factory=dict)
    #: Field name -> `Presence`, for **every** field the extractor declares plus
    #: every field it does not. A caller reading this cannot mistake "not looked
    #: for" for "not there".
    presence: dict[str, Presence] = Field(default_factory=dict)
    #: The evidence this came out of. Provenance: a sighting is traceable to the
    #: exact bytes that produced it.
    evidence_fingerprint: str
    evidence_source: str
    #: Anything the extractor kept that is not a Sighting field — OSM tags, a
    #: category. Never promoted into a field; available for a detector.
    extra: dict[str, Any] = Field(default_factory=dict)

    def absent_in_source(self, field: str) -> bool:
        """Whether the source was consulted for this and had none.

        The question a detector must ask before concluding anything about a
        business from a missing value.
        """
        return self.presence.get(field) is Presence.ABSENT_IN_SOURCE

    def summary(self) -> dict:
        return {"extractor": self.extractor, "source_id": self.source_id,
                "fields": dict(self.fields),
                "presence": {k: v.value for k, v in self.presence.items()},
                "evidence": self.evidence_fingerprint,
                "evidence_source": self.evidence_source}


class Extractor(BaseModel):
    """A declared way of reading one source's responses.

    Typed and inspectable: `describe()` says exactly what it consumes and what
    it can produce, which is the thing a reviewer needs before trusting a
    sighting that came out of it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    #: The source name recorded on every sighting this produces.
    source: str
    #: What it consumes. An extractor handed the wrong kind refuses rather than
    #: trying: a JSON reader pointed at HTML produces nonsense confidently.
    evidence_kind: EvidenceKind
    #: The content type it expects, as a substring match. Empty accepts any.
    content_type: str = ""
    fields: tuple[Field_, ...]
    #: Whether this source can evidence that an entity is new **to it**. Almost
    #: always false, and false by default: `PROVEN_NEW_TO_SOURCE` requires the
    #: source to have said so, and most sources say nothing of the kind.
    can_evidence_novelty: bool = False
    notes: str = ""

    @property
    def produces(self) -> tuple[str, ...]:
        return tuple(sorted(rule.name for rule in self.fields))

    def presence_for(self, stated: set[str]) -> dict[str, Presence]:
        """The presence map for one element.

        Covers every `Sighting` field, not only the declared ones — that is
        what makes `NOT_CONSULTED` visible rather than implied by absence from
        a dict.
        """
        declared = {rule.name for rule in self.fields}
        return {
            name: (Presence.OBSERVED if name in stated
                   else Presence.ABSENT_IN_SOURCE if name in declared
                   else Presence.NOT_CONSULTED)
            for name in Sighting.model_fields
        }

    def describe(self) -> dict:
        return {"id": self.id, "source": self.source,
                "consumes": {"evidence_kind": self.evidence_kind.value,
                             "content_type": self.content_type or "any"},
                "produces": list(self.produces),
                "can_evidence_novelty": self.can_evidence_novelty,
                "rules": [{"field": r.name, "reads": list(r.reads),
                           "required": r.required, "notes": r.notes}
                          for r in self.fields],
                "notes": self.notes}


def _refuse_wrong_evidence(extractor: Extractor, evidence: Evidence) -> None:
    if evidence.kind is not extractor.evidence_kind:
        raise ExtractionError(
            f"{extractor.id} reads {extractor.evidence_kind.value} and this is "
            f"{evidence.kind.value}. A reader pointed at the wrong shape "
            "produces nonsense confidently.")
    seen = str(evidence.observed.get("content_type", ""))
    if extractor.content_type and extractor.content_type not in seen:
        raise ExtractionError(
            f"{extractor.id} expects {extractor.content_type!r} and the server "
            f"sent {seen!r}.")
    if evidence.observed.get("body_truncated"):
        raise ExtractionError(
            f"{extractor.id} was given a truncated body. Extracting from the "
            "part that fitted would report the entities in the first "
            "256 KB as though they were all of them.")
    if not str(evidence.observed.get("body") or "").strip():
        raise ExtractionError(
            f"{extractor.id} was given evidence with no body to read.")


def _value(tags: dict, rule: Field_) -> str:
    for key in rule.reads:
        found = str(tags.get(key) or "").strip()
        if found:
            return found
    return ""


# ============================================================ OpenStreetMap

#: Reads an Overpass API response. Chosen as the first real source because it is
#: public, free, needs no credential, and returns **structured JSON** rather than
#: prose — so extraction is a declared mapping from named keys, not a model
#: reading a page and deciding what looks like a business name.
OPENSTREETMAP = Extractor(
    id="openstreetmap",
    source="openstreetmap",
    evidence_kind=EvidenceKind.HTTP_RESPONSE,
    content_type="json",
    can_evidence_novelty=False,
    fields=(
        Field_(name="name", reads=("name", "name:en"), required=True,
               notes="An unnamed node cannot be written to or researched, and "
                     "would arrive as an anonymous row that poisons the counts."),
        Field_(name="source_url",
               reads=("website", "contact:website", "url", "website:en"),
               notes="Several tags carry a website. Reading only `website` "
                     "reports businesses as siteless when OSM recorded the URL "
                     "under another key — the exact false positive this must "
                     "not produce."),
        Field_(name="city", reads=("addr:city",)),
        Field_(name="country", reads=("addr:country",)),
    ),
    notes=("`country` is frequently absent in OSM and is left absent rather "
           "than inferred from the query's bounding box. A country Qevik "
           "supplied is not a country the source stated."),
)


def extract_overpass(evidence: Evidence, *,
                     extractor: Extractor = OPENSTREETMAP) -> list[Extraction]:
    """Every named element in an Overpass response, as declared extractions."""
    _refuse_wrong_evidence(extractor, evidence)
    try:
        payload = json.loads(str(evidence.observed.get("body")))
    except json.JSONDecodeError as broken:
        raise ExtractionError(
            f"{extractor.id} could not read the response as JSON: {broken}"
        ) from broken

    elements = payload.get("elements")
    if not isinstance(elements, list):
        raise ExtractionError(
            f"{extractor.id} expects an Overpass response with an `elements` "
            "list and this has none.")

    found: list[Extraction] = []
    for element in elements:
        tags = element.get("tags") or {}
        stated: set[str] = set()
        fields: dict[str, str] = {}
        for rule in extractor.fields:
            value = _value(tags, rule)
            if value:
                fields[rule.name] = value
                stated.add(rule.name)
            elif rule.required:
                break
        else:
            found.append(Extraction(
                extractor=extractor.id,
                source_id=f"{element.get('type')}/{element.get('id')}",
                fields=fields,
                presence=extractor.presence_for(stated),
                evidence_fingerprint=evidence.fingerprint,
                evidence_source=evidence.source,
                # Kept, not promoted: a category is useful to a detector and is
                # not a Sighting field.
                extra={"osm_tags": {k: v for k, v in tags.items()
                                    if k in {"shop", "amenity", "craft",
                                             "healthcare"}}},
            ))
    return found


def sighting_from(extraction: Extraction, evidence: Evidence, *,
                  source: str, origin: Origin = Origin.SCAN,
                  novelty: Novelty | None = None) -> Sighting:
    """One extraction as a sighting, carrying its evidence with it.

    `novelty` is a parameter and defaults to `None`, so producing
    `PROVEN_NEW_TO_SOURCE` still requires a caller to have obtained a `Novelty`
    — which cannot be constructed without naming the source, the field and the
    value read. Extraction does not create novelty and cannot.
    """
    return Sighting(
        name=extraction.fields.get("name", ""),
        source=source,
        source_id=extraction.source_id,
        source_url=extraction.fields.get("source_url", ""),
        country=extraction.fields.get("country", ""),
        city=extraction.fields.get("city", ""),
        origin=origin,
        evidence=[evidence],
        novelty=novelty,
    )


#: Extractors this deployment has. In code, beside the other registries, for the
#: same reason: what a source is allowed to produce is a decision somebody makes
#: on purpose.
EXTRACTORS: tuple[Extractor, ...] = (OPENSTREETMAP,)


class UnknownExtractor(Exception):
    """A name nobody declared. Never a fallback to another reader."""


def get(extractor_id: str) -> Extractor:
    for found in EXTRACTORS:
        if found.id == extractor_id:
            return found
    raise UnknownExtractor(
        f"no extractor named {extractor_id!r}. Known: "
        f"{', '.join(sorted(e.id for e in EXTRACTORS))}.")


def describe() -> list[dict]:
    return [e.describe() for e in EXTRACTORS]


__all__ = ["EXTRACTORS", "OPENSTREETMAP", "Extraction", "ExtractionError",
           "Extractor", "Field_", "Presence", "UnknownExtractor", "describe",
           "extract_overpass", "get", "sighting_from"]
