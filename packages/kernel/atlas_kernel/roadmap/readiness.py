"""Where a business stands, scored only from what was actually confirmed.

The 0→100 view, and the three rules that stop it becoming a sales instrument:

**Unverified lowers confidence, not the score.** Not having measured AI
visibility is not the same as being invisible in it. A dimension whose inputs
are mostly unverified reports LOW confidence and keeps whatever score its
confirmed evidence supports — it does not get marked down for our blind spot.

**A high score produces no priority.** AHS scores well on technical health, so
the roadmap must propose nothing there. This is "do not manufacture weaknesses"
expressed as arithmetic rather than as a warning in a document.

**Weighting is per business model.** Conversion matters more for a caterer than
content depth; the inverse for a publisher. One global weighting would rank every
business the same way and produce the same roadmap, which is the failure this
whole phase is judged against.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class Dimension(StrEnum):
    REACHABILITY = "reachability"
    CONVERSION = "conversion"
    DISCOVERABILITY = "discoverability"
    AI_VISIBILITY = "ai_visibility"
    CONTENT = "content"
    PROOF = "proof"
    TECHNICAL_HEALTH = "technical_health"
    MULTILINGUAL = "multilingual"


class Confidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


#: Which research features speak to which dimension. Only features the audit and
#: research engine genuinely emit — a dimension fed by nothing scores UNKNOWN
#: rather than zero.
SIGNALS: dict[Dimension, tuple[str, ...]] = {
    Dimension.REACHABILITY: ("click_to_call", "whatsapp", "contact_form",
                             "journey_call", "journey_email", "journey_enquiry"),
    Dimension.CONVERSION: ("journey", "journey_requirements", "journey_proof",
                           "contact_form", "opening_hours"),
    Dimension.DISCOVERABILITY: ("page_title", "meta_description", "canonical",
                                "structured_data", "sitemap", "orphan_pages",
                                "duplicate_titles", "h1", "open_graph",
                                "indexability", "image_alt_text"),
    Dimension.AI_VISIBILITY: ("ai_mention_rate", "ai_citation_rate"),
    Dimension.CONTENT: ("blog", "blog_quality", "blog_freshness", "blog_cadence",
                        "blog_media", "blog_structure", "thin_pages",
                        "content_to_service"),
    Dimension.PROOF: ("social_proof", "portfolio_depth", "social_links",
                      "market_position", "established_business"),
    Dimension.TECHNICAL_HEALTH: ("https", "page_speed", "broken_links",
                                 "broken_images", "viewport_meta", "redirect_chain",
                                 "page_weight", "robots_txt"),
    Dimension.MULTILINGUAL: ("arabic", "hreflang"),
}

#: How much each dimension matters, per business model. Only models the
#: classifier actually produces. A model with no entry uses DEFAULT.
DEFAULT_WEIGHTS: dict[Dimension, float] = {
    Dimension.REACHABILITY: 1.0, Dimension.CONVERSION: 1.0,
    Dimension.DISCOVERABILITY: 0.8, Dimension.AI_VISIBILITY: 0.6,
    Dimension.CONTENT: 0.6, Dimension.PROOF: 0.7,
    Dimension.TECHNICAL_HEALTH: 0.8, Dimension.MULTILINGUAL: 0.4,
}

WEIGHTS: dict[str, dict[Dimension, float]] = {
    # A caterer is chosen on proof and reached by phone; nobody picks one from
    # its blog cadence.
    "CATERING": {**DEFAULT_WEIGHTS, Dimension.PROOF: 1.0,
                 Dimension.REACHABILITY: 1.0, Dimension.CONVERSION: 1.0,
                 Dimension.CONTENT: 0.4, Dimension.MULTILINGUAL: 0.8},
    # A café is found locally and decided on in seconds.
    "CAFE": {**DEFAULT_WEIGHTS, Dimension.DISCOVERABILITY: 1.0,
             Dimension.REACHABILITY: 1.0, Dimension.PROOF: 0.3,
             Dimension.CONTENT: 0.3},
    "RESTAURANT": {**DEFAULT_WEIGHTS, Dimension.DISCOVERABILITY: 1.0,
                   Dimension.CONVERSION: 1.0, Dimension.PROOF: 0.4},
    # A shop lives or dies on being found and on the product page working.
    "ECOMMERCE": {**DEFAULT_WEIGHTS, Dimension.DISCOVERABILITY: 1.0,
                  Dimension.CONVERSION: 1.0, Dimension.TECHNICAL_HEALTH: 1.0,
                  Dimension.PROOF: 0.8},
    # A buyer here reads before enquiring, and checks who else you have served.
    "B2B_SERVICE": {**DEFAULT_WEIGHTS, Dimension.PROOF: 1.0,
                    Dimension.CONTENT: 0.9, Dimension.CONVERSION: 0.9,
                    Dimension.REACHABILITY: 0.7},
    "PROFESSIONAL_SERVICE": {**DEFAULT_WEIGHTS, Dimension.PROOF: 0.9,
                             Dimension.CONTENT: 0.8},
    "LOGISTICS": {**DEFAULT_WEIGHTS, Dimension.CONVERSION: 1.0,
                  Dimension.MULTILINGUAL: 0.8, Dimension.PROOF: 0.8},
    "CLINIC": {**DEFAULT_WEIGHTS, Dimension.REACHABILITY: 1.0,
               Dimension.CONVERSION: 1.0, Dimension.PROOF: 0.8},
}

#: At or above this, a dimension is working and must not generate a task.
STRONG = 75
#: Below this, a confirmed weakness worth acting on.
WEAK = 55


class DimensionScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    dimension: Dimension
    #: None when nothing confirmed was found. Not zero.
    score: int | None
    confidence: Confidence
    confirmed: int = 0
    unverified: int = 0
    weight: float = 1.0
    supporting: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()

    @property
    def strong(self) -> bool:
        return self.score is not None and self.score >= STRONG

    @property
    def weak(self) -> bool:
        return self.score is not None and self.score < WEAK

    @property
    def unmeasured(self) -> bool:
        """Nothing confirmed either way. Needs measuring, not fixing."""
        return self.score is None or self.confidence is Confidence.UNKNOWN


class Readiness(BaseModel):
    """Every dimension, and the one number that summarises them."""

    model_config = ConfigDict(frozen=True)

    business_id: str
    business_model: str = ""
    dimensions: tuple[DimensionScore, ...] = ()
    generated_at: str = ""

    @property
    def by_dimension(self) -> dict[Dimension, DimensionScore]:
        return {d.dimension: d for d in self.dimensions}

    @property
    def overall(self) -> int | None:
        """Weighted mean of what was measured. None when nothing was."""
        scored = [(d.score, d.weight) for d in self.dimensions if d.score is not None]
        if not scored:
            return None
        total = sum(weight for _, weight in scored)
        if not total:
            return None
        return round(sum(score * weight for score, weight in scored) / total)

    @property
    def unmeasured(self) -> tuple[DimensionScore, ...]:
        return tuple(d for d in self.dimensions if d.unmeasured)

    @property
    def actionable(self) -> tuple[DimensionScore, ...]:
        """Weak dimensions, worst first, weighted by what this trade needs.

        Strong dimensions are absent by construction — there is no branch that
        can add one, which is stronger than remembering not to.
        """
        weak = [d for d in self.dimensions if d.weak]
        return tuple(sorted(weak, key=lambda d: (d.score or 0) / max(d.weight, 0.01)))


def _confidence(confirmed: int, unverified: int) -> Confidence:
    if confirmed == 0:
        return Confidence.UNKNOWN
    total = confirmed + unverified
    ratio = confirmed / total if total else 0
    if ratio >= 0.8 and confirmed >= 3:
        return Confidence.HIGH
    if ratio >= 0.5:
        return Confidence.MEDIUM
    return Confidence.LOW


def assess(*, business_id: str, observations: list[dict], business_model: str = "",
           generated_at: str = "") -> Readiness:
    """Score every dimension from the research observations, and nothing else."""
    weights = WEIGHTS.get(business_model, DEFAULT_WEIGHTS)
    by_feature = {o.get("feature"): o.get("status") for o in observations}

    scores: list[DimensionScore] = []
    for dimension, features in SIGNALS.items():
        present = [f for f in features if by_feature.get(f) == "present"]
        absent = [f for f in features if by_feature.get(f) == "not_found"]
        unverified = [f for f in features if by_feature.get(f) == "unverified"]
        confirmed = len(present) + len(absent)
        score = round(100 * len(present) / confirmed) if confirmed else None
        scores.append(DimensionScore(
            dimension=dimension, score=score,
            confidence=_confidence(confirmed, len(unverified)),
            confirmed=confirmed, unverified=len(unverified),
            weight=weights.get(dimension, 1.0),
            supporting=tuple(present[:6]), missing=tuple(absent[:6])))
    return Readiness(business_id=business_id, business_model=business_model,
                     dimensions=tuple(scores), generated_at=generated_at)
