"""Everything the AHS concept is allowed to say, and where it was read from.

One module, not a set of parallel lists. The site generator, the audit document
and the tests all read from here, so a fact cannot be true in one place and
missing in another.

Read from ahscatering.com on 2026-08-21 — the twelve pages linked from their
navigation, plus their WordPress REST API, which exposes sixty pages and four
posts. Nothing below is inferred. Where a field is not published it is `None`,
and the site renders that as "not published" rather than filling it in.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SOURCE = "https://ahscatering.com/"
CHECKED_AT = "2026-08-21"

# --- how to reach them -----------------------------------------------------
#: WhatsApp came from their Click-to-Chat widget config, not from the phone
#: number. They happen to match; that was established, not assumed.
PHONE_E164 = "+971557492608"
PHONE_HUMAN = "+971 55 749 2608"
WHATSAPP = "971557492608"
EMAIL = "Info@ahscatering.com"
ADDRESS = "Dubai Investment Park 2"
INSTAGRAM = "https://www.instagram.com/ahscatering"
LINKEDIN = "https://www.linkedin.com/company/ahs-catering-and-events"

#: Their own words, from the homepage hero and the About page.
TAGLINE = "Beyond Catering"
HERO_BLURB = ("Backed by 20+ years of culinary mastery, halal-certified kitchens and a "
              "planning team that perfects every detail of your celebration.")
FOOTER_BLURB = ("Our team of qualified and experienced personnel is always prepared to "
                "provide a comprehensive service for a unique experience.")
ABOUT_OPENER = ("AHS Catering and Events is a leading Dubai catering company with more than "
                "20 years of excellence in luxury weddings, corporate functions, and private "
                "celebrations. From intimate gatherings to large-scale galas, we craft tailored "
                "menus that blend authentic Middle Eastern flavors with refined international "
                "cuisine, all prepared in halal-certified kitchens.")
FOUNDER = "Ali Darwish"
#: About page, paraphrase-free summary of what it states about him.
FOUNDER_FACTS = (
    "Started at 16 in hospitality — polishing cutlery, serving tables.",
    "Learned front-of-house first, then moved into the kitchen to understand "
    "production, preparation systems, discipline and consistency.",
    "Travelled across Europe, Asia and the Middle East for inspiration rather than recipes.",
)
FOUNDER_QUOTE = "You can't lead excellence if you don't understand the details."

#: EATLUX, from their own EATLUX page and blog post.
EATLUX_CLAIM = "the UAE's first-ever Show Belt Dining Experience"
EATLUX_ORIGIN = ("Kristina, from wedding planning, saw that catering too often meant long "
                 "buffet queues and uninspired dishes. She joined forces with Ali, and EATLUX "
                 "came out of that.")

#: Verbatim from the About page. Their claim about themselves, not ours.
CLIENTS_ABOUT = ("MBC Group", "Michelin", "Dubai Mall", "Gucci", "Booking.com", "Validus",
                 "Hyundai", "Red Bull", "Nestlé", "Messara Living", "the Romanian Consulate",
                 "Sephora")
#: From the Formula 1 post, 11 Nov 2025.
CLIENTS_BLOG = ("Amazon", "Bybit", "DHL", "Dubai Police", "DEWA")
F1 = "Formula 1 Abu Dhabi Grand Prix 2025"

CAPABILITIES = (
    ("Capacity", "Scaled to the event rather than a fixed maximum."),
    ("HACCP certified", "Food safety management in the kitchens behind every event."),
    ("Sustainability", "Local sourcing, zero-waste kitchen practice, reusable serviceware."),
    ("Local products", "Regional producers, for freshness and a shorter journey."),
    ("Special dietary needs", "Vegan, gluten-free, halal and allergen-free menus."),
)


# --- the work they have published -----------------------------------------

@dataclass(frozen=True)
class Case:
    """One of their event pages.

    `client`, `kind` and `venue` are `None` unless their own page title says so.
    That is the whole point: the concept shows what they publish and marks the
    rest unpublished, instead of writing a plausible sentence.
    """

    slug: str
    title: str          #: their page title, exactly
    photos: int         #: images counted in that page's content
    sector: str
    client: str | None = None
    kind: str | None = None
    venue: str | None = None
    note: str = ""      #: only ever an observation about their page, never about the event

    @property
    def unpublished(self) -> tuple[str, ...]:
        missing = ["Date", "Guests", "Menu", "Service style"]
        if self.client is None:
            missing.insert(0, "Client")
        if self.kind is None:
            missing.insert(0, "Event type")
        return tuple(missing)


CASES: tuple[Case, ...] = (
    Case("nestle", "Nestle", 6, "fmcg", client="Nestlé"),
    Case("porsche", "Porsche", 3, "automotive", client="Porsche"),
    Case("red-bull-event", "Red bull event", 5, "fmcg", client="Red Bull"),
    Case("roger-vivier-dubai-mall", "ROGER VIVIER DUBAI MALL", 6, "luxury",
         client="Roger Vivier", venue="Dubai Mall"),
    Case("mbc-group-ramadan-iftar", "Mbc group Ramadan iftar", 5, "media",
         client="MBC Group", kind="Ramadan iftar"),
    Case("geidea-board-meeting", "GEIDEA BOARD MEETING", 6, "finance",
         client="Geidea", kind="Board meeting"),
    Case("schwarzkopf-academy", "Schwarzkopf academy", 3, "beauty",
         client="Schwarzkopf", kind="Academy"),
    Case("breakfast-catering-for-pepsi-in-dip", "BREAKFAST CATERING FOR PEPSI IN DIP", 5,
         "fmcg", client="Pepsi", kind="Breakfast", venue="Dubai Investment Park"),
    Case("validus-office-opening", "Validus office opening", 6, "professional",
         client="Validus", kind="Office opening"),
    Case("validus-office-brunch", "VALIDUS OFFICE BRUNCH", 6, "professional",
         client="Validus", kind="Office brunch"),
    Case("nour-energy-board-meeting", "Nour energy board meeting", 6, "energy",
         client="Nour Energy", kind="Board meeting"),
    Case("yallabid-auction-event", "YALLABID AUCTION EVENT", 6, "tech",
         client="YallaBid", kind="Auction event"),
    Case("nas-daily-x-solana", "NAS DAILY × SOLANA", 3, "media", client="Nas Daily × Solana"),
    Case("german-experts-management-iftar", "German experts management iftar", 3,
         "professional", client="German Experts Management", kind="Iftar"),
    Case("opening-basetruck-company", "OPENING BASETRUCK COMPANY", 5, "logistics",
         client="BaseTruck", kind="Company opening"),
    Case("luxury-cars-showroom-opening", "Luxury cars showroom opening", 6, "automotive",
         kind="Showroom opening"),
    Case("company-opening-dip", "COMPANY OPENING DIP", 5, "corporate",
         kind="Company opening", venue="Dubai Investment Park"),
    Case("corporate-lunch", "CORPORATE LUNCH", 6, "corporate", kind="Corporate lunch"),
    Case("staff-party-for-real-estate", "STAFF PARTY FOR REAL ESTATE", 5, "real-estate",
         kind="Staff party"),
    Case("nas-daily-x-solana-2-3-4", "Staff party for real estate", 6, "real-estate",
         kind="Staff party",
         note="Published under a nas-daily-x-solana URL — the address and the page disagree."),
    Case("event-in-5-hotels-jvc", "EVENT IN 5 HOTELS JVC", 6, "hospitality", venue="JVC"),
    Case("winter-wonderland", "Winter wonderland", 7, "seasonal"),
    Case("arabic-theme-dinner", "ARABIC THEME DINNER", 6, "private", kind="Theme dinner"),
    Case("thanks-giving-seated-dinner", "Thanks Giving Seated dinner", 5, "private",
         kind="Seated dinner"),
    Case("dubai-palm-jumairah-private", "DUBAI PALM JUMAIRAH PRIVATE", 2, "private",
         venue="Palm Jumeirah"),
    Case("birthday-celebration", "BIRTHDAY CELEBRATION", 7, "private", kind="Birthday"),
    Case("birthday-seated-dinner", "Birthday seated dinner", 5, "private",
         kind="Birthday, seated"),
    Case("nas-daily-x-solana-16-2", "Birthday", 6, "private", kind="Birthday",
         note="Also published under a nas-daily-x-solana URL."),
    Case("private-brunch", "PRIVATE BRUNCH", 6, "private", kind="Brunch"),
    Case("private-catering-brunch", "Private catering brunch", 6, "private", kind="Brunch"),
    Case("private-catering-seated-lunch", "Private catering seated lunch", 6, "private",
         kind="Seated lunch"),
    Case("private-catering-dinner", "Private catering dinner", 6, "private", kind="Dinner"),
)

SECTORS = {
    "fmcg": "FMCG", "automotive": "Automotive", "luxury": "Luxury & fashion",
    "media": "Media", "finance": "Finance", "beauty": "Beauty", "tech": "Technology",
    "energy": "Energy", "logistics": "Logistics", "professional": "Professional services",
    "real-estate": "Real estate", "corporate": "Corporate", "hospitality": "Hospitality",
    "seasonal": "Seasonal", "private": "Private",
}

PHOTOS_TOTAL = sum(c.photos for c in CASES)
MEDIA_LIBRARY = 501  #: X-WP-Total on their /wp/v2/media endpoint


# --- what they sell --------------------------------------------------------

@dataclass(frozen=True)
class Service:
    slug: str
    name: str
    source_path: str
    words: int          #: on their page
    photos: int         #: on their page
    points: tuple[str, ...]   #: headings they publish under it


SERVICES: tuple[Service, ...] = (
    Service("corporate", "Corporate catering",
            "/corporate-catering-in-dubai-premium-catering-for-corporate-events/", 878, 19,
            ("Tailored menus", "Professional presentation", "On-time & seamless service",
             "Experience with Dubai corporates")),
    Service("private", "Private catering", "/private-catering-services/", 795, 15,
            ("Housewarming parties", "Birthday catering", "Gatherings & social events",
             "Seated dinners")),
    Service("live-stations", "Live station catering",
            "/live-station-catering-in-dubai-gourmet-interactive-experience/", 981, 17,
            ("BBQ station", "Seafood & oyster bar", "Pasta & gourmet sliders")),
    Service("canape-dessert", "Canapé & dessert catering", "/canap-dessert-catering/", 805, 16,
            ("European canapés", "Arabic delight", "Asian & international")),
    Service("wedding", "Wedding catering", "/wedding-catering/", 1045, 9,
            ("Seated & plated wedding dining", "Wedding buffet & live stations")),
    Service("gala", "Gala catering", "/gala-catering/", 787, 7,
            ("Black-tie corporate award nights", "Executive private dinners",
             "Seated & plated fine dining", "Culinary direction — gala edition")),
    Service("ramadan", "Ramadan 2026", "/ramadan-2026-2/", 554, 17,
            ("Leadership in hospitality", "For corporate leaders & private hosts",
             "Execution first. Always.", "Premium grilled & carving stations",
             "Signature Ramadan dessert")),
    Service("eatlux", "EATLUX", "/eatlux/", 756, 1,
            ("Show belt dining", "Canapés on a moving belt", "Hostesses in synchrony")),
)


# --- what they have written ------------------------------------------------

@dataclass(frozen=True)
class Article:
    slug: str
    source_slug: str
    title: str          #: their title, exactly
    date: str
    words: int          #: on their site
    theme: str
    facts: tuple[str, ...] = field(default_factory=tuple)


#: All four of their posts. Every one published 2025-11-11, all "Uncategorized",
#: none carries a single image.
ARTICLES: tuple[Article, ...] = (
    Article("formula-1-abu-dhabi", "the-latest-one-is-the-formula-1-catering-announcement",
            "AHS Catering & Events Joins the Formula 1 Abu Dhabi 2025 Stage", "2025-11-11", 103,
            "proof",
            ("Serving at the Formula 1 Abu Dhabi Grand Prix 2025.",
             "Names Amazon, Bybit, DHL, Dubai Police and DEWA as brands served.")),
    Article("show-belt-dining", "eatlux-where-dining-becomes-a-show",
            "EatLux — Where Dining Becomes a Show", "2025-11-11", 149, "eatlux",
            ("EATLUX is described as the UAE's first-ever Show Belt Dining Experience.",
             "Canapés travel a moving belt; hostesses work in synchrony.",
             "Positioned as engagement without hiring additional performers.")),
    Article("behind-the-scenes", "behind-the-scenes-crafting-a-luxury-catering-experience",
            "Behind the Scenes — Crafting a Luxury Catering Experience", "2025-11-11", 331,
            "method",
            ("Their planning starts from one question: what do you want guests to feel?",
             "Menus are built as chapters, beginning with arrival canapés.")),
    Article("sustainable-luxury", "sustainability-luxury-yes-they-can-coexist",
            "Sustainability & Luxury — Yes, They Can Coexist", "2025-11-11", 146,
            "sustainability",
            ("Local sourcing from regional producers.",
             "Zero-waste kitchen systems.",
             "Reusable glass, metal and bamboo serviceware.",
             "Vegan, gluten-free, halal and allergen-free menus.")),
)


# --- what is wrong with their site, with the evidence ----------------------

@dataclass(frozen=True)
class Defect:
    key: str
    title: str
    evidence: str
    where: str


DEFECTS: tuple[Defect, ...] = (
    Defect("click_to_call", "Phone and email are not links",
           "No tel: or mailto: anywhere on the site; both are plain text on all 12 pages.",
           "every page"),
    Defect("no_arabic", "No Arabic version",
           'html lang="en-US", no hreflang alternates, no language switcher, no translation '
           "plugin. The site is English only.",
           "every page"),
    Defect("work_invisible", "The work is not reachable from the homepage",
           f"{len(CASES)} event pages carrying {PHOTOS_TOTAL} photographs. The homepage links "
           "to none of them.",
           "/wp-json/wp/v2/pages"),
    Defect("cases_empty", "Event pages carry no information",
           "Each event page is a title and photographs — the 33 sampled average under five "
           "words. No date, guest count, service style or menu on any of them.",
           "every event page"),
    Defect("clients_buried", "The client list is one sentence in About",
           f"{len(CLIENTS_ABOUT)} named brands inside a paragraph, plus {len(CLIENTS_BLOG)} more "
           "in a blog post. Not on the homepage, not linked to the work.",
           "/about-us/"),
    Defect("reviews_orphan", "Testimonials name a different brand",
           'The /reviews/ page is not in the navigation, and two of its three testimonials '
           'thank "Al Hamra Street" rather than AHS.',
           "/reviews/"),
    Defect("blog_thin", "Four posts, one day, no pictures",
           f"All four published 2025-11-11, all filed Uncategorized, {min(a.words for a in ARTICLES)}"
           f"–{max(a.words for a in ARTICLES)} words, and not one image — beside a "
           f"{MEDIA_LIBRARY}-item media library.",
           "/blog/"),
    Defect("privacy_default", "The privacy policy is the WordPress sample text",
           'Unedited: "Who we are — Our website address is…", then sections on blog comments, '
           "Gravatar and embedded content. Nothing about catering, events or guest data.",
           "/privacy-policy-2/"),
    Defect("ia_decay", "Duplicate and stale routes",
           "/home-old-old/, /homeold/, /sample-page-2-2/ titled New Home, /privet/, "
           "/corporate-events-2/ titled PRIVATE EVENTS, three Ramadan pages, and two competing "
           "corporate-catering URLs.",
           "/wp-json/wp/v2/pages"),
    Defect("nav_eleven", "Eleven top-level items",
           "The navigation wraps onto three lines at 1280 and asks the visitor to classify "
           "themselves before they have seen anything.",
           "every page"),
)

#: Things their site does that the concept must not lose.
KEEP = ("Gold on near-black", "Beyond Catering", "Uppercase headline voice",
        "Full-bleed dark food photography", "Bespoke quoting with no published prices")
