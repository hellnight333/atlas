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
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from ..auth import Scope, User, requires
from ..outreach import scoring

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

#: The nav's industry groups, mapped onto the categories the discovery wrote.
INDUSTRY = {
    "food": "Food & Drink", "beauty": "Health & Beauty", "health": "Health & Beauty",
    "dental": "Health & Beauty", "home": "Home Services", "automotive": "Automotive",
    "professional": "Professional Services", "retail": "Retail",
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
        shots: dict = {}
        shots_at = None
        drafts: list[dict] = []
        timeline: list[dict] = []
        sent: list[dict] = []
        replies: list[dict] = []

        for factory, kind, at, detail in events:
            if kind == "website_audited":
                audit, audits, audited_at = detail, audits + 1, at
            elif kind == "claims_verified":
                # Merged, never replaced: a later run only re-tests what is
                # still flagged, so the newest event is not the whole truth.
                verified.update({c["feature"]: c["verdict"] for c in detail.get("claims", [])})
                live, verified_at = detail, at
            elif kind == "website_demo_published":
                demo = detail.get("demo_url", "")
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
        category = audit.get("category") or ("dental" if demo else "")

        merged = dict(audit)
        if verified:
            merged = scoring.apply_verification(
                {**audit, "live_load_ms": live.get("load_ms"),
                 "live_http_status": live.get("http_status")},
                verified,
            )

        score = scoring.score(
            business_id=business["id"], name=business["name"], website=business["website"],
            phone=business["phone"], email=business["email"], category=category,
            audit=merged, audit_count=audits, demo_url=demo,
            sample_slug=SAMPLE_FOR.get(category, ""),
        )

        fresh_hours = _hours_since(verified_at or audited_at)
        return {
            "business": business, "category": category, "score": score,
            "audit": merged, "raw_audit": audit, "verified": verified, "live": live,
            "audited_at": audited_at, "verified_at": verified_at,
            "demo": demo, "shots": shots, "shots_at": shots_at,
            "drafts": drafts, "messages": messages, "sent": sent, "replies": replies,
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
            "strongest": (LABEL.get(score.speakable[0], score.speakable[0])
                          if score.speakable else ""),
            "speakable": [LABEL.get(f, f) for f in score.speakable],
            "demo": folded["demo"],
            "demo_kind": ("prospect" if folded["demo"] else
                          "sample" if SAMPLE_FOR.get(folded["category"]) else "none"),
            "sample": SAMPLE_FOR.get(folded["category"], ""),
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
        out, blocked = [], []
        for folded in _all():
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
            (blocked if reasons else out).append({**card, "blocked_by": reasons})
        return {"ready": out[:limit], "blocked": blocked[:40],
                "ready_total": len(out), "blocked_total": len(blocked)}

    @router.get("/prospects/{business_id}", dependencies=[Depends(requires(Scope.READ))])
    def prospect(business_id: str) -> dict:
        for folded in _all():
            if folded["business"]["id"] != business_id:
                continue
            score, business = folded["score"], folded["business"]
            findings = _findings(folded)
            contact = contactability(business["phone"], business["email"])
            drafts = [
                {"channel": m["channel"], "status": m["status"], "recipient": m["recipient"],
                 "subject": m["subject"], "body": m["body"],
                 "created_at": m["created_at"].isoformat() if m["created_at"] else "",
                 "sent_at": m["sent_at"].isoformat() if m["sent_at"] else "",
                 "provider_message_id": m["provider_message_id"]}
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
                    "feature": score.speakable[0],
                    "label": LABEL.get(score.speakable[0], score.speakable[0]),
                    "impact": IMPACT.get(score.speakable[0], ""),
                    "remedy": REMEDY.get(score.speakable[0], ""),
                    "evidence": next((f["evidence"] for f in findings
                                      if f["feature"] == score.speakable[0]), ""),
                } if score.speakable else None),
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
                "demo": {
                    "url": folded["demo"] or (f"https://sites.qevik.ai/{SAMPLE_FOR[folded['category']]}/"
                                              if SAMPLE_FOR.get(folded["category"]) else ""),
                    "kind": "prospect" if folded["demo"] else
                            "sample" if SAMPLE_FOR.get(folded["category"]) else "none",
                    "label": ("Prospect-specific unsolicited demo" if folded["demo"]
                              else "Relevant Qevik sample" if SAMPLE_FOR.get(folded["category"])
                              else "No demo matches this industry"),
                    "why": (f"Built for {business['name']} from their own public listing details."
                            if folded["demo"] else
                            SAMPLE_WHY.get(SAMPLE_FOR.get(folded["category"], ""), "")),
                },
                "outreach": {
                    "channel": contact["channel"], "why": contact["why"],
                    "contactability": contact, "drafts": drafts,
                    "do_not_say": _do_not_say(folded),
                },
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

    return router


#: Kept in step with `infra/score_prospects.py`. Duplicated deliberately: the
#: kernel may not import from `infra/`, and a shared constants module for two
#: dictionaries would be indirection for its own sake.
SAMPLE_FOR = {
    "dental": "sample", "health": "sample", "food": "sample-nar",
    "beauty": "sample-atelier", "automotive": "sample-apex", "home": "sample-homefix",
    "professional": "sample-meridian", "retail": "sample-verdant", "fitness": "sample-kilo",
}

SAMPLE_WHY = {
    "sample": "A bilingual clinic site with verified hours and tap-to-call.",
    "sample-nar": "An editorial restaurant page — a premium experience rather than a generic template.",
    "sample-atelier": "A salon treatment list with real durations and prices.",
    "sample-apex": "A four-step quote configurator that prices live.",
    "sample-homefix": "Built for someone on a phone who wants a number and a human.",
    "sample-meridian": "Property search with filters, a saved list and a call-back request.",
    "sample-verdant": "A filterable catalogue with a working basket.",
    "sample-kilo": "A mobile-first member app: bookings, sessions and progress.",
}


def install(app) -> None:
    """Additive. A failure here must never take the control plane down."""
    app.include_router(build_router())
