"""What a site says, and where every word of it came from.

The invariant this file exists to enforce: **no fabricated business facts on a
published site.**

M014's rule is that Atlas may not make a claim about a business it cannot
substantiate. Publishing *as* that business is strictly worse. An invented
opening time, a made-up service list or a plausible-sounding address is wrong in
the customer's own voice, on their own domain, and they carry the consequences —
a customer turns up at 8pm because the site Atlas wrote said the shop was open.

Two mechanisms, and they are different in kind:

**Facts carry a source, and there is no source meaning "a model wrote it."**
``FactSource`` has no ``GENERATED`` member. That does not stop a determined
caller from attributing an invention to the operator, and it is not meant to —
it makes every fact *attributable*, so a wrong one leads back to whoever or
whatever supplied it instead of dissolving into the output.

**Absent facts are absent from the page.** No placeholders, no "Call us today!",
no filler where a phone number should be. This is the mechanism that actually
does the work, because the tempting failure is not inventing an address — it is
padding a thin page with confident-sounding copy that asserts nothing anyone
supplied. A site with three facts on it is a small site.

Prose is separate and may be written, but it is rendered only where prose
belongs and cannot introduce a fact of its own.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FactSource(StrEnum):
    """Where a fact came from.

    **Deliberately has no ``GENERATED`` member.** A fact about someone's business
    that originates in a language model is not a fact, and the absence of the
    option is the point: there is nothing to select when the honest answer is
    "Atlas made it up".
    """

    #: Ayoub or his team typed it in.
    OPERATOR = "operator"
    #: The business itself supplied it — a form, an email, a phone call.
    CUSTOMER = "customer"
    #: Read from the ``Business`` record Atlas already holds.
    BUSINESS_RECORD = "business_record"
    #: Observed on their existing site or listing, with evidence behind it.
    OBSERVED = "observed"


class Fact(BaseModel):
    """One assertion about the business, and its provenance.

    Immutable, because a fact that can be edited after the source is recorded is
    a fact whose source no longer means anything.
    """

    model_config = ConfigDict(frozen=True)

    value: str
    source: FactSource
    #: Where exactly — "phone call 2026-08-01", "their Google listing". Not
    #: required, and worth filling in: it is the difference between an
    #: attributable claim and a shrug.
    note: str = ""

    @field_validator("value")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError(
                "a fact must say something — an empty fact renders as an empty "
                "promise on someone's website"
            )
        return value.strip()


class Prose(BaseModel):
    """Written copy, which may be generated.

    Kept distinct from ``Fact`` so the two can never be confused at a call site.
    Prose describes; it does not assert hours, prices or addresses. What stops it
    doing so is that facts are rendered from ``Fact`` fields and prose is
    rendered where prose goes — a paragraph cannot become the opening hours by
    being written confidently.
    """

    model_config = ConfigDict(frozen=True)

    text: str
    #: What wrote it. ``"operator"`` when a person did, a model name otherwise.
    written_by: str = "operator"

    @field_validator("text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("prose must say something")
        return value.strip()


class Service(BaseModel):
    """Something the business does.

    The name is a fact — it is a claim about what they offer. The description is
    prose and optional, because a service with no description is a service, and
    inventing one to fill the space is exactly the failure this module exists to
    prevent.
    """

    model_config = ConfigDict(frozen=True)

    name: Fact
    description: Prose | None = None


class OpeningHours(BaseModel):
    """When the business is open.

    Days are facts individually, so a business that supplied only its weekday
    hours publishes only its weekday hours. Guessing the weekend is the exact
    shape of harm this file is about: a customer drives across town on a Sunday.
    """

    model_config = ConfigDict(frozen=True)

    #: Day name -> hours, e.g. ``{"Monday": Fact("9:00 – 18:00", CUSTOMER)}``.
    #: Missing days are missing, never assumed closed and never assumed open.
    days: dict[str, Fact] = Field(default_factory=dict)
    note: Prose | None = None

    @property
    def is_empty(self) -> bool:
        return not self.days


class ContactDetails(BaseModel):
    model_config = ConfigDict(frozen=True)

    phone: Fact | None = None
    email: Fact | None = None
    address: Fact | None = None
    whatsapp: Fact | None = None

    @property
    def is_empty(self) -> bool:
        return not any([self.phone, self.email, self.address, self.whatsapp])


class SiteContent(BaseModel):
    """Everything a site says, medium-agnostic.

    Carries no HTML, no theme, no colours and no layout — the same separation
    M013 keeps between a Script and a Rendition, for the same reason: this
    content should be renderable as a one-page site, a multi-page site or a
    printed sheet without any of it changing.

    Every optional field is genuinely optional. A site generated from a business
    name and a phone number is a page with a name and a phone number on it, and
    that is a better outcome than a page padded with copy nobody stands behind.
    """

    model_config = ConfigDict(frozen=True)

    #: The only required fact. A site with no business name is not a site.
    business_name: Fact
    tagline: Fact | None = None
    #: One or two sentences. Prose, so it may be written rather than supplied.
    about: Prose | None = None
    services: list[Service] = Field(default_factory=list)
    hours: OpeningHours = Field(default_factory=OpeningHours)
    contact: ContactDetails = Field(default_factory=ContactDetails)
    #: City, emirate, country — whatever was actually supplied.
    location: Fact | None = None
    #: Year founded, licence number, anything else attributable.
    extras: dict[str, Fact] = Field(default_factory=dict)

    @property
    def facts(self) -> list[Fact]:
        """Every fact on the site, for auditing what is being claimed."""
        collected: list[Fact] = [self.business_name]
        for optional in (self.tagline, self.location):
            if optional is not None:
                collected.append(optional)
        collected.extend(service.name for service in self.services)
        collected.extend(self.hours.days[day] for day in sorted(self.hours.days))
        for detail in (
            self.contact.phone,
            self.contact.email,
            self.contact.address,
            self.contact.whatsapp,
        ):
            if detail is not None:
                collected.append(detail)
        collected.extend(self.extras[key] for key in sorted(self.extras))
        return collected

    @property
    def sources(self) -> set[FactSource]:
        return {fact.source for fact in self.facts}

    def sourced_from(self, source: FactSource) -> list[Fact]:
        return [fact for fact in self.facts if fact.source is source]
