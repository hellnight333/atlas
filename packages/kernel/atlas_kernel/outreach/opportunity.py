"""What digital product this business is missing — not what is wrong with its site.

The audit answers "is the phone a link, is there an Arabic version". Useful, but
it only ever produces one pitch: *your website has defects, we fix websites*.
That pitch is interchangeable between every prospect and every agency in Dubai.

This module answers a different question. Given what the business already does,
what could be **built** for it? A caterer with thirty-two event pages that carry
photographs and no facts is not missing a redesign, it is missing a proof
system. A recruiter is missing a shortlist. That is the difference between
selling a website and selling a digital product.

Two rules hold the thing honest:

- an opportunity needs evidence, and the evidence is the audit's own
  observations. Nothing is derived from a hunch about the industry;
- only CONFIRMED_ABSENT counts. NOT_VERIFIED means the checker could not see it,
  which is a fact about the checker. Selling against it would be selling against
  our own blind spot.
"""

from __future__ import annotations

from dataclasses import dataclass

#: §3's controlled vocabulary. A product family is a real capability boundary —
#: what Qevik would have to build — not a marketing category.
FAMILIES: dict[str, tuple[str, ...]] = {
    "website": ("Website redesign", "Arabic experience", "Editorial website",
                "Landing experience", "Gallery", "Portfolio", "Case-study system",
                "Interactive lookbook"),
    "interaction": ("Booking flow", "Enquiry builder", "Quote builder", "Event planner",
                    "Appointment planner", "Configurator", "Calculator", "Estimator",
                    "Recommendation tool"),
    "accounts": ("Customer portal", "Membership", "Loyalty", "Saved items",
                 "Order tracking", "Shortlist"),
    "operations": ("Dashboard", "Internal workflow tool", "Scheduling", "Staff portal",
                   "CRM-style interface", "Candidate platform"),
    "commerce": ("E-commerce", "Catalogue", "Comparison", "Cart", "Subscription"),
    "discovery": ("Search", "Filters", "Recommendations", "Comparison", "Location finder",
                  "Service finder"),
    "marketing": ("Campaign microsite", "Interactive promotion", "Quiz", "Game",
                  "Lead-generation tool"),
    "ai": ("AI assistant", "AI recommendation", "AI search", "AI quotation assistant",
           "AI workflow"),
}

#: Every product name, for validating that an opportunity names a real one.
PRODUCTS: frozenset[str] = frozenset(p for group in FAMILIES.values() for p in group)

PRIORITIES = ("HIGH", "MEDIUM", "LOW")
CONFIDENCE = ("HIGH", "MEDIUM", "LOW")


class Unsupported(ValueError):
    """Raised when an opportunity is built without evidence, which is a bug.

    Not caught anywhere on purpose. An unsupported opportunity is a fabricated
    sales claim, and the correct behaviour is to fail loudly in a test rather
    than quietly rank it fifth.
    """


@dataclass(frozen=True)
class Opportunity:
    """A digital product this business could have, and why we say so."""

    key: str
    name: str            #: what the operator calls it
    product: str         #: from PRODUCTS — what Qevik would build
    family: str
    priority: str
    confidence: str
    evidence: tuple[str, ...]   #: observed facts, never adjectives
    why: str             #: why it fits *this* business
    builds: str          #: what Qevik would actually build
    user: str            #: whose problem it solves
    interaction: str     #: the main thing that user does
    value: str           #: the expected digital value
    demo: str | None = None     #: an existing demo slug, if one shows it

    def __post_init__(self) -> None:
        if not self.evidence:
            raise Unsupported(f"{self.key}: an opportunity without evidence is a guess")
        if self.product not in PRODUCTS:
            raise Unsupported(f"{self.key}: {self.product!r} is not in the vocabulary")
        if self.family not in FAMILIES:
            raise Unsupported(f"{self.key}: {self.family!r} is not a product family")
        if self.priority not in PRIORITIES or self.confidence not in CONFIDENCE:
            raise Unsupported(f"{self.key}: priority/confidence outside the scale")

    @property
    def rank(self) -> tuple[int, int, int]:
        """Priority first, then how sure we are, then how much we can show."""
        return (PRIORITIES.index(self.priority), CONFIDENCE.index(self.confidence),
                -len(self.evidence))


@dataclass(frozen=True)
class Rule:
    """Fires an opportunity when the audit confirms the ground for it."""

    key: str
    name: str
    product: str
    family: str
    priority: str
    confidence: str
    why: str
    builds: str
    user: str
    interaction: str
    value: str
    #: Features the audit must have CONFIRMED_ABSENT. Empty means the rule does
    #: not depend on an absence — it then needs `needs_present` or a category.
    absent: frozenset[str] = frozenset()
    #: Features that must be CONFIRMED_PRESENT — an opportunity that builds on
    #: something they already have.
    present: frozenset[str] = frozenset()
    #: Restrict to these categories. Empty means any.
    categories: frozenset[str] = frozenset()
    demo: str | None = None

    def evidence_for(self, absent: frozenset[str], present: frozenset[str]) -> tuple[str, ...]:
        return tuple([f"{f} is confirmed absent on their site" for f in sorted(self.absent & absent)]
                     + [f"{f} is already on their site" for f in sorted(self.present & present)])


#: Rules are deliberately few. Each one had to be justified by something an
#: audit actually observes; there is no rule for "they could use a mobile app".
RULES: tuple[Rule, ...] = (
    Rule("arabic", "Arabic experience", "Arabic experience", "website", "HIGH", "HIGH",
         why="Their site is English only in a market where a large share of buyers read Arabic "
             "first.",
         builds="An authored Arabic version with RTL layout and reciprocal hreflang — not a "
                "machine translation of the English.",
         user="An Arabic-first customer", interaction="Reads and enquires in Arabic",
         value="Reaches buyers the English-only site cannot address, and is indexable separately.",
         absent=frozenset({"arabic"})),
    Rule("reachability", "One-tap contact", "Landing experience", "website", "HIGH", "HIGH",
         why="The number is published but cannot be tapped, so a phone visitor has to copy it "
             "by hand.",
         builds="Tappable phone, WhatsApp and email on every page, plus a persistent contact "
                "affordance.",
         user="A visitor on a phone", interaction="Taps to call or message",
         value="Removes the step between wanting to enquire and enquiring.",
         absent=frozenset({"click_to_call"})),
    Rule("whatsapp", "WhatsApp as a channel", "Lead-generation tool", "marketing", "HIGH",
         "HIGH",
         why="WhatsApp is how business is actually transacted in this market, and the site "
             "does not offer it.",
         builds="A verified WhatsApp destination in the contact area and as a persistent "
                "affordance.",
         user="A buyer who does not want to fill in a form",
         interaction="Opens a chat with a pre-filled context line",
         value="Converts the visitors who will never complete a form.",
         absent=frozenset({"whatsapp"})),
    Rule("enquiry", "Structured enquiry", "Enquiry builder", "interaction", "HIGH", "MEDIUM",
         why="Quoting is bespoke, so the first exchange decides whether a quote can even be "
             "prepared.",
         builds="A short qualification flow that produces a structured brief instead of a "
                "free-text message.",
         user="Someone planning something specific",
         interaction="Answers a few questions and sends a brief",
         value="Arrives as a quotable brief rather than 'how much for catering?'.",
         absent=frozenset({"contact_form"})),
    Rule("proof", "Proof system", "Case-study system", "website", "HIGH", "HIGH",
         why="The work exists and is published, but a buyer cannot find or filter it.",
         builds="A structured, filterable index of the work they already publish — by sector, "
                "event type and service style.",
         user="A buyer deciding whether this supplier has done their kind of job",
         interaction="Filters to their own sector and sees comparable work",
         value="Answers the only question that matters before a first call.",
         present=frozenset({"social_proof"})),
    Rule("discovery", "Service finder", "Service finder", "discovery", "MEDIUM", "MEDIUM",
         why="The services exist as separate pages with no way to compare them.",
         builds="A guided route into the right service instead of an eleven-item menu.",
         user="A visitor who does not know the trade's vocabulary",
         interaction="Describes the need and is routed",
         value="Stops asking the visitor to classify themselves before they have seen anything.",
         present=frozenset({"services_navigation"})),
    Rule("editorial", "Editorial hub", "Editorial website", "website", "MEDIUM", "MEDIUM",
         why="They already write about their own trade; the writing is not presented as a "
             "product surface.",
         builds="A small, strong editorial section with real structure, imagery and internal "
                "links.",
         user="A buyer researching before enquiring",
         interaction="Reads, then enquires from the article",
         value="Indexable, topic-specific content that supports the enquiry rather than "
               "sitting beside it.",
         present=frozenset({"structured_data"})),
    # --- rules the research engine made possible -------------------------
    # Each of these needs evidence a single-page audit cannot produce: a crawl,
    # a sitemap, or a CMS content API.
    Rule("buried_work", "Work nobody can find", "Case-study system", "website",
         "HIGH", "HIGH",
         why="The work that wins this trade is published and unreachable — pages exist "
             "that nothing on the site links to.",
         builds="A filterable index built from the pages they already have, so the "
                "portfolio becomes navigable instead of merely present.",
         user="A buyer checking whether this supplier has done their kind of job",
         interaction="Filters to their own sector and sees comparable work",
         value="Turns existing, paid-for content into the thing that closes a first call.",
         absent=frozenset({"orphan_pages"}), present=frozenset({"portfolio_depth"})),
    Rule("blog_revival", "Dormant editorial", "Editorial website", "website",
         "MEDIUM", "HIGH",
         why="They started writing and stopped. The subjects were right; the habit "
             "did not survive.",
         builds="A small editorial section with real structure and imagery, and a route "
                "from each piece into the enquiry.",
         user="A buyer researching before committing",
         interaction="Reads, then enquires from the article",
         value="Recovers content already written instead of starting again.",
         absent=frozenset({"blog_cadence"}), present=frozenset({"blog"})),
    Rule("unillustrated", "Writing with no pictures", "Gallery", "website",
         "MEDIUM", "HIGH",
         why="They hold a large media library and publish articles carrying none of it.",
         builds="Illustrated articles and galleries drawn from the library they own.",
         user="A reader deciding whether to trust the work",
         interaction="Sees the work while reading about it",
         value="Uses an asset already paid for.",
         absent=frozenset({"blog_media"})),
    # The only rule that fires on a business having nothing rather than
    # something. `website` is CONFIRMED_ABSENT only when no site is recorded or
    # DNS reports no such host — a site that resolves and did not answer is
    # UNVERIFIED, and UNVERIFIED never reaches this set. See research/discovery.
    # "Landing experience" rather than a new product name: a first site for a
    # business with none is exactly that, and the product list is derived from
    # what the build queue can actually accept.
    Rule("no_website", "No website", "Landing experience", "website", "HIGH", "HIGH",
         why="The business has no website. Everything a search, a listing or a "
             "referral leads to belongs to somebody else.",
         builds="A site carrying the facts the business has supplied, and nothing "
                "it has not.",
         user="Anyone who looks the business up",
         interaction="Finds the business's own page rather than a directory entry",
         value="Gives the business somewhere of its own for every other channel "
               "to point at.",
         absent=frozenset({"website"})),
    Rule("performance", "Site speed", "Landing experience", "website", "HIGH", "HIGH",
         why="Pages are slow enough that visitors leave before they render.",
         builds="A rebuilt front end with the images and scripts brought under control.",
         user="Every visitor", interaction="Waits, or does not",
         value="Recovers the visitors lost before the page appears.",
         absent=frozenset({"page_speed"})),
    Rule("broken", "Broken links", "Website redesign", "website", "MEDIUM", "HIGH",
         why="Links on the site lead nowhere.",
         builds="The dead routes fixed or redirected.",
         user="A visitor following a link", interaction="Reaches the page they asked for",
         value="Stops a visit ending on an error page.",
         absent=frozenset({"broken_links"})),
    Rule("thin_content", "Pages with nothing on them", "Editorial website", "website",
         "LOW", "MEDIUM",
         why="A large share of published pages carry almost no words.",
         builds="The pages that matter written properly; the rest merged or removed.",
         user="A visitor who lands from search", interaction="Finds an answer",
         value="Gives search engines and readers something to work with.",
         absent=frozenset({"thin_pages"})),
    Rule("maps", "Findability", "Location finder", "discovery", "LOW", "MEDIUM",
         why="An address is published with no way to route to it.",
         builds="A map link and directions from the contact surface.",
         user="A visitor who needs to get there", interaction="Opens directions",
         value="Removes a small, certain drop-off.",
         absent=frozenset({"google_maps"})),
)


def derive(*, category: str, absent: frozenset[str], present: frozenset[str],
           extra: tuple[Opportunity, ...] = ()) -> tuple[Opportunity, ...]:
    """Rank the opportunities the evidence supports. Never invents one.

    `absent` must contain only CONFIRMED_ABSENT features — pass NOT_VERIFIED
    ones and the caller has turned a blind spot into a pitch.
    """
    found: list[Opportunity] = []
    for rule in RULES:
        if rule.categories and category not in rule.categories:
            continue
        if rule.absent and not rule.absent <= absent:
            continue
        if rule.present and not rule.present <= present:
            continue
        evidence = rule.evidence_for(absent, present)
        if not evidence:
            continue
        found.append(Opportunity(
            key=rule.key, name=rule.name, product=rule.product, family=rule.family,
            priority=rule.priority, confidence=rule.confidence, evidence=evidence,
            why=rule.why, builds=rule.builds, user=rule.user,
            interaction=rule.interaction, value=rule.value, demo=rule.demo))
    by_key = {o.key: o for o in found}
    by_key.update({o.key: o for o in extra})   # a researched opportunity wins over a derived one
    return tuple(sorted(by_key.values(), key=lambda o: o.rank))


def headline(opportunities: tuple[Opportunity, ...]) -> str:
    """The single strongest thing to open a conversation with."""
    return opportunities[0].name if opportunities else ""


# --- researched, not derived ----------------------------------------------
#
# A rule fires on a feature flag, which is all an automated audit can see. Real
# research sees more: that a caterer publishes thirty-two event pages carrying a
# hundred and seventy photographs and links to none of them from the homepage is
# not a feature flag, and no rule would ever produce it.
#
# These are hand-authored from a read of the business, every line citing what it
# was read from. They override a derived opportunity with the same key, because
# a researched one is strictly better evidenced.

RESEARCHED: dict[str, tuple[Opportunity, ...]] = {
    "ahscatering.com": (
        Opportunity(
            key="proof", name="Proof system", product="Case-study system", family="website",
            priority="HIGH", confidence="HIGH",
            evidence=("32 event pages carrying 170 photographs, read from their WordPress API",
                      "The homepage links to none of the 32",
                      "The 33 sampled event pages average under five words each — a title and "
                      "photographs, no date, guest count, service style or menu",
                      "Their About page names 12 brands in one sentence; a blog post names 5 "
                      "more and the Formula 1 Abu Dhabi Grand Prix 2025",
                      "The /reviews/ page is not in the navigation"),
            why="They have done the work that wins corporate catering — Nestlé, Porsche, Red "
                "Bull, Gucci, MBC, Pepsi, Formula 1 — and a buyer cannot find any of it. The "
                "proof exists as photographs with no facts attached.",
            builds="A filterable index of the events they already publish, each reduced to the "
                   "facts they publish, with the unpublished fields shown as unpublished so "
                   "they can see exactly what to add.",
            user="A corporate buyer deciding whether AHS has done their kind of event",
            interaction="Filters to their own sector and event type, and sees comparable work",
            value="Answers the question that decides a first call, from assets they already own.",
            demo="sample-ahs"),
        Opportunity(
            key="arabic", name="Arabic experience", product="Arabic experience",
            family="website", priority="HIGH", confidence="HIGH",
            evidence=('html lang="en-US" with no hreflang alternates',
                      "No language switcher and no translation plugin on any of the 12 pages",
                      "They publish an Arabic-theme dinner and Ramadan catering, so the "
                      "audience is one they already serve"),
            why="They sell Ramadan iftars and Arabic-theme dinners to a market that reads "
                "Arabic, entirely in English.",
            builds="An authored Arabic site with RTL layout and reciprocal hreflang.",
            user="An Arabic-first corporate or private host",
            interaction="Reads the work and enquires in Arabic",
            value="Addresses buyers the current site cannot, and indexes separately.",
            demo="sample-ahs"),
        Opportunity(
            key="enquiry", name="Event brief builder", product="Event planner",
            family="interaction", priority="HIGH", confidence="HIGH",
            evidence=("Their contact form already asks occasion, guests, timings, service "
                      "type, staffing, dietary needs and budget — 9 structured questions",
                      "No price is published anywhere, so every job is quoted bespoke"),
            why="They already know exactly what they need to quote. It is asked as a long form "
                "at the end instead of collected while the visitor reads.",
            builds="A qualification flow that assembles the brief as the visitor browses, so "
                   "the enquiry arrives quotable.",
            user="Someone planning a specific event",
            interaction="Sets occasion, guests, date and style, then sends the assembled brief",
            value="Turns 'how much for catering?' into a brief that can be priced.",
            demo="sample-ahs"),
        Opportunity(
            key="editorial", name="Editorial hub", product="Editorial website",
            family="website", priority="MEDIUM", confidence="HIGH",
            evidence=("4 posts, all published 2025-11-11, all filed Uncategorized",
                      "103–331 words each, and not one of them carries an image",
                      "Their media library holds 501 items",
                      "Their largest achievement — Formula 1 Abu Dhabi 2025 — is a 103-word "
                      "post"),
            why="They have the material and the subjects. The blog is a stub beside a "
                "501-item library.",
            builds="A small editorial section on the subjects they already chose, with real "
                   "structure, imagery and a route into the enquiry.",
            user="A buyer researching before committing",
            interaction="Reads, then enquires from the article",
            value="Indexable content on their own topics instead of four orphan posts.",
            demo="sample-ahs"),
        Opportunity(
            key="reachability", name="One-tap contact", product="Landing experience",
            family="website", priority="HIGH", confidence="HIGH",
            evidence=("No tel: or mailto: link anywhere on the site",
                      "Phone and email are plain text on all 12 pages",
                      "Their WhatsApp exists only inside a Click-to-Chat widget config"),
            why="Every contact route they publish requires the visitor to copy it by hand.",
            builds="Tappable phone, WhatsApp and email on every page and a persistent "
                   "affordance that does not cover the primary controls.",
            user="A visitor on a phone", interaction="Taps to call or message",
            value="Removes the step between wanting to enquire and enquiring.",
            demo="sample-ahs"),
    ),
}


def for_host(host: str, *, category: str, absent: frozenset[str],
             present: frozenset[str]) -> tuple[Opportunity, ...]:
    """Derived opportunities, with researched ones layered over the top."""
    key = (host or "").lower().removeprefix("www.").strip("/")
    return derive(category=category, absent=absent, present=present,
                  extra=RESEARCHED.get(key, ()))
