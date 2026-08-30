"""An approved opportunity becoming a mission.

The one edge that did not exist. Qevik could discover a business, fetch its
site, audit what came back and rank what that supported saying — and a person
approving the result changed nothing, because `atlas_signals` was read by the
console and by nobody else.

## A signal is not a mission

It never becomes one. This creates a mission that **references** the signal, the
same way `recurrence.enqueue` creates one that references an occurrence, and
through the same three calls: `service.create`, a transition to PLANNING, then
`service.attach_plan`, which runs `policy.decide`. A delivery cannot reach the
queue by any route a person's own request could not.

## What the approval decides, and what it does not

The approval decides **that** the work happens. It does not decide what the work
is: the recipe comes from `OFFER_RECIPES`, keyed by the capability the signal's
own suggested action named, and there is no parameter anywhere on this path that
lets a caller ask for a different one. A model may propose approving opportunity
`sig-123`; it cannot propose that `sig-123` be delivered by something else.

That is why `enqueue` takes a **signal id** and reads the signal itself rather
than accepting a signal-shaped argument. A caller that could pass the record
could pass one it had edited.

## Where this deliberately stops

At an artefact in a scratch workspace and a report. Publishing it and telling
the business about it are separate outward acts, and neither is reachable from
here: the `website-builder` agent declares one tool, `website-generator`, so a
recipe on this path that named an HTTP or shell step would be refused at import
by `recipes.validate` rather than at three in the morning by a firewall.
"""

from __future__ import annotations

import logging

from atlas_kernel.fabric import recipes
from atlas_kernel.opportunity.models import FindingKind

from . import origins, service
from .models import Mission, MissionStatus

log = logging.getLogger(__name__)


class NotDeliverable(Exception):
    """This opportunity cannot become a mission, and why."""


#: Offer -> the recipe that delivers it. The only mapping there is.
#:
#: A key on both sides. The offer is what the opportunity's suggested action
#: named, and the recipe is what `fabric.recipes` declares — so adding a
#: deliverable offer is a reviewed change in git and not a string somebody
#: passed to an endpoint.
OFFER_RECIPES: dict[str, str] = {
    "offer-website": "deliver-website",
    "offer-health-check": "deliver-health-check",
}

#: Audited defect -> the fix `execution/capabilities/website.py` declares.
#:
#: Its `FIXES` table is the authority for what a build can actually address;
#: this says which observed defect is which entry in it. Deliberately a
#: different question from `detect.ANSWERED_BY`, which says whether an *offer*
#: claims to answer a defect at all — an offer can honestly answer something no
#: executor can build yet, and collapsing the two would hide exactly that.
BUILDABLE: dict[FindingKind, str] = {
    FindingKind.MISSING_TITLE: "page_title",
    FindingKind.MISSING_META_DESCRIPTION: "meta_description",
    FindingKind.MISSING_H1: "h1",
    FindingKind.NOT_MOBILE_FRIENDLY: "viewport_meta",
    FindingKind.THIN_CONTENT: "thin_pages",
    FindingKind.SLOW_RESPONSE: "page_speed",
}

#: Defects the website audit can produce that no build addresses, and why.
#:
#: Written down rather than left as the absence of a `BUILDABLE` entry, because
#: an absence says nothing about whether somebody thought about it. A test
#: checks every kind the audit can raise appears in exactly one of the two.
NOT_BUILDABLE: dict[FindingKind, str] = {
    FindingKind.SITE_UNREACHABLE:
        "a homepage that 404s or errors is a real problem and `FIXES` has no "
        "entry for it — `broken_links` is about links within a site. The offer "
        "honestly answers `broken`; nothing can build the answer yet.",
    FindingKind.NO_HTTPS:
        "a certificate is a hosting decision, not a file in the artefact.",
    FindingKind.NO_STRUCTURED_DATA:
        "worth adding and not in `FIXES`, so no build declares it.",
    FindingKind.TLS_INVALID:
        "the same as NO_HTTPS: nothing in a generated site changes it.",
}


def offer_of(signal: dict) -> str:
    """The capability this opportunity's own suggested action named.

    Read from the stored signal, not from anything a caller supplies. The
    action was written by a deterministic detector out of evidence, and it is
    the only thing on this path that gets to say what the work would be.
    """
    actions = (signal.get("detail") or {}).get("actions") or []
    return (actions[0] or {}).get("capability", "") if actions else ""


def recipe_for(signal: dict) -> str:
    """The declared recipe that delivers this opportunity, or a refusal."""
    offer = offer_of(signal)
    if not offer:
        raise NotDeliverable(
            f"{signal.get('id')} suggests no capability, so there is nothing "
            "declared to carry it out.")
    recipe_id = OFFER_RECIPES.get(offer)
    if recipe_id is None:
        raise NotDeliverable(
            f"{offer!r} has no delivery recipe. Known: "
            f"{', '.join(sorted(OFFER_RECIPES)) or 'none'}. An offer with no "
            "recipe is work Qevik cannot carry out, and saying so is better "
            "than routing it to the nearest one.")
    return recipe_id


def refusals(signal: dict) -> list[str]:
    """Every reason this opportunity may not become a mission, before it does.

    Checked here as well as by the surface that asked, because the surface's
    check answers a typo immediately and this one is what protects execution.
    """
    reasons: list[str] = []
    if signal.get("state") != "approved":
        reasons.append(
            f"{signal.get('id')} is {signal.get('state')!r}. Only an approved "
            "opportunity becomes a mission — approval is what authorises the "
            "work, and a mission created without it would be work nobody "
            "agreed to, carrying a reference implying somebody had.")
    if not signal.get("needs_approval"):
        reasons.append(
            "this opportunity's actions stay inside Qevik, so there is no "
            "outward work here to deliver.")
    if not signal.get("business_id"):
        reasons.append(
            "no business — a delivery is for somebody, and an artefact built "
            "for nobody cannot be reviewed or sent.")
    try:
        recipe_for(signal)
    except NotDeliverable as refused:
        reasons.append(str(refused))
    return reasons


def scope_of(signal: dict) -> str:
    """What was approved, in the offer's own vocabulary.

    Taken from the action's statement where the detector named the keys, so the
    mission records the scope in the words the approver read rather than in a
    re-derivation that could differ from them.
    """
    from atlas_kernel.opportunity import detect

    offer = offer_of(signal)
    statement = ((signal.get("detail") or {}).get("actions") or [{}])[0].get(
        "statement", "")
    named = [key for key in sorted(set(detect.ANSWERED_BY.values()))
             if key in statement]
    return f"{offer}: {', '.join(named)}" if named else offer


def enqueue(signal: dict, *, tenant: str | None, origin: origins.Origin,
            actor: str) -> tuple[Mission, tuple[object, ...]]:
    """Create the delivery mission for an approved opportunity.

    Returns the mission and the events to persist, exactly as
    `recurrence.enqueue` does — the caller owns the timeline, and a function
    that wrote to it would be a second way missions come into being.

    `origin` is resolved by the caller for the same reason it is there: the
    caller owns the registry, and whether a person is asked comes from the
    origin the worker will actually use rather than from a field this could
    have set to anything.
    """
    stop = refusals(signal)
    if stop:
        raise NotDeliverable(" ".join(stop))

    signal_id = signal["id"]
    recipe_id = recipe_for(signal)
    recipe = recipes.get(recipe_id)          # refuses an undeclared name

    business = signal.get("scope") or signal.get("business_id")
    # Everything the approval decided, written at creation and never
    # recomputed. The recipe among them: it was derived from the opportunity's
    # own suggested action a few lines above, and nothing downstream may look
    # it up again from anywhere else.
    mission, created = service.create(
        tenant=tenant,
        title=f"Deliver {recipe.id} for {business}",
        description=(f"{recipe.does}\n\nApproved from opportunity "
                     f"{signal_id} by {actor}."),
        requested_by=actor,
        origin_name=origin.name,
        recipe=recipe.id,
        signal_id=signal_id,
        approved_scope=scope_of(signal),
        evidence_fingerprints=tuple(signal.get("evidence_fingerprints") or ()))

    # DRAFT -> PLANNING -> (QUEUED | AWAITING_APPROVAL). The same three steps a
    # person's own request takes, through the same functions: `ALLOWED` refuses
    # draft -> queued outright, and a delivery does not get a shortcut through
    # the state machine because somebody already said yes to the opportunity.
    mission, planning = service.transition(
        mission, MissionStatus.PLANNING, tenant=tenant, actor=actor,
        note=f"delivering {signal_id}")
    mission, attached = service.attach_plan(
        mission, plan_for(recipe, signal), tenant=tenant, actor=actor,
        agent_id=recipe.agent_id,
        modifies_qevik_itself=origin.modifies_qevik_itself)

    log.info("opportunity %s approved by %s: %s as %s in origin %s",
             signal_id, actor, mission.id, recipe.id, origin.name)
    return mission, (created, planning, attached)


def plan_for(recipe, signal: dict):
    """The recipe, as the plan a policy decision is made about.

    Nothing is generated. The steps were approved when the recipe was merged
    and the work was approved when the opportunity was; this states both so the
    decision is made about what will actually run.
    """
    from .models import Plan, PlanStep

    return Plan(
        goal=recipe.does,
        why=(f"opportunity {signal['id']} — {scope_of(signal)}, approved by a "
             "person"),
        steps=tuple(
            PlanStep(order=n, title=step.proves,
                     why=f"{step.tool}: {' '.join(step.command)}")
            for n, step in enumerate(recipe.steps, start=1)),
        test_plan="the artefact is written to the scratch workspace and listed "
                  "in the report",
        security_impact=("Writes files into this mission's scratch workspace "
                         "and nothing else. Publishes nothing and contacts "
                         "nobody: the delivering agent declares one tool and it "
                         "is not a network tool."),
        rollback="the artefact is a file in a scratch workspace; deleting it "
                 "undoes the whole delivery",
        estimated_cost=0.0, cost_status="REPORTED",
        approval_required=False)


__all__ = ["BUILDABLE", "NOT_BUILDABLE", "OFFER_RECIPES", "NotDeliverable",
           "enqueue", "offer_of", "plan_for", "recipe_for", "refusals",
           "scope_of"]
