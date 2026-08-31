"""Email addresses a business actually published, read from a page already fetched.

412 businesses and not one email address. No source collects one: the Places
field mask has no email field because the API does not return one, OpenStreetMap
rarely records it, and the audit read every homepage and kept none of it.

## Where the content comes from

The audit already fetches the homepage and holds the HTML in memory to run
`audit_html` over it. This reads the same string in the same pass. **No
additional browsing, and no second scraper**: the audited page is not stored, so
there is nothing to re-read later, and fetching it again purely to hunt for
contacts would be a second visit to somebody's site for our benefit.

## What it will not do

**It never derives an address.** `info@` a domain is a guess that lands in a
stranger's inbox or bounces, and once written into a message the guess is
indistinguishable from a fact. `verified_recipient` already refuses derived
addresses; this agrees with it rather than restating the rule.

Only what the page states. A `mailto:` link is the strongest form of that — the
business built a control whose entire purpose is to be written to — and a plain
address in the page text is the weaker form, recorded with that distinction
kept.

## Business address or somebody's

A role address (`info@`, `bookings@`, `sales@`) is a channel a business
published for the purpose. A personal-looking one (`ahmed.hassan@`) may be a
named employee, and writing to that is a different act with a different footing.

Both are recorded; **only role addresses are promoted to contactability.** The
rest are surfaced for a policy decision rather than used, because whether to
write to a named person at a business is DQ-005's territory and not this
module's.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

#: The same shape `outreach/preparation.py` validates a recipient against.
#: Deliberately conservative — a string that merely looks addressy is not one.
EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

#: `mailto:` links, which is the form that says "write to us here".
MAILTO = re.compile(r"""mailto:\s*([^"'?>\s]+)""", re.I)

#: Local parts that name a function rather than a person. A business published
#: these to be written to; that is what they are for.
ROLE_PARTS: frozenset[str] = frozenset({
    "info", "contact", "hello", "hi", "enquiries", "enquiry", "inquiries",
    "inquiry", "sales", "bookings", "booking", "reservations", "reservation",
    "admin", "office", "support", "help", "team", "mail", "email", "general",
    "reception", "frontdesk", "front-desk", "customerservice", "service",
    "marketing", "orders", "order", "appointments", "appointment", "clinic",
    "shop", "store", "care", "hr", "careers", "jobs", "accounts", "billing",
})

#: Addresses that belong to a platform rather than the business. Writing to one
#: reaches a tools vendor, not the company whose site published it.
NOT_THE_BUSINESS: tuple[re.Pattern[str], ...] = (
    # The *reserved* placeholder domains, named exactly. An earlier version
    # matched any domain beginning "example" and rejected `example.ae`, which
    # is an ordinary registrable UAE domain a real business could hold —
    # a filter that silently discards real addresses is worse than none.
    # Template placeholders shipped with a theme. `you@company.com` reached a
    # real measurement run and was counted as two businesses' contact, because
    # two sites shipped the same untouched template.
    re.compile(r"@(example|yourdomain|yoursite|domain|company|mysite|website"
               r"|site|yourcompany|email)\.(com|org|net|edu)$", re.I),
    re.compile(r"^(you|youremail|your-email|name|username|firstname)@", re.I),
    re.compile(r"@[^@]*\.(test|localhost|invalid|example)$", re.I),
    re.compile(r"@(sentry|wixpress|godaddy|squarespace|shopify|wordpress)\.", re.I),
    re.compile(r"^(no-?reply|do-?not-?reply|postmaster|abuse|webmaster)@", re.I),
    re.compile(r"\.(png|jpg|jpeg|gif|webp|svg|css|js)$", re.I),
    re.compile(r"^[0-9a-f]{16,}@", re.I),          # tracking and message ids
)


class ContactType(StrEnum):
    """What sort of contact this is. **Never inferred from the domain alone.**

    An earlier version had three kinds and decided them from the local part,
    which threw away real inventory: an owner-operated business whose published
    contact is `ahmed@gmail.com`, presented as "Ahmed — Owner", is a business
    contact. Judging that by its domain would discard exactly the small
    businesses this engine exists to find.

    So the type comes from what the page says *around* the address — a role, a
    name, a contact heading, a testimonial — and the domain is not consulted.
    """

    #: A function the business published to be written to: `info@`, `bookings@`.
    BUSINESS = "business_email"
    #: A named person the business presents as a contact, owner or manager.
    #: The mailbox may be anywhere; what matters is that the page presents them
    #: as the way to reach the business.
    INDIVIDUAL = "individual_business_contact"
    #: An individual-looking address whose relationship to the business cannot
    #: be established — an address in a testimonial, a comment, a byline.
    PERSONAL = "personal_or_ambiguous"
    #: Present, and nothing on the page says what it is.
    UNKNOWN = "unknown"


class Presented(StrEnum):
    """How the page offered it. Provenance, not decoration."""

    #: A `mailto:` link — a control whose purpose is to be written to.
    MAILTO = "mailto"
    #: Present in the page text.
    TEXT = "text"


@dataclass(frozen=True)
class ObservedAddress:
    """One address a page stated, how it stated it, and what it said about it.

    **Not a party.** `test_one_customer_entity` refused an earlier version
    called `Contact`, and was right to: that is the head noun of a second
    customer entity, and a factory that grows its own is how one company
    becomes a Prospect here and a Client there. This is an observation about a
    page. The company it belongs to is `atlas_businesses.id`.

    Every field is provenance. A reviewer deciding whether to write to
    `ahmed@gmail.com` needs to see that the page said "Ahmed — Owner" beside
    it, on which page, and how it was read — not a verdict.
    """

    address: str
    contact_type: ContactType
    presented: Presented
    #: The page it was read from, so the claim is checkable.
    source_url: str
    #: What the page displayed beside it. Recorded, never used to construct
    #: anything: a name is evidence about a page, not a fact about a person.
    displayed_name: str = ""
    displayed_role: str = ""
    #: When the page was read.
    observed_at: str = ""

    @property
    def associated_with_business(self) -> bool:
        """Whether the page presents this as a way to reach *this* business.

        A testimonial address appears on the business's site and is not the
        business's contact. The distinction is the whole point of reading
        context rather than the domain.
        """
        return self.contact_type in (ContactType.BUSINESS,
                                     ContactType.INDIVIDUAL)

    @property
    def usable(self) -> bool:
        """Whether this may become the business's contactability.

        A business channel or a named person the business presents as its
        contact. An address whose relationship to the business could not be
        established is recorded and never promoted — using it would decide
        DQ-005 quietly.
        """
        return self.associated_with_business

    def summary(self) -> dict:
        return {"address": self.address,
                "contact_type": self.contact_type.value,
                "presented": self.presented.value,
                "source_url": self.source_url,
                "displayed_name": self.displayed_name,
                "displayed_role": self.displayed_role,
                "associated_with_business": self.associated_with_business,
                "observed_at": self.observed_at,
                "usable": self.usable}


def normalise(address: str) -> str:
    """One spelling per address, before anything compares two.

    Lowercased and trimmed of the punctuation that survives an HTML scrape.
    The local part is *not* otherwise altered: stripping dots or `+tags` would
    merge addresses that some providers treat as distinct, which is a guess
    about somebody's mail server.
    """
    text = (address or "").strip().strip(".,;:<>()[]\"'").lower()
    if text.startswith("mailto:"):
        text = text[len("mailto:"):]
    return text.split("?")[0].strip()


#: Words that present somebody as speaking for the business.
ROLE_TITLES: tuple[str, ...] = (
    "owner", "founder", "co-founder", "proprietor", "partner", "director",
    "managing director", "manager", "general manager", "principal", "ceo",
    "cto", "coo", "president", "head of", "supervisor", "in charge",
    "sales manager", "branch manager", "practice manager", "dentist", "doctor",
    "consultant", "specialist",
)

#: Words that mean "this is how you reach us".
CONTACT_HEADINGS: tuple[str, ...] = (
    "contact us", "contact", "get in touch", "reach us", "reach out",
    "email us", "write to us", "enquiries", "enquiry", "inquiries",
    "book now", "booking", "appointment", "our team", "meet the team",
    "head office", "customer service", "support",
)

#: Words that mean the address belongs to somebody talking *about* the
#: business rather than speaking for it.
NOT_SPEAKING_FOR = (
    "testimonial", "review", "reviewed by", "comment", "posted by", "wrote",
    "says:", "rating", "feedback from", "guest post", "author",
)

#: How much text either side of an address counts as its context. Wide enough
#: to catch "Ahmed — Owner" on the line above; narrow enough that a heading
#: three sections away is not read as this address's label.
CONTEXT = 220


def _around(html: str, address: str) -> str:
    """The words either side of this address, as a reader would see them.

    The window is taken from the **raw HTML** and the tags stripped afterwards,
    not the other way round. A `mailto:` address lives inside an attribute, so
    stripping tags first removes it entirely — an earlier version did that and
    classified "Ahmed — Owner" with a `mailto:ahmed@gmail.com` beside it as
    `UNKNOWN`, which is exactly the small-business contact this is for.

    The raw window is wider than the visible one it becomes, because markup
    inflates the distance between things a reader sees as adjacent.
    """
    where = html.lower().find(address.lower())
    if where < 0:
        return ""
    window = html[max(0, where - CONTEXT * 4):where + len(address) + CONTEXT * 4]
    without_scripts = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", window)
    stripped = re.sub(r"(?s)<[^>]+>", " ", without_scripts)
    return re.sub(r"\s+", " ", stripped.replace("&mdash;", "—").replace("&amp;", "&"))


def _named_person(context: str, address: str) -> str:
    """A displayed name presented with this address, if the page shows one.

    Two capitalised words near the address. Deliberately shallow: a name is
    recorded as provenance, never used to construct anything, and a confident
    parser here would be inventing people.
    """
    before = context[:context.lower().find(address.lower())] or context
    found = re.findall(r"\b([A-Z][a-z]{1,15}(?:\s+[A-Z][a-z]{1,15}){0,2})\b",
                       before[-120:])
    # A role is not a name. "Ahmed Hassan — Owner" must record the person, and
    # an earlier version returned "Owner" because it was nearer the address.
    titles = {word for title in ROLE_TITLES for word in title.split()}
    skip = titles | {"contact", "email", "phone", "call", "about", "our", "the",
                     "we", "home", "us", "get", "touch", "reach", "write",
                     "book", "now", "team", "meet", "office", "head"}
    for candidate in reversed(found):
        words = [word.lower() for word in candidate.split()]
        if any(word in skip for word in words):
            continue
        return candidate
    return ""


def _role_shown(context: str) -> str:
    lowered = context.lower()
    for title in sorted(ROLE_TITLES, key=len, reverse=True):
        if title in lowered:
            return title
    return ""


def classify(address: str, *, context: str = "") -> tuple[ContactType, str, str]:
    """`(type, displayed_name, displayed_role)` for one observed address.

    **The domain is never consulted.** `ahmed@gmail.com` presented as "Ahmed —
    Owner" is a business contact; `ahmed@thecompany.ae` quoted in a customer
    testimonial is not. Only what the page says around it decides.
    """
    local = address.split("@", 1)[0].lower()
    role_local = re.sub(r"[^a-z]", "", local) in ROLE_PARTS or local in ROLE_PARTS
    lowered = context.lower()

    # Somebody talking *about* the business, not for it. Checked first: a
    # testimonial can sit inside a page that also says "contact us".
    if any(word in lowered for word in NOT_SPEAKING_FOR) and not role_local:
        # No displayed name recorded. Nothing here is being presented as a
        # contact, and a name guessed out of review prose would be a claim
        # about a person written into provenance.
        return ContactType.PERSONAL, "", ""

    if role_local:
        return ContactType.BUSINESS, "", ""

    role = _role_shown(context)
    name = _named_person(context, address)
    if role:
        return ContactType.INDIVIDUAL, name, role
    if any(heading in lowered for heading in CONTACT_HEADINGS):
        # Offered as the way to reach the business, with no role stated. A
        # person if the page names one, otherwise the business's own channel.
        return (ContactType.INDIVIDUAL if name else ContactType.BUSINESS), name, ""
    if not context:
        return ContactType.UNKNOWN, "", ""
    return ContactType.PERSONAL, "", ""


def _is_the_business(address: str) -> bool:
    return not any(pattern.search(address) for pattern in NOT_THE_BUSINESS)


def observed(html: str, *, url: str, at: str = "") -> tuple[ObservedAddress, ...]:
    """Every address this page states, with what the page said about each.

    `mailto:` beats page text when the same address appears as both: the link
    is the stronger evidence that it was published to be written to, and the
    provenance should record the stronger form.

    Classification reads the *visible* text around each address, not the
    markup, because a name and an address separated by two hundred characters
    of tags are adjacent to every reader.
    """
    found: dict[str, ObservedAddress] = {}

    def add(address: str, presented: Presented) -> None:
        kind, name, role = classify(address, context=_around(html or "", address))
        found[address] = ObservedAddress(
            address=address, contact_type=kind, presented=presented,
            source_url=url, displayed_name=name, displayed_role=role,
            observed_at=at)

    for raw in MAILTO.findall(html or ""):
        address = normalise(raw)
        if not address or not EMAIL.fullmatch(address) or not _is_the_business(address):
            continue
        add(address, Presented.MAILTO)

    for raw in EMAIL.findall(html or ""):
        address = normalise(raw)
        if not address or address in found or not _is_the_business(address):
            continue
        add(address, Presented.TEXT)

    return tuple(sorted(found.values(),
                        key=lambda c: (c.presented is not Presented.MAILTO,
                                       not c.usable,
                                       c.contact_type is not ContactType.BUSINESS,
                                       c.address)))


def contactable_at(contacts: tuple[ObservedAddress, ...]) -> str:
    """The one address a business becomes contactable at, or `""`.

    The first usable one in the order `observed` returns: a `mailto:` role
    address before a role address in text, and nothing at all when the page
    published only personal or ambiguous ones. Choosing between two role
    addresses is not a judgement worth making — both were published for the
    purpose — so the ordering is stated rather than scored.
    """
    for contact in contacts:
        if contact.usable:
            return contact.address
    return ""


__all__ = ["CONTACT_HEADINGS", "CONTEXT", "EMAIL", "MAILTO",
           "NOT_SPEAKING_FOR", "NOT_THE_BUSINESS", "ROLE_PARTS", "ROLE_TITLES",
           "ContactType", "ObservedAddress", "Presented", "classify",
           "contactable_at", "normalise", "observed"]
