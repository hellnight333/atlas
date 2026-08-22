"""What a customer is shown, and the gate every sentence of it passes.

Not a portal. A structured view a surface can render, kept here because the
constraint that matters is not visual: **a roadmap is written before anything
has been measured**, so nothing in it may imply a result. The same P1.4
attribution model that governs measurement copy governs this, at
`Attribution.UNKNOWN` — the level a plan is entitled to.

The gate runs at build time and raises. Returning an unvetted view and checking
it at the edge would mean the check lives in whichever surface remembered to
call it, and the one that forgets is the one that ships.

Answering, for a customer, in their order:

* where they stand, and how confident we are about it
* what should happen next, and why
* who has to do it
* what it is waiting on
* how anybody will know whether it worked
* what Qevik can actually perform, and what it cannot
"""

from __future__ import annotations

from ..measurement.attribution import Attribution, permits, refuse
from ..measurement.models import BY_KEY
from .lifecycle import TaskFacts, TaskState, blockers, state_of
from .models import Executability, Horizon, Roadmap, RoadmapTask

#: The level a plan speaks at. Nothing here has been measured, so nothing here
#: may assert a change, a sequence or a cause.
LEVEL = Attribution.UNKNOWN

#: How each executability reads to somebody who is not us. The wording is the
#: point: "we can do this" and "this is worth doing and we cannot" must not be
#: distinguishable only by a colour in a UI.
OWNERSHIP: dict[Executability, str] = {
    Executability.QEVIK_CAN_EXECUTE: "Qevik can do this",
    Executability.CUSTOMER_MUST_ACT: "only you can do this",
    Executability.NO_CAPABILITY: "worth doing — Qevik has no capability for it yet",
    Executability.MEASURE_FIRST: "nobody has measured this yet",
}


class Overclaim(Exception):
    """A sentence bound for a customer asserted more than a plan can support."""


def vet(sentence: str, *, where: str) -> str:
    """Return the sentence, or refuse to build the view containing it."""
    if sentence and not permits(LEVEL, sentence):
        raise Overclaim(f"{where}: {refuse(LEVEL, sentence)}")
    return sentence


def _measurement(task: RoadmapTask) -> dict:
    """How anyone would know, said without promising that they will."""
    metric = BY_KEY.get(task.metric_key)
    if not metric:
        return {"metric": "", "label": "", "note":
                "No metric is attached to this yet, so there is nothing to compare against."}
    return {
        "metric": task.metric_key,
        "label": metric.label,
        # Deliberately "would be watched", not "will improve". The difference is
        # the whole of P1.4 in one phrase.
        "note": f"{metric.label} is what would be watched. A baseline is taken "
                "before the work and read again after it.",
    }


def task_view(task: RoadmapTask, facts: TaskFacts) -> dict:
    """One task, as a customer sees it."""
    state = state_of(task, facts)
    waiting = blockers(task, facts)
    return {
        "id": task.id,
        "title": vet(task.task.title, where=f"{task.id} title"),
        "why": vet(task.why, where=f"{task.id} why"),
        "who": OWNERSHIP[task.executability],
        "kind": task.kind.value,
        "state": state.value,
        "horizon": task.horizon.value,
        "dimension": task.dimension,
        "action": task.task.action,
        "depends_on": list(task.depends_on),
        "blocked_by": list(waiting),
        "confidence": task.confidence,
        "evidence": list(task.evidence),
        "measurement": _measurement(task),
        "expected_outcome": vet(task.expected_outcome,
                                where=f"{task.id} expected outcome"),
        # Said plainly rather than left to be inferred from `who`. A customer
        # reading a plan assumes everything on it is going to happen.
        "qevik_will_execute": task.executability is Executability.QEVIK_CAN_EXECUTE,
        "needs_approval": task.requires_approval,
    }


def view(roadmap: Roadmap, *, facts: TaskFacts | None = None,
         confidence: str = "") -> dict:
    """The whole plan, as a customer sees it.

    `facts` defaults to knowing nothing, which is the honest starting position
    for a plan nobody has acted on yet: every task reads as proposed rather than
    ready, and nothing is described as under way.
    """
    facts = facts or TaskFacts()
    tasks = [task_view(t, facts) for t in roadmap.tasks]
    by_state: dict[str, list[str]] = {}
    for entry in tasks:
        by_state.setdefault(entry["state"], []).append(entry["id"])

    return {
        "business_id": roadmap.business_id,
        # --- where they stand -------------------------------------------
        "readiness": {
            "overall": roadmap.readiness_overall,
            "confidence": confidence or "MEDIUM",
            "note": "Scored only from what was checked. Anything unchecked "
                    "lowers the confidence rather than the score.",
            "working_already": list(roadmap.left_alone),
            "working_already_note":
                "Nothing is proposed for these. They were checked and found in place.",
        },
        # --- what happens next ------------------------------------------
        "next": [t for t in tasks if t["horizon"] == Horizon.DAY_7.value],
        "horizons": {h.value: [t for t in tasks if t["horizon"] == h.value]
                     for h in Horizon},
        # --- who does what ----------------------------------------------
        "qevik_can_execute": [t for t in tasks if t["qevik_will_execute"]],
        "your_tasks": [t for t in tasks if t["kind"] == "customer_task"],
        "no_capability": [t for t in tasks
                          if t["who"] == OWNERSHIP[Executability.NO_CAPABILITY]],
        "not_yet_measured": [t for t in tasks
                             if t["who"] == OWNERSHIP[Executability.MEASURE_FIRST]],
        "blocked": [t for t in tasks if t["state"] == TaskState.BLOCKED.value],
        "by_state": by_state,
        "generated_at": roadmap.generated_at,
    }
