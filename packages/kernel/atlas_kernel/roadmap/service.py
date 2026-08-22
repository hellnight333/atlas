"""Generating the plan, and changing it when the evidence changes.

The whole point is that two businesses get different plans. That is not achieved
by adding variety — it falls out of deriving every task from something specific:
which dimensions this business's research confirmed weak, which of those Qevik
has a registered capability for, what the customer must supply first, and what
has never been measured at all.

Four rules do most of the work:

* **A strong dimension produces nothing.** `Readiness.actionable` cannot return
  one, so there is no branch here that could add a task to fill space.
* **An unmeasured dimension produces a measurement task**, never an assumed
  weakness. "We have not looked at your AI visibility" is a true and useful
  thing to put in a plan; "your AI visibility is poor" would be invented.
* **Qevik only claims work a registered capability can do.** Anything else is
  labelled `NO_CAPABILITY` and shown without being promised.
* **A customer task that blocks comes first.** Scheduling our work before the
  permission it needs produces a plan that stalls in week two.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from ..opportunity.models import BusinessEvent
from ..opportunity.tenancy import TenantId, owns
from ..opportunity.tenancy import require as _require_tenant
from ..recommendation.models import CustomerTask, QevikTask, Recommendation
from ..recommendation.offers import offer_for
from .models import Executability, Horizon, Roadmap, RoadmapTask
from .readiness import Confidence, Dimension, DimensionScore, Readiness, assess

log = logging.getLogger(__name__)

FACTORY = "roadmap"
GENERATED = "roadmap_generated"

#: Which dimension each offer improves, so a recommendation lands in the right
#: part of the plan. Keyed on offers that exist; an offer with no entry is
#: still scheduled, just without a dimension.
OFFER_DIMENSION: dict[str, Dimension] = {
    "offer-portfolio-system": Dimension.PROOF,
    "offer-arabic-experience": Dimension.MULTILINGUAL,
    "offer-editorial": Dimension.CONTENT,
    "offer-imagery": Dimension.CONTENT,
    "offer-one-tap-contact": Dimension.REACHABILITY,
    "offer-enquiry-builder": Dimension.CONVERSION,
}

#: What would show that work on a dimension had any effect. Metric keys from the
#: measurement catalogue, so a roadmap task and a later measurement agree on
#: what was being watched.
DIMENSION_METRIC: dict[Dimension, str] = {
    Dimension.REACHABILITY: "leads",
    Dimension.CONVERSION: "conversion_rate",
    Dimension.DISCOVERABILITY: "clicks",
    Dimension.AI_VISIBILITY: "ai_mention_rate",
    Dimension.CONTENT: "views",
    Dimension.PROOF: "page_views",
    Dimension.TECHNICAL_HEALTH: "technical_health",
    Dimension.MULTILINGUAL: "sessions",
}

#: What a confirmed-weak dimension needs, for the case where no offer covers it.
#: Without this a weakness nobody sells against disappears from the plan, which
#: is the same failure as inventing one — the clinic below had no proof at all
#: and no capability matched, so its roadmap said nothing about proof.
WEAKNESS: dict[Dimension, tuple[str, str]] = {
    Dimension.REACHABILITY: (
        "Make the business contactable from a phone",
        "The published contact methods are not usable in one tap."),
    Dimension.CONVERSION: (
        "Give visitors a way to ask for what they want",
        "There is no path from interest to an enquiry that captures what the "
        "business needs in order to quote."),
    Dimension.DISCOVERABILITY: (
        "Repair how search engines read the site",
        "Titles, structure and indexability are what a search engine has to work "
        "with, and they are not in place."),
    Dimension.AI_VISIBILITY: (
        "Become answerable by AI assistants",
        "The site does not carry the structured, factual answers an assistant "
        "needs in order to cite a business."),
    Dimension.CONTENT: (
        "Publish something worth finding",
        "There is little or nothing published for search or an assistant to read."),
    Dimension.PROOF: (
        "Turn the work already done into evidence a buyer can check",
        "A buyer cannot answer the only question that matters — have they done my "
        "kind of work — because the proof is not on the site in a usable form."),
    Dimension.TECHNICAL_HEALTH: (
        "Repair the certificate, speed and broken links",
        "A visitor who is warned the site is not secure, or who waits, leaves "
        "before reading anything on it."),
    Dimension.MULTILINGUAL: (
        "Serve the market in its own language",
        "The site is published in one language in a market that is not."),
}

#: How a dimension is measured when nothing has measured it. Says what would
#: have to happen, which is usually a connection only the customer can make.
MEASUREMENT_TASK: dict[Dimension, tuple[str, str, str]] = {
    Dimension.AI_VISIBILITY: (
        "Measure AI search visibility",
        "Run the visibility queries for this business across the supported "
        "assistants and search engines, and record what each one actually shows.",
        ""),
    Dimension.CONTENT: (
        "Assess the existing content",
        "Read what is published before proposing anything new, so a plan does not "
        "recommend writing to a business that already writes.",
        ""),
    Dimension.DISCOVERABILITY: (
        "Connect Search Console",
        "Impressions, clicks and position come from Search Console. Without it "
        "search performance can only be guessed at.",
        "Grant Qevik read access to Search Console for this domain"),
    Dimension.CONVERSION: (
        "Connect analytics",
        "Conversion rate cannot be measured without an analytics source, and a "
        "baseline taken after the work has started is not a baseline.",
        "Grant Qevik read access to the analytics property"),
}


def _horizon(index: int) -> Horizon:
    """When work belongs, given how weak its dimension is relative to the rest.

    The first week is reserved for measurement and for what the customer has to
    supply — a plan whose opening week contains both "send us your articles" and
    "the articles are published" is not a plan. So work starts at 30 days, and
    anything blocked is after its prerequisite by construction rather than by a
    rule that could be got wrong.
    """
    return (Horizon.DAY_30 if index < 2 else
            Horizon.DAY_60 if index < 4 else Horizon.DAY_90)


def generate(*, business_id: str, tenant_id: str | None, observations: list[dict],
             recommendations: tuple[Recommendation, ...] = (),
             business_model: str = "", measured_metrics: frozenset[str] = frozenset(),
             readiness: Readiness | None = None) -> Roadmap:
    """Derive a plan from this business's evidence and nothing else."""
    now = datetime.now(UTC).isoformat()
    readiness = readiness or assess(business_id=business_id, observations=observations,
                                    business_model=business_model, generated_at=now)
    by_dimension = readiness.by_dimension
    tasks: list[RoadmapTask] = []
    counter = 0

    def _id() -> str:
        nonlocal counter
        counter += 1
        return f"task-{counter:02d}"

    # --- 1. what has never been measured -------------------------------------
    # First, and deliberately: proposing a fix for something nobody has looked
    # at is how a plan invents a weakness.
    for score in readiness.unmeasured:
        template = MEASUREMENT_TASK.get(score.dimension)
        if not template:
            continue
        title, why, customer_action = template
        metric = DIMENSION_METRIC.get(score.dimension, "")
        if metric and metric in measured_metrics:
            continue
        task = (CustomerTask(title, customer_action, why=why) if customer_action
                else QevikTask(title, why=why))
        tasks.append(RoadmapTask(
            id=_id(), task=task, horizon=Horizon.DAY_7,
            # Measurement, whoever performs it. `blocked_by_customer` reads the
            # task's kind, so one that needs a grant is still shown as waiting.
            executability=Executability.MEASURE_FIRST,
            dimension=score.dimension.value, why=why, evidence=(),
            requires_approval=False, metric_key=metric,
            expected_outcome=f"a baseline for {metric or score.dimension.value}",
            confidence=Confidence.UNKNOWN.value))

    # --- 2. which recommendations survive this business's evidence -----------
    # A dimension already working gets nothing, whatever else is true — and
    # nothing downstream of it either. Filtering here rather than at scheduling
    # time is what stops the plan asking a customer to prepare material for work
    # that was never going to run.
    def _score_for(recommendation: Recommendation) -> DimensionScore | None:
        dimension = OFFER_DIMENSION.get(recommendation.offer_id)
        return by_dimension.get(dimension) if dimension else None

    def _severity(recommendation: Recommendation) -> float:
        score = _score_for(recommendation)
        if score is None or score.score is None:
            return 1.0  # no basis to rank it above something measured weak
        return score.score / max(score.weight, 0.01)

    surviving = sorted(
        (r for r in recommendations
         if not (lambda s: s is not None and s.strong)(_score_for(r))),
        key=_severity)

    # --- 3. what the customer must supply, for surviving work only -----------
    by_title: dict[str, str] = {}
    prerequisites: dict[str, list[str]] = {}
    for recommendation in surviving:
        dimension = OFFER_DIMENSION.get(recommendation.offer_id)
        for task in recommendation.customer_tasks:
            if task.title not in by_title:
                task_id = _id()
                by_title[task.title] = task_id
                tasks.append(RoadmapTask(
                    id=task_id, task=task, horizon=Horizon.DAY_7,
                    executability=Executability.CUSTOMER_MUST_ACT,
                    dimension=dimension.value if dimension else "",
                    why=task.why or recommendation.rationale,
                    evidence=recommendation.evidence,
                    requires_approval=False,
                    recommendation_id=recommendation.id,
                    metric_key=DIMENSION_METRIC.get(dimension, "") if dimension else "",
                    expected_outcome="unblocks the work that depends on it",
                    confidence=recommendation.confidence))
            if task.blocks:
                prerequisites.setdefault(recommendation.id, []).append(by_title[task.title])

    # --- 4. the work itself, worst dimension first ---------------------------
    for index, recommendation in enumerate(surviving):
        offer = offer_for(recommendation.offer_id)
        dimension = OFFER_DIMENSION.get(recommendation.offer_id)
        executable = bool(recommendation.capability_id) and offer is not None
        metric = DIMENSION_METRIC.get(dimension, "") if dimension else ""
        # Only what this piece of work is actually waiting for. Depending on
        # every outstanding customer task would stall each one behind all of them.
        depends_on = tuple(prerequisites.get(recommendation.id, ()))
        tasks.append(RoadmapTask(
            id=_id(),
            task=QevikTask(recommendation.title, why=recommendation.rationale),
            horizon=_horizon(index),
            executability=(Executability.QEVIK_CAN_EXECUTE if executable
                           else Executability.NO_CAPABILITY),
            dimension=dimension.value if dimension else "",
            why=recommendation.rationale,
            evidence=recommendation.evidence,
            depends_on=depends_on,
            requires_approval=recommendation.requires_approval,
            recommendation_id=recommendation.id,
            capability_id=recommendation.capability_id if executable else "",
            metric_key=metric,
            expected_outcome=(", ".join(recommendation.measurement)
                              or (f"a change in {metric}" if metric else "an observable change")),
            confidence=recommendation.confidence))

    # --- 5. confirmed-weak, and nothing here can sell against it -------------
    # Shown, never promised. Dropping these would make the plan quietly
    # capability-shaped: only the weaknesses Qevik happens to have an offer for
    # would ever appear, which reads to a customer as an audit and is not one.
    covered = {OFFER_DIMENSION.get(r.offer_id) for r in surviving}
    already = {t.dimension for t in tasks}
    for index, score in enumerate(readiness.actionable, start=len(surviving)):
        if score.dimension in covered or score.dimension.value in already:
            continue
        finding = WEAKNESS.get(score.dimension)
        if not finding:
            continue
        title, why = finding
        tasks.append(RoadmapTask(
            id=_id(), task=QevikTask(title, why=why), horizon=_horizon(index),
            executability=Executability.NO_CAPABILITY,
            dimension=score.dimension.value, why=why,
            # The confirmed-absent features themselves. A finding with no
            # capability behind it still has to rest on something observed.
            evidence=score.missing,
            requires_approval=True,
            metric_key=DIMENSION_METRIC.get(score.dimension, ""),
            expected_outcome=f"a higher {score.dimension.value} score once addressed",
            confidence=score.confidence.value))

    left_alone = tuple(d.dimension.value for d in readiness.dimensions if d.strong)
    return Roadmap(
        business_id=business_id, tenant_id=tenant_id, business_model=business_model,
        readiness_overall=readiness.overall, tasks=tuple(tasks),
        left_alone=left_alone, generated_at=now,
        derived_from={
            "observations": len(observations),
            "recommendations": [r.id for r in recommendations],
            "scheduled": [r.id for r in surviving],
            "readiness": {d.dimension.value: d.score for d in readiness.dimensions},
            "measured_metrics": sorted(measured_metrics),
        })


def to_event(roadmap: Roadmap, *, actor: str = "roadmap") -> BusinessEvent:
    return BusinessEvent(
        business_id=roadmap.business_id, factory=FACTORY, kind=GENERATED, actor=actor,
        detail={
            "tenant_id": roadmap.tenant_id,
            "business_model": roadmap.business_model,
            "readiness_overall": roadmap.readiness_overall,
            "generated_at": roadmap.generated_at,
            "left_alone": list(roadmap.left_alone),
            "derived_from": roadmap.derived_from,
            "tasks": [
                {"id": t.id, "title": t.task.title, "kind": t.task.kind.value,
                 "horizon": t.horizon.value, "executability": t.executability.value,
                 "dimension": t.dimension, "why": t.why,
                 "depends_on": list(t.depends_on), "metric": t.metric_key,
                 "expected_outcome": t.expected_outcome,
                 "evidence": list(t.evidence)} for t in roadmap.tasks],
        })


def read(events: list, *, tenant: TenantId | None = None) -> list[dict]:
    """TENANT_SCOPED. Roadmaps for one tenant, newest first."""
    tenant = _require_tenant(tenant, method="roadmap.read")
    found = []
    for event in events:
        kind = getattr(event, "kind", None) or event.get("kind")
        if kind != GENERATED:
            continue
        detail = getattr(event, "detail", None) or event.get("detail") or {}
        if not owns(detail.get("tenant_id"), tenant):
            continue
        found.append(dict(detail))
    return sorted(found, key=lambda d: d.get("generated_at", ""), reverse=True)


def changed(previous: Roadmap, current: Roadmap) -> dict:
    """What re-evaluation actually changed, and why.

    A plan that silently regenerates invalidates work a customer is part-way
    through, so the difference is reported rather than assumed.
    """
    before = {t.task.title for t in previous.tasks}
    after = {t.task.title for t in current.tasks}
    moved = {t.task.title: (p.horizon.value, t.horizon.value)
             for t in current.tasks
             for p in previous.tasks
             if p.task.title == t.task.title and p.horizon is not t.horizon}
    return {
        "added": sorted(after - before),
        "removed": sorted(before - after),
        "rescheduled": moved,
        "readiness": (previous.readiness_overall, current.readiness_overall),
        "newly_left_alone": sorted(set(current.left_alone) - set(previous.left_alone)),
        "changed": bool((after - before) or (before - after) or moved
                        or previous.readiness_overall != current.readiness_overall),
    }
