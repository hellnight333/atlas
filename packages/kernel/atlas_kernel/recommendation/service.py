"""Turning opportunities into recommendations, and reading them back safely.

Nothing here executes. A recommendation is a proposal a customer can accept or
refuse, and the step from acceptance to a job is deliberately not in this
module — P1.3 owns that, and keeping the boundary visible is what stops a
recommendation quietly becoming work somebody did not agree to.

Persistence is the existing `BusinessEvent` timeline under a `recommendation`
factory. No new table: a recommendation is something that happened to a
business, its state is folded from events, and the append-only history is what
answers "why was this proposed, and who declined it".
"""

from __future__ import annotations

import logging

from ..opportunity.models import BusinessEvent
from ..opportunity.tenancy import TenantId
from ..opportunity.tenancy import require as _require_tenant
from ..outreach.opportunity import Opportunity
from .models import (
    CustomerTask,
    QevikTask,
    Recommendation,
    RecommendationState,
    Task,
    Unsupported,
)
from .offers import CapabilityOffer, offers_for_opportunity

log = logging.getLogger(__name__)

FACTORY = "recommendation"
PROPOSED = "recommendation_proposed"
DECIDED = "recommendation_decided"
#: A customer did the thing only they could do. An event rather than a field
#: because `Recommendation.waiting_on_customer` reads the tasks as written and
#: has no way to know one was since completed — and a stored flag beside it
#: would be a second answer to the same question.
CUSTOMER_TASK_DONE = "customer_task_completed"

#: Work every offer needs from the customer before anything can be published.
#: Held here rather than per-offer because it is the same consent every time,
#: and repeating it per offer is how one of them ends up missing it.
_ALWAYS: tuple[Task, ...] = (
    CustomerTask("Approve the result before it goes live",
                 "Review what Qevik produced and approve or reject it",
                 why="Nothing is published without an explicit decision on the "
                     "actual artefact."),
)


def _tasks_for(offer: CapabilityOffer) -> tuple[Task, ...]:
    """What Qevik would do, and what only the customer can do."""
    tasks: list[Task] = [
        QevikTask(f"Build: {offer.name}", why=offer.summary),
    ]
    if offer.qa_layers:
        tasks.append(QevikTask(
            "Run QA", why=f"Checks: {', '.join(offer.qa_layers)}. A result that "
                          "fails any of them does not reach you."))
    for connection in offer.required_connections:
        tasks.append(CustomerTask(
            f"Grant {connection}", f"Record {connection} in the dashboard",
            why="Qevik cannot grant this on your behalf."))
    for needed in offer.required_inputs:
        # Inputs the business already publishes are ours to gather; anything
        # else has to come from them, and saying so is the point of the split.
        if "already" in needed or "publishes" in needed:
            tasks.append(QevikTask(f"Gather {needed}"))
        else:
            tasks.append(CustomerTask(
                f"Provide {needed}", f"Send or confirm {needed}",
                why="Only you have this."))
    if offer.measurement:
        tasks.append(QevikTask(
            "Measure the result",
            why=f"Baseline then re-measure: {', '.join(offer.measurement)}.",
            blocks=False))
    return tuple(tasks) + _ALWAYS


def propose(*, business_id: str, tenant_id: str | None,
            opportunities: tuple[Opportunity, ...], business_model: str = "",
            plan: str = "", strengths: tuple[str, ...] = (),
            unverified: tuple[str, ...] = ()) -> tuple[Recommendation, ...]:
    """One recommendation per opportunity Qevik can actually act on.

    An opportunity with no matching offer produces nothing rather than a
    recommendation with no executor. Zero recommendations is a valid and common
    outcome — a strong business with a fast site and nothing confirmed missing
    should receive none, and manufacturing one to fill the page is the failure
    this whole layer is built to avoid.
    """
    # One recommendation per offer, not per opportunity. Two opportunities can
    # legitimately point at the same piece of work — "your proof is invisible"
    # and "pages nothing links to" are both answered by a portfolio index — and
    # proposing it twice makes the list look automated, which is the fastest way
    # for a customer to stop reading it. The evidence merges instead.
    grouped: dict[str, list[Opportunity]] = {}
    for opportunity in opportunities:
        offers = offers_for_opportunity(opportunity.key, business_model=business_model,
                                        plan=plan)
        if not offers:
            continue
        grouped.setdefault(offers[0].id, []).append(opportunity)

    made: list[Recommendation] = []
    for offer_id, group in grouped.items():
        offer = next(o for o in offers_for_opportunity(group[0].key,
                                                       business_model=business_model,
                                                       plan=plan) if o.id == offer_id)
        # The strongest of the group leads; every one of them contributes its
        # evidence, so the recommendation cites everything that supports it.
        opportunity = min(group, key=lambda o: o.rank)
        evidence: list[str] = []
        for member in group:
            for item in member.evidence:
                if item not in evidence:
                    evidence.append(item)
        made.append(Recommendation(
            business_id=business_id,
            tenant_id=tenant_id,
            opportunity_key=opportunity.key,
            evidence=tuple(evidence),
            unverified=unverified,
            capability_id=offer.capability_id,
            offer_id=offer.id,
            title=offer.name,
            rationale=opportunity.why,
            strengths=strengths,
            tasks=_tasks_for(offer),
            priority=opportunity.priority,
            confidence=opportunity.confidence,
            requires_approval=offer.requires_approval,
            estimated_units=offer.estimated_units,
            qa_layers=offer.qa_layers,
            publication_target=offer.publication_target,
            measurement=offer.measurement,
        ))
    return tuple(made)


def to_event(recommendation: Recommendation, *, actor: str = "recommendation_engine"
             ) -> BusinessEvent:
    """A proposal, recorded on the business's own timeline."""
    return BusinessEvent(
        business_id=recommendation.business_id, factory=FACTORY, kind=PROPOSED,
        actor=actor,
        detail={
            "recommendation_id": recommendation.id,
            "tenant_id": recommendation.tenant_id,
            "opportunity_key": recommendation.opportunity_key,
            "offer_id": recommendation.offer_id,
            "capability_id": recommendation.capability_id,
            "title": recommendation.title,
            "rationale": recommendation.rationale,
            "evidence": list(recommendation.evidence),
            "unverified": list(recommendation.unverified),
            "strengths": list(recommendation.strengths),
            "priority": recommendation.priority,
            "confidence": recommendation.confidence,
            "requires_approval": recommendation.requires_approval,
            "estimated_units": recommendation.estimated_units,
            "customer_tasks": [t.title for t in recommendation.customer_tasks],
            "qevik_tasks": [t.title for t in recommendation.qevik_tasks],
            "measurement": list(recommendation.measurement),
            "state": recommendation.state.value,
        },
    )


def decision_event(recommendation_id: str, business_id: str, state: RecommendationState,
                   *, actor: str, note: str = "") -> BusinessEvent:
    """A human answered. Append-only, so a change of mind is visible as one."""
    if state is RecommendationState.PROPOSED:
        raise Unsupported("proposed is not a decision")
    return BusinessEvent(
        business_id=business_id, factory=FACTORY, kind=DECIDED, actor=actor,
        detail={"recommendation_id": recommendation_id, "state": state.value,
                "note": note},
    )


def fold(events: list, *, tenant: TenantId | None = None) -> list[dict]:
    """Current recommendations for one business, from its events.

    TENANT_SCOPED. A recommendation carries the tenant it was proposed under, so
    a caller cannot read another tenant's proposals even through a shared
    timeline — the same rule the repository applies to businesses.
    """
    from ..opportunity.tenancy import owns

    tenant = _require_tenant(tenant, method="recommendation.fold")
    current: dict[str, dict] = {}
    for event in events:
        kind = getattr(event, "kind", None) or event.get("kind")
        detail = getattr(event, "detail", None) or event.get("detail") or {}
        if kind == PROPOSED:
            if not owns(detail.get("tenant_id"), tenant):
                continue
            current[detail["recommendation_id"]] = dict(detail)
        elif kind == DECIDED:
            existing = current.get(detail.get("recommendation_id"))
            if existing is not None:
                existing["state"] = detail["state"]
                existing["decided_note"] = detail.get("note", "")
    return list(current.values())


def customer_task_event(recommendation_id: str, business_id: str, title: str,
                        *, tenant_id: str | None = None,
                        actor: str = "customer") -> BusinessEvent:
    """Record that the customer completed one of their tasks.

    The actor matters and is not defaulted to Qevik: this is the customer
    reporting that they did something outside the system, and the timeline
    should not later read as though we did it for them.
    """
    return BusinessEvent(
        business_id=business_id, factory=FACTORY, kind=CUSTOMER_TASK_DONE,
        actor=actor,
        detail={"recommendation_id": recommendation_id, "title": title,
                "tenant_id": tenant_id})


def completed_customer_tasks(events: list, *, recommendation_id: str = "",
                             tenant: TenantId | None = None) -> frozenset[str]:
    """Titles the customer has reported done, folded from the timeline."""
    tenant = _require_tenant(tenant, method="recommendation.completed_customer_tasks")
    from ..opportunity.tenancy import owns

    done: set[str] = set()
    for event in events:
        kind = getattr(event, "kind", None) or event.get("kind")
        if kind != CUSTOMER_TASK_DONE:
            continue
        detail = getattr(event, "detail", None) or event.get("detail") or {}
        if not owns(detail.get("tenant_id"), tenant):
            continue
        if recommendation_id and detail.get("recommendation_id") != recommendation_id:
            continue
        if title := detail.get("title"):
            done.add(title)
    return frozenset(done)
