"""What kind of business this is, from what the site says rather than its name.

"Al Noor Trading" could be anything. The signal is in what the site sells, so
classification reads navigation, headings and content — and returns
`NOT_VERIFIED` rather than a guess when nothing is decisive.

It matters because the journey model downstream is chosen from this. Classify a
caterer as a restaurant and the engine starts asking why there is no menu with
prices, which is a criticism of something the business deliberately does not do.
"""

from __future__ import annotations

import re
from collections import Counter

_TAG = re.compile(r"<[^>]+>")

#: Words that only appear when a business does a particular thing. Deliberately
#: narrow: "service" and "quality" appear on every site ever made.
SIGNALS: dict[str, tuple[str, ...]] = {
    "CATERING": ("catering", "canapé", "canape", "buffet", "live station", "iftar",
                 "event catering", "guests", "per person"),
    "RESTAURANT": ("reservation", "book a table", "our menu", "starters", "mains",
                   "dine-in", "à la carte", "opening hours"),
    "CAFE": ("coffee", "espresso", "roastery", "barista", "brunch menu", "beans"),
    "ECOMMERCE": ("add to cart", "shopping cart", "checkout", "free shipping",
                  "in stock", "product code", "wishlist"),
    "CLINIC": ("appointment", "patients", "treatment", "consultation", "dentist",
               "clinic", "doctor", "insurance"),
    "BEAUTY": ("salon", "hair", "nails", "spa", "beauty treatment", "stylist"),
    "RECRUITMENT": ("candidates", "vacancies", "job seekers", "employers", "cv",
                    "staffing", "recruitment", "shortlist"),
    "LOGISTICS": ("freight", "shipment", "tracking", "customs", "warehouse",
                  "cargo", "supply chain", "container"),
    "REAL_ESTATE": ("properties", "for sale", "for rent", "bedrooms", "sq ft",
                    "listings", "off-plan"),
    "AUTOMOTIVE": ("vehicle", "car service", "garage", "mot", "tyres", "detailing",
                   "showroom"),
    "EDUCATION": ("courses", "students", "enrol", "curriculum", "tuition", "academy"),
    "HOSPITALITY": ("rooms", "suites", "check-in", "guests stay", "hotel"),
    "B2B_SERVICE": ("rfq", "request a quote", "enterprise", "our clients",
                    "case studies", "b2b", "wholesale"),
    "PROFESSIONAL_SERVICE": ("consultancy", "advisory", "audit", "legal", "accounting",
                             "compliance"),
}

#: What a category needs before it may be claimed at all.
MINIMUM_HITS = 2


def classify(pages_html: list[str], *, category_hint: str = "") -> tuple[str, float, dict]:
    """Return (model, confidence 0–1, evidence). `OTHER` when nothing is decisive."""
    text = " ".join(_TAG.sub(" ", html or "") for html in pages_html).lower()
    if not text.strip():
        return "NOT_VERIFIED", 0.0, {"reason": "no page text was available"}

    scores: Counter[str] = Counter()
    matched: dict[str, list[str]] = {}
    for model, words in SIGNALS.items():
        hits = [w for w in words if w in text]
        if len(hits) >= MINIMUM_HITS:
            scores[model] = len(hits)
            matched[model] = hits[:6]

    if not scores:
        return "OTHER", 0.0, {"reason": "no category signal appeared at least "
                                        f"{MINIMUM_HITS} times"}
    ranked = scores.most_common()
    best, best_score = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0
    # Confidence is the margin, not the raw count: a site matching two categories
    # equally has not been classified, however many words matched.
    confidence = round((best_score - runner_up) / best_score, 2) if best_score else 0.0
    return best, confidence, {"matched": matched.get(best, []),
                              "runners_up": [m for m, _ in ranked[1:3]],
                              "hint": category_hint}
