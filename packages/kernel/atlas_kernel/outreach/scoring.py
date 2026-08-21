"""How commercially worth contacting a prospect is, and why — from stored evidence only.

`rank_market.py` scores the *market*: which industry to attack, from weighted
defect counts. This scores a *conversation*: whether one specific business is
worth spending a first message on. They are different questions and the second
one is the expensive one to get wrong, because a message is a thing a real
person reads once.

Four rules the design exists to enforce.

**A weakness we cannot fix is not an opportunity.** Every audited clinic is
missing `booking_link`, and Qevik has no booking backend — that is stated
plainly on the public site. Scoring it would rank prospects by the size of a
problem we would have to decline, and would tempt a message that implies we
solve it. So the pain a business has and the part of it we can address are
scored *separately*: `weakness` measures their problem, `improvement` measures
our opportunity, and only the second one may be spoken about in outreach.

**`unverified` scores nothing, in either direction.** The audit reads one
homepage. A feature can live on an inner page, and absent-from-our-sample is not
absent-from-their-site. An unverified finding lowers `confidence` rather than
raising `weakness`, because the honest response to not knowing is to claim less.

**Reachability multiplies nothing but it caps a lot.** A perfect opportunity at
a number nobody answers is worth nothing, and a mobile is worth far more than a
switchboard: it reaches a person who can decide, on the channel they already
read. Toll-free numbers score near zero — they reach a call centre.

**No component may be justified by anything but a stored event.** Every one
returns the evidence it used, so a score can be argued with rather than
believed. Nothing here reads review counts, revenue, staff numbers or any other
figure Qevik has not actually observed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

#: What a missing feature costs the business, on a common scale.
#:
#: Commercial cost, not detection difficulty. `https` is the highest because a
#: browser now labels the site "Not secure" in front of every visitor; `arabic`
#: is next because in this market it decides whether a share of customers can
#: read the page at all. Metadata sits at the bottom: it moves a ranking
#: slightly and no visitor ever sees it.
COST: dict[str, int] = {
    "https": 25,
    "viewport_meta": 22,
    "arabic": 20,
    "click_to_call": 18,
    "whatsapp": 15,
    "google_maps": 13,
    "opening_hours": 12,
    "contact_form": 11,
    "structured_data": 8,
    "services_navigation": 5,
    "h1": 5,
    "meta_description": 3,
    "image_alt_text": 2,
    "page_title": 2,
    "page_weight": 1,
    # Dental-audit vocabulary.
    "insurance_info": 9,
    "emergency_info": 7,
    "doctors_team": 6,
    "social_proof": 4,
}

#: Features Qevik has actually shipped and can therefore offer to fix.
#:
#: `booking_link` is deliberately absent. There is no appointment backend, the
#: public site says so, and a prospect who asked for it would have to be told
#: no. Anything not in this set may be *scored as their pain* but must never
#: appear in a message as something we will solve.
FIXABLE = frozenset({
    "https", "viewport_meta", "arabic", "click_to_call", "whatsapp",
    "google_maps", "opening_hours", "contact_form", "structured_data",
    "services_navigation", "h1", "meta_description", "image_alt_text",
    "page_title", "insurance_info", "emergency_info", "doctors_team",
})

#: Reached by WhatsApp, and reaches a person rather than a switchboard.
_MOBILE = re.compile(r"^(?:971)?0?5[024568]\d{7}$")
#: A call centre. Whoever answers cannot buy a website.
_TOLL_FREE = re.compile(r"^(?:971)?800\d+$")

#: A homepage slower than this loses visitors before it renders.
SLOW_MS = 6000

MAX = {
    "reachability": 20,
    "weakness": 25,
    "improvement": 25,
    "quality": 15,
    "confidence": 10,
    "relevance": 5,
}


@dataclass(frozen=True)
class Component:
    """One part of the score, with the evidence that produced it."""

    name: str
    points: int
    out_of: int
    reason: str
    evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Score:
    business_id: str
    name: str
    total: int
    components: tuple[Component, ...]
    #: Confirmed-absent and fixable, most costly first. The only weaknesses a
    #: message is allowed to raise.
    speakable: tuple[str, ...]
    #: Confirmed-absent but outside what Qevik ships. Real, and unsayable.
    unfixable: tuple[str, ...]
    #: Confirmed present. What not to insult.
    strengths: tuple[str, ...]
    #: False when the audit never reached the site. Everything else in this
    #: score is then a statement about our failure to look, not about them.
    audit_complete: bool
    #: True once the claims were re-tested live. Until then the score is
    #: provisional, and reliably too high.
    verified: bool
    #: Not observed either way. Never describe these as missing.
    unverified: tuple[str, ...]
    contact: str
    contact_kind: str

    def as_event_detail(self) -> dict[str, Any]:
        """The whole score, flattened for a BusinessEvent."""
        return {
            "total": self.total,
            "components": [
                {
                    "name": c.name,
                    "points": c.points,
                    "out_of": c.out_of,
                    "reason": c.reason,
                    "evidence": c.evidence,
                }
                for c in self.components
            ],
            "speakable_weaknesses": list(self.speakable),
            "unfixable_weaknesses": list(self.unfixable),
            "confirmed_strengths": list(self.strengths),
            "not_verified": list(self.unverified),
            "audit_complete": self.audit_complete,
            "verified": self.verified,
            "contact": self.contact,
            "contact_kind": self.contact_kind,
            "scorer_version": VERSION,
        }


#: Bumped whenever the weights or rules change, so two scores are comparable
#: only when this matches. Stored on every event.
VERSION = "cos-1"


def digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _observations(audit: dict) -> list[dict]:
    """Findings, under whichever key the pipeline that wrote them used."""
    return audit.get("observations") or audit.get("findings") or []


def _split(audit: dict) -> tuple[list[str], list[str], list[str]]:
    """Confirmed-absent, confirmed-present, and not-verified — never merged."""
    absent, present, unknown = [], [], []
    for finding in _observations(audit):
        feature, status = finding.get("feature", ""), finding.get("status")
        if status == "not_found":
            absent.append(feature)
        elif status == "present":
            present.append(feature)
        elif status == "unverified":
            unknown.append(feature)
    return absent, present, unknown


def apply_verification(audit: dict, verified: dict[str, str]) -> dict:
    """Fold a live re-check back over a stored audit.

    The stored audit says what a homepage looked like on the day it was read; a
    message sent later asserts it is still true. Re-checking the top prospects
    refuted three of Malabar's five recorded weaknesses and two prospects'
    missing HTTPS outright — the audit only ever knew their *listed* URL began
    `http://`. Scoring the stale copy would have ranked prospects by problems
    they had already fixed, and written messages about them.

    A refuted finding becomes `present`. An unresolved one becomes `unverified`
    rather than quietly staying absent, because failing to confirm something is
    not confirming it.
    """
    if not verified:
        return audit
    findings = []
    for finding in _observations(audit):
        verdict = verified.get(finding.get("feature", ""))
        if verdict == "REFUTED":
            finding = {**finding, "status": "present", "evidence": "re-checked live: no longer absent"}
        elif verdict == "CONFIRMED":
            finding = {**finding, "status": "not_found", "evidence": "re-checked live: still absent"}
        elif verdict == "NOT_VERIFIED":
            finding = {**finding, "status": "unverified", "evidence": "re-check inconclusive"}
        findings.append(finding)
    updated = {**audit, "observations": findings, "verified": True}
    updated.pop("findings", None)

    # A live measurement supersedes a stored one — same reading, taken later.
    # This also rescues the case where the stored audit has *no* findings to
    # rewrite: Kings' two recorded runs are zero-byte failures, and only the
    # live check knows the site answers at all, slowly.
    live_status = audit.get("live_http_status")
    live_load = audit.get("live_load_ms")
    if verified.get("site_loads") == "REFUTED" and live_status:
        updated["http_status"] = live_status
        updated["reachable"] = True
    if live_load and ("slow_homepage" in verified or verified.get("site_loads") == "REFUTED"):
        updated["load_ms"] = live_load
    return updated


def audit_completed(audit: dict) -> bool:
    """Did the audit actually observe anything?

    A run that returns no findings and no HTTP status did not find a clean site
    — it failed to reach one. The two are opposite conclusions and the first
    draft of this scored them identically, handing a business whose homepage
    never responded a spotless `weakness` of 0 and calling it "the site passed
    every check we ran". Nothing was checked.
    """
    return bool(_observations(audit)) or bool(audit.get("http_status"))


def _saturate(value: float, full: float, out_of: int) -> int:
    """Diminishing returns: the tenth small defect matters less than the first.

    A linear scale lets a pile of metadata nits outrank one broken enquiry path,
    which is the failure the market scorer was rewritten to avoid.
    """
    return min(out_of, round(out_of * (1 - pow(2.718281828, -value / full))))


def reachability(phone: str, email: str = "") -> Component:
    number = digits(phone)
    if number and _TOLL_FREE.match(number):
        return Component("reachability", 4, 20, "toll-free number — reaches a call centre, not an owner",
                         [f"phone {phone}"])
    if number and _MOBILE.match(number):
        return Component("reachability", 20, 20, "UAE mobile — WhatsApp reaches a person who can decide",
                         [f"phone {phone}"])
    if number:
        return Component("reachability", 11, 20, "landline only — a call, probably through reception",
                         [f"phone {phone}"])
    if email:
        return Component("reachability", 7, 20, "email only — no phone on the listing", [f"email {email}"])
    return Component("reachability", 0, 20, "no contact method on the listing", [])


def weakness(audit: dict) -> Component:
    """How much their site is costing them. Confirmed absences only."""
    if not audit_completed(audit):
        return Component(
            "weakness", 0, 25,
            "AUDIT DID NOT COMPLETE — the homepage returned nothing, so no "
            "weakness is confirmed and none is ruled out",
            [f"http_status {audit.get('http_status')!r}, {len(_observations(audit))} findings recorded"],
        )
    absent, _, _ = _split(audit)
    scored = sorted(((COST.get(f, 2), f) for f in absent), reverse=True)
    load = audit.get("load_ms") or 0
    evidence = [f"confirmed absent: {f} (cost {c})" for c, f in scored[:6]]
    total = sum(c for c, _ in scored)
    if load >= SLOW_MS:
        total += 12
        evidence.append(f"homepage took {load / 1000:.1f}s (measured once)")
    if audit.get("reachable") is False:
        total += 40
        evidence.append(f"site did not load: {str(audit.get('error', ''))[:60]}")
    if not scored and not evidence:
        return Component("weakness", 0, 25,
                         "nothing confirmed absent — the site passed every check we ran", [])
    return Component("weakness", _saturate(total, 55, 25), 25,
                     f"{len(absent)} confirmed absences, weighted by what each costs", evidence)


def improvement(audit: dict) -> tuple[Component, tuple[str, ...], tuple[str, ...]]:
    """The part of their problem Qevik has actually shipped a fix for."""
    if not audit_completed(audit):
        return Component("improvement", 0, 25,
                         "unknown — nothing was observed to fix", []), (), ()
    absent, _, _ = _split(audit)
    speakable = tuple(f for _, f in sorted(((COST.get(f, 2), f) for f in absent if f in FIXABLE), reverse=True))
    unfixable = tuple(f for _, f in sorted(((COST.get(f, 2), f) for f in absent if f not in FIXABLE), reverse=True))
    value = sum(COST.get(f, 2) for f in speakable)
    if not speakable:
        note = ("nothing we ship is confirmed missing"
                + (f" — their gaps ({', '.join(unfixable)}) are outside what Qevik builds"
                   if unfixable else ""))
        return Component("improvement", 0, 25, note, []), speakable, unfixable
    return (
        Component(
            "improvement", _saturate(value, 45, 25), 25,
            f"{len(speakable)} of {len(absent)} confirmed gaps are things Qevik has shipped",
            [f"can fix: {f}" for f in speakable]
            + ([f"cannot fix, do not raise: {f}" for f in unfixable] if unfixable else []),
        ),
        speakable,
        unfixable,
    )


def quality(audit: dict, website: str) -> Component:
    """Evidence the business takes its web presence seriously — nothing more.

    Deliberately not a guess at revenue, size or reputation. Qevik has observed
    one homepage; inventing a judgement about the company behind it would be the
    kind of claim this whole project refuses to make.
    """
    _, present, _ = _split(audit)
    points, why = 0, []
    if audit.get("http_status") == 200:
        points += 4
        why.append("homepage returns 200")
    host = re.sub(r"^https?://(www\.)?", "", website or "").split("/")[0]
    if host and not re.search(r"\.(wixsite|weebly|blogspot|business\.site|godaddysites)\.", host):
        points += 3
        why.append(f"own domain ({host})")
    density = min(8, round(len(present) * 0.5))
    points += density
    why.append(f"{len(present)} features confirmed present — a site somebody invested in")
    load = audit.get("load_ms")
    if load:
        why.append(f"homepage load {load / 1000:.1f}s")
    return Component("quality", min(15, points), 15, "apparent investment in their web presence", why)


def confidence(audit: dict, audit_count: int) -> Component:
    """How much of the audit is actually known, versus not observed.

    Re-checking counts for a lot here, because stale evidence is *optimistic*
    evidence: sites get fixed between the audit and the message, never broken to
    order. Verifying the first six prospects moved them 86->76, 80->66 and
    76->68. A ranking that did not price that in would put whichever businesses
    we had looked at least recently on top — rewarding ignorance, and sending
    the confident messages to exactly the prospects we knew least about.
    """
    absent, present, unknown = _split(audit)
    seen = len(absent) + len(present)
    total = seen + len(unknown)
    if not total:
        return Component(
            "confidence", 0, 10,
            "nothing observed — every feature is NOT_VERIFIED, including the ones "
            "a clean audit would have confirmed present",
            [f"{audit_count} audit run(s), all returning no findings"],
        )
    ratio = seen / total
    checked = bool(audit.get("verified"))
    points = round(4 * ratio) + min(2, audit_count) + (4 if checked else 0)
    why = [f"{seen} of {total} features confirmed either way"]
    if unknown:
        why.append(f"NOT_VERIFIED, never to be described as missing: {', '.join(unknown)}")
    why.append(f"{audit_count} independent audit run(s) on record")
    why.append("claims re-checked live" if checked
               else "NOT re-checked — this score is provisional and probably too high")
    return Component(
        "confidence", min(10, points), 10,
        f"{ratio:.0%} of checked features resolved"
        + ("" if checked else ", but nothing re-verified since the audit"),
        why,
    )


def relevance(category: str, demo_url: str, sample_slug: str) -> Component:
    """Whether we can show them something that looks like their own business."""
    if demo_url:
        return Component("relevance", 5, 5,
                         "a demo was built for this business specifically", [demo_url])
    if sample_slug:
        return Component("relevance", 3, 5,
                         f"a portfolio sample matches their industry ({category or 'unknown'})",
                         [f"https://sites.qevik.ai/{sample_slug}/"])
    return Component("relevance", 0, 5, f"no demo or sample matches {category or 'this industry'}", [])


def score(
    *,
    business_id: str,
    name: str,
    website: str,
    phone: str,
    email: str,
    category: str,
    audit: dict,
    audit_count: int,
    demo_url: str = "",
    sample_slug: str = "",
) -> Score:
    """The whole Commercial Opportunity Score, with its reasoning attached."""
    absent, present, unknown = _split(audit)
    reach = reachability(phone, email)
    weak = weakness(audit)
    improve, speakable, unfixable = improvement(audit)
    qual = quality(audit, website)
    conf = confidence(audit, audit_count)
    rel = relevance(category, demo_url, sample_slug)
    components = (reach, weak, improve, qual, conf, rel)

    number = digits(phone)
    kind = (
        "mobile" if number and _MOBILE.match(number)
        else "toll_free" if number and _TOLL_FREE.match(number)
        else "landline" if number
        else "email" if email
        else "none"
    )
    return Score(
        audit_complete=audit_completed(audit),
        verified=bool(audit.get("verified")),
        business_id=business_id,
        name=name,
        total=sum(c.points for c in components),
        components=components,
        speakable=speakable,
        unfixable=unfixable,
        strengths=tuple(sorted(present)),
        unverified=tuple(sorted(unknown)),
        contact=phone or email,
        contact_kind=kind,
    )
