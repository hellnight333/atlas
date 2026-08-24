"""An Arabic version of a site, built only from Arabic somebody actually wrote.

`arabic` is the opportunity this engine raises most often for UAE businesses,
and until now nothing could deliver it. The offer existed, the recommendation was
produced, and there was no executor — so the roadmap could propose work Qevik
could not do.

The whole design turns on one refusal.

**Nothing here translates anything.** Not with a model, not with a dictionary,
not "as a starting point the customer can edit". A machine translation of a
business's own description of itself is a claim about that business, published in
their name, in a language the person approving it very often cannot read. The
failure is silent and total: it looks finished, it reads fluently to nobody who
would notice, and the customer discovers it from a phone call.

So this takes Arabic text that a person supplied, pairs it with the English that
already exists, and refuses to emit a page for anything unpaired. A site with
three translated sections and six missing is delivered as three sections — which
is a smaller deliverable and an honest one.

What it does provide is everything that is *not* language: `dir="rtl"`,
`lang="ar"`, the mirrored layout, the hreflang pair, the canonical relationship,
and the language switch. That is the part of "an Arabic experience" that is
engineering rather than authorship, and it is the part customers most often get
wrong — an Arabic page served with `dir="ltr"` reads as broken even when every
word is right.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .content import Fact, FactSource, Prose, Service, SiteContent

#: The suffix Arabic pages take. A directory (`/ar/`) would be better for a real
#: host and needs a server rule; a suffix works on a filesystem target, which is
#: the only publication target currently connected.
SUFFIX = "-ar"

#: Characters that mean text is actually Arabic. Used to refuse a "translation"
#: that is the English string copied across — the most common way a half-built
#: Arabic site passes review.
ARABIC_RANGE = ((0x0600, 0x06FF), (0x0750, 0x077F), (0x08A0, 0x08FF),
                (0xFB50, 0xFDFF), (0xFE70, 0xFEFF))


def is_arabic(text: str) -> bool:
    """Whether this is Arabic script rather than the English copied across.

    Not a language check — it cannot tell good Arabic from bad. It catches the
    specific failure of an untranslated field being marked translated, which is
    what happens when a form is filled in by somebody working through a list.
    """
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    arabic = sum(1 for c in letters
                 if any(low <= ord(c) <= high for low, high in ARABIC_RANGE))
    # Majority rather than any: a business name or a phone prefix legitimately
    # appears in Latin script inside otherwise Arabic copy.
    return arabic > len(letters) / 2


class NotTranslated(Exception):
    """There is not enough Arabic to build an Arabic page."""


class ArabicContent(BaseModel):
    """Arabic a person wrote, keyed to the English it corresponds to.

    Every field optional, because a business that supplied three translations
    should get three translated sections rather than a refusal — and because a
    required field is a field somebody fills in with the English to get past it.
    """

    model_config = ConfigDict(frozen=True)

    business_name: str = ""
    tagline: str = ""
    about: str = ""
    #: English service name -> Arabic. Keyed by the English so a service with no
    #: translation is identifiable rather than merely absent.
    services: dict[str, str] = Field(default_factory=dict)
    service_descriptions: dict[str, str] = Field(default_factory=dict)
    #: Day name -> Arabic. Hours are numerals in both languages, so this is the
    #: day label only.
    days: dict[str, str] = Field(default_factory=dict)
    #: Labels for the fixed furniture: "Contact", "About", "What we do".
    labels: dict[str, str] = Field(default_factory=dict)
    #: Who supplied it. Required in `check`, because a translation is somebody's
    #: word and an unsigned one cannot be queried later.
    supplied_by: str = ""

    @property
    def supplied(self) -> tuple[str, ...]:
        """Which fields carry actual Arabic."""
        found = []
        for name in ("business_name", "tagline", "about"):
            if is_arabic(getattr(self, name)):
                found.append(name)
        found += [f"service:{k}" for k, v in self.services.items() if is_arabic(v)]
        return tuple(found)

    @property
    def untranslated(self) -> tuple[str, ...]:
        """Fields that were filled in with something that is not Arabic.

        Reported separately from "empty". An empty field is work not done; a
        field holding the English string is work somebody believes is done, and
        only one of those gets fixed on its own.
        """
        found = []
        for name in ("business_name", "tagline", "about"):
            value = getattr(self, name)
            if value and not is_arabic(value):
                found.append(name)
        found += [f"service:{k}" for k, v in self.services.items()
                  if v and not is_arabic(v)]
        return tuple(found)


def check(arabic: ArabicContent, english: SiteContent) -> dict:
    """What can be built, what cannot, and why. Never raises.

    Returned as a report rather than a boolean because the interesting answer is
    always partial: a customer who translated their tagline and half their
    services needs to know exactly which half is missing, in their own terms.
    """
    missing_services = [s.name.value for s in english.services
                        if not is_arabic(arabic.services.get(s.name.value, ""))]
    problems = []
    if not is_arabic(arabic.tagline) and not is_arabic(arabic.about):
        problems.append(
            "no Arabic tagline and no Arabic description, so an Arabic page "
            "would have nothing on it that an Arabic reader could read")
    if arabic.untranslated:
        problems.append(
            f"{len(arabic.untranslated)} field(s) contain text that is not "
            "Arabic script: " + ", ".join(arabic.untranslated))
    if not arabic.supplied_by.strip():
        problems.append(
            "nobody is recorded as having supplied this translation, and an "
            "unsigned translation cannot be queried when it turns out to be wrong")

    return {
        "buildable": not problems,
        "supplied": list(arabic.supplied),
        "untranslated": list(arabic.untranslated),
        "missing_services": missing_services,
        "problems": problems,
        "statement": ("Ready to build." if not problems else
                      f"{len(problems)} thing(s) stop an Arabic page: "
                      + "; ".join(problems)),
        # Stated explicitly, in the artefact's own provenance, because the
        # question "did a machine write this" must have an answer on the record.
        "machine_translated": False,
        "note": "Qevik does not translate. Every Arabic string here was "
                "supplied by a person and is attributed to them.",
    }


def translated(arabic: ArabicContent, english: SiteContent) -> SiteContent:
    """The Arabic site content, built from supplied Arabic and nothing else.

    A field with no Arabic is **dropped**, not carried over in English. An
    Arabic page with English sections on it is the artefact that looks finished
    and is not — and it is the one a reviewer who reads only English approves.
    """
    report = check(arabic, english)
    if not report["buildable"]:
        raise NotTranslated(report["statement"])

    def fact(value: str) -> Fact:
        # Attributed to the person who supplied it, not to Qevik. `CUSTOMER`
        # because that is who stands behind the words.
        return Fact(value=value, source=FactSource.CUSTOMER,
                    note=f"Arabic supplied by {arabic.supplied_by}")

    def prose(text: str) -> Prose:
        # `written_by`, not `source`. `Prose` has no `source` field and pydantic
        # drops an unknown keyword silently, so the attribution this whole
        # capability rests on — that a *person* wrote the Arabic — was being
        # discarded while every test passed.
        return Prose(text=text, written_by=arabic.supplied_by)

    services = []
    for service in english.services:
        name = arabic.services.get(service.name.value, "")
        if not is_arabic(name):
            continue                            # dropped, never left in English
        description = arabic.service_descriptions.get(service.name.value, "")
        services.append(Service(
            name=fact(name),
            description=prose(description) if is_arabic(description) else None))

    return SiteContent(
        business_name=(fact(arabic.business_name)
                       if is_arabic(arabic.business_name)
                       # A business name is often legitimately the same in both
                       # scripts, so this one field falls back rather than being
                       # dropped — a page with no name is not a page.
                       else english.business_name),
        tagline=fact(arabic.tagline) if is_arabic(arabic.tagline) else None,
        about=prose(arabic.about) if is_arabic(arabic.about) else None,
        services=services,
        # Numbers, addresses and hours are not translated and do not need to be.
        # Carried across unchanged rather than dropped: a phone number is the
        # same phone number.
        hours=english.hours, contact=english.contact, location=english.location,
        extras=english.extras)


def rtl(markup: str, *, english_page: str = "", arabic_page: str = "") -> str:
    """Turn a rendered page into a right-to-left one.

    This is the half of "an Arabic experience" that is engineering rather than
    authorship, and it is the half businesses get wrong: an Arabic page served
    with `dir="ltr"` reads as broken to a native reader even when every word is
    correct.

    `hreflang` is emitted only when both sides of the pair are named. A
    self-referential alternate, or one pointing at a page that does not exist,
    is worse than none — it tells a search engine a translation exists where it
    does not.
    """
    page = markup.replace('<html lang="en">', '<html lang="ar" dir="rtl">')
    page = page.replace(
        "<style>",
        "<style>\nbody{direction:rtl;text-align:right}\n"
        "dl{direction:rtl}\ndt,dd{text-align:right}\n"
        # Numerals, phone numbers and email addresses stay left-to-right inside
        # right-to-left text; without this a phone number renders reversed.
        'a[href^="tel:"],a[href^="mailto:"]{direction:ltr;'
        "display:inline-block;unicode-bidi:embed}\n",
        1)
    if english_page and arabic_page:
        alternates = (f'<link rel="alternate" hreflang="en" href="{english_page}">'
                      f'<link rel="alternate" hreflang="ar" href="{arabic_page}">')
        page = page.replace("</head>", f"{alternates}</head>", 1)
    return page


def switch(to_page: str, label: str) -> str:
    """The language link. Placed by the caller, because where it goes is layout."""
    return f'<p class="lang"><a href="{to_page}" hreflang="auto">{label}</a></p>'


def pair(english_files: dict[str, str], arabic_files: dict[str, str]
         ) -> dict[str, str]:
    """Merge an English bundle and an Arabic one into one deliverable.

    Arabic pages take the `-ar` suffix, each side links to the other, and the
    English `sitemap.xml` and `robots.txt` are kept — one site with two
    languages, not two sites. Two sitemaps would compete for the same canonical.
    """
    merged = dict(english_files)
    for name, markup in arabic_files.items():
        if not name.endswith(".html"):
            continue                            # one sitemap, one robots
        stem, _, extension = name.rpartition(".")
        arabic_name = f"{stem}{SUFFIX}.{extension}"
        merged[arabic_name] = rtl(markup, english_page=name,
                                  arabic_page=arabic_name)
        if name in merged:
            merged[name] = merged[name].replace(
                "</header>",
                switch(arabic_name, "العربية") + "</header>", 1)
            merged[arabic_name] = merged[arabic_name].replace(
                "</header>", switch(name, "English") + "</header>", 1)
    return merged
