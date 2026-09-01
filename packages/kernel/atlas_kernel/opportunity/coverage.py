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

`Backlog` answers the question freshness raises and cannot settle on its own:
whether an old observation is a queue position, a pass that stopped, or a
record the rotation is never going to reach at all.
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


#: How many nights may pass before "nightly" stops describing what happened.
#: One missed night is a missed night; two is a pass that stopped, and the
#: difference is the whole distinction between a backlog draining and a
#: schedule nobody noticed had gone quiet.
A_STOPPED_PASS = 2.0

#: What `audit_freshness` counts as within a week: **eight** days, not seven.
#: A pass that runs at 05:00 reads a site at 05:00, and seven days later that
#: reading is seven days and a minute old — stale by an hour of arithmetic and
#: by nothing else. So the rotation gets eight nights to come back round, and
#: the backlog arithmetic has to use the same eight or the two numbers beside
#: each other on one screen disagree about what a week is.
A_WEEK_IN_NIGHTS = 8


@dataclass(frozen=True)
class Backlog:
    """Why an observation is old: a queue position, or a pass that stopped.

    "Most businesses carry observations older than a week" is either alarming
    or exactly what the schedule produces, and the freshness surface could not
    say which. The nightly rotation takes `per_night` sites, least recently
    verified first, so a population of `sites` is swept in
    `nights_for_a_full_sweep` nights. When that is longer than the week
    freshness measures against, the majority **must** be older than a week: the
    cadence is the cause, and the answer is to make it visible rather than to
    change it. 359 sites at 40 a night is nine nights, and nine is more than a
    week — nothing is wrong, and nothing said so.

    What this must never print over is the opposite failure, which this
    repository has already shipped once: the pass reaching sites without
    observing them, so `website_verified` refreshed every night for twelve days
    while `website_audited` stood still. `the_pass_is_running` is therefore
    measured from the observation the pass *produces*, never from the turn it
    took — a fresh turn with no observation beside it makes this false, and
    says so under its own name.
    """

    #: Distinct websites in the rotation. Distinct, because the rotation
    #: de-duplicates by address: two businesses sharing a website are one fetch
    #: and therefore one night's work, not two. And only addresses it can
    #: actually fetch — a `mailto:` value it will never visit is not a night's
    #: work either, and counting it would report a sweep slower than the one
    #: that runs.
    sites: int
    #: Read from `audit_freshness`, never recomputed. Two queries with the same
    #: intent is how two numbers on one screen come to disagree.
    older_than_a_week: int
    #: How many sites one night of the pass takes. The rotation's own bound.
    per_night: int
    #: Nights since the last `website_audited` **the scheduled pass itself
    #: wrote**. `None` when there has never been one — which is not an old pass,
    #: it is no pass. Whose reading it was matters as much as when: three other
    #: things append that kind, one of them a correction that reads nothing, and
    #: any of them would otherwise certify a stalled pass as alive.
    nights_since_an_observation: float | None = None
    #: Nights since the pass's last `website_verified`: a site having had its
    #: turn, whether or not anything was read from it.
    nights_since_a_turn: float | None = None
    #: Stale sites the rotation has **already come back round to** and still
    #: could not re-observe. The measured answer to "does the refresh path
    #: reach them", as opposed to the ordering's promise that it will.
    #:
    #: The turn has to be the scheduled pass's own. A hand-run probe marks a
    #: site as having had its turn too, and reading that as the rotation would
    #: move a site out of the queue it is still in and into the count that says
    #: waiting will not help — an operator acting on a sweep that has not been
    #: past yet.
    #:
    #: Named for what was not read rather than for what stayed stale, because
    #: the console renders this field and refuses any name beginning
    #: `stale_after`: that is the shape of a worker-health threshold
    #: (`stale_after_seconds`), and a surface that computes staleness from one
    #: is the failure that guard exists to stop. This computes nothing — it is
    #: a count the timeline already settled — but a guard worth having is worth
    #: not arguing with over a name.
    unread_after_a_turn: int = 0
    #: Stale records the rotation will never **select**, so it can never even
    #: fail to read them. The other half of the same question, and the half the
    #: ordering hides completely: the count above is at least evidence of a
    #: turn, and these have no turn to be evidence of.
    #:
    #: Two things put a business here. One night's work is one *address*, so the
    #: rotation de-duplicates by website and only the earliest business recorded
    #: against an address is ever fetched — a second business on the same
    #: website is never visited again after whatever first observed it. And an
    #: address the fetcher is never handed — no scheme, `mailto:`, or removed
    #: since the reading was taken — is not in the rotation at all.
    #:
    #: Both keep an observation for ever, both count in `older_than_a_week`, and
    #: without this they read as queue positions in a sweep that will never
    #: reach them. That is the one sentence this surface exists to stop being
    #: said: wait, and it will come good.
    never_in_the_rotation: int = 0
    last_observation: str = ""
    last_turn: str = ""

    @property
    def nights_for_a_full_sweep(self) -> int:
        """How long the rotation takes to come back round to any one site."""
        if self.sites <= 0 or self.per_night <= 0:
            return 0
        return -(-self.sites // self.per_night)

    @property
    def the_pass_is_running(self) -> bool:
        """Whether observations are still being written. Measured, not declared.

        A recurrence saying "nightly" is a declaration; this is the timeline.
        And it reads the *observation*, because the record that refreshed
        nightly while nothing was being read was the other one — and only the
        pass's own observations, because a hand-run correction stamped now would
        otherwise answer this question on the pass's behalf.
        """
        since = self.nights_since_an_observation
        return since is not None and since <= A_STOPPED_PASS

    @property
    def the_pass_ran_without_observing(self) -> bool:
        """The twelve-day failure, as one boolean.

        Sites took their turn last night and none of them was read. Every
        number on the freshness surface would look alive; the evidence behind
        the commercial decisions would be a fortnight old.
        """
        turn = self.nights_since_a_turn
        return (turn is not None and turn <= A_STOPPED_PASS
                and not self.the_pass_is_running)

    @property
    def beyond_the_rotations_reach(self) -> int:
        """Stale records the sweep cannot clear, however it fails to reach them.

        The two counts are disjoint by construction — one is a business the
        rotation selected and could not read, the other is a business it will
        never select — so they add rather than overlap, and the sum is the
        number an operator actually needs: how much of the age is not a queue.
        """
        return self.unread_after_a_turn + self.never_in_the_rotation

    @property
    def waiting_will_not_clear_these(self) -> bool:
        """Whether some of the age is beyond the rotation's power to fix.

        The ordering promises every site a turn; it cannot promise a reading,
        and it never promised anything at all to a site it does not hold.

        A site whose server refused, timed out, returned something that is not
        HTML, or was cut off mid-body takes its turn and is deliberately not
        re-observed — auditing what came back would put an invented absence in
        front of a business. A business whose address another business already
        holds, or whose address the fetcher is never handed, is not visited even
        that far. Both cycle for ever, and telling an operator to wait for the
        sweep would be a promise nothing will keep.

        Kept out of `the_cadence_explains_the_age` on purpose: this is a
        finding about reach, which `Coverage` already counts and names as ours
        or theirs. Two numbers about the same sites saying it twice would make
        the more urgent one harder to see.
        """
        return self.beyond_the_rotations_reach > 0

    @property
    def the_cadence_explains_the_age(self) -> bool:
        """Whether the schedule accounts for the age, or something is wrong.

        False in the two cases worth waking somebody for: the pass has stopped,
        so the age is a stall; or the rotation sweeps everything inside a week
        and sites are stale anyway, so the pass is running and not reaching
        them — which is precisely what the alphabetical-forty bug did while
        succeeding nightly.
        """
        if not self.older_than_a_week:
            return True
        return (self.the_pass_is_running
                and self.nights_for_a_full_sweep > A_WEEK_IN_NIGHTS)

    def summary(self) -> dict:
        return {
            "sites": self.sites,
            "older_than_a_week": self.older_than_a_week,
            "per_night": self.per_night,
            "nights_for_a_full_sweep": self.nights_for_a_full_sweep,
            "the_pass_is_running": self.the_pass_is_running,
            "the_pass_ran_without_observing": self.the_pass_ran_without_observing,
            "the_cadence_explains_the_age": self.the_cadence_explains_the_age,
            "unread_after_a_turn": self.unread_after_a_turn,
            "never_in_the_rotation": self.never_in_the_rotation,
            "beyond_the_rotations_reach": self.beyond_the_rotations_reach,
            "waiting_will_not_clear_these": self.waiting_will_not_clear_these,
            "nights_since_an_observation": self.nights_since_an_observation,
            "nights_since_a_turn": self.nights_since_a_turn,
            "last_observation": self.last_observation,
            "last_turn": self.last_turn,
            "note": (f"The pass takes {self.per_night} sites a night, least "
                     f"recently verified first, so {self.sites} sites are swept "
                     f"in {self.nights_for_a_full_sweep} nights. "
                     + ("Observations older than a week are that queue, not a "
                        "stall, and the cadence is reported rather than changed."
                        if self.the_cadence_explains_the_age else
                        "That does not account for the age on the timeline: "
                        "either the pass has stopped or it is not reaching "
                        "these sites.")
                     + (f" {self.beyond_the_rotations_reach} of them are "
                        "beyond the rotation's reach, so waiting for the sweep "
                        "will not clear those — their reach is the finding, "
                        f"not the cadence: {self.unread_after_a_turn} have "
                        "already had a turn since their last reading and were "
                        f"not re-observed, and {self.never_in_the_rotation} "
                        "are not in the rotation at all, because the address "
                        "is one it cannot fetch or one another business "
                        "already holds."
                        if self.waiting_will_not_clear_these else "")),
        }


def backlog(*, sites: int, older_than_a_week: int, per_night: int,
            nights_since_an_observation: float | None = None,
            nights_since_a_turn: float | None = None,
            unread_after_a_turn: int = 0, never_in_the_rotation: int = 0,
            last_observation: str = "", last_turn: str = "") -> Backlog:
    """The backlog, from counts and two timestamps the repository has."""
    # Never more than the population they are subsets of, and never more than
    # it between them: a part larger than its whole is a reader people stop
    # trusting, and the two are read from one query and clamped as one number
    # because they are shown added together.
    stale = max(0, older_than_a_week)
    unread = min(max(0, unread_after_a_turn), stale)
    return Backlog(
        sites=max(0, sites), older_than_a_week=stale,
        per_night=per_night,
        nights_since_an_observation=nights_since_an_observation,
        nights_since_a_turn=nights_since_a_turn,
        unread_after_a_turn=unread,
        never_in_the_rotation=min(max(0, never_in_the_rotation),
                                  stale - unread),
        last_observation=last_observation, last_turn=last_turn)


__all__ = ["A_STOPPED_PASS", "A_WEEK_IN_NIGHTS", "LEGACY_OUR_FAILURE",
           "OUR_FAILURE_FIELD", "Backlog", "Coverage", "Reachability",
           "backlog", "measure", "ours", "reachable"]
