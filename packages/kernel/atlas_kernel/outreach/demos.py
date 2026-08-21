"""Which Qevik demo to show a prospect, and the words used to describe it.

**One registry, because three of them disagreed.** Demo choice used to live in
three places — a `SAMPLE_FOR` in the scorer, another in the control API, and a
separate `TRADE` dict supplying the noun the message used. They keyed on the
same category and had to agree by hand, so of course they stopped: professional
services mapped to Meridian, the real-estate sample, and the message described
it as "a property company". A staffing agency would have received a property
portal and a sentence about an industry it is not in. Fifty-seven prospects sit
in that category.

The fix is not a corrected row. A list maintained in parallel with another list
will drift again, so demo, industry, wording and relevance now come from a
single `Demo` object, and everything that renders or writes a message takes all
four from the same one.

Two rules the selection enforces:

**Relevance is asserted, never assumed.** A demo is offered only for a category
it genuinely serves. Where nothing serves the prospect's trade the answer is
`None` and the interface says so — an operator contacting them anyway is fine,
but the message must not claim we built something for a business like theirs.

**A sample is Qevik's own work.** Nothing here may describe one as client work,
a customer, or a site built for the prospect. Only a `demo-…` URL was built for
a specific business, and it was unsolicited.
"""

from __future__ import annotations

from dataclasses import dataclass, field

BASE = "https://sites.qevik.ai"


@dataclass(frozen=True)
class Demo:
    """One Qevik sample: what it is, who it suits, and how to describe it."""

    slug: str
    name: str
    #: What the sample itself is. Used in the card, never bent to fit a prospect.
    industry: str
    #: Prospect categories this genuinely suits. Empty means "never auto-select".
    serves: frozenset[str]
    #: The bare noun a message uses — "restaurant site", "B2B software". The article
    #: belongs to the sentence, not the data.
    #: Comes from the demo, not from a table keyed on the prospect's category —
    #: that separation is what produced "property company" for a staffing agency.
    trade: str
    #: What a visitor can actually do in it.
    shows: str
    #: Audit features it visibly demonstrates. Used to break ties, and to avoid
    #: raising a gap the thing we are linking to does not answer.
    demonstrates: frozenset[str] = field(default_factory=frozenset)
    #: Whether it exists in Arabic. Only the bilingual clinic vertical does; the
    #: hand-built portfolio samples are English-only.
    bilingual: bool = False

    @property
    def url(self) -> str:
        return f"{BASE}/{self.slug}/"


#: Every sample, and the only place any of them is described.
DEMOS: tuple[Demo, ...] = (
    Demo("sample", "the bilingual clinic sample", "Healthcare",
         frozenset({"health", "dental"}), "bilingual clinic site",
         "English and Arabic side by side, verified opening hours and tap-to-call",
         frozenset({"arabic", "click_to_call", "whatsapp", "opening_hours",
                    "google_maps", "structured_data", "contact_form"}), bilingual=True),
    Demo("sample-nar", "NAR", "Fine dining",
         frozenset({"food"}), "restaurant site",
         "a priced menu, a room gallery and a table request that says plainly it is not connected",
         frozenset({"contact_form", "opening_hours", "structured_data"})),
    Demo("sample-atelier", "Atelier", "Luxury salon",
         frozenset({"beauty"}), "salon site",
         "a treatment list with real durations and prices, and today's opening hours",
         frozenset({"opening_hours", "structured_data", "contact_form"})),
    Demo("sample-apex", "APEX Detailing", "Automotive",
         frozenset({"automotive"}), "car detailing site",
         "a four-step quote configurator that prices the job live",
         frozenset({"contact_form", "structured_data"})),
    Demo("sample-homefix", "HomeFix", "Home services",
         frozenset({"home"}), "home services site",
         "an estimator above the fold and two thumb-sized buttons pinned to the bottom of the phone",
         frozenset({"click_to_call", "whatsapp", "opening_hours", "contact_form"})),
    Demo("sample-meridian", "Meridian", "Real estate",
         frozenset({"real_estate", "property"}), "estate agency site",
         "property search with filters, a saved list and a call-back request",
         frozenset({"contact_form", "google_maps"})),
    Demo("sample-verdant", "Verdant", "Retail",
         frozenset({"retail"}), "retail site",
         "a filterable catalogue, live search and a working basket",
         frozenset({"contact_form", "structured_data"})),
    Demo("sample-ledgerloop", "LedgerLoop", "B2B software site",
         frozenset({"professional"}), "B2B software site",
         "a business site with the product itself running inside the page, and clear pricing",
         frozenset({"contact_form", "structured_data", "meta_description"})),
    Demo("sample-foundry", "Foundry", "AI and automation",
         frozenset({"technology", "ai"}), "workflow automation concept",
         "a workflow product with explicit states and the evidence behind each one",
         frozenset({"opening_hours", "structured_data"})),
    Demo("sample-pulse", "Pulse", "Fitness analytics",
         frozenset(), "training log app",
         "a product interface rather than a marketing page — charts, goals and a session history",
         frozenset()),
    Demo("sample-kilo", "Kilo", "Gym membership",
         frozenset({"fitness"}), "gym member app",
         "a member app: class booking that takes a seat, a workout runner and a membership card",
         frozenset({"opening_hours", "click_to_call"})),
    Demo("sample-carrot", "Carrot Dash", "Games",
         frozenset({"games"}), "browser game",
         "a genuinely playable one-button game — physics, rising difficulty and a kept score",
         frozenset()),
    # Recruitment is its own category, deliberately not folded into
    # "professional". A staffing business and an accountancy practice are both
    # professional services and need completely different products; collapsing
    # them is how the real-estate sample reached a staffing agency.
    Demo("sample-hire360", "HIRE360", "Hospitality recruitment",
         frozenset({"recruitment", "staffing", "hospitality"}), "hospitality recruitment platform",
         "a two-sided talent marketplace — search and filter candidates, open a profile, "
         "shortlist, compare people side by side, and raise a hiring brief",
         frozenset({"arabic", "click_to_call", "contact_form", "structured_data"}),
         bilingual=True),
    Demo("sample-wordrush", "Word Rush", "Education",
         frozenset({"education"}), "bilingual learning app",
         "an interface that switches language and direction at runtime, not at build time",
         frozenset({"arabic"}), bilingual=True),
)

BY_SLUG = {demo.slug: demo for demo in DEMOS}

#: Prospect category -> the demos that genuinely serve it, best first.
#: Derived from `serves` rather than written out again, so a demo cannot appear
#: here without also declaring the category on itself.
SERVES: dict[str, tuple[Demo, ...]] = {}
for _demo in DEMOS:
    for _category in _demo.serves:
        SERVES.setdefault(_category, ())
        SERVES[_category] = SERVES[_category] + (_demo,)


@dataclass(frozen=True)
class Selection:
    """The chosen demo and the argument for it — or an honest refusal."""

    demo: Demo | None
    #: A URL built for this business specifically. Beats every sample.
    prospect_url: str = ""
    reason: str = ""
    matched: bool = False

    @property
    def url(self) -> str:
        return self.prospect_url or (self.demo.url if self.demo else "")

    @property
    def kind(self) -> str:
        if self.prospect_url:
            return "prospect"
        return "sample" if self.demo else "none"

    @property
    def label(self) -> str:
        return {
            "prospect": "Prospect-specific unsolicited demo",
            "sample": "Relevant Qevik sample",
            "none": "No directly matched demo",
        }[self.kind]

    @property
    def bilingual(self) -> bool:
        """Does the thing we are linking to exist in Arabic?

        A prospect demo is rendered by the bilingual vertical and always does; a
        sample almost never. Raising a missing Arabic version and then linking
        an English-only page invites exactly the reply it deserves.
        """
        return bool(self.prospect_url) or bool(self.demo and self.demo.bilingual)


def select(category: str, *, prospect_demo_url: str = "",
           weaknesses: tuple[str, ...] = ()) -> Selection:
    """Pick what to show this prospect, and say why.

    A demo built for them wins outright. Otherwise the choice is limited to
    samples that serve their category — and among those, one that visibly
    demonstrates their strongest confirmed gap is preferred, because that is the
    thing the conversation is about.
    """
    if prospect_demo_url:
        return Selection(demo=None, prospect_url=prospect_demo_url, matched=True,
                         reason="Built for this business specifically, from their own "
                                "public listing details. Unsolicited, and not client work.")

    candidates = SERVES.get(category, ())
    if not candidates:
        return Selection(
            demo=None, matched=False,
            reason=(f"No Qevik sample is genuinely a {category or 'business of this kind'}. "
                    "Showing one anyway would mean claiming a relevance that does not exist."),
        )

    def rank(demo: Demo) -> tuple[int, int]:
        answered = len(demo.demonstrates & set(weaknesses))
        first = weaknesses[0] if weaknesses else ""
        return (-(first in demo.demonstrates), -answered)

    demo = sorted(candidates, key=rank)[0]
    answered = [w for w in weaknesses if w in demo.demonstrates]
    reason = (f"{demo.name} is Qevik's own {demo.industry} sample — the closest trade "
              f"Qevik has actually built. It shows {demo.shows}.")
    if answered:
        reason += (" It also demonstrates the exact thing missing from their site: "
                   + ", ".join(a.replace("_", " ") for a in answered) + ".")
    return Selection(demo=demo, matched=True, reason=reason)


def relevance(selection: Selection, category: str, weakness: str) -> str:
    """One or two sentences on why this demo suits this prospect.

    Deliberately does not claim the sample was built for them, and does not
    pretend their trade and the sample's are the same.
    """
    if not selection.demo and not selection.prospect_url:
        return ("Nothing in the portfolio is genuinely this trade. Contact them on the "
                "evidence alone, and do not imply a sample was built for a business like theirs.")
    if selection.prospect_url:
        return ("This page was generated for them from their own listing — name, address, "
                "phone and hours. Nothing on it is invented, and nobody asked for it.")
    demo = selection.demo
    gap = weakness.replace("_", " ") if weakness else ""
    lead = (f"{demo.name} is Qevik's own {demo.industry} sample — not client work. "
            f"It shows {demo.shows}.")
    if gap and weakness in demo.demonstrates:
        return lead + f" It also answers the gap confirmed on their site: {gap}."
    if gap:
        return lead + (f" It does not itself demonstrate {gap}, so raise that from the "
                       "evidence rather than from the link.")
    return lead


def leadable(selection: Selection, weaknesses: tuple[str, ...]) -> tuple[str, ...]:
    """The gaps this message may actually open with, given what it links to.

    Arabic is the most valuable gap in this market and it is confirmed for
    almost every prospect — but raising it and then linking an English-only
    sample invites exactly the reply it deserves. So it is dropped whenever the
    thing being linked has no Arabic version.

    Both the message generator and the dashboard's "strongest angle" read this,
    because a page that headlines one gap while its message opens with another
    leaves the operator deciding which to trust.
    """
    if selection.url and not selection.bilingual:
        return tuple(w for w in weaknesses if w != "arabic")
    return weaknesses


def article(noun: str) -> str:
    """"a" or "an", for a noun the registry supplies."""
    return "an" if noun[:1].lower() in "aeiou" else "a"
