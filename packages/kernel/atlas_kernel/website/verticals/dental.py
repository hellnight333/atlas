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
from . import _strings

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
_ARABIC_CHARS = re.compile(r"[\u0600-\u06ff]")
_AM = re.compile(r"\bAM\b", re.IGNORECASE)
_PM = re.compile(r"\bPM\b", re.IGNORECASE)


def _has_arabic(value: str) -> bool:
    return bool(_ARABIC_CHARS.search(value))


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


#: UAE mobile prefixes, in local form. WhatsApp runs on a mobile number; a
#: landline or a toll-free line cannot receive it.
_UAE_MOBILE = re.compile(r"^0?5[024568]\d{7}$")


def whatsapp_href(phone: str) -> str:
    """A WhatsApp link, but only for a number that can actually receive one.

    Empty when the number cannot, and that emptiness is the point. Generated
    naively from a business listing, this produced ``wa.me/043987075`` for a
    landline and ``wa.me/800732757`` for a toll-free line — dead buttons on
    seventeen of twenty demos, on the one channel UAE patients actually use.

    A dead WhatsApp button is worse than no button: it is discovered by the
    visitor who most wanted to make contact, and on a proposal it is discovered
    by the owner deciding whether we know what we are doing.
    """
    digits = re.sub(r"\D", "", tel_href(phone))
    if digits.startswith("971"):
        digits = "0" + digits[3:]
    if not _UAE_MOBILE.match(digits):
        return ""
    return "971" + digits.lstrip("0")


def whatsapp_status(phone: str) -> str:
    """Why WhatsApp is or is not offered, for the audit and the brief.

    Never guesses. A landline is a confirmed *no*; anything unrecognised is
    unverified rather than absent, because a number we cannot classify is not
    evidence that the clinic lacks WhatsApp.
    """
    digits = re.sub(r"\D", "", tel_href(phone))
    if not digits:
        return "NOT_VERIFIED: no phone number on the listing"
    local = "0" + digits[3:] if digits.startswith("971") else digits
    if _UAE_MOBILE.match(local):
        return "CONFIRMED_PRESENT: listing number is a UAE mobile"
    if local.startswith("800"):
        return "CONFIRMED_ABSENT: toll-free numbers cannot receive WhatsApp"
    if re.match(r"^0?[2-4679]\d{7}$", local):
        return "CONFIRMED_ABSENT: landline numbers cannot receive WhatsApp"
    return "NOT_VERIFIED: number format not recognised"


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


def _structured_data(
    *, name: str, phone: str, address: str, url: str, hours: list[tuple[str, str]] | None = None
) -> str:
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
    if hours:
        # Emitted verbatim from the listing. Search engines accept a plain
        # string here, and rewriting "Sat-Thu 9:00 - 21:00" into a structured
        # day range would mean deciding what the clinic meant.
        data["openingHours"] = [f"{day} {time}" for day, time in hours]
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
<html lang="{lang}" dir="{dir}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{description}">
<link rel="canonical" href="{canonical}">
<link rel="alternate" hreflang="en" href="{href_en}">
<link rel="alternate" hreflang="ar" href="{href_ar}">
<link rel="alternate" hreflang="x-default" href="{href_en}">
<meta property="og:title" content="{og_title}">
<meta property="og:description" content="{description}">
<meta property="og:type" content="website">
<meta property="og:url" content="{canonical}">
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

  .lang {{ margin-inline-start:.9rem; font-size:.85rem; text-decoration:none; color:var(--muted);
           border:1px solid var(--line); border-radius:99px; padding:.35rem .7rem; white-space:nowrap; }}
  .lang:hover {{ border-color:var(--brand); color:var(--brand-dark); }}

  form.request {{ background:#fff; border:1px solid var(--line); border-radius:14px; padding:1.4rem; }}
  .fields {{ display:grid; gap:.9rem; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); }}
  form.request label {{ display:block; font-size:.88rem; color:var(--muted); }}
  form.request label.wide {{ margin-top:.9rem; }}
  form.request input, form.request select, form.request textarea {{
    width:100%; margin-top:.35rem; padding:.65rem .7rem; font:inherit; color:var(--ink);
    border:1px solid var(--line); border-radius:9px; background:#fff; }}
  form.request button {{ margin-top:1rem; background:var(--brand); color:#fff; border:0;
    padding:.8rem 1.6rem; border-radius:10px; font:inherit; font-weight:600; cursor:pointer; }}
  form.request button:hover {{ background:var(--brand-dark); }}
  .notice {{ margin:.9rem 0 0; font-size:.88rem; color:var(--muted); }}
  .notice.shown {{ color:var(--ink); background:#fff8e8; border:1px solid var(--accent);
                   border-radius:9px; padding:.7rem .8rem; }}

  /* Right-to-left. Logical properties do most of the work; these are the few
     places a physical direction was assumed. */
  [dir="rtl"] .hours li {{ flex-direction:row-reverse; }}
  [dir="rtl"] .info dl {{ direction:rtl; }}
  [dir="rtl"] ul {{ padding-left:0; padding-right:1.2rem; }}

  footer {{ padding:2rem 0; border-top:1px solid var(--line); color:var(--muted); font-size:.88rem; }}
  footer .wrap {{ display:flex; gap:1rem; flex-wrap:wrap; justify-content:space-between; }}

  /* Sticky action bar. On a phone the important actions must stay reachable
     without scrolling back to the top — a patient in pain does not hunt for a
     number. Hidden on desktop, where the header CTA is always visible. */
  .sticky {{ display:none; }}
  @media (max-width:760px) {{
    .sticky {{ display:flex; position:fixed; inset:auto 0 0 0; z-index:40;
               background:#fff; border-top:1px solid var(--line);
               padding:.55rem .6rem; gap:.5rem;
               box-shadow:0 -6px 18px rgba(18,33,46,.08); }}
    .sticky a {{ flex:1; text-align:center; padding:.7rem .3rem; border-radius:10px;
                 text-decoration:none; font-weight:600; font-size:.85rem; }}
    .sticky .s-call {{ background:var(--brand); color:#fff; }}
    .sticky .s-wa {{ background:#25d366; color:#fff; }}
    .sticky .s-book {{ background:var(--accent); color:#12212e; }}
    .sticky .s-map {{ border:1.5px solid var(--line); color:var(--ink); }}
    body {{ padding-bottom:4.5rem; }}
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
      <a href="#services">{nav_services}</a>
      <a href="#visit">{nav_visit}</a>
      <a href="#contact">{nav_contact}</a>
    </nav>
    <a class="lang" href="{other_href}" hreflang="{other_lang}">{other_language}</a>
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
    <h2>{services_heading}</h2>
    <p class="sub">{services_sub}</p>
    <div class="grid" id="features">{services}</div>
  </div>
</section>

<section class="alt" id="why">
  <div class="wrap">
    <h2>{why_heading}</h2>
    <p class="sub">{why_sub}</p>
    <div class="grid">{assurances}</div>
  </div>
</section>

<section id="visit">
  <div class="wrap">
    <h2>{visit_heading}</h2>
    <p class="sub">{visit_sub}</p>
    <div class="split">
      <div class="info">
        <dl>{contact_rows}</dl>
      </div>
      {hours_block}
    </div>
  </div>
</section>

<section class="alt" id="request">
  <div class="wrap">
    <h2>{request_heading}</h2>
    <p class="sub">{request_sub}</p>
    <form class="request" id="appointment-form" novalidate>
      <div class="fields">
        <label>{field_name}<input name="name" autocomplete="name" required></label>
        <label>{field_phone}<input name="phone" type="tel" autocomplete="tel" required></label>
        <label>{field_when}<input name="preferred" type="datetime-local"></label>
        <label>{field_service}
          <select name="service">{service_options}</select>
        </label>
      </div>
      <label class="wide">{field_message}<textarea name="message" rows="3"></textarea></label>
      <button type="submit">{request_submit}</button>
      <p class="notice" id="form-notice" role="status">{request_notice}</p>
    </form>
  </div>
</section>

<div class="final" id="contact">
  <div class="wrap">
    <h2>{book_heading}</h2>
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

<div class="sticky">{sticky}</div>

<script type="application/ld+json">{structured}</script>
<script>
// The appointment backend does not exist yet. Rather than pretend, the form
// states that plainly and points the visitor at a channel that does work.
// A fake success message here would be the one lie that reaches a patient.
document.getElementById('appointment-form').addEventListener('submit', function (e) {{
  e.preventDefault();
  var notice = document.getElementById('form-notice');
  notice.textContent = {not_implemented_js};
  notice.className = 'notice shown';
}});
</script>
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
    booking_url: str = "",
    year: int = 2026,
    lang: str = "en",
    base_url: str = "",
) -> str:
    """Render one language of a clinic page.

    Every argument except the copy defaults is a fact about a real business, and
    anything absent is *omitted* rather than filled with an example — a proposal
    showing "123 Example Street" to a dentist who knows their own address ends
    the conversation.
    """
    strings = _strings.AR if lang == "ar" else _strings.EN
    services = _strings.SERVICES_AR if lang == "ar" else _strings.SERVICES_EN
    assurances = _strings.ASSURANCES_AR if lang == "ar" else _strings.ASSURANCES_EN

    e = html.escape
    name_x = e(name.strip() or "Dental Clinic")
    area_x = e(area.strip())
    dial = tel_href(phone)
    wa = whatsapp_href(phone)

    site_root = url or (f"{base_url}/" if base_url else "")
    href_en = site_root
    href_ar = f"{site_root}ar/" if site_root else "ar/"
    # Each language page is canonical for itself. Pointing the Arabic page's
    # canonical at the English one declares it a duplicate, and Google drops
    # duplicates from the index — which would remove the Arabic page from
    # exactly the searches it was written to win. hreflang, not canonical, is
    # what tells a crawler these two are translations of each other.
    canonical = href_ar if lang == "ar" else href_en
    other_href = href_ar if lang == "en" else site_root or "../"

    # A Latin district name inside an Arabic sentence is reordered by the bidi
    # algorithm and lands on its own line, reading as though it were pasted in —
    # "طب أسنان حديث ولطيف في Mankhool". The area names come from a Google
    # listing in English, and inventing an Arabic rendering of a Dubai district
    # would be exactly the fabrication this template refuses elsewhere. So the
    # Arabic headline drops the area unless the area itself is Arabic; the
    # address block still shows the real location either way.
    use_area = bool(area_x) and (lang != "ar" or _has_arabic(area_x))
    headline = strings.headline_template.format(area=area_x) if use_area else strings.headline_plain
    lead_area = area_x if use_area else ""
    lead = (
        strings.lead_template.format(name=name_x, area=lead_area)
        if lead_area
        else strings.lead_plain.format(name=name_x)
    )
    description = strings.description_template.format(
        name=name_x, area_clause=f" — {area_x}" if area_x else ""
    )

    # Buttons exist only when there is something real behind them. A "Call now"
    # that dials nothing is discovered by the visitor who most wanted to use it.
    header_cta = f'<a class="call" href="tel:{e(dial)}">{strings.call} {e(phone.strip())}</a>' if dial else ""
    maps_url = (
        "https://www.google.com/maps/search/?api=1&query=" + quote(f"{name} {address}")
        if address
        else ""
    )

    ctas = ""
    if dial:
        ctas += f'<a class="btn btn-primary" href="tel:{e(dial)}">{strings.call} {e(phone.strip())}</a>'
    if booking_url:
        ctas += f'<a class="btn btn-ghost" href="{e(booking_url)}" rel="noopener">{strings.book_heading}</a>'
    else:
        # "Book" is only truthful when it reaches a real provider (the branch
        # above). Pointing it at the placeholder form would promise a booking
        # that no backend can make — the one claim on these pages that would
        # reach a patient rather than a prospect. The label matches what the
        # form actually does: it takes a request.
        ctas += f'<a class="btn btn-ghost" href="#request">{strings.request_heading}</a>'
    if wa:
        ctas += f'<a class="btn btn-ghost" href="https://wa.me/{e(wa)}" rel="noopener">{strings.whatsapp}</a>'
    if maps_url:
        ctas += f'<a class="btn btn-ghost" href="{maps_url}" rel="noopener">{strings.directions}</a>'

    sticky = ""
    if dial:
        sticky += f'<a class="s-call" href="tel:{e(dial)}">{strings.call}</a>'
    # Same rule as the hero CTA: "Book" only where a real provider is wired.
    sticky_book = strings.book_heading if booking_url else strings.request_heading
    sticky += (
        f'<a class="s-book" href="{e(booking_url) if booking_url else "#request"}">'
        f"{sticky_book}</a>"
    )
    if wa:
        sticky += f'<a class="s-wa" href="https://wa.me/{e(wa)}" rel="noopener">{strings.whatsapp}</a>'
    if maps_url:
        sticky += f'<a class="s-map" href="{maps_url}" rel="noopener">{strings.directions}</a>'

    service_cards = "".join(
        f'<div class="card"><div class="ico">{_ICON.format(ICONS.get(icon, ICONS["tooth"]))}</div>'
        f"<h3>{e(title)}</h3><p>{e(blurb)}</p></div>"
        for title, icon, blurb in services
    )
    assurance_cards = "".join(
        f'<div class="card"><h3>{e(title)}</h3><p>{e(blurb)}</p></div>' for title, blurb in assurances
    )

    rows = ""
    if address:
        rows += f"<dt>{strings.address}</dt><dd>{e(address)}</dd>"
    if phone:
        rows += f'<dt>{strings.phone_label}</dt><dd><a href="tel:{e(dial)}">{e(phone.strip())}</a></dd>'
    if wa:
        rows += f'<dt>{strings.whatsapp}</dt><dd><a href="https://wa.me/{e(wa)}" rel="noopener">{strings.whatsapp}</a></dd>'
    if area_x:
        rows += f"<dt>{strings.area}</dt><dd>{area_x}</dd>"
    if not rows:
        rows = f"<dt>{strings.nav_contact}</dt><dd>{strings.contact_tbc}</dd>"

    # Hours are stated or absent. Guessing them sends a patient to a locked door.
    hours_block = ""
    if hours:
        items = "".join(
            f"<li><span>{e(_localise_day(day, lang))}</span>"
            f"<span>{e(_localise_time(time, lang))}</span></li>"
            for day, time in hours
        )
        hours_block = (
            f'<div class="info"><h3 style="margin-top:0">{strings.hours_heading}</h3>'
            f'<ul class="plain hours">{items}</ul></div>'
        )

    return PAGE.format(
        lang=strings.lang,
        dir=strings.direction,
        title=f"{name_x} | {strings.clinic_label}{f' — {area_x}' if area_x else ''}",
        og_title=name_x,
        description=e(description),
        canonical=e(canonical),
        href_en=e(href_en),
        href_ar=e(href_ar),
        other_href=e(other_href),
        other_lang="ar" if lang == "en" else "en",
        other_language=strings.other_language,
        name=name_x,
        tagline_short=e(f"{strings.clinic_label}{f' · {area}' if area else ''}"),
        headline=headline,
        tagline=lead,
        header_cta=header_cta,
        hero_ctas=ctas,
        final_ctas=ctas,
        sticky=sticky,
        hero_art=HERO_ART,
        services=service_cards,
        assurances=assurance_cards,
        contact_rows=rows,
        hours_block=hours_block,
        closing=strings.book_sub_with_phone if dial else strings.book_sub_without_phone,
        nav_services=strings.nav_services,
        nav_visit=strings.nav_visit,
        nav_contact=strings.nav_contact,
        services_heading=strings.services_heading,
        services_sub=strings.services_sub,
        why_heading=strings.why_heading,
        why_sub=strings.why_sub,
        visit_heading=strings.visit_heading,
        visit_sub=strings.visit_sub,
        book_heading=strings.book_heading,
        request_heading=strings.request_heading,
        request_sub=strings.request_sub,
        field_name=strings.field_name,
        field_phone=strings.field_phone,
        field_when=strings.field_when,
        field_service=strings.field_service,
        field_message=strings.field_message,
        request_submit=strings.request_submit,
        request_notice=strings.request_notice,
        service_options="".join(f"<option>{e(s[0])}</option>" for s in services),
        not_implemented_js=json.dumps(strings.request_not_implemented),
        year=year,
        footer_location=e(address or area or ""),
        structured=_structured_data(
            name=name, phone=dial, address=address, url=canonical, hours=hours
        ),
    )


def _localise_day(day: str, lang: str) -> str:
    """Translate a day label only when it is one we recognise.

    An unrecognised label is passed through untouched. The hours came from the
    clinic's own listing, and mangling "Sat-Thu" into something plausible-looking
    would be inventing information about when they are open.
    """
    if lang != "ar":
        return day
    return _strings.DAYS_AR.get(day.strip().lower(), day)


def _localise_time(value: str, lang: str) -> str:
    """Arabic meridiem markers, and nothing else.

    ص / م are the standard Arabic forms of AM / PM. This is a change of
    notation, not of information: the digits are untouched, so no time can move
    by this function. Anything it does not recognise is left exactly as the
    clinic's listing gave it.
    """
    if lang != "ar":
        return value
    return _AM.sub("ص", _PM.sub("م", value))


def render_site(
    *,
    name: str,
    phone: str = "",
    address: str = "",
    area: str = "Dubai",
    base_url: str = "",
    hours: list[tuple[str, str]] | None = None,
    booking_url: str = "",
    year: int = 2026,
) -> dict[str, str]:
    """Every file the published site consists of.

    Two languages as separate URLs rather than a client-side toggle: a search
    engine can index both, `hreflang` can point at them, and a visitor who lands
    on the Arabic page from a search result stays there.
    """
    canonical = f"{base_url.rstrip('/')}/" if base_url else ""
    common = dict(
        name=name, phone=phone, address=address, area=area, hours=hours,
        booking_url=booking_url, year=year, base_url=base_url,
    )
    files = {
        "index.html": render(**common, url=canonical, lang="en"),
        "ar/index.html": render(**common, url=canonical, lang="ar"),
    }
    if canonical:
        files["robots.txt"] = f"User-agent: *\nAllow: /\nSitemap: {canonical}sitemap.xml\n"
        files["sitemap.xml"] = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n'
            f"  <url><loc>{canonical}</loc>\n"
            f'    <xhtml:link rel="alternate" hreflang="en" href="{canonical}"/>\n'
            f'    <xhtml:link rel="alternate" hreflang="ar" href="{canonical}ar/"/>\n'
            "  </url>\n"
            f"  <url><loc>{canonical}ar/</loc></url>\n"
            "</urlset>\n"
        )
    return files
