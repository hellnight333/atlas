"""The sales workspace's read API: prospects, evidence, and what may be said.

Every route here is a *view over the existing timeline*. There is no prospect
table, no lead table, no pipeline column and no status field — a business's
state is folded from its `BusinessEvent`s on each request, because a funnel
computed from a stored status cannot tell you that somebody replied, took a
meeting and then went quiet. Only the sequence can, and only while nothing
overwrites it.

Three properties this layer exists to preserve, all of which are easy to lose
the moment a UI is put in front of the data:

**Three states, never two.** `CONFIRMED_PRESENT`, `CONFIRMED_ABSENT` and
`NOT_VERIFIED` reach the browser as three distinct values. A dashboard that
renders "not verified" as a red cross has invented a finding, and the operator
will then say it out loud to a business owner who knows better.

**A refuted finding is shown as refuted, not deleted and not current.** The
audit said three prospects had no HTTPS; they all do. Both readings stay on the
record, and the UI shows the correction rather than quietly serving the newer
one — that failure has already happened here once.

**Nothing in this module can send.** It is read-only apart from two explicitly
human-triggered records (marking a message sent, logging a reply), and it
imports no client of any kind. The WhatsApp affordance is a `wa.me` link the
operator's own phone opens; there is no API call behind it.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from ..auth import Scope, User, requires
from ..outreach import consistency, demos, offer, opportunity, scoring

#: Where `capture_evidence.py` writes screenshots. Served through this API
#: rather than by the web server: the console's CSP is `img-src 'self'`, and
#: prospect evidence must not become a publicly reachable directory.
EVIDENCE = Path("/var/lib/qevik/evidence")

#: Older than this and a finding is not safe to repeat to a business without
#: looking again. Sites get fixed; the drift is one-directional.
STALE_AFTER_HOURS = 72

#: How the audit's feature names read to a person selling.
LABEL = {
    "https": "HTTPS", "arabic": "Arabic version", "click_to_call": "Tap-to-call number",
    "whatsapp": "WhatsApp button", "google_maps": "Map link", "opening_hours": "Opening hours",
    "contact_form": "Contact form", "structured_data": "Structured data",
    "services_navigation": "Services pages", "h1": "Main heading",
    "meta_description": "Meta description", "image_alt_text": "Image alt text",
    "page_title": "Page title", "viewport_meta": "Mobile viewport",
    "booking_link": "Online booking", "insurance_info": "Insurance information",
    "emergency_info": "Emergency information", "doctors_team": "Team profiles",
    "social_proof": "Reviews", "page_weight": "Page weight",
    "slow_homepage": "Homepage load time", "site_loads": "Site reachable",
}

#: What fixing each one is worth to the business, in a sentence.
IMPACT = {
    "https": "Browsers label the site “Not secure” to every visitor.",
    "arabic": "Arabic-speaking customers have no Arabic experience, and Google has no Arabic text to match them against.",
    "click_to_call": "On a phone the number cannot be tapped; it has to be copied out by hand.",
    "whatsapp": "The channel most customers here prefer is not offered.",
    "google_maps": "Someone has to search the address separately to find it.",
    "opening_hours": "Visitors cannot tell whether they are open right now.",
    "contact_form": "There is no way to make contact without already having the number.",
    "structured_data": "Google has to guess what kind of business this is.",
    "services_navigation": "Services are not separately reachable, so they cannot rank separately.",
    "h1": "The page has no main heading, which is the first thing Google reads.",
    "meta_description": "Google writes its own summary of the business in search results.",
    "image_alt_text": "Search engines cannot tell what any of the images show.",
    "page_title": "The tab and the search result carry no useful title.",
    "viewport_meta": "The page is not told to adapt to a phone screen.",
    "slow_homepage": "Visitors wait on a blank screen, and many leave before it renders.",
}

#: What Qevik has actually shipped for each. Only these may be offered — the
#: set mirrors `scoring.FIXABLE`, and a feature outside it is displayed as
#: their problem and explicitly marked unsayable.
REMEDY = {
    "https": "Serve the site over HTTPS and redirect the insecure version to it.",
    "arabic": "An authored Arabic RTL version with its own canonical and reciprocal hreflang.",
    "click_to_call": "A tap-to-call number in the header and a persistent mobile action bar.",
    "whatsapp": "A WhatsApp button that opens a conversation with a prefilled message.",
    "google_maps": "A map link and embedded directions.",
    "opening_hours": "Opening hours on the page and in structured data, including a today marker.",
    "contact_form": "An enquiry form — clearly labelled as not connected until a provider is chosen.",
    "structured_data": "LocalBusiness structured data so search engines read the details directly.",
    "services_navigation": "A separately addressable page per service.",
    "h1": "A single descriptive main heading.",
    "meta_description": "An authored description per page.",
    "image_alt_text": "Alt text on every content image.",
    "page_title": "A unique title per page.",
    "viewport_meta": "A responsive layout built mobile-first.",
}

#: The nav's industry groups, mapped onto the categories the discovery wrote and
#: onto the finer ones an evidenced `business_classified` event can introduce.
#: A category with no entry here reads as "Other", which is how a recruitment
#: agency ended up labelled "Other · Dubai · recruitment" on its own page.
INDUSTRY = {
    "food": "Food & Drink", "cafe": "Food & Drink",
    "beauty": "Health & Beauty", "health": "Health & Beauty", "dental": "Health & Beauty",
    "home": "Home Services", "automotive": "Automotive",
    "professional": "Professional Services",
    "recruitment": "Recruitment & Staffing", "staffing": "Recruitment & Staffing",
    "hospitality": "Hospitality", "retail": "Retail",
    "real_estate": "Real Estate", "property": "Real Estate",
    "fitness": "Fitness", "technology": "Technology", "ai": "Technology",
    "education": "Education", "games": "Games",
}

_FIXTURE_HOST = re.compile(r"-[0-9a-f]{8,}\.(ae|com)\b|(^|\.)example\.|(^|\.)test\.")
_MOBILE = scoring._MOBILE
_TOLL_FREE = scoring._TOLL_FREE

#: Standing rules, shown on every prospect. The per-prospect entries are derived
#: from that prospect's own evidence and appended to these.
STANDING_DO_NOT_SAY = [
    "Do not call Qevik a licensed company — it is a brand of Asia Link Internet Content Provider LLC.",
    "Do not call a Qevik sample “client work”. Qevik has no customers yet.",
    "Do not promise appointment booking. There is no booking backend.",
    "Do not invent testimonials, awards, reviews, staff or results.",
    "Do not say a website is broken when it merely loaded slowly.",
]


def _detail(raw: Any) -> dict:
    return raw if isinstance(raw, dict) else json.loads(raw or "{}")


def _observations(audit: dict) -> list[dict]:
    return audit.get("observations") or audit.get("findings") or []


def _hours_since(when: datetime | None) -> float | None:
    if not when:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return (datetime.now(UTC) - when).total_seconds() / 3600


def _age(hours: float | None) -> str:
    if hours is None:
        return "never"
    if hours < 1:
        return f"{round(hours * 60)} minutes ago"
    if hours < 24:
        return f"{round(hours)} hours ago"
    days = round(hours / 24)
    return "yesterday" if days == 1 else f"{days} days ago"


def contactability(phone: str, email: str) -> dict:
    """How this business can be reached — and whether WhatsApp is one of them.

    A landline gets no WhatsApp affordance at all. Offering one produces a
    message that silently goes nowhere, which is worse than an error, and it is
    the same fault the generated sites refuse to reproduce.
    """
    number = scoring.digits(phone)
    if number and _MOBILE.match(number):
        return {"kind": "mobile", "whatsapp": "REACHABLE", "channel": "WHATSAPP",
                "wa_link": f"https://wa.me/{number if number.startswith('971') else '971' + number.lstrip('0')}",
                "why": "UAE mobile — WhatsApp reaches a person who can decide."}
    if number and _TOLL_FREE.match(number):
        return {"kind": "toll_free", "whatsapp": "CONFIRMED_ABSENT", "channel": "PHONE",
                "wa_link": "", "why": "Toll-free number — reaches a call centre, not an owner."}
    if number:
        return {"kind": "landline", "whatsapp": "CONFIRMED_ABSENT", "channel": "PHONE",
                "wa_link": "", "why": "Landline — a call, probably through reception."}
    if email:
        return {"kind": "email", "whatsapp": "NOT_VERIFIED", "channel": "EMAIL",
                "wa_link": "", "why": "No phone on the listing; email only."}
    return {"kind": "none", "whatsapp": "NOT_VERIFIED", "channel": "NONE",
            "wa_link": "", "why": "No contact method on the listing."}


class SentRecord(BaseModel):
    """A human confirming they sent something, by hand, at a real time."""

    channel: str = Field(min_length=2, max_length=20)
    sent_at: datetime
    message_version: str = ""
    note: str = Field(default="", max_length=2000)


class ReplyRecord(BaseModel):
    response: str = Field(min_length=2, max_length=40)
    verbatim: str = Field(default="", max_length=4000)
    objection: str = Field(default="", max_length=400)


def _demo_view(folded: dict) -> dict:
    """The demo, its wording and its justification — all from one Selection.

    Everything a message could say about the demo is read from here, so the
    URL in the message and the URL on the card cannot come apart.
    """
    chosen: demos.Selection = folded["chosen"]
    leads = demos.leadable(chosen, folded["score"].speakable)
    strongest = leads[0] if leads else ""
    return {
        "url": chosen.url,
        "slug": chosen.demo.slug if chosen.demo else "",
        "name": chosen.demo.name if chosen.demo else "",
        "industry": chosen.demo.industry if chosen.demo else "",
        "trade": chosen.demo.trade if chosen.demo else "",
        "shows": chosen.demo.shows if chosen.demo else "",
        "kind": chosen.kind,
        "matched": chosen.matched,
        "label": chosen.label,
        "bilingual": chosen.bilingual,
        "why": demos.relevance(chosen, folded["category"], strongest),
        "product_type": chosen.demo.product_type if chosen.demo else "Website",
        "business_class": chosen.demo.business_class if chosen.demo else "",
        "primary": chosen.demo.primary if chosen.demo else "",
        "secondary": list(chosen.demo.secondary) if chosen.demo else [],
        "proves": chosen.demo.proves if chosen.demo else "",
        "does_not_prove": chosen.demo.does_not_prove if chosen.demo else "",
    }


#: The build lifecycle. "Done" is not one of them — a build is READY only once
#: its QA has run, and READY is the only state outreach may reference.
#:
#: The middle states name what is actually happening, because "running" for
#: forty minutes tells an operator nothing while "MEDIA" tells them what it is
#: waiting on. CANCELLED is terminal and kept deliberately: one real job is in
#: it, and a vocabulary that cannot express the state a record is already in
#: would force either a rewrite of history or a job displayed as something it
#: is not.
JOB_STATES = ("QUEUED", "RESEARCHING", "DESIGNING", "BUILDING", "MEDIA", "QA",
              "REVIEW", "READY", "FAILED", "CANCELLED")

#: Nothing further happens from here.
TERMINAL_JOB_STATES = frozenset({"READY", "FAILED", "CANCELLED"})

#: What an operator can ask to have built. Checking a box requests nothing; a
#: build starts on an explicit action and never as a side effect of ticking.
#:
#: Derived, not typed out. The first version was a hand-written list beside the
#: opportunity vocabulary, and the two disagreed immediately: the interface sent
#: an opportunity's name — "Proof system" — while this list held a different
#: label, so six of eight buildable opportunities came back "unknown product".
#: Two lists keyed on the same thing always drift; this one cannot.
NATIVE = ("Android app", "iOS app", "PWA / mobile web app")
PRODUCTS = tuple(sorted(opportunity.PRODUCTS | set(NATIVE)))

#: What the customer has actually agreed to, in ascending order.
#:
#: `permission_pending` earns its place by being the state everything else
#: collapses into wrongly: "we asked and they have not answered" is not "no
#: permission", and an operator chasing a reply needs to see the difference. The
#: existing four keep their names — they are written into production event
#: history, and renaming them would buy tidiness at the cost of a migration.
MEDIA_PERMISSION = ("none", "permission_pending", "use_originals", "edit_enhance",
                    "generate_matching")

#: Only these allow a customer's own photographs anywhere near a build.
MEDIA_ALLOWS_ORIGINALS = frozenset({"use_originals", "edit_enhance", "generate_matching"})


log = logging.getLogger(__name__)


def _safe(name: str, produce, fallback, *, business_id: str, warnings: list[dict]):
    """Run one presentation block; degrade it rather than the whole page.

    The prospect page went to 500 for every prospect because one helper raised a
    NameError. A page that cannot show a build queue should still show who the
    business is, what the evidence says and how to reach them — the operator
    loses a panel, not the customer.

    Nothing is swallowed: the traceback is logged with the business id, and the
    response carries a warning the interface displays. A block that is quietly
    empty is worse than one that is visibly broken.
    """
    try:
        return produce()
    except Exception:                      # noqa: BLE001 - deliberately broad
        log.exception("sales: %s failed for business %s", name, business_id)
        warnings.append({"block": name,
                         "message": "Could not be built for this prospect. "
                                    "The error is in the server log."})
        return fallback


def _digital(findings: list[dict], *, category: str, website: str) -> list[dict]:
    """The products this business is missing, ranked, each citing its evidence.

    Deliberately separate from the audit findings above it. A finding is "your
    phone is not a link"; this is "you have thirty-two event pages nobody can
    find". Only CONFIRMED_ABSENT features are passed in — an unverified feature
    is a gap in our checking, and pitching against it would be pitching against
    our own blind spot.
    """
    absent = frozenset(f["feature"] for f in findings if f["state"] == "CONFIRMED_ABSENT")
    present = frozenset(f["feature"] for f in findings if f["state"] == "CONFIRMED_PRESENT")
    host = re.sub(r"^https?://(www\.)?", "", website).split("/")[0]
    return [
        {"key": o.key, "name": o.name, "product": o.product, "family": o.family,
         "priority": o.priority, "confidence": o.confidence, "evidence": list(o.evidence),
         "why": o.why, "builds": o.builds, "user": o.user, "interaction": o.interaction,
         "value": o.value, "demo": o.demo or ""}
        for o in opportunity.for_host(host, category=category,
                                      absent=absent, present=present)
    ]


class MediaPermission(BaseModel):
    permission: str
    source: str = ""     #: WhatsApp / Email / Call / Other — where they said it
    note: str = ""


class BuildRequest(BaseModel):
    product: str
    brief: str = ""
    opportunity: str = ""   #: the opportunity key this build answers


#: What the console needs to show a research run honestly. A run that partly
#: failed must look different from one that found nothing, which is the whole
#: reason the stage states are carried through rather than summarised away.
def _research_view(folded: dict) -> dict:
    research = folded.get("research") or {}
    if not research:
        return {"state": "NONE",
                "summary": "This business has not been researched yet.",
                "stages": {}, "facts": {}}
    stages = research.get("stages") or {}
    failed = [name for name, s in stages.items() if s.get("state") == "failed"]
    state = research.get("state", "NOT_VERIFIED")
    summary = {
        "READY": "Every stage ran.",
        "PARTIAL": f"{len(stages) - len(failed)} of {len(stages)} stages ran; "
                   f"{', '.join(failed)} did not.",
        "FAILED": "The site could not be reached, so nothing about it is established.",
    }.get(state, "Research state unknown.")
    facts = research.get("facts") or {}
    return {
        "state": state, "summary": summary, "at": research.get("at", ""),
        "website": research.get("website", ""),
        "stages": stages, "failed": failed,
        "speed": (facts.get("technical") or {}).get("speed_class", "NOT_VERIFIED"),
        "model": (facts.get("classify") or {}).get("model", "NOT_VERIFIED"),
        "position": (facts.get("position") or {}).get("grade", "NOT_VERIFIED"),
        "position_reasons": (facts.get("position") or {}).get("reasons", []),
        "journey_break": (facts.get("journey") or {}).get("first_break", ""),
        "pages": (facts.get("cms") or {}).get("pages"),
        "posts": (facts.get("cms") or {}).get("posts"),
        "media": (facts.get("cms") or {}).get("media_total"),
        "orphans": (facts.get("seo") or {}).get("orphan_count"),
        "crawled": (facts.get("crawl") or {}).get("ok"),
        "stopped_because": (facts.get("crawl") or {}).get("stopped_because", ""),
    }


def build_router() -> APIRouter:  # noqa: C901 - one cohesive read model
    router = APIRouter(prefix="/control/sales", tags=["sales"])

    # ---------------------------------------------------------------- data

    def _rows() -> tuple[dict, dict]:
        """Businesses, and every event that matters, in one pass.

        Two queries for the whole workspace rather than one per prospect. With
        several hundred businesses the per-row version is the difference between
        a page that opens and a page somebody stops using.
        """
        from sqlalchemy import text

        from ..db import SessionLocal

        with SessionLocal() as session:
            businesses = {
                row[0]: {"id": row[0], "name": row[1], "website": row[2] or "",
                         "email": row[3] or "", "phone": row[4] or "",
                         "geography": row[5] or "", "sources": row[6] or []}
                for row in session.execute(text(
                    "select id, name, website, email, phone, geography, sources "
                    "from atlas_businesses"))
            }
            events: dict[str, list[tuple[str, str, datetime, dict]]] = {}
            for business_id, factory, kind, at, detail in session.execute(text(
                "select business_id, factory, kind, at, detail from atlas_business_events "
                "order by at")):
                events.setdefault(business_id, []).append((factory, kind, at, _detail(detail)))

            messages: dict[str, list[dict]] = {}
            for row in session.execute(text(
                "select business_id, channel, status, recipient, subject, body, "
                "created_at, sent_at, provider_message_id "
                "from atlas_outreach_messages order by created_at")):
                messages.setdefault(row[0], []).append({
                    "channel": row[1], "status": row[2], "recipient": row[3] or "",
                    "subject": row[4] or "", "body": row[5] or "",
                    "created_at": row[6], "sent_at": row[7],
                    "provider_message_id": row[8] or "",
                })
        return businesses, (events, messages)

    def _fold(business: dict, events: list, messages: list) -> dict | None:
        """One business's whole state, derived — never stored."""
        audit: dict = {}
        audits = 0
        audited_at = None
        verified: dict[str, str] = {}
        verified_at = None
        live: dict = {}
        demo = ""
        classified = ""
        shots: dict = {}
        shots_at = None
        drafts: list[dict] = []
        timeline: list[dict] = []
        sent: list[dict] = []
        replies: list[dict] = []
        media: dict = {"permission": "none", "source": "", "at": "", "note": ""}
        builds: dict[str, dict] = {}
        research: dict = {}

        for factory, kind, at, detail in events:
            if kind == "researched":
                # Latest run wins for presentation; the observations are merged
                # into the audit below so a partial run adds evidence rather
                # than replacing what a fuller run established.
                research = {**detail, "at": at.isoformat() if at else ""}
            elif kind == "media_permission_recorded":
                # Latest wins: permission is a current fact, and a customer who
                # revokes must not be overridden by the earlier grant. The
                # timeline keeps the history.
                media = {"permission": detail.get("permission", "none"),
                         "source": detail.get("source", ""),
                         "note": detail.get("note", ""),
                         "at": at.isoformat() if at else ""}
            elif kind == "product_build_requested":
                builds[detail["job_id"]] = {
                    "job_id": detail["job_id"], "product": detail["product"],
                    "state": "QUEUED", "brief": detail.get("brief", ""),
                    "created": at.isoformat() if at else "", "started": "", "finished": "",
                    "output": "", "error": "", "screenshots": 0, "qa": "",
                    "requested_by": detail.get("actor", "")}
            elif kind == "product_build_progressed":
                job = builds.get(detail.get("job_id"))
                if job:
                    job.update({k: v for k, v in detail.items() if k in job and k != "job_id"})
            elif kind == "website_audited":
                audit, audits, audited_at = detail, audits + 1, at
            elif kind == "claims_verified":
                # Merged, never replaced: a later run only re-tests what is
                # still flagged, so the newest event is not the whole truth.
                verified.update({c["feature"]: c["verdict"] for c in detail.get("claims", [])})
                live, verified_at = detail, at
            elif kind == "website_demo_published":
                demo = detail.get("demo_url", "")
            elif kind == "business_classified":
                classified = detail.get("category", "")
            elif kind == "screenshot_captured":
                shots, shots_at = detail.get("shots", {}), at
            elif kind == "experiment_prepared":
                drafts.append({**detail, "at": at})
            elif kind == "experiment_sent":
                sent.append({**detail, "at": at})
            elif kind == "experiment_response":
                replies.append({**detail, "at": at})
            if kind in {"business_discovered", "website_audited", "claims_verified",
                        "website_demo_published", "screenshot_captured", "outreach_drafted",
                        "experiment_prepared", "experiment_sent", "experiment_response",
                        "experiment_objection", "experiment_outcome", "prospect_scored"}:
                timeline.append({"kind": kind, "factory": factory, "at": at.isoformat(),
                                 "actor": detail.get("actor", ""), "detail": detail})

        if not audit:
            return None
        # An explicit, evidenced classification beats the discovery query's
        # guess. 360 Agency was filed under "professional" because that is the
        # bucket it was found in; its own homepage says it is a hospitality
        # recruitment agency, which is a different product entirely.
        category = classified or audit.get("category") or ("dental" if demo else "")

        merged = dict(audit)
        if verified:
            merged = scoring.apply_verification(
                {**audit, "live_load_ms": live.get("load_ms"),
                 "live_http_status": live.get("http_status")},
                verified,
            )

        chosen = demos.select(
            category,
            prospect_demo_url=demo,
            weaknesses=tuple(
                f["feature"] for f in _observations(merged) if f.get("status") == "not_found"
            ),
        )
        if research.get("observations"):
            merged = dict(merged)
            by_feature = {o["feature"]: o for o in _observations(merged)}
            for observation in research["observations"]:
                current = by_feature.get(observation["feature"])
                # A crawl-wide confirmation outranks a homepage guess; an
                # unverified reading never displaces a confirmed one.
                if current and observation["status"] == "unverified" \
                        and current.get("status") != "unverified":
                    continue
                by_feature[observation["feature"]] = observation
            merged["observations"] = list(by_feature.values())

        score = scoring.score(
            business_id=business["id"], name=business["name"], website=business["website"],
            phone=business["phone"], email=business["email"], category=category,
            audit=merged, audit_count=audits, demo_url=demo,
            sample_slug=(chosen.demo.slug if chosen.demo else ""),
        )

        fresh_hours = _hours_since(verified_at or audited_at)
        return {
            "business": business, "category": category, "score": score,
            "audit": merged, "raw_audit": audit, "verified": verified, "live": live,
            "audited_at": audited_at, "verified_at": verified_at,
            "demo": demo, "chosen": chosen, "shots": shots, "shots_at": shots_at,
            "drafts": drafts, "messages": messages, "sent": sent, "replies": replies,
            "media": media, "builds": builds, "research": research,
            "timeline": timeline, "fresh_hours": fresh_hours,
            "stale": fresh_hours is None or fresh_hours > STALE_AFTER_HOURS,
        }

    def _all() -> list[dict]:
        businesses, (events, messages) = _rows()
        out = []
        for business_id, business in businesses.items():
            if _FIXTURE_HOST.search(business["website"]):
                continue
            folded = _fold(business, events.get(business_id, []), messages.get(business_id, []))
            if folded:
                out.append(folded)
        return sorted(out, key=lambda f: -f["score"].total)

    # ------------------------------------------------------------- shaping

    def _stage(folded: dict) -> str:
        """Where this prospect is, folded from events. Never a stored column.

        NOT_CONTACTED and NO_REPLY are different states and are kept apart:
        silence is not rejection, and a draft existing is not a send.
        """
        if any(r.get("result") == "won" for r in folded["replies"]):
            return "WON"
        if folded["replies"]:
            return "REPLIED"
        if folded["sent"]:
            return "SENT"
        approved = [m for m in folded["messages"] if m["status"] == "approved"]
        if approved:
            return "APPROVED"
        if folded["drafts"] or folded["messages"]:
            return "DRAFT"
        return "NOT_CONTACTED"

    def _findings(folded: dict) -> list[dict]:
        """Every observation, in its true state, with what it means and costs."""
        out = []
        for finding in _observations(folded["audit"]):
            feature = finding.get("feature", "")
            status = finding.get("status")
            state = ({"not_found": "CONFIRMED_ABSENT", "present": "CONFIRMED_PRESENT"}
                     .get(status, "NOT_VERIFIED"))
            verdict = folded["verified"].get(feature, "")
            refuted = verdict == "REFUTED" and any(
                o.get("feature") == feature and o.get("status") == "not_found"
                for o in _observations(folded["raw_audit"])
            )
            out.append({
                "feature": feature,
                "label": LABEL.get(feature, feature.replace("_", " ").title()),
                "state": state,
                "fixable": feature in scoring.FIXABLE,
                "cost": scoring.COST.get(feature, 0),
                "evidence": finding.get("evidence", "") or "",
                "impact": IMPACT.get(feature, ""),
                "remedy": REMEDY.get(feature, ""),
                "recheck": verdict,
                "refuted": refuted,
                "previously": "CONFIRMED_ABSENT" if refuted else "",
            })
        return sorted(out, key=lambda f: (-f["cost"], f["label"]))

    def _do_not_say(folded: dict) -> list[str]:
        score = folded["score"]
        rules = list(STANDING_DO_NOT_SAY)
        for feature in score.unfixable:
            rules.append(f"Do not offer to fix {LABEL.get(feature, feature)} — Qevik does not build it.")
        for feature in score.unverified:
            rules.append(f"Do not say they lack {LABEL.get(feature, feature)} — it was never verified.")
        for feature, verdict in folded["verified"].items():
            if verdict == "REFUTED":
                rules.append(f"Do not raise {LABEL.get(feature, feature)} — the re-check refuted it.")
        if folded["stale"]:
            rules.append("Evidence is stale. Re-verify before making any claim from it.")
        contact = contactability(folded["business"]["phone"], folded["business"]["email"])
        if contact["whatsapp"] != "REACHABLE":
            rules.append("Do not claim they are on WhatsApp — the number is not a UAE mobile.")
        return rules

    def _confidence(folded: dict, ready: bool) -> dict:
        """HIGH / MEDIUM / LOW / HOLD, folded from the same evidence as everything
        else. Not a stored field — a reading, with the reasons it came to it.
        """
        score = folded["score"]
        contact = contactability(folded["business"]["phone"], folded["business"]["email"])
        holds, softs = [], []
        if not score.audit_complete:
            holds.append("the audit never completed — nothing is confirmed either way")
        if folded["stale"]:
            holds.append("evidence is older than three days; re-verify before claiming anything")
        if contact["channel"] == "NONE":
            holds.append("no contact method on the listing")
        if not folded["chosen"].url:
            holds.append("no Qevik sample genuinely matches this trade")
        if holds:
            return {"level": "HOLD", "why": holds}
        if not score.speakable:
            softs.append("no confirmed weakness — this is a capability conversation, not a problem one")
        if contact["whatsapp"] != "REACHABLE":
            softs.append("not WhatsApp-reachable; this is a phone call")
        if folded["chosen"].kind == "sample":
            softs.append("a relevant sample rather than a demo built for them")
        if not ready:
            softs.append("no draft that passes its checks yet")
        level = "HIGH" if not softs else "MEDIUM" if len(softs) <= 2 else "LOW"
        return {"level": level, "why": softs or [
            "fresh evidence, a confirmed gap Qevik fixes, a reachable mobile, "
            "a matched demo and a draft that passes its checks"]}

    def _card(folded: dict) -> dict:
        business, score = folded["business"], folded["score"]
        contact = contactability(business["phone"], business["email"])
        return {
            "id": business["id"],
            "name": business["name"],
            "industry": INDUSTRY.get(folded["category"], "Other"),
            "category": folded["category"],
            "location": business["geography"] or "Dubai",
            "website": business["website"],
            "score": score.total,
            "band": ("HIGH OPPORTUNITY" if score.total >= 75
                     else "WORTH A LOOK" if score.total >= 55 else "LOW"),
            "confidence": next(c.points for c in score.components if c.name == "confidence"),
            "audit_complete": score.audit_complete,
            "verified": score.verified,
            "stale": folded["stale"],
            "last_verified": _age(folded["fresh_hours"]),
            "contact": business["phone"] or business["email"],
            "contactability": contact,
            "strongest": (lambda ls: LABEL.get(ls[0], ls[0]) if ls else "")(
                demos.leadable(folded["chosen"], score.speakable)),
            "speakable": [LABEL.get(f, f) for f in score.speakable],
            "demo": folded["demo"],
            "confidence": _confidence(folded, bool(folded["messages"]))["level"],
            "demo_kind": folded["chosen"].kind,
            "demo_matched": folded["chosen"].matched,
            "demo_name": (folded["chosen"].demo.name if folded["chosen"].demo
                          else "built for them" if folded["chosen"].prospect_url else ""),
            "stage": _stage(folded),
            "has_shot": bool(folded["shots"].get("desktop", {}).get("captured")),
            "load_ms": (folded["live"].get("load_ms") or folded["audit"].get("load_ms") or 0),
            "https": ("CONFIRMED_PRESENT" if folded["verified"].get("https") == "REFUTED"
                      or any(o.get("feature") == "https" and o.get("status") == "present"
                             for o in _observations(folded["audit"]))
                      else "CONFIRMED_ABSENT" if "https" in score.speakable
                      else "NOT_VERIFIED"),
        }

    # ------------------------------------------------------------- routes

    @router.get("/summary", dependencies=[Depends(requires(Scope.READ))])
    def summary() -> dict:
        folded = _all()
        stages = [_stage(f) for f in folded]
        contacts = [contactability(f["business"]["phone"], f["business"]["email"]) for f in folded]
        return {
            "total": len(folded),
            "audited": sum(1 for f in folded if f["score"].audit_complete),
            "high_opportunity": sum(1 for f in folded if f["score"].total >= 75),
            "whatsapp_reachable": sum(1 for c in contacts if c["whatsapp"] == "REACHABLE"),
            "approved": stages.count("APPROVED"),
            "contacted": stages.count("SENT") + stages.count("REPLIED") + stages.count("WON"),
            "replies": stages.count("REPLIED") + stages.count("WON"),
            "interested": sum(1 for f in folded
                              for r in f["replies"] if r.get("response") == "interested"),
            "not_contacted": stages.count("NOT_CONTACTED"),
            "stale": sum(1 for f in folded if f["stale"]),
            "generated_at": datetime.now(UTC).isoformat(),
        }

    @router.get("/prospects", dependencies=[Depends(requires(Scope.READ))])
    def prospects(
        q: str = "",
        industry: str = "",
        contact: str = "",
        website: str = "",
        stage: str = "",
        sort: str = "score",
        page: int = Query(1, ge=1),
        size: int = Query(24, ge=1, le=100),
    ) -> dict:
        cards = [_card(f) for f in _all()]

        if q:
            needle = q.lower()
            cards = [c for c in cards if needle in c["name"].lower()
                     or needle in c["website"].lower() or needle in c["contact"].lower()
                     or needle in c["location"].lower() or needle in c["industry"].lower()]
        if industry and industry != "All":
            cards = [c for c in cards if c["industry"] == industry]
        if contact:
            cards = [c for c in cards if {
                "whatsapp": c["contactability"]["whatsapp"] == "REACHABLE",
                "phone": c["contactability"]["kind"] in {"landline", "toll_free"},
                "email": c["contactability"]["kind"] == "email",
                "none": c["contactability"]["kind"] == "none",
            }.get(contact, True)]
        if website:
            cards = [c for c in cards if {
                "has_website": bool(c["website"]),
                "slow": c["load_ms"] >= 6000,
                "https": c["https"] == "CONFIRMED_PRESENT",
                "no_arabic": "Arabic version" in c["speakable"],
                "no_mobile_cta": "Tap-to-call number" in c["speakable"],
                "weaknesses": bool(c["speakable"]),
            }.get(website, True)]
        if stage:
            cards = [c for c in cards if c["stage"] == stage]

        cards.sort(key={
            "score": lambda c: -c["score"],
            "confidence": lambda c: -c["confidence"],
            "industry": lambda c: (c["industry"], -c["score"]),
            "verified": lambda c: (c["stale"], -c["score"]),
            "contactability": lambda c: (c["contactability"]["whatsapp"] != "REACHABLE", -c["score"]),
            "stage": lambda c: (c["stage"], -c["score"]),
        }.get(sort, lambda c: -c["score"]))

        start = (page - 1) * size
        return {"total": len(cards), "page": page, "size": size,
                "items": cards[start:start + size]}

    @router.get("/ready", dependencies=[Depends(requires(Scope.READ))])
    def ready(limit: int = 10) -> dict:
        """The operational queue: who can honestly be contacted right now.

        Every condition is a reason a message would otherwise be wrong — no
        confirmed weakness means nothing true to say; stale evidence means the
        claim may already be false; already-contacted means this is a follow-up
        and a different message.
        """
        pool = _all()
        out, blocked = [], []
        for folded in pool:
            card = _card(folded)
            reasons = []
            if not folded["score"].audit_complete:
                reasons.append("the audit never completed — nothing is confirmed either way")
            if not folded["score"].speakable:
                reasons.append("no confirmed weakness that Qevik can fix")
            if folded["stale"]:
                reasons.append(f"evidence last checked {card['last_verified']} — re-verify first")
            if card["contactability"]["channel"] == "NONE":
                reasons.append("no contact method on the listing")
            if card["stage"] in {"SENT", "REPLIED", "WON"}:
                reasons.append(f"already {card['stage'].lower()} — this would be a follow-up")
            if not (folded["drafts"] or folded["messages"]):
                reasons.append("no draft prepared")
            elif folded["messages"]:
                others = tuple(
                    consistency.Other(
                        business_id=f["business"]["id"], name=f["business"]["name"],
                        phone=f["business"]["phone"],
                        host=re.sub(r"^https?://(www\.)?", "",
                                    f["business"]["website"]).split("/")[0],
                        demo_url=f["demo"])
                    for f in pool
                )
                faults = {p for m in folded["messages"]
                          for p in consistency.check(
                              m["body"], business_id=folded["business"]["id"],
                              speakable=folded["score"].speakable,
                              unfixable=folded["score"].unfixable,
                              unverified=folded["score"].unverified,
                              chosen=folded["chosen"], category=folded["category"],
                              others=others)}
                if faults:
                    reasons.append("draft requires review: " + "; ".join(sorted(faults)[:2]))
            if not folded["chosen"].matched and folded["chosen"].kind != "prospect":
                reasons.append("no Qevik sample genuinely matches this trade")
            (blocked if reasons else out).append({**card, "blocked_by": reasons})
        return {"ready": out[:limit], "blocked": blocked[:40],
                "ready_total": len(out), "blocked_total": len(blocked)}

    def _brief(folded: dict, lead: str, chosen, drafts: list) -> dict:
        """What to read in the thirty seconds before typing to a stranger."""
        score = folded["score"]
        name = folded["business"]["name"].split("|")[0].split("(")[0].strip()
        why = demos.why_this_demo(chosen, folded["category"], lead)
        gap = LABEL.get(lead, lead)
        return {
            "opening": (
                f"Open on something true about their site, then the one gap: {gap.lower()}."
                if lead else
                "There is no confirmed gap, so open on what they do and what Qevik builds — "
                "not on a problem."),
            "why_them": (
                f"{score.total}/100. "
                + (f"{len(score.speakable)} confirmed gap(s) Qevik ships fixes for, "
                   if score.speakable else "No confirmed gap, but ")
                + f"{contactability(folded['business']['phone'], folded['business']['email'])['why'].lower()}"),
            "what_to_show": ({"demo": chosen.url,
                              "name": chosen.demo.name if chosen.demo else "built for them",
                              "steps": list(demos.show_this(chosen))}),
            "mention": [m for m in (
                (f"The {gap.lower()} gap, and only that one" if lead else ""),
                (why["demonstrates"][0] if why["demonstrates"] else ""),
                "That the demo is Qevik's own work and nobody asked for it",
            ) if m][:3],
            "answers": [
                {"q": "Why did you build this?",
                 "a": (f"Your business is a good example of where a normal brochure website "
                       f"isn't enough, so I wanted to show the kind of product we build. "
                       f"{name} wasn't involved — I put it together from what's public.")},
                {"q": "Is this our website?",
                 "a": ("No. It's an independent concept built from publicly visible information "
                       "about your business."
                       if chosen.kind != "prospect" else
                       "No. It's an example I built using your public listing details — your "
                       "name, address, phone and hours. It isn't connected to anything.")},
                {"q": "Are you already working with us?",
                 "a": "No. This is unsolicited — nobody asked for it and there's no invoice attached."},
                {"q": "How much?",
                 "a": (f"{offer.CURRENCY} {offer.SETUP_AED:,} to set up, then "
                       f"{offer.CURRENCY} {offer.MONTHLY_AED} a month. "
                       "Only answer this if they ask — it is not in the first message.")},
            ],
            "do_not_say": _do_not_say(folded),
            "does_not_claim": why["does_not_claim"],
        }

    @router.get("/prospects/{business_id}", dependencies=[Depends(requires(Scope.READ))])
    def prospect(business_id: str) -> dict:
        everything = _all()
        for folded in everything:
            if folded["business"]["id"] != business_id:
                continue
            score, business = folded["score"], folded["business"]
            warnings: list[dict] = []
            findings = _findings(folded)
            # The angle the message can actually open with, by the same rule the
            # generator uses — so the headline and the draft never disagree.
            leads = demos.leadable(folded["chosen"], score.speakable)
            lead = leads[0] if leads else ""
            contact = contactability(business["phone"], business["email"])
            others = tuple(
                consistency.Other(
                    business_id=f["business"]["id"], name=f["business"]["name"],
                    phone=f["business"]["phone"],
                    host=re.sub(r"^https?://(www\.)?", "", f["business"]["website"]).split("/")[0],
                    demo_url=f["demo"],
                )
                for f in everything
            )
            drafts = [
                {"channel": m["channel"], "status": m["status"], "recipient": m["recipient"],
                 "subject": m["subject"], "body": m["body"],
                 "created_at": m["created_at"].isoformat() if m["created_at"] else "",
                 "sent_at": m["sent_at"].isoformat() if m["sent_at"] else "",
                 "provider_message_id": m["provider_message_id"],
                 # Validated on the way out, with the same checker that wrote it.
                 # A draft that looks fine and is about two businesses at once is
                 # worse than one that is obviously unfinished.
                 "problems": consistency.check(
                     m["body"], business_id=business["id"],
                     speakable=score.speakable, unfixable=score.unfixable,
                     unverified=score.unverified, chosen=folded["chosen"],
                     category=folded["category"], others=others),
                 }
                for m in folded["messages"]
            ]
            return {
                "card": _card(folded),
                "identity": {
                    "name": business["name"],
                    "listing_name": business["name"],
                    "website": business["website"],
                    "phone": business["phone"], "email": business["email"],
                    "location": business["geography"] or "NOT VERIFIED",
                    "city": "Dubai", "country": "United Arab Emirates",
                    "category": folded["category"] or "NOT VERIFIED",
                    "sources": business["sources"] or [],
                    "maps": ("https://www.google.com/maps/search/?api=1&query="
                             + (business["name"] + " " + (business["geography"] or "Dubai")).replace(" ", "+")),
                    "audited_at": folded["audited_at"].isoformat() if folded["audited_at"] else "",
                    "verified_at": folded["verified_at"].isoformat() if folded["verified_at"] else "",
                    "last_verified": _age(folded["fresh_hours"]),
                    "stale": folded["stale"],
                },
                "health": {
                    "http_status": (folded["live"].get("http_status")
                                    or folded["audit"].get("http_status") or 0),
                    "load_ms": (folded["live"].get("load_ms")
                                or folded["audit"].get("load_ms") or 0),
                    "load_measured": "re-check" if folded["live"].get("load_ms") else "audit",
                    "audit_complete": score.audit_complete,
                    "checked_at": (folded["verified_at"] or folded["audited_at"]).isoformat()
                                  if (folded["verified_at"] or folded["audited_at"]) else "",
                    "items": findings,
                },
                "score": {
                    "total": score.total,
                    "components": [{"name": c.name, "points": c.points, "out_of": c.out_of,
                                    "reason": c.reason, "evidence": c.evidence}
                                   for c in score.components],
                },
                "strongest": ({
                    "feature": lead,
                    "label": LABEL.get(lead, lead),
                    "impact": IMPACT.get(lead, ""),
                    "remedy": REMEDY.get(lead, ""),
                    "evidence": next((f["evidence"] for f in findings
                                      if f["feature"] == lead), ""),
                    # A bigger gap exists that the linked demo cannot answer.
                    # Say so, rather than headlining something the message
                    # deliberately does not raise.
                    "deferred": [LABEL.get(f, f) for f in score.speakable
                                 if f not in leads],
                } if lead else None),
                "strengths": [f for f in findings
                              if f["state"] == "CONFIRMED_PRESENT" and not f["refuted"]],
                "opportunities": [f for f in findings
                                  if f["state"] == "CONFIRMED_ABSENT" and f["fixable"]],
                "unfixable": [f for f in findings
                              if f["state"] == "CONFIRMED_ABSENT" and not f["fixable"]],
                "unverified": [f for f in findings if f["state"] == "NOT_VERIFIED"],
                "refuted": [f for f in findings if f["refuted"]],
                "screenshots": {
                    label: {**shot,
                            "url": (f"/control/sales/prospects/{business_id}/shot/{label}"
                                    if shot.get("captured") else "")}
                    for label, shot in folded["shots"].items()
                } or {"desktop": {"captured": False, "reason": "not captured"},
                      "mobile": {"captured": False, "reason": "not captured"}},
                "screenshots_at": folded["shots_at"].isoformat() if folded["shots_at"] else "",
                "demo": _demo_view(folded),
                "research": _safe(
                    "research", lambda: _research_view(folded), {"state": "NONE"},
                    business_id=business_id, warnings=warnings),
                "digital_opportunities": _safe(
                    "digital_opportunities",
                    lambda: _digital(findings, category=folded["category"],
                                     website=business["website"]),
                    [], business_id=business_id, warnings=warnings),
                "media": _safe(
                    "media",
                    lambda: {**folded["media"], "options": list(MEDIA_PERMISSION)},
                    {"permission": "none", "source": "", "at": "", "note": "",
                     "options": list(MEDIA_PERMISSION)},
                    business_id=business_id, warnings=warnings),
                "builds": _safe(
                    "builds",
                    lambda: {"jobs": sorted(folded["builds"].values(),
                                            key=lambda j: j["created"], reverse=True),
                             "products": list(PRODUCTS), "states": list(JOB_STATES)},
                    {"jobs": [], "products": list(PRODUCTS), "states": list(JOB_STATES)},
                    business_id=business_id, warnings=warnings),
                "warnings": warnings,
                "outreach": {
                    "channel": contact["channel"], "why": contact["why"],
                    "contactability": contact, "drafts": drafts,
                    "do_not_say": _do_not_say(folded),
                    "ready": bool(drafts) and not any(d["problems"] for d in drafts),
                    "problems": sorted({p for d in drafts for p in d["problems"]}),
                },
                "why_demo": demos.why_this_demo(folded["chosen"], folded["category"], lead),
                "show_this": list(demos.show_this(folded["chosen"])),
                "brief": _brief(folded, lead, folded["chosen"], drafts),
                "confidence": _confidence(
                    folded, bool(drafts) and not any(d["problems"] for d in drafts)),
                "timeline": folded["timeline"],
                "stage": _stage(folded),
            }
        raise HTTPException(status_code=404, detail="no such prospect")

    @router.get("/prospects/{business_id}/shot/{label}",
                dependencies=[Depends(requires(Scope.READ))])
    def screenshot(business_id: str, label: str, thumb: bool = False) -> Response:
        """Served through the API, never from a public directory.

        The console's CSP is `img-src 'self'`, and prospect evidence must stay
        behind the same authentication as everything else about them.
        """
        if not re.fullmatch(r"[0-9a-f-]{36}", business_id) or label not in {"desktop", "mobile"}:
            raise HTTPException(status_code=400, detail="bad request")
        folder = EVIDENCE / business_id
        pattern = f"{label}-*.thumb.jpg" if thumb else f"{label}-*.png"
        files = sorted(folder.glob(pattern)) if folder.is_dir() else []
        if not files:
            raise HTTPException(status_code=404, detail="screenshot not captured")
        return Response(
            content=files[-1].read_bytes(),
            media_type="image/jpeg" if thumb else "image/png",
            headers={"Cache-Control": "private, max-age=3600",
                     "X-Robots-Tag": "noindex, nofollow"},
        )

    # -- the only two writes, both recording something a human did ---------

    @router.post("/prospects/{business_id}/sent")
    def record_sent(business_id: str, record: SentRecord,
                    user: User = Depends(requires(Scope.READ))) -> dict:
        """A human confirms they sent a message, by hand, at a real time.

        Nothing is sent here and nothing can be. This exists so that "contacted"
        means somebody says they did it, never that a draft was approved.
        """
        from ..opportunity.models import BusinessEvent
        from ..opportunity.repository import OpportunityRepository

        if record.sent_at.tzinfo is None:
            raise HTTPException(status_code=400, detail="sent_at must carry a timezone")
        OpportunityRepository().record_event(BusinessEvent(
            business_id=business_id, factory="sales_experiment", kind="experiment_sent",
            actor=user.username, detail={"channel": record.channel,
                                         "sent_at": record.sent_at.isoformat(),
                                         "message_version": record.message_version,
                                         "note": record.note, "by_hand": True},
        ))
        return {"recorded": True}

    @router.post("/prospects/{business_id}/reply")
    def record_reply(business_id: str, record: ReplyRecord,
                     user: User = Depends(requires(Scope.READ))) -> dict:
        from ..opportunity.models import BusinessEvent
        from ..opportunity.repository import OpportunityRepository

        OpportunityRepository().record_event(BusinessEvent(
            business_id=business_id, factory="sales_experiment", kind="experiment_response",
            actor=user.username, detail={"response": record.response,
                                         "verbatim": record.verbatim,
                                         "objection": record.objection},
        ))
        return {"recorded": True}

    @router.post("/prospects/{business_id}/media-permission")
    def record_media_permission(business_id: str, record: MediaPermission,
                                user: User = Depends(requires(Scope.READ))) -> dict:
        """A human ticks what the customer actually said, when they said it.

        Deliberately one field and one click. An operator reading "yes, use our
        photos" in a WhatsApp thread should be able to record it without
        leaving the conversation, and a permission that is slow to record is a
        permission that gets assumed instead.
        """
        from ..opportunity.models import BusinessEvent
        from ..opportunity.repository import OpportunityRepository

        if record.permission not in MEDIA_PERMISSION:
            raise HTTPException(status_code=400, detail=f"permission must be one of "
                                                        f"{MEDIA_PERMISSION}")
        OpportunityRepository().record_event(BusinessEvent(
            business_id=business_id, factory="media", kind="media_permission_recorded",
            actor=user.username, detail={"permission": record.permission,
                                         "source": record.source, "note": record.note},
        ))
        return {"recorded": True, "permission": record.permission}

    @router.post("/prospects/{business_id}/build")
    def request_build(business_id: str, record: BuildRequest,
                      user: User = Depends(requires(Scope.READ))) -> dict:
        """Queue a product build. Queues it — nothing is generated here.

        A queued job is not a thing that exists, so it may not appear in a
        message. Outreach reads READY and nothing else.
        """
        from ..opportunity.models import BusinessEvent
        from ..opportunity.repository import OpportunityRepository

        if record.product not in PRODUCTS:
            raise HTTPException(status_code=400, detail="unknown product")
        everything = {f["business"]["id"]: f for f in _all()}
        folded = everything.get(business_id)
        if folded is None:
            raise HTTPException(status_code=404, detail="no such prospect")
        # §49: a build must not guess. Without research there is nothing for the
        # brief to be derived from, and a generic product is worse than none.
        if not _digital(_findings(folded), category=folded["category"],
                        website=folded["business"]["website"]):
            raise HTTPException(status_code=409,
                                detail="REQUIRES BRIEF — no evidenced opportunity for this "
                                       "business yet; audit it first")
        if (record.product in ("Android app", "iOS app")
                and folded["media"]["permission"] == "none"):
            # Not a blocker, a label: an app concept without media rights is a
            # concept, and it must not be described as anything else.
            pass
        job_id = f"{business_id[:8]}-{len(folded['builds']) + 1:03d}"
        OpportunityRepository().record_event(BusinessEvent(
            business_id=business_id, factory="product_build",
            kind="product_build_requested", actor=user.username,
            detail={"job_id": job_id, "product": record.product, "brief": record.brief,
                    "opportunity": record.opportunity, "actor": user.username},
        ))
        return {"queued": True, "job_id": job_id, "state": "QUEUED"}

    return router


def install(app) -> None:
    """Additive. A failure here must never take the control plane down."""
    app.include_router(build_router())
