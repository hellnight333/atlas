"""Everything known about one prospect, gathered from the models that own it.

Thirteen questions a person asks before deciding whether to write to a stranger.
Their answers already exist, in eight different places: the business record, the
signal, the audit, the publications and reviews, the outreach message, the
contact provenance and the timeline. An operator answering them today opens five
screens and infers the rest, and the inferring is where the mistakes live.

## It owns nothing

Every answer names the model it came from, and every answer is *read* from that
model. Nothing here composes, derives or stores a fact that something else
already holds — most of all the message: what will be sent is the stored draft's
own words, not a fresh composition that might differ from them. A second answer
to "what exactly will be sent" is the failure a fingerprint would then faithfully
certify.

The only derived answer is the last one, and it says so.

## Absence is an answer

**A missing fact is reported as missing.** A dossier that filled gaps would be
most confident exactly where it knows least, and the decision it informs is
whether to write to a real business.

So every answer carries `known`. `known=False` is not an error and not an empty
string; it is the state most of these facts are in for most prospects, and it is
usually the thing somebody has to go and do.

## Every answer is about the thing shown beside it

Two of these questions are about a specific artefact rather than about the
business. `approval` is about **the draft this dossier displays** — an older
approved message is not an approval of words written after it — and
`why_usable` is about **the address it displays**, so an address published on
the business's own page vouches for that address and for no other. Both were
once `bool(...)` over everything on file, and both then reported evidence for
something nobody had evidenced.

That extends to what each answer says *around* its fact. `evidence_moved_since`
is measured from the approval the answer is about, so where no approval covers
the draft on screen there is no window and nothing has moved since one — not a
window borrowed from an approval given to different words.

## It grows with the pipeline

Delivery, the Message-ID, a reply, a conversation, a proposal, a customer and a
payment all appear here as their own events occur — the first four because the
outreach record has those columns, the rest because "what happened afterwards"
is read from the business timeline, which is append-only and open to any factory
that writes to it. Nothing here needs editing when the first message is finally
sent. The `sent` answer starts saying yes.
"""

from __future__ import annotations

import json
from typing import Any

#: What each question is answered from, named so a reader can go and check.
#: Not decoration: a dossier whose fields cannot be traced is a summary, and a
#: summary is what somebody argues with once a claim turns out to be wrong.
OWNERS: dict[str, str] = {
    "who": "atlas_businesses",
    "why": "atlas_signals — the opportunity's own suggested action",
    "observed": "website_audited — what the audit actually saw",
    "evidence": "atlas_signals.evidence_fingerprints",
    "produced": "publication_completed + artefact_reviewed",
    "live": "publication_completed.url",
    "message": "atlas_outreach_messages.subject / body",
    "recipient": "atlas_outreach_messages.recipient, "
                 "else outreach.preparation.verified_recipient",
    "why_usable": "contact_observed — the page that published this address",
    "approval": "atlas_outreach_messages.approved_fingerprint "
                "— of the drafted message",
    "sent": "atlas_outreach_messages.status / sent_at / provider_message_id",
    "after": "atlas_business_events — the business's own timeline",
    "next": "derived from the answers above; owns nothing",
}


def _answer(known: bool, source: str, **detail: Any) -> dict:
    return {"known": known, "from": source, **detail}


def _age(stamp: str) -> int | None:
    """Whole days since an observation was made, or None if it does not say.

    `None`, never a large number: an audit with no timestamp is one whose age
    is unknown, and reporting that as very old is a claim about a record rather
    than a reading of it.
    """
    from datetime import UTC, datetime

    try:
        then = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=UTC)
    return max(0, (datetime.now(UTC) - then).days)


def _same_address(recorded: Any, shown: Any) -> bool:
    """Whether a provenance record is about the address the dossier displays.

    Case and surrounding space only — nothing that could make two different
    addresses match. `record_contactability` stores the address stripped and
    lowercased; a draft's recipient is whatever was written on it.
    """
    left, right = str(recorded or "").strip().lower(), str(shown or "").strip().lower()
    return bool(left) and left == right


def _detail(raw: Any) -> dict:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return {}
    return dict(raw) if raw else {}


def assemble(business_id: str, *, memory: Any, tenant: Any = None) -> dict:
    """The thirteen answers for one prospect, each read from its own owner."""
    from ..outreach.preparation import COMPOSABLE, verified_recipient
    from .tenancy import ALL_TENANTS

    # A company is shared; an opportunity belongs to a tenant. `save_business`
    # writes no tenant at all, so scoping the *business* here would find
    # nothing for anybody — the tenant gate is on the opportunity below, which
    # is the record that actually carries one, and it is what decides whether
    # this caller has a reason to be looking.
    business = memory.get_business(business_id, tenant=ALL_TENANTS)
    if business is None:
        return {"business_id": business_id, "known": False,
                "detail": "no business has that id"}

    answers: dict[str, dict] = {}

    # 1. Who they are.
    answers["who"] = _answer(
        True, OWNERS["who"], name=business.name,
        website=getattr(business, "website", "") or "",
        geography=getattr(business, "geography", "") or "",
        email=getattr(business, "email", "") or "",
        phone=getattr(business, "phone", "") or "")

    # 2. Why Qevik selected them — the opportunity's own words, in any state.
    #    The newest, with the count beside it: a prospect two detectors named
    #    separately is a prospect somebody must choose between, and choosing
    #    here would hide that there was a choice.
    signals = memory.signals_for(business_id, tenant=tenant)
    signal = signals[0] if signals else None
    if signal is None:
        answers["why"] = _answer(
            False, OWNERS["why"],
            detail="no opportunity names this business. Nothing has "
                   "established a reason to approach them.")
    else:
        action = ((signal.get("detail") or {}).get("actions") or [{}])[0]
        answers["why"] = _answer(
            True, OWNERS["why"], signal_id=signal.get("id"),
            kind=signal.get("kind"), state=signal.get("state"),
            statement=action.get("statement", ""),
            capability=action.get("capability", ""),
            needs_approval=signal.get("needs_approval"),
            score=signal.get("score"), detected_at=signal.get("detected_at"),
            others=max(0, len(signals) - 1))

    # 3. What Qevik observed. Counted three ways, never two: an observation
    #    nobody could complete is not an absence, and summing it into one would
    #    turn our own failure into a finding about their website.
    audit = memory.latest_audit(business_id)
    observations = audit.get("observations") or []
    if not observations:
        answers["observed"] = _answer(
            False, OWNERS["observed"],
            detail="no audit has recorded observations for this business. "
                   "That is not a finding about their site.")
    else:
        confirmed_absent = sum(1 for o in observations
                               if o.get("status") == "not_found")
        confirmed_present = sum(1 for o in observations
                                if o.get("status") == "present")
        answers["observed"] = _answer(
            True, OWNERS["observed"], checked=len(observations),
            confirmed_absent=confirmed_absent,
            confirmed_present=confirmed_present,
            not_verified=len(observations) - confirmed_absent - confirmed_present,
            url=audit.get("url", ""), audited_at=audit.get("audited_at", ""),
            # How the page was read, because it decides what an absence is
            # worth: a browser renders a phone number a plain fetch never sees.
            # Empty on every record written before the field existed, and that
            # stays unknown rather than being assumed to be either kind.
            read_by=audit.get("read_by", ""),
            recorded_at=audit.get("recorded_at", ""),
            # From the reading time when there is one, and from the write time
            # when there is not — 336 of the audits on file carry no reading
            # time. Which of the two it is, said out loud: a write time is an
            # upper bound on the age of the reading, not the age itself.
            days_old=_age(audit.get("audited_at")
                          or audit.get("recorded_at", "")),
            age_is=("when the page was read" if audit.get("audited_at")
                    else "when the record was written; this audit does not say "
                         "when the page was read"),
            observations=observations)

    # 4. What the claim rests on.
    fingerprints = list((signal or {}).get("evidence_fingerprints") or [])
    findings = memory.list_findings(business_id)
    answers["evidence"] = _answer(
        bool(fingerprints or findings), OWNERS["evidence"],
        fingerprints=fingerprints,
        findings=[{"kind": f.kind, "evidence": f.evidence} for f in findings],
        detail="" if (fingerprints or findings) else
        "the opportunity cites no evidence fingerprints and no findings are "
        "recorded. There is nothing here to show the business.")

    # 5–6. What was produced, and where it is.
    publications = memory.publications_of(business_id)
    live = publications[-1] if publications else None
    mission_id = (live or {}).get("mission_id", "")
    reviews = memory.reviews_for(mission_id) if mission_id else []
    answers["produced"] = _answer(
        bool(live), OWNERS["produced"],
        mission_id=mission_id, kind=(live or {}).get("kind", ""),
        # Unknown stays unknown. A health check reported as a website build is
        # a false statement to the business it is about.
        offer=(live or {}).get("offer", ""),
        # Where that came from. Four of Qevik's five publications record no
        # offer and it is recovered from the mission's recipe — as true, and
        # not from the same place, so the dossier says which.
        offer_from=(live or {}).get("offer_from", ""),
        # Whether a message can truthfully describe what is at that address.
        # Four of the five things Qevik has published record no offer, and
        # `prepare` refuses them — so telling an operator to write the message
        # would send them at a door the system holds shut.
        describable=(live or {}).get("offer", "") in COMPOSABLE,
        commit=(live or {}).get("commit", ""),
        published_at=(live or {}).get("at", ""),
        reviews=[{"decision": r["decision"], "actor": r["actor"],
                  "note": r["note"], "at": r["at"]} for r in reviews],
        # "accepted", the repository's own word. A near-miss here reads as
        # nobody having reviewed an artefact somebody accepted.
        accepted=any(r["decision"] == "accepted" for r in reviews),
        detail="" if live else "nothing has been produced for this business")
    answers["live"] = _answer(
        bool((live or {}).get("url")), OWNERS["live"],
        url=(live or {}).get("url", ""),
        others=max(0, len(publications) - 1),
        detail="" if live else "there is no live artefact to point anybody at")

    # 7–8. What will be sent, and to whom. Read from the draft, never composed:
    #      the words a person approved are the words that go out, and a second
    #      rendering of them here would be a second answer to one question.
    messages = memory.messages_for(business_id)
    latest = messages[-1] if messages else None
    if latest is None:
        answers["message"] = _answer(
            False, OWNERS["message"],
            detail="nothing has been drafted for this business. What would be "
                   "said is decided when a draft is prepared from a published "
                   "artefact, and is not guessed here.")
    else:
        answers["message"] = _answer(
            True, OWNERS["message"], id=latest.id, channel=latest.channel,
            subject=latest.subject, body=latest.body,
            status=latest.status.value, drafted_at=latest.created_at.isoformat(),
            mission_id=latest.mission_id or "", others=len(messages) - 1)

    verified, channel = verified_recipient(business)
    if latest is not None and latest.recipient:
        answers["recipient"] = _answer(
            True, OWNERS["recipient"], address=latest.recipient,
            channel=latest.channel, is_the_drafted_recipient=True,
            # Said out loud rather than assumed equal: a draft written before
            # the record carried an address would go to the old one.
            still_matches_the_record=(latest.recipient == verified))
    else:
        answers["recipient"] = _answer(
            bool(verified), OWNERS["recipient"], address=verified,
            channel=channel, is_the_drafted_recipient=False,
            detail="" if verified else
            "no verified way to reach this business. Qevik does not derive an "
            "address from a domain, and a landline is not a WhatsApp number.")

    # 9. Why *this* contact is considered usable — the page that published it.
    #    Provenance is per address, so it is matched against the address this
    #    dossier displays. A page that published one address is no evidence for
    #    a different, hand-entered one, and this is the single fact that
    #    justifies writing to a stranger at all.
    provenance = [_detail(row.get("detail"))
                  for row in memory.contact_provenance(business_id)]
    address = answers["recipient"].get("address", "")
    for_this = [p for p in provenance if _same_address(p.get("address"), address)]
    others = len(provenance) - len(for_this)
    answers["why_usable"] = _answer(
        bool(address and for_this), OWNERS["why_usable"],
        # Only the records that are about the address shown above. The rest are
        # counted, never shown as evidence for it.
        observations=for_this, other_addresses_observed=others,
        address=address,
        detail="" if (address and for_this) else
        ("this address was not read from their website — "
         + ("the address their site published is not this one. "
            if others == 1 else
            f"none of the {others} addresses their site published is this "
            "one. ")
         + "It came from whatever recorded it, or somebody entered it by "
           "hand, and that is not the same evidence."
         if address and others else
         "this address was not read from their website. It came from whatever "
         "recorded it, or somebody entered it by hand — and that is not the "
         "same evidence." if address else
         "no address has been read from this business's website"))

    # 10–11. Which approval authorises **the draft shown above**, and whether it
    #        actually went. The question is about those words, not about the
    #        business: an older approved message beside a newer unapproved draft
    #        would otherwise render the new words under "Approved, not sent",
    #        and an operator would read `approved` next to a sentence nobody
    #        approved.
    approved = [m for m in messages if m.approved_fingerprint]
    authorises = latest if (latest is not None
                            and latest.approved_fingerprint) else None
    sent = [m for m in messages if m.status.value == "sent"]
    # Whether the ground under those words has moved since they were written.
    # A fact, not a verdict: the message is still exactly what a person
    # approved, and whether a changed observation should stop a send is their
    # decision. Nothing here withdraws an approval. Measured from the approval
    # this answer is about, so the window belongs to the words on screen — and
    # when nothing approves those words there is no window at all. Falling back
    # to an earlier approval's moment would report, under an unapproved draft,
    # changes that happened before that draft was written.
    moved = memory.evidence_changes_since(
        business_id,
        authorises.created_at if authorises is not None else None)
    answers["approval"] = _answer(
        authorises is not None, OWNERS["approval"],
        # Which draft the answer is about, said out loud: the reader is looking
        # at `message`, and this is the claim made about that id.
        message_id=(latest.id if latest is not None else ""),
        evidence_moved_since=moved,
        approvals=[{"message_id": m.id, "fingerprint": m.approved_fingerprint,
                    "approval_id": m.approval_id or "",
                    # A positive marker, never inferred from status: every
                    # message predating automated sending was approved for a
                    # person to send by hand.
                    "authorises_automated_send":
                        m.authorized_automated_at is not None,
                    "status": m.status.value,
                    # The earlier approvals stay visible — they happened — but
                    # each says whether it is about the draft on screen.
                    "is_the_drafted_message":
                        latest is not None and m.id == latest.id}
                   for m in approved],
        superseded_approvals=max(0, len(approved) - (1 if authorises else 0)),
        detail="" if authorises is not None else
        (f"the draft shown here is not approved. {len(approved)} earlier "
         f"message{'' if len(approved) == 1 else 's'} to this business "
         "carried an approval, and that approval is not about these words."
         if approved else
         "nobody has approved a message to this business"))
    answers["sent"] = _answer(
        bool(sent), OWNERS["sent"],
        sent=[{"message_id": m.id,
               "at": m.sent_at.isoformat() if m.sent_at else "",
               "provider_message_id": m.provider_message_id or "",
               "recipient": m.recipient, "channel": m.channel} for m in sent],
        drafted_not_sent=len(messages) - len(sent),
        detail="" if sent else
        "nothing has ever been sent to this business")

    # 12. What happened afterwards — the timeline from the moment something
    #     went out. Read as a chronology rather than as named event kinds, so a
    #     reply, a conversation, a proposal, a customer or a payment appears
    #     here the moment whichever factory owns it writes one.
    answers["after"] = _after(memory, business_id, sent)

    # 13. Derived, and the only answer that is.
    answers["next"] = _next_action(answers)

    return {
        "business_id": business_id, "known": True, "answers": answers,
        "note": ("Every answer is read from the model named in its `from` "
                 "field. A fact that does not exist is reported as missing "
                 "rather than filled: the decision this informs is whether to "
                 "write to a real business."),
    }


def _after(memory: Any, business_id: str, sent: list) -> dict:
    """Everything on the timeline after the first thing Qevik sent them."""
    first_sent = min((m.sent_at for m in sent if m.sent_at), default=None)
    delivery = [{"message_id": m.id, "status": m.status.value,
                 "detail": m.detail or ""} for m in sent]
    if first_sent is None:
        return _answer(
            False, OWNERS["after"], since="", events=[], delivery=delivery,
            detail="nothing has been sent, so there is no afterwards. Anything "
                   "on their timeline happened before Qevik spoke to them.")
    later = [event for event in memory.timeline(business_id)
             if event.at and event.at > first_sent]
    return _answer(
        True, OWNERS["after"], since=first_sent.isoformat(),
        events=[{"kind": e.kind, "factory": e.factory, "actor": e.actor,
                 "at": e.at.isoformat() if e.at else ""} for e in later],
        delivery=delivery,
        detail="" if later else
        "it was sent and nothing has happened since — no bounce, no reply, "
        "nothing. Silence is not the same as a refusal.")


def _next_action(answers: dict) -> dict:
    """The one thing that would move this prospect forward.

    Derived, never stored, and it says so in its own `from`. It reads the
    answers above in the order the commercial chain actually runs and names the
    **first** thing that is not done, because a list of everything outstanding
    is a list nobody acts on.

    It never proposes sending. Sending is dispatched through the approval
    boundary that already exists, and a suggestion that reads as a button is the
    first step towards becoming one.
    """
    source = OWNERS["next"]

    def act(action: str, because: str) -> dict:
        return _answer(True, source, action=action, because=because)

    if not answers["why"]["known"]:
        return act("Nothing to do",
                   "no opportunity names this business, so there is no "
                   "evidenced reason to approach them")
    if not answers["observed"]["known"]:
        return act("Wait for the audit",
                   "nothing has been observed about their site, so there is "
                   "nothing to tell them and nothing to build from")
    if not answers["evidence"]["known"]:
        return act("Re-audit before acting",
                   "an opportunity exists but cites no evidence, and the "
                   "message would have nothing to show")
    if not answers["produced"]["known"]:
        return act("Approve the opportunity",
                   "the evidence is there and nothing has been produced yet")
    if not answers["produced"]["accepted"]:
        return act("Review the artefact",
                   "something was produced and nobody has accepted it")
    if not answers["recipient"]["known"]:
        return act("Find a way to reach them",
                   "there is a live artefact and no verified address or number "
                   "to tell anybody about it")
    if not answers["message"]["known"]:
        if not answers["produced"]["describable"]:
            offer = answers["produced"]["offer"]
            return act("Record what was published",
                       f"the publication says {offer or 'nothing'} about what "
                       "is at that address, so no message can describe it "
                       "truthfully and preparing one is refused")
        return act("Prepare the message",
                   "there is something to say and somebody to say it to, and "
                   "nothing has been drafted")
    if not answers["approval"]["known"]:
        return act("Review the draft",
                   "a message is written and nobody has decided about it")
    if not answers["sent"]["known"]:
        return act("Approved, not sent",
                   "somebody approved this and it has not gone. Sending is "
                   "dispatched through the approval boundary, not from here.")
    if not answers["after"].get("events"):
        return act("Wait",
                   "it was sent and nothing has come back yet")
    return act("Read what came back",
               "something happened on their timeline after Qevik wrote to them")


__all__ = ["OWNERS", "assemble"]
