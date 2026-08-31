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

`Backlog` answers the question one step further on. Once the observations do
refresh, most of them being older than a week is the next thing anybody
notices — and on a population larger than one night's fetch that is the
rotation, not a fault. So the age is reported beside the rate that drains it,
and the part the rate does **not** explain is separated out, because that part
is the only half worth acting on.
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


#: The age the question arrives as: "most observation records are more than a
#: week old". A threshold worth naming because it is not the interesting one —
#: on a population bigger than one night's fetch, a week says nothing until it
#: is read beside how long a full sweep takes.
A_WEEK = 7


@dataclass(frozen=True)
class Backlog:
    """Why an observation is as old as it is: the queue, or something else.

    The nightly pass fetches a bounded number of sites, least recently verified
    first. On a population larger than that bound, *most* observations being
    older than a week is arithmetic rather than a fault: forty a night over
    three hundred and fifty sites is a nine-night sweep, so an eight-day-old
    reading is the rotation working exactly as declared. Reported as staleness
    with nothing beside it, that number invites somebody to fix a cadence that
    is not broken.

    What the rotation cannot excuse is a record older than **one full sweep**.
    The queue has been all the way round by then, so something else is true:
    the pass reached the site and could record nothing, or the site never
    enters the queue at all. Those are counted separately and never added to
    the first — the same distinction `reevaluation` draws between a fact about
    their site and a fact about our own checking, and summing them would hide
    the only half anybody can act on.
    """

    #: What one sweep must cover: distinct fetchable addresses, counted the way
    #: the queue itself counts them rather than by counting businesses. Two
    #: businesses sharing a website are one fetch.
    sites: int
    #: How many of them one pass takes.
    a_night: int
    #: Whole days since each site's latest observation, one entry per site in
    #: the queue; ``None`` for one that has never been observed.
    observed_days_ago: tuple[int | None, ...]
    #: Sites a pass reached since their last observation and wrote nothing for
    #: — a truncated body, an error page, a refusal, a document that was not
    #: HTML. Another turn of the queue does not clear these.
    reached_without_observation: int = 0
    #: Businesses holding an address no fetcher may be handed: `mailto:`, or no
    #: scheme at all. Not observable at any cadence.
    cannot_be_fetched: int = 0
    #: Businesses whose website another business already holds. The queue
    #: de-duplicates by address, so only one of them is ever fetched and the
    #: rest carry whatever observations they were given elsewhere.
    shares_an_address: int = 0

    @property
    def nights_for_a_full_sweep(self) -> int:
        """How long the declared cadence takes to come back round.

        At least one whenever there is anything to fetch, so "up to N days old
        is the queue" is never read as "up to zero".
        """
        if self.sites <= 0 or self.a_night <= 0:
            return 0
        return max(1, -(-self.sites // self.a_night))

    @property
    def observed(self) -> tuple[int, ...]:
        return tuple(d for d in self.observed_days_ago if d is not None)

    @property
    def never_observed(self) -> int:
        return sum(1 for d in self.observed_days_ago if d is None)

    @property
    def older_than_a_week(self) -> int:
        return sum(1 for d in self.observed if d > A_WEEK)

    @property
    def older_than_a_full_sweep(self) -> int:
        """The residue the cadence does not explain.

        Nothing here can be answered with "it has not come round yet": by
        definition it has.
        """
        nights = self.nights_for_a_full_sweep
        return sum(1 for d in self.observed if d > nights) if nights else 0

    @property
    def explained_by_the_backlog(self) -> int:
        """Older than a week, and no older than one turn of the queue."""
        return max(0, self.older_than_a_week - self.older_than_a_full_sweep)

    @property
    def the_cadence_explains_the_age(self) -> bool:
        """Whether every old record is one the queue has yet to reach.

        False the moment a single reading is older than a full sweep, because
        one that old is a different question from the cadence and reading it as
        the cadence is how it stays unanswered.
        """
        return self.older_than_a_full_sweep == 0

    def summary(self) -> dict:
        nights = self.nights_for_a_full_sweep
        return {
            "sites": self.sites,
            "a_night": self.a_night,
            "nights_for_a_full_sweep": nights,
            "observed": len(self.observed),
            "never_observed": self.never_observed,
            "older_than_a_week": self.older_than_a_week,
            "explained_by_the_backlog": self.explained_by_the_backlog,
            "older_than_a_full_sweep": self.older_than_a_full_sweep,
            "the_cadence_explains_the_age": self.the_cadence_explains_the_age,
            "reached_without_observation": self.reached_without_observation,
            "cannot_be_fetched": self.cannot_be_fetched,
            "shares_an_address": self.shares_an_address,
            "note": (
                f"{self.a_night} a night over {self.sites} site(s) is a "
                f"{nights}-night sweep, so an observation up to {nights} day(s) "
                f"old is the rotation and not a fault — "
                f"{self.explained_by_the_backlog} of the "
                f"{self.older_than_a_week} older than a week are that. "
                f"{self.older_than_a_full_sweep} are older than a full sweep, "
                f"which the cadence does not explain; of the population "
                f"{self.reached_without_observation} were reached by a pass "
                f"that could record nothing, "
                f"{self.cannot_be_fetched} hold an address that cannot be "
                f"fetched and {self.shares_an_address} share an address with "
                f"another business, and none of those three age out."),
        }


def backlog(*, sites: int, a_night: int,
            observed_days_ago: list[int | None] | tuple[int | None, ...],
            reached_without_observation: int = 0, cannot_be_fetched: int = 0,
            shares_an_address: int = 0) -> Backlog:
    """The cadence read as arithmetic, from counts the repository has.

    Pure, and separate from the query for the reason `measure` is: the
    interesting cases — a sweep longer than a week, a record older than one —
    are ones a test has to be able to construct without a population.
    """
    return Backlog(
        sites=max(0, int(sites)), a_night=max(0, int(a_night)),
        observed_days_ago=tuple(None if d is None else max(0, int(d))
                                for d in observed_days_ago),
        reached_without_observation=max(0, int(reached_without_observation)),
        cannot_be_fetched=max(0, int(cannot_be_fetched)),
        shares_an_address=max(0, int(shares_an_address)))


@dataclass(frozen=True)
class Reachability:
    """Who Qevik could actually write to, by channel.

    Measured because the answer was surprising and it changes what is worth
    doing: on 2026-08-31, **412 businesses and not one email address**. No
    source Qevik has ever collects one — OpenStreetMap's extractor does not
    read it, the Places field mask has no email field because the API does not
    return one, and nothing reads contacts out of the audited homepages.

    So configuring DNS and SMTP would enable email to nobody. That is worth
    knowing before spending an afternoon on it, and it is not visible from any
    other number in the system: the outreach pipeline reports messages blocked
    on `NO_SENDING_IDENTITY`, which reads as "the sender is missing" rather
    than "there is no recipient either".
    """

    businesses: int
    by_email: int
    by_phone: int
    by_neither: int

    @property
    def email_is_addressable(self) -> bool:
        """Whether an SMTP identity would have anywhere to send."""
        return self.by_email > 0

    def summary(self) -> dict:
        return {
            "businesses": self.businesses,
            "by_email": self.by_email,
            "by_phone": self.by_phone,
            "by_neither": self.by_neither,
            "email_is_addressable": self.email_is_addressable,
            "note": ("A channel with no recipients cannot be unblocked by "
                     "configuring the sender. Email and WhatsApp are counted "
                     "separately because only one of them is automated."),
        }


def reachable(*, businesses: int, with_email: int, with_phone: int,
              with_neither: int) -> Reachability:
    """Who could be written to, from counts the repository has."""
    return Reachability(businesses=businesses, by_email=with_email,
                        by_phone=with_phone, by_neither=with_neither)


__all__ = ["A_WEEK", "LEGACY_OUR_FAILURE", "OUR_FAILURE_FIELD", "Backlog",
           "Coverage", "Reachability", "backlog", "measure", "ours",
           "reachable"]
