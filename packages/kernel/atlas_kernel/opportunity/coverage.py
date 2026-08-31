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

The rate is **measured, never assumed**. A configured forty-a-night is the same
kind of statement as a recurrence saying "nightly", and that statement was
already wrong once here for twelve days. A report that excused an eight-day-old
observation with a nine-night rotation nothing had run would rebuild exactly
the blind spot this module exists to remove.
"""

from __future__ import annotations

import json
import math
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

#: How many nights the rate is measured over. A single night is a sample of
#: one: a pass that missed last night and runs tonight has not stopped, and a
#: report that called that an outage would cry wolf the first time a run
#: slipped past midnight. A week is long enough to average a real cadence and
#: short enough that a pass which stopped a week ago is already visible.
MEASURED_OVER = A_WEEK


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

    But only a sweep that **actually runs** excuses anything, so the rate here
    is taken from the verification events on the timeline and not from the
    limit the runner is configured with. Those two have already disagreed once:
    a recurrence declared nightly wrote no observations for twelve days. Had
    this excused an eight-day-old record with a nine-night rotation nothing had
    performed, a stopped scheduler would read as a queue doing its job — the
    precise blind spot the number is here to remove. The configured limit is
    still reported beside the measured rate, because a pass managing half of
    what it was asked for is its own finding.

    What a rotation cannot excuse is a record older than **one full sweep**.
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
    #: How many of them one pass is *configured* to take. An intention. Never
    #: the basis of the sweep arithmetic when the timeline can be read instead.
    a_night_declared: int
    #: Whole days since each site's latest observation, one entry per site in
    #: the queue; ``None`` for one that has never been observed.
    observed_days_ago: tuple[int | None, ...]
    #: Sites the pass actually verified over the last `over_nights` nights —
    #: attempts, counted from the timeline, so a pass that ran three nights in
    #: seven reports the throughput it achieved rather than the one it declared.
    #: ``None`` when nothing measured it, which is the only case where the
    #: declared rate is used.
    verified_recently: int | None = None
    #: The window `verified_recently` was counted over.
    over_nights: int = MEASURED_OVER
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
    def a_night_observed(self) -> float | None:
        """Sites a night, as the timeline actually records them.

        Attempts over nights, not distinct sites over nights: on a population
        smaller than one week's capacity the distinct count saturates at the
        population and would report a healthy three-night rotation as a
        seven-night one, excusing staleness that nothing excuses.
        """
        if self.verified_recently is None or self.over_nights <= 0:
            return None
        return self.verified_recently / self.over_nights

    @property
    def a_night_effective(self) -> float:
        """The rate the sweep arithmetic runs at.

        Measured whenever anything measured it. The declared limit is the
        fallback for a caller with no timeline to read — a test constructing a
        case, not a production report — and never a substitute for one that
        came back zero.
        """
        observed = self.a_night_observed
        return float(self.a_night_declared) if observed is None else observed

    @property
    def the_pass_is_running(self) -> bool:
        """Whether anything was verified at all in the measured window.

        Reported in its own right, because a stopped pass is visible here on
        the first night and in the ages only once they drift past a sweep.
        """
        return self.a_night_effective > 0

    @property
    def a_sweep_completes(self) -> bool:
        """Whether the queue comes round at all: something to fetch, and a rate."""
        return self.sites > 0 and self.the_pass_is_running

    @property
    def a_night_expected(self) -> int:
        """The most a pass could manage: the configured limit, or the whole
        population when that is smaller.

        A market of twenty sites cannot verify forty a night, and counting that
        as falling behind would leave the flag below permanently raised on
        every small market — a warning that is always on is a warning nobody
        reads.
        """
        return (self.a_night_declared if self.sites <= 0
                else min(self.a_night_declared, self.sites))

    @property
    def the_pass_is_keeping_up(self) -> bool:
        """Whether the measured rate is the rate that was asked for.

        The half that checking for a *stopped* pass misses. One site a night
        over three hundred and fifty is a 350-night rotation, and a rotation
        that long is arithmetically capable of excusing any age at all — the
        same false reassurance the configured rate used to give, arrived at
        from the other direction. So a sweep only accounts for an age while the
        pass is running at the rate the sweep was promised at.

        Unmeasured is not a claim of falling behind, and reads true.
        """
        observed = self.a_night_observed
        return True if observed is None else observed >= self.a_night_expected

    @property
    def nights_for_a_full_sweep(self) -> int:
        """How long the measured cadence takes to come back round.

        At least one whenever there is anything to fetch, so "up to N days old
        is the queue" is never read as "up to zero". Zero means no sweep
        completes — nothing to fetch, or nothing fetching — and is never a
        sweep of length zero.
        """
        if not self.a_sweep_completes:
            return 0
        return max(1, math.ceil(self.sites / self.a_night_effective))

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

        When no sweep completes — nothing verified in the window — the queue is
        not coming round for anybody, and every stale reading is residue.
        Returning zero there is the trap: a scheduler that stopped a week ago
        leaves every observation eight days old, and an untested nine-night
        rotation would report all of it as the queue working.
        """
        if not self.a_sweep_completes:
            return self.older_than_a_week
        nights = self.nights_for_a_full_sweep
        return sum(1 for d in self.observed if d > nights)

    @property
    def explained_by_the_backlog(self) -> int:
        """Older than a week, and no older than one turn of the queue.

        Zero whenever no turn is being taken, because a rotation that is not
        running explains nothing.
        """
        return max(0, self.older_than_a_week - self.older_than_a_full_sweep)

    @property
    def the_cadence_explains_the_age(self) -> bool:
        """Whether every old record is one the queue has yet to reach.

        False the moment a single reading is older than a full sweep, because
        one that old is a different question from the cadence and reading it as
        the cadence is how it stays unanswered. False as well whenever nothing
        is sweeping and anything is stale: there is no cadence to do the
        explaining.
        """
        return self.older_than_a_full_sweep == 0

    def _rate_note(self) -> str:
        """Where the rate came from, said plainly. Half of every claim below."""
        if self.a_night_observed is None:
            return (f"no verification was measured, so this falls back to the "
                    f"{self.a_night_declared} a night the runner is configured "
                    f"for")
        return (f"{self.a_night_observed:.3g} a night measured from "
                f"{self.verified_recently} verification(s) over the last "
                f"{self.over_nights} night(s), against "
                f"{self.a_night_declared} a night configured")

    def _residue_note(self) -> str:
        """What is left over once the rotation has been allowed for."""
        return (f"of the population {self.reached_without_observation} were "
                f"reached by a pass that could record nothing, "
                f"{self.cannot_be_fetched} hold an address that cannot be "
                f"fetched and {self.shares_an_address} share an address with "
                f"another business, and none of those three age out.")

    def summary(self) -> dict:
        nights = self.nights_for_a_full_sweep
        if not self.a_sweep_completes:
            note = (
                f"No sweep is completing — {self._rate_note()}, over "
                f"{self.sites} site(s). Nothing is coming round, so the "
                f"rotation explains none of the {self.older_than_a_week} "
                f"observation(s) older than a week and all of them are counted "
                f"as unexplained; {self._residue_note()}")
        else:
            note = (
                f"{self._rate_note()}: over {self.sites} site(s) that is a "
                f"{nights}-night sweep, so an observation up to {nights} "
                f"day(s) old is the rotation and not a fault — "
                f"{self.explained_by_the_backlog} of the "
                f"{self.older_than_a_week} older than a week are that. "
                f"{self.older_than_a_full_sweep} are older than a full sweep, "
                f"which the cadence does not explain; {self._residue_note()}")
        return {
            "sites": self.sites,
            # Both rates, never one. The configured limit alone is what made
            # the claim unfalsifiable; the measured rate alone would hide a
            # pass quietly managing a quarter of what it was asked for.
            "a_night_declared": self.a_night_declared,
            "a_night_observed": (None if self.a_night_observed is None
                                 else round(self.a_night_observed, 2)),
            "verified_recently": self.verified_recently,
            "over_nights": self.over_nights,
            "the_pass_is_running": self.the_pass_is_running,
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
            "note": note,
        }


def backlog(*, sites: int, a_night_declared: int,
            observed_days_ago: list[int | None] | tuple[int | None, ...],
            verified_recently: int | None = None,
            over_nights: int = MEASURED_OVER,
            reached_without_observation: int = 0, cannot_be_fetched: int = 0,
            shares_an_address: int = 0) -> Backlog:
    """The cadence read as arithmetic, from counts the repository has.

    Pure, and separate from the query for the reason `measure` is: the
    interesting cases — a sweep longer than a week, a record older than one, a
    pass that stopped — are ones a test has to be able to construct without a
    population.
    """
    return Backlog(
        sites=max(0, int(sites)),
        a_night_declared=max(0, int(a_night_declared)),
        observed_days_ago=tuple(None if d is None else max(0, int(d))
                                for d in observed_days_ago),
        verified_recently=(None if verified_recently is None
                           else max(0, int(verified_recently))),
        over_nights=max(0, int(over_nights)),
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


__all__ = ["A_WEEK", "LEGACY_OUR_FAILURE", "MEASURED_OVER", "OUR_FAILURE_FIELD",
           "Backlog", "Coverage", "Reachability", "backlog", "measure", "ours",
           "reachable"]
