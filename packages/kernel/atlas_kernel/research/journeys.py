"""The customer's actual path, tested step by step for the business it is.

"UX could be improved" is not a finding, it is a shrug. This names the step —
*a visitor who has decided to enquire cannot find a phone number they can tap* —
and that sentence is worth sending because it is specific, checkable and about
them.

The other half is restraint. A caterer has no cart and needs none; a clinic has
no quote builder. Every journey below is a list of steps **for that model
only**, and a step absent from a model is never reported. Criticising a business
for lacking something its trade does not use is the fastest way to prove nobody
looked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..opportunity.website_audit import Category, Finding, Status

_TAG = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class Step:
    """One thing the customer has to be able to do."""

    name: str
    #: Regexes, any of which satisfies the step. Matched against raw HTML so
    #: hrefs count — a tel: link is the evidence for "call", not the word "call".
    signals: tuple[str, ...]
    #: What the visitor is trying to do. Used verbatim in the finding.
    intent: str
    #: A step the model cannot work without. Optional steps are reported as
    #: opportunities, never as defects.
    required: bool = True


CALL = Step("call", (r'href=["\']tel:',), "phone the business")
WHATSAPP = Step("whatsapp", (r'wa\.me/', r'api\.whatsapp\.com'), "message on WhatsApp",
                required=False)
EMAIL = Step("email", (r'href=["\']mailto:',), "email the business")
ENQUIRY = Step("enquiry", (r"<form", r"contact-form", r"wpcf7"), "send an enquiry")
LOCATION = Step("location", (r"google\.com/maps", r"maps\.app\.goo\.gl", r"<iframe[^>]*maps"),
                "find or route to the address", required=False)
HOURS = Step("hours", (r"opening hours", r"\bmon(day)?\s*[-–]\s*", r"\bsat(urday)?\b.*\d"),
             "know when it is open", required=False)

#: One list per business model. Steps are in the order a customer meets them.
JOURNEYS: dict[str, tuple[Step, ...]] = {
    "CATERING": (
        Step("services", (r"catering", r"our services"), "see what is offered"),
        Step("proof", (r"portfolio", r"our work", r"case stud", r"gallery", r"previous events"),
             "see comparable events already delivered"),
        Step("requirements", (r"guests", r"number of people", r"event date", r"occasion"),
             "state the event's shape"),
        ENQUIRY, CALL, WHATSAPP, EMAIL,
    ),
    "RESTAURANT": (
        Step("menu", (r"\bmenu\b", r"starters", r"mains"), "read the menu"),
        Step("reserve", (r"reserv", r"book a table", r"opentable", r"quandoo"),
             "reserve a table"),
        LOCATION, HOURS, CALL, WHATSAPP,
    ),
    "CAFE": (
        Step("menu", (r"\bmenu\b", r"coffee", r"espresso"), "see what is served"),
        LOCATION, HOURS, Step("order", (r"deliveroo", r"talabat", r"order online"),
                              "order for delivery", required=False),
        CALL,
    ),
    "ECOMMERCE": (
        Step("browse", (r"category", r"shop", r"collection"), "browse the range"),
        Step("product", (r"add to cart", r"add to basket"), "choose a product"),
        Step("cart", (r"/cart", r"shopping-cart"), "review the basket"),
        Step("checkout", (r"/checkout", r"secure checkout"), "pay"),
        Step("returns", (r"returns", r"refund policy"), "know the returns policy",
             required=False),
        CALL, EMAIL,
    ),
    "CLINIC": (
        Step("services", (r"treatment", r"our services"), "find the treatment"),
        Step("clinicians", (r"our team", r"our doctors", r"meet the"), "see who will treat them",
             required=False),
        Step("book", (r"book (an )?appointment", r"request an appointment", r"<form"),
             "book an appointment"),
        LOCATION, HOURS, CALL, WHATSAPP,
    ),
    "BEAUTY": (
        Step("services", (r"treatment", r"services", r"price list"), "find the treatment"),
        Step("book", (r"book", r"<form"), "book"),
        LOCATION, HOURS, CALL, WHATSAPP,
    ),
    "RECRUITMENT": (
        Step("audience", (r"employers", r"candidates", r"job seekers"),
             "identify as employer or candidate"),
        Step("search", (r"search", r"vacanc", r"browse jobs"), "search roles or candidates"),
        Step("filter", (r"filter", r"refine", r"sort by"), "narrow the list", required=False),
        Step("apply", (r"apply", r"submit (your )?cv", r"<form"), "apply or enquire"),
        CALL, EMAIL,
    ),
    "LOGISTICS": (
        Step("services", (r"freight", r"air|sea|road freight", r"customs"),
             "find the right service"),
        Step("quote", (r"request a quote", r"get a quote", r"rfq", r"<form"), "get a quote"),
        Step("tracking", (r"track", r"tracking"), "track a shipment", required=False),
        CALL, EMAIL,
    ),
    "REAL_ESTATE": (
        Step("listings", (r"properties", r"listings", r"for sale", r"for rent"),
             "browse properties"),
        Step("filter", (r"bedrooms", r"price range", r"filter"), "narrow by requirement"),
        Step("enquire", (r"<form", r"register interest"), "enquire on a property"),
        CALL, WHATSAPP,
    ),
    "B2B_SERVICE": (
        Step("capability", (r"our services", r"capabilit", r"what we do"),
             "understand the capability"),
        Step("proof", (r"case stud", r"our clients", r"portfolio", r"projects"),
             "see proof it has been done before"),
        Step("qualify", (r"rfq", r"request a quote", r"<form"), "start a conversation"),
        CALL, EMAIL,
    ),
    "PROFESSIONAL_SERVICE": (
        Step("services", (r"our services", r"what we do"), "understand the service"),
        Step("credibility", (r"about", r"our team", r"case stud"), "judge credibility"),
        ENQUIRY, CALL, EMAIL,
    ),
}

#: When the model is unknown, only the steps every business shares are tested.
DEFAULT = (Step("services", (r"services", r"what we do", r"products"),
                "understand what is sold"), ENQUIRY, CALL, EMAIL)


@dataclass(frozen=True)
class StepResult:
    step: str
    intent: str
    satisfied: bool
    required: bool
    evidence: str


def walk(model: str, pages_html: list[str]) -> tuple[dict, list[Finding]]:
    """Test the journey for this model against everything crawled."""
    steps = JOURNEYS.get(model, DEFAULT)
    if not pages_html:
        return ({"model": model, "tested": 0}, [Finding(
            feature="journey", category=Category.CONVERSION, status=Status.UNVERIFIED,
            evidence="no pages were retrieved, so the journey was not walked")])

    combined = "\n".join(pages_html)
    results: list[StepResult] = []
    for step in steps:
        hit = next((s for s in step.signals if re.search(s, combined, re.I)), "")
        results.append(StepResult(step.name, step.intent, bool(hit), step.required,
                                  f"matched {hit!r}" if hit else "nothing on the site matches"))

    findings: list[Finding] = []
    for result in results:
        # An optional step that is missing is an opportunity, not a fault, and
        # is recorded as unverified-for-blame rather than as a weakness.
        findings.append(Finding(
            feature=f"journey_{result.step}",
            category=Category.CONVERSION,
            status=Status.PRESENT if result.satisfied
            else (Status.NOT_FOUND if result.required else Status.UNVERIFIED),
            evidence=f"{model}: a visitor trying to {result.intent} — {result.evidence}"))

    # Two journey steps carry names the opportunity engine already reasons
    # about. Emitting them under those names lets a crawl-wide result feed rules
    # written before this engine existed.
    ALIAS = {"call": "click_to_call", "whatsapp": "whatsapp"}
    for result in results:
        alias = ALIAS.get(result.step)
        if not alias:
            continue
        findings.append(Finding(
            feature=alias, category=Category.CONTACT,
            status=Status.PRESENT if result.satisfied
            else (Status.NOT_FOUND if result.required else Status.UNVERIFIED),
            evidence=f"across the whole site: {result.evidence}"))

    broken = [r for r in results if not r.satisfied and r.required]
    findings.append(Finding(
        feature="journey", category=Category.CONVERSION,
        status=Status.PRESENT if not broken else Status.NOT_FOUND,
        evidence=f"{model} journey: {len(results) - len(broken)} of {len(results)} steps work"
                 + (f"; first break is '{broken[0].step}' — cannot {broken[0].intent}"
                    if broken else "")))

    facts = {
        "model": model, "tested": len(results),
        "steps": [{"step": r.step, "satisfied": r.satisfied, "required": r.required,
                   "intent": r.intent} for r in results],
        "first_break": broken[0].step if broken else "",
        "broken_required": [r.step for r in broken],
    }
    return facts, findings
