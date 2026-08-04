"""Entities for the Opportunity Factory.

Read ``docs/OPPORTUNITY_FACTORY.md`` before changing anything here. Two rules in
this file are load-bearing rather than stylistic, and both are enforced by
construction:

* **A finding cannot exist without evidence.** Atlas is about to tell a stranger
  something is wrong with their business. If it cannot say what it observed,
  where, when and with what, it does not get to make the claim. There is no
  constructor path that produces an unevidenced finding.
* **A proposal cannot exist without findings.** Every claim cites one. This is
  what turns "never send generic templates" into a property of the system
  instead of a hope about how well a prompt was written.

The layering matters too. Nothing in the source layer may reference a channel, a
proposal or a send: a business is a fact about the world and does not know it is
being sold to. That separation is what will let Website, Amazon and SaaS each
put a different offer over the same discovery later, without any of this
changing.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid4())


def _digest(*parts: object) -> str:
    """A stable hash of some inputs.

    ``None`` and ``""`` stay distinct — "absent" and "blank" are different
    states, and collapsing them would hide a real change from the fingerprint
    check that guards every send.
    """
    material = "\x1f".join("\x00NULL" if part is None else str(part) for part in parts)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Evidence — the thing that makes a claim legitimate
# ---------------------------------------------------------------------------


class EvidenceKind(StrEnum):
    """How something came to be known.

    ``ASSERTED`` exists so that a human-supplied fact can enter the system
    honestly rather than being dressed up as an observation. It is deliberately
    the least trusted kind, and scoring treats it that way.
    """

    HTTP_RESPONSE = "http_response"
    HTML_CONTENT = "html_content"
    TLS_CERTIFICATE = "tls_certificate"
    DNS_RECORD = "dns_record"
    TIMING = "timing"
    SCREENSHOT = "screenshot"
    ASSERTED = "asserted"


class Evidence(BaseModel):
    """What was actually observed.

    Every field here answers a question someone could reasonably ask about a
    claim: what did you look at, when, what did you get back, and how do I check
    it myself. A finding carrying one of these can be defended; a finding
    without one cannot, which is why it is not permitted to exist.
    """

    model_config = ConfigDict(frozen=True)

    kind: EvidenceKind
    #: What was inspected — a URL, a hostname, a file path.
    source: str
    #: The observation itself, in whatever shape the detector produced. Kept raw
    #: on purpose: a summarised observation cannot be re-checked.
    observed: dict[str, Any] = Field(default_factory=dict)
    #: A short human-readable rendering of ``observed``, for the proposal. This
    #: is a convenience, never the record of truth.
    summary: str = ""
    observed_at: datetime = Field(default_factory=_now)
    #: Which detector produced this, so a bad detector can be traced from a bad
    #: claim rather than guessed at.
    detector: str = "unknown"

    @field_validator("source")
    @classmethod
    def _source_is_real(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("evidence must name what was inspected")
        return value.strip()

    @property
    def fingerprint(self) -> str:
        return _digest(self.kind, self.source, sorted(self.observed.items()), self.detector)


# ---------------------------------------------------------------------------
# Source layer — facts about the world.
#
# Business is the permanent customer record. Nothing here knows about channels,
# proposals or sends.
#
# Nothing below this heading until the OFFER heading may reference a proposal, a
# channel, a message or a send.
# ---------------------------------------------------------------------------


class Business(BaseModel):
    """The permanent record of a company. **One per company, forever.**

    This is deliberately not called a Prospect. "Prospect" is a role a company
    plays inside a sales pipeline, and naming the entity after one role is how
    every factory ends up with its own copy of the same customer — a Prospect
    here, a Client in the website factory, a Seller in the Amazon factory, three
    rows for one company and no way to tell they are the same.

    So a Business knows who it is and how to reach it, and nothing about what is
    being done with it. Opportunities reference it. Websites, listings, media,
    projects, deployments and support history will reference it the same way,
    each owning its own state and none duplicating this record.

    ``niche`` is deliberately absent. A company is not "a dental clinic in the
    example-uae-services niche" — it is a company, which may be qualified under
    several niches over time. The niche belongs on the Opportunity, which is the
    thing that has a niche.

    **The id is immutable.** Every factory that ever touches this company —
    website, listings, media, SaaS, support, billing — references this id, and
    the timeline in ``BusinessEvent`` is keyed on it. An id that can change is a
    history that can be orphaned: events written yesterday would point at
    nothing, and no amount of care downstream recovers that. The model is frozen
    so it cannot be reassigned, and ``merged_with`` checks explicitly rather
    than trusting itself, because ``model_copy`` does not validate.
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=_new_id)
    name: str
    geography: str = ""
    website: str | None = None
    email: str | None = None
    phone: str | None = None
    #: Stable keys used to recognise this company again. See ``identity.py``.
    identity_keys: list[str] = Field(default_factory=list)
    #: Every source that has reported this company, in the order first seen.
    #: A list rather than a field, because the second source to find a business
    #: is evidence about it and overwriting would throw that away.
    sources: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    first_seen_at: datetime = Field(default_factory=_now)
    last_seen_at: datetime = Field(default_factory=_now)

    @field_validator("name")
    @classmethod
    def _named(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("a business must have a name")
        return value.strip()

    def merged_with(self, other: Business) -> Business:
        """Fold a fresh sighting into the stored record.

        Existing values win. A later source correcting an earlier one is
        possible but rarer than a later source being sloppier, and silently
        overwriting a good phone number with a worse one is not recoverable.
        Genuinely new facts are filled in, and every source is remembered.
        """
        merged = self.model_copy(
            update={
                "website": self.website or other.website,
                "email": self.email or other.email,
                "phone": self.phone or other.phone,
                "geography": self.geography or other.geography,
                "identity_keys": sorted(set(self.identity_keys) | set(other.identity_keys)),
                "sources": self.sources + [s for s in other.sources if s not in self.sources],
                "metadata": {**other.metadata, **self.metadata},
                "last_seen_at": _now(),
            }
        )
        if merged.id != self.id:  # pragma: no cover - defensive
            raise ValueError(
                "a merge may not change a business id; every factory and every "
                "timeline entry references it"
            )
        return merged


class FindingKind(StrEnum):
    """Classes of defect. Additive — a new detector adds a member here."""

    NO_WEBSITE = "no_website"
    SITE_UNREACHABLE = "site_unreachable"
    NO_HTTPS = "no_https"
    TLS_INVALID = "tls_invalid"
    NOT_MOBILE_FRIENDLY = "not_mobile_friendly"
    SLOW_RESPONSE = "slow_response"
    MISSING_TITLE = "missing_title"
    MISSING_META_DESCRIPTION = "missing_meta_description"
    MISSING_H1 = "missing_h1"
    NO_STRUCTURED_DATA = "no_structured_data"
    THIN_CONTENT = "thin_content"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


#: How much each severity contributes to an opportunity score. Data rather than
#: branching, so tuning is an edit and not a code change.
SEVERITY_WEIGHT: dict[Severity, float] = {
    Severity.LOW: 1.0,
    Severity.MEDIUM: 2.5,
    Severity.HIGH: 5.0,
}


class Finding(BaseModel):
    """One evidenced defect.

    **Invariant 1 lives here.** ``evidence`` is required and must be non-empty.
    Pydantic enforces it at construction, so there is no path -- including
    ``model_construct`` misuse in a hurry -- that yields a claim Atlas cannot
    substantiate.
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=_new_id)
    business_id: str
    kind: FindingKind
    severity: Severity
    #: One sentence, stated as fact, in language the business owner would use.
    #: Not marketing copy -- this ends up quoted in a proposal.
    statement: str
    evidence: list[Evidence]
    #: How much this particular observation should be trusted, 0-1.
    #:
    #: Not all detectors are equally reliable and not all observations are
    #: equally direct. Reading a missing ``<title>`` out of the markup is nearly
    #: certain; calling a site slow from one timing sample is a guess with a
    #: network in the way. Scoring multiplies severity by this, so a weak signal
    #: cannot push a business over the qualification bar on its own.
    #:
    #: The number must be *justified* by how the observation was made — see the
    #: named constants in ``detectors/website.py``. A confidence a detector
    #: invents is worse than no confidence at all, because it looks like rigour.
    confidence: float = 1.0
    detected_at: datetime = Field(default_factory=_now)

    @field_validator("evidence")
    @classmethod
    def _must_be_evidenced(cls, value: list[Evidence]) -> list[Evidence]:
        if not value:
            raise ValueError(
                "a finding must carry evidence — Atlas does not make claims it cannot show"
            )
        return value

    @field_validator("statement")
    @classmethod
    def _must_say_something(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("a finding must state what is wrong")
        return value.strip()

    @field_validator("confidence")
    @classmethod
    def _within_range(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"confidence must be between 0 and 1, got {value}")
        return value

    @property
    def weight(self) -> float:
        """Severity discounted by how sure we are.

        A high-severity guess and a low-severity certainty should not score the
        same, and multiplying is the least surprising way to say so.
        """
        return round(SEVERITY_WEIGHT[self.severity] * self.confidence, 4)

    @property
    def fingerprint(self) -> str:
        return _digest(
            self.kind,
            self.severity,
            self.statement,
            self.confidence,
            *(item.fingerprint for item in self.evidence),
        )


class OpportunityStage(StrEnum):
    """The funnel. Ordered, and the order is meaningful — see ``metrics.py``."""

    DISCOVERED = "discovered"
    QUALIFIED = "qualified"
    PROPOSED = "proposed"
    APPROVED = "approved"
    SENT = "sent"
    REPLIED = "replied"
    MEETING = "meeting"
    WON = "won"
    LOST = "lost"
    DISQUALIFIED = "disqualified"


#: Stages that end the pipeline for a business.
TERMINAL_STAGES: frozenset[OpportunityStage] = frozenset(
    {OpportunityStage.WON, OpportunityStage.LOST, OpportunityStage.DISQUALIFIED}
)


class Opportunity(BaseModel):
    """A scored bundle of findings that constitutes something sellable."""

    id: str = Field(default_factory=_new_id)
    business_id: str
    niche: str
    findings: list[Finding] = Field(default_factory=list)
    stage: OpportunityStage = OpportunityStage.DISCOVERED
    #: Sum of finding weights. Comparable within a niche, not across niches.
    score: float = 0.0
    #: What the work is assumed to be worth. An assumption, labelled as one.
    estimated_value: float | None = None
    currency: str = "AED"
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    @property
    def is_qualified(self) -> bool:
        return bool(self.findings)

    @property
    def findings_fingerprint(self) -> str:
        """Changes whenever the underlying facts change.

        The proposal fingerprint incorporates this, so a re-detection that
        changes what is true invalidates an approval that was granted on the old
        facts. That is the whole safety property.
        """
        return _digest(*sorted(finding.fingerprint for finding in self.findings))


# ---------------------------------------------------------------------------
# Offer layer — what we say to them. Still channel-agnostic.
# ---------------------------------------------------------------------------


class ProposalClaim(BaseModel):
    """One assertion in a proposal, tied to the finding that justifies it."""

    model_config = ConfigDict(frozen=True)

    finding_id: str
    #: What the reader is told.
    text: str
    #: What Atlas proposes doing about it.
    remedy: str = ""

    @field_validator("text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("a claim must say something")
        return value.strip()


class Proposal(BaseModel):
    """A proposal generated from findings.

    **Invariant 2 lives here.** A proposal must cite at least one claim, and
    every claim must reference a finding that is actually attached. A template
    with the business name substituted in cannot satisfy that, which is the
    point: the check is structural, so it holds regardless of which model wrote
    the prose.
    """

    id: str = Field(default_factory=_new_id)
    business_id: str
    opportunity_id: str
    subject: str
    body: str
    claims: list[ProposalClaim]
    #: The offer being made, from the niche profile.
    offer: str = ""
    price: float | None = None
    currency: str = "AED"
    #: Fingerprint of the facts this was generated from, captured at generation.
    findings_fingerprint: str = ""
    generated_at: datetime = Field(default_factory=_now)
    #: Which model or template produced the prose, for provenance.
    generator: str = "unknown"

    @field_validator("claims")
    @classmethod
    def _must_cite(cls, value: list[ProposalClaim]) -> list[ProposalClaim]:
        if not value:
            raise ValueError(
                "a proposal must be built from findings — generic templates are not permitted"
            )
        return value

    @model_validator(mode="after")
    def _body_is_not_empty(self) -> Proposal:
        if not self.subject.strip() or not self.body.strip():
            raise ValueError("a proposal needs a subject and a body")
        return self

    @property
    def fingerprint(self) -> str:
        """What an approval binds to.

        Covers the words that will be sent **and** the facts they rest on. Edit
        the body or re-run a detector and this moves, which voids the approval
        rather than silently sending something a human never read.
        """
        return _digest(
            self.subject,
            self.body,
            self.offer,
            self.price,
            self.findings_fingerprint,
            *sorted(f"{claim.finding_id}:{claim.text}:{claim.remedy}" for claim in self.claims),
        )


# ---------------------------------------------------------------------------
# Delivery layer
# ---------------------------------------------------------------------------


class OutreachStatus(StrEnum):
    DRAFT = "draft"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    SENT = "sent"
    FAILED = "failed"
    SUPPRESSED = "suppressed"


class OutreachMessage(BaseModel):
    """A proposal rendered for one channel, and the record of what happened.

    Carries ``approved_fingerprint`` rather than a boolean. A flag would say
    "someone approved this message"; the fingerprint says "someone approved
    *these exact words resting on these exact facts*", which is the only version
    of the claim that survives an edit.
    """

    id: str = Field(default_factory=_new_id)
    proposal_id: str
    business_id: str
    channel: str
    recipient: str
    subject: str
    body: str
    status: OutreachStatus = OutreachStatus.DRAFT
    approval_id: str | None = None
    #: The proposal fingerprint at the moment of approval. Re-checked at send.
    approved_fingerprint: str | None = None
    created_at: datetime = Field(default_factory=_now)
    sent_at: datetime | None = None
    #: Why a send failed or was suppressed. Never silently empty on failure.
    detail: str | None = None
    provider_message_id: str | None = None


#: The Opportunity Factory's own name on the timeline. Each factory owns a
#: namespace, so Website can record "deployed" and Amazon "listing_updated"
#: without either of them appearing in the enum below or touching this module.
OPPORTUNITY_FACTORY = "opportunity"


class PipelineEventKind(StrEnum):
    """Things that happen to an opportunity, and the measurement substrate.

    Deliberately **not** the full vocabulary of the timeline. Other factories
    have their own kinds and must not have to add members here — a closed enum
    covering every factory would make this module a dependency of all of them,
    which is the coupling ``BusinessEvent.factory`` exists to avoid.
    """

    DISCOVERED = "discovered"
    QUALIFIED = "qualified"
    DISQUALIFIED = "disqualified"
    PROPOSAL_GENERATED = "proposal_generated"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    SENT = "sent"
    SEND_FAILED = "send_failed"
    SUPPRESSED = "suppressed"
    REPLIED = "replied"
    MEETING_BOOKED = "meeting_booked"
    WON = "won"
    LOST = "lost"


class BusinessEvent(BaseModel):
    """One thing that happened to a company. Append-only, and shared.

    **This is Atlas's permanent memory of a business**, not the Opportunity
    Factory's log that other factories may borrow. Every factory writes here:
    outreach today; a website deployed, a listing updated, a video published, a
    support ticket answered, later. One company, one chronological history,
    whichever part of Atlas caused the entry.

    That is why ``kind`` is a plain string rather than a closed enum. Each
    factory owns its namespace under its own ``factory`` label and adds kinds
    without editing this module — an enum spanning every factory would make the
    opportunity package a dependency of all of them, and the first factory to
    need a new kind would have to change code it does not own.

    Append-only is the other half. Metrics are derived from these rather than
    from mutable stage fields, because a funnel computed from current state
    cannot tell you that forty businesses reached "sent" and came back to
    nothing — and a memory you can overwrite is not a memory.
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=_new_id)
    #: The business this happened to. Required — this is what makes the timeline
    #: one history per company rather than one per pipeline.
    business_id: str
    #: Which part of Atlas caused it. Namespaces ``kind`` and lets a reader ask
    #: for the whole history or one factory's slice of it.
    factory: str = OPPORTUNITY_FACTORY
    #: What happened, within that factory's vocabulary.
    kind: str
    #: The opportunity it happened under, when there is one. Optional because a
    #: company is discovered before it has an opportunity, and because a
    #: deployment or a support ticket is not an opportunity at all.
    opportunity_id: str | None = None
    at: datetime = Field(default_factory=_now)
    actor: str = "system"
    detail: dict[str, Any] = Field(default_factory=dict)

    @field_validator("kind")
    @classmethod
    def _kind_is_named(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("an event must say what happened")
        return value.strip()


#: Kept so existing call sites and imports keep working. The name that describes
#: what this is now is ``BusinessEvent``.
PipelineEvent = BusinessEvent


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class NicheProfile(BaseModel):
    """One niche, one geography, expressed as data.

    Changing target market is editing one of these. Nothing branches on niche
    anywhere in the package — if something ever needs to, it belongs here as a
    field instead.
    """

    id: str
    name: str
    geography: str
    #: What is being sold to this niche.
    offer: str
    #: Assumed engagement value. An assumption, and labelled as one everywhere
    #: it surfaces.
    estimated_value: float | None = None
    currency: str = "AED"
    #: Findings below this total score are not worth contacting anyone about.
    qualify_threshold: float = 5.0
    #: Findings this niche does not care about, even if detected.
    ignore_kinds: list[FindingKind] = Field(default_factory=list)
    #: Findings below this confidence are dropped before scoring. A weak signal
    #: should not reach a business owner as a stated fact, however many of them
    #: pile up.
    min_confidence: float = 0.5
    #: Days before the same business may be contacted again.
    contact_cooldown_days: int = 90
    notes: str = ""
