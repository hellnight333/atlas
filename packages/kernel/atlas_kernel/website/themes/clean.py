"""One theme: a fast, readable, mobile-first page.

Two constraints shape every line of this, and neither is aesthetic.

**It must pass Atlas's own detector.** Title, meta description, viewport, an
``<h1>``, structured data and enough real text — because those are the defects
M014 sells against, and shipping a site missing any of them would be
indefensible. The gate checks this at deploy time; the theme is where it is
earned.

**It must be deterministic.** Same content in, same bytes out. No build
timestamp, no generated ids, no unordered iteration. That is what makes
"rebuilt correctly" a fingerprint comparison instead of a person looking at two
pages, and it is the whole basis of rebuild-from-Business-memory.

The CSS is inline and small on purpose. A separate stylesheet is a second
request before the page can render, and "slow homepage" is one of the findings
on the proposal. Self-consistency again: Atlas cannot sell a speed fix and ship a
render-blocking request it did not need.

**Sections with no facts do not appear.** There is no "Contact us today!" where a
phone number should be. A site with three facts is a small site, and a small
honest site is the deliverable — padding it with copy nobody stands behind is the
exact failure ``content.py`` exists to prevent.

**The page count follows the content, and is never a setting.** A business with
two services and a phone number gets one page; splitting it into Home, Services
and Contact produces three thin pages that read worse, rank worse and take three
requests to say what one said. So ``pages()`` warrants a separate page only where
there is enough to fill one, and refuses to split at all unless at least two are
warranted — Home plus one is a two-page site whose navigation is noise.

Every page carries the full head, its own ``<h1>``, its own structured data and
the whole navigation, because the gate checks pages and not sites: a services
page missing a title is a page that fails Atlas's own detector, on a customer's
domain, shipped by us. Links are relative, so the same bytes work at ``/`` in
production and under ``/preview/<id>/`` before anybody has agreed to publish.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Callable
from dataclasses import dataclass

from ..content import SiteContent

NAME = "clean"
VERSION = "1"

#: Ordered so the rendered day list follows the week rather than the alphabet.
#: Days outside this list are appended in sorted order, so an unexpected key is
#: rendered rather than silently dropped.
WEEK = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

#: Inline, minimal, mobile-first. Deliberately not a framework: a customer site
#: that ships a CSS framework to show a phone number is the page weight this
#: whole factory sells against.
STYLES = """\
*,*::before,*::after{box-sizing:border-box}
body{margin:0;font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
color:#1a1a1a;background:#fff}
.wrap{max-width:44rem;margin:0 auto;padding:2rem 1.25rem 4rem}
header{padding:3rem 0 1.5rem;border-bottom:1px solid #e6e6e6}
h1{font-size:2rem;line-height:1.2;margin:0 0 .5rem}
.tagline{font-size:1.15rem;color:#555;margin:0}
h2{font-size:1.15rem;margin:2.5rem 0 .75rem}
p{margin:0 0 1rem}
ul{margin:0;padding:0;list-style:none}
li{padding:.5rem 0;border-bottom:1px solid #f0f0f0}
li:last-child{border-bottom:0}
.service-name{font-weight:600}
.service-desc{color:#555;display:block}
dl{margin:0;display:grid;grid-template-columns:auto 1fr;gap:.4rem 1.25rem}
dt{color:#666}
dd{margin:0}
a{color:#0b5fff}
footer{margin-top:3rem;padding-top:1.5rem;border-top:1px solid #e6e6e6;color:#666;
font-size:.9rem}
@media(prefers-color-scheme:dark){
body{background:#111;color:#eee}
.tagline,.service-desc,dt,footer{color:#aaa}
header,li,footer{border-color:#2a2a2a}
a{color:#7aa7ff}
}
"""


def _esc(value: str) -> str:
    """Escape everything that reaches the page.

    Content comes from operators, customers and models, and all three can
    contain an ampersand. None of them should be able to contain a script tag.
    """
    return html.escape(value, quote=True)


def _ordered_days(days: dict) -> list[str]:
    known = [day for day in WEEK if day in days]
    unknown = sorted(key for key in days if key not in WEEK)
    return known + unknown


def _meta_description(content: SiteContent) -> str:
    """A description built only from what was supplied.

    Falls back through tagline, about, then services — and if none exist, states
    the business name and location and stops. Padding it out with invented
    marketing language would put an unsourced claim in the one place search
    engines quote verbatim.
    """
    if content.tagline is not None:
        return content.tagline.value
    if content.about is not None:
        text = content.about.text
        return text if len(text) <= 155 else text[:152].rstrip() + "…"
    if content.services:
        offered = ", ".join(service.name.value for service in content.services[:3])
        return f"{content.business_name.value} — {offered}"
    if content.location is not None:
        return f"{content.business_name.value}, {content.location.value}"
    return content.business_name.value


def _structured_data(content: SiteContent) -> str:
    """Schema.org for the business, from supplied facts only.

    This is the machine-readable half of the offer — hours and location showing
    up in search results — so an invented field here is an invented fact with
    better distribution than one in the visible copy.
    """
    payload: dict[str, object] = {
        "@context": "https://schema.org",
        "@type": "LocalBusiness",
        "name": content.business_name.value,
    }
    if content.tagline is not None:
        payload["description"] = content.tagline.value
    elif content.about is not None:
        payload["description"] = content.about.text
    if content.contact.phone is not None:
        payload["telephone"] = content.contact.phone.value
    if content.contact.email is not None:
        payload["email"] = content.contact.email.value
    if content.contact.address is not None or content.location is not None:
        address: dict[str, str] = {"@type": "PostalAddress"}
        if content.contact.address is not None:
            address["streetAddress"] = content.contact.address.value
        if content.location is not None:
            address["addressLocality"] = content.location.value
        payload["address"] = address
    if not content.hours.is_empty:
        payload["openingHours"] = [
            f"{day[:2]} {content.hours.days[day].value}"
            for day in _ordered_days(content.hours.days)
        ]
    # sort_keys so the same content always serialises to the same bytes.
    serialised = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    # JSON escaping does NOT escape `</script>`, so a business name containing
    # one closes this block and everything after it is markup. That is a real
    # cross-site scripting hole on a customer's own domain, published by Atlas,
    # in their name — and `html.escape` cannot be used here because the contents
    # of a script element are not parsed as HTML and would arrive as literal
    # `&lt;`. Escaping the three characters as JSON unicode escapes keeps the
    # payload valid JSON and makes the sequence unrepresentable.
    return serialised.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")




# ============================================ sections

# Each section renders in one of two modes. `brief` is what the home page shows
# when the section has a page of its own: enough to know it is there and to
# decide whether to click, and not a second copy of the full text.
#
# One function per section, not two registries. A brief renderer kept in a
# parallel map is a renderer that drifts — a section added to the full map and
# forgotten in the brief one disappears from the home page and nobody notices,
# because the site still builds and every page still renders.


def _about(content: SiteContent, *, brief: bool = False) -> list[str]:
    if content.about is None:
        return []
    text = content.about.text
    if brief and len(text) > ABOUT_EXCERPT:
        # Cut on a sentence where there is one, so the excerpt reads as writing
        # rather than as a string that ran out.
        cut = text.rfind(". ", 0, ABOUT_EXCERPT)
        text = (text[:cut + 1] if cut > ABOUT_EXCERPT // 2
                else text[:ABOUT_EXCERPT].rstrip() + "…")
    parts = ["<h2>About</h2>", f"<p>{_esc(text)}</p>"]
    if brief:
        parts.append('<p><a href="about.html">More about us</a></p>')
    return parts


def _services(content: SiteContent, *, brief: bool = False) -> list[str]:
    if not content.services:
        return []
    parts = ["<h2>What we do</h2>", "<ul>"]
    for service in content.services:
        entry = f'<li><span class="service-name">{_esc(service.name.value)}</span>'
        # In brief, names only: the descriptions are the reason the services
        # page exists, and printing them twice is duplicate content on the two
        # pages a search engine compares first.
        if service.description is not None and not brief:
            entry += f'<span class="service-desc">{_esc(service.description.text)}</span>'
        parts.append(entry + "</li>")
    parts.append("</ul>")
    if brief:
        parts.append('<p><a href="services.html">What each of these involves</a></p>')
    return parts


def _hours(content: SiteContent, *, brief: bool = False) -> list[str]:
    if content.hours.is_empty:
        return []
    parts = ["<h2>Opening hours</h2>", "<dl>"]
    for day in _ordered_days(content.hours.days):
        parts.append(
            f"<dt>{_esc(day)}</dt><dd>{_esc(content.hours.days[day].value)}</dd>")
    parts.append("</dl>")
    if content.hours.note is not None and not brief:
        parts.append(f"<p>{_esc(content.hours.note.text)}</p>")
    return parts


def _contact(content: SiteContent, *, brief: bool = False) -> list[str]:
    """Contact is never reduced to a link.

    Even in brief it prints the phone number and the email. "Click through for
    our number" is the friction this whole offer sells against, and a visitor
    who landed on the home page is the visitor most likely to be about to call.
    """
    if content.contact.is_empty and content.location is None:
        return []
    parts = ["<h2>Contact</h2>", "<dl>"]
    if content.contact.phone is not None:
        number = _esc(content.contact.phone.value)
        parts.append(f'<dt>Phone</dt><dd><a href="tel:{number.replace(" ", "")}">'
                     f"{number}</a></dd>")
    if content.contact.whatsapp is not None:
        parts.append(f"<dt>WhatsApp</dt><dd>{_esc(content.contact.whatsapp.value)}</dd>")
    if content.contact.email is not None:
        address = _esc(content.contact.email.value)
        parts.append(f'<dt>Email</dt><dd><a href="mailto:{address}">{address}</a></dd>')
    if content.contact.address is not None and not brief:
        parts.append(f"<dt>Address</dt><dd>{_esc(content.contact.address.value)}</dd>")
    elif content.location is not None and content.contact.address is None:
        parts.append(f"<dt>Location</dt><dd>{_esc(content.location.value)}</dd>")
    parts.append("</dl>")
    return parts


def _extras(content: SiteContent, *, brief: bool = False) -> list[str]:
    if not content.extras:
        return []
    parts = ["<h2>Details</h2>", "<dl>"]
    # Sorted, not insertion-ordered: a dict that arrived in a different order
    # would otherwise render different bytes for identical content.
    for key in sorted(content.extras):
        parts.append(f"<dt>{_esc(key)}</dt><dd>{_esc(content.extras[key].value)}</dd>")
    parts.append("</dl>")
    return parts


#: section id -> renderer, in the order they appear on a page. One registry, so
#: a section cannot be rendered on the single-page site and forgotten on the
#: multi-page one — the split reads from this, it does not restate it.
SECTIONS: dict[str, Callable[..., list[str]]] = {
    "about": _about, "services": _services, "hours": _hours,
    "contact": _contact, "extras": _extras}

#: Which sections each page owns in full, when the site splits. `index.html`
#: owns nothing in full: it carries a brief of everything, which is what keeps a
#: home page substantial rather than a stub with a navigation bar on it.
LAYOUT: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("services.html", "Services", ("services",)),
    ("about.html", "About", ("about", "extras")),
    ("contact.html", "Contact", ("contact", "hours")),
)

#: A page is warranted only if it would clear Atlas's *own* thin-content
#: detector. Imported rather than restated: three invented thresholds ("at least
#: three services", "at least 240 characters of about text") stood here first,
#: and they let the split ship a 222-character contact page — the exact defect
#: this factory sells a fix for, on a customer's domain, under our name.
#:
#: Deriving the rule from the detector makes that impossible to reintroduce, and
#: it means tightening the detector tightens the generator in the same commit.
from ...opportunity.detectors.website import THIN_CONTENT_CHARS  # noqa: E402

#: How much of the about text the home page shows before linking on.
ABOUT_EXCERPT = 200


@dataclass(frozen=True)
class Page:
    """One rendered page: its filename, its nav label, and what it carries."""

    filename: str
    label: str
    #: Sections rendered in full.
    sections: tuple[str, ...] = ()
    #: Sections rendered as a summary that links to the page owning them.
    brief: tuple[str, ...] = ()

    @property
    def is_home(self) -> bool:
        return self.filename == "index.html"

    def order(self) -> tuple[tuple[str, bool], ...]:
        """Every section this page shows, in registry order, with its mode."""
        shown = {**{s: False for s in self.sections},
                 **{s: True for s in self.brief}}
        return tuple((section, shown[section]) for section in SECTIONS
                     if section in shown)


def visible_length(markup: str) -> int:
    """How much text a reader actually sees. Approximates the detector's parser.

    Script and style contents are removed whole, then tags, then runs of
    whitespace are collapsed — the same reduction the crawler performs, so the
    number this returns is comparable with THIN_CONTENT_CHARS rather than merely
    similar in spirit.
    """
    without = _SCRIPTS.sub(" ", markup)
    return len(" ".join(_TAGS.sub(" ", without).split()))


_SCRIPTS = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_TAGS = re.compile(r"<[^>]+>")


def _single(content: SiteContent) -> tuple[Page, ...]:
    return (Page(filename="index.html", label="Home", sections=tuple(SECTIONS)),)


def _split(content: SiteContent, extra: list) -> tuple[Page, ...]:
    taken = {section for _, _, sections in extra for section in sections}
    return (Page(filename="index.html", label="Home",
                 # Whatever no other page claimed, in full; everything they did
                 # claim, in brief. Home is therefore never thinner than the
                 # content allows, which matters because thin_content is a
                 # defect Atlas detects and sells against.
                 sections=tuple(s for s in SECTIONS if s not in taken),
                 brief=tuple(s for s in SECTIONS if s in taken)),
            *(Page(filename=name, label=label, sections=sections)
              for name, label, sections in extra))


def pages(content: SiteContent) -> tuple[Page, ...]:
    """Which pages this content warrants, and what goes on each.

    A page is kept only if, once rendered, it clears the same thin-content
    threshold Atlas's detector applies to a stranger's website. Guessing from
    section counts is what shipped a 222-character contact page; rendering the
    candidate and measuring it cannot be wrong in that direction.

    Returns a single page unless at least two survive. One extra page beside
    Home is a two-page site whose navigation exists to hold two links, which is
    worse than the page it split.
    """
    candidates = [entry for entry in LAYOUT
                  if any(SECTIONS[section](content) for section in entry[2])]
    if len(candidates) < 2:
        return _single(content)

    # Render once to measure, then keep only the pages that earned their place.
    provisional = _split(content, candidates)
    substantial = [entry for entry in candidates
                   if _thick_enough(content, entry, provisional)]

    if len(substantial) < 2:
        return _single(content)
    if len(substantial) == len(candidates):
        return provisional
    # Dropping a page returns its sections to the home page in full, which only
    # ever makes home longer — so one re-render settles it and there is no loop.
    return _split(content, substantial)


def _thick_enough(content: SiteContent, entry: tuple, every: tuple[Page, ...]
                  ) -> bool:
    page = next(p for p in every if p.filename == entry[0])
    return visible_length(_render_page(content, page, every)) >= THIN_CONTENT_CHARS


# ============================================ rendering


def _nav(current: Page, every: tuple[Page, ...]) -> list[str]:
    """The whole navigation, on every page.

    Relative hrefs, so the same bytes serve from the site root and from a
    preview directory. A page linking to `/services.html` would 404 in every
    preview, which is exactly where a customer looks first.
    """
    if len(every) < 2:
        return []
    links = []
    for page in every:
        label = _esc(page.label)
        links.append(f'<span aria-current="page">{label}</span>'
                     if page.filename == current.filename
                     else f'<a href="{page.filename}">{label}</a>')
    return ['<nav aria-label="Site">', " ".join(links), "</nav>"]


def _page_title(content: SiteContent, page: Page) -> str:
    name = _esc(content.business_name.value)
    where = (f" — {_esc(content.location.value)}"
             if content.location is not None else "")
    if page.is_home:
        return f"{name}{where}"
    # The page's own subject first: four tabs all reading "Business Name" are
    # four tabs a person cannot tell apart.
    return f"{_esc(page.label)} — {name}"


def _render_page(content: SiteContent, page: Page,
                 every: tuple[Page, ...]) -> str:
    name = _esc(content.business_name.value)
    parts: list[str] = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{_page_title(content, page)}</title>",
        f'<meta name="description" content="{_esc(_meta_description(content))}">',
        f"<style>{STYLES}</style>",
        # On every page, not only the home page. A services page with no
        # structured data reads to a search engine as unrelated to the business
        # it belongs to.
        f'<script type="application/ld+json">{_structured_data(content)}</script>',
        "</head>",
        "<body>",
        '<div class="wrap">',
        "<header>",
        f"<h1>{name}</h1>" if page.is_home else f"<h1>{_esc(page.label)}</h1>",
    ]
    if page.is_home and content.tagline is not None:
        parts.append(f'<p class="tagline">{_esc(content.tagline.value)}</p>')
    elif not page.is_home:
        # The business name still has to appear on an inner page: a "Contact"
        # page that never names the business is a page a search result cannot
        # be attributed to.
        parts.append(f'<p class="tagline">{name}</p>')
    parts.extend(_nav(page, every))
    parts.append("</header>")

    for section, brief in page.order():
        parts.extend(SECTIONS[section](content, brief=brief))

    # No build date, no "generated by" line. Both would change the bytes without
    # changing the content, which is exactly what determinism forbids — and a
    # customer's site is not the place for Atlas's byline.
    parts.extend([f"<footer>{name}</footer>", "</div>", "</body>", "</html>"])
    return "\n".join(parts) + "\n"


def render(content: SiteContent) -> dict[str, str]:
    """Render the content to a file map. Deterministic."""
    every = pages(content)
    return {page.filename: _render_page(content, page, every) for page in every}
