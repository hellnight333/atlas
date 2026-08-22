"""What the business has written, and whether writing more would help.

The instruction this exists to obey: **do not automatically say "needs a blog".**
A company with eighty useful posts does not have a blog opportunity, it has a
distribution opportunity, and telling them to start blogging would announce that
nobody looked.

So this measures four separate things and only the combination decides anything:
does a blog exist, is there enough of it, is it recent, and is it connected to
the things the business sells. A blog can fail on any one of those while passing
the others, and each failure has a different remedy.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ..opportunity.website_audit import Category, Finding, Status
from .cms.base import CMSFacts, ContentItem

#: Below this the blog is a stub rather than a body of work.
THIN_POSTS = 6
#: A post shorter than this rarely ranks or holds a reader.
SHORT_WORDS = 400
#: Older than this and the blog reads as abandoned.
STALE_DAYS = 240


def _age_days(published: str) -> int | None:
    try:
        when = datetime.fromisoformat(published.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return (datetime.now(UTC) - when).days


def analyse(cms: CMSFacts, *, service_slugs: tuple[str, ...] = ()) -> tuple[dict, list[Finding]]:
    findings: list[Finding] = []
    if not cms.detected:
        return {"read": False}, [Finding(
            feature="blog_quality", category=Category.CONTENT, status=Status.UNVERIFIED,
            evidence="no readable content API, so the blog was not assessed")]

    posts: list[ContentItem] = list(cms.posts)
    if not posts:
        return ({"read": True, "posts": 0}, [Finding(
            feature="blog_quality", category=Category.CONTENT, status=Status.NOT_FOUND,
            evidence="the CMS holds no posts")])

    ages = [a for a in (_age_days(p.published) for p in posts) if a is not None]
    newest = min(ages) if ages else None
    same_day = len({p.published[:10] for p in posts}) == 1
    without_images = [p for p in posts if p.images == 0]
    short = [p for p in posts if p.words < SHORT_WORDS]
    uncategorised = [p for p in posts
                     if not p.categories or set(p.categories) <= {"Uncategorized"}]
    linked_to_services = [
        p for p in posts
        if service_slugs and any(slug in (p.slug or "") for slug in service_slugs)]

    substantial = len(posts) >= THIN_POSTS and len(short) < len(posts) * 0.6
    findings.append(Finding(
        feature="blog_quality", category=Category.CONTENT,
        status=Status.PRESENT if substantial else Status.NOT_FOUND,
        evidence=f"{len(posts)} posts, {len(short)} under {SHORT_WORDS} words"
                 + (f", newest {newest} days old" if newest is not None else "")))

    if newest is not None:
        findings.append(Finding(
            feature="blog_freshness", category=Category.CONTENT,
            status=Status.PRESENT if newest <= STALE_DAYS else Status.NOT_FOUND,
            evidence=f"most recent post is {newest} days old"))

    # Every post published on one day is a launch, not a habit — and it is the
    # difference between "keep going" and "start".
    if same_day and len(posts) > 1:
        findings.append(Finding(
            feature="blog_cadence", category=Category.CONTENT, status=Status.NOT_FOUND,
            evidence=f"all {len(posts)} posts were published on "
                     f"{posts[0].published[:10]}"))

    if without_images:
        findings.append(Finding(
            feature="blog_media", category=Category.CONTENT,
            status=Status.NOT_FOUND if len(without_images) == len(posts) else Status.PRESENT,
            evidence=f"{len(without_images)} of {len(posts)} posts carry no image"
                     + (f", against a library of {cms.media_total}"
                        if cms.media_total else "")))

    if uncategorised:
        findings.append(Finding(
            feature="blog_structure", category=Category.CONTENT,
            status=Status.NOT_FOUND if len(uncategorised) == len(posts) else Status.PRESENT,
            evidence=f"{len(uncategorised)} of {len(posts)} posts are uncategorised"))

    if service_slugs:
        findings.append(Finding(
            feature="content_to_service", category=Category.CONTENT,
            status=Status.PRESENT if linked_to_services else Status.NOT_FOUND,
            evidence=f"{len(linked_to_services)} post(s) map to a service page"
            if linked_to_services else "no post maps onto anything the business sells"))

    facts = {
        "read": True, "posts": len(posts), "substantial": substantial,
        "newest_days": newest, "all_same_day": same_day,
        "posts_without_images": len(without_images), "short_posts": len(short),
        "uncategorised": len(uncategorised), "categories": cms.categories[:20],
        "median_words": sorted(p.words for p in posts)[len(posts) // 2],
        "linked_to_services": len(linked_to_services),
    }
    return facts, findings
