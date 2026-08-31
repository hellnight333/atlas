"""Whose fault was it that the page did not load?

An audit that cannot fetch a site records something about that business, and
the something has to be true. Two very different facts arrive as the same
exception:

- **The site did not answer.** DNS says no such host, the connection was
  refused, the certificate is invalid. That is a fact about them, and a real
  finding.
- **Our fetch did not complete.** The browser was reused across sites and one
  navigation interrupted another; the process ran out of memory; the session
  died. That is a fact about us, and recording it as `reachable=False` puts a
  false statement about a real business into the ledger.

Seven of sixty audited businesses were marked unreachable by the second kind,
including two large retailers whose sites plainly work. Each was then silently
dropped from the funnel: no observations, no findings, no opportunity, no
health check — for a defect that was ours.

The classification is **deliberately conservative**. Only patterns that can only
be ours are called ours; everything else stays a finding about the site. Being
wrong in this direction costs an audit; being wrong in the other direction
tells a business their website is down when it is not.
"""

from __future__ import annotations

import re

#: Failures that can only be ours. Each is a message Playwright produces about
#: the state of *our* browser, never about the far end.
OURS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"interrupted by another navigation", re.I),
     "our browser navigated elsewhere before this page finished loading"),
    (re.compile(r"Target (page|closed|crashed)|has been closed", re.I),
     "our browser page closed before the check completed"),
    (re.compile(r"Browser(Type)?\.(launch|connect)|browser has been closed", re.I),
     "our browser was not running"),
    (re.compile(r"Execution context was destroyed", re.I),
     "our browser discarded the page mid-check"),
    (re.compile(r"Protocol error", re.I),
     "our browser driver failed"),
    (re.compile(r"out of memory|Cannot allocate memory", re.I),
     "the machine running the check ran out of memory"),
)


def ours(error: str) -> str:
    """Why this failure was ours, or `""` when it was not.

    `""` is not "it was theirs" in a strong sense — it is "nothing here
    identifies this as ours", which for a conservative classifier is the same
    decision and a different claim.
    """
    text = error or ""
    for pattern, because in OURS:
        if pattern.search(text):
            return because
    return ""


def reachability(error: str) -> tuple[bool | None, str]:
    """`(reachable, because)` for a failed fetch.

    `None` means not established. It is not `False`: a site we could not check
    is not a site that is down, and only one of those is a finding about the
    business.
    """
    because = ours(error)
    if because:
        return None, because
    return False, "the site did not answer"


__all__ = ["OURS", "ours", "reachability"]
