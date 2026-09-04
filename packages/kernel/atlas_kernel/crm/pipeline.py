"""A CRM whose stages are derived, and whose next action carries its reason.

Every CRM ever built stores a stage on a record and asks a person to keep it
true. That is why every CRM is wrong: the field says `contacted` because
somebody clicked it, and nothing anywhere knows whether a message was actually
sent, to whom, or whether the address was real. The pipeline becomes a set of
opinions with a dashboard on top.

This one stores no stage. It *derives* one, per company, from things that
actually happened:

    the business record        it exists, and whether it has a reachable contact
    findings                   what an audit of its site actually established
    the opportunity            whether it was scored, and what it was scored at
    outreach messages          whether words were approved, and whether they left
    business events            the permanent, append-only timeline every factory
                               writes to — a site deployed, a reply received

So a stage cannot be stale, cannot be optimistic, and cannot be edited into
something the evidence does not support. If the pipeline says `contacted`, a
message row says `sent`.

## The part that is actually new

The valuable output is not the stage — it is `next_action`, and every action
carries **why**, in the evidence's own terms, and **what blocks it**:

    Ayoub's Clinic · qualified · next: find a contact address
      because  the audit found 4 issues and there is no email on file
      blocked  nothing — this is discovery work a worker can do now

    Al Noor Dental · approved · next: send the approved message
      because  a proposal was approved on 2026-08-30 and has not been sent
      blocked  PENDING_CREDENTIAL: no email channel is configured

That last line is why this is worth building here rather than buying one: the
blockers are the same blockers the agent floor draws, so a company sitting still
and an unseated desk are the same fact seen from two directions. A conventional
CRM would show `approved` and a human would wonder why nothing happened.

## What it deliberately does not do

It does not act. Nothing here sends, approves, schedules or writes — a
derivation that could also send is a derivation nobody can safely run twice.
The actions it names are proposals for the mission queue, which already has the
approval gate in front of anything irreversible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from ..opportunity.models import (
    Business,
    BusinessEvent,
    Finding,
    Opportunity,
    OutreachMessage,
    OutreachStatus,
)

#: After this long with nothing at all happening, a company is dormant rather
#: than in flight. Not a deletion and not a judgement — a company nobody has
#: touched in a month is not "in the pipeline" in any sense a person means it.
DORMANT_AFTER = timedelta(days=30)


class Stage(StrEnum):
    """Where a relationship actually stands.

    Ordered by how far it has got. Each one is defined by evidence, and the
    definition is in `stage_of` rather than in a comment, so it cannot drift.
    """

    #: Seen, and nothing looked at it yet.
    DISCOVERED = "discovered"
    #: An audit ran and established something about them.
    RESEARCHED = "researched"
    #: Scored, and worth pursuing.
    QUALIFIED = "qualified"
    #: A proposal exists, in words, awaiting a person.
    PROPOSED = "proposed"
    #: Those exact words were approved and have not left yet.
    APPROVED = "approved"
    #: Something was sent to them.
    CONTACTED = "contacted"
    #: They answered.
    REPLIED = "replied"
    #: They are paying, or we are delivering.
    CUSTOMER = "customer"
    #: Nothing has happened for a long time.
    DORMANT = "dormant"
    #: Deliberately stopped: they said no, or they were disqualified.
    CLOSED = "closed"


class ActionKind(StrEnum):
    """What to do next. Each maps to work the system can already do."""

    AUDIT = "audit"                    #: Look at their web presence.
    FIND_CONTACT = "find_contact"      #: Discover a reachable address.
    SCORE = "score"                    #: Qualify what the audit found.
    DRAFT = "draft"                    #: Write a proposal from the findings.
    REVIEW = "review"                  #: A person reads the words.
    SEND = "send"                      #: Deliver the approved words.
    FOLLOW_UP = "follow_up"            #: Chase a silence.
    RESPOND = "respond"                #: They replied; answer them.
    SERVE = "serve"                    #: They are a customer; do the work.
    NOTHING = "nothing"                #: Deliberately closed.


@dataclass(frozen=True)
class NextAction:
    """One thing to do, why it is the thing, and what stops it."""

    kind: ActionKind
    #: The instruction, in the words a person would use.
    summary: str
    #: The evidence this was derived from. Never a generic sentence: a reason
    #: that does not name a fact is a reason nobody can check.
    because: str
    #: Empty when the action can start now. Otherwise the same blocker
    #: vocabulary the agent floor uses, so one unlock clears both views.
    blocked_by: str = ""

    @property
    def blocked(self) -> bool:
        return bool(self.blocked_by)


@dataclass(frozen=True)
class Relationship:
    """One company, as the pipeline sees it."""

    business_id: str
    name: str
    stage: Stage
    next_action: NextAction
    #: What the stage was derived from, so a person can disagree with the
    #: derivation rather than with the number.
    because: str
    findings: int = 0
    severity: str = ""
    score: float | None = None
    last_activity: datetime | None = None
    contactable: bool = False
    events: int = 0
    labels: dict[str, Any] = field(default_factory=dict)


def _latest(events: list[BusinessEvent], messages: list[OutreachMessage],
            findings: list[Finding]) -> datetime | None:
    stamps = [e.at for e in events]
    stamps += [m.sent_at or m.created_at for m in messages if (m.sent_at or m.created_at)]
    stamps += [f.detected_at for f in findings if f.detected_at]
    return max(stamps) if stamps else None


def _replied(events: list[BusinessEvent]) -> BusinessEvent | None:
    """A reply is an event on the timeline, not a status somebody set."""
    for event in sorted(events, key=lambda e: e.at, reverse=True):
        if "repl" in event.kind or "inbound" in event.kind or "enquiry" in event.kind:
            return event
    return None


def _serving(events: list[BusinessEvent]) -> BusinessEvent | None:
    """Delivery is also an event: a site published for them, a payment taken."""
    for event in sorted(events, key=lambda e: e.at, reverse=True):
        if any(word in event.kind for word in ("published", "deployed", "paid",
                                               "subscribed", "delivered")):
            return event
    return None


def stage_of(business: Business, *, findings: list[Finding],
             opportunity: Opportunity | None, messages: list[OutreachMessage],
             events: list[BusinessEvent], now: datetime | None = None) -> tuple[Stage, str]:
    """The stage, and the sentence that justifies it.

    Read top down: the furthest thing that actually happened wins. Terminal
    states are checked first because a closed relationship is closed regardless
    of how much evidence sits behind it.
    """
    now = now or datetime.now(UTC)

    if opportunity is not None and opportunity.stage.value in {"lost", "disqualified"}:
        return Stage.CLOSED, f"the opportunity is {opportunity.stage.value}"

    served = _serving(events)
    if served is not None:
        return Stage.CUSTOMER, f"'{served.kind}' on {served.at:%Y-%m-%d}"

    replied = _replied(events)
    if replied is not None:
        return Stage.REPLIED, f"they answered — '{replied.kind}' on {replied.at:%Y-%m-%d}"

    sent = [m for m in messages if m.status is OutreachStatus.SENT]
    if sent:
        latest = max(sent, key=lambda m: m.sent_at or m.created_at)
        when = latest.sent_at or latest.created_at
        return Stage.CONTACTED, f"a message was sent on {when:%Y-%m-%d}"

    approved = [m for m in messages if m.status in
                (OutreachStatus.APPROVED, OutreachStatus.APPROVED_FOR_MANUAL_SEND)]
    if approved:
        return Stage.APPROVED, "words were approved and have not been sent"

    drafted = [m for m in messages if m.status in
               (OutreachStatus.DRAFT, OutreachStatus.AWAITING_APPROVAL)]
    if drafted:
        return Stage.PROPOSED, "a proposal exists and nobody has decided on it"

    if opportunity is not None:
        return Stage.QUALIFIED, f"scored {opportunity.score:g}"

    if findings:
        last = _latest(events, messages, findings)
        if last is not None and now - last > DORMANT_AFTER:
            return Stage.DORMANT, f"nothing has happened since {last:%Y-%m-%d}"
        return Stage.RESEARCHED, f"an audit found {len(findings)} issue(s)"

    last = _latest(events, messages, findings)
    if last is not None and now - last > DORMANT_AFTER:
        return Stage.DORMANT, f"nothing has happened since {last:%Y-%m-%d}"
    return Stage.DISCOVERED, "seen, and nothing has looked at it yet"


def next_action(stage: Stage, business: Business, *, findings: list[Finding],
                opportunity: Opportunity | None, messages: list[OutreachMessage],
                channels_ready: frozenset[str] = frozenset()) -> NextAction:
    """What to do about this company, why, and what stops it.

    `channels_ready` is passed in rather than read: whether email is configured
    is a deployment fact, and a pipeline that goes and looks is a pipeline that
    behaves differently in a test than in production.
    """
    contactable = bool(business.email or business.phone)

    if stage is Stage.CLOSED:
        return NextAction(ActionKind.NOTHING, "leave it",
                          because="the opportunity is closed")

    if stage is Stage.CUSTOMER:
        return NextAction(ActionKind.SERVE, "do the work they are paying for",
                          because="they are being delivered to")

    if stage is Stage.REPLIED:
        return NextAction(ActionKind.RESPOND, "answer them",
                          because="they replied and nobody has answered")

    if stage is Stage.CONTACTED:
        return NextAction(ActionKind.FOLLOW_UP, "wait, then follow up once",
                          because="a message was delivered and there is no reply yet")

    if stage is Stage.APPROVED:
        if not contactable:
            return NextAction(
                ActionKind.FIND_CONTACT, "find an address before sending",
                because="the words are approved but there is nobody to send them to",
                blocked_by="")
        if "email" not in channels_ready:
            return NextAction(
                ActionKind.SEND, "send the approved message",
                because="a proposal was approved and has not been sent",
                blocked_by="PENDING_CREDENTIAL")
        return NextAction(ActionKind.SEND, "send the approved message",
                          because="a proposal was approved and has not been sent")

    if stage is Stage.PROPOSED:
        return NextAction(ActionKind.REVIEW, "read the draft and decide",
                          because="a draft exists and nobody has approved or rejected it")

    if stage is Stage.QUALIFIED:
        if not contactable:
            return NextAction(
                ActionKind.FIND_CONTACT, "find a contact address",
                because=(f"scored {opportunity.score:g} with {len(findings)} finding(s), "
                         "and there is no address on file"
                         if opportunity else "no address on file"))
        return NextAction(ActionKind.DRAFT, "draft a proposal from the findings",
                          because=(f"scored {opportunity.score:g} and reachable"
                                   if opportunity else "qualified and reachable"))

    if stage is Stage.RESEARCHED:
        return NextAction(ActionKind.SCORE, "score what the audit found",
                          because=f"{len(findings)} finding(s) and no opportunity yet")

    if stage is Stage.DORMANT:
        return NextAction(ActionKind.AUDIT, "look again, or close it",
                          because="nothing has happened for a month")

    return NextAction(ActionKind.AUDIT, "audit their web presence",
                      because="nothing is known about them yet")


def relationship(business: Business, *, findings: list[Finding] | None = None,
                 opportunity: Opportunity | None = None,
                 messages: list[OutreachMessage] | None = None,
                 events: list[BusinessEvent] | None = None,
                 channels_ready: frozenset[str] = frozenset(),
                 now: datetime | None = None) -> Relationship:
    """One company's whole pipeline position, derived."""
    findings = findings or []
    messages = messages or []
    events = events or []

    stage, because = stage_of(business, findings=findings, opportunity=opportunity,
                              messages=messages, events=events, now=now)
    action = next_action(stage, business, findings=findings, opportunity=opportunity,
                         messages=messages, channels_ready=channels_ready)

    worst = ""
    if findings:
        order = {"high": 3, "medium": 2, "low": 1}
        worst = max((f.severity.value for f in findings), key=lambda s: order.get(s, 0))

    return Relationship(
        business_id=business.id,
        name=business.name,
        stage=stage,
        next_action=action,
        because=because,
        findings=len(findings),
        severity=worst,
        score=opportunity.score if opportunity else None,
        last_activity=_latest(events, messages, findings),
        contactable=bool(business.email or business.phone),
        events=len(events),
    )


def board(relationships: list[Relationship]) -> dict[str, Any]:
    """The pipeline as a board, plus what is standing in its way.

    Counts per stage are the least interesting part. The two lists after them
    are the point: what can be started right now, and what cannot be started at
    all until something is obtained — grouped by the blocker, because that is
    the unit of work a person actually does about it.
    """
    stages: dict[str, int] = {stage.value: 0 for stage in Stage}
    for r in relationships:
        stages[r.stage.value] += 1

    actionable = [r for r in relationships
                  if not r.next_action.blocked and r.next_action.kind is not ActionKind.NOTHING]
    blocked: dict[str, list[str]] = {}
    for r in relationships:
        if r.next_action.blocked:
            blocked.setdefault(r.next_action.blocked_by, []).append(r.business_id)

    by_kind: dict[str, int] = {}
    for r in actionable:
        by_kind[r.next_action.kind.value] = by_kind.get(r.next_action.kind.value, 0) + 1

    return {
        "total": len(relationships),
        "stages": stages,
        "actionable": len(actionable),
        "actionable_by_kind": dict(sorted(by_kind.items(), key=lambda kv: -kv[1])),
        "blocked_on": [
            {"blocker": blocker, "companies": len(ids), "examples": sorted(ids)[:5]}
            for blocker, ids in sorted(blocked.items(), key=lambda kv: -len(kv[1]))
        ],
        # Named so a caller cannot mistake "nothing to do" for "nothing known".
        "detail": ("derived from findings, opportunities, outreach and the business "
                   "timeline; no stage is stored anywhere"),
    }
