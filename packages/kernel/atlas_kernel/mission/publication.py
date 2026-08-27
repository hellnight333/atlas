"""An authorised publication becoming a mission.

The third and last edge in the chain, and the only one that leaves the building.
`delivery.py` is its sibling and this deliberately reads like it: an approval
somebody gave, a recipe derived rather than requested, and a mission created
through the same three calls every other mission goes through.

## What makes this one different

Every earlier step was undoable. A sighting can be re-recorded, an opportunity
re-detected, an artefact rebuilt, a review superseded. A publication cannot: the
page was on the internet and somebody may have read it. `rollback` restores the
previous version and does not restore what a visitor already saw.

So the authorisation is its own decision, `PUBLICATION_EVENT`, and it names five
things — opportunity, mission, commit, site, and the person. The executing side
re-checks all five rather than trusting that the approval wrote them, for the
reason the delivery guard re-checks its own: a mission can sit in a queue while
the world changes underneath it.

## The address is derived, never asked for

`site_id` comes from the business id and nothing else. Not from the request, not
from the business *name*, and not from anything a model could influence:

* A caller that could name the directory could name `../../../etc`, and the only
  reliable defence against a path is not accepting one.
* A name changes. A slug derived from a name moves every published version of a
  site to a new address the first time somebody fixes a typo.

The result is validated anyway, because "derived" is an argument about the code
as it is today and the check is a property of the code as it will be.
"""

from __future__ import annotations

import logging
import re

from atlas_kernel.fabric import recipes

from . import origins, service
from .models import Mission, MissionStatus

log = logging.getLogger(__name__)


class NotPublishable(Exception):
    """This cannot become a publication mission, and why."""


#: Offer -> the recipe that publishes it. The only mapping there is, and the
#: same shape as `delivery.OFFER_RECIPES` for the same reason.
OFFER_RECIPES: dict[str, str] = {
    "offer-website": "publish-website",
}

#: A site id is a bare key: lowercase, digits, hyphens. No slashes, no dots, no
#: traversal, nothing a filesystem reads as a location.
SITE_ID = re.compile(r"^site-[a-z0-9-]{4,40}$")


def site_for(business_id: str) -> str:
    """The address this business's site lives at. Derived, then checked."""
    cleaned = re.sub(r"[^a-z0-9]+", "", (business_id or "").lower())
    if len(cleaned) < 4:
        raise NotPublishable(
            f"cannot derive a site address from business id {business_id!r}. A "
            "publication needs somewhere to go that nobody typed.")
    site = f"site-{cleaned[:16]}"
    if not SITE_ID.fullmatch(site):
        raise NotPublishable(f"{site!r} is not a usable site address")
    return site


def known(site_id: str, *, business_id: str) -> bool:
    """Whether this address is the one this business's artefacts publish to.

    The registry is the derivation. A site is *registered* precisely when it is
    the address `site_for` produces, which makes "publishing to an unregistered
    target" impossible to express rather than merely refused — there is no list
    to add an entry to.
    """
    try:
        return site_id == site_for(business_id)
    except NotPublishable:
        return False


def recipe_for(signal: dict) -> str:
    """The declared recipe that publishes this opportunity's artefact."""
    from . import delivery

    offer = delivery.offer_of(signal)
    if not offer:
        raise NotPublishable(
            f"{signal.get('id')} suggests no capability, so there is nothing "
            "declared to publish.")
    recipe_id = OFFER_RECIPES.get(offer)
    if recipe_id is None:
        raise NotPublishable(
            f"{offer!r} has no publication recipe. Known: "
            f"{', '.join(sorted(OFFER_RECIPES)) or 'none'}.")
    return recipe_id


def refusals(approval: dict, signal: dict, *, business_id: str) -> list[str]:
    """Every reason this authorisation may not become a mission."""
    reasons: list[str] = []
    if not approval:
        reasons.append(
            "nothing authorised this publication. An accepted artefact is not "
            "an instruction to publish it; somebody has to say so.")
        return reasons
    if not approval.get("commit"):
        reasons.append(
            "the authorisation names no commit, so it authorises whatever the "
            "branch holds when this runs.")
    if not known(approval.get("site_id", ""), business_id=business_id):
        reasons.append(
            f"{approval.get('site_id')!r} is not this business's site address. "
            "An address is derived from the business, never supplied.")
    if approval.get("signal_id") != signal.get("id"):
        reasons.append(
            f"the authorisation is for opportunity {approval.get('signal_id')} "
            f"and this names {signal.get('id')}.")
    try:
        recipe_for(signal)
    except NotPublishable as refused:
        reasons.append(str(refused))
    return reasons


def enqueue(approval: dict, signal: dict, *, tenant: str | None,
            origin: origins.Origin, actor: str,
            business_id: str) -> tuple[Mission, tuple[object, ...]]:
    """Create the publication mission for an authorised publication."""
    stop = refusals(approval, signal, business_id=business_id)
    if stop:
        raise NotPublishable(" ".join(stop))

    recipe = recipes.get(recipe_for(signal))
    source = approval["mission_id"]

    mission, created = service.create(
        tenant=tenant,
        title=f"Publish {approval['site_id']}",
        description=(f"{recipe.does}\n\nAuthorised by {actor} from "
                     f"{source} at commit {approval['commit'][:12]}."),
        requested_by=actor,
        origin_name=origin.name,
        recipe=recipe.id,
        signal_id=signal["id"],
        approved_scope=f"publish {approval['commit'][:12]} to "
                       f"{approval['site_id']}",
        evidence_fingerprints=tuple(signal.get("evidence_fingerprints") or ()),
        # The mission whose artefact this publishes. One field, because
        # everything else about the authorisation is re-read from the timeline
        # at execution — a mission that carried the commit could have it edited,
        # and then the record and the act would disagree.
        publishes=source)

    mission, planning = service.transition(
        mission, MissionStatus.PLANNING, tenant=tenant, actor=actor,
        note=f"publishing {source}")
    mission, attached = service.attach_plan(
        mission, plan_for(recipe, approval), tenant=tenant, actor=actor,
        agent_id=recipe.agent_id,
        modifies_qevik_itself=origin.modifies_qevik_itself)

    log.info("publication of %s at %s authorised by %s: %s in origin %s",
             source, approval["commit"][:12], actor, mission.id, origin.name)
    return mission, (created, planning, attached)


def plan_for(recipe, approval: dict):
    """The recipe, as the plan policy decides about."""
    from .models import Plan, PlanStep

    return Plan(
        goal=recipe.does,
        why=(f"publication of {approval['mission_id']} at "
             f"{approval['commit'][:12]}, authorised by a person"),
        steps=tuple(
            PlanStep(order=n, title=step.proves,
                     why=f"{step.tool}: {' '.join(step.command)}")
            for n, step in enumerate(recipe.steps, start=1)),
        test_plan="the public address is fetched afterwards and must serve the "
                  "published bytes",
        security_impact=("**This is outward.** The bundle becomes readable by "
                         "anyone with the address. It is served over Qevik's "
                         "own host under a Qevik address; no customer domain, "
                         "no DNS change, no mail. Rolling back restores the "
                         "previous version and does not un-read the page."),
        rollback="the previous version is kept and the address can be pointed "
                 "back at it",
        estimated_cost=0.0, cost_status="REPORTED",
        approval_required=True)


__all__ = ["OFFER_RECIPES", "SITE_ID", "NotPublishable", "enqueue", "known",
           "plan_for", "recipe_for", "refusals", "site_for"]
