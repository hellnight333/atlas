"""Building or improving a business's website, from what was actually observed.

The generation is not written here. `website.content` and `website.generation`
already exist and already enforce the rule that matters — **no fabricated
business facts on a published site** — through a `FactSource` enum with no
`GENERATED` member and a renderer that omits what nobody supplied rather than
padding it. This module's whole job is to decide *what to build and whether to
build at all*, and then hand real facts to that machinery.

Two modes, and neither is chosen by a caller:

**CREATE** — research could not read a site. There is nothing to improve, so a
site is built from the business record.

**MODIFY** — a site exists. Only what research confirmed *absent* is added, and
what it confirmed *present* is left alone. A page that already has a tappable
phone number does not get a second one.

The refusal is the important part. If research confirms a site that already does
everything this capability could add, `build_website` raises rather than
producing a marginally different page. That is `STRONG WEBSITE + LIMITED WEBSITE
OPPORTUNITY` expressed where it cannot be argued with: there is no artefact, so
there is nothing to approve, publish or bill for.
"""

from __future__ import annotations

from enum import StrEnum

from ...opportunity.models import Business
from ...website.content import ContactDetails, Fact, FactSource, Prose, Service, SiteContent
from ...website.generation import generate

#: What a regenerated site fixes, in MODIFY mode. Deliberately short, and
#: deliberately not including the contact affordances — `offer-one-tap-contact`
#: answers those, and two offers claiming the same gap is how a customer is sold
#: the same fix twice. A CREATE-mode site carries contact details anyway,
#: because the theme renders them when the facts exist.
#:
#: Every key is a feature the research pipeline emits with PRESENT meaning
#: healthy, so `not_found` is the gap. See `roadmap.readiness.INVERTED` for the
#: one feature in the codebase where that is not true.
FIXES: dict[str, str] = {
    "page_title": "a title on every page",
    "meta_description": "a description search engines can read",
    "h1": "a heading on every page",
    "viewport_meta": "a layout that works on a phone",
    "broken_links": "internal links that resolve",
    "thin_pages": "pages with something on them",
    "page_speed": "a page that loads quickly",
    "duplicate_titles": "a distinct title per page",
}


class NothingToBuild(ValueError):
    """There is no artefact to produce, and that is a finding, not a failure.

    Raised when a site already does everything this capability could add. The
    execution layer records it as a failed job, which is correct: no asset was
    produced, so nothing can be approved or published.
    """


class WebsiteMode(StrEnum):
    CREATE = "create"
    MODIFY = "modify"


def _observed(research: dict) -> tuple[frozenset[str], frozenset[str]]:
    """Confirmed present and confirmed absent. Unverified is neither."""
    observations = research.get("observations") or []
    present, absent = set(), set()
    for observation in observations:
        feature, status = observation.get("feature"), observation.get("status")
        if status == "present":
            present.add(feature)
        elif status == "not_found":
            absent.add(feature)
    return frozenset(present), frozenset(absent)


class SiteState(StrEnum):
    """What research established about the site's existence. Four answers.

    The middle two are the ones that matter. Treating UNVERIFIED as ABSENT
    offers a business a website it already has; treating it as PRESENT builds a
    modification against evidence nobody gathered.
    """

    #: No site recorded, or DNS says no such host. Conclusive.
    ABSENT = "absent"
    #: A site is recorded and research could not read it. Establishes nothing.
    UNVERIFIED = "unverified"
    #: Read, and confirmed short of what this capability could add.
    WEAK = "weak"
    #: Read, and already doing everything this capability could add.
    STRONG = "strong"


def site_state(research: dict) -> SiteState:
    """The four-way answer, read from the `website` observation.

    Read from the observation rather than inferred from an HTTP status: a status
    of zero means "we did not get one", which is exactly the case that must not
    become "there is no website".
    """
    present, absent = _observed(research)
    if "website" in absent:
        return SiteState.ABSENT
    if "website" not in present:
        return SiteState.UNVERIFIED
    return SiteState.WEAK if improvable(research) else SiteState.STRONG


def mode_for(research: dict) -> WebsiteMode:
    """Derived from what research established, never passed in.

    Letting a caller declare which mode applies is how a business with a working
    website gets a new one built over the top of it.
    """
    return (WebsiteMode.CREATE if site_state(research) is SiteState.ABSENT
            else WebsiteMode.MODIFY)


def improvable(research: dict) -> tuple[str, ...]:
    """What this capability could add that the site confirmedly lacks.

    Only `not_found`. A feature nobody checked is not a gap — it is a gap in our
    knowledge, and building against it would be manufacturing a weakness.
    """
    _present, absent = _observed(research)
    return tuple(sorted(FIXES[feature] for feature in absent if feature in FIXES))


def _facts(business: Business | None, business_name: str, research: dict
           ) -> tuple[SiteContent, list[str]]:
    """Content, and the list of what was left out for want of a source."""
    missing: list[str] = []
    record = f"business {business.id}" if business else "supplied business name"

    def fact(value: str | None, note: str = record) -> Fact | None:
        """A fact, or nothing. Never a fact with an empty value.

        The `or ""` is not defensive tidying: a `Business` may hold `None` for a
        detail nobody recorded, and the difference between "no phone number" and
        "a phone number that is the empty string" is the difference between a
        page without a phone number and a page with a broken `tel:` link on it.
        """
        text = (value or "").strip()
        return Fact(value=text, source=FactSource.BUSINESS_RECORD,
                    note=note) if text else None

    name = fact(business.name if business else business_name)
    if name is None:
        raise NothingToBuild("no business name, and a site with no name is not a site")

    for label, value in (("phone", business.phone if business else ""),
                         ("email", business.email if business else ""),
                         ("location", business.geography if business else "")):
        if not (value or "").strip():
            missing.append(label)

    # Service names read from the business's own published pages. OBSERVED,
    # because they were seen rather than supplied — and only titles, because a
    # description we wrote would be a claim about their service.
    cms = (research.get("facts") or {}).get("cms") or {}
    services = [
        Service(name=Fact(value=title, source=FactSource.OBSERVED,
                          note=f"published at {page.get('url') or page.get('slug')}"))
        for page in (cms.get("service_page_list") or [])
        if (title := (page.get("title") or "").strip())
    ]

    return SiteContent(
        business_name=name,
        location=fact(business.geography if business else ""),
        contact=ContactDetails(phone=fact(business.phone if business else ""),
                               email=fact(business.email if business else "")),
        services=services,
        # Prose describes and asserts nothing. It names the business and says
        # what the page is; every claim on the page comes from a Fact.
        about=Prose(text=f"{name.value} — enquiries and contact details.")
        if not services else None,
    ), missing


def build_website(*, business_name: str, research: dict,
                  strengths: tuple[str, ...] = (),
                  business: Business | None = None,
                  theme: str = "clean") -> tuple[dict[str, str], dict]:
    """Build or improve a site. Returns the file bundle and its provenance.

    Raises rather than producing an artefact when there is nothing to do — a
    capability that always produces something is one whose output means nothing.
    """
    state = site_state(research)
    mode = mode_for(research)
    gaps = improvable(research)
    present, _absent = _observed(research)

    if state is SiteState.UNVERIFIED:
        raise NothingToBuild(
            f"research could not establish whether {business_name} has a website. "
            "That is a gap in what we checked, not a gap in their business, and "
            "building against it would be inventing the finding.")
    if mode is WebsiteMode.MODIFY and not gaps:
        addressable = ", ".join(sorted(FIXES)) or "nothing"
        raise NothingToBuild(
            f"{business_name} already has a site with none of the problems this "
            f"capability fixes ({addressable}). A strong site is a finding, not "
            "a reason to rebuild it.")

    content, missing = _facts(business, business_name, research)
    files, provenance = generate(content, theme=theme)

    provenance = {
        **provenance,
        "mode": mode.value,
        "site_state": state.value,
        # What the build is a response to. A reviewer can check every one of
        # these against the research record.
        "addresses": list(gaps),
        "left_alone": sorted(f for f in present if f in FIXES),
        # Said out loud rather than inferred from a short page. A site missing a
        # phone number is missing it because nobody recorded one.
        "not_published_for_want_of_a_source": missing,
        "strengths_noted": list(strengths),
    }
    return files, provenance
