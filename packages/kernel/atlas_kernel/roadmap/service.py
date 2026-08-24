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
from enum import StrEnum

from ..execution.capabilities import EXECUTORS, REQUIRES_CUSTOMER_INPUT
from ..opportunity.models import BusinessEvent
from ..opportunity.tenancy import TenantId, owns
from ..opportunity.tenancy import require as _require_tenant
from ..recommendation.models import CustomerTask, QevikTask, Recommendation
from ..recommendation.offers import OFFERS, offer_for
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
    "offer-website": Dimension.TECHNICAL_HEALTH,
}

#: Every offer must appear above. Without this, adding an offer produces tasks
#: with no dimension and no metric — they schedule, they are approved, they
#: execute, and nothing can ever be measured about them. Checked at import so a
#: missing entry is a failure to start rather than a quiet loss of measurement.
_uncovered = {o.id for o in OFFERS} - set(OFFER_DIMENSION)
if _uncovered:                                          # pragma: no cover - guard
    raise RuntimeError(
        f"offers with no dimension: {sorted(_uncovered)}. Add them to "
        "OFFER_DIMENSION, or a roadmap task for them carries no metric.")

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
        # Worded around its own claim gate, twice. "after the work" reads as a
        # sequence claim and the word "measured" reads as a change claim, so a
        # sentence explaining methodology tripped the check that exists to stop
        # us claiming results. The check is right; the sentence had to change.
        "Conversion rate needs an analytics source. A reading taken once the "
        "work is under way is not a baseline.",
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
            id=_id(), tenant_id=tenant_id, task=task, horizon=Horizon.DAY_7,
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

    def _executable(recommendation: Recommendation) -> bool:
        """Whether something can actually perform this today.

        An offer existing is not the same as an executor existing. `EXECUTORS`
        is the registry of what Qevik can run, and reading the offer catalogue
        alone presented five capabilities as executable that nothing could
        perform — a promise the execution gate would then refuse, after the
        customer had read it as a plan.

        An executor existing is not sufficient either. The execution service
        passes exactly four arguments, so a capability needing anything else —
        Arabic copy, a logo, a price list — can never succeed through this path
        however correct its code is. `REQUIRES_CUSTOMER_INPUT` names those, and
        they are presented as needing the customer rather than as work Qevik
        will do. The refusal at execution time was already correct; what was
        wrong was promising it beforehand.
        """
        return (bool(recommendation.capability_id)
                and offer_for(recommendation.offer_id) is not None
                and recommendation.offer_id in EXECUTORS
                and recommendation.offer_id not in REQUIRES_CUSTOMER_INPUT)

    surviving = sorted(
        (r for r in recommendations
         if not (lambda s: s is not None and s.strong)(_score_for(r))),
        key=_severity)

    # --- 3. what the customer must supply, for surviving work only -----------
    by_title: dict[str, str] = {}
    prerequisites: dict[str, list[str]] = {}
    for recommendation in surviving:
        # Only for work that can actually run. Asking a customer to gather
        # material for a capability nothing can perform wastes their time on
        # our behalf, and it is the same defect as asking them to prepare work
        # for a dimension that was already strong.
        if not _executable(recommendation):
            continue
        dimension = OFFER_DIMENSION.get(recommendation.offer_id)
        for task in recommendation.customer_tasks:
            if task.title not in by_title:
                task_id = _id()
                by_title[task.title] = task_id
                tasks.append(RoadmapTask(
                    id=task_id, tenant_id=tenant_id, task=task, horizon=Horizon.DAY_7,
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
        dimension = OFFER_DIMENSION.get(recommendation.offer_id)
        executable = _executable(recommendation)
        metric = DIMENSION_METRIC.get(dimension, "") if dimension else ""
        # Only what this piece of work is actually waiting for. Depending on
        # every outstanding customer task would stall each one behind all of them.
        depends_on = tuple(prerequisites.get(recommendation.id, ()))
        tasks.append(RoadmapTask(
            id=_id(), tenant_id=tenant_id,
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
            id=_id(), tenant_id=tenant_id, task=QevikTask(title, why=why),
            horizon=_horizon(index),
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


class Change(StrEnum):
    """What kind of change re-evaluation found.

    Named rather than left as added/removed lists, because the same movement
    means different things and a customer needs the difference. A task
    disappearing because the problem was fixed and a task disappearing because
    nobody can do it any more are both "removed", and only one of them is good
    news.
    """

    UNCHANGED = "unchanged"
    NEWLY_MEASURED = "newly_measured"
    DIMENSION_IMPROVED = "dimension_improved"
    DIMENSION_WORSENED = "dimension_worsened"
    NEW_OPPORTUNITY = "new_opportunity"
    OPPORTUNITY_RESOLVED = "opportunity_resolved"
    TASK_NO_LONGER_REQUIRED = "task_no_longer_required"


def changed(previous: Roadmap, current: Roadmap) -> dict:
    """What re-evaluation changed, and why it changed.

    A plan that silently regenerates invalidates work a customer is part-way
    through, so the difference is reported rather than assumed — and each part
    of it is traced back to the evidence that moved. "Your roadmap changed" with
    no reason is indistinguishable from a system that reshuffles itself, which
    is how a customer stops believing any of it.

    Neither roadmap is modified. History lives in the event timeline: both plans
    remain as they were recorded, and this is a reading across them.
    """
    before = {t.task.title: t for t in previous.tasks}
    after = {t.task.title: t for t in current.tasks}
    moved = {title: (before[title].horizon.value, task.horizon.value)
             for title, task in after.items()
             if title in before and before[title].horizon is not task.horizon}

    was = previous.derived_from.get("readiness") or {}
    now = current.derived_from.get("readiness") or {}
    dimensions = {
        d: {"from": was.get(d), "to": now.get(d)}
        for d in set(was) | set(now) if was.get(d) != now.get(d)}

    newly_measured = (set(current.derived_from.get("measured_metrics") or ())
                      - set(previous.derived_from.get("measured_metrics") or ()))

    added, removed = sorted(set(after) - set(before)), sorted(set(before) - set(after))
    return {
        "added": added,
        "removed": removed,
        "rescheduled": moved,
        "readiness": (previous.readiness_overall, current.readiness_overall),
        "dimensions_moved": dimensions,
        "newly_measured": sorted(newly_measured),
        "newly_left_alone": sorted(set(current.left_alone) - set(previous.left_alone)),
        "why": _why(added, removed, moved, dimensions, newly_measured,
                    previous, current, before, after),
        "outcomes": _outcomes(added, removed, dimensions, newly_measured,
                              previous, current, before, after),
        "changed": bool(added or removed or moved
                        or previous.readiness_overall != current.readiness_overall),
    }


def _outcomes(added: list, removed: list, dimensions: dict, newly_measured: set,
              previous: Roadmap, current: Roadmap, before: dict, after: dict
              ) -> list[dict]:
    """Every change, classified. One entry per thing that moved.

    A dimension's direction is read from the scores rather than from whether a
    task disappeared: work can leave a plan because it was done, because the
    capability went away, or because the evidence behind it was withdrawn, and
    only the first is an improvement.
    """
    found: list[dict] = []
    for dimension, movement in sorted(dimensions.items()):
        was, now = movement["from"], movement["to"]
        if was is None and now is not None:
            kind = Change.NEWLY_MEASURED
        elif was is not None and now is not None and now > was:
            kind = Change.DIMENSION_IMPROVED
        elif was is not None and now is not None and now < was:
            kind = Change.DIMENSION_WORSENED
        else:
            continue
        found.append({"change": kind.value, "dimension": dimension,
                      "from": was, "to": now})

    for metric in sorted(newly_measured):
        found.append({"change": Change.NEWLY_MEASURED.value, "metric": metric})

    for title in removed:
        task = before[title]
        movement = dimensions.get(task.dimension) or {}
        improved = (movement.get("from") is not None
                    and movement.get("to") is not None
                    and movement["to"] > movement["from"])
        resolved = improved or task.dimension in current.left_alone
        found.append({
            "change": (Change.OPPORTUNITY_RESOLVED.value if resolved
                       else Change.TASK_NO_LONGER_REQUIRED.value),
            "task": title, "dimension": task.dimension})

    for title in added:
        found.append({"change": Change.NEW_OPPORTUNITY.value, "task": title,
                      "dimension": after[title].dimension})

    return found or [{"change": Change.UNCHANGED.value}]


def _why(added: list, removed: list, moved: dict, dimensions: dict,
         newly_measured: set, previous: Roadmap, current: Roadmap,
         before: dict, after: dict) -> list[str]:
    """One sentence per change, naming the evidence that caused it.

    Phrased to assert nothing beyond what happened. "X is no longer proposed
    because the site now serves Arabic" is a statement about the site; "X worked"
    would be a claim about a result, and the roadmap has no standing to make one.
    """
    reasons: list[str] = []
    for title in removed:
        task = before[title]
        moved_to = dimensions.get(task.dimension)
        if task.dimension in current.left_alone:
            reasons.append(f"{title!r} is no longer proposed: {task.dimension} is now "
                           "confirmed in place, so there is nothing to do there.")
        elif moved_to:
            reasons.append(f"{title!r} is no longer proposed: {task.dimension} moved "
                           f"from {moved_to['from']} to {moved_to['to']}.")
        elif task.metric_key in newly_measured:
            reasons.append(f"{title!r} is no longer proposed: {task.metric_key} now has "
                           "a source, so it no longer needs establishing.")
        else:
            reasons.append(f"{title!r} is no longer proposed: it was not derived from "
                           "the current evidence.")
    for title in added:
        task = after[title]
        moved_to = dimensions.get(task.dimension)
        if moved_to:
            reasons.append(f"{title!r} is newly proposed: {task.dimension} moved from "
                           f"{moved_to['from']} to {moved_to['to']}.")
        else:
            reasons.append(f"{title!r} is newly proposed: {task.why}")
    for title, (was_h, now_h) in moved.items():
        reasons.append(f"{title!r} moved from the {was_h} to the {now_h} horizon "
                       "as the ranking of what is weakest changed.")
    if not reasons and previous.readiness_overall != current.readiness_overall:
        reasons.append(
            f"The plan is unchanged; readiness moved from "
            f"{previous.readiness_overall} to {current.readiness_overall}.")
    return reasons
