"""How much of the discovered population Qevik can actually see.

A business Qevik cannot fetch produces no observations, so no findings, so no
opportunity, so no artefact and no outreach. It leaves the funnel without
appearing anywhere as a loss — the operator sees a shorter list, not a gap.

That happened at scale. A shared browser page meant one site's navigation
cancelled the previous one, and the failure was recorded as `reachable=false`
against the **previous** business: 43 of 352 audited businesses were marked as
having a dead website by a defect that was ours. Businesses whose latest audit
says unreachable carry a signal 6.6% of the time against 22.4% for the rest.

So coverage is a number worth watching, and the distinction that matters inside
it is **whose failure it was**:

- `answered` — the site replied and was audited. Evidence exists.
- `did_not_answer` — the site genuinely failed. A finding about them.
- `we_failed` — our own tooling did not complete the check. A finding about us,
  and the number that should fall to zero as the nightly rotation revisits them.
- `never_audited` — has a website and has not been looked at yet. Not a
  failure; a queue position.

Read-only, derived from the timeline. Nothing here re-audits: the nightly
verification already revisits these, and duplicating it to produce a number
would spend somebody else's bandwidth to make a report look complete.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

#: The marker a failed check leaves when the failure was ours. Written by
#: `infra/audit_discovered.py` from `browser.failures.reachability`.
OUR_FAILURE_FIELD = "check_failed_because"

#: Errors from before that field existed. Kept so history reads correctly
#: rather than counting every old failure against the businesses.
LEGACY_OUR_FAILURE = "interrupted by another navigation"


@dataclass(frozen=True)
class Coverage:
    """What Qevik can and cannot currently see."""

    with_a_website: int
    answered: int
    did_not_answer: int
    we_failed: int
    never_audited: int

    @property
    def audited(self) -> int:
        return self.answered + self.did_not_answer + self.we_failed

    @property
    def blocked_by_us(self) -> int:
        """The number that should reach zero on its own.

        Every one of these is a business Qevik could have evidence about and
        does not, for a reason that was never theirs.
        """
        return self.we_failed

    def summary(self) -> dict:
        return {
            "with_a_website": self.with_a_website,
            "audited": self.audited,
            "answered": self.answered,
            "did_not_answer": self.did_not_answer,
            "we_failed": self.we_failed,
            "never_audited": self.never_audited,
            "blocked_by_us": self.blocked_by_us,
            "note": ("A business Qevik cannot fetch produces no evidence and "
                     "leaves the funnel without appearing as a loss. "
                     "`we_failed` is ours to fix and should fall to zero as "
                     "the nightly verification revisits them; "
                     "`did_not_answer` is a finding about the site."),
        }


def _detail(raw: Any) -> dict:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return {}
    return raw or {}


def ours(detail: dict) -> bool:
    """Whether this failed audit was our tooling rather than their site."""
    if (detail.get(OUR_FAILURE_FIELD) or "").strip():
        return True
    # Before the field existed the only evidence is the error text. Matched
    # narrowly: one message, which only our own browser produces.
    return LEGACY_OUR_FAILURE in (detail.get("error") or "")


def measure(*, latest_audits: list, with_a_website: int) -> Coverage:
    """Coverage from one row per business — its **latest** audit.

    Latest, not every audit: a business audited badly on Monday and well on
    Tuesday is visible, and counting both would report it as a loss and a
    success at once.
    """
    answered = failed_theirs = failed_ours = 0
    for row in latest_audits:
        detail = _detail(row.get("detail") if isinstance(row, dict)
                         else getattr(row, "detail", None))
        reachable = detail.get("reachable")
        if reachable is None:
            # Two very different rows arrive as `None`. A recent one carries
            # our failure reason; an older format simply never wrote the field,
            # and those audits have observations and are fine.
            if ours(detail):
                failed_ours += 1
            elif detail.get("observations"):
                answered += 1
            else:
                failed_theirs += 1
            continue
        if reachable in (True, "true"):
            answered += 1
        elif ours(detail):
            failed_ours += 1
        else:
            failed_theirs += 1

    audited = answered + failed_theirs + failed_ours
    return Coverage(
        with_a_website=with_a_website,
        answered=answered,
        did_not_answer=failed_theirs,
        we_failed=failed_ours,
        # Never below zero: a deployment where more businesses were audited
        # than currently carry a website would otherwise report a negative
        # queue, which reads as a bug in the reader rather than in the data.
        never_audited=max(0, with_a_website - audited))


__all__ = ["LEGACY_OUR_FAILURE", "OUR_FAILURE_FIELD", "Coverage", "measure",
           "ours"]
