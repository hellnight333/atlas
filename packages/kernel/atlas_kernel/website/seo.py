"""The files a site needs that nobody reads: sitemap, robots, canonicals.

These are the difference between a site that exists and a site that can be
found, and Atlas detects their absence on strangers' websites and sells the fix.
Shipping a generated site without them would be the same self-inconsistency as
the 222-character contact page: selling a repair for a defect we ship.

Three rules shape every line.

**Derived from the pages, never listed separately.** The sitemap is built from
the file map the theme produced. A hand-maintained list of URLs beside a
hand-maintained set of pages is two lists that must agree, and the one that
drifts is always the one nobody looks at — a sitemap naming a page that does not
exist is a crawl error on every visit.

**A site that is not published yet gets a sitemap that says so.** The canonical
URL of a preview is not the canonical URL of the live site, and writing the
preview's address into `<loc>` would publish the preview to search engines. With
no domain agreed, the sitemap is generated with relative paths and the robots
file disallows everything, so a preview that leaks cannot be indexed.

**Deterministic, like the pages.** Same content in, same bytes out: no
timestamps, no generated ids, sorted iteration. `lastmod` is deliberately
omitted rather than set to the build time — a build date is not a content date,
and a sitemap that claims every page changed today is a sitemap search engines
learn to ignore.
"""

from __future__ import annotations

from urllib.parse import quote, urlsplit

#: Pages a sitemap never lists.
NEVER_LISTED = frozenset({"robots.txt", "sitemap.xml", "404.html"})

#: What a preview's robots file says. Total exclusion, because a preview URL
#: that reaches an index is a customer's unfinished site in search results.
PREVIEW_ROBOTS = """\
User-agent: *
Disallow: /
"""


def _pages(files: dict[str, str]) -> list[str]:
    """Every HTML page in the bundle, in a stable order."""
    return sorted(name for name in files
                  if name.endswith(".html") and name not in NEVER_LISTED)


def canonical_host(website: str) -> str:
    """The scheme and host a site will actually be served from, or empty.

    Empty is a real answer and the common one: until somebody agrees a domain,
    there is no canonical URL, and inventing one puts a wrong address in the
    single place search engines trust most.
    """
    if not website:
        return ""
    parts = urlsplit(website if "//" in website else f"https://{website}")
    if not parts.netloc:
        return ""
    # Always https. A canonical pointing at http invites a redirect chain on
    # every crawl, and the site is served over https or it fails the gate.
    return f"https://{parts.netloc}"


def _url(host: str, page: str) -> str:
    """One page's URL. Relative when there is no host, which is honest."""
    path = "" if page == "index.html" else quote(page)
    return f"{host}/{path}" if host else (f"/{path}" if path else "/")


def sitemap(files: dict[str, str], *, website: str = "") -> str:
    """`sitemap.xml`, derived from the pages that exist.

    No `lastmod`. The only date available here is the build time, and a build
    date is not a content date — a sitemap claiming every page changed today is
    one a crawler learns to discount.
    """
    host = canonical_host(website)
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for page in _pages(files):
        lines.append(f"  <url><loc>{_url(host, page)}</loc></url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def robots(*, website: str = "", published: bool = False) -> str:
    """`robots.txt`.

    Disallows everything unless the site is actually published to an agreed
    domain. The default is the safe one because the common case is a preview,
    and a preview that reaches an index is the customer's unfinished site in
    somebody's search results — which nobody can un-publish on their behalf.
    """
    host = canonical_host(website)
    if not published or not host:
        return PREVIEW_ROBOTS
    return ("User-agent: *\n"
            "Allow: /\n"
            "\n"
            f"Sitemap: {host}/sitemap.xml\n")


def canonical_link(page: str, *, website: str = "") -> str:
    """The `<link rel="canonical">` for one page, or an empty string.

    Empty when no domain is agreed. A canonical tag pointing at a preview
    address tells search engines the preview is the real page.
    """
    host = canonical_host(website)
    if not host:
        return ""
    return f'<link rel="canonical" href="{_url(host, page)}">'


def artefacts(files: dict[str, str], *, website: str = "",
              published: bool = False) -> dict[str, str]:
    """The SEO files for this bundle, ready to be merged into it.

    Returned rather than written, so the caller merges them before hashing —
    the publication gate compares `bundle_hash(files)` against what was
    approved, and a file added after hashing is a file nobody approved.
    """
    return {"sitemap.xml": sitemap(files, website=website),
            "robots.txt": robots(website=website, published=published)}


def audit(files: dict[str, str], *, website: str = "") -> dict:
    """What is wrong with this bundle, in the terms Atlas uses on other people.

    Runs the same checks the detector runs against a stranger's site, so a
    generated bundle cannot ship a defect the sales pitch is about. Findings are
    statements about *this artefact*, not predictions about how it will rank.
    """
    pages = _pages(files)
    findings: list[dict] = []

    if not pages:
        findings.append({"kind": "no_pages",
                         "detail": "the bundle contains no HTML page"})

    for page in pages:
        body = files[page]
        for kind, needle, detail in (
            ("missing_title", "<title>", "no <title>"),
            ("missing_meta_description", '<meta name="description"',
             "no meta description"),
            ("missing_viewport", '<meta name="viewport"',
             "no viewport, so it renders badly on a phone"),
            ("missing_h1", "<h1>", "no <h1>"),
            ("missing_structured_data", "application/ld+json",
             "no structured data"),
        ):
            if needle not in body:
                findings.append({"kind": kind, "page": page, "detail": detail})

    # Every internal link must resolve inside the bundle. A generated site with
    # a broken internal link is the `broken` finding Atlas sells against, and it
    # is checkable here with certainty rather than by crawling later.
    for page in pages:
        for target in _internal_links(files[page]):
            if target not in files:
                findings.append({
                    "kind": "broken_link", "page": page,
                    "detail": f"links to {target}, which is not in the bundle"})

    if "sitemap.xml" not in files:
        findings.append({"kind": "missing_sitemap",
                         "detail": "no sitemap.xml"})
    if "robots.txt" not in files:
        findings.append({"kind": "missing_robots", "detail": "no robots.txt"})

    return {
        "pages": pages, "findings": findings, "clean": not findings,
        "website": canonical_host(website),
        "statement": ("Every page carries what the detector checks, and every "
                      "internal link resolves." if not findings else
                      f"{len(findings)} problem(s) in this bundle."),
    }


def _internal_links(markup: str) -> set[str]:
    """Same-bundle link targets. Ignores anchors, mail, tel and absolute URLs."""
    import re

    found = set()
    for href in re.findall(r'href="([^"]+)"', markup):
        if href.startswith(("#", "mailto:", "tel:", "http://", "https://", "//")):
            continue
        target = href.split("#", 1)[0].split("?", 1)[0]
        if target:
            found.add(target)
    return found
