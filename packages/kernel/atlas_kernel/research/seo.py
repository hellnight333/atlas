"""SEO as a real category, across a crawl rather than a homepage.

Most of what matters here is invisible on one page. Duplicate titles need two
pages to exist. An orphan page needs the sitemap *and* the link graph. Hreflang
reciprocity needs both sides. That is why this stage runs after the crawl and
the CMS read instead of alongside `audit_html`.

The line held throughout: this measures what the site publishes about itself. It
does not measure how the site ranks, and nothing here may be phrased as though
it did — there is no ranking data, so there is no ranking claim. Visibility is a
separate stage with its own evidence, and where that evidence is missing the
answer is NOT_VERIFIED.
"""

from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urljoin

from ..opportunity.website_audit import Category, Finding, Status
from .cms.base import CMSFacts
from .crawler import Crawl, links_in
from .net import normalise

_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_META = re.compile(r'<meta\b[^>]*\bname\s*=\s*["\']description["\'][^>]*\bcontent\s*=\s*["\']([^"\']*)',
                   re.I)
_CANON = re.compile(r'<link\b[^>]*\brel\s*=\s*["\']canonical["\'][^>]*\bhref\s*=\s*["\']([^"\']+)',
                    re.I)
_ROBOTS_META = re.compile(r'<meta\b[^>]*\bname\s*=\s*["\']robots["\'][^>]*\bcontent\s*=\s*["\']([^"\']*)',
                          re.I)
_H = re.compile(r"<h([1-6])\b[^>]*>(.*?)</h\1>", re.I | re.S)
_IMG = re.compile(r"<img\b[^>]*>", re.I)
#: A non-empty alt, quoted or not. `alt=""` is deliberate decoration and is
#: counted separately rather than as missing — marking a spacer image as an
#: accessibility defect trains people to ignore the finding.
_ALT = re.compile(r'\balt\s*=\s*(?:"[^"]+"|\'[^\']+\'|[^\s"\'>]+)', re.I)
_ALT_EMPTY = re.compile(r'\balt\s*=\s*(?:""|\'\')', re.I)
_OG = re.compile(r'<meta\b[^>]*\bproperty\s*=\s*["\']og:(\w+)["\']', re.I)
_LD = re.compile(r'<script[^>]*type\s*=\s*["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                 re.I | re.S)
_LD_TYPE = re.compile(r'"@type"\s*:\s*"([^"]+)"')
_HREFLANG = re.compile(r'<link\b[^>]*\bhreflang\s*=\s*["\']([^"\']+)["\'][^>]*\bhref\s*=\s*["\']([^"\']+)',
                       re.I)
_LANG = re.compile(r"<html\b[^>]*\blang\s*=\s*[\"']([^\"']+)", re.I)
_TAG = re.compile(r"<[^>]+>")

#: Below this a page has nothing for a reader or a search engine.
THIN_WORDS = 120


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", _TAG.sub(" ", html or "")).strip()


def analyse(walk: Crawl, *, cms: CMSFacts | None = None,
            sitemap_routes: list[str] | None = None) -> tuple[dict, list[Finding]]:
    pages = walk.html_pages
    findings: list[Finding] = []
    if not pages:
        return {"pages_analysed": 0}, [Finding(
            feature="seo", category=Category.SEO, status=Status.UNVERIFIED,
            evidence="no pages were retrieved, so nothing about SEO was established")]

    titles: Counter[str] = Counter()
    descriptions: Counter[str] = Counter()
    missing_title, missing_desc, missing_canon, no_h1, multi_h1 = [], [], [], [], []
    thin, images, images_with_alt, decorative = [], 0, 0, 0
    schema_types: Counter[str] = Counter()
    og_pages, hreflang_pages, noindex = 0, 0, []
    languages: Counter[str] = Counter()
    outbound: dict[str, set[str]] = {}

    for page in pages:
        html = page.html
        title = _text(_TITLE.search(html).group(1)) if _TITLE.search(html) else ""
        (titles.update([title]) if title else missing_title.append(page.url))
        desc = _META.search(html)
        (descriptions.update([desc.group(1).strip()]) if desc else missing_desc.append(page.url))
        if not _CANON.search(html):
            missing_canon.append(page.url)
        robots_meta = _ROBOTS_META.search(html)
        if robots_meta and "noindex" in robots_meta.group(1).lower():
            noindex.append(page.url)

        headings = _H.findall(html)
        h1s = [h for level, h in headings if level == "1"]
        if not h1s:
            no_h1.append(page.url)
        elif len(h1s) > 2:      # themes routinely render a mobile duplicate
            multi_h1.append(page.url)

        body_words = len(_text(html).split())
        if body_words < THIN_WORDS:
            thin.append(page.url)

        page_images = _IMG.findall(html)
        images += len(page_images)
        images_with_alt += sum(1 for tag in page_images if _ALT.search(tag))
        decorative += sum(1 for tag in page_images if _ALT_EMPTY.search(tag))

        for block in _LD.findall(html):
            schema_types.update(_LD_TYPE.findall(block))
        if _OG.search(html):
            og_pages += 1
        if _HREFLANG.search(html):
            hreflang_pages += 1
        lang = _LANG.search(html)
        if lang:
            languages.update([lang.group(1).lower()])

        outbound[normalise(page.url)] = {
            normalise(urljoin(page.url, link)) for link in links_in(html, base=page.url)}

    total = len(pages)
    linked_to = {target for targets in outbound.values() for target in targets}

    def add(feature: str, ok: bool, category: Category, evidence: str) -> None:
        findings.append(Finding(feature=feature, category=category,
                                status=Status.PRESENT if ok else Status.NOT_FOUND,
                                evidence=evidence))

    add("page_title", not missing_title, Category.SEO,
        f"every one of {total} pages has a title" if not missing_title
        else f"{len(missing_title)} of {total} pages have no title")
    add("meta_description", not missing_desc, Category.SEO,
        f"all {total} pages carry a description" if not missing_desc
        else f"{len(missing_desc)} of {total} pages have no meta description")
    add("canonical", not missing_canon, Category.SEO,
        f"canonical on all {total} pages" if not missing_canon
        else f"{len(missing_canon)} of {total} pages have no canonical")

    duplicate_titles = [t for t, n in titles.items() if n > 1]
    add("duplicate_titles", not duplicate_titles, Category.SEO,
        "no two pages share a title" if not duplicate_titles
        else f"{len(duplicate_titles)} title(s) used on more than one page: "
             f"{duplicate_titles[0][:60]!r}")
    duplicate_desc = [d for d, n in descriptions.items() if n > 1 and d]
    if descriptions:
        add("duplicate_descriptions", not duplicate_desc, Category.SEO,
            "descriptions are distinct" if not duplicate_desc
            else f"{len(duplicate_desc)} description(s) reused across pages")

    add("h1", not no_h1, Category.SEO,
        f"an h1 on all {total} pages" if not no_h1 else f"{len(no_h1)} page(s) have no h1")
    if multi_h1:
        findings.append(Finding(
            feature="heading_structure", category=Category.SEO, status=Status.NOT_FOUND,
            evidence=f"{len(multi_h1)} page(s) render more than two h1s — "
                     "usually a theme emitting desktop and mobile copies"))

    if images:
        described = images - decorative
        coverage = images_with_alt / described if described else 1.0
        add("image_alt_text", coverage >= 0.8, Category.ACCESSIBILITY,
            f"{images_with_alt} of {described} content images have alt text "
            f"({coverage:.0%}); {decorative} marked decorative")

    add("structured_data", bool(schema_types), Category.SEO,
        f"schema types: {', '.join(sorted(schema_types))[:80]}" if schema_types
        else "no JSON-LD structured data on any page crawled")
    add("open_graph", og_pages > 0, Category.SEO,
        f"Open Graph on {og_pages} of {total} pages" if og_pages
        else "no Open Graph tags, so shared links render without a card")

    # Multilingual: a single declared language and no alternates is English-only.
    if hreflang_pages:
        add("hreflang", True, Category.MULTILINGUAL,
            f"hreflang alternates on {hreflang_pages} of {total} pages")
    else:
        findings.append(Finding(
            feature="hreflang", category=Category.MULTILINGUAL, status=Status.NOT_FOUND,
            evidence=f"no hreflang anywhere; html lang is "
                     f"{', '.join(sorted(languages)) or 'undeclared'}"))

    # The engine already has an `arabic` rule. Across a whole crawl the absence
    # of any hreflang *and* of an Arabic lang declaration is a confirmed
    # absence, which one homepage could never establish.
    arabic_declared = any(code.startswith("ar") for code in languages)
    findings.append(Finding(
        feature="arabic", category=Category.MULTILINGUAL,
        status=Status.PRESENT if arabic_declared else Status.NOT_FOUND,
        evidence=f"Arabic declared on {languages.get('ar', 0)} page(s)" if arabic_declared
        else f"no Arabic version: no hreflang across {total} pages, html lang is "
             f"{', '.join(sorted(languages)) or 'undeclared'}"))

    if noindex:
        findings.append(Finding(
            feature="indexability", category=Category.SEO, status=Status.NOT_FOUND,
            evidence=f"{len(noindex)} crawled page(s) carry meta robots noindex"))

    if thin:
        findings.append(Finding(
            feature="thin_pages", category=Category.CONTENT, status=Status.NOT_FOUND,
            evidence=f"{len(thin)} of {total} pages carry under {THIN_WORDS} words"))

    # Orphans need the CMS or the sitemap to know a page exists at all — the
    # crawl alone can only find what something already links to.
    known = {normalise(r) for r in (sitemap_routes or [])}
    if cms and cms.detected:
        known |= {normalise(item.url) for item in cms.pages if item.url}
    orphans = sorted(known - linked_to - {normalise(p.url) for p in pages})
    if known:
        findings.append(Finding(
            feature="orphan_pages", category=Category.SEO,
            status=Status.NOT_FOUND if orphans else Status.PRESENT,
            evidence=f"{len(orphans)} published page(s) are not linked from anything crawled"
            if orphans else f"every one of {len(known)} known pages is linked"))
    else:
        findings.append(Finding(
            feature="orphan_pages", category=Category.SEO, status=Status.UNVERIFIED,
            evidence="no sitemap and no CMS, so which pages exist is unknown"))

    facts = {
        "pages_analysed": total, "titles": len(titles), "duplicate_titles": duplicate_titles[:5],
        "duplicate_descriptions": len(duplicate_desc), "missing_title": len(missing_title),
        "missing_description": len(missing_desc), "missing_canonical": len(missing_canon),
        "no_h1": len(no_h1), "multiple_h1": len(multi_h1), "thin_pages": len(thin),
        "images": images, "images_with_alt": images_with_alt,
        "decorative_images": decorative,
        "schema_types": sorted(schema_types), "open_graph_pages": og_pages,
        "hreflang_pages": hreflang_pages, "languages": sorted(languages),
        "noindex_pages": len(noindex), "orphans": orphans[:20], "orphan_count": len(orphans),
    }
    return facts, findings
