"""Is this message about this prospect, and only this prospect?

Every field in a draft can be individually correct while the finished message is
wrong. That is not hypothetical: a staffing agency's draft carried its real
name, its real number and its real confirmed weakness, and then offered the
real-estate sample described as "a property company". Nothing was fabricated and
nothing was another business's — the message was simply about two different
companies at once, because the demo and the wording came from tables that were
keyed on the same thing and had drifted apart.

Checking each field against its own source cannot catch that. Checking the
finished text against the rest of the pipeline can, which is what this does.

Used by both the generator that writes drafts and the dashboard that displays
them, so a draft cannot pass on the way in and fail on the way out.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import demos, identity, offer

#: How a feature reads in prose, for spotting it in a finished sentence.
_SPOKEN = {
    "booking_link": ("online booking", "appointment booking", "book online"),
    "insurance_info": ("insurance",),
    "emergency_info": ("emergency",),
    "doctors_team": ("doctor profiles", "team profiles"),
    "social_proof": ("reviews", "testimonial"),
    "arabic": ("arabic",),
    "whatsapp": ("whatsapp",),
    "opening_hours": ("opening hours",),
    "google_maps": ("map link",),
    "https": ("not secure", "https"),
    "contact_form": ("enquiry form", "contact form"),
}


@dataclass(frozen=True)
class Other:
    """Another prospect, reduced to the things that must never leak."""

    business_id: str
    name: str
    phone: str
    host: str
    demo_url: str


def _mentions(text: str, needles: tuple[str, ...]) -> str:
    lowered = text.lower()
    for needle in needles:
        if needle and needle in lowered:
            return needle
    return ""


def check(
    text: str,
    *,
    business_id: str,
    speakable: tuple[str, ...],
    unfixable: tuple[str, ...],
    unverified: tuple[str, ...],
    chosen: demos.Selection,
    category: str,
    others: tuple[Other, ...] = (),
) -> list[str]:
    """Every reason this draft is not safe to copy. Empty means ready."""
    problems: list[str] = []
    lowered = text.lower()

    # --- who is writing -------------------------------------------------
    problems += [f"presents Qevik as its own company: {c!r}" for c in identity.entity_claims(text)]

    # --- what may not be claimed ----------------------------------------
    for feature in unfixable:
        hit = _mentions(text, _SPOKEN.get(feature, (feature.replace("_", " "),)))
        if hit:
            problems.append(f"raises {feature}, which Qevik does not build ({hit!r})")
    for feature in unverified:
        hit = _mentions(text, _SPOKEN.get(feature, (feature.replace("_", " "),)))
        if hit:
            problems.append(f"mentions {feature}, which is NOT_VERIFIED ({hit!r})")
    if "book" in lowered and "placeholder" not in lowered:
        problems.append("mentions booking without the placeholder disclaimer")
    for token in (str(offer.SETUP_AED), str(offer.MONTHLY_AED), "aed"):
        if token in lowered:
            problems.append(f"names a price ({token}) in a first message")

    # --- the demo must be the demo --------------------------------------
    if chosen.url and chosen.url not in text:
        problems.append(f"does not carry the selected demo URL {chosen.url}")
    for demo in demos.DEMOS:
        if chosen.demo is not None and demo.slug == chosen.demo.slug:
            continue
        if f"/{demo.slug}/" in text:
            problems.append(f"links {demo.slug}, which is not the selected demo")
        # Substring, not phrase: "restaurant site" sits inside "bilingual
        # restaurant site", so a correct draft for the bilingual sample was
        # refused for describing itself as the other one. Only a trade that is
        # not part of the chosen trade can be a genuine mismatch.
        if (chosen.demo is not None
                and demo.trade != chosen.demo.trade
                and demo.trade.lower() not in chosen.demo.trade.lower()
                and demo.trade.lower() in lowered):
            problems.append(f"describes the demo as {demos.article(demo.trade)} {demo.trade}")
    if chosen.demo is not None and category and category not in chosen.demo.serves:
        problems.append(f"offers the {chosen.demo.name} sample to a {category} business, "
                        f"which it does not serve")
    if chosen.kind == "sample" and "built you" in lowered:
        problems.append("implies a Qevik sample was built for this prospect")
    # The demo's honesty class, not the sentence's confidence, decides which
    # verbs are available. "We built your new site" is true of exactly one
    # class, and it is the one a customer has to have asked for.
    for phrase in demos.overclaims(text, chosen.demo):
        problems.append(f"says {phrase!r} about a {chosen.demo.classification} demo")
    if not chosen.url and "sites.qevik.ai" in lowered:
        problems.append("links a demo when none was selected as relevant")

    # --- and it must be about one business ------------------------------
    for other in others:
        if other.business_id == business_id:
            continue
        for value, label in ((other.name, "name"), (other.phone, "phone number"),
                             (other.host, "website"), (other.demo_url, "demo URL")):
            # Short values produce false positives — a two-word trading name can
            # legitimately appear inside another. Six characters is enough to be
            # identifying without flagging "Auto" or "Dubai".
            if value and len(value) > 6 and value.lower() in lowered:
                problems.append(f"contains another prospect's {label}: {value!r}")
    return problems
