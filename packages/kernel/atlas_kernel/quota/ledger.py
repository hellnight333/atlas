"""The ledger: reserve before acting, and plan the day from what is left.

Two behaviours matter more than the bookkeeping.

**Refuse rather than fail.** A connector asks before it acts. Discovering a
limit from a platform's 403 means the work is already half-done, the artifact is
half-uploaded and nobody can say whether it counted. Asking first turns an
outage into a decision.

**Never silently do nothing.** The operator's instruction was to set a floor and
a ceiling and keep producing rather than stopping — so `plan()` returns what is
achievable *and why it is not more*. A production loop that quietly returns zero
looks identical to one that is broken, and the difference between "the quota is
gone" and "the code is wrong" is a day of debugging nobody needed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict

from ..opportunity.models import BusinessEvent
from .models import (
    LimitKind,
    QuotaExhausted,
    QuotaPolicy,
    QuotaSpend,
    QuotaStatus,
    QuotaWindow,
    window_end,
    window_start,
)

log = logging.getLogger(__name__)

FACTORY = "quota"
#: An allowance was set or changed.
POLICY_SET = "quota_policy_set"
#: Units were consumed. Replaying these is what makes a rolling window survive a
#: restart, which a running counter never could.
SPENT = "quota_spent"


def _kind_of(event: object) -> str:
    return getattr(event, "kind", None) or (
        event.get("kind", "") if isinstance(event, dict) else "")


def _detail_of(event: object) -> dict:
    detail = getattr(event, "detail", None)
    if detail is None and isinstance(event, dict):
        detail = event.get("detail")
    return detail or {}


class Plan(BaseModel):
    """How much of the day's ambition the quota actually permits."""

    model_config = ConfigDict(frozen=True)

    resource: str
    #: What to attempt. Never negative, never above the ceiling asked for.
    count: int
    #: The ceiling the caller asked for.
    requested: int
    #: How many short of the caller's floor, if any. Zero when the floor is met.
    shortfall: int = 0
    #: Plain English, for a daily report that a person reads.
    reason: str = ""

    @property
    def met_the_floor(self) -> bool:
        return self.shortfall == 0

    def __str__(self) -> str:
        return f"{self.resource}: {self.count} of {self.requested} — {self.reason}"


class QuotaLedger:
    """Tracks allowances across windows and answers what may still be done.

    Held in memory. The window logic is deliberately computed from timestamped
    entries rather than from a counter, so persisting this later is a matter of
    storing `QuotaSpend` rows and replaying them — no redesign, and rolling
    windows keep working across a restart, which a counter could never do.
    """

    def __init__(self, policies: list[QuotaPolicy] | None = None, *, now=None,
                 events: list | None = None,
                 sink: Callable[[Any], None] | None = None) -> None:
        """The allowances, and the timeline they are rebuilt from.

        **Persistence belongs here, not above.** The class docstring already
        said storing `QuotaSpend` rows and replaying them was all it would take;
        putting it anywhere else means every caller that draws on this ledger —
        `credits`, `fabric.budgets`, whatever comes next — needs its own answer,
        and the second one to be written is the one that disagrees.

        Without `events` this is in-memory, which is right for a test and was
        quietly wrong for the deployment: a restart forgot every plan and every
        unit spent, so the month's usage reset whenever the service redeployed.
        """
        self._policies: dict[str, QuotaPolicy] = {}
        self._spends: list[QuotaSpend] = []
        #: Injected so windows and rollovers are testable without waiting a day.
        self._now = now or (lambda: datetime.now(UTC))
        self._sink = sink
        if events is not None:
            self._replay(events)
        for policy in policies or []:
            self.register(policy)

    # -- durability -------------------------------------------------------

    def _replay(self, events: list) -> None:
        """Rebuild policies and spends from the timeline.

        Policies before spends, because a spend against an unregistered
        resource has nowhere to go. Both are appended in the order they
        happened, so replaying them in one pass over a chronological log is
        enough — but the policy pass runs first regardless, since a log may be
        read out of order and a lost policy silently discards the usage that
        went with it.
        """
        found = 0
        for event in events:
            if _kind_of(event) != POLICY_SET:
                continue
            detail = _detail_of(event)
            try:
                self._policies[detail["resource"]] = QuotaPolicy.model_validate(
                    detail["policy"])
                found += 1
            except (KeyError, ValueError):
                log.warning("quota: a policy event could not be read; skipped")
        for event in events:
            if _kind_of(event) != SPENT:
                continue
            detail = _detail_of(event)
            try:
                self._spends.append(QuotaSpend.model_validate(detail["spend"]))
            except (KeyError, ValueError):
                log.warning("quota: a spend event could not be read; skipped")
        if found or self._spends:
            log.info("quota: restored %d polic(ies) and %d spend(s)",
                     found, len(self._spends))

    def _remember(self, kind: str, detail: dict) -> None:
        if self._sink is None:
            return
        self._sink(BusinessEvent(business_id="", factory=FACTORY, kind=kind,
                                 actor="quota", detail=detail))

    def register(self, policy: QuotaPolicy) -> None:
        known = self._policies.get(policy.resource)
        self._policies[policy.resource] = policy
        # Only when it actually changes. Re-registering an identical policy on
        # every boot would grow the timeline without recording anything.
        if known != policy:
            self._remember(POLICY_SET, {"resource": policy.resource,
                                        "policy": policy.model_dump(mode="json"),
                                        "at": self._now().isoformat()})

    def policy(self, resource: str) -> QuotaPolicy:
        try:
            return self._policies[resource]
        except KeyError:
            raise KeyError(
                f"no quota policy for {resource!r}. Register one before spending against "
                "it — an unmetered resource is how a limit gets discovered from a 403."
            ) from None

    def _in_window(self, policy: QuotaPolicy, now: datetime) -> list[QuotaSpend]:
        entries = [s for s in self._spends if s.resource == policy.resource]
        if policy.window is QuotaWindow.ROLLING_24H:
            cutoff = now - timedelta(hours=24)
            return [s for s in entries if s.at > cutoff]
        start = window_start(policy.window, now)
        return [s for s in entries if start is None or s.at >= start]

    def status(self, resource: str) -> QuotaStatus:
        policy = self.policy(resource)
        now = self._now()
        used = sum(s.amount for s in self._in_window(policy, now))
        # Ordinary work never sees the floor; essential work does.
        ordinary = max(0.0, policy.limit - policy.floor - used)
        essential = max(0.0, policy.limit - used)
        return QuotaStatus(
            resource=resource,
            kind=policy.kind,
            limit=policy.limit,
            used=used,
            remaining=ordinary,
            remaining_essential=essential,
            window=policy.window,
            resets_at=window_end(policy.window, now),
        )

    def remaining(self, resource: str, *, essential: bool = False) -> float:
        status = self.status(resource)
        return status.remaining_essential if essential else status.remaining

    def spend(
        self,
        resource: str,
        amount: float,
        *,
        essential: bool = False,
        note: str = "",
    ) -> QuotaStatus:
        """Consume the allowance, or refuse.

        Raises before recording anything. A partially applied spend is worse
        than a refusal because it is invisible.
        """
        if amount < 0:
            raise ValueError("a spend cannot be negative")
        policy = self.policy(resource)
        available = self.remaining(resource, essential=essential)
        if amount > available:
            raise QuotaExhausted(resource, policy.kind, available, amount)
        entry = QuotaSpend(resource=resource, amount=amount, at=self._now(),
                           essential=essential, note=note)
        self._spends.append(entry)
        # Appended after the refusal above, never before: a spend recorded and
        # then rejected would leave the timeline claiming units that were never
        # consumed, and the next replay would believe it.
        self._remember(SPENT, {"resource": resource, "amount": amount,
                               "spend": entry.model_dump(mode="json"),
                               "at": entry.at.isoformat()})
        return self.status(resource)

    def affords(self, resource: str, amount: float, *, essential: bool = False) -> bool:
        """Whether a single unit of work fits. Never raises."""
        try:
            return self.remaining(resource, essential=essential) >= amount
        except KeyError:
            return False

    def plan(
        self,
        resource: str,
        *,
        unit_cost: float,
        maximum: int,
        minimum: int = 0,
        essential: bool = False,
    ) -> Plan:
        """How many items to attempt, given what the quota allows.

        This is the operator's rule made concrete: a limit reduces the day's
        output, it does not cancel it. If twelve are wanted and six fit, six get
        made — and the plan says so, rather than returning a number that could
        equally mean "the code is broken".
        """
        if unit_cost <= 0:
            raise ValueError("unit_cost must be positive — an item that costs nothing to do")
        if maximum < 0 or minimum < 0:
            raise ValueError("maximum and minimum must not be negative")
        if minimum > maximum:
            raise ValueError(f"minimum {minimum} is above maximum {maximum}")

        status = self.status(resource)
        available = status.remaining_essential if essential else status.remaining
        affordable = int(available // unit_cost)
        count = min(affordable, maximum)

        if count >= maximum:
            reason = f"quota permits {affordable}, which covers the target"
        elif count > 0:
            reason = (
                f"quota permits {count} of {maximum} — {available:g} of "
                f"{status.limit:g} {'units' if status.kind is LimitKind.PLATFORM else 'USD'} left"
            )
        else:
            reason = (
                f"nothing affordable: {available:g} left and each item costs {unit_cost:g}. "
                + (
                    "Raise the ceiling if the work is worth it"
                    if status.kind is LimitKind.SPEND
                    else f"Resets at {status.resets_at:%Y-%m-%d %H:%M UTC}"
                    if status.resets_at
                    else "This is a rolling window; capacity returns gradually"
                )
            )

        return Plan(
            resource=resource,
            count=count,
            requested=maximum,
            shortfall=max(0, minimum - count),
            reason=reason,
        )

    def report(self) -> list[QuotaStatus]:
        """Every allowance, worst first — the shape a daily report needs."""
        statuses = [self.status(resource) for resource in self._policies]
        return sorted(statuses, key=lambda s: (s.remaining / s.limit) if s.limit else 0)
