"""Generate the AHS concept — every route, both languages.

Why a generator and not another single file: their real site separates the work,
the services and the writing into pages, and collapsing that into one scroll
because one file is easier to write would be removing their architecture rather
than improving it. Ninety-eight routes cannot be hand-maintained.

The one thing this must never do is invent. Every fact comes from `source.py`,
and where a field is `None` the page prints "not published" — which is the whole
argument being made to AHS, in their own data.
"""

from __future__ import annotations

import hashlib
import html
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import source as S               # noqa: E402
from deck import ARTICLE_AR, KIND_AR, SECTOR_AR, SERVICE_AR, STEPS, T  # noqa: E402

BASE = "/sample-ahs"
LIVE = "https://sites.qevik.ai/sample-ahs"
e = lambda s: html.escape(str(s), quote=True)


def path(lang: str, *parts: str) -> str:
    """A route, always with a trailing slash so relative links behave."""
    prefix = f"{BASE}/ar" if lang == "ar" else BASE
    return "/".join([prefix, *[p for p in parts if p]]) + "/"


def label(lang: str, en: str, ar: str) -> str:
    return ar if lang == "ar" else en


def sector_name(lang: str, key: str) -> str:
    return SECTOR_AR[key] if lang == "ar" else S.SECTORS[key]


def kind_name(lang: str, kind: str | None) -> str:
    """Their page titles stay verbatim; our classification of them is translated."""
    if not kind:
        return ""
    return KIND_AR.get(kind, kind) if lang == "ar" else kind


def service_name(lang: str, svc: S.Service) -> str:
    return SERVICE_AR[svc.slug] if lang == "ar" else svc.name


def service_href(lang: str, svc: S.Service) -> str:
    """EATLUX is their own sub-brand and gets one route, not two.

    It sits in SERVICES because they sell it as one, but giving it both
    /eatlux/ and /services/eatlux/ would be the same duplicate-route fault the
    concept points out on their site — two corporate-catering URLs, three
    Ramadan pages — committed while criticising it.
    """
    return path(lang, "eatlux") if svc.slug == "eatlux" else path(lang, "services", svc.slug)


# --------------------------------------------------------------------- style
CSS = """
*,*::before,*::after{box-sizing:border-box}
:root{
  --night:#0C0B09; --night-2:#141210; --night-3:#1C1917;
  --gold:#C9A227; --gold-lift:#E1C25F; --linen:#EFE9DD; --linen-2:#E4DCCC;
  --sage:#6E7A5E; --ink:#17150F;
  --ash:#8A8377;            /* warm grey, biased gold — not a neutral by default */
  --ash-2:#5D584E;
  --rule:rgba(201,162,39,.22);
  --measure:64ch;
  --display:"Iowan Old Style","Palatino Linotype",Palatino,"Book Antiqua",Georgia,serif;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}
[lang=ar]{--display:"Iowan Old Style","Times New Roman",serif;
  --sans:"Segoe UI","Noto Naskh Arabic",-apple-system,system-ui,sans-serif}
html{-webkit-text-size-adjust:100%;scroll-behavior:smooth}
/* The masthead is sticky, so anything scrolled to the top of the viewport ends
   up underneath it — an in-page anchor lands on a heading the header is
   covering, and a control there cannot be clicked at all. */
section,.chip,.rec,.stepq,h1,h2,[id]{scroll-margin-top:86px}
body{margin:0;background:var(--night);color:var(--linen);font:400 17px/1.65 var(--sans);
  overflow-x:hidden}
img{max-width:100%;display:block}
a{color:inherit}
:focus-visible{outline:2px solid var(--gold-lift);outline-offset:3px}
.skip{position:absolute;inset-inline-start:-9999px;top:0;background:var(--gold);color:var(--ink);
  padding:.7rem 1rem;z-index:99}
.skip:focus{inset-inline-start:0}
.wrap{width:min(1180px,100% - 3rem);margin-inline:auto}
.narrow{width:min(760px,100% - 3rem);margin-inline:auto}
.engraved{font:600 11px/1 var(--sans);letter-spacing:.22em;text-transform:uppercase;
  color:var(--gold)}
.deck{font:300 clamp(2rem,4.6vw,3.5rem)/1.06 var(--display);letter-spacing:-.015em;margin:0;
  text-wrap:balance}
.deck em{font-style:italic;color:var(--gold-lift)}
.lead{color:var(--ash);max-width:var(--measure);margin:.9rem 0 0}
.tab{font-variant-numeric:tabular-nums}

/* masthead ------------------------------------------------------------- */
.mast{position:sticky;top:0;z-index:40;background:rgba(12,11,9,.86);
  backdrop-filter:blur(12px);border-bottom:1px solid var(--rule)}
.mast .wrap{display:flex;align-items:center;gap:1.4rem;min-height:66px}
.mark{font:400 20px/1 var(--display);letter-spacing:.3em;color:var(--gold);text-decoration:none;
  display:block}
.mark small{display:block;font:600 8px/1.6 var(--sans);letter-spacing:.26em;color:var(--ash);
  text-transform:uppercase}
.mast nav{margin-inline-start:auto;display:flex;gap:1.3rem;align-items:center}
.mast nav a{font:500 12px/1 var(--sans);letter-spacing:.13em;text-transform:uppercase;
  color:var(--linen);text-decoration:none;opacity:.82}
.mast nav a:hover,.mast nav a[aria-current=page]{opacity:1;color:var(--gold-lift)}
.mast .cta{background:none;border:1px solid var(--gold);padding:.55rem .9rem;
  color:var(--gold);opacity:1;letter-spacing:.13em}
.mast .cta:hover{background:var(--gold);color:var(--ink)}
.lang{font:600 11px/1 var(--sans);letter-spacing:.1em;border:1px solid var(--rule);
  padding:.45rem .6rem;text-decoration:none;color:var(--ash)}
.lang:hover{color:var(--gold-lift);border-color:var(--gold)}
.burger{display:none;margin-inline-start:auto;background:none;border:1px solid var(--rule);
  color:var(--linen);width:42px;height:38px;font-size:15px;cursor:pointer}

/* composed image treatments -------------------------------------------- */
.plate{position:relative;background:var(--night-2);overflow:hidden;isolation:isolate}
.plate{background:
  radial-gradient(85% 70% at 26% 18%,rgba(225,194,95,.34),transparent 58%),
  radial-gradient(70% 65% at 82% 88%,rgba(110,122,94,.30),transparent 60%),
  radial-gradient(60% 50% at 62% 42%,rgba(201,162,39,.14),transparent 70%),
  linear-gradient(155deg,#241F18 0%,#15120E 46%,#0A0907 100%)}
.plate::before{content:"";position:absolute;inset:0;z-index:1;opacity:.5;
  background:repeating-linear-gradient(112deg,rgba(255,255,255,.035) 0 1px,transparent 1px 7px)}
.plate::after{content:"";position:absolute;inset:0;z-index:1;
  background:radial-gradient(120% 95% at 50% 40%,transparent 38%,rgba(6,5,4,.72) 100%)}
.plate .note{position:absolute;inset-inline:0;bottom:0;z-index:2;padding:.5rem .7rem;
  font:400 9px/1.4 var(--mono);letter-spacing:.06em;color:rgba(239,233,221,.5);
  text-transform:uppercase}
.ratio{width:100%;aspect-ratio:4/3}
.ratio.tall{aspect-ratio:3/4}
.ratio.wide{aspect-ratio:16/9}

/* the ledger — the work index ------------------------------------------ */
.filters{position:sticky;top:66px;z-index:30;background:var(--night);
  border-bottom:1px solid var(--rule);padding:.9rem 0}
.filters .row{display:flex;gap:.45rem;flex-wrap:wrap;align-items:center}
.filters .row+.row{margin-top:.55rem}
.filters .cap{font:600 10px/1 var(--sans);letter-spacing:.18em;text-transform:uppercase;
  color:var(--ash-2);min-width:64px}
.chip{background:none;border:1px solid var(--rule);color:var(--linen);font:500 12px/1 var(--sans);
  padding:.42rem .7rem;cursor:pointer;white-space:nowrap}
.chip:hover{border-color:var(--gold)}
.chip[aria-pressed=true]{background:var(--gold);border-color:var(--gold);color:var(--ink)}
.ledger{border-top:1px solid var(--rule);margin-top:1.6rem}
.rec{display:grid;grid-template-columns:2.1fr 1fr 1fr auto;gap:1rem;align-items:baseline;
  padding:1.05rem .2rem;border-bottom:1px solid rgba(201,162,39,.12);text-decoration:none;
  color:inherit;transition:background .14s}
.rec:hover{background:var(--night-2)}
.rec .t{font:400 19px/1.25 var(--display)}
.rec .c{color:var(--gold-lift);font-size:14px}
.rec .m{color:var(--ash-2);font-size:12px;letter-spacing:.09em;text-transform:uppercase}
.rec .n{color:var(--ash-2);font:400 12px/1 var(--mono)}
.rec .miss{color:var(--ash-2);font-size:12px;font-style:italic}
.tally{display:flex;gap:1.6rem;flex-wrap:wrap;margin-top:1.4rem;color:var(--ash-2);
  font:400 12px/1 var(--mono);letter-spacing:.08em;text-transform:uppercase}
.tally b{color:var(--gold-lift);font-weight:400;font-size:17px}
.empty{padding:3rem .2rem;color:var(--ash);font-style:italic}

/* case record ----------------------------------------------------------- */
.record{display:grid;grid-template-columns:1.1fr .9fr;gap:3rem;align-items:start}
.facts{border-top:1px solid var(--rule);margin:0}
.facts div{display:grid;grid-template-columns:9rem 1fr;gap:1rem;padding:.72rem 0;
  border-bottom:1px solid rgba(201,162,39,.12)}
.facts dt{color:var(--ash-2);font:600 10px/1.6 var(--sans);letter-spacing:.16em;
  text-transform:uppercase}
.facts dd{margin:0}
.facts .un dd{color:var(--ash-2);font-style:italic}
.facts .un dt{opacity:.55}
.gap{margin-top:1.5rem;border:1px solid var(--rule);padding:1rem 1.1rem;background:var(--night-2)}
.gap p{margin:.4rem 0 0;color:var(--ash);font-size:14px}

/* light sections -------------------------------------------------------- */
.light{background:var(--linen);color:var(--ink)}
.light .lead{color:#4A4438}
.light .engraved{color:#8A6D12}
.light .deck em{color:#8A6D12}
.pad{padding:clamp(3.4rem,7vw,6rem) 0}
.dark{background:var(--night)}

/* services / editorial -------------------------------------------------- */
.grid{display:grid;gap:1.4rem}
.g2{grid-template-columns:repeat(2,1fr)}.g3{grid-template-columns:repeat(3,1fr)}
.card{border:1px solid var(--rule);padding:1.4rem;text-decoration:none;color:inherit;
  display:block;transition:border-color .14s}
.card:hover{border-color:var(--gold)}
.card h3{font:400 22px/1.2 var(--display);margin:.7rem 0 .4rem}
.card p{margin:0;color:var(--ash);font-size:15px}
.bullets{list-style:none;padding:0;margin:1rem 0 0}
.bullets li{padding-inline-start:1.1rem;position:relative;color:var(--ash);font-size:15px;
  margin:.35rem 0}
.bullets li::before{content:"";position:absolute;inset-inline-start:0;top:.62em;width:5px;
  height:5px;background:var(--gold)}
.prose{max-width:var(--measure)}
.prose p{margin:1.05rem 0}
.prose h2{font:400 27px/1.25 var(--display);margin:2.3rem 0 .6rem}
.src{font:400 11px/1.6 var(--mono);color:var(--ash-2);letter-spacing:.05em}

/* the brief ------------------------------------------------------------- */
.brief-rail{border:1px solid var(--rule);padding:1.3rem;background:var(--night-2)}
.stepq+.stepq{margin-top:1.2rem;padding-top:1.2rem;border-top:1px solid rgba(201,162,39,.14)}
.stepq .n{font:400 11px/1 var(--mono);color:var(--gold)}
.stepq .q{font:600 11px/1 var(--sans);letter-spacing:.17em;text-transform:uppercase;
  color:var(--linen);margin:.45rem 0 .6rem}
.opts{display:flex;flex-wrap:wrap;gap:.4rem}
.summary{border:1px solid var(--rule);margin:1.6rem 0}
.summary div{display:grid;grid-template-columns:9rem 1fr;gap:1rem;padding:.62rem .9rem;
  border-bottom:1px solid rgba(201,162,39,.12)}
.summary div:last-child{border-bottom:0}
.summary dt{color:var(--ash-2);font:600 10px/1.7 var(--sans);letter-spacing:.16em;
  text-transform:uppercase}
.summary dd{margin:0;font-style:italic;color:var(--ash)}
.summary dd.set{font-style:normal;color:var(--linen)}
.fields{display:grid;grid-template-columns:1fr 1fr;gap:1.1rem 1.4rem}
.fields label{display:block}
.fields .full{grid-column:1/-1}
.fields span{display:block;font:600 10px/1.8 var(--sans);letter-spacing:.16em;
  text-transform:uppercase;color:var(--ash-2)}
.fields input,.fields textarea{width:100%;background:none;border:0;
  border-bottom:1px solid var(--rule);color:var(--linen);font:400 16px/1.6 var(--sans);
  padding:.4rem 0}
.fields input:focus,.fields textarea:focus{border-color:var(--gold);outline:none}
.cta{display:inline-block;background:var(--gold);color:var(--ink);border:0;
  font:600 12px/1 var(--sans);letter-spacing:.16em;text-transform:uppercase;padding:1rem 1.5rem;
  text-decoration:none;cursor:pointer}
.cta.ghost{background:none;border:1px solid var(--linen);color:var(--linen)}
.cta.wa{background:#1F7A3A;color:#fff}
.reach{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--rule);
  margin-top:1.4rem;border:1px solid var(--rule)}
.reach a{background:var(--night);padding:.95rem 1.1rem;text-decoration:none}
.reach .k{display:block;font:600 10px/1.8 var(--sans);letter-spacing:.16em;text-transform:uppercase;
  color:var(--ash-2)}
.reach .v{display:block;font-size:16px;color:var(--linen)}
.reach a.wa .v{color:#7BD69B}
.disclaim{color:var(--ash-2);font-size:13px;line-height:1.6;margin-top:1rem;max-width:var(--measure)}

/* persistent whatsapp --------------------------------------------------- */
.wafloat{position:fixed;inset-inline-end:18px;bottom:18px;z-index:45;width:52px;height:52px;
  border-radius:50%;background:#1F7A3A;display:grid;place-items:center;text-decoration:none;
  box-shadow:0 6px 22px rgba(0,0,0,.45)}
.wafloat svg{width:26px;height:26px;fill:#fff}
.wafloat:hover{background:#27924a}


/* footer ---------------------------------------------------------------- */
footer{border-top:1px solid var(--rule);padding:3rem 0 2.4rem;background:var(--night-2)}
.cols{display:grid;grid-template-columns:1.5fr 1fr 1fr;gap:2.4rem}
footer h3{font:600 10px/1 var(--sans);letter-spacing:.18em;text-transform:uppercase;
  color:var(--gold);margin:0 0 .9rem}
.blurb{color:var(--ash);font-size:15px;max-width:34ch}
.social{display:flex;gap:.5rem;margin-top:1rem}
.social a{border:1px solid var(--rule);padding:.42rem .7rem;font:600 10px/1 var(--sans);
  letter-spacing:.14em;text-transform:uppercase;color:var(--gold-lift);text-decoration:none}
.list{list-style:none;padding:0;margin:0}
.list li{margin:.42rem 0}
.list a{color:var(--linen);text-decoration:none;font-size:15px;opacity:.85}
.list a:hover{opacity:1;color:var(--gold-lift)}
.who a{color:var(--linen);text-decoration:none}
.who span{color:var(--ash-2)}
.fine{border-top:1px solid var(--rule);margin-top:2.4rem;padding-top:1.4rem;
  display:grid;grid-template-columns:1.6fr 1fr;gap:2rem;color:var(--ash-2);font-size:13px}
.fine b{color:var(--linen)}

.dock{display:none}
@media (max-width:900px){
  .dock{display:flex}
  body.has-dock .wafloat{bottom:82px}
  /* The dock is fixed to the bottom, so without clearance it sits on top of
     whatever the page ends with — on the homepage that is the brief itself,
     and the last row of chips could not be tapped at all. */
  body.has-dock{padding-bottom:84px}
  .record,.cols,.fine,.g3,.g2{grid-template-columns:1fr}
  .rec{grid-template-columns:1fr auto;gap:.3rem 1rem}
  .rec .m,.rec .c{grid-column:1}
  .mast nav{display:none;order:3;width:100%;flex-direction:column;align-items:flex-start;
    gap:.1rem;padding:.6rem 0 1rem}
  .mast nav a{padding:.6rem 0;font-size:14px}
  .mast[data-open=true] nav{display:flex}
  .mast .wrap{flex-wrap:wrap}
  .burger{display:block}
  .fields{grid-template-columns:1fr}
  .reach{grid-template-columns:1fr}
  .facts div,.summary div{grid-template-columns:7rem 1fr}
  .filters{position:static}
}
@media (prefers-reduced-motion:reduce){
  *{transition:none!important;animation:none!important}
  html{scroll-behavior:auto}
}
"""

WA_ICON = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12.04 2C6.58 2 2.13 6.45 2.13 '
           '11.91c0 1.75.46 3.45 1.32 4.95L2 22l5.25-1.38a9.9 9.9 0 0 0 4.79 1.22h.01c5.46 0 '
           '9.91-4.45 9.91-9.91 0-2.65-1.03-5.14-2.9-7.01A9.82 9.82 0 0 0 12.04 2zm0 18.15h-.01a8.2 '
           '8.2 0 0 1-4.19-1.15l-.3-.18-3.12.82.83-3.04-.2-.31a8.19 8.19 0 0 1-1.26-4.38c0-4.54 '
           '3.7-8.23 8.25-8.23 2.2 0 4.27.86 5.83 2.42a8.18 8.18 0 0 1 2.41 5.82c0 4.54-3.7 '
           '8.23-8.24 8.23zm4.52-6.16c-.25-.12-1.47-.72-1.69-.81-.23-.08-.39-.12-.56.13-.16.24-.64.8'
           '-.79.97-.14.16-.29.18-.54.06-.25-.12-1.05-.39-1.99-1.23-.74-.66-1.23-1.47-1.38-1.72-.14'
           '-.25-.01-.38.11-.5.11-.11.25-.29.37-.43.12-.15.16-.25.25-.41.08-.17.04-.31-.02-.43-.06-.'
           '12-.56-1.34-.76-1.84-.2-.48-.41-.42-.56-.43l-.48-.01c-.16 0-.43.06-.65.31-.22.25-.85.83-'
           '.85 2.02s.87 2.34.99 2.5c.12.16 1.71 2.61 4.15 3.66.58.25 1.03.4 1.39.51.58.19 1.11.16 '
           '1.53.1.47-.07 1.47-.6 1.67-1.18.21-.58.21-1.07.15-1.18-.06-.11-.22-.17-.47-.29z"/></svg>')


#: The stylesheet's name carries a hash of its contents.
#:
#: Without this the first redeploy shipped correct CSS that nobody could see:
#: the edge had `styles.css` cached with a four-hour max-age and served the old
#: file over the new HTML, so a fixed layout stayed broken and looked like the
#: fix had failed. A content-addressed name cannot go stale — a changed
#: stylesheet is a different URL — and it keeps the long cache lifetime, which
#: a cache-buster query string would not.
STYLES = f"styles-{hashlib.sha256(CSS.encode()).hexdigest()[:10]}.css"


def wafloat(lang: str) -> str:
    return (f'<a class="wafloat" href="https://wa.me/{S.WHATSAPP}" target="_blank" '
            f'rel="noopener" aria-label="{e(T[lang]["wa_aria"])}">{WA_ICON}</a>')


# ---------------------------------------------------------------- the shell
def nav_items(lang: str) -> tuple[tuple[str, str], ...]:
    """Six, not their eleven. Every destination still reachable, one level down."""
    t = T[lang]
    return ((path(lang, "work"), t["nav_work"]),
            (path(lang, "services"), t["nav_services"]),
            (path(lang, "eatlux"), t["nav_eatlux"]),
            (path(lang, "journal"), t["nav_journal"]),
            (path(lang, "about"), t["nav_about"]),
            (path(lang, "contact"), t["nav_contact"]))


def masthead(lang: str, here: str) -> str:
    t = T[lang]
    links = "".join(
        f'<a href="{e(href)}"{" aria-current=\"page\"" if href == here else ""}>{e(name)}</a>'
        for href, name in nav_items(lang))
    other = T[t["other"]]
    # The same page in the other language, not the other language's homepage.
    swap = here.replace(f"{BASE}/ar/", f"{BASE}/") if lang == "ar" \
        else here.replace(f"{BASE}/", f"{BASE}/ar/", 1)
    return f"""<header class="mast" id="mast" data-open="false"><div class="wrap">
<a class="mark" href="{e(path(lang))}">{e(t["brand"])}<small>{e(t["tagline"])}</small></a>
<button class="burger" type="button" id="burger" aria-expanded="false"
  aria-controls="menu" aria-label="Menu">☰</button>
<nav id="menu">{links}
<a class="lang" href="{e(swap)}" lang="{e(other["lang"])}"
   dir="{e(other["dir"])}">{e(t["other_name"])}</a>
<a class="cta" href="tel:{S.PHONE_E164}">{e(t["call"])}</a></nav>
</div></header>"""


def footer(lang: str) -> str:
    t = T[lang]
    services = "".join(
        f'<li><a href="{e(service_href(lang, s))}">{e(service_name(lang, s))}</a></li>'
        for s in S.SERVICES)
    return f"""<footer><div class="wrap"><div class="cols">
<div><span class="mark">{e(t["brand"])}<small>{e(t["tagline"])}</small></span>
<p class="blurb">{e(S.FOOTER_BLURB if lang == "en" else
    "فريقنا من الكفاءات المدرَّبة جاهز دائمًا لتقديم خدمة متكاملة لتجربة استثنائية.")}</p>
<div class="social">
<a href="{S.INSTAGRAM}" target="_blank" rel="noopener">Instagram</a>
<a href="{S.LINKEDIN}" target="_blank" rel="noopener">LinkedIn</a></div></div>
<div><h3>{e(t["footer_do"])}</h3><ul class="list">{services}</ul></div>
<div><h3>{e(t["footer_reach"])}</h3><p class="who">
<a href="tel:{S.PHONE_E164}" dir="ltr">{e(S.PHONE_HUMAN)}</a><br>
<a href="https://wa.me/{S.WHATSAPP}" target="_blank" rel="noopener">{e(t["whatsapp"])}</a><br>
<a href="mailto:{S.EMAIL}" dir="ltr">{e(S.EMAIL)}</a><br>
<span>{e(S.ADDRESS if lang == "en" else "مجمع دبي للاستثمار ٢")}</span></p>
<p class="who" style="margin-top:.9rem"><a href="{e(path(lang, "about"))}">{e(t["nav_about"])}</a>
 · <a href="{e(path(lang, "privacy"))}">{e(t["privacy_title"])}</a></p></div></div>
<div class="fine"><div>
<p><b>Concept / sample site built by Qevik. Not a client website.</b><br>
Not affiliated with, commissioned by, or connected to AHS Catering &amp; Events, and not their
official site. Built from information AHS publishes about itself, to show what a different
structure could look like. The official site is
<a href="{S.SOURCE}" target="_blank" rel="noopener" style="color:var(--gold-lift)">ahscatering.com</a>.</p>
<p class="src">Contact details, address and social accounts above are AHS's own, as published on
their site on {S.CHECKED_AT}. Photography: none of their photographs are reproduced here — every
image region is a composed treatment and says so.</p></div>
<div><p><b>Qevik</b> — by Asia Link Internet Content Provider LLC<br>
Office 301, Al Othman Building, Deiram, Dubai<br><span dir="ltr">+971 50 102 9104</span></p></div>
</div></div></footer>"""


def shell(*, lang: str, here: str, title: str, description: str, body: str,
          jsonld: str = "", dock: bool = False) -> str:
    """One head, so no route can quietly lose its metadata or its language pair."""
    t = T[lang]
    other = T[t["other"]]
    swap = here.replace(f"{BASE}/ar/", f"{BASE}/") if lang == "ar" \
        else here.replace(f"{BASE}/", f"{BASE}/ar/", 1)
    en_url, ar_url = (here, swap) if lang == "en" else (swap, here)
    schema = f'<script type="application/ld+json">{jsonld}</script>' if jsonld else ""
    return f"""<!doctype html>
<html lang="{e(t["lang"])}" dir="{e(t["dir"])}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(description)}">
<meta name="robots" content="noindex,nofollow">
<link rel="canonical" href="{e(LIVE + here[len(BASE):])}">
<link rel="alternate" hreflang="en" href="{e(LIVE + en_url[len(BASE):])}">
<link rel="alternate" hreflang="ar" href="{e(LIVE + ar_url[len(BASE):])}">
<link rel="alternate" hreflang="x-default" href="{e(LIVE + en_url[len(BASE):])}">
<meta property="og:type" content="website">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(description)}">
<meta property="og:locale" content="{"ar_AE" if lang == "ar" else "en_AE"}">
<meta name="theme-color" content="#0C0B09">
<link rel="stylesheet" href="{BASE}/{STYLES}">{schema}
</head>
<body{' class="has-dock"' if dock else ''}>
<a class="skip" href="#main">Skip to content</a>
{masthead(lang, here)}
<main id="main">{body}</main>
{footer(lang)}
{wafloat(lang)}
<script>
(function(){{
  var b=document.getElementById('burger'), m=document.getElementById('mast');
  if(b) b.addEventListener('click', function(){{
    var open = m.dataset.open !== 'true';
    m.dataset.open = open ? 'true' : 'false';
    b.setAttribute('aria-expanded', open ? 'true' : 'false');
  }});
}})();
</script>
</body></html>"""


def plate(ratio: str, note: str) -> str:
    return f'<div class="plate ratio {ratio}"><span class="note">{e(note)}</span></div>'


# ------------------------------------------------------------------ the work
def work_index(lang: str) -> str:
    """A ledger, not a card grid.

    A buyer arriving here has one question — have they done my kind of event —
    and a wall of pretty tiles answers it worse than a list they can filter and
    read down. The blank fields are deliberately visible: this is AHS's own
    data, and the missing columns are the argument.
    """
    t = T[lang]
    sectors = sorted({c.sector for c in S.CASES}, key=lambda k: sector_name(lang, k))
    kinds = sorted({c.kind for c in S.CASES if c.kind},
                   key=lambda k: kind_name(lang, k))
    chips = lambda group, items, all_label: "".join(
        [f'<button class="chip" type="button" data-g="{group}" data-v="" '
         f'aria-pressed="true">{e(all_label)}</button>']
        + [f'<button class="chip" type="button" data-g="{group}" data-v="{e(v)}" '
           f'aria-pressed="false">{e(n)}</button>' for v, n in items])
    rows = []
    for c in S.CASES:
        client = e(c.client) if c.client else f'<span class="miss">{e(t["case_unpublished"])}</span>'
        kind = e(kind_name(lang, c.kind)) if c.kind else \
            f'<span class="miss">{e(t["case_unpublished"])}</span>'
        rows.append(
            f'<a class="rec" href="{e(path(lang, "work", c.slug))}" data-sector="{e(c.sector)}" '
            f'data-kind="{e(c.kind or "")}">'
            f'<span class="t">{e(c.title)}</span><span class="c">{client}</span>'
            f'<span class="m">{kind}</span>'
            f'<span class="n tab">{c.photos}&nbsp;{e(t["proof_photos"])}</span></a>')
    return f"""<section class="pad dark"><div class="wrap">
<span class="engraved">{e(t["proof_eyebrow"])}</span>
<h1 class="deck" style="margin-top:.7rem">{e(t["proof_title"])}</h1>
<p class="lead">{e(t["proof_lead"])}</p></div></section>
<div class="filters"><div class="wrap">
<div class="row"><span class="cap">{e(t["proof_sector"])}</span>
{chips("sector", [(s, sector_name(lang, s)) for s in sectors], t["proof_all"])}</div>
<div class="row"><span class="cap">{e(t["proof_kind"])}</span>
{chips("kind", [(k, kind_name(lang, k)) for k in kinds], t["proof_all"])}</div></div></div>
<section class="dark" style="padding-bottom:4rem"><div class="wrap">
<div class="ledger" id="ledger">{"".join(rows)}</div>
<p class="empty" id="empty" hidden>{e(t["proof_empty"])}</p>
<div class="tally"><span><b id="shown">{len(S.CASES)}</b> {e(t["proof_count"])}</span>
<span><b class="tab">{S.PHOTOS_TOTAL}</b> {e(t["proof_photos"])}</span>
<span><b class="tab">{len([c for c in S.CASES if c.client])}</b>
{e("named clients" if lang == "en" else "عميل مذكور")}</span></div>
</div></section>
<script>
(function(){{
  var f={{sector:'',kind:''}}, rows=[].slice.call(document.querySelectorAll('#ledger .rec'));
  var shown=document.getElementById('shown'), empty=document.getElementById('empty');
  function draw(){{
    var n=0;
    rows.forEach(function(r){{
      var ok=(!f.sector||r.dataset.sector===f.sector)&&(!f.kind||r.dataset.kind===f.kind);
      r.hidden=!ok; if(ok) n++;
    }});
    shown.textContent=n; empty.hidden=n>0;
  }}
  document.querySelectorAll('.chip').forEach(function(c){{
    c.addEventListener('click', function(){{
      var g=c.dataset.g; f[g]=c.dataset.v;
      document.querySelectorAll('.chip[data-g="'+g+'"]').forEach(function(o){{
        o.setAttribute('aria-pressed', o===c ? 'true' : 'false');
      }});
      draw();
    }});
  }});
  draw();
}})();
</script>"""


def case_page(lang: str, c: S.Case) -> str:
    t = T[lang]
    published = [(t["case_sector"], sector_name(lang, c.sector)),
                 (t["case_photos"], f"{c.photos}")]
    if c.client:
        published.insert(0, (t["case_client"], c.client))
    if c.kind:
        published.insert(0, (t["case_kind"], kind_name(lang, c.kind)))
    if c.venue:
        published.append((t["case_venue"], c.venue))
    rows = "".join(f"<div><dt>{e(k)}</dt><dd>{e(v)}</dd></div>" for k, v in published)
    gaps = "".join(f'<div class="un"><dt>{e(g)}</dt><dd>{e(t["case_unpublished"])}</dd></div>'
                   for g in c.unpublished)
    similar = [o for o in S.CASES if o.slug != c.slug and o.sector == c.sector][:4] \
        or [o for o in S.CASES if o.slug != c.slug and o.kind and o.kind == c.kind][:4]
    rel = "".join(
        f'<a class="card" href="{e(path(lang, "work", o.slug))}"><h3>{e(o.title)}</h3>'
        f'<p>{e(o.client or sector_name(lang, o.sector))} · '
        f'{o.photos} {e(t["proof_photos"])}</p></a>' for o in similar)
    note = (f'<div class="gap"><span class="engraved">{e(t["case_note"])}</span>'
            f"<p>{e(c.note)}</p></div>") if c.note else ""
    return f"""<section class="pad dark"><div class="wrap">
<p style="margin:0 0 1.4rem"><a class="src" href="{e(path(lang, "work"))}">← {e(t["case_back"])}</a></p>
<div class="record">
<div><span class="engraved">{e(sector_name(lang, c.sector))}</span>
<h1 class="deck" style="margin-top:.7rem">{e(c.title)}</h1>
<span class="engraved" style="color:var(--ash-2);display:block;margin:1.8rem 0 .5rem">
{e(t["case_published"])}</span>
<dl class="facts">{rows}</dl>
<span class="engraved" style="color:var(--ash-2);display:block;margin:1.8rem 0 .5rem">
{e(t["case_unpublished"])}</span>
<dl class="facts">{gaps}</dl>{note}
<p style="margin-top:1.8rem">
<a class="cta" href="{e(path(lang, "contact"))}">{e(t["home_cta"])}</a></p></div>
<div>{plate("tall", f"Composed treatment · {c.photos} AHS photographs sit here")}</div>
</div></div></section>
<section class="pad light"><div class="wrap">
<span class="engraved">{e(t["case_related"])}</span>
<div class="grid g2" style="margin-top:1.2rem">{rel}</div></div></section>"""


# ------------------------------------------------------------------ the brief
#: The brief's third step is keyed "month" — it offers months, not dates — but
#: reads "Date" to a visitor. Keeping the key honest and the label human means
#: one small map rather than a misleading key or a misleading label.
STEP_LABEL = {"occasion": "occasion", "guests": "guests", "month": "date", "style": "style"}


def brief_steps(lang: str) -> str:
    out = []
    for i, (key, opts) in enumerate(STEPS, 1):
        buttons = "".join(
            f'<button class="chip" type="button" data-k="{key}" data-v="{v}" '
            f'aria-pressed="false">{e(ar if lang == "ar" else en)}</button>'
            for v, en, ar in opts)
        out.append(f'<div class="stepq"><span class="n">0{i}</span>'
                   f'<p class="q">{e(T[lang][STEP_LABEL[key]])}</p>'
                   f'<div class="opts">{buttons}</div></div>')
    return "".join(out)


#: One script, on every page that carries a brief. State lives in localStorage so
#: a visitor who sets the occasion on the homepage still has it on the enquiry —
#: which is the part a single-page concept never had to solve.
BRIEF_JS = """
(function(){
  var KEY='ahs.brief', LABELS=%s;
  var brief={}; try{ brief=JSON.parse(localStorage.getItem(KEY)||'{}'); }catch(x){ brief={}; }
  function save(){ try{ localStorage.setItem(KEY, JSON.stringify(brief)); }catch(x){} }
  function draw(){
    document.querySelectorAll('.chip[data-k]').forEach(function(c){
      c.setAttribute('aria-pressed', brief[c.dataset.k]===c.dataset.v ? 'true':'false');
    });
    document.querySelectorAll('[data-sum]').forEach(function(d){
      var v=brief[d.dataset.sum];
      d.textContent = v ? (LABELS[d.dataset.sum][v]||v) : d.dataset.unset;
      d.className = v ? 'set' : '';
    });
    var set=Object.keys(brief).filter(function(k){return brief[k];});
    var dock=document.getElementById('dockval');
    if(dock) dock.textContent = set.length
      ? set.map(function(k){return LABELS[k][brief[k]]||brief[k];}).join(' · ')
      : dock.dataset.start;
  }
  document.addEventListener('click', function(ev){
    var c=ev.target.closest('.chip[data-k]'); if(!c) return;
    brief[c.dataset.k] = brief[c.dataset.k]===c.dataset.v ? '' : c.dataset.v;
    save(); draw();
  });
  var form=document.getElementById('form');
  if(form) form.addEventListener('submit', function(ev){
    ev.preventDefault();
    document.getElementById('formstatus').textContent = form.dataset.sent;
  });
  draw();
})();
"""


def labels_json(lang: str) -> str:
    parts = []
    for key, opts in STEPS:
        inner = ",".join(f'"{v}":"{(ar if lang == "ar" else en)}"' for v, en, ar in opts)
        parts.append(f'"{key}":{{{inner}}}')
    return "{" + ",".join(parts) + "}"


def dock(lang: str) -> str:
    t = T[lang]
    return f"""<div class="dock" style="position:fixed;inset-inline:0;bottom:0;z-index:44;
background:var(--night-2);border-top:1px solid var(--rule);padding:.6rem 1rem;
gap:.6rem;align-items:center">
<span class="engraved" style="color:var(--ash-2)">{e(t["brief_your"])}</span>
<span id="dockval" data-start="{e(t["brief_start"])}"
  style="flex:1;font-size:13px;color:var(--linen)">{e(t["brief_start"])}</span>
<a class="cta" style="padding:.6rem .8rem" href="tel:{S.PHONE_E164}">{e(t["call"])}</a></div>"""


def reach(lang: str) -> str:
    t = T[lang]
    return f"""<div class="reach">
<a href="tel:{S.PHONE_E164}"><span class="k">{e(t["call"])}</span>
<span class="v" dir="ltr">{e(S.PHONE_HUMAN)}</span></a>
<a class="wa" href="https://wa.me/{S.WHATSAPP}" target="_blank" rel="noopener">
<span class="k">{e(t["whatsapp"])}</span><span class="v" dir="ltr">{e(S.PHONE_HUMAN)}</span></a>
<a href="mailto:{S.EMAIL}"><span class="k">{e(t["email"])}</span>
<span class="v" dir="ltr">{e(S.EMAIL)}</span></a></div>"""


def contact_page(lang: str) -> str:
    t = T[lang]
    summary = "".join(
        f'<div><dt>{e(t[STEP_LABEL[k]])}</dt><dd data-sum="{k}" data-unset="{e(t["brief_unset"])}">'
        f'{e(t["brief_unset"])}</dd></div>' for k, _ in STEPS)
    return f"""<section class="pad dark"><div class="wrap">
<span class="engraved">{e(t["brief_eyebrow"])}</span>
<h1 class="deck" style="margin-top:.7rem">{e(t["brief_title"])}</h1>
<p class="lead">{e(t["brief_lead"])}</p>
<div class="record" style="margin-top:2.6rem">
<div><div class="brief-rail">{brief_steps(lang)}</div></div>
<div><dl class="summary">{summary}</dl>
<form class="fields" id="form" novalidate data-sent="{e(t["sent"])}">
<label><span>{e(t["name"])}</span><input name="name" autocomplete="name"></label>
<label><span>{e(t["org"])}</span><input name="org"></label>
<label><span>{e(t["email"])}</span><input name="email" type="email" autocomplete="email"></label>
<label><span>{e(t["phone"])}</span><input name="phone" type="tel" autocomplete="tel"></label>
<label class="full"><span>{e(t["notes"])}</span><textarea name="notes" rows="3"></textarea></label>
<div class="full" style="display:flex;gap:.7rem;flex-wrap:wrap">
<button type="submit" class="cta">{e(t["brief_send"])}</button>
<a class="cta wa" href="https://wa.me/{S.WHATSAPP}" target="_blank" rel="noopener">
{e(t["brief_wa"])}</a></div></form>
<p class="engraved" style="color:var(--ash-2);margin-top:1.6rem">{e(t["brief_or"])}</p>
{reach(lang)}
<p class="disclaim" id="formstatus"></p>
<p class="disclaim">{e(t["disclaim"])}</p></div></div></div></section>
<script>{BRIEF_JS % labels_json(lang)}</script>"""


# ------------------------------------------------------------------ the rest
def home(lang: str) -> str:
    t = T[lang]
    named = [c for c in S.CASES if c.client][:8]
    roll = " · ".join(e(c.client) for c in named)
    svc = "".join(
        f'<a class="card" href="{e(service_href(lang, s))}">'
        f'<span class="engraved">{s.photos} {e(t["svc_photos"])}</span>'
        f'<h3>{e(service_name(lang, s))}</h3>'
        f'<p>{e(" · ".join(s.points[:2]))}</p></a>' for s in S.SERVICES[:6])
    return f"""<section class="dark" style="padding:0"><div class="plate"
style="width:100%;min-height:min(78vh,640px);display:grid;align-items:end">
<div class="wrap" style="position:relative;z-index:2;padding:0 0 clamp(2rem,5vw,4rem)">
<span class="engraved">{e(t["home_eyebrow"])}</span>
<h1 class="deck" style="margin-top:.8rem;max-width:16ch">{e(t["home_title"])}
<em>{e(t["home_title_em"])}</em></h1>
<p class="lead">{e(S.HERO_BLURB if lang == "en" else
  "أكثر من عشرين عامًا من الخبرة، ومطابخ حاصلة على شهادة الحلال، وفريق تخطيط يتقن كل تفصيل.")}</p>
<p style="margin-top:1.8rem;display:flex;gap:.8rem;flex-wrap:wrap">
<a class="cta" href="{e(path(lang, "contact"))}">{e(t["home_cta"])}</a>
<a class="cta ghost" href="{e(path(lang, "work"))}">{e(t["home_cta2"])}</a></p></div>
<span class="note">Composed treatment · AHS event photography would sit here</span>
</div></section>

<section class="pad dark"><div class="wrap">
<span class="engraved">{e(t["proof_eyebrow"])}</span>
<h2 class="deck" style="margin-top:.7rem;max-width:20ch">{e(t["proof_title"])}</h2>
<p class="lead">{e(t["proof_lead"])}</p>
<div class="tally"><span><b class="tab">{len(S.CASES)}</b> {e(t["proof_count"])}</span>
<span><b class="tab">{S.PHOTOS_TOTAL}</b> {e(t["proof_photos"])}</span>
<span><b class="tab">{len([c for c in S.CASES if c.client])}</b>
{e("named clients" if lang == "en" else "عميل مذكور")}</span></div>
<p class="lead" style="margin-top:1.4rem;color:var(--gold-lift)">{roll}</p>
<p class="src" style="margin-top:.5rem">{e(t["about_clients_note"])}</p>
<p style="margin-top:1.6rem"><a class="cta ghost"
href="{e(path(lang, "work"))}">{e(t["proof_open"])}</a></p></div></section>

<section class="pad light"><div class="wrap">
<span class="engraved">{e(t["svc_eyebrow"])}</span>
<h2 class="deck" style="margin-top:.7rem">{e(t["svc_title"])}</h2>
<p class="lead">{e(t["svc_lead"])}</p>
<div class="grid g3" style="margin-top:2rem">{svc}</div></div></section>

<section class="pad dark"><div class="wrap"><div class="record">
<div><span class="engraved">EATLUX</span>
<h2 class="deck" style="margin-top:.7rem">{e(S.EATLUX_CLAIM if lang == "en" else
  "أول تجربة «حزام العرض» في الإمارات")}</h2>
<p class="lead">{e(S.EATLUX_ORIGIN if lang == "en" else
  "لاحظت كريستينا، القادمة من تنظيم الأعراس، أن الضيافة غالبًا ما تعني طوابير وأطباقًا "
  "بلا روح. فتعاونت مع علي، ومن هناك وُلد EATLUX.")}</p>
<p style="margin-top:1.6rem"><a class="cta ghost"
href="{e(path(lang, "eatlux"))}">{e(t["journal_read"])}</a></p></div>
<div>{plate("wide", "Composed treatment · the EATLUX belt")}</div></div></div></section>

<section class="pad light"><div class="wrap">
<span class="engraved">{e(t["brief_eyebrow"])}</span>
<h2 class="deck" style="margin-top:.7rem">{e(t["brief_q"])}</h2>
<p class="lead">{e(t["brief_sub"])}</p>
<div class="grid g2" style="margin-top:1.8rem;align-items:start">
<div class="brief-rail" style="background:#fff;border-color:rgba(138,109,18,.2)">
{brief_steps(lang)}</div>
<div><p class="lead">{e(t["brief_lead"])}</p>
<p style="margin-top:1.4rem"><a class="cta"
href="{e(path(lang, "contact"))}">{e(t["brief_send"])}</a></p></div></div></div></section>
{dock(lang)}
<script>{BRIEF_JS % labels_json(lang)}</script>"""


def services_index(lang: str) -> str:
    t = T[lang]
    cards = "".join(
        f'<a class="card" href="{e(service_href(lang, s))}">'
        f'<span class="engraved">{s.words} {e(t["svc_words"])} · {s.photos} '
        f'{e(t["svc_photos"])}</span><h3>{e(service_name(lang, s))}</h3>'
        f'<p>{e(" · ".join(s.points[:3]))}</p></a>' for s in S.SERVICES)
    return f"""<section class="pad dark"><div class="wrap">
<span class="engraved">{e(t["svc_eyebrow"])}</span>
<h1 class="deck" style="margin-top:.7rem">{e(t["svc_title"])}</h1>
<p class="lead">{e(t["svc_lead"])}</p>
<div class="grid g2" style="margin-top:2.2rem">{cards}</div></div></section>"""


def service_page(lang: str, s: S.Service) -> str:
    t = T[lang]
    points = "".join(f"<li>{e(p)}</li>" for p in s.points)
    related = [c for c in S.CASES if c.kind and s.name.split()[0].lower() in c.kind.lower()][:3]
    rel = "".join(
        f'<a class="card" href="{e(path(lang, "work", c.slug))}"><h3>{e(c.title)}</h3>'
        f'<p>{e(c.client or sector_name(lang, c.sector))}</p></a>' for c in related)
    return f"""<section class="pad dark"><div class="wrap"><div class="record">
<div><span class="engraved">{e(t["svc_eyebrow"])}</span>
<h1 class="deck" style="margin-top:.7rem">{e(service_name(lang, s))}</h1>
<span class="engraved" style="color:var(--ash-2);display:block;margin:1.8rem 0 .4rem">
{e(t["svc_includes"])}</span>
<ul class="bullets">{points}</ul>
<p class="src" style="margin-top:1.6rem">{e(t["svc_source"])}: {e(s.source_path)} ·
{s.words} {e(t["svc_words"])} · {s.photos} {e(t["svc_photos"])}</p>
<p style="margin-top:1.6rem">
<a class="cta" href="{e(path(lang, "contact"))}">{e(t["home_cta"])}</a></p></div>
<div>{plate("tall", f"Composed treatment · {s.photos} AHS photographs sit here")}</div>
</div>{f'<div class="grid g3" style="margin-top:3rem">{rel}</div>' if rel else ""}
</div></section>"""


def eatlux_page(lang: str) -> str:
    t = T[lang]
    return f"""<section class="pad dark"><div class="wrap">
<span class="engraved">EATLUX</span>
<h1 class="deck" style="margin-top:.7rem;max-width:18ch">{e(S.EATLUX_CLAIM if lang == "en"
  else "أول تجربة «حزام العرض» في الإمارات")}</h1>
<div class="prose" style="margin-top:1.6rem">
<p>{e(S.EATLUX_ORIGIN if lang == "en" else
  "لاحظت كريستينا، القادمة من تنظيم الأعراس، أن الضيافة غالبًا ما تعني طوابير وأطباقًا بلا "
  "روح. فتعاونت مع علي، ومن هناك وُلد EATLUX.")}</p></div>
<div class="grid g3" style="margin-top:2.4rem">
{"".join(f'<div class="card"><h3>{e(p)}</h3></div>' for p in S.SERVICES[-1].points)}</div>
<p style="margin-top:2rem"><a class="cta"
href="{e(path(lang, "contact"))}">{e(t["home_cta"])}</a></p></div></section>"""


def journal_index(lang: str) -> str:
    t = T[lang]
    cards = []
    for a in S.ARTICLES:
        title = ARTICLE_AR[a.slug][0] if lang == "ar" else a.title
        sub = ARTICLE_AR[a.slug][1] if lang == "ar" else a.facts[0]
        cards.append(f'<a class="card" href="{e(path(lang, "journal", a.slug))}">'
                     f'<span class="engraved">{e(a.date)}</span><h3>{e(title)}</h3>'
                     f'<p>{e(sub)}</p></a>')
    return f"""<section class="pad dark"><div class="wrap">
<span class="engraved">{e(t["journal_eyebrow"])}</span>
<h1 class="deck" style="margin-top:.7rem">{e(t["journal_title"])}</h1>
<p class="lead">{e(t["journal_lead"])}</p>
<div class="grid g2" style="margin-top:2.2rem">{"".join(cards)}</div></div></section>"""


def article_page(lang: str, a: S.Article) -> str:
    t = T[lang]
    title = ARTICLE_AR[a.slug][0] if lang == "ar" else a.title
    facts = "".join(f"<li>{e(f)}</li>" for f in a.facts) if lang == "en" else \
        f"<li>{e(ARTICLE_AR[a.slug][1])}</li>"
    jsonld = ('{"@context":"https://schema.org","@type":"Article",'
              f'"headline":{title!r},"datePublished":"{a.date}",'
              '"publisher":{"@type":"Organization","name":"AHS Catering & Events"}}'
              ).replace("'", '"')
    return jsonld, f"""<section class="pad dark"><div class="narrow">
<p style="margin:0 0 1.4rem"><a class="src"
href="{e(path(lang, "journal"))}">← {e(t["journal_back"])}</a></p>
<span class="engraved">{e(a.date)}</span>
<h1 class="deck" style="margin-top:.7rem">{e(title)}</h1>
<div style="margin:2rem 0">{plate("wide", "Composed treatment · their post carries no image")}</div>
<div class="prose">
<span class="engraved" style="color:var(--ash-2)">{e(t["journal_facts"])}</span>
<ul class="bullets">{facts}</ul>
<p class="src" style="margin-top:1.8rem">{e(t["journal_source"])} · {e(a.date)} ·
{a.words} {e(t["svc_words"])} · /{e(a.source_slug)}/</p>
<p style="margin-top:1.8rem">
<a class="cta" href="{e(path(lang, "contact"))}">{e(t["home_cta"])}</a></p>
</div></div></section>"""


def about_page(lang: str) -> str:
    t = T[lang]
    clients = " · ".join(e(c) for c in (*S.CLIENTS_ABOUT, *S.CLIENTS_BLOG))
    facts = "".join(f"<li>{e(f)}</li>" for f in S.FOUNDER_FACTS) if lang == "en" else \
        "<li>بدأ في السادسة عشرة في الضيافة.</li><li>تعلّم الصالة أولًا ثم انتقل إلى المطبخ.</li>" \
        "<li>سافر بحثًا عن الإلهام لا الوصفات.</li>"
    caps = "".join(f'<div class="card"><h3>{e(h)}</h3><p>{e(p)}</p></div>'
                   for h, p in S.CAPABILITIES) if lang == "en" else \
        "".join(f'<div class="card"><h3>{e(h)}</h3></div>' for h, _ in S.CAPABILITIES)
    return f"""<section class="pad dark"><div class="wrap">
<span class="engraved">{e(t["about_eyebrow"])}</span>
<h1 class="deck" style="margin-top:.7rem">{e(t["about_title"])}</h1>
<p class="lead">{e(S.ABOUT_OPENER if lang == "en" else
  "AHS شركة ضيافة رائدة في دبي بخبرة تتجاوز عشرين عامًا في الأعراس الفاخرة والمناسبات "
  "المؤسسية والاحتفالات الخاصة، بقوائم تجمع نكهات الشرق الأوسط بالمطبخ العالمي، "
  "وتُحضَّر في مطابخ حاصلة على شهادة الحلال.")}</p>
<div class="record" style="margin-top:3rem">
<div><span class="engraved">{e(t["about_founder"])}</span>
<h2 class="deck" style="font-size:clamp(1.6rem,3vw,2.3rem);margin-top:.6rem">
{e(S.FOUNDER)}</h2>
<ul class="bullets">{facts}</ul>
<p style="margin-top:1.4rem;font:300 clamp(1.2rem,2.4vw,1.7rem)/1.35 var(--display);
color:var(--gold-lift)">“{e(S.FOUNDER_QUOTE if lang == "en" else
  "لا يمكنك قيادة التميّز إن لم تفهم التفاصيل.")}”</p></div>
<div>{plate("tall", "Composed treatment · AHS publishes a portrait here")}</div></div>
<div style="margin-top:3.4rem"><span class="engraved">{e(t["about_clients"])}</span>
<p class="lead" style="color:var(--gold-lift);margin-top:.8rem;max-width:none">{clients}</p>
<p class="src" style="margin-top:.6rem">{e(t["about_clients_note"])} — {e(S.F1)}.</p></div>
<div class="grid g3" style="margin-top:3rem">{caps}</div></div></section>"""


def privacy_page(lang: str) -> str:
    t = T[lang]
    body = ("<p>This is a concept page. It is not AHS's privacy policy and has no legal "
            "effect.</p><p>Nothing here collects, stores or transmits anything. The enquiry "
            "form does not send. There is no analytics, no tracking pixel, no cookie and no "
            "third-party script on any page of this concept.</p><p>The route exists because "
            "the real business publishes a privacy policy and a concept that quietly drops it "
            "would be removing part of their site. Their own policy is at "
            f'<a href="{S.SOURCE}privacy-policy-2/" target="_blank" rel="noopener" '
            'style="color:var(--gold-lift)">ahscatering.com</a>, and it is worth reading: it '
            "is still the unedited WordPress sample text, covering blog comments and Gravatar "
            "rather than catering.</p>") if lang == "en" else (
            "<p>هذه صفحة نموذجية، وليست سياسة الخصوصية الخاصة بـ AHS، وليس لها أي أثر قانوني.</p>"
            "<p>لا شيء هنا يجمع أو يخزّن أو يرسل أي بيانات. نموذج الطلب لا يُرسل. لا توجد أي "
            "أدوات تحليل أو تتبّع أو ملفات تعريف ارتباط في أي صفحة من هذا النموذج.</p>")
    return f"""<section class="pad dark"><div class="narrow">
<span class="engraved">{e(t["privacy_eyebrow"])}</span>
<h1 class="deck" style="margin-top:.7rem">{e(t["privacy_title"])}</h1>
<div class="prose">{body}</div></div></section>"""


# ------------------------------------------------------------------- assemble
ORG_JSONLD = ('{"@context":"https://schema.org","@type":"Organization",'
              '"name":"AHS Catering & Events","url":"https://ahscatering.com/",'
              f'"telephone":"{S.PHONE_E164}","email":"{S.EMAIL}",'
              '"address":{"@type":"PostalAddress","addressLocality":"Dubai Investment Park 2",'
              '"addressCountry":"AE"},'
              f'"sameAs":["{S.INSTAGRAM}","{S.LINKEDIN}"]}}')


def build() -> dict[str, str]:
    """Every route, both languages. Returns {path relative to the site root: html}."""
    out: dict[str, str] = {}

    def put(lang: str, parts: tuple[str, ...], title: str, desc: str, body: str,
            jsonld: str = "", dock_: bool = False) -> None:
        here = path(lang, *parts)
        rel = here[len(BASE) + 1:] + "index.html"
        out[rel] = shell(lang=lang, here=here, title=title, description=desc, body=body,
                         jsonld=jsonld, dock=dock_)

    for lang in ("en", "ar"):
        t = T[lang]
        brand = "AHS Catering & Events"
        suffix = " | مفهوم Qevik" if lang == "ar" else " | Qevik concept"

        put(lang, (), f"{brand} — {t['home_title']} {t['home_title_em']}{suffix}",
            S.HERO_BLURB if lang == "en" else t["proof_lead"], home(lang), ORG_JSONLD, True)
        put(lang, ("work",), f"{t['proof_title']} — {brand}{suffix}", t["proof_lead"],
            work_index(lang))
        for c in S.CASES:
            put(lang, ("work", c.slug), f"{c.title} — {brand}{suffix}",
                f"{c.title}. {sector_name(lang, c.sector)}. "
                f"{c.photos} {t['proof_photos']}.", case_page(lang, c))
        put(lang, ("services",), f"{t['svc_title']} — {brand}{suffix}", t["svc_lead"],
            services_index(lang))
        for s in S.SERVICES:
            if s.slug == "eatlux":
                continue    # has its own route; see service_href
            put(lang, ("services", s.slug), f"{service_name(lang, s)} — {brand}{suffix}",
                " · ".join(s.points[:3]), service_page(lang, s))
        put(lang, ("eatlux",), f"EATLUX — {brand}{suffix}", S.EATLUX_CLAIM, eatlux_page(lang))
        put(lang, ("journal",), f"{t['journal_title']} — {brand}{suffix}", t["journal_lead"],
            journal_index(lang))
        for a in S.ARTICLES:
            jsonld, body = article_page(lang, a)
            title = ARTICLE_AR[a.slug][0] if lang == "ar" else a.title
            put(lang, ("journal", a.slug), f"{title} — {brand}{suffix}",
                a.facts[0] if lang == "en" else ARTICLE_AR[a.slug][1], body, jsonld)
        put(lang, ("about",), f"{t['about_title']} — {brand}{suffix}",
            S.ABOUT_OPENER[:160], about_page(lang), ORG_JSONLD)
        put(lang, ("contact",), f"{t['brief_title']} — {brand}{suffix}", t["brief_lead"][:160],
            contact_page(lang), "", True)
        put(lang, ("privacy",), f"{t['privacy_title']} — {brand}{suffix}",
            "Concept page. Nothing is collected.", privacy_page(lang))

    out[STYLES] = CSS
    out["sitemap.xml"] = sitemap(out)
    out["robots.txt"] = "User-agent: *\nDisallow: /\n"   # a concept, not a site to index
    verify(out)
    return out


def sitemap(pages: dict[str, str]) -> str:
    urls = "".join(
        f"<url><loc>{LIVE}/{p[:-len('index.html')]}</loc></url>"
        for p in sorted(pages) if p.endswith("index.html"))
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>')


class Incomplete(AssertionError):
    """A route that lost something every route must carry."""


def verify(pages: dict[str, str]) -> None:
    """Refuse to emit a build where a page lost its contact routes or its language pair.

    Cheap, and it is the failure that actually happened: a redesign that looked
    better and quietly dropped the phone number. A generator makes that failure
    ninety-eight times at once, so it is checked here rather than by eye.
    """
    required = (f'href="tel:{S.PHONE_E164}"', f'href="https://wa.me/{S.WHATSAPP}"',
                f'href="mailto:{S.EMAIL}"', S.INSTAGRAM, S.LINKEDIN,
                'hreflang="ar"', 'hreflang="en"', 'rel="canonical"',
                "Not a client website", 'class="wafloat"', 'id="main"')
    for route, html_ in pages.items():
        if not route.endswith("index.html"):
            continue
        for needle in required:
            if needle not in html_:
                raise Incomplete(f"{route} is missing {needle!r}")
        if "<title>" not in html_ or "<title></title>" in html_:
            raise Incomplete(f"{route} has no title")
        if f'href="{BASE}/{STYLES}"' not in html_:
            raise Incomplete(f"{route} does not load the stylesheet")
    if STYLES not in pages:
        raise Incomplete("the stylesheet itself was not emitted")


def main() -> int:
    pages = build()
    root = Path(__file__).resolve().parent / "dist"
    for route, body in pages.items():
        target = root / route
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    html_pages = [p for p in pages if p.endswith("index.html")]
    print(f"  {len(html_pages)} pages ({len([p for p in html_pages if p.startswith('ar/')])} ar)"
          f" -> {root}")
    print(f"  {sum(len(v) for v in pages.values()) // 1024} KB total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
