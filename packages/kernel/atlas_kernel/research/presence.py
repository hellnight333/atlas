"""Which channels a business actually has, and how sure we are.

Two failure modes to avoid, and they pull in opposite directions.

Claiming absence from silence: the site not linking Instagram does not mean
there is no Instagram, and "you have no social presence" is a humiliating thing
to be wrong about. So a channel the site does not link is `NOT_VERIFIED` until
something else establishes it, never `NOT_FOUND`.

Attaching the wrong account: a search for a common trading name returns other
people's profiles. So a channel found by searching is `PROBABLE` at best, and
only a link from the business's own site makes it `OFFICIAL`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from ..opportunity.website_audit import Category, Finding, Status

CHANNELS: dict[str, str] = {
    "instagram": r"instagram\.com/([A-Za-z0-9_.]+)",
    "linkedin": r"linkedin\.com/(?:company|in)/([A-Za-z0-9_\-]+)",
    "facebook": r"facebook\.com/([A-Za-z0-9_.\-]+)",
    "youtube": r"youtube\.com/(?:@|c/|channel/|user/)([A-Za-z0-9_\-]+)",
    "tiktok": r"tiktok\.com/@([A-Za-z0-9_.]+)",
    "x": r"(?:twitter|x)\.com/([A-Za-z0-9_]+)",
    "google_maps": r"(?:google\.com/maps|maps\.app\.goo\.gl)/\S+",
    "whatsapp": r"wa\.me/(\d+)",
}

#: Paths that look like a channel but are share buttons or SDK noise.
_NOISE = re.compile(r"(sharer|share\?|intent/|/plugins/|platform\.|widgets\.|/embed/"
                    r"|connect\.facebook)", re.I)


class Confidence(StrEnum):
    #: Linked from the business's own website.
    OFFICIAL = "official"
    #: Found some other way. Never stated as theirs without a human confirming.
    PROBABLE = "probable"
    UNVERIFIED = "unverified"


@dataclass(frozen=True)
class Channel:
    name: str
    handle: str = ""
    url: str = ""
    confidence: Confidence = Confidence.UNVERIFIED
    found: bool = False


def from_site(pages_html: list[str]) -> dict[str, Channel]:
    """Channels the business links from its own pages. These are official."""
    combined = "\n".join(pages_html)
    found: dict[str, Channel] = {}
    for name, pattern in CHANNELS.items():
        for match in re.finditer(pattern, combined, re.I):
            fragment = combined[max(0, match.start() - 120):match.end() + 40]
            if _NOISE.search(fragment):
                continue
            handle = match.group(1) if match.groups() else ""
            found[name] = Channel(name=name, handle=handle, url=match.group(0),
                                  confidence=Confidence.OFFICIAL, found=True)
            break
    return found


def assess(pages_html: list[str], *, searched: dict[str, Channel] | None = None
           ) -> tuple[dict, list[Finding]]:
    """What the site links, plus anything a search stage supplied."""
    if not pages_html:
        return ({"read": False}, [Finding(
            feature="social_links", category=Category.TRUST, status=Status.UNVERIFIED,
            evidence="no pages were retrieved, so linked channels are unknown")])

    linked = from_site(pages_html)
    channels = dict(linked)
    for name, channel in (searched or {}).items():
        channels.setdefault(name, channel)

    social = [c for n, c in channels.items()
              if n not in ("google_maps", "whatsapp") and c.found]
    official = [c for c in social if c.confidence is Confidence.OFFICIAL]

    findings = [Finding(
        feature="social_links", category=Category.TRUST,
        status=Status.PRESENT if official else Status.NOT_FOUND,
        evidence=", ".join(f"{c.name} ({c.handle})" for c in official)
        if official else "the site links no social account from any page crawled")]

    # Only ever a real absence when the site links it nowhere *and* nothing else
    # found it. Otherwise it is a question, not a finding.
    for name in ("instagram", "linkedin"):
        if name in linked:
            continue
        probable = channels.get(name)
        findings.append(Finding(
            feature=f"{name}_presence", category=Category.TRUST,
            status=Status.UNVERIFIED,
            evidence=(f"not linked from the site; a search suggests {probable.url} "
                      "which is unconfirmed" if probable and probable.found
                      else "not linked from the site and not searched for")))

    if "google_maps" in channels:
        findings.append(Finding(feature="google_maps", category=Category.LOCAL_SEO,
                                status=Status.PRESENT, evidence="map or directions link present"))
    if "whatsapp" in channels:
        findings.append(Finding(
            feature="whatsapp", category=Category.CONTACT, status=Status.PRESENT,
            evidence=f"wa.me/{channels['whatsapp'].handle}"))

    facts = {
        "read": True,
        "channels": {n: {"handle": c.handle, "url": c.url,
                         "confidence": c.confidence.value} for n, c in channels.items()},
        "official": [c.name for c in official],
        "linked_count": len(official),
    }
    return facts, findings
