"""Reading a site's own content API instead of guessing from its HTML.

A crawl sees what a site links to. A content API sees what a site *has* — and
the gap between the two is where the value is. AHS publishes thirty-two event
pages carrying a hundred and seventy photographs and links to none of them from
the homepage; no amount of polite crawling finds that, and one request to
`/wp-json/wp/v2/pages` returns all of it.

The protocol comes first deliberately. WordPress is the first reader because it
is the most common, not because the design is about WordPress: a reader detects
itself, reads what it can, and reports facts in a vocabulary no vendor owns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import httpx

from ...opportunity.website_audit import Category, Finding, Status


@dataclass
class ContentItem:
    """One thing the CMS holds, in vendor-neutral terms."""

    slug: str
    title: str
    url: str
    kind: str = "page"          #: page | post | other
    published: str = ""
    words: int = 0
    images: int = 0
    categories: tuple[str, ...] = ()
    linked_from_nav: bool = False


@dataclass
class CMSFacts:
    """What the CMS said. Empty and `detected=False` is a perfectly good answer."""

    platform: str = ""
    detected: bool = False
    version_hint: str = ""
    pages: list[ContentItem] = field(default_factory=list)
    posts: list[ContentItem] = field(default_factory=list)
    media_total: int | None = None
    categories: list[str] = field(default_factory=list)
    #: Pages that are mostly photographs and almost no words — a portfolio the
    #: site is keeping without describing.
    image_pages: list[ContentItem] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def total_images(self) -> int:
        return sum(item.images for item in (*self.pages, *self.posts))

    def summary(self) -> dict:
        newest = max((p.published for p in self.posts), default="")
        oldest = min((p.published for p in self.posts), default="")
        return {
            "platform": self.platform, "detected": self.detected,
            "version_hint": self.version_hint,
            "pages": len(self.pages), "posts": len(self.posts),
            "media_total": self.media_total,
            "images_in_content": self.total_images,
            "image_pages": len(self.image_pages),
            "categories": self.categories[:20],
            "newest_post": newest, "oldest_post": oldest,
            "notes": self.notes[:10],
            # The pages themselves, not just how many. The portfolio capability
            # builds from these, and a summary that counted them and threw them
            # away would force a second crawl to recover what was already read.
            "image_page_list": [
                {"slug": p.slug, "title": p.title, "url": p.url, "images": p.images}
                for p in sorted(self.image_pages, key=lambda x: -x.images)[:80]
            ],
            # Same reasoning as image_page_list, for the editorial capability:
            # what they publish, not how much of it. An index built from a count
            # would have to guess at the titles.
            "post_list": [
                {"slug": p.slug, "title": p.title, "url": p.url,
                 "published": p.published, "words": p.words, "images": p.images,
                 "categories": list(p.categories)}
                for p in sorted(self.posts, key=lambda x: x.published, reverse=True)[:80]
            ],
        }


@runtime_checkable
class CMSReader(Protocol):
    """Detect, then read. Nothing else."""

    platform: str

    def detect(self, client: httpx.Client, root: str, html: str) -> bool: ...

    def read(self, client: httpx.Client, root: str) -> CMSFacts: ...


def read_cms(client: httpx.Client, root: str, html: str,
             readers: list[CMSReader] | None = None) -> tuple[CMSFacts, list[Finding]]:
    """Try each reader in turn. No detection is not a failure.

    A site with no readable CMS gets `detected=False` and no findings against
    it — "we could not read a content API" is a fact about our reach, not a
    defect in their website.
    """
    from .wordpress import WordPress

    for reader in (readers if readers is not None else [WordPress()]):
        try:
            if not reader.detect(client, root, html):
                continue
            facts = reader.read(client, root)
        except Exception as error:               # noqa: BLE001 - a CMS is data
            failed = CMSFacts(platform=reader.platform, detected=True)
            failed.notes.append(f"{type(error).__name__}: {error}"[:180])
            return failed, [Finding(
                feature="cms_content", category=Category.CONTENT,
                status=Status.UNVERIFIED,
                evidence=f"{reader.platform} detected but not readable: {failed.notes[-1]}")]
        return facts, _findings(facts)
    return CMSFacts(), []


def _findings(facts: CMSFacts) -> list[Finding]:
    """Only what the CMS actually establishes."""
    if not facts.detected:
        return []
    out = [Finding(feature="cms_content", category=Category.CONTENT, status=Status.PRESENT,
                   evidence=f"{facts.platform}: {len(facts.pages)} pages, "
                            f"{len(facts.posts)} posts, "
                            f"{facts.media_total if facts.media_total is not None else '?'} "
                            f"media items")]
    if facts.posts:
        out.append(Finding(
            feature="blog", category=Category.CONTENT, status=Status.PRESENT,
            evidence=f"{len(facts.posts)} posts, newest "
                     f"{max(p.published for p in facts.posts)[:10]}"))
    else:
        out.append(Finding(
            feature="blog", category=Category.CONTENT, status=Status.NOT_FOUND,
            evidence=f"{facts.platform} content API returned no posts"))
    if facts.image_pages:
        out.append(Finding(
            feature="portfolio_depth", category=Category.CONTENT, status=Status.PRESENT,
            evidence=f"{len(facts.image_pages)} pages are photographs with almost no text "
                     f"({sum(p.images for p in facts.image_pages)} images)"))
    return out
