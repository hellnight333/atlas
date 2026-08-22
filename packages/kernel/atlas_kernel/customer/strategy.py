"""The paragraph a customer actually reads, assembled from evidence.

Everything below is derived. There is no template with slots, because a template
produces the same three sentences for every business and the whole point of the
readiness model is that two businesses get different answers. What is fixed is
the *shape* of the answer — where you stand, what is already fine, what is
worth doing, who does it, and what happens after — and each part is either
filled from evidence or omitted.

Two rules do the work:

**A dimension nobody measured is described as unmeasured**, not as a weakness.
"AI visibility — not yet checked" and "AI visibility — weak" are different
statements and only one of them is true.

**Every sentence passes the P1.4 claim gate at UNKNOWN.** A strategy is written
before anything has been measured, so nothing in it may assert a result. That is
enforced here rather than trusted, because this is the text most likely to drift
towards salesmanship.
"""

from __future__ import annotations

from ..measurement.models import BY_KEY
from ..roadmap.models import Executability, Horizon, Roadmap
from ..roadmap.presentation import vet
from ..roadmap.readiness import DimensionScore, Readiness

#: How a dimension reads in a sentence. Short, because these appear in lists.
LABELS: dict[str, str] = {
    "reachability": "how easily people can contact you",
    "conversion": "turning visitors into enquiries",
    "discoverability": "how search engines read your site",
    "ai_visibility": "whether AI assistants can cite you",
    "content": "what you publish",
    "proof": "evidence a buyer can check",
    "technical_health": "the health of your site",
    "multilingual": "serving the market in its own language",
}


def _describe(dimension: str, score: DimensionScore | None) -> str:
    label = LABELS.get(dimension, dimension.replace("_", " "))
    if score is None:
        return f"{label} — not yet checked"
    if score.unmeasured:
        return f"{label} — not yet checked"
    if score.weak:
        return f"{label} — confirmed short of where it should be"
    return f"{label} — confirmed in place"


def summarise(*, roadmap: Roadmap, readiness: Readiness,
              measurements: tuple[dict, ...] = ()) -> dict:
    """The strategy, as structure and as prose.

    Returns both: the structure is what a surface renders, and the prose is what
    somebody reads out on a call. They are generated from the same values, so
    they cannot say different things.
    """
    strong = [d for d in readiness.dimensions if d.strong]
    unmeasured = list(readiness.unmeasured)
    actionable = list(readiness.actionable)

    qevik_now = [t for t in roadmap.at(Horizon.DAY_7) + roadmap.at(Horizon.DAY_30)
                 if t.executability is Executability.QEVIK_CAN_EXECUTE]
    customer_now = [t for t in roadmap.tasks if t.is_customer]
    unbuildable = [t for t in roadmap.tasks
                   if t.executability is Executability.NO_CAPABILITY]

    # --- where you stand --------------------------------------------------
    lines: list[str] = []
    if roadmap.readiness_overall is not None:
        lines.append(f"Overall readiness: {roadmap.readiness_overall} out of 100, "
                     f"scored only from what was checked.")
    if strong:
        names = ", ".join(LABELS.get(d.dimension.value, d.dimension.value)
                          for d in strong)
        lines.append(f"Already in place, and nothing is proposed for it: {names}.")

    # --- what is worth doing ----------------------------------------------
    # Weaknesses and blind spots both, and capped separately. Merging them into
    # one ranked list and taking the top three buried every unmeasured dimension
    # behind the confirmed ones — so a customer never learned what had not been
    # looked at, which is the fact they are least able to discover themselves.
    priorities: list[dict] = []
    for score in actionable[:3]:
        priorities.append({
            "dimension": score.dimension.value, "state": "confirmed_weak",
            "description": _describe(score.dimension.value, score),
            "score": score.score, "confidence": score.confidence.value})
    for score in unmeasured[:2]:
        priorities.append({
            "dimension": score.dimension.value, "state": "unmeasured",
            "description": _describe(score.dimension.value, score),
            "score": None, "confidence": score.confidence.value})
    if priorities:
        lines.append("The biggest opportunities: "
                     + "; ".join(f"{i}. {p['description']}"
                                 for i, p in enumerate(priorities, 1)) + ".")

    # --- who does what ----------------------------------------------------
    if qevik_now:
        lines.append("Qevik can start on: "
                     + ", ".join(t.task.title for t in qevik_now) + ".")
    if customer_now:
        lines.append("Qevik needs from you: "
                     + ", ".join(t.task.action or t.task.title
                                 for t in customer_now) + ".")
    if unbuildable:
        lines.append("Worth doing, and Qevik has no capability for it yet: "
                     + ", ".join(t.task.title for t in unbuildable) + ".")

    # --- what happens next ------------------------------------------------
    metrics = sorted({t.metric_key for t in roadmap.tasks if t.metric_key})
    if metrics:
        readable = ", ".join(BY_KEY[m].label for m in metrics if m in BY_KEY)
        if readable:
            # "will be read again" rather than "will improve": a plan may say
            # what it intends to watch and may not say what watching will show.
            lines.append(f"Once something is published, a baseline is taken and "
                         f"these are read again: {readable}. The roadmap is then "
                         f"rebuilt from the new evidence.")
    for entry in measurements:
        lines.append(entry.get("statement", ""))

    prose = [vet(line, where="strategy") for line in lines if line]
    return {
        "business_id": roadmap.business_id,
        "readiness": roadmap.readiness_overall,
        "already_working": [d.dimension.value for d in strong],
        "priorities": priorities,
        "qevik_can_start": [{"task_id": t.id, "title": t.task.title,
                             "capability": t.capability_id} for t in qevik_now],
        "needs_from_you": [{"task_id": t.id, "title": t.task.title,
                            "do": t.task.action} for t in customer_now],
        "no_capability_yet": [{"title": t.task.title, "dimension": t.dimension}
                              for t in unbuildable],
        "will_be_measured": metrics,
        "measurements": list(measurements),
        "prose": prose,
    }
