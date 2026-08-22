"""What Qevik sells around a capability it already has.

`CapabilitySpec` in `models.py` is the capability registry and stays that way —
it says what the system can execute and which providers can do it. An offer is
the commercial half: who it is for, what it costs, what the customer must
connect, what approval it needs, what QA it must pass and what would later be
measured.

Keeping them apart is deliberate. A capability is a technical fact and changes
when the providers change; an offer is a commercial decision and changes when
pricing or plans change. Merging them would put a price in the execution path.

**An offer cannot name a capability that does not exist.** The constructor
checks the registry, so a plan cannot sell something the system has no way to
perform — which is the failure this whole layer exists to prevent.

Publication targets are not capabilities. One capability reaches many targets;
modelling `amazon.listing.create` as its own capability would give every
marketplace a private copy of approval, credential and QA logic, and they would
drift.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from ..models import CapabilitySpec
from ..registry import Registry
from .models import Unsupported


class Availability(StrEnum):
    AVAILABLE = "available"
    #: The capability exists; the customer has not connected the account it
    #: needs. Still recommendable — that is how Qevik offers marketplace work
    #: honestly before marketplace access exists.
    REQUIRES_CONNECTION = "requires_connection"
    REQUIRES_APPROVAL = "requires_approval"
    #: Not built yet. May be shown, may never be offered.
    UNAVAILABLE = "unavailable"


class CapabilityOffer(BaseModel):
    """One capability, offered commercially."""

    model_config = ConfigDict(frozen=True)

    id: str
    #: Must exist in the Registry. Validated, never assumed.
    capability_id: str
    name: str
    summary: str
    version: str = "1.0.0"

    availability: Availability = Availability.AVAILABLE
    #: Business models this suits, from research.classify. Empty means any.
    business_models: frozenset[str] = frozenset()
    #: Opportunity keys this offer answers, from outreach.opportunity.
    answers: frozenset[str] = frozenset()

    required_inputs: tuple[str, ...] = ()
    required_connections: tuple[str, ...] = ()
    requires_approval: bool = True
    #: Declared, not computed during execution — pricing must not live in the
    #: execution path. Charging belongs to the later credits phase.
    estimated_units: int = 0
    plans: frozenset[str] = frozenset({"PRO", "ADVANCED", "ENTERPRISE"})

    outputs: tuple[str, ...] = ()
    qa_layers: tuple[str, ...] = ()
    publication_target: str = ""
    measurement: tuple[str, ...] = ()

    def validate_against(self, registry: Registry) -> CapabilitySpec:
        """Refuse to be an offer for a capability the system does not have."""
        spec = registry.get_capability(self.capability_id)
        if spec is None:
            raise Unsupported(
                f"{self.id}: no capability {self.capability_id!r} is registered. An "
                "offer cannot sell something the system has no way to execute."
            )
        return spec

    def eligible(self, *, business_model: str = "", plan: str = "") -> bool:
        if self.business_models and business_model and business_model not in self.business_models:
            return False
        if plan and plan not in self.plans:
            return False
        return self.availability is not Availability.UNAVAILABLE


#: The catalogue. Every entry names a capability registered by the composition
#: root, so this is a view over that registry rather than a second one.
OFFERS: tuple[CapabilityOffer, ...] = (
    CapabilityOffer(
        id="offer-portfolio-system",
        capability_id="cap-code-generation",
        name="Portfolio and case-study system",
        summary="Turn work the business already publishes into a filterable index, "
                "with the facts it publishes shown and the ones it does not marked "
                "as unpublished.",
        answers=frozenset({"proof", "buried_work"}),
        business_models=frozenset({"CATERING", "B2B_SERVICE", "PROFESSIONAL_SERVICE",
                                   "LOGISTICS", "REAL_ESTATE"}),
        required_inputs=("the pages already published",),
        outputs=("a filterable index", "one page per case"),
        qa_layers=("schema", "content", "browser", "link", "accessibility", "seo"),
        publication_target="website",
        measurement=("portfolio page views", "enquiries citing a case"),
        estimated_units=40,
    ),
    CapabilityOffer(
        id="offer-arabic-experience",
        capability_id="cap-reasoning",
        name="Arabic experience",
        summary="An authored Arabic version with RTL layout and reciprocal hreflang — "
                "not a machine translation of the English.",
        answers=frozenset({"arabic"}),
        required_inputs=("the pages to translate",),
        outputs=("an Arabic route per page", "hreflang pairs"),
        qa_layers=("content", "browser", "seo", "accessibility"),
        publication_target="website",
        measurement=("Arabic page views", "enquiries in Arabic"),
        estimated_units=30,
    ),
    CapabilityOffer(
        id="offer-editorial",
        capability_id="cap-reasoning",
        name="Editorial hub",
        summary="A small editorial section on the subjects the business already "
                "writes about, with real structure and a route into the enquiry.",
        answers=frozenset({"editorial", "blog_revival", "unillustrated"}),
        required_inputs=("existing articles", "subjects the business cares about"),
        outputs=("articles", "an index", "internal links"),
        qa_layers=("content", "brand", "seo", "link"),
        publication_target="website",
        measurement=("article views", "time on page", "enquiries from an article"),
        estimated_units=25,
    ),
    CapabilityOffer(
        id="offer-imagery",
        capability_id="cap-image-generation",
        name="Supporting imagery",
        summary="Images generated to support content the customer has approved, "
                "never presented as photographs of their work.",
        answers=frozenset({"unillustrated"}),
        required_connections=("media permission",),
        required_inputs=("brand direction", "media permission"),
        outputs=("images with recorded provenance",),
        qa_layers=("brand", "visual", "rights"),
        publication_target="website",
        measurement=("engagement on illustrated pages",),
        estimated_units=1,
    ),
    CapabilityOffer(
        id="offer-one-tap-contact",
        capability_id="cap-code-generation",
        name="One-tap contact",
        summary="Tappable phone, WhatsApp and email on every page, plus a persistent "
                "affordance that does not cover the primary controls.",
        answers=frozenset({"reachability", "whatsapp"}),
        required_inputs=("the contact details the business publishes",),
        outputs=("contact links on every route",),
        qa_layers=("browser", "link", "accessibility"),
        publication_target="website",
        measurement=("taps to call", "WhatsApp conversations started"),
        estimated_units=10,
    ),
    CapabilityOffer(
        id="offer-website",
        capability_id="cap-code-generation",
        name="Website",
        summary="A site built from the facts the business has supplied or published, "
                "with nothing on it that nobody stands behind. Creates one where "
                "there is none, and rebuilds the structure where there is.",
        # The three website opportunities nothing else answered. A site that is
        # slow, broken or empty is one artefact's problem, not three.
        answers=frozenset({"performance", "broken", "thin_content"}),
        required_inputs=("the business name, and any contact details to publish",),
        # Only what every build carries. The QA gate checks each declared
        # output is actually in the artefact, so declaring a contact section
        # would fail for a business that has recorded no contact details — and
        # the honest response to that is a shorter declaration, not a weaker
        # gate. What the site contains beyond this depends on what was supplied,
        # which is the whole point of `website/content.py`.
        outputs=("a page with a title",),
        qa_layers=("browser", "content", "link", "accessibility", "seo"),
        publication_target="website",
        measurement=("sessions", "enquiries"),
        estimated_units=30,
    ),
    CapabilityOffer(
        id="offer-enquiry-builder",
        capability_id="cap-code-generation",
        name="Structured enquiry",
        summary="A short qualification flow that produces a quotable brief instead "
                "of a free-text message.",
        answers=frozenset({"enquiry"}),
        business_models=frozenset({"CATERING", "B2B_SERVICE", "LOGISTICS",
                                   "PROFESSIONAL_SERVICE", "REAL_ESTATE"}),
        required_inputs=("the questions the business needs answered to quote",),
        outputs=("an enquiry flow", "a structured brief"),
        qa_layers=("browser", "content", "accessibility"),
        publication_target="website",
        measurement=("enquiries completed", "enquiries that could be quoted"),
        estimated_units=20,
    ),
)

BY_ID: dict[str, CapabilityOffer] = {o.id: o for o in OFFERS}


def offer_for(offer_id: str) -> CapabilityOffer | None:
    return BY_ID.get(offer_id)


def offers_for_opportunity(key: str, *, business_model: str = "",
                           plan: str = "") -> tuple[CapabilityOffer, ...]:
    """Offers that answer this opportunity and suit this business.

    Empty is a legitimate answer: an opportunity Qevik cannot act on is still
    worth telling a customer about, and pretending otherwise is how a platform
    starts recommending whatever it happens to have built.
    """
    return tuple(o for o in OFFERS if key in o.answers
                 and o.eligible(business_model=business_model, plan=plan))
