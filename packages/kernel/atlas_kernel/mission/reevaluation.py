"""Re-running the engine over a business already researched, without losing what
it knew before.

§18 and §13 of the master directive. The temptation is to re-research and
overwrite: the new engine knows more, so the new answer must be better. That
reasoning destroys the one thing a second look is for — the *difference*. A
finding that disappeared is a fact about the business; a finding that was
confirmed and is now unverified is a fact about our checking; and only the
comparison distinguishes them.

So nothing is overwritten. Historical observations stay on the timeline, the new
ones are appended, and this computes the delta between them across six kinds:

============================  ============================================
UNCHANGED                     Same status, both times.
NEWLY_OBSERVED                Not checked before, confirmed now.
DISAPPEARED                   Confirmed before, absent now.
CONTRADICTED                  Confirmed present before, confirmed absent now
                              (or the reverse) — a real change on their site.
NOW_CONFIRMED                 Unverified before, confirmed now. Our blind
                              spot closed; their business did not change.
NOW_UNVERIFIED                Confirmed before, unverified now. **Our** loss
                              of visibility, never reported as their decline.
============================  ============================================

The last two are the pair that a naive diff gets wrong, and getting them wrong
is how a re-evaluation tells a customer their site got worse when in fact the
crawler timed out.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from ..opportunity.models import BusinessEvent
from ..opportunity.tenancy import TenantId, owns
from ..opportunity.tenancy import require as _require_tenant

FACTORY = "reevaluation"
COMPARED = "business_reevaluated"

#: The three statuses research emits. Anything else is treated as unverified,
#: because an unrecognised status is a thing we do not understand rather than a
#: finding we can rely on.
PRESENT, ABSENT, UNVERIFIED = "present", "not_found", "unverified"


class Change(StrEnum):
    UNCHANGED = "unchanged"
    NEWLY_OBSERVED = "newly_observed"
    DISAPPEARED = "disappeared"
    CONTRADICTED = "contradicted"
    NOW_CONFIRMED = "now_confirmed"
    NOW_UNVERIFIED = "now_unverified"


#: Changes that say something about the *business*. The rest say something
#: about our checking, and a customer-facing summary must not mix them.
ABOUT_THE_BUSINESS: frozenset[Change] = frozenset({
    Change.NEWLY_OBSERVED, Change.DISAPPEARED, Change.CONTRADICTED})

#: Changes that say something about our own coverage.
ABOUT_OUR_CHECKING: frozenset[Change] = frozenset({
    Change.NOW_CONFIRMED, Change.NOW_UNVERIFIED})


class FeatureChange(BaseModel):
    """One feature, then and now, and what kind of change that is."""

    model_config = ConfigDict(frozen=True)

    feature: str
    was: str = ""
    now: str = ""
    change: Change

    @property
    def about_the_business(self) -> bool:
        return self.change in ABOUT_THE_BUSINESS


def _normalise(status: str | None) -> str:
    """Anything unrecognised is unverified, not a finding."""
    return status if status in (PRESENT, ABSENT, UNVERIFIED) else UNVERIFIED


def _by_feature(observations: list[dict]) -> dict[str, str]:
    """Feature -> status. Observations with no feature name are not findings."""
    return {str(o["feature"]): str(o.get("status") or "")
            for o in observations if o.get("feature")}


def classify(was: str | None, now: str | None) -> Change:
    """What kind of change this is. The whole delicacy of §13 lives here."""
    before, after = _normalise(was), _normalise(now)

    if before == after:
        return Change.UNCHANGED
    if before == UNVERIFIED:
        # We had not looked. Now we have — that is our coverage improving, not
        # the business changing, even when the new reading is bad news.
        return Change.NOW_CONFIRMED
    if after == UNVERIFIED:
        # We used to know and now we do not. Never reported as a decline: the
        # crawler timing out is not the customer's site getting worse.
        return Change.NOW_UNVERIFIED
    # Both confirmed, and they disagree. A genuine change on their site.
    return Change.CONTRADICTED


class Comparison(BaseModel):
    """What the second look found, beside what the first one knew."""

    model_config = ConfigDict(frozen=True)

    business_id: str
    tenant_id: str
    changes: tuple[FeatureChange, ...] = ()
    #: Features present in the new reading that the old one never mentioned.
    first_seen: tuple[str, ...] = ()
    #: Features the old reading had that the new one does not mention at all.
    no_longer_checked: tuple[str, ...] = ()

    def of_kind(self, change: Change) -> tuple[FeatureChange, ...]:
        return tuple(c for c in self.changes if c.change is change)

    @property
    def business_changes(self) -> tuple[FeatureChange, ...]:
        return tuple(c for c in self.changes if c.about_the_business)

    @property
    def coverage_changes(self) -> tuple[FeatureChange, ...]:
        return tuple(c for c in self.changes
                     if c.change in ABOUT_OUR_CHECKING)

    @property
    def anything_changed(self) -> bool:
        return any(c.change is not Change.UNCHANGED for c in self.changes)

    def statement(self) -> str:
        """What the comparison shows, separating their site from our checking.

        Written so a customer reading it cannot mistake a gap in our coverage
        for a decline in their business — the two clauses are never merged.
        """
        theirs = len(self.business_changes)
        ours = len(self.coverage_changes)
        if not theirs and not ours:
            return "Nothing changed since the previous check."
        parts = []
        if theirs:
            parts.append(f"{theirs} change(s) on the site itself")
        if ours:
            parts.append(f"{ours} change(s) in what we were able to check, "
                         "which is about our coverage rather than the business")
        return "; ".join(parts) + "."

    def summary(self) -> dict:
        return {
            "business_id": self.business_id, "tenant_id": self.tenant_id,
            "changes": [c.model_dump(mode="json") for c in self.changes],
            "first_seen": list(self.first_seen),
            "no_longer_checked": list(self.no_longer_checked),
            "counts": {
                "total": len(self.changes),
                "unchanged": len(self.of_kind(Change.UNCHANGED)),
                "about_the_business": len(self.business_changes),
                "about_our_checking": len(self.coverage_changes),
            },
            "statement": self.statement(),
        }


def compare(*, business_id: str, tenant: TenantId | None,
            previous: list[dict], current: list[dict]) -> Comparison:
    """Diff two sets of observations. Neither is modified.

    Both are read-only inputs and the historical one is never rewritten — §18
    is explicit that historical research stays historical, and the delta is
    worthless if the baseline moves.
    """
    tenant = _require_tenant(tenant, method="reevaluation.compare")
    was = _by_feature(previous)
    now = _by_feature(current)

    changes: list[FeatureChange] = []
    for feature in sorted(set(was) | set(now)):
        if feature in was and feature in now:
            changes.append(FeatureChange(
                feature=feature, was=_normalise(was[feature]),
                now=_normalise(now[feature]),
                change=classify(was[feature], now[feature])))
        elif feature in now:
            # Never checked before. Only a finding about the business if the
            # new reading actually confirms something.
            observed = _normalise(now[feature])
            changes.append(FeatureChange(
                feature=feature, was="", now=observed,
                change=(Change.NEWLY_OBSERVED if observed != UNVERIFIED
                        else Change.NOW_UNVERIFIED)))
        else:
            # The old reading had it and the new one does not mention it. That
            # is our pipeline changing, not their site, so it is recorded as a
            # coverage change rather than a disappearance.
            changes.append(FeatureChange(
                feature=feature, was=_normalise(was[feature]), now="",
                change=Change.NOW_UNVERIFIED))

    return Comparison(
        business_id=business_id, tenant_id=str(tenant), changes=tuple(changes),
        first_seen=tuple(sorted(set(now) - set(was))),
        no_longer_checked=tuple(sorted(set(was) - set(now))))


def to_event(comparison: Comparison, *, actor: str = "reevaluation"
             ) -> BusinessEvent:
    """Append the comparison. The historical observations are untouched."""
    return BusinessEvent(business_id=comparison.business_id, factory=FACTORY,
                         kind=COMPARED, actor=actor, detail=comparison.summary())


def read(events: list, *, tenant: TenantId | None = None) -> list[dict]:
    """TENANT_SCOPED. Comparisons for one tenant, newest first."""
    tenant = _require_tenant(tenant, method="reevaluation.read")
    found = []
    for event in events:
        kind = getattr(event, "kind", None) or event.get("kind")
        if kind != COMPARED:
            continue
        detail = getattr(event, "detail", None) or event.get("detail") or {}
        if not owns(detail.get("tenant_id"), tenant):
            continue
        found.append(dict(detail))
    return found


class Candidate(BaseModel):
    """A business worth re-evaluating, and why."""

    model_config = ConfigDict(frozen=True)

    business_id: str
    tenant_id: str
    name: str = ""
    website: str = ""
    #: How many observations the last research produced. Zero means the old
    #: record is a stub, which is a reason to research rather than to compare.
    observations: int = 0
    last_checked: str = ""
    reason: str = ""


def candidates(businesses: list[dict], *, tenant: TenantId | None,
               known_features: frozenset[str] = frozenset()) -> tuple[Candidate, ...]:
    """Which businesses a re-evaluation would actually learn something about.

    Not "all of them". A business whose last research already covered every
    feature the current engine emits, recently, has nothing to gain from a
    second pass — and running one anyway spends the customer's quota to
    produce `UNCHANGED` rows.
    """
    tenant = _require_tenant(tenant, method="reevaluation.candidates")
    found: list[Candidate] = []
    for business in businesses:
        if not owns(business.get("tenant_id"), tenant):
            continue
        observed = {o.get("feature") for o in (business.get("observations") or [])}
        missing = known_features - observed if known_features else set()
        if not business.get("observations"):
            reason = "no previous research to compare against"
        elif missing:
            reason = (f"{len(missing)} feature(s) the current engine checks were "
                      "not checked last time")
        else:
            continue
        found.append(Candidate(
            business_id=business.get("business_id", ""),
            tenant_id=str(tenant), name=business.get("name", ""),
            website=business.get("website", ""),
            observations=len(business.get("observations") or []),
            last_checked=business.get("last_checked", ""), reason=reason))
    return tuple(found)
