"""Build a portfolio index out of what the business already publishes.

The smallest capability that proves the whole loop, chosen for three reasons: it
consumes real research evidence, it needs no external provider, and it is
genuinely the thing AHS's evidence asked for — thirty-two event pages carrying a
hundred and seventy photographs that the homepage links to none of.

It invents nothing. Every row comes from a page the research engine actually
read, and a field the business does not publish is rendered as *not published*
rather than filled in. That is the argument being made to the customer, in their
own data, and it is also why this artefact can be shown to a strong business
without implying anything is wrong with them.
"""

from __future__ import annotations

import html
import re

#: A page with no title tells the reader nothing, and a row with no link is not
#: an index entry. Both are dropped rather than rendered empty.
_SLUG = re.compile(r"^[a-z0-9][a-z0-9\-]*$", re.I)


def _cases(research: dict) -> list[dict]:
    """The event pages the research engine read, cleaned but never invented."""
    cms = (research.get("facts") or {}).get("cms") or {}
    rows = cms.get("image_page_list") or []
    cases: list[dict] = []
    for row in rows:
        slug = (row.get("slug") or "").strip()
        title = (row.get("title") or "").strip()
        if not title or not _SLUG.match(slug or ""):
            continue
        cases.append({"slug": slug, "title": title,
                      "url": (row.get("url") or "").strip(),
                      "images": int(row.get("images") or 0)})
    return cases


def _facts(research: dict) -> dict:
    facts = research.get("facts") or {}
    cms = facts.get("cms") or {}
    seo = facts.get("seo") or {}
    return {"pages": cms.get("pages"), "media": cms.get("media_total"),
            "orphans": seo.get("orphan_count"), "posts": cms.get("posts")}


def build_portfolio_index(*, business_name: str, research: dict,
                          strengths: tuple[str, ...] = (),
                          business=None) -> tuple[str, dict]:
    """Return the artefact and what it was built from.

    Raises when there is nothing to build from. A capability that produces an
    empty page rather than refusing is how a job reports success for no work.
    """
    cases = _cases(research)
    if not cases:
        raise ValueError(
            "no published event pages in the research record — nothing to index. "
            "Research this business before proposing a portfolio system.")

    facts = _facts(research)
    total_images = sum(c["images"] for c in cases)
    rows = "\n".join(
        f'    <a class="rec" href="{html.escape(c["url"] or "#")}" '
        f'data-slug="{html.escape(c["slug"])}">'
        f'<span class="t">{html.escape(c["title"])}</span>'
        f'<span class="n">{c["images"]} photographs</span>'
        f'<span class="u">date · guests · service style — not published</span></a>'
        for c in cases)
    strength_line = (
        f'  <p class="strengths">{html.escape(" · ".join(strengths))}</p>'
        if strengths else "")

    artefact = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(business_name)} — the work</title>
<meta name="robots" content="noindex,nofollow"></head>
<body>
<main>
  <h1>a filterable index of the work</h1>
{strength_line}
  <p class="lead">{len(cases)} events already published, carrying {total_images}
  photographs. Each entry below is one this business publishes; where a detail is
  not published, it says so rather than guessing.</p>
  <div class="ledger">
{rows}
  </div>
  <p class="tally">{len(cases)} events · {total_images} photographs
  {"· " + str(facts["orphans"]) + " of these pages are linked from nothing" if facts.get("orphans") else ""}</p>
  <p class="note">one page per case follows this index.</p>
</main>
</body></html>
"""
    return artefact, {
        "cases": len(cases),
        "photographs": total_images,
        "source_pages": [c["slug"] for c in cases],
        "research_facts": facts,
        "invented_fields": 0,
    }
