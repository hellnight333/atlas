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

#: What a demo *is*, in ascending order of what it entitles a message to claim.
#: This is the honesty class of the artefact, and outreach language is derived
#: from it rather than written per prospect — "I built you a working example"
#: and "I put together a concept" are not interchangeable, and which one is true
#: is a property of the demo, not of how confident the sentence feels.
CLASSES: tuple[str, ...] = (
    "GENERIC_SAMPLE",          # ours, for a trade, nobody in particular
    "INDUSTRY_CONCEPT",        # ours, exploring how a trade could work
    "PROSPECT_INSPIRED",       # built from what a named business publishes, unsolicited
    "PROSPECT_REBUILD",        # their site, rebuilt — still unsolicited
    "CLIENT_APPROVED_REBUILD", # they asked for it
    # Ours, showing what Qevik can build. Deliberately last and deliberately
    # apart from the ladder above: the others describe how close a demo is to a
    # particular business, and this one is not about a business at all. A 3D
    # venue or a CRM shown to a caterer proves capability, not that they need it.
    "CAPABILITY_DEMO",
)

#: How a message may introduce each class. The strong verbs are unlocked by
#: approval, never by enthusiasm.
CLAIM: dict[str, str] = {
    "GENERIC_SAMPLE": "Ours, not a client's",
    "INDUSTRY_CONCEPT": "A concept we built to show how this could work",
    "PROSPECT_INSPIRED": "A concept I put together from what you publish — not commissioned "
                         "by you and not your site",
    "PROSPECT_REBUILD": "A working rebuild of your site, built unsolicited from what you "
                        "publish",
    "CLIENT_APPROVED_REBUILD": "The rebuild you approved",
    "CAPABILITY_DEMO": "Something we built to show what is possible — not for "
                       "your business and not a suggestion that you need it",
}

#: Verbs no message may use about a demo below the given class.
FORBIDDEN_ABOVE: dict[str, tuple[str, ...]] = {
    "GENERIC_SAMPLE": ("built you", "we built your", "your new site", "commissioned"),
    "INDUSTRY_CONCEPT": ("built you", "we built your", "your new site", "commissioned"),
    # "built you" is barred here too. Unsolicited work can honestly be described
    # as built *for* someone, but only once the artefact is their site rebuilt.
    # A concept assembled from what they publish is a concept, and saying it was
    # built for them is how a demo turns into an accidental claim of a
    # relationship that does not exist.
    "PROSPECT_INSPIRED": ("built you", "we built your", "your new site", "commissioned",
                          "you approved"),
    "PROSPECT_REBUILD": ("commissioned", "you approved"),
    "CLIENT_APPROVED_REBUILD": (),
    # The strictest of the lot. A capability demo may not be attached to the
    # prospect in any way, so the possessive is barred outright.
    "CAPABILITY_DEMO": ("built you", "we built your", "your new site", "commissioned",
                        "you approved", "for your business"),
}


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
    #: Whether it exists in Arabic. The vertical-generated local-business sites
    #: have an /ar/ route; HIRE360 and Word Rush switch in place; the rest of
    #: the hand-built samples are English-only.
    bilingual: bool = False
    #: What kind of thing this is, in the operator's words.
    product_type: str = "Website"
    #: The kind of business it suits, said plainly.
    business_class: str = ""
    #: The one capability worth leading with.
    primary: str = ""
    #: Everything else it genuinely shows.
    secondary: tuple[str, ...] = ()
    #: What a prospect may conclude from it.
    proves: str = ""
    #: The honest limit. Shown beside `proves`, never omitted.
    does_not_prove: str = ""
    #: What to walk somebody through, in order, if they reply.
    show_this: tuple[str, ...] = ()
    #: The honesty class. Defaults to the weakest claim on purpose: a demo that
    #: forgot to declare what it is must not be introduced as client work.
    classification: str = "GENERIC_SAMPLE"

    @property
    def url(self) -> str:
        return f"{BASE}/{self.slug}/"


#: Every sample, and the only place any of them is described.
DEMOS: tuple[Demo, ...] = (
    Demo("sample", "the bilingual clinic sample", "Healthcare",
         frozenset({"health", "dental"}), "bilingual clinic site",
         "English and Arabic side by side, verified opening hours and tap-to-call",
         frozenset({"arabic", "click_to_call", "whatsapp", "opening_hours",
                    "google_maps", "structured_data", "contact_form"}), bilingual=True,
         product_type='Website',
         business_class='a clinic or medical practice',
         primary='English and Arabic as two separately indexed sites',
         secondary=(
                    'verified opening hours with a today marker',
                    'tap-to-call and WhatsApp',
                    'LocalBusiness structured data',
         ),
         proves='Qevik ships a bilingual clinic site where the Arabic is authored and has its own canonical URL.',
         does_not_prove='The appointment form is a placeholder and books nothing.',
         show_this=(
                    'Open it on a phone',
                    'Switch to the Arabic version and check it is RTL, not mirrored',
                    "Show today's opening hours",
                    'Tap the call button',
                    'Open the appointment form and read the note saying it is not connected',
         ),
         classification="GENERIC_SAMPLE"),
    Demo("sample-nar", "NAR", "Fine dining",
         frozenset({"food"}), "restaurant site",
         "a priced menu, a room gallery and a table request that says plainly it is not connected",
         frozenset({"contact_form", "opening_hours", "structured_data"}),
         product_type='Website',
         business_class='a fine-dining restaurant',
         primary='an editorial page with no navigation at all — the menu is the site',
         secondary=(
                    'priced menu as a list, not cards',
                    'horizontal room gallery',
                    'table request that states it is not connected',
         ),
         proves='Qevik can build something that reads like a restaurant rather than a template.',
         does_not_prove='It has no Arabic version and takes no reservations.',
         show_this=(
                    'Open on desktop for the full-bleed opening',
                    'Scroll the priced menu',
                    'Swipe the room gallery',
                    'Open the table request',
         ),
         classification="INDUSTRY_CONCEPT"),
    Demo("sample-atelier", "Atelier", "Luxury salon",
         frozenset({"beauty"}), "salon site",
         "a treatment list with real durations and prices, and today's opening hours",
         frozenset({"opening_hours", "structured_data", "contact_form"}),
         product_type='Website',
         business_class='a premium salon or spa',
         primary='a treatment list with real durations and prices',
         secondary=(
                    "today's opening hours",
                    'a visit builder',
         ),
         proves='Qevik can present a service menu a customer can plan a visit from.',
         does_not_prove='It has no Arabic version and takes no appointments.',
         show_this=(
                    'Open the treatment list',
                    'Show durations and prices',
                    'Build a visit',
                    'Open it on a phone',
         ),
         classification="INDUSTRY_CONCEPT"),
    Demo("sample-apex", "APEX Detailing", "Automotive",
         frozenset({"automotive"}), "car detailing site",
         "a four-step quote configurator that prices the job live",
         frozenset({"contact_form", "structured_data"}),
         product_type='Web app',
         business_class='a detailing or workshop business',
         primary='a four-step quote configurator that prices the job live',
         secondary=(
                    'multi-select services with a running total',
                    'plan discount recalculates',
                    'step validation',
         ),
         proves='Qevik can replace “call for a price” with a number the customer gets themselves.',
         does_not_prove='It sends no quote and schedules nothing. No Arabic version.',
         show_this=(
                    'Start the configurator',
                    'Pick a vehicle',
                    'Add two services and watch the total',
                    'Change the plan and watch the discount',
                    'Open it on a phone',
         ),
         classification="INDUSTRY_CONCEPT"),
    Demo("sample-homefix", "HomeFix", "Home services",
         frozenset({"home"}), "home services site",
         "an estimator above the fold and two thumb-sized buttons pinned to the bottom of the phone",
         frozenset({"click_to_call", "whatsapp", "opening_hours", "contact_form"}),
         product_type='Website',
         business_class='a home-services company',
         primary='built for somebody on a phone at the worst moment',
         secondary=(
                    'estimator above the fold',
                    'two thumb buttons pinned to the bottom',
                    'FAQ and service area',
         ),
         proves='Qevik designs for the actual moment of need, not a desktop brochure.',
         does_not_prove='It dispatches nobody and takes no payment. No Arabic version.',
         show_this=(
                    'Open it on a phone first',
                    'Use the estimator',
                    'Show the pinned call and WhatsApp bar',
                    'Open the FAQ',
         ),
         classification="INDUSTRY_CONCEPT"),
    Demo("sample-meridian", "Meridian", "Real estate",
         frozenset({"real_estate", "property"}), "estate agency site",
         "property search with filters, a saved list and a call-back request",
         frozenset({"contact_form", "google_maps"}),
         product_type='Web app',
         business_class='an estate or letting agency',
         primary='property search with filters and a saved list',
         secondary=(
                    'detail overlay',
                    'call-back request',
                    'sidebar layout',
         ),
         proves='Qevik can build a searchable catalogue, not a page of listings.',
         does_not_prove='No live inventory, no Arabic version, no viewings booked.',
         show_this=(
                    'Filter by beds and area',
                    'Open a property detail',
                    'Save two properties',
                    'Open the saved list',
                    'Request a call back',
         ),
         classification="INDUSTRY_CONCEPT"),
    Demo("sample-verdant", "Verdant", "Retail",
         frozenset({"retail"}), "retail site",
         "a filterable catalogue, live search and a working basket",
         frozenset({"contact_form", "structured_data"}),
         product_type='E-commerce',
         business_class='a shop selling physical products',
         primary='a filterable catalogue with a working basket',
         secondary=(
                    'live text search',
                    'cart drawer with a running subtotal',
                    'detail overlay',
         ),
         proves='Qevik can build a storefront that behaves like one.',
         does_not_prove='No payment, no stock levels, no delivery pricing. No Arabic version.',
         show_this=(
                    'Filter the catalogue',
                    'Search for a product',
                    'Add two items to the basket',
                    'Open the cart and show the subtotal',
                    'Open it on a phone',
         ),
         classification="INDUSTRY_CONCEPT"),
    Demo("sample-ledgerloop", "LedgerLoop", "B2B software site",
         frozenset({"professional"}), "B2B software site",
         "a business site with the product itself running inside the page, and clear pricing",
         frozenset({"contact_form", "structured_data", "meta_description"}),
         product_type='SaaS',
         business_class='a B2B software or services company',
         primary='the product itself running inside the marketing page',
         secondary=(
                    'filterable approvals queue',
                    'billing period switch',
                    'pricing comparison',
         ),
         proves='Qevik can put a working product on the page instead of a screenshot of one.',
         does_not_prove='No accounts, no data, no billing. No Arabic version.',
         show_this=(
                    'Show the product embedded in the hero',
                    'Filter the approvals queue',
                    'Switch the billing period',
                    'Scroll the comparison table',
                    'Open it on a phone',
         ),
         classification="INDUSTRY_CONCEPT"),
    Demo("sample-foundry", "Foundry", "AI and automation",
         frozenset({"technology", "ai"}), "workflow automation concept",
         "a workflow product with explicit states and the evidence behind each one",
         frozenset({"opening_hours", "structured_data"}),
         product_type='Concept',
         business_class='an AI or automation business',
         primary='a workflow product with explicit states and the evidence behind each',
         secondary=(
                    'state transitions',
                    'evidence panel',
         ),
         proves='Qevik can express an operational workflow rather than a marketing claim about AI.',
         does_not_prove='It is a concept piece and says so. Nothing runs behind it.',
         show_this=(
                    'Walk the workflow states',
                    'Open the evidence behind a state',
                    'Point out that it is labelled a concept',
         ),
         classification="INDUSTRY_CONCEPT"),
    Demo("sample-pulse", "Pulse", "Fitness analytics",
         frozenset(), "training log app",
         "a product interface rather than a marketing page — charts, goals and a session history",
         frozenset(),
         product_type='Web app',
         business_class='a training or analytics product',
         primary='a product interface with no marketing page at all',
         secondary=(
                    'chart tabs that switch the series',
                    'goals',
                    'session history',
                    'sidebar collapses to a mobile rail',
         ),
         proves='Qevik builds software, not only websites.',
         does_not_prove='No accounts, no device sync, no stored workouts. No Arabic version.',
         show_this=(
                    'Switch the chart between volume and sessions',
                    'Show the goals',
                    'Scroll the session history',
                    'Open it on a phone and show the rail',
         ),
         classification="INDUSTRY_CONCEPT"),
    Demo("sample-kilo", "Kilo", "Gym membership",
         frozenset({"fitness"}), "gym member app",
         "a member app: class booking that takes a seat, a workout runner and a membership card",
         frozenset({"opening_hours", "click_to_call"}),
         product_type='Mobile app',
         business_class='a gym or membership business',
         primary='a member app where booking a class takes a seat',
         secondary=(
                    'workout runner with a rest timer',
                    'membership card',
                    'figures derived from what you did',
         ),
         proves='Qevik can build the operational side of a membership business, not just its brochure.',
         does_not_prove='No accounts, no real timetable, and the check-in code scans nothing.',
         show_this=(
                    'Book a class and watch a seat go',
                    'Start the session and tick a set',
                    'Show the rest timer',
                    'Finish and show the week move',
                    'Open the membership card',
         ),
         classification="INDUSTRY_CONCEPT"),
    Demo("sample-carrot", "Carrot Dash", "Games",
         frozenset({"games"}), "browser game",
         "a genuinely playable one-button game — physics, rising difficulty and a kept score",
         frozenset(),
         product_type='Game',
         business_class='a brand wanting something playable',
         primary='a genuinely playable one-button game',
         secondary=(
                    'variable-height jumps',
                    'rising difficulty',
                    'best score kept between visits',
         ),
         proves='Qevik makes things people play, not only pages they read.',
         does_not_prove='No leaderboards, no accounts, and it is not packaged for an app store.',
         show_this=(
                    'Play it',
                    'Show the score rising',
                    'Show it works on a phone with one thumb',
         ),
         classification="INDUSTRY_CONCEPT"),
    # Recruitment is its own category, deliberately not folded into
    # "professional". A staffing business and an accountancy practice are both
    # professional services and need completely different products; collapsing
    # them is how the real-estate sample reached a staffing agency.
    # The vertical-generated local-business sites. Structurally simpler than the
    # hand-built samples, and the only ones with a real Arabic route — which
    # makes them the better demo whenever the prospect's confirmed gap is
    # Arabic, the most common confirmed gap in the whole pool.
    Demo("sample-restaurant", "Sample Grill House", "Restaurant",
         frozenset({"food"}), "bilingual restaurant site",
         "a priced menu, tap-to-call, WhatsApp and directions — in English and Arabic",
         frozenset({"arabic", "click_to_call", "whatsapp", "google_maps",
                    "opening_hours", "structured_data", "contact_form"}), bilingual=True,
         product_type="Website", business_class="a restaurant or grill house",
         primary="the same page in English and Arabic, with its own Arabic URL",
         secondary=("priced menu by section", "tap-to-call and WhatsApp on a phone",
                    "a table request that says plainly it is not connected"),
         proves="Qevik ships a bilingual local-business site where the Arabic is authored, "
                "not machine-translated, and has its own indexable address.",
         does_not_prove="It takes no bookings and no payments.",
         show_this=("Open it on a phone", "Tap العربية and watch the whole page flip to RTL",
                    "Scroll the priced menu", "Tap the call button",
                    "Open the table request and read the note saying it is not connected"),
         classification="GENERIC_SAMPLE"),
    Demo("sample-cafe", "Sample Coffee Roasters", "Café and roastery",
         frozenset({"cafe"}), "bilingual café site",
         "a drinks list with prices, beans to take home, and an Arabic version",
         frozenset({"arabic", "click_to_call", "whatsapp", "google_maps",
                    "opening_hours", "structured_data"}), bilingual=True,
         product_type="Website", business_class="a café or roastery",
         primary="an authored Arabic version at its own address",
         secondary=("priced drinks list", "retail beans", "tap-to-call and directions"),
         proves="Qevik ships small bilingual sites that work on a phone.",
         does_not_prove="It has no ordering or delivery.",
         show_this=("Open it on a phone", "Switch to Arabic", "Scroll the drinks list",
                    "Tap WhatsApp"),
         classification="GENERIC_SAMPLE"),
    Demo("sample-salon", "Sample Beauty Studio", "Salon",
         frozenset({"beauty"}), "bilingual salon site",
         "a treatment list with prices and durations, in English and Arabic",
         frozenset({"arabic", "click_to_call", "whatsapp", "google_maps",
                    "opening_hours", "structured_data"}), bilingual=True,
         product_type="Website", business_class="a hair, skin or nails salon",
         primary="an authored Arabic version at its own address",
         secondary=("treatments with durations and prices", "tap-to-call and WhatsApp"),
         proves="Qevik ships a bilingual salon site a customer can use on a phone.",
         does_not_prove="It takes no appointments.",
         show_this=("Open it on a phone", "Switch to Arabic", "Scroll the treatment list",
                    "Tap the call button"),
         classification="GENERIC_SAMPLE"),
    Demo("sample-detailing", "Sample Auto Detailing", "Car detailing",
         frozenset({"automotive"}), "bilingual detailing site",
         "priced packages, tap-to-call and directions, in English and Arabic",
         frozenset({"arabic", "click_to_call", "whatsapp", "google_maps",
                    "opening_hours", "structured_data"}), bilingual=True,
         product_type="Website", business_class="a detailing or car-care workshop",
         primary="an authored Arabic version at its own address",
         secondary=("priced packages", "tap-to-call and WhatsApp", "directions"),
         proves="Qevik ships a bilingual workshop site that works on a phone.",
         does_not_prove="It has no quoting engine — APEX is the sample for that.",
         show_this=("Open it on a phone", "Switch to Arabic", "Scroll the packages",
                    "Tap the call button"),
         classification="GENERIC_SAMPLE"),
    Demo("sample-property", "Sample Property", "Property",
         frozenset({"real_estate", "property"}), "bilingual property site",
         "listings, service pages and a call-back request, in English and Arabic",
         frozenset({"arabic", "click_to_call", "whatsapp", "google_maps",
                    "opening_hours", "structured_data"}), bilingual=True,
         product_type="Website", business_class="a small property or letting agency",
         primary="an authored Arabic version at its own address",
         secondary=("service pages", "call-back request", "tap-to-call"),
         proves="Qevik ships a bilingual property site that works on a phone.",
         does_not_prove="It has no search or saved list — Meridian is the sample for that.",
         show_this=("Open it on a phone", "Switch to Arabic", "Read the service pages",
                    "Tap the call button"),
         classification="GENERIC_SAMPLE"),
    # Built from one real business's published information, for that business.
    # `serves` is empty on purpose: this is not a category demo and must never be
    # auto-selected for anybody else. It reaches AHS through their own
    # prospect demo link, not through category matching.
    Demo("sample-ahs", "AHS — Beyond Catering", "Event catering",
         frozenset(), "event catering concept",
         "a persistent event brief that filters the page as you set occasion, guests, "
         "date and style, with no prices anywhere because AHS quotes bespoke",
         frozenset({"arabic", "click_to_call", "contact_form", "structured_data"}),
         product_type="Concept", business_class="a full-service event caterer",
         primary="an event brief that writes the enquiry while you read",
         secondary=("two-arm corporate/private structure taken from their own site",
                    "live stations as a cinematic sequence, not a service card",
                    "EATLUX as its own chapter",
                    "their five real capability statements",
                    "gallery filtered by the occasion you chose"),
         proves="Qevik studies a specific business and builds around how it actually "
                "operates, rather than fitting it to an industry template.",
         does_not_prove="It is unsolicited, it is not AHS's website, no AHS photograph is "
                        "reproduced in it, and the enquiry submits nowhere.",
         show_this=("Set an occasion in the brief and watch the gallery filter",
                    "Set 400+ guests and watch Capacity come forward",
                    "Scroll the live-station sequence",
                    "Show the enquiry already written from what you chose",
                    "Open it on a phone and pull up the brief bar"),
         classification="PROSPECT_INSPIRED"),
    Demo("sample-hire360", "HIRE360", "Hospitality recruitment",
         frozenset({"recruitment", "staffing", "hospitality"}), "hospitality recruitment platform",
         "a two-sided talent marketplace — search and filter candidates, open a profile, "
         "shortlist, compare people side by side, and raise a hiring brief",
         frozenset({"arabic", "click_to_call", "contact_form", "structured_data"}),
         bilingual=True,
         product_type='Marketplace',
         business_class='a recruitment or staffing business',
         primary='a two-sided talent marketplace with real search and shortlisting',
         secondary=(
                    'six composable filters and sorting',
                    'candidate profiles with a timeline',
                    'side-by-side comparison',
                    'a seven-step hiring brief',
                    'employer and candidate modes',
                    'full Arabic RTL',
         ),
         proves='Qevik can build a working digital product around a hiring workflow, not a brochure in front of one.',
         does_not_prove="Every candidate is invented. Nothing submits, sends or contacts anybody, and it is not a rebuild of anyone's existing platform.",
         show_this=(
                    'Open candidate search',
                    'Filter to a role and a city',
                    'Change the location on the map',
                    'Open a candidate profile',
                    'Shortlist two people',
                    'Compare them side by side',
                    'Switch to candidate mode',
                    'Switch to Arabic and show the RTL layout',
                    'Open it on a phone',
         ),
         classification="PROSPECT_INSPIRED"),
    Demo("sample-wordrush", "Word Rush", "Education",
         frozenset({"education"}), "bilingual learning app",
         "an interface that switches language and direction at runtime, not at build time",
         frozenset({"arabic"}), bilingual=True,
         product_type='Mobile app',
         business_class='a business needing both languages',
         primary='an interface that switches language and direction at runtime',
         secondary=(
                    'timed drill with lives and streaks',
                    'searchable word list with mastery',
                    'progress history',
         ),
         proves='Qevik can build one product that works properly in Arabic and English.',
         does_not_prove='No accounts, no audio, and it is not packaged for an app store.',
         show_this=(
                    'Play a round',
                    'Tap عربي and watch the whole interface flip',
                    'Open the word list and search in Arabic',
                    'Show the progress screen',
         ),
         classification="INDUSTRY_CONCEPT"),
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


# --- the sales brief -------------------------------------------------------

def why_this_demo(selection: Selection, category: str, weakness: str = "") -> dict:
    """Everything the operator needs to justify this demo, out loud, to a stranger.

    Assembled from the selected `Demo` and nothing else, so the argument on the
    dashboard, the sentence in the message and the URL in both are the same
    object's fields. The `does_not_claim` line is not optional: a demo shown
    without its limits is how a concept turns into a promise.
    """
    if selection.prospect_url:
        return {
            "chose": ("This page was generated for them specifically, from their own public "
                      "listing — name, address, phone and opening hours."),
            "demonstrates": ("An authored Arabic version alongside the English one",
                             "Verified opening hours and a tap-to-call number",
                             "A layout built for a phone first"),
            "relevant": ("It is their own business on the page, so there is nothing to "
                         "imagine — they can check every detail against reality."),
            "does_not_claim": ("Nobody asked for it. It is unsolicited work, it is not their "
                               "website, and the appointment form on it books nothing."),
        }
    demo = selection.demo
    if demo is None:
        return {
            "chose": ("Nothing in the portfolio is genuinely this trade, so no demo is "
                      "attached. Contact them on the evidence alone."),
            "demonstrates": (),
            "relevant": "",
            "does_not_claim": ("Do not imply a sample was built for a business like theirs — "
                               "none was."),
        }
    answered = weakness and weakness in demo.demonstrates
    return {
        "chose": (f"They are {demo.business_class}. {demo.name} is Qevik's own "
                  f"{demo.industry.lower()} {demo.product_type.lower()} — it shows "
                  f"{demo.primary}."),
        "demonstrates": (demo.primary,) + demo.secondary,
        "relevant": (
            f"It answers the gap confirmed on their own site: {weakness.replace('_', ' ')}."
            if answered else
            (f"Their confirmed gap is {weakness.replace('_', ' ')}, which this sample does not "
             f"itself demonstrate — raise that from the evidence, and use the demo to show "
             f"what Qevik builds." if weakness else
             "No weakness was confirmed, so this is a capability conversation rather than a "
             "problem one.")),
        # The generic disclaimer is appended only when the demo's own limits do
        # not already cover it, so the sentence does not say the same thing twice.
        "does_not_claim": (demo.does_not_prove if "rebuild" in demo.does_not_prove
                           else demo.does_not_prove
                           + " It is a Qevik sample, not client work, and not a rebuild of "
                             "anything they already run."),
    }


def show_this(selection: Selection) -> tuple[str, ...]:
    """The order to walk somebody through it, if they reply."""
    if selection.prospect_url:
        return ("Open it on their phone", "Switch to the Arabic version",
                "Check their own opening hours and phone number are right",
                "Point out the appointment form is a placeholder and says so")
    return selection.demo.show_this if selection.demo else ()


def claim(demo: Demo | None) -> str:
    """The sentence a message may use to introduce this demo."""
    return CLAIM.get(demo.classification, "") if demo is not None else ""


def overclaims(text: str, demo: Demo | None) -> list[str]:
    """Phrases in this text that claim more than the demo's class allows."""
    if demo is None:
        return []
    lowered = text.lower()
    return [phrase for phrase in FORBIDDEN_ABOVE.get(demo.classification, ())
            if phrase in lowered]
