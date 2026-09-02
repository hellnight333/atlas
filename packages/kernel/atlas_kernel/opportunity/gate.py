"""The one place a person is asked before Atlas contacts a stranger.

Same shape as the Media Factory's publish gate, and deliberately so — it reuses
``atlas_kernel.approval`` rather than growing a second approval system beside it.

**The approval is on the outcome:** this business, these words, this channel. The
approver is not asked to authorise detector runs, scoring, or proposal
generation. Those are Atlas's problem, and asking would be asking someone to
audit an internal plan they have no way to evaluate.

**The approval binds to a fingerprint.** What is recorded is not "someone
approved this message" but "someone approved *these exact words resting on these
exact facts*". Re-run a detector, edit a paragraph, change the offer, and the
fingerprint moves — at which point the send is refused rather than quietly
delivering something no human read. That is the difference between consent to a
particular thing and a standing permission to contact someone.

**Both directions bind, and each by what it has.** ``authorise`` proves the
approval describes the message by re-deriving the fingerprint. ``reject`` has no
fingerprint to work with — a refusal says nothing about a body of text — so it
proves the same thing through an identifier, and through nothing weaker. An
unbound rejection closes somebody else's message with a decision nobody took
about it, and leaves the refused one looking like an open question.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..approval.events import ApprovalCancelled, ApprovalExpired, ApprovalRejected
from ..approval.models import (
    TERMINAL_APPROVAL_STATES,
    ApprovalContext,
    ApprovalRequest,
    ApprovalScope,
    ApprovalState,
)
from ..approval.service import ApprovalError, ApprovalService
from .models import (
    Business,
    Finding,
    OutreachMessage,
    OutreachStatus,
    Proposal,
)

#: Stored on the approval so the check at send time compares like with like.
PROPOSAL_FINGERPRINT = "proposal_fingerprint"

#: What the policy engine sees. Named so a policy can require a second approver
#: for outreach specifically, without this file knowing such a policy exists.
OUTREACH_ACTION = "opportunity.outreach.send"

#: Which message ``request`` was raised about, recorded on the approval itself.
#:
#: The mirror of the ``approval_id`` the service writes onto the row, and it
#: exists because the two ends can be out of step: a caller holding a copy of the
#: row taken before the question was put carries no ``approval_id``, and then
#: this is the only thing that says which row a refusal closes.
#:
#: An identifier, and never a description. The business, proposal, recipient and
#: channel are recorded beside it as context for whoever reads the approval;
#: ``_must_describe`` has the argument for why they are not a binding.
BOUND_MESSAGE = "message_id"

#: Terminal approval states that foreclose the send, and what each is recorded
#: as on the message.
#:
#: Three entries rather than one line of prose, because they are not the same
#: event. A person refusing, a request being cancelled, and a request nobody
#: answered before it expired all stop the send, but only the first is a
#: decision somebody took — and "rejected by approver" written onto an expiry
#: puts words in the mouth of a person who never spoke.
#:
#: ``APPROVED`` is deliberately absent. It is terminal for the approval and not
#: for the message: marking a message approved is ``authorise``'s act, because
#: only ``authorise`` re-derives the fingerprint first.
FORECLOSED: dict[ApprovalState, str] = {
    ApprovalState.REJECTED: "rejected by approver",
    ApprovalState.CANCELLED: "the approval request was cancelled before anybody decided",
    ApprovalState.EXPIRED: "the approval request expired with nobody having answered it",
}

#: Why a request this gate raised was taken back before anybody answered it.
#:
#: Recorded as the cancellation comment, because the state alone cannot say it.
#: A request an operator cancelled and one withdrawn because the message could
#: not record that it was raised are both ``CANCELLED``, and only this separates
#: them for whoever reads the history afterwards.
WITHDRAWN = "withdrawn: the message could not record that this question was raised"


class OutreachNotApproved(RuntimeError):
    """The message was not cleared to send."""


@dataclass
class OutreachOutcome:
    """Exactly what a person is being asked to approve.

    Carries the findings as well as the message. An approver who cannot see what
    the claims rest on is being asked to trust the generator, and the entire
    point of the evidence invariant is that they should not have to.
    """

    business: Business
    proposal: Proposal
    findings: list[Finding]
    channel: str
    recipient: str
    #: The row these words were written to. Not part of what a person is asked —
    #: nobody approves a database id — but recorded on the request so a decision
    #: arriving later can be shown to be about *this* row and no other.
    #:
    #: Empty is a real value and the safe one: an outcome assembled without a
    #: stored message asks the same question, and the refusal it earns can only
    #: close a row that names the request back.
    message_id: str = ""

    @property
    def fingerprint(self) -> str:
        return self.proposal.fingerprint

    def summary(self) -> dict[str, Any]:
        return {
            "business": self.business.name,
            "recipient": self.recipient,
            "channel": self.channel,
            "subject": self.proposal.subject,
            "claims": len(self.proposal.claims),
            "evidence": [
                {
                    "statement": finding.statement,
                    "observed": [item.summary for item in finding.evidence],
                }
                for finding in self.findings
            ],
        }


class OutreachGate:
    """Requests approval, and converts an approval into a sendable message."""

    def __init__(self, approvals: ApprovalService) -> None:
        self._approvals = approvals

    def request(self, outcome: OutreachOutcome, *, requested_by: str = "atlas") -> ApprovalRequest:
        """Ask a human. Nothing is sent by this call.

        The evidence goes in the payload rather than only the summary line: an
        approver who cannot see what the claims rest on is being asked to trust
        the generator, and the evidence invariant exists so they do not have to.
        """
        context = ApprovalContext(
            action=OUTREACH_ACTION,
            scopes=[ApprovalScope.EXTERNAL_API, ApprovalScope.NETWORK],
            requested_by=requested_by,
            payload=outcome.summary(),
        )
        return self._approvals.create_request(
            title=f"Contact {outcome.business.name}",
            context=context,
            metadata={
                PROPOSAL_FINGERPRINT: outcome.fingerprint,
                BOUND_MESSAGE: outcome.message_id,
                "business_id": outcome.business.id,
                "proposal_id": outcome.proposal.id,
                "recipient": outcome.recipient,
                "channel": outcome.channel,
            },
        )

    def withdraw(self, request: ApprovalRequest, *, actor: str = "atlas") -> ApprovalRequest:
        """Take back a request whose claim on the message was never recorded.

        ``request`` creates a live question the moment it returns, and the caller
        then has to write onto the row that it was raised. Those are two writes
        to two stores and the second can fail — at which point the question is
        real, somebody will be shown it, and nothing points at it from the other
        end.

        Cancelled rather than deleted: the request happened, the approval log is
        append-only, and ``FORECLOSED`` already reads ``CANCELLED`` as "cancelled
        before anybody decided", which is exactly what this is. ``WITHDRAWN`` is
        what distinguishes it from a person cancelling.

        **A request somebody answered in between is left exactly as they left
        it.** This is reached from a failure path — the row could not record
        that the question was raised — and a decision landing inside that same
        window is not a second failure to report. There is nothing left to take
        back: the answer is terminal, the write-back has already closed the row
        through ``BOUND_MESSAGE``, and cancelling would raise ``ApprovalError``
        over the top of whatever failure sent us here, replacing an accurate
        account of what went wrong with "already rejected". An answered question
        is still never quietly withdrawn — it is not withdrawn at all.

        The request as it now stands is returned either way, so the caller can
        say which of the two happened. Everything else ``cancel`` refuses — an
        unknown id, a request still pending — raises, because neither is this
        race.
        """
        try:
            return self._approvals.cancel(request.id, actor=actor, comment=WITHDRAWN)
        except ApprovalError:
            answered = self._approvals.get(request.id)
            if answered is None or answered.state not in TERMINAL_APPROVAL_STATES:
                raise
            return answered

    def on_foreclosed(
        self, handler: Callable[[ApprovalRequest, str], None]
    ) -> bool:
        """Call ``handler`` whenever an outreach approval is closed against a send.

        This is the seam onto the path production actually takes. Nothing decides
        an outreach approval by calling back into this package: the customer
        endpoint calls ``ApprovalService.reject`` directly, the kernel API calls
        ``reject``/``cancel``, and ``expire_due`` sweeps requests nobody answered
        — and every one of those publishes on the approval service's own event
        bus. Subscribing there is what makes a write-back reachable from all
        three at once; a method the endpoints would have to remember to call is
        one they demonstrably do not.

        Narrowed to this gate's own action, because the bus carries every
        approval in Atlas — a media publication, a credit spend, a roadmap
        decision — and handing those to an outreach write-back would ask it about
        requests that never named a message.

        That narrowing is **routing, and never authority.** ``action`` and
        ``metadata`` are whatever created the request supplied, and
        ``POST /approvals`` takes both from its caller — so a request wearing this
        action shows only that this subscriber is the right one to hand it to. It
        is no evidence that this gate raised it, and none at all that the message
        its metadata names was ever asked about. What a decision may actually
        close is settled against the stored row: ``_must_describe`` here, and
        ``OpportunityService._message_asked_about`` there.

        ``APPROVED`` is not delivered. The way a yes reaches a message is
        ``authorise``, which re-derives the fingerprint first, and a second door
        onto ``APPROVED`` that skips that check is a door onto sending words
        nobody read.

        Returns whether a subscription was made, so a caller wired to an approval
        service with no bus — a test double, most of them — can tell the
        difference between "watching" and "silently not watching".
        """
        bus = getattr(self._approvals, "event_bus", None)
        if bus is None:
            return False

        def deliver(event: Any) -> None:
            approval_id = str(getattr(event, "approval_id", "") or "")
            if not approval_id:
                return
            request = self._approvals.get(approval_id)
            if request is None or request.action != OUTREACH_ACTION:
                return
            if request.state not in FORECLOSED:
                return
            # The actor comes off the event rather than out of the decision list:
            # the event is what the endpoint published, and an expiry has no
            # actor at all, which the empty string says plainly.
            handler(request, str(getattr(event, "actor", "") or ""))

        for event_type in (ApprovalRejected, ApprovalCancelled, ApprovalExpired):
            bus.subscribe(event_type, deliver)
        return True

    def authorise(
        self,
        message: OutreachMessage,
        approval: ApprovalRequest,
        proposal: Proposal,
    ) -> OutreachMessage:
        """Turn an approved request into a message that may be sent.

        Re-derives the fingerprint from the proposal as it stands *now* and
        compares it against the one recorded when approval was requested. A
        mismatch means the thing approved is not the thing that would be sent,
        and the only safe answer is no.
        """
        if approval.state is not ApprovalState.APPROVED:
            raise OutreachNotApproved(
                f"approval {approval.id} is {approval.state.value}; nothing sends without a yes"
            )

        recorded = approval.metadata.get(PROPOSAL_FINGERPRINT)
        if not recorded:
            raise OutreachNotApproved(
                f"approval {approval.id} records no proposal fingerprint, so it cannot "
                "be shown to describe this message"
            )

        current = proposal.fingerprint
        if recorded != current:
            raise OutreachNotApproved(
                f"the proposal changed after approval (approved {recorded}, now {current}); "
                "re-request approval for the new version"
            )

        return message.model_copy(
            update={
                "status": OutreachStatus.APPROVED,
                "approval_id": approval.id,
                "approved_fingerprint": current,
                # This gate is where a person authorises *Qevik* to deliver, as
                # distinct from approving words they will send themselves. The
                # marker is written here and nowhere else, so "may a machine
                # send this" has one origin and is never inferred from a status
                # that meant something different when it was recorded.
                "authorized_automated_at": datetime.now(UTC),
            }
        )

    def reject(self, message: OutreachMessage, approval: ApprovalRequest) -> OutreachMessage:
        """Close the message against an approval that forecloses the send.

        The counterpart to ``authorise``, and it takes the reason from the
        approval's own state rather than asserting one — ``FORECLOSED`` says why
        that distinction is worth three entries.

        Refuses a request nobody has decided yet, because writing ``REJECTED``
        on a pending approval would answer on the approver's behalf, which is the
        exact thing this gate exists to prevent. Refuses an approved one too: the
        way to record a yes is ``authorise``.
        """
        if approval.state is ApprovalState.APPROVED:
            raise OutreachNotApproved(
                f"approval {approval.id} is approved; record that with authorise, "
                "which re-checks the fingerprint, not with a refusal"
            )
        if approval.state not in FORECLOSED:
            raise OutreachNotApproved(
                f"approval {approval.id} is {approval.state.value}; nobody has decided "
                "it, and closing the message now would answer for the approver"
            )

        self._must_describe(message, approval)

        return message.model_copy(
            update={
                "status": OutreachStatus.REJECTED,
                "approval_id": approval.id,
                "detail": FORECLOSED[approval.state],
            }
        )

    @staticmethod
    def _must_describe(message: OutreachMessage, approval: ApprovalRequest) -> None:
        """Refuse an approval that cannot be shown to be about *these* words.

        ``authorise`` gets this for nothing: it re-derives the proposal
        fingerprint and refuses a mismatch. A refusal has no fingerprint to
        compare against, so the binding has to be established directly or
        ``reject`` stamps whichever approval it is handed onto whichever message
        it is handed.

        Closing the wrong row is not a small error. The message it closes leaves
        the review queue carrying a decision nobody took about it, and the
        message somebody actually refused stays in the queue looking like an open
        question — so the same person is asked again about words they have
        already said no to.

        Two ways to establish it, and both are **identifiers**. ``approval_id``
        is the message's own record of which question it was raised under.
        ``BOUND_MESSAGE`` is the same link written from the other end, and it
        covers the case the first cannot: a caller holding a copy of the row from
        before the question was put has no ``approval_id`` on it, and the request
        still knows which row it named. Either settles the matter alone, because
        each names exactly one thing. Absent both, the answer is no.

        What is deliberately **not** a link is a description of the artefact.
        Business, proposal, recipient and channel together look like they pick out
        one message and they do not: ``infra/outreach_drafts.py`` writes a
        WhatsApp draft and an email draft from one proposal, and a draft rewritten
        after a typo keeps all four and differs only in its id and its words. Two
        live rows can therefore carry an identical four, and a refusal raised
        about one of them would be accepted for the other — which is the
        wrong-row closure this guard exists to prevent, arrived at through the
        guard itself. The four stay on the approval, where they tell a reader
        what was asked about; they are not evidence of which row was asked about.
        """
        named = message.approval_id
        if named:
            if named != approval.id:
                raise OutreachNotApproved(
                    f"message {message.id} was raised under approval {named}, not "
                    f"{approval.id}; deciding one request does not close a message "
                    "somebody asked about separately"
                )
            return

        raised_about = str(approval.metadata.get(BOUND_MESSAGE) or "")
        if not raised_about:
            raise OutreachNotApproved(
                f"message {message.id} names no approval and approval {approval.id} "
                "names no message; nothing ties the two together, and a refusal has "
                "no fingerprint that could"
            )
        if raised_about != message.id:
            raise OutreachNotApproved(
                f"approval {approval.id} was raised about message {raised_about}, "
                f"not {message.id}; deciding one request does not close a message "
                "somebody asked about separately"
            )
