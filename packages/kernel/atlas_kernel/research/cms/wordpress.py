"""WordPress, read through its own REST API.

The reference case is AHS: sixty pages, four posts, thirty-two event pages
carrying a hundred and seventy photographs, a five-hundred-item media library,
and a homepage that links to none of it. Every one of those numbers came from
`/wp-json/wp/v2/…` in a single pass, and none of them is discoverable by
crawling.

Read-only throughout: only public collections, only `GET`, no authentication
attempted and none of the endpoints that would expose drafts or users' emails.
"""

from __future__ import annotations

import html as html_module
import re

import httpx

from .base import CMSFacts, ContentItem

API = "/wp-json/wp/v2"
_TIMEOUT = 20.0
#: Enough to characterise a site without pulling an archive of thousands.
PER_PAGE = 100
MAX_ITEMS = 300

_TAG = re.compile(r"<[^>]+>")
_IMG = re.compile(r"<img\b", re.I)
_WS = re.compile(r"\s+")


def _text(raw: str) -> str:
    return _WS.sub(" ", html_module.unescape(_TAG.sub(" ", raw or ""))).strip()


def _item(row: dict, kind: str, categories: dict[int, str]) -> ContentItem:
    rendered = (row.get("content") or {}).get("rendered", "")
    body = _text(rendered)
    return ContentItem(
        slug=row.get("slug", ""),
        title=_text((row.get("title") or {}).get("rendered", "")),
        url=row.get("link", ""),
        kind=kind,
        published=(row.get("date") or "")[:19],
        words=len(body.split()),
        images=len(_IMG.findall(rendered)),
        categories=tuple(categories.get(c, str(c)) for c in (row.get("categories") or [])),
    )


class WordPress:
    """A `CMSReader` for WordPress."""

    platform = "WordPress"

    def detect(self, client: httpx.Client, root: str, html: str) -> bool:
        """Prefer the site's own advertisement of the API over guessing."""
        if "wp-json" in (html or "") or "/wp-content/" in (html or ""):
            return True
        try:
            probe = client.get(root.rstrip("/") + "/wp-json/", timeout=_TIMEOUT)
        except Exception:                        # noqa: BLE001
            return False
        return probe.status_code == 200 and "application/json" in \
            probe.headers.get("content-type", "")

    def _collection(self, client: httpx.Client, root: str, name: str,
                    fields: str = "") -> tuple[list[dict], int | None]:
        """One public collection, paged, bounded, and its declared total."""
        rows: list[dict] = []
        total: int | None = None
        page = 1
        while len(rows) < MAX_ITEMS:
            params = {"per_page": PER_PAGE, "page": page}
            if fields:
                params["_fields"] = fields
            response = client.get(f"{root.rstrip('/')}{API}/{name}",
                                  params=params, timeout=_TIMEOUT)
            if response.status_code != 200:
                break
            if total is None:
                header = response.headers.get("X-WP-Total")
                total = int(header) if header and header.isdigit() else None
            batch = response.json()
            if not isinstance(batch, list) or not batch:
                break
            rows += batch
            if len(batch) < PER_PAGE:
                break
            page += 1
        return rows[:MAX_ITEMS], total

    def read(self, client: httpx.Client, root: str) -> CMSFacts:
        facts = CMSFacts(platform=self.platform, detected=True)

        category_rows, _ = self._collection(client, root, "categories", "id,name,count")
        categories = {row["id"]: row.get("name", "") for row in category_rows}
        facts.categories = [row.get("name", "") for row in category_rows]

        page_rows, page_total = self._collection(client, root, "pages")
        facts.pages = [_item(row, "page", categories) for row in page_rows]
        if page_total and page_total > len(facts.pages):
            facts.notes.append(f"{page_total} pages exist; read the first {len(facts.pages)}")

        post_rows, post_total = self._collection(client, root, "posts")
        facts.posts = [_item(row, "post", categories) for row in post_rows]
        if post_total and post_total > len(facts.posts):
            facts.notes.append(f"{post_total} posts exist; read the first {len(facts.posts)}")

        # Media is counted, never downloaded — one request for the header.
        try:
            media = client.get(f"{root.rstrip('/')}{API}/media",
                               params={"per_page": 1, "_fields": "id"}, timeout=_TIMEOUT)
            header = media.headers.get("X-WP-Total")
            facts.media_total = int(header) if header and header.isdigit() else None
        except Exception:                        # noqa: BLE001
            facts.notes.append("media count unavailable")

        # A page carrying pictures and almost no words is a portfolio entry the
        # site is keeping without describing. This is the AHS pattern, and it is
        # an opportunity rather than a defect.
        facts.image_pages = [p for p in facts.pages if p.images >= 2 and p.words <= 12]
        return facts
