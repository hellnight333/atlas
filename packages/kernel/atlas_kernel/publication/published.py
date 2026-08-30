"""Everything Qevik has actually put on the internet, and whether it is still up.

The operator had no way to see this. `sites.qevik.ai` serves 57 directories; the
control plane recorded publications for one of them, and the Publications page
promised "what has actually gone live" while showing only the queue of things
waiting for authorisation.

Two kinds of thing get published and they are written by different paths:

  - `publication_completed` — the mission pipeline, for a business's own site.
  - `website_demo_published` — the demo built during outreach, whose URL goes
    into the message. **These are the ones that matter commercially**: a dead
    demo means an approved message pointing a stranger at nothing.

This reads both and returns one list. It is a *read*: nothing here publishes,
and the two writers stay exactly where they are — merging them into one event
kind would rewrite history to tidy a report.

Liveness is asked separately and never inferred. A directory existing on a disk
is not a site being served, and the publication card already refuses to work it
out that way; this asks the URL.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

#: The two timeline entries that mean something is on the internet.
PUBLICATION_EVENT = "publication_completed"
DEMO_EVENT = "website_demo_published"


class Liveness(StrEnum):
    """Three states. A site that could not be checked is not a site that is down.

    Reporting NOT_CHECKED as DOWN would have somebody rebuild a site that is
    serving perfectly; reporting it as LIVE would have them send outreach
    pointing at a dead page. Both are worse than saying nothing is known.
    """

    LIVE = "CONFIRMED_LIVE"
    DOWN = "CONFIRMED_DOWN"
    UNKNOWN = "NOT_CHECKED"


@dataclass(frozen=True)
class Published:
    """One thing Qevik has published."""

    url: str
    kind: str
    #: `site-…` for a mission publication, the slug for a demo.
    identifier: str
    at: str
    business_id: str = ""
    mission_id: str = ""
    commit: str = ""
    liveness: Liveness = Liveness.UNKNOWN
    status: int = 0
    detail: str = ""

    @property
    def is_demo(self) -> bool:
        """A demo URL travels inside an outreach message. That is why its
        liveness is a commercial fact and not a housekeeping one."""
        return self.kind == DEMO_EVENT

    def summary(self) -> dict:
        return {"url": self.url, "kind": self.kind, "identifier": self.identifier,
                "at": self.at, "business_id": self.business_id,
                "mission_id": self.mission_id, "commit": self.commit,
                "is_demo": self.is_demo, "liveness": self.liveness.value,
                "status": self.status, "detail": self.detail}


def _detail(raw: Any) -> dict:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return {}
    return raw or {}


def from_events(rows: list) -> tuple[Published, ...]:
    """Every publication on the timeline, newest first, one row per URL.

    De-duplicated by URL because republishing the same site is the ordinary
    case — the mission pipeline recorded the same address three times — and a
    list with one row per event answers "how many times did we publish" when
    the operator asked "what is published".
    """
    newest: dict[str, Published] = {}
    for row in rows:
        kind = row.get("kind") if isinstance(row, dict) else getattr(row, "kind", "")
        if kind not in (PUBLICATION_EVENT, DEMO_EVENT):
            continue
        detail = _detail(row.get("detail") if isinstance(row, dict)
                         else getattr(row, "detail", None))
        url = (detail.get("url") or detail.get("demo_url") or "").strip()
        if not url:
            continue
        at = str(detail.get("published_at") or detail.get("at") or
                 (row.get("at") if isinstance(row, dict) else getattr(row, "at", "")))
        found = Published(
            url=url, kind=kind,
            identifier=detail.get("site_id") or detail.get("slug") or "",
            at=at,
            business_id=detail.get("business_id") or "",
            mission_id=detail.get("mission_id") or "",
            commit=detail.get("commit") or detail.get("version_id") or "")
        seen = newest.get(url)
        if seen is None or found.at >= seen.at:
            newest[url] = found
    return tuple(sorted(newest.values(), key=lambda p: p.at, reverse=True))


def check(page: Any) -> tuple[Liveness, int, str]:
    """Read one fetched page as a liveness verdict.

    Takes the `Page` rather than fetching, so the decision is testable without a
    network and the fetching stays in one place.

    A transport error is `NOT_CHECKED`, never `DOWN`: "we could not reach it"
    and "it is not there" are different facts, and only the second is a reason
    to rebuild anything. A 4xx or 5xx *is* an answer — the server spoke — so it
    is a confirmed finding.
    """
    error = getattr(page, "error", "") or ""
    status = int(getattr(page, "status", 0) or 0)
    if error and status == 0:
        return Liveness.UNKNOWN, 0, error
    if status == 0:
        return Liveness.UNKNOWN, 0, "no response and no error was recorded"
    if 200 <= status < 300:
        # A 200 serving nothing is not a live page. The published demos are
        # ~2KB; an empty body means the directory is there and the file is not.
        if int(getattr(page, "bytes", 0) or 0) <= 0:
            return Liveness.DOWN, status, "answered 200 with an empty body"
        return Liveness.LIVE, status, ""
    return Liveness.DOWN, status, f"the server answered {status}"


__all__ = ["DEMO_EVENT", "PUBLICATION_EVENT", "Liveness", "Published", "check",
           "from_events"]
