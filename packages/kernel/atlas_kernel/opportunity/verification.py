"""Reading website-verification evidence into findings.

A verification mission fetches the websites Qevik has recorded and stores what
each server said. Until this module existed, that was where it stopped: real
responses, recorded with provenance, that nothing ever read. The evidence was
genuine and the system drew nothing from it.

## What this is, and what it deliberately is not

It is a **reader**. It performs no fetches, opens no sockets and reaches no
network. Everything it produces comes out of `Evidence.observed`, written by
`crawler.evidence_from` at the moment a guarded fetcher completed. That
matters for a reason beyond tidiness: the guard — allow-list, robots, address
checks on every redirect hop — ran once, at fetch time, and an auditor that
re-fetched would have to be trusted with all of it again.

The finding rules are **not here either**. They are `WebsiteDetector`'s, reached
through `findings_from`, which is why an audit of stored evidence produces
exactly what a live inspection would have produced from the same page. A second
implementation reading the same evidence would agree on the day it was written
and drift the first time `SLOW_RESPONSE_SECONDS` moved.

## What the evidence cannot support

Three refusals, each of them a false finding that would otherwise ship:

**A refusal is not a response.** `crawler.fetch_steps` records a blocked
address, a robots exclusion and a dead host as evidence too — status 0 with an
error. That is `NOT_VERIFIED`: nobody saw the site. Auditing it would report a
business whose homepage Qevik was not allowed to fetch as a business with a
broken homepage.

**A truncated body is not a short page.** Handled in `PageObservation`, and the
reason its `body_complete` field exists.

**Evidence of the wrong kind is not weak evidence.** A DNS record carries no
status and no markup. It is refused rather than read with defaults, because
defaults are how a missing field becomes a confirmed absence.

## Matching a response back to a business

By the URL that was **requested**, not the one that answered. A site that
redirects `example.ae` to `www.example.ae` produces evidence whose source is
the second, and Qevik's memory holds the first. The requested address is the
head of `redirect_chain` when there was a redirect, and the source otherwise —
so the join survives the redirect rather than silently dropping every business
whose site moves visitors to `www`.
"""

from __future__ import annotations

import logging
from urllib.parse import urlsplit

from .detectors.website import PageObservation, WebsiteDetector
from .models import Business, Evidence, EvidenceKind, Finding

log = logging.getLogger(__name__)

#: The kinds of evidence a website audit can read. Anything else is refused:
#: a DNS record and a screenshot are real evidence about a business and say
#: nothing about what its homepage returned.
READABLE = frozenset({EvidenceKind.HTTP_RESPONSE, EvidenceKind.HTML_CONTENT})

#: What a caller should attach alongside a finding from this path, so the
#: chain back to the mission survives. `Finding` carries no detector of its
#: own — provenance lives on each `Evidence` — and the derived evidence a
#: finding holds names the *rules* that produced it, not the fetch. The
#: original recorded response is what proves the fetch happened, so anything
#: building a signal from these findings carries it too. See
#: `detect.weak_web_presence`.
DETECTOR = "website"


class Unreadable(Exception):
    """This evidence cannot support a website finding, and why."""


def requested_url(evidence: Evidence) -> str:
    """The address that was asked for, before any redirect."""
    chain = evidence.observed.get("redirect_chain") or []
    if isinstance(chain, list) and chain and isinstance(chain[0], str):
        return chain[0]
    return evidence.source


def observation_from(evidence: Evidence) -> PageObservation:
    """One recorded response, as the observation the finding rules read.

    Raises `Unreadable` rather than returning a half-filled observation. An
    observation with a defaulted status is one every rule downstream would
    happily reason about.
    """
    if evidence.kind not in READABLE:
        raise Unreadable(
            f"{evidence.kind.value} evidence says nothing about what a homepage "
            "returned. Only a recorded HTTP response can.")

    observed = evidence.observed
    error = str(observed.get("error") or "")
    status = observed.get("status")
    if not isinstance(status, int):
        raise Unreadable(
            "this evidence carries no HTTP status, so nothing establishes that "
            "a server answered at all.")
    if status == 0 or error:
        # The distinction the whole subsystem exists to hold. A fetch that was
        # refused, disallowed or never completed is NOT_VERIFIED. Turning it
        # into SITE_UNREACHABLE would report Qevik's own guard as the
        # business's outage.
        raise Unreadable(
            f"nothing was retrieved: {error or 'no response'}. A fetch that did "
            "not happen is not a finding about the site.")

    body = observed.get("body")
    body = body if isinstance(body, str) else ""
    truncated = bool(observed.get("body_truncated"))
    size = observed.get("bytes")
    size = size if isinstance(size, int) else len(body)
    # A body dropped for being enormous arrives empty with a byte count that is
    # not. Treating that as a complete empty page is exactly the storage-limit
    # -becomes-a-finding mistake `body_complete` exists to prevent.
    dropped = not body and size > 0
    elapsed_ms = observed.get("elapsed_ms")
    elapsed_ms = elapsed_ms if isinstance(elapsed_ms, (int, float)) else 0

    return PageObservation(
        requested_url=requested_url(evidence),
        final_url=evidence.source,
        status=status,
        content_type=str(observed.get("content_type") or ""),
        elapsed_seconds=float(elapsed_ms) / 1000.0,
        bytes=size,
        body=body,
        body_complete=not (truncated or dropped),
    )


def audit(business: Business, evidence: Evidence, *,
          detector: WebsiteDetector | None = None) -> list[Finding]:
    """Findings this recorded response supports for this business.

    Empty when it supports none — including when it cannot be read at all,
    which is reported to the log and not to the opportunity list.
    """
    try:
        page = observation_from(evidence)
    except Unreadable as refused:
        log.info("not auditing %s: %s", evidence.source, refused)
        return []

    return (detector or WebsiteDetector()).findings_from(business, page)


def owner_index(businesses: dict[str, Business]) -> dict[str, Business]:
    """A lookup from recorded website to the business that claims it.

    `businesses` is keyed by the address as memory holds it. This is the one
    place the comparison rule lives, so the audit and anything else pairing a
    response to a company cannot disagree about which URLs are the same site.
    """
    return {_key(url): business for url, business in businesses.items()}


def owner_of(evidence: Evidence, index: dict[str, Business]) -> Business | None:
    """Which business this response belongs to, or none.

    Tries the requested address first and the answering one second, so a site
    that redirects still matches whichever of the two memory happens to hold.
    Returns `None` rather than a guess: the addresses came from memory, so an
    unmatched response means memory changed under the run, and inventing an
    owner would put a finding on the wrong company.
    """
    return (index.get(_key(requested_url(evidence)))
            or index.get(_key(evidence.source)))


def audit_pass(businesses: dict[str, Business], evidence: list[Evidence], *,
               detector: WebsiteDetector | None = None
               ) -> dict[str, list[Finding]]:
    """Every finding a verification pass supports, by business id."""
    shared = detector or WebsiteDetector()
    index = owner_index(businesses)
    found: dict[str, list[Finding]] = {}
    for piece in evidence:
        business = owner_of(piece, index)
        if business is None:
            log.info("no business claims %s; not attributing findings to one",
                     piece.source)
            continue
        supported = audit(business, piece, detector=shared)
        if supported:
            found.setdefault(business.id, []).extend(supported)
    return found


def _key(url: str) -> str:
    """A URL reduced to what makes two addresses the same website here.

    Scheme and a trailing slash are exactly what a redirect changes, and are
    the two differences that must not break the join. Anything more aggressive
    — dropping `www`, ignoring the path — would merge two addresses that a
    business may genuinely run as different sites.
    """
    parts = urlsplit(url.strip())
    host = (parts.netloc or parts.path).lower().rstrip("/")
    path = (parts.path if parts.netloc else "").rstrip("/")
    return f"{host}{path}"


__all__ = ["DETECTOR", "READABLE", "Unreadable", "audit", "audit_pass",
           "observation_from", "owner_index", "owner_of", "requested_url"]
