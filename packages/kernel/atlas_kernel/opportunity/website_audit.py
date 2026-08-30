"""What a prospect's existing website actually does, with evidence.

A demo only sells if it is *demonstrably* better than what the clinic already
has, and half of these clinics have a decent site. So the pitch cannot be "yours
looks old" — it has to be "yours has no click-to-call on mobile, here is the
line of your own HTML, and here is what that costs you".

**Three states, never two.** A feature is `PRESENT`, `NOT_FOUND` or
`UNVERIFIED`, and the last is not a polite way of saying missing. A homepage
visit cannot see a doctors page that exists two clicks away, and telling a
dentist their site lacks something it has is the fastest way to lose both the
argument and the meeting. Every finding carries the evidence that produced it,
so any claim can be checked before it is said out loud.

Only the homepage is fetched — one page per clinic, the same request any visitor
makes. Nothing here crawls a site, follows a sitemap or touches anything a
`robots.txt` would speak to.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


#: schema.org types that mark a page as a local business.
#:
#: A sample, not the whole vocabulary — schema.org declares roughly two hundred
#: `LocalBusiness` subtypes and this audit runs against whatever verticals Qevik
#: is scanning. It began as five dental and medical types, which meant a plumber
#: publishing valid `@type: Plumber` was recorded as having no local-search
#: signal.
#:
#: Because it is a sample, a type absent from it produces `UNVERIFIED` rather
#: than `NOT_FOUND`: this list not recognising something is a fact about the
#: list.
LOCAL_BUSINESS_TYPES: tuple[str, ...] = (
    "localbusiness", "organization",
    # health
    "dentist", "medicalclinic", "medicalbusiness", "physician", "hospital",
    "pharmacy", "veterinarycare", "optician",
    # trades and home services
    "plumber", "electrician", "roofingcontractor", "generalcontractor",
    "homeandconstructionbusiness", "movingcompany", "housepainter",
    "locksmith", "hvacbusiness",
    # food and hospitality
    "restaurant", "cafeorcoffeeshop", "bakery", "bar", "foodestablishment",
    "lodgingbusiness", "hotel",
    # retail and personal
    "store", "healthandbeautybusiness", "beautysalon", "hairsalon", "daysspa",
    "automotivebusiness", "autorepair", "sportsactivitylocation", "gym",
    # professional
    "professionalservice", "legalservice", "accountingservice",
    "realestateagent", "travelagency", "childcare", "educationalorganization",
)


#: Types that are structural page furniture, never a local-business signal.
#:
#: Named so that "this is not a local business type" and "this audit does not
#: recognise this type" stay different answers. A breadcrumb is conclusively not
#: a local-search signal; `@type: Plumber` is one this list simply had not heard
#: of, and reporting the second as the first put a false finding in front of the
#: business it was about.
NOT_LOCAL_TYPES: tuple[str, ...] = (
    "breadcrumblist", "webpage", "website", "article", "blogposting",
    "newsarticle", "faqpage", "itemlist", "searchaction", "videoobject",
    "imageobject", "collectionpage", "sitenavigationelement",
)


class Status(StrEnum):
    """Whether a feature is there.

    `UNVERIFIED` exists so that an honest gap in the audit never gets reported
    as a gap in the customer's website.
    """

    PRESENT = "present"
    #: Looked for it on the homepage and it was not there. For features a site
    #: would normally surface on the homepage, this is a real finding.
    NOT_FOUND = "not_found"
    #: Could not tell — the page did not load, or the feature would normally
    #: live on a subpage this audit did not open. Never counted against them.
    UNVERIFIED = "unverified"


class Category(StrEnum):
    CONVERSION = "conversion"
    CONTACT = "contact"
    BOOKING = "booking"
    LOCAL_SEO = "local_seo"
    SEO = "seo"
    MOBILE = "mobile"
    CONTENT = "content"
    TRUST = "trust"
    ACCESSIBILITY = "accessibility"
    PERFORMANCE = "performance"
    MULTILINGUAL = "multilingual"
    TECHNICAL = "technical"


class Finding(BaseModel):
    """One observation about one feature, and what proves it."""

    model_config = ConfigDict(frozen=True)

    feature: str
    category: Category
    status: Status
    #: The actual thing observed — a matched href, a tag, a measured number.
    #: Without this a finding is an opinion, and an opinion is not something to
    #: put in front of a business owner about their own website.
    evidence: str = ""
    #: Why this matters to a dental practice specifically.
    note: str = ""

    @property
    def counts_against(self) -> bool:
        """Only a confirmed absence is a weakness."""
        return self.status is Status.NOT_FOUND


class SiteAudit(BaseModel):
    """Everything observed about one clinic's existing website."""

    model_config = ConfigDict(frozen=True)

    clinic: str
    url: str
    reachable: bool = False
    http_status: int = 0
    load_ms: int = 0
    page_bytes: int = 0
    is_https: bool = False
    error: str = ""
    findings: list[Finding] = Field(default_factory=list)
    audited_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def by_status(self, status: Status) -> list[Finding]:
        return [f for f in self.findings if f.status is status]

    @property
    def strengths(self) -> list[Finding]:
        return self.by_status(Status.PRESENT)

    @property
    def weaknesses(self) -> list[Finding]:
        """Confirmed absences only. An unverified feature is never a weakness."""
        return self.by_status(Status.NOT_FOUND)

    @property
    def unverified(self) -> list[Finding]:
        return self.by_status(Status.UNVERIFIED)


#: What to look for, and how. Each entry is (feature, category, note) — the
#: detection lives in `audit_html` so the evidence and the rule stay together.
#:
#: **The notes are vertical-neutral, and that is a correctness requirement.**
#: This table was written for dental clinics and applied to every business the
#: engine audited. It ran against 40 retail businesses and recorded, about Sony
#: at the Dubai Mall, that "a patient in pain phones" and that emergency
#: patients convert immediately — sentences that are false about a shop and
#: would have gone out over Qevik's name once the health-check product started
#: showing them to the business they are about.
#:
#: A note says what a missing feature costs *any* business with a website. Where
#: a vertical-specific sentence is genuinely better it belongs in a per-vertical
#: override keyed on the audit's own category, not in the shared table.
FEATURE_NOTES: dict[str, tuple[Category, str]] = {
    "click_to_call": (
        Category.CONVERSION,
        "Someone ready to phone has to copy the number by hand, on the device "
        "they would have called from.",
    ),
    "whatsapp": (
        Category.CONTACT,
        "In the UAE most enquiries arrive on WhatsApp rather than through a form.",
    ),
    "contact_form": (Category.CONTACT,
                     "A written route for anyone who would rather not phone."),
    "booking_link": (
        Category.BOOKING,
        "A direct route to book rather than a general contact page.",
    ),
    "google_maps": (Category.LOCAL_SEO, "People choose a place they can find and drive to."),
    "opening_hours": (
        Category.CONTENT,
        "Opening hours are among the most-looked-for facts on any local "
        "site; absent, people phone to ask or go elsewhere.",
    ),
    "services_navigation": (Category.CONTENT,
                            "Visitors usually arrive looking for one specific thing."),
    "doctors_team": (Category.TRUST,
                     "Named people are one of the strongest trust signals a site has."),
    "insurance_info": (Category.TRUST,
                        "Where it applies, what is accepted or covered decides the enquiry."),
    "emergency_info": (Category.CONVERSION,
                         "Someone with an urgent need acts immediately or leaves."),
    "social_proof": (Category.TRUST, "Reviews shown on the page rather than only on Google."),
    "structured_data": (
        Category.LOCAL_SEO,
        "Structured data is what puts a local business into search results "
        "and map packs.",
    ),
    "meta_description": (Category.SEO, "Controls the snippet a searcher reads before clicking."),
    "page_title": (Category.SEO, "The clickable line in search results."),
    "viewport_meta": (Category.MOBILE, "Without it a phone renders a desktop page zoomed out."),
    "h1": (Category.SEO, "One clear page heading, for readers and for search."),
    "image_alt_text": (Category.ACCESSIBILITY, "Screen readers, and image search."),
    "arabic": (Category.MULTILINGUAL,
                "A large share of people in Dubai read Arabic first."),
    "https": (Category.TECHNICAL, "Browsers warn on forms served without it."),
    "page_weight": (Category.PERFORMANCE, "Heavy pages lose mobile visitors before they render."),
}

_ARABIC = re.compile(r"[؀-ۿ]")
_HOURS = re.compile(
    r"(mon|tue|wed|thu|fri|sat|sun)[a-z]*\s*[-–—:]?\s*(?:[a-z]*\s*)?\d{1,2}[:.]\d{2}"
    r"|\d{1,2}[:.]\d{2}\s*(?:am|pm)?\s*[-–—]\s*\d{1,2}[:.]\d{2}",
    re.I,
)
_BOOKING_WORDS = re.compile(r"book|appointment|schedule|reserve|احجز|موعد", re.I)
_SERVICE_WORDS = re.compile(r"\bservices?\b|treatments?|خدمات", re.I)
_TEAM_WORDS = re.compile(r"\bdoctors?\b|\bdentists?\b|our team|meet the team|أطباء", re.I)


def _finding(feature: str, status: Status, evidence: str = "") -> Finding:
    category, note = FEATURE_NOTES[feature]
    return Finding(
        feature=feature, category=category, status=status, evidence=evidence[:300], note=note
    )


def audit_html(html: str, *, url: str, page_bytes: int) -> list[Finding]:
    """Read one homepage and report what it demonstrably has.

    Deliberately conservative. Where a feature would normally live on a subpage
    — a full doctors list, an insurance page — absence from the homepage is
    reported as UNVERIFIED rather than NOT_FOUND, because a homepage visit is
    not evidence that a site lacks a page it did not open.
    """
    low = html.lower()
    findings: list[Finding] = []

    def seen(feature: str, pattern: str, *, flags=re.I) -> re.Match | None:
        return re.search(pattern, html, flags)

    # -- things a homepage either has or does not ------------------------
    tel = seen("click_to_call", r'href=["\']tel:([^"\']+)')
    findings.append(
        _finding(
            "click_to_call",
            Status.PRESENT if tel else Status.NOT_FOUND,
            f"href=tel:{tel.group(1)}" if tel else "no tel: link in the homepage HTML",
        )
    )

    wa = seen("whatsapp", r'href=["\'][^"\']*(?:wa\.me|api\.whatsapp\.com)[^"\']*')
    findings.append(
        _finding(
            "whatsapp",
            Status.PRESENT if wa else Status.NOT_FOUND,
            wa.group(0)[:120] if wa else "no wa.me or api.whatsapp.com link",
        )
    )

    has_form = bool(re.search(r"<form[^>]*>", html, re.I)) and bool(
        re.search(r"<(?:input|textarea)[^>]*>", html, re.I)
    )
    findings.append(
        _finding(
            "contact_form",
            Status.PRESENT if has_form else Status.NOT_FOUND,
            "<form> with inputs" if has_form else "no form with input fields on the homepage",
        )
    )

    booking = None
    for match in re.finditer(
        r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.{0,80}?)</a>", html, re.I | re.S
    ):
        href, text = match.group(1), re.sub(r"<[^>]+>", " ", match.group(2))
        if _BOOKING_WORDS.search(text) or _BOOKING_WORDS.search(href):
            booking = f"{text.strip()[:40]!r} -> {href[:80]}"
            break
    findings.append(
        _finding(
            "booking_link",
            Status.PRESENT if booking else Status.NOT_FOUND,
            booking or "no link or button whose text or target mentions booking",
        )
    )

    maps = seen(
        "google_maps",
        r'(?:src|href)=["\'][^"\']*(?:google\.[a-z.]+/maps|maps\.app\.goo\.gl|goo\.gl/maps)[^"\']*',
    )
    findings.append(
        _finding(
            "google_maps",
            Status.PRESENT if maps else Status.NOT_FOUND,
            maps.group(0)[:120] if maps else "no Google Maps embed or link",
        )
    )

    hours = _HOURS.search(re.sub(r"<[^>]+>", " ", html))
    findings.append(
        _finding(
            "opening_hours",
            Status.PRESENT if hours else Status.NOT_FOUND,
            hours.group(0)[:60] if hours else "no day/time pattern in the homepage text",
        )
    )

    services = _SERVICE_WORDS.search(html)
    findings.append(
        _finding(
            "services_navigation",
            Status.PRESENT if services else Status.NOT_FOUND,
            "services/treatments wording present" if services else "no services wording",
        )
    )

    # -- technical, always determinable from the page --------------------
    title = re.search(r"<title[^>]*>(.{1,200}?)</title>", html, re.I | re.S)
    findings.append(
        _finding(
            "page_title",
            Status.PRESENT if title and title.group(1).strip() else Status.NOT_FOUND,
            (title.group(1).strip()[:120] if title else "no <title>"),
        )
    )

    desc = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]*content=["\']([^"\']{1,300})', html, re.I
    )
    findings.append(
        _finding(
            "meta_description",
            Status.PRESENT if desc else Status.NOT_FOUND,
            (desc.group(1)[:120] if desc else "no meta description"),
        )
    )

    viewport = seen("viewport_meta", r'<meta[^>]+name=["\']viewport["\']')
    findings.append(
        _finding(
            "viewport_meta",
            Status.PRESENT if viewport else Status.NOT_FOUND,
            "viewport meta present" if viewport else "no viewport meta — desktop layout on phones",
        )
    )

    h1 = re.search(r"<h1[^>]*>(.{0,120}?)</h1>", html, re.I | re.S)
    findings.append(
        _finding(
            "h1",
            Status.PRESENT if h1 else Status.NOT_FOUND,
            re.sub(r"<[^>]+>", "", h1.group(1)).strip()[:80] if h1 else "no <h1> on the homepage",
        )
    )

    # Structured data: present is not enough — it has to describe the business
    # rather than the page.
    ld = re.findall(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", html, re.I | re.S)
    blob = " ".join(ld).lower()
    if not ld:
        findings.append(_finding("structured_data", Status.NOT_FOUND, "no ld+json block"))
    elif any(t in blob for t in LOCAL_BUSINESS_TYPES):
        kind = next(t for t in LOCAL_BUSINESS_TYPES if t in blob)
        findings.append(
            _finding("structured_data", Status.PRESENT, f"ld+json @type includes {kind}")
        )
    else:
        # Two different answers, kept apart.
        #
        # A breadcrumb or a web page is conclusively not a local-search signal.
        # A type this audit has never heard of is not a finding about the
        # business — `LOCAL_BUSINESS_TYPES` is a sample of schema.org, and
        # reporting its gaps as theirs told a plumber publishing valid
        # `@type: Plumber` that they had no local-search signal.
        if any(t in blob for t in NOT_LOCAL_TYPES):
            findings.append(
                _finding(
                    "structured_data",
                    Status.NOT_FOUND,
                    "ld+json describes page structure rather than the business "
                    "— not a local-search signal",
                )
            )
        else:
            findings.append(
                _finding(
                    "structured_data",
                    Status.UNVERIFIED,
                    "ld+json is present and its @type is not one this audit "
                    "recognises, so whether it is a local-business signal was "
                    "not established",
                )
            )

    images = re.findall(r"<img\b[^>]*>", html, re.I)
    with_alt = [i for i in images if re.search(r'\balt=["\'][^"\']+', i)]
    if not images:
        findings.append(
            _finding("image_alt_text", Status.UNVERIFIED, "no <img> tags in the served HTML")
        )
    else:
        share = len(with_alt) / len(images)
        findings.append(
            _finding(
                "image_alt_text",
                Status.PRESENT if share >= 0.6 else Status.NOT_FOUND,
                f"{len(with_alt)}/{len(images)} images have alt text",
            )
        )

    arabic = (
        _ARABIC.search(html)
        or re.search(r'\blang=["\']ar', html, re.I)
        or re.search(r'href=["\'][^"\']*/ar[/"\']', html, re.I)
    )
    findings.append(
        _finding(
            "arabic",
            Status.PRESENT if arabic else Status.NOT_FOUND,
            "Arabic text or /ar route present"
            if arabic
            else "no Arabic content or language switch",
        )
    )

    findings.append(
        _finding(
            "https",
            Status.PRESENT if url.startswith("https://") else Status.NOT_FOUND,
            url.split("/")[0],
        )
    )

    findings.append(
        _finding(
            "page_weight",
            Status.PRESENT if page_bytes and page_bytes < 2_000_000 else Status.NOT_FOUND,
            f"{page_bytes / 1024:.0f} KB of HTML+resources measured",
        )
        if page_bytes
        else _finding("page_weight", Status.UNVERIFIED, "not measured")
    )

    # -- things a homepage cannot settle ---------------------------------
    # Absence here is UNVERIFIED, not a weakness: these routinely live on their
    # own page, and calling them missing would be a claim we cannot support.
    for feature, pattern in (
        ("doctors_team", _TEAM_WORDS),
        ("insurance_info", re.compile(r"insurance|تأمين", re.I)),
        ("emergency_info", re.compile(r"emergency|urgent care|طوارئ", re.I)),
        ("social_proof", re.compile(r"testimonial|reviews?|rating|patients say|★", re.I)),
    ):
        match = pattern.search(low if feature != "social_proof" else html)
        findings.append(
            _finding(
                feature,
                Status.PRESENT if match else Status.UNVERIFIED,
                (match.group(0)[:60] if match else "not on the homepage; may exist on a subpage"),
            )
        )

    return findings
