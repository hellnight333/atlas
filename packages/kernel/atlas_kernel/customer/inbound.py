"""Somebody asked Qevik about their own website. That is a lead.

`POST /api/public/audit` is the one place a stranger arrives under their own
steam — they typed their address in and asked what we found. It answered and
forgot them. Every other signal in this system is Qevik noticing a business;
this is a business noticing Qevik, which is a far stronger one and the only
inbound signal that exists.

It is also where a health-check recipient lands. The published page invites
them to see what we would change; without this they arrive, read, leave, and
nothing records that they came.

## What is recorded, and what deliberately is not

**The website, the moment, and what Qevik already knew.** That is enough for an
operator to act on and it is not personal data: a company's public address is a
fact about a company. No name, no email, no phone, no IP, no user agent, no
cookie — none of which the route receives and none of which it should start
receiving to make this richer.

The roadmap's instruction for this track is to handle personal data lawfully and
conservatively. The most conservative version of a lead is one that identifies a
*business* rather than a person, and that is what this is.

## Where it lives

On `atlas_business_events`, like everything else. There is no lead table and
there must not be one: a lead is something that happened, the timeline already
holds things that happened, and a second store is a second thing that can
disagree with the first about who asked and when.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

#: The timeline entry. One name, used by the writer and by every reader.
LEAD_EVENT = "lead_captured"

#: How the request arrived. Recorded rather than inferred, because "they found
#: the public audit" and "they clicked through from a health check we sent them"
#: are different commercial facts and only the second closes a loop.
SOURCE_PUBLIC_AUDIT = "public-audit"


@dataclass(frozen=True)
class AuditRequest:
    """One moment when a business asked about itself.

    **Not a company record.** `test_one_customer_entity` refused an earlier
    version of this called `Lead`, and it was right to: "lead" is the head noun
    of a second customer entity, and a factory that grows its own is how one
    company ends up as a Prospect here, a Client there and a Seller somewhere
    else. This is a *request* — a thing that happened at a moment — and the
    company it is about is `atlas_businesses.id`, referenced and never copied.
    """

    website: str
    #: The registrable host, so two spellings of one address are one lead.
    host: str
    source: str
    at: str
    #: What Qevik already held about them when they asked. Zero means the
    #: audit had never seen this site — which is not a failure, and is the
    #: single most useful thing for an operator to know before replying.
    observations: int = 0
    #: The business this matched, when research already knew them.
    business_id: str = ""

    @property
    def already_known(self) -> bool:
        return bool(self.business_id) or self.observations > 0

    def summary(self) -> dict:
        return {"website": self.website, "host": self.host,
                "source": self.source, "at": self.at,
                "observations": self.observations,
                "business_id": self.business_id,
                "already_known": self.already_known}


def host_of(website: str) -> str:
    """The host, lowercased, without `www.`.

    Two spellings of one address are one lead. Without this a business that
    types `https://example.ae/` on Monday and `example.ae` on Tuesday is two
    rows, and the operator sees interest where there was persistence.
    """
    raw = (website or "").strip()
    if not raw:
        return ""
    if "//" not in raw:
        raw = f"//{raw}"
    host = (urlparse(raw).hostname or "").lower().strip(".")
    if host.startswith("www."):
        host = host[4:]
    # A host has a dot and no spaces. Without this, "not a url" parses to
    # itself and becomes a lead an operator cannot act on, at the top of the
    # one list in this system that is inbound.
    if "." not in host or " " in host:
        return ""
    return host


def capture(*, website: str, observations: int = 0, business_id: str = "",
            source: str = SOURCE_PUBLIC_AUDIT,
            at: datetime | None = None) -> AuditRequest | None:
    """The request this represents, or `None` when it represents none.

    `None` for a request with no usable address. A lead whose host cannot be
    read is a row an operator cannot act on, and recording it would put noise
    at the top of the one list in this system that is inbound.
    """
    host = host_of(website)
    if not host:
        return None
    return AuditRequest(website=website.strip(), host=host, source=source,
                at=(at or datetime.now(UTC)).isoformat(),
                observations=max(0, int(observations)),
                business_id=business_id)


def from_events(rows: list) -> tuple[AuditRequest, ...]:
    """Every lead on the timeline, newest first, one row per host.

    De-duplicated by host and **counted**, because a business that asks three
    times is one lead and three visits — and the second fact is the interesting
    one. `asked` carries it so nothing has to read the raw events again.
    """
    import json

    newest: dict[str, AuditRequest] = {}
    counts: dict[str, int] = {}
    for row in rows:
        kind = row.get("kind") if isinstance(row, dict) else getattr(row, "kind", "")
        if kind != LEAD_EVENT:
            continue
        detail = row.get("detail") if isinstance(row, dict) else getattr(row, "detail", None)
        if isinstance(detail, str):
            try:
                detail = json.loads(detail)
            except (TypeError, ValueError):
                continue
        detail = detail or {}
        host = detail.get("host") or host_of(detail.get("website", ""))
        if not host:
            continue
        counts[host] = counts.get(host, 0) + 1
        found = AuditRequest(website=detail.get("website", ""), host=host,
                     source=detail.get("source", ""),
                     at=str(detail.get("at", "")),
                     observations=int(detail.get("observations") or 0),
                     business_id=detail.get("business_id", ""))
        seen = newest.get(host)
        if seen is None or found.at >= seen.at:
            newest[host] = found
    return tuple(
        sorted(({**lead.summary(), "asked": counts[host]}  # type: ignore[misc]
                for host, lead in newest.items()),
               key=lambda row: row["at"], reverse=True))


__all__ = ["LEAD_EVENT", "SOURCE_PUBLIC_AUDIT", "AuditRequest", "capture",
           "from_events", "host_of"]
