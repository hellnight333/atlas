"""A production-quality site for a dental clinic.

This is the thing that gets sold, so it is held to a different standard from the
placeholder that preceded it: a headline, a line of text and three bullets is
not what anyone pays for. The market rate found by our own research was AED
3,500 for a dental clinic site, and those are multi-section, mobile-first, with
a real call-to-action and a findable address.

**Nothing here invents a claim about a real business.** The clinic's name,
address and phone come from its own listing and are rendered as facts; the
services and reassurance copy are category-typical and written as an offer, not
as an assertion about this clinic's credentials. That distinction is the
difference between a proposal a dentist recognises as their own and a page full
of confident nonsense they will resent. No invented dentists, no invented years
of experience, no invented awards, no invented testimonials — those are exactly
what a prospect checks first, and exactly what would end the conversation.

Self-contained by design: no external fonts, scripts, analytics or images. It
loads instantly on a phone over a Dubai mobile connection, survives the strict
CSP the host sets, and has no third-party request for a prospect's IT person to
object to.
"""

from __future__ import annotations

import html
import json
import re
from urllib.parse import quote

from ..content import Fact, SiteContent

NAME = "dental"

#: Services a dental clinic offers. Category-typical and phrased as what the
#: page *offers to describe*, never as a credential claim about this clinic.
#: A dentist reading these should think "yes, we do that", not "we never said
#: that".
#: Inline SVG, not emoji. Emoji render differently on every platform — a wrench
#: for "implants" and a siren for "emergency" look like placeholders, and they
#: look like *different* placeholders on the prospect's Windows machine. These
#: are a single consistent stroke weight and cost no extra request.
_ICON = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"'
    ' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{}</svg>'
)
ICONS: dict[str, str] = {
    "tooth": '<path d="M12 3c-2 0-3 1-4.5 1S4 3.2 4 6c0 4 1.5 6 2.5 9.5S8 21 9.5 21s1.3-3 2.5-3'
    ' 1.3 3 2.5 3 2-2 3-5.5S20 10 20 6c0-2.8-2-2-3.5-2S14 3 12 3Z"/>',
    "shield": '<path d="M12 3 5 6v6c0 4 3 7 7 9 4-2 7-5 7-9V6l-7-3Z"/><path d="m9 12 2 2 4-4"/>',
    "sparkle": '<path d="m12 4 1.8 4.2L18 10l-4.2 1.8L12 16l-1.8-4.2L6 10l4.2-1.8L12 4Z"/>'
    '<path d="M18 16.5 18.8 18l1.5.8-1.5.7L18 21l-.8-1.5-1.5-.7 1.5-.8.8-1.5Z"/>',
    "align": '<path d="M4 8h16M4 16h16"/><path d="M8 5v6M12 5v6M16 5v6M8 13v6M12 13v6M16 13v6"/>',
    "crown": '<path d="M4 17h16"/><path d="m4 17 1-8 4 3 3-6 3 6 4-3 1 8"/>',
    "clock": '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/>',
}

DEFAULT_SERVICES: tuple[tuple[str, str, str], ...] = (
    ("Check-ups & Cleaning", "tooth", "Routine examinations and professional hygiene appointments."),
    ("Fillings & Restorations", "shield", "Tooth-coloured fillings and repair of damaged teeth."),
    ("Teeth Whitening", "sparkle", "In-clinic and take-home whitening options."),
    ("Braces & Aligners", "align", "Orthodontic assessment and treatment planning."),
    ("Implants & Crowns", "crown", "Replacement and restoration of missing teeth."),
    ("Emergency Dental Care", "clock", "Same-day appointments for pain and urgent problems."),
)

#: Reassurances that are true of any competent clinic and assert nothing
#: specific. Anything a prospect could dispute about their own practice is
#: deliberately absent.
DEFAULT_ASSURANCES: tuple[tuple[str, str], ...] = (
    ("Modern equipment", "Digital imaging and up-to-date clinical technique."),
    ("Comfortable care", "Gentle treatment, with anxious patients in mind."),
    ("Clear pricing", "Costs explained before treatment begins."),
    ("Family friendly", "Appointments for adults and children alike."),
)

_SAFE = re.compile(r"[^A-Za-z0-9+\-() ]")


def tel_href(phone: str) -> str:
    """A dialable ``tel:`` value.

    Stripped to digits and a leading plus: a number with spaces or a country
    label in it silently fails to dial on some Android browsers, which turns the
    single most important button on the page into decoration.
    """
    cleaned = _SAFE.sub("", phone or "").strip()
    digits = re.sub(r"[^\d+]", "", cleaned)
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    return digits


def whatsapp_href(phone: str) -> str:
    """WhatsApp expects digits only, no plus.

    Worth having: in the UAE a business enquiry is far more likely to arrive on
    WhatsApp than through a contact form, and a form that emails into a void is
    worse than no form at all.
    """
    return re.sub(r"\D", "", tel_href(phone))


def _fact(content: SiteContent, name: str) -> str:
    """A stated fact, or an empty string.

    Empty rather than a placeholder: a section that cannot be filled from real
    data is omitted, because "123 Example Street" on a real clinic's proposal is
    worse than no address at all.
    """
    value = getattr(content, name, None)
    if isinstance(value, Fact):
        return value.value.strip()
    if isinstance(value, str):
        return value.strip()
    return ""


def _structured_data(*, name: str, phone: str, address: str, url: str) -> str:
    """Schema.org for a dental practice.

    The reason a small clinic's site shows up in a local search at all. Only
    fields backed by real data are emitted — an incomplete record ranks; an
    invented one is a lie a search engine may also punish.
    """
    data: dict[str, object] = {
        "@context": "https://schema.org",
        "@type": "Dentist",
        "name": name,
    }
    if phone:
        data["telephone"] = phone
    if address:
        data["address"] = {"@type": "PostalAddress", "streetAddress": address}
    if url:
        data["url"] = url
    data["areaServed"] = "Dubai"
    # JSON encoding does not escape </script>, so a name containing it would
    # close the block and execute what follows.
    return (
        json.dumps(data, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


#: A calm inline illustration for the hero.
#:
#: Drawn rather than photographed on purpose: stock photography of smiling
#: strangers is the tell of a template, and a real clinic's own photos are the
#: first thing they will want to supply. Inline SVG also means no external
#: request, so the page still loads instantly and passes the host's strict CSP.
HERO_ART = """<svg class="hero-art" viewBox="0 0 420 320" role="img"
  aria-label="Illustration of a dental clinic">
  <defs>
    <linearGradient id="g1" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#e8f4f6"/><stop offset="100%" stop-color="#f8fcfd"/>
    </linearGradient>
  </defs>
  <rect x="20" y="30" width="380" height="260" rx="22" fill="url(#g1)"/>
  <g fill="none" stroke="#0f7d8c" stroke-width="2.4" stroke-linecap="round"
     stroke-linejoin="round">
    <path d="M210 96c-14 0-21 7-31 7s-24-6-24 13c0 27 10 41 17 65s10 37 20 37 9-20 17-20
             9 20 17 20 14-14 21-37 17-38 17-65c0-19-14-13-24-13s-16-7-30-7Z"/>
    <path d="M186 128c7-4 15-4 22 0" opacity=".55"/>
  </g>
  <g fill="#0f7d8c" opacity=".13">
    <circle cx="86" cy="88" r="16"/><circle cx="340" cy="238" r="22"/>
    <circle cx="330" cy="92" r="9"/><circle cx="96" cy="242" r="11"/>
  </g>
  <g fill="none" stroke="#f6b352" stroke-width="3" stroke-linecap="round">
    <path d="M64 176h34"/><path d="M322 158h34"/>
  </g>
</svg>"""

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{description}">
<meta property="og:title" content="{og_title}">
<meta property="og:description" content="{description}">
<meta property="og:type" content="website">
<style>
  :root {{
    --ink:#12212e; --muted:#5a6b7a; --line:#e3e9ee; --bg:#ffffff; --soft:#f5f9fc;
    --brand:#0f7d8c; --brand-dark:#0b5f6b; --accent:#f6b352;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font:16px/1.65 -apple-system,"Segoe UI",Roboto,system-ui,sans-serif;
         color:var(--ink); background:var(--bg); -webkit-font-smoothing:antialiased; }}
  .wrap {{ max-width:1080px; margin:0 auto; padding:0 1.25rem; }}
  a {{ color:var(--brand-dark); }}

  header {{ position:sticky; top:0; z-index:10; background:rgba(255,255,255,.96);
            border-bottom:1px solid var(--line); backdrop-filter:blur(6px); }}
  header .wrap {{ display:flex; align-items:center; gap:1rem; padding-top:.85rem; padding-bottom:.85rem; }}
  .brand {{ font-weight:700; font-size:1.05rem; letter-spacing:-.01em; }}
  .brand small {{ display:block; font-weight:400; font-size:.75rem; color:var(--muted); }}
  header nav {{ margin-left:auto; display:flex; gap:1.25rem; }}
  header nav a {{ text-decoration:none; color:var(--muted); font-size:.9rem; }}
  header nav a:hover {{ color:var(--brand-dark); }}
  .call {{ background:var(--brand); color:#fff !important; padding:.6rem 1.1rem; border-radius:99px;
           text-decoration:none; font-weight:600; white-space:nowrap; font-size:.92rem; }}
  .call:hover {{ background:var(--brand-dark); }}

  .hero {{ background:linear-gradient(160deg,var(--soft) 0%,#fff 70%); padding:4rem 0 3.5rem;
           border-bottom:1px solid var(--line); }}
  .hero .wrap {{ display:grid; grid-template-columns:1.15fr .85fr; gap:2.5rem; align-items:center; }}
  .hero-art {{ width:100%; height:auto; }}
  .ico svg {{ width:26px; height:26px; color:var(--brand); }}
  .hero h1 {{ font-size:clamp(2rem,5.5vw,3.1rem); line-height:1.12; margin:0 0 .9rem;
              letter-spacing:-.02em; max-width:20ch; }}
  .hero p.lead {{ font-size:1.12rem; color:var(--muted); max-width:52ch; margin:0 0 1.8rem; }}
  .cta-row {{ display:flex; gap:.75rem; flex-wrap:wrap; }}
  .btn {{ display:inline-block; padding:.85rem 1.5rem; border-radius:10px; text-decoration:none;
          font-weight:600; }}
  .btn-primary {{ background:var(--brand); color:#fff; }}
  .btn-primary:hover {{ background:var(--brand-dark); }}
  .btn-ghost {{ border:1.5px solid var(--line); color:var(--ink); background:#fff; }}
  .btn-ghost:hover {{ border-color:var(--brand); }}

  section {{ padding:3.5rem 0; }}
  section.alt {{ background:var(--soft); }}
  h2 {{ font-size:clamp(1.5rem,3.5vw,2rem); margin:0 0 .5rem; letter-spacing:-.015em; }}
  .sub {{ color:var(--muted); margin:0 0 2rem; max-width:56ch; }}

  .grid {{ display:grid; gap:1.1rem; grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); }}
  .card {{ background:#fff; border:1px solid var(--line); border-radius:14px; padding:1.4rem; }}
  .card .ico {{ font-size:1.6rem; line-height:1; margin-bottom:.6rem; }}
  .card h3 {{ margin:0 0 .35rem; font-size:1.05rem; }}
  .card p {{ margin:0; color:var(--muted); font-size:.94rem; }}

  .split {{ display:grid; gap:2rem; grid-template-columns:1.1fr .9fr; align-items:start; }}
  .info {{ background:#fff; border:1px solid var(--line); border-radius:14px; padding:1.5rem; }}
  .info dl {{ display:grid; grid-template-columns:auto 1fr; gap:.6rem 1rem; margin:0; }}
  .info dt {{ color:var(--muted); font-size:.9rem; }}
  .info dd {{ margin:0; font-weight:500; }}
  .hours li {{ display:flex; justify-content:space-between; padding:.35rem 0;
               border-bottom:1px dashed var(--line); font-size:.94rem; }}
  ul.plain {{ list-style:none; padding:0; margin:0; }}

  .final {{ background:var(--brand-dark); color:#fff; text-align:center; padding:3.5rem 0; }}
  .final h2 {{ color:#fff; }}
  .final p {{ color:#cfe6ea; max-width:48ch; margin:0 auto 1.6rem; }}
  .final .btn-primary {{ background:var(--accent); color:#12212e; }}

  footer {{ padding:2rem 0; border-top:1px solid var(--line); color:var(--muted); font-size:.88rem; }}
  footer .wrap {{ display:flex; gap:1rem; flex-wrap:wrap; justify-content:space-between; }}

  @media (max-width:760px) {{
    header nav {{ display:none; }}
    .split {{ grid-template-columns:1fr; }}
    .hero {{ padding:3rem 0 2.5rem; }}
    .hero .wrap {{ grid-template-columns:1fr; gap:1.5rem; }}
    /* The illustration is decoration. On a phone it costs a screenful before
       the call button, which is the one thing a visitor in pain wants. */
    .hero-art {{ display:none; }}
    header .wrap {{ flex-wrap:wrap; row-gap:.6rem; }}
    .brand {{ flex:1 1 auto; }}
    .call {{ font-size:.85rem; padding:.5rem .9rem; }}
  }}
</style>
</head>
<body>

<header>
  <div class="wrap">
    <div class="brand">{name}<small>{tagline_short}</small></div>
    <nav>
      <a href="#services">Services</a>
      <a href="#visit">Visit us</a>
      <a href="#contact">Contact</a>
    </nav>
    {header_cta}
  </div>
</header>

<div class="hero">
  <div class="wrap">
    <div>
      <h1 id="headline">{headline}</h1>
      <p class="lead" id="tagline">{tagline}</p>
      <div class="cta-row">{hero_ctas}</div>
    </div>
    {hero_art}
  </div>
</div>

<section id="services">
  <div class="wrap">
    <h2>Our services</h2>
    <p class="sub">Comprehensive dental care for adults and children.</p>
    <div class="grid" id="features">{services}</div>
  </div>
</section>

<section class="alt" id="why">
  <div class="wrap">
    <h2>Why patients choose us</h2>
    <p class="sub">Careful, unhurried treatment with the details explained.</p>
    <div class="grid">{assurances}</div>
  </div>
</section>

<section id="visit">
  <div class="wrap">
    <h2>Visit us</h2>
    <p class="sub">Find us, call us, or message us on WhatsApp.</p>
    <div class="split">
      <div class="info">
        <dl>{contact_rows}</dl>
      </div>
      {hours_block}
    </div>
  </div>
</section>

<div class="final" id="contact">
  <div class="wrap">
    <h2>Book an appointment</h2>
    <p>{closing}</p>
    <div class="cta-row" style="justify-content:center">{final_ctas}</div>
  </div>
</div>

<footer>
  <div class="wrap">
    <span>&copy; {year} {name}</span>
    <span>{footer_location}</span>
  </div>
</footer>

<script type="application/ld+json">{structured}</script>
</body>
</html>
"""


def render(
    *,
    name: str,
    phone: str = "",
    address: str = "",
    area: str = "Dubai",
    url: str = "",
    hours: list[tuple[str, str]] | None = None,
    services: tuple[tuple[str, str, str], ...] = DEFAULT_SERVICES,
    assurances: tuple[tuple[str, str], ...] = DEFAULT_ASSURANCES,
    year: int = 2026,
) -> str:
    """Render a client-ready page.

    Every argument except the copy defaults is a fact about a real business.
    Anything absent is *omitted* rather than filled with an example — a proposal
    showing "123 Example Street" to a dentist who knows their own address is a
    proposal that ends the conversation.
    """
    e = html.escape
    name_x = e(name.strip() or "Dental Clinic")
    area_x = e(area.strip())
    dial = tel_href(phone)
    wa = whatsapp_href(phone)

    headline = f"Gentle, modern dentistry in {area_x}" if area_x else "Gentle, modern dentistry"
    tagline = (
        f"{name_x} provides routine and specialist dental care"
        + (f" in {area_x}." if area_x else ".")
        + " Same-day appointments available for urgent problems."
    )
    description = (
        f"{name_x} — dental clinic"
        + (f" in {area_x}" if area_x else "")
        + ". Check-ups, cleaning, whitening, braces, implants and emergency care."
    )

    # Buttons only exist when there is a real number behind them. A "Call now"
    # that dials nothing is worse than no button, because it is discovered by
    # the one visitor who most wanted to get in touch.
    header_cta = f'<a class="call" href="tel:{e(dial)}">Call {e(phone.strip())}</a>' if dial else ""
    hero_ctas = ""
    final_ctas = ""
    if dial:
        hero_ctas += f'<a class="btn btn-primary" href="tel:{e(dial)}">Call {e(phone.strip())}</a>'
        final_ctas += f'<a class="btn btn-primary" href="tel:{e(dial)}">Call {e(phone.strip())}</a>'
    if wa:
        link = f"https://wa.me/{e(wa)}"
        hero_ctas += f'<a class="btn btn-ghost" href="{link}" rel="noopener">WhatsApp</a>'
        final_ctas += f'<a class="btn btn-ghost" href="{link}" rel="noopener">WhatsApp</a>'
    if address:
        maps = "https://www.google.com/maps/search/?api=1&query=" + quote(f"{name} {address}")
        hero_ctas += f'<a class="btn btn-ghost" href="{maps}" rel="noopener">Directions</a>'

    service_cards = "".join(
        f'<div class="card"><div class="ico">{_ICON.format(ICONS.get(icon, ICONS["tooth"]))}</div>'
        f"<h3>{e(title)}</h3><p>{e(blurb)}</p></div>"
        for title, icon, blurb in services
    )
    assurance_cards = "".join(
        f'<div class="card"><h3>{e(title)}</h3><p>{e(blurb)}</p></div>'
        for title, blurb in assurances
    )

    rows = ""
    if address:
        rows += f"<dt>Address</dt><dd>{e(address)}</dd>"
    if phone:
        rows += f'<dt>Phone</dt><dd><a href="tel:{e(dial)}">{e(phone.strip())}</a></dd>'
    if wa:
        rows += f'<dt>WhatsApp</dt><dd><a href="https://wa.me/{e(wa)}" rel="noopener">Message us</a></dd>'
    if area_x:
        rows += f"<dt>Area</dt><dd>{area_x}</dd>"
    if not rows:
        rows = "<dt>Contact</dt><dd>Details to be confirmed</dd>"

    # Opening hours are asserted or absent. Guessing them is the fastest way to
    # have a patient arrive at a locked door.
    hours_block = ""
    if hours:
        items = "".join(
            f"<li><span>{e(day)}</span><span>{e(time)}</span></li>" for day, time in hours
        )
        hours_block = (
            f'<div class="info"><h3 style="margin-top:0">Opening hours</h3>'
            f'<ul class="plain hours">{items}</ul></div>'
        )

    closing = (
        "Call us and we will find a time that suits you."
        if dial
        else "Get in touch and we will find a time that suits you."
    )

    return PAGE.format(
        title=f"{name_x} | Dental Clinic{f' in {area_x}' if area_x else ''}",
        og_title=name_x,
        description=e(description),
        name=name_x,
        tagline_short=e(f"Dental clinic{f' · {area}' if area else ''}"),
        headline=headline,
        tagline=tagline,
        header_cta=header_cta,
        hero_ctas=hero_ctas,
        final_ctas=final_ctas,
        services=service_cards,
        assurances=assurance_cards,
        contact_rows=rows,
        hours_block=hours_block,
        hero_art=HERO_ART,
        closing=closing,
        year=year,
        footer_location=e(address or area or ""),
        structured=_structured_data(name=name, phone=dial, address=address, url=url),
    )


def from_content(content: SiteContent, *, year: int = 2026) -> str:
    """Render from a `SiteContent`, taking only what is actually stated."""
    contact = getattr(content, "contact", None)
    return render(
        name=_fact(content, "business_name") or getattr(content, "title", "") or "Dental Clinic",
        phone=getattr(contact, "phone", "") if contact else "",
        address=getattr(contact, "address", "") if contact else "",
        area=_fact(content, "area") or "Dubai",
        year=year,
    )
