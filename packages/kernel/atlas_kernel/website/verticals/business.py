"""A composable site for any local business, in English and Arabic.

`dental.py` proved the shape and is now load-bearing: twenty live demos and two
approved outreach messages point at pages it renders. So this is a second
renderer rather than a refactor of that one — the sales experiment must not move
while the product broadens underneath it.

What differs is that nothing here is industry-specific. A `Business` carries its
own sections, its own words, and its own schema.org type, in both languages. The
template arranges them and adds the parts every local business needs: address,
hours, map, tap-to-call, WhatsApp where the number can receive it, and a sticky
call bar on mobile.

The rules from `dental.py` carry over unchanged, because they are about honesty
rather than about dentistry:

- **Every fact comes from the caller.** No invented staff, no invented
  certifications, no invented reviews, no stock photography implying premises.
- **WhatsApp only on a mobile that can receive it.** `wa.me` on a landline is a
  dead link.
- **Nothing books.** Enquiry and reservation sections take a *request* and say
  so, in the page's own language.
- **Both languages are authored, not translated at render time.** A caller
  supplies English and Arabic; anything it does not supply is left out rather
  than guessed.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from typing import Literal

Lang = Literal["en", "ar"]

#: The only numbers WhatsApp can deliver to.
_UAE_MOBILE = re.compile(r"^0?5[024568]\d{7}$")
_SAFE_DIAL = re.compile(r"[^0-9+]")


def e(value: str) -> str:
    return html.escape(str(value or ""), quote=True)


@dataclass(frozen=True)
class Text:
    """One string in both languages. Arabic is authored, never machine-made."""

    en: str
    ar: str

    def get(self, lang: Lang) -> str:
        return self.ar if lang == "ar" else self.en


@dataclass(frozen=True)
class Item:
    """One thing the business offers — a dish, a treatment, a service."""

    name: Text
    detail: Text
    #: Optional, and shown verbatim. A price the caller did not give is not
    #: invented; the field simply stays empty.
    price: str = ""


@dataclass(frozen=True)
class Group:
    """A titled set of items — a menu category, a service group."""

    title: Text
    items: tuple[Item, ...]


@dataclass(frozen=True)
class Question:
    question: Text
    answer: Text


@dataclass(frozen=True)
class Business:
    """Everything the renderer is allowed to know."""

    name: str
    #: schema.org type. Wrong here is worse than absent — it tells Google the
    #: business is something it is not.
    schema_type: str
    tagline: Text
    intro: Text
    area: str = "Dubai"
    phone: str = ""
    address: str = ""
    hours: tuple[tuple[str, Text], ...] = ()

    #: The main offering, however the industry names it.
    offering_heading: Text = Text("What we offer", "ما نقدمه")
    offering_note: Text = Text("", "")
    groups: tuple[Group, ...] = ()

    #: Short reasons to choose them. Claims about *them*, supplied by them.
    highlights: tuple[Item, ...] = ()

    faq: tuple[Question, ...] = ()

    #: What the enquiry section is called. "Reserve a table" and "Request a
    #: quote" are different promises, and both are still requests.
    request_heading: Text = Text("Send an enquiry", "أرسل استفساراً")
    request_note: Text = Text(
        "This form is part of a demonstration and is not connected yet. "
        "Please call or message directly.",
        "هذا النموذج جزء من عرض توضيحي وغير متصل بعد. يرجى الاتصال أو المراسلة مباشرة.",
    )
    cta_label: Text = Text("Send enquiry", "إرسال الاستفسار")

    #: Marks the page as a Qevik demonstration rather than a live business site.
    demo_notice: Text = field(
        default_factory=lambda: Text(
            "Sample site built by Qevik. Not a real business.",
            "موقع نموذجي من إعداد Qevik. ليس نشاطاً تجارياً حقيقياً.",
        )
    )


CHROME: dict[Lang, dict[str, str]] = {
    "en": {
        "dir": "ltr",
        "call": "Call",
        "directions": "Directions",
        "whatsapp": "WhatsApp",
        "enquire": "Enquire",
        "visit": "Visit us",
        "hours": "Opening hours",
        "address": "Address",
        "phone": "Phone",
        "area": "Area",
        "why": "Why choose us",
        "faq": "Common questions",
        "name_field": "Name",
        "phone_field": "Phone number",
        "message_field": "Message",
        "other_lang": "العربية",
        "not_sent": "Not sent — this demonstration form is not connected yet. "
        "Please call directly.",
    },
    "ar": {
        "dir": "rtl",
        "call": "اتصل",
        "directions": "الاتجاهات",
        "whatsapp": "واتساب",
        "enquire": "استفسر",
        "visit": "زورونا",
        "hours": "ساعات العمل",
        "address": "العنوان",
        "phone": "الهاتف",
        "area": "المنطقة",
        "why": "لماذا نحن",
        "faq": "أسئلة شائعة",
        "name_field": "الاسم",
        "phone_field": "رقم الهاتف",
        "message_field": "الرسالة",
        "other_lang": "English",
        "not_sent": "لم يتم الإرسال — هذا النموذج التوضيحي غير متصل بعد. "
        "يرجى الاتصال مباشرة.",
    },
}

_AM = re.compile(r"\bAM\b", re.IGNORECASE)
_PM = re.compile(r"\bPM\b", re.IGNORECASE)


def dial(phone: str) -> str:
    return _SAFE_DIAL.sub("", phone or "")


def whatsapp_number(phone: str) -> str:
    """The number to use on `wa.me`, or empty when it cannot receive.

    Same rule as the dental template: sixteen of twenty audited clinics publish
    a landline, and a WhatsApp link on one is not an error the visitor sees — it
    is a dead end they blame the business for.
    """
    digits = re.sub(r"\D", "", phone or "")
    national = digits[3:] if digits.startswith("971") else digits
    return f"971{national.lstrip('0')}" if _UAE_MOBILE.match(national) else ""


def localise_time(value: str, lang: Lang) -> str:
    """ص / م in Arabic. Notation only — the digits are untouched."""
    return _AM.sub("ص", _PM.sub("م", value)) if lang == "ar" else value


STYLE = """
:root{--ink:#16211F;--ink-2:#3B4A48;--stone:#6B7B79;--ground:#FBFAF8;--surface:#fff;
--surface-2:#F3F2ED;--hair:#E3E2DA;--brand:__BRAND__;--brand-deep:__BRAND_DEEP__;
--accent:__ACCENT__;--radius:10px;
--display:"Charter","Iowan Old Style",Palatino,Georgia,serif;
--body:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--body);
font-size:17px;line-height:1.6;-webkit-font-smoothing:antialiased;padding-bottom:76px}
.wrap{max-width:1000px;margin:0 auto;padding:0 clamp(1rem,4vw,2rem)}
h1,h2,h3{font-family:var(--display);letter-spacing:-.015em;text-wrap:balance}
h1{font-size:clamp(1.9rem,5.4vw,3rem);line-height:1.08;margin:0 0 .8rem}
h2{font-size:clamp(1.35rem,3.2vw,1.9rem);line-height:1.2;margin:0 0 .6rem}
h3{font-family:var(--body);font-weight:650;font-size:1rem;margin:0 0 .3rem;letter-spacing:0}
p{margin:0 0 .9rem;max-width:62ch}
a{color:var(--brand)}
.top{background:var(--surface);border-bottom:1px solid var(--hair);position:sticky;top:0;z-index:5}
.top .wrap{display:flex;align-items:center;gap:1rem;padding-top:.7rem;padding-bottom:.7rem;flex-wrap:wrap}
.bname{font-family:var(--display);font-size:1.15rem;font-weight:600;flex:1 1 auto}
.bname small{display:block;font-family:var(--body);font-size:.76rem;color:var(--stone);font-weight:400}
.lang{border:1px solid var(--hair);border-radius:999px;padding:.28rem .8rem;font-size:.82rem;
text-decoration:none;color:var(--ink-2);white-space:nowrap}
.hero{padding:clamp(2.2rem,7vw,4rem) 0;background:linear-gradient(180deg,var(--surface) 0%,var(--ground) 100%)}
.hero p.lead{font-size:clamp(1.02rem,2vw,1.15rem);color:var(--ink-2);max-width:52ch}
.btns{display:flex;flex-wrap:wrap;gap:.6rem;margin-top:1.4rem}
.btn{display:inline-block;padding:.7rem 1.2rem;border-radius:8px;border:1px solid var(--hair);
background:var(--surface);color:var(--ink);font-weight:600;font-size:.95rem;text-decoration:none}
.btn.p{background:var(--brand);border-color:var(--brand);color:#fff}
.btn.a{background:var(--accent);border-color:var(--accent);color:#16211F}
section.band{padding:clamp(2.2rem,6vw,3.6rem) 0;border-top:1px solid var(--hair)}
section.band.alt{background:var(--surface-2)}
.sub{color:var(--ink-2);max-width:58ch;margin-bottom:1.6rem}
.group{margin:0 0 2rem}
.group h3{font-family:var(--display);font-size:1.15rem;font-weight:600;margin:0 0 .8rem;
padding-bottom:.4rem;border-bottom:2px solid var(--brand);display:inline-block}
.items{display:grid;gap:.7rem;grid-template-columns:repeat(auto-fit,minmax(250px,1fr))}
.item{background:var(--surface);border:1px solid var(--hair);border-radius:var(--radius);padding:.9rem 1.05rem}
.item .row{display:flex;justify-content:space-between;gap:.8rem;align-items:baseline}
.item h4{margin:0;font-size:.98rem;font-weight:650}
.item .price{font-weight:650;color:var(--brand);white-space:nowrap;font-size:.94rem}
.item p{margin:.25rem 0 0;font-size:.9rem;color:var(--ink-2)}
.cards{display:grid;gap:.8rem;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));margin-top:1.4rem}
.card{background:var(--surface);border:1px solid var(--hair);border-left:3px solid var(--brand);
border-radius:8px;padding:1rem 1.15rem}
.card p{margin:0;font-size:.92rem;color:var(--ink-2)}
.info{background:var(--surface);border:1px solid var(--hair);border-radius:var(--radius);padding:1.2rem 1.35rem}
dl.nap{margin:0;display:grid;grid-template-columns:auto 1fr;gap:.45rem 1.1rem;font-size:.94rem}
dl.nap dt{color:var(--stone);font-size:.82rem;padding-top:.1rem}
dl.nap dd{margin:0}
ul.hours{list-style:none;margin:.4rem 0 0;padding:0}
ul.hours li{display:flex;justify-content:space-between;gap:1rem;padding:.32rem 0;
border-bottom:1px solid var(--hair);font-size:.93rem}
ul.hours li:last-child{border-bottom:none}
details{background:var(--surface);border:1px solid var(--hair);border-radius:8px;
padding:.8rem 1.05rem;margin:0 0 .6rem}
summary{cursor:pointer;font-weight:600;font-size:.96rem}
details[open] summary{margin-bottom:.5rem}
details p{margin:0;font-size:.93rem;color:var(--ink-2)}
form{display:grid;gap:.7rem;max-width:520px;margin-top:1.2rem}
label{font-size:.86rem;color:var(--ink-2)}
input,textarea{width:100%;padding:.65rem .8rem;border:1px solid var(--hair);border-radius:8px;
font:inherit;font-size:.95rem;background:var(--surface);color:var(--ink)}
textarea{min-height:96px;resize:vertical}
.notice{display:none;padding:.75rem .9rem;border-radius:8px;background:#FBF1DD;
border:1px solid #E7D4A8;color:#7A4E08;font-size:.9rem}
.notice.shown{display:block}
.formnote{font-size:.84rem;color:var(--stone);max-width:52ch}
.sticky{position:fixed;left:0;right:0;bottom:0;z-index:9;display:flex;gap:.4rem;
padding:.5rem;background:color-mix(in srgb,var(--surface) 94%,transparent);
border-top:1px solid var(--hair);backdrop-filter:blur(8px)}
.sticky a{flex:1 1 0;text-align:center;padding:.65rem .4rem;border-radius:8px;
font-size:.88rem;font-weight:650;text-decoration:none;border:1px solid var(--hair);
background:var(--surface);color:var(--ink)}
.sticky a.p{background:var(--brand);border-color:var(--brand);color:#fff}
.sticky a.w{background:#25D366;border-color:#25D366;color:#08301A}
footer{border-top:1px solid var(--hair);background:var(--surface-2);
padding:1.6rem 0 2rem;margin-top:0;font-size:.88rem;color:var(--stone)}
.demo-flag{background:#16211F;color:#F3F2ED;font-size:.8rem;padding:.5rem 0;text-align:center}
[dir="rtl"] .item .row,[dir="rtl"] ul.hours li{flex-direction:row-reverse}
[dir="rtl"] dl.nap{direction:rtl}
@media (max-width:560px){.items{grid-template-columns:1fr}}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
"""


def _schema(biz: Business, url: str) -> str:
    data: dict[str, object] = {
        "@context": "https://schema.org",
        "@type": biz.schema_type,
        "name": biz.name,
        "url": url,
        "areaServed": biz.area,
    }
    if biz.phone:
        data["telephone"] = dial(biz.phone)
    if biz.address:
        data["address"] = {"@type": "PostalAddress", "streetAddress": biz.address}
    if biz.hours:
        data["openingHours"] = [f"{day} {hours.en}" for day, hours in biz.hours]
    # json.dumps escapes quotes but not "</script>", so a business name
    # containing markup closes the block and injects into the page. The names
    # here come from Google listings — untrusted input — and a script tag that
    # escapes its own container is a cross-site scripting hole, not a rendering
    # nit. Escaping "<" as \u003c keeps the JSON valid and inert.
    payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    return f'<script type="application/ld+json">{payload}</script>' 


def render(
    biz: Business,
    *,
    lang: Lang = "en",
    base_url: str = "",
    brand: str = "#0D6E6B",
    brand_deep: str = "#095351",
    accent: str = "#E9B44C",
    year: int = 2026,
) -> str:
    c = CHROME[lang]
    root = f"{base_url.rstrip('/')}/" if base_url else ""
    href_en, href_ar = root, f"{root}ar/" if root else "ar/"
    canonical = href_ar if lang == "ar" else href_en
    other = href_ar if lang == "en" else (root or "../")

    tel, wa = dial(biz.phone), whatsapp_number(biz.phone)
    maps = (
        "https://www.google.com/maps/search/?api=1&query="
        + e(f"{biz.name} {biz.address}".replace(" ", "+"))
        if biz.address
        else ""
    )

    buttons = []
    if tel:
        buttons.append(f'<a class="btn p" href="tel:{e(tel)}">{c["call"]} {e(biz.phone)}</a>')
    buttons.append(f'<a class="btn a" href="#request">{e(biz.request_heading.get(lang))}</a>')
    if wa:
        buttons.append(f'<a class="btn" href="https://wa.me/{wa}" rel="noopener">{c["whatsapp"]}</a>')
    if maps:
        buttons.append(f'<a class="btn" href="{maps}" rel="noopener">{c["directions"]}</a>')

    groups = ""
    for group in biz.groups:
        items = "".join(
            f'<div class="item"><div class="row"><h4>{e(item.name.get(lang))}</h4>'
            + (f'<span class="price">{e(item.price)}</span>' if item.price else "")
            + f"</div><p>{e(item.detail.get(lang))}</p></div>"
            for item in group.items
        )
        groups += (
            f'<div class="group"><h3>{e(group.title.get(lang))}</h3>'
            f'<div class="items">{items}</div></div>'
        )

    highlights = "".join(
        f'<div class="card"><h3>{e(h.name.get(lang))}</h3><p>{e(h.detail.get(lang))}</p></div>'
        for h in biz.highlights
    )

    faq = "".join(
        f"<details><summary>{e(q.question.get(lang))}</summary>"
        f"<p>{e(q.answer.get(lang))}</p></details>"
        for q in biz.faq
    )

    hours_rows = "".join(
        f"<li><span>{e(day.get(lang) if isinstance(day, Text) else day)}</span>"
        f"<span>{e(localise_time(value.get(lang), lang))}</span></li>"
        for day, value in biz.hours
    )

    nap = ""
    if biz.address:
        nap += f'<dt>{c["address"]}</dt><dd>{e(biz.address)}</dd>'
    if biz.phone:
        nap += f'<dt>{c["phone"]}</dt><dd><a href="tel:{e(tel)}">{e(biz.phone)}</a></dd>'
    nap += f'<dt>{c["area"]}</dt><dd>{e(biz.area)}</dd>'

    sticky = ""
    if tel:
        sticky += f'<a class="p" href="tel:{e(tel)}">{c["call"]}</a>'
    sticky += f'<a href="#request">{e(biz.cta_label.get(lang))}</a>'
    if wa:
        sticky += f'<a class="w" href="https://wa.me/{wa}" rel="noopener">{c["whatsapp"]}</a>'
    if maps:
        sticky += f'<a href="{maps}" rel="noopener">{c["directions"]}</a>'

    # Token replacement rather than %-formatting: the stylesheet is full of
    # literal percentages (100%, 94%) and every one of them would need escaping.
    style = (
        STYLE.replace("__BRAND__", brand)
        .replace("__BRAND_DEEP__", brand_deep)
        .replace("__ACCENT__", accent)
    )
    title = f"{biz.name} — {biz.tagline.get(lang)}"

    return f"""<!doctype html>
<html lang="{lang}" dir="{c['dir']}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(biz.intro.get(lang)[:180])}">
<link rel="canonical" href="{e(canonical)}">
<link rel="alternate" hreflang="en" href="{e(href_en)}">
<link rel="alternate" hreflang="ar" href="{e(href_ar)}">
<link rel="alternate" hreflang="x-default" href="{e(href_en)}">
<meta property="og:type" content="website">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(biz.intro.get(lang)[:180])}">
<meta property="og:url" content="{e(canonical)}">
<meta name="theme-color" content="{brand}">
<style>{style}</style>
{_schema(biz, canonical)}
</head>
<body>
<div class="demo-flag">{e(biz.demo_notice.get(lang))}</div>
<header class="top"><div class="wrap">
  <div class="bname">{e(biz.name)}<small>{e(biz.tagline.get(lang))} · {e(biz.area)}</small></div>
  <a class="lang" href="{e(other)}">{c['other_lang']}</a>
</div></header>

<main>
<section class="hero"><div class="wrap">
  <h1>{e(biz.tagline.get(lang))}</h1>
  <p class="lead">{e(biz.intro.get(lang))}</p>
  <div class="btns">{''.join(buttons)}</div>
</div></section>

{f'''<section class="band"><div class="wrap">
  <h2>{e(biz.offering_heading.get(lang))}</h2>
  {f'<p class="sub">{e(biz.offering_note.get(lang))}</p>' if biz.offering_note.get(lang) else ''}
  {groups}
</div></section>''' if groups else ''}

{f'''<section class="band alt"><div class="wrap">
  <h2>{c['why']}</h2><div class="cards">{highlights}</div>
</div></section>''' if highlights else ''}

<section class="band"><div class="wrap">
  <h2>{c['visit']}</h2>
  <div class="info">
    <dl class="nap">{nap}</dl>
    {f'<h3 style="margin-top:1.1rem">{c["hours"]}</h3><ul class="hours">{hours_rows}</ul>' if hours_rows else ''}
  </div>
</div></section>

{f'''<section class="band alt"><div class="wrap">
  <h2>{c['faq']}</h2>{faq}
</div></section>''' if faq else ''}

<section class="band" id="request"><div class="wrap">
  <h2>{e(biz.request_heading.get(lang))}</h2>
  <p class="sub">{e(biz.request_note.get(lang))}</p>
  <form id="request-form">
    <div><label for="rf-name">{c['name_field']}</label><input id="rf-name" name="name" required></div>
    <div><label for="rf-phone">{c['phone_field']}</label><input id="rf-phone" name="phone" type="tel" required></div>
    <div><label for="rf-msg">{c['message_field']}</label><textarea id="rf-msg" name="message"></textarea></div>
    <div class="notice" id="rf-notice" role="status"></div>
    <button class="btn p" type="submit">{e(biz.cta_label.get(lang))}</button>
    <p class="formnote">{e(biz.request_note.get(lang))}</p>
  </form>
</div></section>
</main>

<footer><div class="wrap">
  <p>{e(biz.name)} · {e(biz.area)} · &copy; {year}</p>
  <p>{e(biz.demo_notice.get(lang))}</p>
</div></footer>

<nav class="sticky" aria-label="{c['call']}">{sticky}</nav>

<script>
// No backend exists. Saying so is the only honest thing the form can do — a
// success message here would tell a real person their request was received.
document.getElementById('request-form').addEventListener('submit', function (event) {{
  event.preventDefault();
  var notice = document.getElementById('rf-notice');
  notice.textContent = {json.dumps(c["not_sent"], ensure_ascii=True)};
  notice.className = 'notice shown';
}});
</script>
</body>
</html>
"""


def render_site(
    biz: Business,
    *,
    base_url: str = "",
    brand: str = "#0D6E6B",
    brand_deep: str = "#095351",
    accent: str = "#E9B44C",
    year: int = 2026,
) -> dict[str, str]:
    """Both languages, plus robots and a sitemap covering both."""
    common = {
        "base_url": base_url,
        "brand": brand,
        "brand_deep": brand_deep,
        "accent": accent,
        "year": year,
    }
    files = {
        "index.html": render(biz, lang="en", **common),
        "ar/index.html": render(biz, lang="ar", **common),
    }
    root = f"{base_url.rstrip('/')}/" if base_url else ""
    if root:
        files["robots.txt"] = f"User-agent: *\nAllow: /\nSitemap: {root}sitemap.xml\n"
        files["sitemap.xml"] = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n'
            f"  <url><loc>{root}</loc>\n"
            f'    <xhtml:link rel="alternate" hreflang="en" href="{root}"/>\n'
            f'    <xhtml:link rel="alternate" hreflang="ar" href="{root}ar/"/>\n'
            "  </url>\n"
            f"  <url><loc>{root}ar/</loc></url>\n"
            "</urlset>\n"
        )
    return files
