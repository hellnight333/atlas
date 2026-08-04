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
"""

from __future__ import annotations

import html
import json

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


def render(content: SiteContent) -> dict[str, str]:
    """Render the content to a file map. Deterministic."""
    name = _esc(content.business_name.value)
    parts: list[str] = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{name}"
        + (f" — {_esc(content.location.value)}" if content.location is not None else "")
        + "</title>",
        f'<meta name="description" content="{_esc(_meta_description(content))}">',
        f"<style>{STYLES}</style>",
        f'<script type="application/ld+json">{_structured_data(content)}</script>',
        "</head>",
        "<body>",
        '<div class="wrap">',
        "<header>",
        f"<h1>{name}</h1>",
    ]

    if content.tagline is not None:
        parts.append(f'<p class="tagline">{_esc(content.tagline.value)}</p>')
    parts.append("</header>")

    if content.about is not None:
        parts.append("<h2>About</h2>")
        parts.append(f"<p>{_esc(content.about.text)}</p>")

    if content.services:
        parts.append("<h2>What we do</h2>")
        parts.append("<ul>")
        for service in content.services:
            entry = f'<li><span class="service-name">{_esc(service.name.value)}</span>'
            if service.description is not None:
                entry += f'<span class="service-desc">{_esc(service.description.text)}</span>'
            parts.append(entry + "</li>")
        parts.append("</ul>")

    if not content.hours.is_empty:
        parts.append("<h2>Opening hours</h2>")
        parts.append("<dl>")
        for day in _ordered_days(content.hours.days):
            parts.append(f"<dt>{_esc(day)}</dt><dd>{_esc(content.hours.days[day].value)}</dd>")
        parts.append("</dl>")
        if content.hours.note is not None:
            parts.append(f"<p>{_esc(content.hours.note.text)}</p>")

    if not content.contact.is_empty or content.location is not None:
        parts.append("<h2>Contact</h2>")
        parts.append("<dl>")
        if content.contact.phone is not None:
            number = _esc(content.contact.phone.value)
            tel = number.replace(" ", "")
            parts.append(f'<dt>Phone</dt><dd><a href="tel:{tel}">{number}</a></dd>')
        if content.contact.whatsapp is not None:
            parts.append(f"<dt>WhatsApp</dt><dd>{_esc(content.contact.whatsapp.value)}</dd>")
        if content.contact.email is not None:
            address = _esc(content.contact.email.value)
            parts.append(f'<dt>Email</dt><dd><a href="mailto:{address}">{address}</a></dd>')
        if content.contact.address is not None:
            parts.append(f"<dt>Address</dt><dd>{_esc(content.contact.address.value)}</dd>")
        elif content.location is not None:
            parts.append(f"<dt>Location</dt><dd>{_esc(content.location.value)}</dd>")
        parts.append("</dl>")

    if content.extras:
        parts.append("<h2>Details</h2>")
        parts.append("<dl>")
        for key in sorted(content.extras):
            parts.append(f"<dt>{_esc(key)}</dt><dd>{_esc(content.extras[key].value)}</dd>")
        parts.append("</dl>")

    # No build date, no "generated by" line. Both would change the bytes without
    # changing the content, which is exactly what determinism forbids — and a
    # customer's site is not the place for Atlas's byline.
    parts.extend([f"<footer>{name}</footer>", "</div>", "</body>", "</html>"])

    return {"index.html": "\n".join(parts) + "\n"}
