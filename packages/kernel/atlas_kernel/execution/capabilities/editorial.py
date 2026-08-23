"""An editorial hub built from what the business already publishes.

The temptation here is enormous and has to be named: a capability called
"editorial" sounds like it should *write articles*, and writing an article about
somebody else's business means asserting things about their business that nobody
told us. `website/content.py` forbids exactly that, and the forbidding is the
reason the whole content architecture is trustworthy.

So this does the other thing, which is what the research actually supports. AHS
publish four posts on genuinely good subjects — Formula 1 Abu Dhabi, their
show-belt dining, sustainability — all dated the same day, all uncategorised,
none carrying an image, none reachable from anywhere useful. The subjects are
theirs and they are good. What is missing is structure.

So the hub is **an index, one page per subject, and the internal links between
them**, carrying the title and date they published and a route back to their own
article. Every fact on the page came from their CMS. Nothing is written about
their business that they did not write first.

`NothingToBuild` when they publish nothing: an editorial hub over zero articles
is a page that would have to invent its contents.
"""

from __future__ import annotations

import html
import re
from datetime import datetime

from ...opportunity.models import Business
from ...website.content import FactSource

#: A slug that is safe as a file path. Anything else is dropped rather than
#: rewritten — a renamed route is a broken link to their original.
_SLUG = re.compile(r"^[a-z0-9][a-z0-9\-]*$", re.I)

#: How many articles the hub carries. Not a limit on their writing — a limit on
#: how much is restructured in one job, so the units a customer is charged stay
#: proportional to what the offer declared.
MAX_ARTICLES = 24


class NothingToBuild(ValueError):
    """There is nothing published to build an editorial hub from."""


def _posts(research: dict) -> list[dict]:
    """The articles the CMS reported, cleaned but never invented."""
    cms = (research.get("facts") or {}).get("cms") or {}
    found = []
    for row in cms.get("post_list") or []:
        slug = (row.get("slug") or "").strip()
        title = (row.get("title") or "").strip()
        if not title or not _SLUG.match(slug or ""):
            continue
        found.append({
            "slug": slug, "title": title, "url": (row.get("url") or "").strip(),
            "published": (row.get("published") or "")[:10],
            "words": int(row.get("words") or 0),
            "images": int(row.get("images") or 0),
            "categories": [c for c in (row.get("categories") or []) if c],
        })
    return found[:MAX_ARTICLES]


def _readable(published: str) -> str:
    """Their date, reformatted. Never a date we chose."""
    try:
        return datetime.strptime(published, "%Y-%m-%d").strftime("%-d %B %Y")
    except (ValueError, TypeError):
        return published


_STYLE = """
:root{--ink:#16181d;--muted:#5b6472;--line:#e4e7ec;--bg:#fff;--accent:#1f4fd8}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
 font:16px/1.65 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:66ch;margin:0 auto;padding:3rem 1.25rem 5rem}
h1{font-size:2rem;line-height:1.2;margin:0 0 .4rem;text-wrap:balance}
h2{font-size:1.05rem;margin:2.5rem 0 .75rem;letter-spacing:.04em;
 text-transform:uppercase;color:var(--muted)}
.lede{color:var(--muted);margin:0 0 2.5rem}
ol.index{list-style:none;margin:0;padding:0;display:grid;gap:1px;
 background:var(--line);border-block:1px solid var(--line)}
ol.index li{background:var(--bg)}
ol.index a{display:grid;gap:.15rem;padding:1rem .25rem;text-decoration:none;color:inherit}
ol.index a:hover{background:#f7f8fa}
.t{font-weight:600}
.m{font-size:.85rem;color:var(--muted)}
.links{margin-top:2.5rem;padding-top:1.25rem;border-top:1px solid var(--line);
 font-size:.9rem;display:flex;gap:1.25rem;flex-wrap:wrap}
a{color:var(--accent)}
.note{margin-top:3rem;font-size:.85rem;color:var(--muted)}
@media (prefers-color-scheme:dark){
 :root{--ink:#e8eaee;--muted:#98a1b0;--line:#2a2f3a;--bg:#101317;--accent:#8ab0ff}
 ol.index a:hover{background:#171b21}}
"""


def _page(title: str, body: str) -> str:
    return (f'<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">\n'
            f"<title>{html.escape(title)}</title>\n<style>{_STYLE}</style>\n"
            f'</head>\n<body>\n<div class="wrap">\n{body}\n</div>\n</body>\n</html>\n')


def build_editorial_hub(*, business_name: str, research: dict,
                        strengths: tuple[str, ...] = (),
                        business: Business | None = None) -> tuple[dict[str, str], dict]:
    """An index and one page per published subject. Returns bundle and provenance."""
    posts = _posts(research)
    if not posts:
        raise NothingToBuild(
            f"{business_name} publishes no articles the research could read, so "
            "there is nothing to index. An editorial hub over zero articles is a "
            "page that would have to invent its own contents.")

    name = html.escape((business.name if business else business_name).strip())
    rows = "\n".join(
        f'    <li><a href="articles/{html.escape(p["slug"])}.html">'
        f'<span class="t">{html.escape(p["title"])}</span>'
        f'<span class="m">{html.escape(_readable(p["published"])) or "date not published"}'
        f'{" · " + html.escape(", ".join(p["categories"])) if p["categories"] else ""}'
        f"</span></a></li>"
        for p in posts)

    index = _page(
        f"Articles — {name}",
        f"<h1>Articles</h1>\n"
        f'<p class="lede">Everything {name} has published, in one index.</p>\n'
        f'<h2>The index</h2>\n<ol class="index">\n{rows}\n</ol>\n'
        f'<p class="note">Each entry links to the article as {name} published it. '
        f"Titles and dates are theirs; nothing here has been rewritten.</p>")

    files = {"index.html": index}
    for position, post in enumerate(posts):
        neighbours = []
        if position:
            previous = posts[position - 1]
            neighbours.append(f'<a href="{html.escape(previous["slug"])}.html">← '
                              f'{html.escape(previous["title"])}</a>')
        if position + 1 < len(posts):
            following = posts[position + 1]
            neighbours.append(f'<a href="{html.escape(following["slug"])}.html">'
                              f'{html.escape(following["title"])} →</a>')
        original = (f'<p><a href="{html.escape(post["url"])}">'
                    f"Read it as {name} published it</a></p>"
                    if post["url"] else "")
        files[f'articles/{post["slug"]}.html'] = _page(
            f'{post["title"]} — {name}',
            f'<h1>{html.escape(post["title"])}</h1>\n'
            f'<p class="lede">{html.escape(_readable(post["published"])) or "Date not published"}'
            f'{" · " + str(post["words"]) + " words" if post["words"] else ""}</p>\n'
            f"{original}\n"
            f'<div class="links">\n' + "\n".join(neighbours)
            + '\n<a href="../index.html">All articles</a>\n</div>')

    return files, {
        # Everything a reviewer can check against the research record.
        "articles": [p["slug"] for p in posts],
        "titles_are_theirs": True,
        "fact_source": FactSource.OBSERVED.value,
        "published_dates": [p["published"] for p in posts if p["published"]],
        "uncategorised": sum(1 for p in posts if not p["categories"]),
        "without_images": sum(1 for p in posts if not p["images"]),
        "median_words": sorted(p["words"] for p in posts)[len(posts) // 2],
        "strengths_noted": list(strengths),
        # Said plainly because it is the claim that matters about this artefact.
        "nothing_written": "Titles, dates and links are the business's own. No "
                           "article body was generated.",
    }
